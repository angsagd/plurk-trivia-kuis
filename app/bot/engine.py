"""Mesin thread kuis: hold / active / die (lihat "Mekanik thread" di CLAUDE.md).

Satu thread = satu sesi = satu plurk; state disimpan per thread di `sessions`.
Langkah (`sessions.step`):
    hold          menunggu balasan (03 / 10b2 sudah diantre)
    siap          04 "siap-siap soal #n" diantre; tick berikutnya 05 soal
    f0 .. f3      soal #n tampil dengan 0-3 clue; tick berikutnya dinilai
    tutup         die; 11 ranking + farewell diantre

Setiap keputusan mengantre posting ke outbox lalu langsung mengirimnya (dalam jatah tick).
Thread tidak maju lagi selama masih ada posting miliknya yang pending ("status baru berpindah
setelah seluruh rangkaian terkirim"); sisa rangkaian dikirim di awal tick berikutnya.
"""

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.bot import messages
from app.bot.outbox import Pengirim, antre, hasil_kirim
from app.bot.pengaturan import Pengaturan
from app.bot.peringkat import peringkat
from app.core import clues
from app.core.judging import Balasan, nilai_balasan
from app.core.schedule import NAMA_HARI, awal_minggu
from app.core.scoring import hitung_skor
from app.core.selection import KandidatSoal, StokTopik, pilih_soal
from app.models import (
    BotState,
    GameSession,
    Outbox,
    Player,
    Question,
    Response,
    Score,
    SessionQuestion,
    Topic,
)
from app.plurk.client import PlurkClient, tautan_plurk

log = logging.getLogger(__name__)

FASE = ("f0", "f1", "f2", "f3")


@dataclass
class Konteks:
    db: Session
    plurk: PlurkClient
    pengirim: Pengirim
    p: Pengaturan
    now: datetime
    bot_id: int
    rng: random.Random

    def teks(self, key: str, **nilai: object) -> str:
        return messages.render(self.db, key, self.p.batas_teks, **nilai)

    def posting(self, sesi: GameSession, kunci: str, key: str, **nilai: object) -> None:
        """Antre balasan bot di thread sesi."""
        antre(
            self.db,
            f"s{sesi.id}:{kunci}",
            self.teks(key, **nilai),
            self.now,
            session_id=sesi.id,
            target_plurk_id=sesi.plurk_id,
            qualifier=self.p.qualifier,
        )


# ---------------------------------------------------------------- membuka sesi


def soal_berjalan(db: Session) -> list[KandidatSoal]:
    """Soal milik thread yang belum die (termasuk yang belum tampil): dihindari thread baru."""
    q = (
        select(Question)
        .join(SessionQuestion, SessionQuestion.question_id == Question.id)
        .join(GameSession, GameSession.id == SessionQuestion.session_id)
        .where(GameSession.status != "die")
    )
    return [_kandidat(x) for x in db.scalars(q)]


def _kandidat(q: Question) -> KandidatSoal:
    return KandidatSoal(q.id, q.topic_id, q.soal, q.clue, q.jawaban, q.used_cycle)


def buka_sesi(k: Konteks, slot: int) -> GameSession | None:
    """Buat thread baru untuk slot ini (bila belum ada): pilih soal, antre 01-02-03, kirim."""
    db, now = k.db, k.now
    if db.scalar(select(GameSession.id).where(GameSession.play_date == now.date(), GameSession.slot == slot)):
        return None

    stok = []
    for t in db.scalars(select(Topic).where(Topic.is_active)):
        aktif = db.scalars(select(Question).where(Question.topic_id == t.id, Question.is_active)).all()
        stok.append(StokTopik(t.id, t.cycle, [_kandidat(q) for q in aktif]))
    hasil = pilih_soal(stok, k.rng, n=k.p.maks_soal, sudah_ada=soal_berjalan(db))
    for pesan in hasil.peringatan:
        log.warning("pemilihan soal: %s", pesan)
    if not hasil.soal:
        st = db.get_one(BotState, 1)
        st.last_error, st.last_error_at = "Sesi tidak dibuka: stok soal kosong", now
        db.commit()
        return None

    for tid, cycle in hasil.cycle_baru.items():
        db.get_one(Topic, tid).cycle = cycle
    sesi = GameSession(
        play_date=now.date(),
        slot=slot,
        status="hold",
        step="hold",
        question_count=0,
        ever_ran_question=False,
        test_mode=k.p.mode_uji,
    )
    db.add(sesi)
    db.flush()
    for i, s in enumerate(hasil.soal, start=1):
        db.add(SessionQuestion(session_id=sesi.id, number=i, question_id=s.id, step="belum", marker_ids=[]))

    antre(
        db,
        f"s{sesi.id}:01",
        k.teks(
            "sesi_baru",
            hari=NAMA_HARI[now.weekday()],
            tanggal=messages.format_tanggal(now.date()),
            sesi=slot,
            jam=k.p.jadwal.jam_sesi[slot - 1].strftime("%H.%M"),
            maks_soal=k.p.maks_soal,
        ),
        now,
        kind="plurk",
        session_id=sesi.id,
        qualifier=k.p.qualifier,
        limited_to=list(k.p.mode_uji_limited_to) if k.p.mode_uji else None,
    )
    top = peringkat(db, week_start=awal_minggu(now.date()), limit=10)
    if top:
        k.posting(sesi, "02", "top10", top10=messages.format_daftar(top))
    else:
        k.posting(sesi, "02", "top10_kosong")
    k.posting(sesi, "03", "ajakan")
    db.commit()
    log.info("sesi %d dibuka (%s slot %d, %d soal)", sesi.id, now.date(), slot, len(hasil.soal))
    k.pengirim.kirim(db)
    return sesi


# ---------------------------------------------------------------- memajukan thread


def thread_hidup(db: Session) -> list[GameSession]:
    return list(db.scalars(select(GameSession).where(GameSession.status != "die").order_by(GameSession.id)))


def _ada_outbox(db: Session, sesi: GameSession, status: str) -> bool:
    return bool(db.scalar(select(exists().where(Outbox.session_id == sesi.id, Outbox.status == status))))


def majukan_thread(k: Konteks, sesi: GameSession) -> None:
    db = k.db
    if _ada_outbox(db, sesi, "failed"):
        # Posting gagal berkali-kali: thread dihentikan tanpa posting lagi (dicatat di last_error).
        sesi.status, sesi.step, sesi.ended_at = "die", "tutup", k.now
        st = db.get_one(BotState, 1)
        st.last_error, st.last_error_at = f"Sesi {sesi.id} dihentikan: posting gagal", k.now
        db.commit()
        return
    if sesi.plurk_id is None or _ada_outbox(db, sesi, "pending"):
        return  # rangkaian posting belum selesai

    ambil_balasan(k, sesi)
    if sesi.status == "hold":
        _hold(k, sesi)
    elif sesi.step == "siap":
        _tampilkan_soal(k, sesi)
    elif sesi.step in FASE:
        _nilai_fase(k, sesi)
    db.commit()
    k.pengirim.kirim(db)


def ambil_balasan(k: Konteks, sesi: GameSession) -> None:
    """Simpan balasan baru (selain milik bot) ke `responses`; catat ID terakhir yang terbaca."""
    assert sesi.plurk_id is not None
    db = k.db
    for r in k.plurk.get_responses(sesi.plurk_id, sesi.last_response_id or 0):
        sesi.last_response_id = max(sesi.last_response_id or 0, r.id)
        if r.user_id == k.bot_id:
            continue
        pemain = db.scalar(select(Player).where(Player.plurk_user_id == r.user_id))
        if pemain is None:
            pemain = Player(plurk_user_id=r.user_id, nick=r.nick, first_seen=r.posted, is_blocked=False)
            db.add(pemain)
            db.flush()
        elif pemain.nick != r.nick:
            pemain.nick = r.nick
        db.add(
            Response(
                plurk_response_id=r.id,
                session_id=sesi.id,
                player_id=pemain.id,
                content=r.content,
                posted_at=r.posted,
                status="diblokir" if pemain.is_blocked else None,
            )
        )
    db.flush()


def _balasan_sejak(k: Konteks, sesi: GameSession, setelah_id: int) -> list[Response]:
    """Balasan pemain (tidak diblokir) di thread ini dengan ID > setelah_id."""
    q = (
        select(Response)
        .join(Player, Player.id == Response.player_id)
        .where(Response.session_id == sesi.id, Response.plurk_response_id > setelah_id, ~Player.is_blocked)
        .order_by(Response.plurk_response_id)
    )
    return list(k.db.scalars(q))


def _batas_umur(k: Konteks, sesi: GameSession) -> datetime:
    assert sesi.posted_at is not None
    return sesi.posted_at + timedelta(minutes=k.p.umur_hold_menit)


def _hold(k: Konteks, sesi: GameSession) -> None:
    """03 / 10b2: ada balasan -> active (04 di tick yang sama); umur >= 60 menit -> die."""
    batas = _batas_umur(k, sesi)
    # Dibandingkan dengan waktu POSTING balasan: balasan sebelum menit ke-60 tetap mengaktifkan thread.
    balasan = [r for r in _balasan_sejak(k, sesi, sesi.cycle_start_response_id or 0) if r.posted_at < batas]
    if balasan:
        sesi.status = "active"
        _siap(k, sesi)
    elif k.now >= batas:
        _mati(k, sesi)


def _siap(k: Konteks, sesi: GameSession) -> None:
    """04: siap-siap soal berikutnya. Siklus baru dimulai dari balasan terakhir yang terbaca."""
    n = sesi.question_count + 1
    k.posting(sesi, f"q{n}:04", "siap_soal", n=n)
    sesi.step = "siap"
    sesi.cycle_start_response_id = sesi.last_response_id or 0


def _soal_ke(sesi: GameSession, n: int) -> SessionQuestion | None:
    return next((sq for sq in sesi.questions if sq.number == n), None)


def _tampilkan_soal(k: Konteks, sesi: GameSession) -> None:
    """05: soal #n. Soal dicatat terpakai saat ditampilkan (soal yang tak sempat tampil kembali ke bank)."""
    n = sesi.question_count + 1
    sq = _soal_ke(sesi, n)
    if sq is None:  # stok soal saat sesi dibuka kurang dari maks_soal
        _mati(k, sesi)
        return
    q = sq.question
    k.posting(sesi, f"q{n}:05", "soal", n=n, soal=q.soal)
    q.used_cycle = q.topic.cycle
    q.times_used += 1
    sq.step, sq.started_at = "f0", k.now
    sesi.question_count, sesi.ever_ran_question, sesi.step = n, True, "f0"


def _penanda(k: Konteks, sesi: GameSession, n: int, fase: int) -> list[int]:
    kunci = [f"q{n}:05"] + [f"q{n}:clue{i}" for i in range(1, fase + 1)]
    ids = [hasil_kirim(k.db, f"s{sesi.id}:{x}") for x in kunci]
    if any(i is None for i in ids):
        raise RuntimeError(f"sesi {sesi.id} soal {n}: penanda belum lengkap {ids}")
    return [i for i in ids if i is not None]


def _nilai_fase(k: Konteks, sesi: GameSession) -> None:
    """06-09: nilai balasan; benar -> pemenang; belum -> clue berikutnya / buka jawaban. Lalu 10."""
    db, n, fase = k.db, sesi.question_count, FASE.index(sesi.step)
    sq = _soal_ke(sesi, n)
    assert sq is not None
    q = sq.question
    penanda = _penanda(k, sesi, n, fase)
    sq.marker_ids = penanda

    respons = [
        r
        for r in db.scalars(
            select(Response).where(Response.session_id == sesi.id, Response.plurk_response_id > penanda[0])
        )
    ]
    pemain = {
        p.id: p for p in db.scalars(select(Player).where(Player.id.in_({r.player_id for r in respons})))
    }
    diblokir = {p.plurk_user_id for p in pemain.values() if p.is_blocked}
    hasil = nilai_balasan(
        [Balasan(r.plurk_response_id, pemain[r.player_id].plurk_user_id, r.content) for r in respons],
        q.jawaban,
        penanda,
        bot_id=k.bot_id,
        diblokir=diblokir,
        maks_karakter=k.p.maks_karakter_balasan,
        maks_per_fase=k.p.maks_per_fase,
    )
    for r in respons:
        if r.plurk_response_id in hasil.status:
            r.session_question_id = sq.id
            r.status = hasil.status[r.plurk_response_id].value
            r.phase = hasil.fase.get(r.plurk_response_id)

    if hasil.pemenang is not None:
        menang = hasil.pemenang
        juara = next(p for p in pemain.values() if p.plurk_user_id == menang.balasan.pemain_id)
        poin = hitung_skor(q.jawaban, menang.fase, k.p.rumus_skor)
        sq.winner_player_id, sq.winner_response_id = juara.id, menang.balasan.id
        sq.winner_phase, sq.points, sq.step, sq.ended_at = menang.fase, poin, "selesai", k.now
        db.add(
            Score(
                player_id=juara.id,
                session_question_id=sq.id,
                points=poin,
                play_date=sesi.play_date,
                week_start=awal_minggu(sesi.play_date),
            )
        )
        k.posting(sesi, f"q{n}:menang", "pemenang", nama=juara.nick, jawaban=q.jawaban, skor=poin)
        _cek_lanjut(k, sesi)
    elif fase < 3:
        berikut = fase + 1
        if berikut == 1:
            isi = q.clue
        elif berikut == 2:
            isi = clues.clue2(q.jawaban, k.p.karakter_pengganti, k.p.pemisah_kata)
        else:
            isi = clues.clue3(q.jawaban, k.p.karakter_pengganti, k.p.pemisah_kata)
        k.posting(sesi, f"q{n}:clue{berikut}", f"clue{berikut}", clue=isi)
        sq.step = sesi.step = FASE[berikut]
    else:
        k.posting(sesi, f"q{n}:buka", "jawaban_dibuka", jawaban=q.jawaban)
        sq.step, sq.ended_at = "selesai", k.now
        _cek_lanjut(k, sesi)


def _cek_lanjut(k: Konteks, sesi: GameSession) -> None:
    """10: soal ke-maks -> die; ada balasan di siklus ini -> 04; tidak ada -> menunggu (hold).
    Bila umur thread sudah >= 60 menit, thread yang sepi langsung die (pesan menunggu tidak berguna,
    karena balasan sesudah menit ke-60 tidak lagi bisa mengaktifkannya)."""
    n = sesi.question_count
    if n >= k.p.maks_soal:
        _mati(k, sesi)
    elif _balasan_sejak(k, sesi, sesi.cycle_start_response_id or 0):
        _siap(k, sesi)
    elif k.now >= _batas_umur(k, sesi):
        _mati(k, sesi)
    else:
        k.posting(sesi, f"q{n}:tunggu", "menunggu")
        sesi.status, sesi.step = "hold", "hold"
        sesi.cycle_start_response_id = sesi.last_response_id or 0


def _mati(k: Konteks, sesi: GameSession) -> None:
    """11: ranking hari ini (bila sempat ada soal) + farewell dengan jadwal / tautan sesi berikutnya."""
    db = k.db
    sesi.status, sesi.step, sesi.ended_at = "die", "tutup", k.now
    if sesi.ever_ran_question:
        rank = peringkat(db, play_date=sesi.play_date, limit=10)
        if rank:
            k.posting(sesi, "11:ranking", "ranking_hari_ini", ranking=messages.format_daftar(rank))
    berikut = db.scalar(
        select(GameSession)
        .where(GameSession.id > sesi.id, GameSession.status != "die", GameSession.plurk_id.is_not(None))
        .order_by(GameSession.id.desc())
    )
    if berikut is not None and berikut.plurk_id is not None:
        k.posting(sesi, "11:farewell", "farewell_sudah_mulai", tautan=tautan_plurk(berikut.plurk_id))
    else:
        mulai, _ = k.p.jadwal.sesi_berikutnya(k.now)
        k.posting(
            sesi, "11:farewell", "farewell", sesi_berikutnya=messages.format_sesi_berikutnya(mulai, k.now)
        )
    log.info("sesi %d die setelah %d soal", sesi.id, sesi.question_count)


def hentikan_sekarang(k: Konteks) -> int:
    """Kontrol admin: semua thread yang belum die langsung die (langkah 11) dan bot berhenti."""
    jumlah = 0
    for sesi in thread_hidup(k.db):
        _mati(k, sesi)
        jumlah += 1
    k.db.get_one(BotState, 1).status = "berhenti"
    k.db.commit()
    return jumlah
