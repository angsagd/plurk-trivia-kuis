"""Tes tahap 3: mesin thread (hold/active/die), outbox, FakePlurk, dan ketahanan."""

import math
import random
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.bank_soal import impor_topik
from app.bot import engine as mesin
from app.bot.outbox import Pengirim
from app.bot.pengaturan import muat_pengaturan
from app.bot.simulator import PemainSim, putaran
from app.bot.tick import jalankan_tick
from app.clock import WIB, FakeClock
from app.db import sesi_db
from app.models import BotState, GameSession, Outbox, Question, Response, Score, SessionQuestion, Setting
from app.plurk.client import AntiFlood, TokenDitolak, tautan_plurk
from app.plurk.fake import BOT, Crash, FakePlurk

SENIN = datetime(2026, 11, 30, tzinfo=WIB)  # Senin, hari aktif
ANDI, BUDI, CITRA = (9001, "andi"), (9002, "budi"), (9003, "citra")


def jam(h, m=0, s=0, hari=SENIN):
    return hari.replace(hour=h, minute=m, second=s)


def bank_karangan(n: int) -> str:
    """n soal karangan; jawaban unik 7 huruf (JAWABAA, JAWABAB, ...), tidak saling bocor."""
    baris = []
    for i in range(n):
        akhir = chr(65 + i // 26) + chr(65 + i % 26)
        baris.append(f"Soal karangan nomor {i + 1}?|Petunjuk karangan nomor {i + 1}|JAWAB{akhir}")
    return "\n".join(baris)


class Harness:
    def __init__(self, engine, mulai: datetime, soal: int = 30):
        self.engine = engine
        self.clock = FakeClock(mulai)
        self.fake = FakePlurk(self.clock)
        self.rng = random.Random(1)
        with sesi_db(engine) as db:
            impor_topik(db, "trivia_01_karangan.txt", bank_karangan(soal), mulai)
            db.get_one(BotState, 1).status = "aktif"

    # ---------------------------------------------------------- menjalankan
    def tick(self, n: int = 1) -> None:
        for _ in range(n):
            jalankan_tick(
                self.clock.now(), self.engine, self.fake, clock=self.clock, tidur=lambda _: None, rng=self.rng
            )
            self.clock.advance(minutes=1)

    def tick_sampai(self, waktu: datetime) -> None:
        while self.clock.now() <= waktu:
            self.tick()

    def atur(self, **nilai) -> None:
        with sesi_db(self.engine) as db:
            for k, v in nilai.items():
                db.merge(Setting(key=k, value=v, updated_at=self.clock.now()))

    def status_bot(self, nilai: str) -> None:
        with sesi_db(self.engine) as db:
            db.get_one(BotState, 1).status = nilai

    # ---------------------------------------------------------- membaca
    def sesi(self, sesi_id: int | None = None) -> GameSession:
        with sesi_db(self.engine) as db:
            q = select(GameSession).order_by(GameSession.id)
            semua = db.scalars(q).all()
            s = db.get(GameSession, sesi_id) if sesi_id else (semua[-1] if semua else None)
            assert s is not None, "belum ada sesi"
            return s

    def jumlah_sesi(self) -> int:
        with sesi_db(self.engine) as db:
            return db.scalar(select(func.count()).select_from(GameSession)) or 0

    def posting_bot(self, sesi_id: int | None = None) -> list[str]:
        s = self.sesi(sesi_id)
        assert s.plurk_id is not None
        return [r.content for r in self.fake.semua_balasan(s.plurk_id) if r.user_id == BOT.id]

    def jawaban_sekarang(self, sesi_id: int | None = None) -> str:
        s = self.sesi(sesi_id)
        with sesi_db(self.engine) as db:
            sq = db.scalar(
                select(SessionQuestion).where(
                    SessionQuestion.session_id == s.id, SessionQuestion.number == s.question_count
                )
            )
            assert sq is not None
            return sq.question.jawaban

    # ---------------------------------------------------------- pemain
    def balas(self, pemain, teks: str, posted: datetime | None = None, sesi_id: int | None = None) -> int:
        s = self.sesi(sesi_id)
        assert s.plurk_id is not None
        waktu = posted or self.clock.now() - timedelta(seconds=30)  # di antara tick terakhir dan berikutnya
        return self.fake.inject_response(s.plurk_id, pemain[0], pemain[1], teks, waktu)


@pytest.fixture
def h(engine):
    return Harness(engine, jam(11, 59))


def buka_dan_aktifkan(h: Harness) -> None:
    """11:59 kosong, 12:00 01+02, 12:01 03; balasan 'siap' -> 12:02 active + 04."""
    h.tick(3)
    h.balas(ANDI, "siap!")
    h.tick()
    assert h.sesi().status == "active" and h.posting_bot()[-1] == "Siap-siap, soal #1…"


# ====================================================================== jadwal


@pytest.mark.parametrize(
    "waktu", [jam(12, hari=SENIN + timedelta(1)), jam(12, hari=SENIN + timedelta(4)), jam(22, 30)]
)
def test_tidak_ada_sesi_selasa_jumat_dan_2230(engine, waktu):
    h = Harness(engine, waktu)
    h.tick(3)
    assert h.jumlah_sesi() == 0


def test_status_berhenti_tidak_membuka_sesi(h):
    h.status_bot("berhenti")
    h.tick(3)
    assert h.jumlah_sesi() == 0


def test_status_jeda_tidak_membuka_sesi_baru_tapi_thread_berjalan_lanjut(h):
    buka_dan_aktifkan(h)
    h.status_bot("jeda")
    h.tick()  # 12:03 soal #1 tetap keluar
    assert h.posting_bot()[-1].startswith("❓ Soal #1")
    h.atur(jam_sesi=["12:00", "12:05"])
    h.tick_sampai(jam(12, 10))
    assert h.jumlah_sesi() == 1


def test_tick_terlewat_masih_membuka_sesi_dalam_toleransi(engine):
    h = Harness(engine, jam(12, 3))
    h.tick()
    assert h.jumlah_sesi() == 1 and h.sesi().slot == 1


# ====================================================================== hold


def test_buka_sesi_rangkaian_01_02_03(h):
    h.tick(2)  # 11:59, 12:00 -> 01 + 02 (jatah 2 posting per tick)
    s = h.sesi()
    assert s.status == "hold" and s.posted_at == jam(12)
    isi = h.fake.plurk(s.plurk_id)
    assert isi is not None and "Senin, 30 November 2026 · Sesi 1 (12.00 WIB)" in isi[0]
    assert h.posting_bot() == ["🏆 Minggu baru dimulai, papan skor masih kosong. Ayo jadi yang pertama!"]
    h.tick()  # 12:01 -> 03
    assert h.posting_bot()[-1] == "Katakan sesuatu jika Anda siap."
    with sesi_db(h.engine) as db:
        assert db.scalar(select(func.count()).select_from(SessionQuestion)) == 10


def test_thread_tanpa_balasan_60_menit_die_hanya_farewell(h):
    h.tick_sampai(jam(12, 59))
    assert h.sesi().status == "hold"
    h.tick()  # 13:00: umur 60 menit
    s = h.sesi()
    assert s.status == "die" and s.question_count == 0
    posting = h.posting_bot()
    assert posting[-1] == "Terima kasih sudah bermain! Sesi berikutnya: hari ini 14.00 WIB."
    assert not any("Peringkat" in p for p in posting)


def test_balasan_59_50_diperiksa_setelah_menit_60_tetap_aktif(h):
    h.tick_sampai(jam(12, 58))
    h.clock.set(jam(13, 1))  # bot terlambat memeriksa (tick 12:59 & 13:00 terlewat)
    h.balas(BUDI, "wkwk", posted=jam(12, 59, 50))
    h.tick()
    assert h.sesi().status == "active" and h.posting_bot()[-1] == "Siap-siap, soal #1…"


def test_balasan_setelah_menit_60_tidak_menghidupkan(h):
    h.tick_sampai(jam(12, 58))
    h.clock.set(jam(13, 1))
    h.balas(BUDI, "telat", posted=jam(13, 0, 10))
    h.tick()
    assert h.sesi().status == "die"


def test_balasan_pemain_diblokir_tidak_mengaktifkan(h):
    from app.models import Player

    with sesi_db(h.engine) as db:
        db.add(Player(plurk_user_id=CITRA[0], nick=CITRA[1], is_blocked=True, first_seen=h.clock.now()))
    h.tick(3)
    h.balas(CITRA, "siap")
    h.tick()
    assert h.sesi().status == "hold"


# ====================================================================== active


def test_alur_soal_pemenang_skor_dan_lanjut_soal_berikutnya(h):
    buka_dan_aktifkan(h)
    h.tick()  # 12:03 soal #1
    jawaban = h.jawaban_sekarang()
    assert h.posting_bot()[-1].startswith("❓ Soal #1: Soal karangan nomor ")
    h.balas(CITRA, "salah dulu")
    h.tick()  # 12:04 clue 1
    assert h.posting_bot()[-1].startswith("💡 Clue 1: Petunjuk karangan")
    id_budi = h.balas(BUDI, f"jawabannya {jawaban.lower()} dong!")
    h.balas(ANDI, jawaban)
    h.tick()  # 12:05 pemenang + 04 soal #2 (ada balasan di siklus ini)
    poin = math.ceil(7 / 2)
    assert h.posting_bot()[-2:] == [
        f"✅ budi benar! Jawabannya {jawaban}. +{poin} poin.",
        "Siap-siap, soal #2…",
    ]
    with sesi_db(h.engine) as db:
        skor = db.scalars(select(Score)).all()
        assert len(skor) == 1 and skor[0].points == poin
        assert skor[0].play_date == date(2026, 11, 30) and skor[0].week_start == date(2026, 11, 25)
        status = dict(db.execute(select(Response.plurk_response_id, Response.status)).all())
        assert status[id_budi] == "benar"
        assert sorted(s for s in status.values() if s) == ["benar", "di_luar_soal", "salah"]
        sq = db.scalar(select(SessionQuestion).where(SessionQuestion.number == 1))
        assert sq.winner_phase == 1 and sq.winner_response_id == id_budi and len(sq.marker_ids) == 2


def test_status_balasan_lewat_batas_dan_terlalu_panjang(h):
    buka_dan_aktifkan(h)
    h.tick()  # soal #1
    ids = [h.balas(ANDI, t) for t in ["a", "b" * 41, "c", "d"]]
    h.tick()
    with sesi_db(h.engine) as db:
        status = dict(db.execute(select(Response.plurk_response_id, Response.status)).all())
    assert [status[i] for i in ids] == ["salah", "terlalu_panjang", "salah", "lewat_batas"]


def test_siklus_tanpa_balasan_jawaban_dibuka_lalu_hold(h):
    buka_dan_aktifkan(h)
    h.tick(5)  # 12:03 soal, 12:04-12:06 clue 1-3, 12:07 buka jawaban + menunggu
    posting = h.posting_bot()
    jawaban = h.jawaban_sekarang()
    assert posting[-3].startswith("💡 Clue 3: J")
    assert posting[-2:] == [
        f"⌛ Belum ada yang benar. Jawabannya: {jawaban}",
        "Kuis menunggu peserta. Katakan sesuatu jika Anda siap.",
    ]
    s = h.sesi()
    assert s.status == "hold" and s.question_count == 1
    with sesi_db(h.engine) as db:
        tampil = db.scalar(select(Question).where(Question.jawaban == jawaban))
        assert tampil.used_cycle == 1 and tampil.times_used == 1
        belum = db.scalars(select(Question).where(Question.used_cycle == 0)).all()
        assert len(belum) == 29  # soal yang belum tampil kembali ke bank
    h.balas(BUDI, "ayo lagi")
    h.tick()
    assert h.sesi().status == "active" and h.posting_bot()[-1] == "Siap-siap, soal #2…"


def test_clue_2_dan_3_memakai_karakter_pengganti(h):
    h.atur(karakter_pengganti="＿")
    buka_dan_aktifkan(h)
    h.tick(4)  # soal, clue1, clue2, clue3
    jawaban = h.jawaban_sekarang()
    assert h.posting_bot()[-2:] == [
        "💡 Clue 2: 7 huruf: ＿＿＿＿＿＿＿",
        f"💡 Clue 3: J＿＿＿＿＿{jawaban[-1]}",
    ]


def test_karakter_lama_yang_tidak_didukung_kembali_ke_bawaan(h):
    h.atur(karakter_pengganti="-", pemisah_kata="|")
    with sesi_db(h.engine) as db:
        p = muat_pengaturan(db)
    assert (p.karakter_pengganti, p.pemisah_kata) == ("=", " ")


def main_sampai_selesai(
    h: Harness,
    sesi_id: int | None = None,
    benar_di_fase: int = 2,
    diam: tuple[datetime, datetime] | None = None,
    sampai: datetime | None = None,
    batas: int = 300,
) -> None:
    """Pemain membalas setiap tick (kecuali selama rentang `diam`); jawaban benar di fase tertentu."""
    for _ in range(batas):
        if sampai and h.clock.now() >= sampai:
            return
        s = h.sesi(sesi_id)
        if s.status == "die":
            h.tick()  # sisa rangkaian 11 (jatah 2 posting per tick)
            return
        if diam and diam[0] <= h.clock.now() < diam[1]:
            pass
        elif s.status == "hold":
            h.balas(ANDI, "siap", sesi_id=s.id)
        elif s.step == f"f{benar_di_fase}":
            h.balas(BUDI, h.jawaban_sekarang(s.id), sesi_id=s.id)
        else:
            h.balas(CITRA, "hmm", sesi_id=s.id)
        h.tick()
    raise AssertionError("thread tidak selesai")


def test_thread_active_melewati_60_menit_sampai_soal_10(h):
    h.tick(3)
    # Sepi 12:10-12:40: satu siklus tanpa balasan -> hold; balasan sebelum menit 60 -> active lagi.
    main_sampai_selesai(h, diam=(jam(12, 10), jam(12, 40)))
    s = h.sesi()
    assert s.status == "die" and s.question_count == 10
    assert s.ended_at - s.posted_at > timedelta(minutes=60)
    posting = h.posting_bot()
    assert "Kuis menunggu peserta. Katakan sesuatu jika Anda siap." in posting
    assert posting[-2].startswith("📊 Peringkat hari ini:\n1. budi — ")
    assert posting[-1] == "Terima kasih sudah bermain! Sesi berikutnya: hari ini 14.00 WIB."
    assert sum(p.startswith("❓ Soal #") for p in posting) == 10


def test_siklus_sepi_setelah_menit_60_langsung_die(h):
    h.tick(3)
    main_sampai_selesai(h, diam=(jam(12, 5), jam(12, 55)), sampai=jam(13, 2))
    assert h.sesi().status == "active" and h.clock.now() > jam(13, 0)
    # Siklus berjalan masih berisi balasan; siklus sepi berikutnya (<= 6 tick) membuat thread die.
    h.tick(14)
    s = h.sesi()
    assert s.status == "die" and s.question_count < 10
    posting = h.posting_bot()
    assert posting[-1].startswith("Terima kasih sudah bermain!")
    assert (
        posting.count("Kuis menunggu peserta. Katakan sesuatu jika Anda siap.") == 1
    )  # hanya saat sepi 12:05-12:55


# ====================================================================== thread bersamaan


def test_dua_thread_bersamaan_dan_farewell_menyebut_sesi_berikutnya(engine):
    h = Harness(engine, jam(11, 59), soal=40)
    h.atur(jam_sesi=["12:00", "12:30"])
    h.tick(3)
    a = h.sesi().id
    while h.clock.now() < jam(12, 31):
        s = h.sesi(a)
        h.balas(
            BUDI if s.step == "f2" else ANDI, h.jawaban_sekarang(a) if s.step == "f2" else "siap", sesi_id=a
        )
        h.tick()
    b = h.sesi().id
    assert b != a and h.sesi(b).status == "hold" and h.sesi(a).status == "active"

    # Keduanya diproses: B menyelesaikan 01-02-03 sementara A terus berjalan (jatah 2 posting/tick dibagi).
    sebelum_a = len(h.posting_bot(a))
    for _ in range(2):
        h.balas(ANDI, "lanjut", sesi_id=a)
        h.tick()
    assert len(h.posting_bot(a)) > sebelum_a and h.posting_bot(b)[-1] == "Katakan sesuatu jika Anda siap."

    with sesi_db(engine) as db:
        soal_a = set(db.scalars(select(SessionQuestion.question_id).where(SessionQuestion.session_id == a)))
        soal_b = set(db.scalars(select(SessionQuestion.question_id).where(SessionQuestion.session_id == b)))
    assert soal_a and soal_b and not soal_a & soal_b

    main_sampai_selesai(h, a)
    assert h.sesi(b).status == "hold"
    farewell = h.posting_bot(a)[-1]
    assert (
        farewell
        == f"Terima kasih sudah bermain! Sesi berikutnya sudah dimulai: {tautan_plurk(h.sesi(b).plurk_id)}"
    )


# ====================================================================== outbox & ketahanan


def test_bot_mati_di_tengah_rangkaian_tidak_posting_ganda(h):
    h.tick()  # 11:59
    h.fake.crash_setelah = 1  # 01 terkirim, proses mati sebelum 02
    with pytest.raises(Crash):
        h.tick()
    h.tick(2)  # restart: 02, lalu 03
    s = h.sesi()
    assert h.fake.jumlah_plurk() == 1
    assert h.posting_bot(s.id) == [
        "🏆 Minggu baru dimulai, papan skor masih kosong. Ayo jadi yang pertama!",
        "Katakan sesuatu jika Anda siap.",
    ]


def test_bot_mati_setelah_pemenang_tidak_menggandakan_skor(h):
    buka_dan_aktifkan(h)
    h.tick()  # soal #1
    h.balas(BUDI, h.jawaban_sekarang())
    h.fake.crash_setelah = 1  # pemenang terkirim, mati sebelum 04
    with pytest.raises(Crash):
        h.tick()
    h.tick(2)
    posting = h.posting_bot()
    assert sum(p.startswith("✅ budi") for p in posting) == 1
    assert posting.count("Siap-siap, soal #2…") == 1
    assert sum(p.startswith("❓ Soal #2") for p in posting) == 1
    with sesi_db(h.engine) as db:
        assert db.scalar(select(func.count()).select_from(Score)) == 1


def test_anti_flood_ditunda_lalu_terkirim(h):
    h.tick()
    h.fake.gagal = [AntiFlood("anti-flood-too-many-new")]
    h.tick()  # 12:00: 01 ditolak
    with sesi_db(h.engine) as db:
        row = db.scalar(select(Outbox).where(Outbox.kind == "plurk"))
        assert row.status == "pending" and row.attempts == 1
    h.tick()  # 12:01: terkirim
    assert h.fake.jumlah_plurk() == 1 and h.sesi().posted_at == jam(12, 1)


def test_gagal_5_kali_failed_dan_thread_dihentikan(h):
    h.tick(3)
    h.balas(ANDI, "siap")
    h.fake.gagal = [AntiFlood("anti-flood-same-content")] * 5
    h.tick(5)
    with sesi_db(h.engine) as db:
        assert db.scalar(select(Outbox.status).where(Outbox.dedupe_key.like("%:q1:04"))) == "failed"
    h.tick()
    s = h.sesi()
    with sesi_db(h.engine) as db:
        st = db.get_one(BotState, 1)
    assert s.status == "die" and "posting gagal" in st.last_error


def test_token_ditolak_bot_berhenti(h):
    h.tick()
    h.fake.gagal = [TokenDitolak("401")]
    h.tick()
    with sesi_db(h.engine) as db:
        st = db.get_one(BotState, 1)
        assert st.status == "berhenti" and "Token Plurk ditolak" in st.last_error
    assert h.fake.jumlah_plurk() == 0


def test_hentikan_sekarang_thread_die_dan_farewell_tetap_terkirim(h):
    buka_dan_aktifkan(h)
    h.tick()  # soal #1
    with sesi_db(h.engine) as db:
        p = muat_pengaturan(db)
        pengirim = Pengirim(
            h.fake, h.clock, maks_per_tick=0, jeda_detik=0, maks_gagal=5, tidur=lambda _: None
        )
        k = mesin.Konteks(db, h.fake, pengirim, p, h.clock.now(), BOT.id, random.Random())
        assert mesin.hentikan_sekarang(k) == 1
    h.tick()  # status berhenti: hanya mengirim outbox yang tertunda
    s = h.sesi()
    assert s.status == "die"
    assert h.posting_bot()[-1].startswith("Terima kasih sudah bermain!")
    with sesi_db(h.engine) as db:
        assert db.get_one(BotState, 1).status == "berhenti"


def test_ketahanan_sehari_penuh_dengan_crash_acak(engine):
    """Satu hari (5 sesi) dengan pemain acak dan proses mati acak: tidak ada posting ganda,
    semua thread selesai, skor konsisten, tidak ada soal kembar di thread yang berjalan bersamaan."""
    h = Harness(engine, jam(11, 55), soal=80)
    rng = random.Random(2026)
    pemain = [PemainSim(9000 + i, f"pemain{i}") for i in range(6)]
    crash = 0
    while h.clock.now() < jam(23, 30):
        with sesi_db(engine) as db:
            putaran(
                db, h.fake, pemain, rng, benar=0.15, balas=0.25, waktu=h.clock.now() - timedelta(seconds=30)
            )
        if rng.random() < 0.3:
            h.fake.crash_setelah = rng.randint(0, 2)
        try:
            h.tick()
        except Crash:
            crash += 1
            h.clock.advance(minutes=1)
        h.fake.crash_setelah = None
    assert crash > 10

    with sesi_db(engine) as db:
        semua = db.scalars(select(GameSession)).all()
        assert len(semua) == 5 and all(s.status == "die" for s in semua)
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.status != "sent")) == 0
        # setiap posting outbox terkirim tepat sekali
        terkirim = db.scalars(select(Outbox).where(Outbox.status == "sent")).all()
        assert len({o.result_id for o in terkirim}) == len(terkirim)
        jumlah_bot = sum(1 for s in semua for r in h.fake.semua_balasan(s.plurk_id) if r.user_id == BOT.id)
        assert h.fake.jumlah_plurk() == sum(o.kind == "plurk" for o in terkirim) == 5
        assert jumlah_bot == sum(o.kind == "response" for o in terkirim)
        # skor = pemenang
        pemenang = db.scalar(
            select(func.count())
            .select_from(SessionQuestion)
            .where(SessionQuestion.winner_player_id.is_not(None))
        )
        assert db.scalar(select(func.count()).select_from(Score)) == pemenang
        for s in semua:
            assert s.question_count <= 10
            ids = [sq.question_id for sq in s.questions]
            assert len(ids) == len(set(ids))
