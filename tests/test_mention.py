"""Tes tahap 8: perintah lewat mention."""

from datetime import timedelta

import pytest
from sqlalchemy import select

from app.bot.mention import kosongkan_cache_teman
from app.db import sesi_db
from app.models import Command, CommandAlias, CommandRequest, CommandResponse, Player
from app.perintah import pastikan_perintah_bawaan
from app.plurk.client import tautan_plurk
from app.plurk.fake import BOT
from tests.test_engine import ANDI, BUDI, CITRA, SENIN, Harness, jam

DODI, ORANG_LUAR = (9004, "dodi"), (9999, "orangluar")


@pytest.fixture
def h(engine):
    kosongkan_cache_teman()
    h = Harness(engine, jam(10, 0))
    h.atur(perintah_aktif=True)
    with sesi_db(engine) as db:
        pastikan_perintah_bawaan(db)
    h.fake.tambah_teman(ANDI[0], BUDI[0], CITRA[0], DODI[0])
    return h


def mention(h: Harness, pemain, teks: str, di_plurk_milik=None) -> int:
    """Pemain menulis plurk berisi teks, atau membalas di plurk milik orang lain. Kembalikan plurk_id."""
    waktu = h.clock.now() - timedelta(seconds=30)
    if di_plurk_milik is None:
        return h.fake.inject_plurk(pemain[0], pemain[1], teks, waktu)
    pid = h.fake.inject_plurk(
        di_plurk_milik[0], di_plurk_milik[1], "plurk biasa", waktu - timedelta(seconds=5)
    )
    h.fake.inject_response(pid, pemain[0], pemain[1], teks, waktu)
    return pid


def jawaban_bot(h: Harness, plurk_id: int) -> list[str]:
    return [r.content for r in h.fake.semua_balasan(plurk_id) if r.user_id == BOT.id]


def status(h: Harness, plurk_id: int) -> str:
    with sesi_db(h.engine) as db:
        return db.scalar(select(CommandRequest.status).where(CommandRequest.plurk_id == plurk_id))


def test_rank_tanpa_poin_dijawab_di_plurk_itu(h):
    pid = mention(h, ANDI, "@kuisbot rank")
    h.tick()
    assert jawaban_bot(h, pid) == [
        "andi belum punya poin minggu ini. Ikut sesi berikutnya hari ini 12.00 WIB!"
    ]
    assert status(h, pid) == "dijawab"


@pytest.mark.parametrize("teks", ["@kuisbot: Rank?", "@kuisbot RANK aku berapa"])
def test_variasi_penulisan_rank(h, teks):
    pid = mention(h, BUDI, teks)
    h.tick()
    assert status(h, pid) == "dijawab" and "budi belum punya poin" in jawaban_bot(h, pid)[0]


@pytest.mark.parametrize("teks", ["eh @kuisbot rank", "@kuisbot keren banget!"])
def test_bukan_perintah_diabaikan(h, teks):
    pid = mention(h, ANDI, teks)
    h.tick()
    assert jawaban_bot(h, pid) == [] and status(h, pid) == "diabaikan"


def test_rank_lalu_skor_dalam_60_menit_cooldown(h):
    a = mention(h, ANDI, "@kuisbot rank")
    h.tick()
    b = mention(h, ANDI, "@kuisbot skor")
    h.tick()
    assert status(h, a) == "dijawab" and status(h, b) == "cooldown" and jawaban_bot(h, b) == []
    h.clock.advance(minutes=60)
    c = mention(h, ANDI, "@kuisbot poin")
    h.tick()
    assert status(h, c) == "dijawab"


def test_teman_mention_di_plurk_bukan_teman(h):
    pid = mention(h, ANDI, "@kuisbot rank", di_plurk_milik=ORANG_LUAR)
    h.tick()
    assert status(h, pid) == "bukan_teman" and jawaban_bot(h, pid) == []
    pid = mention(h, ORANG_LUAR, "@kuisbot rank")
    h.tick()
    assert status(h, pid) == "bukan_teman"


def test_mention_di_balasan_plurk_teman_dijawab(h):
    pid = mention(h, ANDI, "@kuisbot jadwal", di_plurk_milik=BUDI)
    h.tick()
    assert jawaban_bot(h, pid) == ["Sesi berikutnya hari ini 12.00 WIB."]


def test_pemain_diblokir_perintah_nonaktif_dan_fitur_mati(h):
    with sesi_db(h.engine) as db:
        db.add(Player(plurk_user_id=CITRA[0], nick="citra", is_blocked=True, first_seen=h.clock.now()))
        db.scalar(select(Command).where(Command.key == "aturan")).enabled = False
    a = mention(h, CITRA, "@kuisbot rank")
    b = mention(h, ANDI, "@kuisbot aturan")
    h.tick()
    assert (status(h, a), status(h, b)) == ("diblokir", "nonaktif")
    h.atur(perintah_aktif=False)
    c = mention(h, BUDI, "@kuisbot rank")
    h.tick()
    assert status(h, c) is None and jawaban_bot(h, c) == []


def test_batas_global_per_jam(h):
    h.atur(perintah_batas_global_per_jam=2)
    ids = [mention(h, p, "@kuisbot rank") for p in (ANDI, BUDI, DODI)]
    h.tick()
    assert [status(h, i) for i in ids] == ["dijawab", "dijawab", "batas_global"]


def test_sesi_lebih_penting_isi_dihitung_saat_dikirim(h):
    h.clock.set(jam(11, 59))
    h.tick()  # 11:59
    pid = mention(h, ANDI, "@kuisbot jadwal")  # saat diterima: belum ada sesi berjalan
    h.tick()  # 12:00: 01 + 02 memakai seluruh jatah -> perintah menunggu
    assert jawaban_bot(h, pid) == [] and status(h, pid) == "antre"
    h.tick()  # 12:01: 03 (1 posting) lalu sisa jatah untuk perintah
    sesi = h.sesi()
    assert jawaban_bot(h, pid) == [f"Sesi sedang berlangsung, ayo ikut: {tautan_plurk(sesi.plurk_id)}"]
    assert h.posting_bot()[-1] == "Katakan sesuatu jika Anda siap."  # posting sesi tidak tergeser


def test_antrean_lebih_dari_60_menit_dibuang(h):
    h.clock.set(jam(11, 59))
    h.tick()
    pid = mention(h, ANDI, "@kuisbot rank")
    h.atur(maks_posting_per_tick=2)
    h.tick()  # 12:00: jatah habis untuk sesi
    assert status(h, pid) == "antre"
    h.clock.advance(minutes=61)
    h.status_bot("jeda")
    h.tick()
    assert status(h, pid) == "kedaluwarsa" and jawaban_bot(h, pid) == []


def test_mention_di_thread_kuis_adalah_balasan_biasa(h):
    h.clock.set(jam(11, 59))
    h.tick(3)
    h.balas(ANDI, "@kuisbot rank siap!")
    h.tick()
    s = h.sesi()
    assert s.status == "active" and status(h, s.plurk_id) == "diabaikan"


def test_klasemen_dan_rank_selasa_hasil_minggu_lalu(h):
    h.clock.set(jam(11, 59))
    h.tick(3)
    h.balas(ANDI, "siap")
    h.tick(2)
    h.balas(BUDI, h.jawaban_sekarang())
    h.tick()  # budi menang 7 poin (Senin 30 Nov, minggu 25-30 Nov)
    h.status_bot("hentikan")  # tutup thread Senin (ranking + farewell) agar jatah posting Selasa kosong
    h.tick(3)
    h.clock.set(jam(10, 0, hari=SENIN + timedelta(days=1)))  # Selasa
    h.status_bot("jeda")
    a = mention(h, BUDI, "@kuisbot rank")
    b = mention(h, ANDI, "@kuisbot top")
    h.tick()
    assert jawaban_bot(h, a) == ["Kamu #1 minggu ini (7 poin)! Sesi berikutnya besok 12.00 WIB."]
    assert jawaban_bot(h, b) == ["🏆 Top 10 minggu ini:\n1. budi — 7"]
    c = mention(h, ANDI, "@kuisbot statistik")
    d = mention(h, BUDI, "@kuisbot statistik")
    h.tick()
    assert jawaban_bot(h, c) == ["andi: 0 jawaban benar, paling sering benar di -."]
    assert jawaban_bot(h, d) == ["budi: 1 jawaban benar, paling sering benar di Soal."]


def test_bantuan_dengan_tanda_tanya_dan_kustom_acak(h):
    with sesi_db(h.engine) as db:
        cmd = Command(key="halo", kind="kustom", enabled=True, show_in_help=False)
        db.add(cmd)
        db.flush()
        db.add(CommandAlias(alias="hai", command_id=cmd.id))
        db.add(CommandResponse(command_id=cmd.id, body="Halo juga, {nama}!"))
    a = mention(h, ANDI, "@kuisbot ?")
    b = mention(h, BUDI, "@kuisbot hai")
    h.tick()
    assert jawaban_bot(h, a) == ["Kata kunci: aturan, bantuan, jadwal, klasemen, rank"]
    assert jawaban_bot(h, b) == ["Halo juga, budi!"]


def test_template_lama_dengan_isian_kosong_tidak_bocor(h):
    with sesi_db(h.engine) as db:
        db.scalar(
            select(Command).where(Command.key == "jadwal")
        ).template = "Sesi berikutnya {sesi_berikutnya}. {tautan_sesi}"
    pid = mention(h, ANDI, "@kuisbot jadwal")
    h.tick()
    assert jawaban_bot(h, pid) == ["Sesi berikutnya hari ini 12.00 WIB."]


def test_alert_yang_sama_hanya_diproses_sekali(h):
    pid = mention(h, ANDI, "@kuisbot rank")
    h.tick(3)
    assert len(jawaban_bot(h, pid)) == 1
    with sesi_db(h.engine) as db:
        assert len(db.scalars(select(CommandRequest)).all()) == 1


def test_error_mention_tidak_mengganggu_sesi(h, monkeypatch):
    def rusak():
        raise RuntimeError("API mati")

    monkeypatch.setattr(h.fake, "get_mentions", rusak)
    h.clock.set(jam(11, 59))
    h.tick(2)
    assert h.sesi().plurk_id is not None
