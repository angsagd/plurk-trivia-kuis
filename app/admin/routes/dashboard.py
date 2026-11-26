"""Dashboard: status bot, thread berjalan (HTMX tiap 5 detik), ringkasan, peringatan, jadwal, Top 5, stok."""

import random
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.deps import audit, get_db, jam_nyata, kembali, render, sekarang, templates, wajib_login
from app.admin.query import ringkasan_hari, stok_topik
from app.bot import engine as mesin
from app.bot.pengaturan import muat_pengaturan
from app.bot.peringkat import peringkat
from app.core import clues
from app.core.schedule import NAMA_HARI, awal_minggu
from app.models import BotState, GameSession, Outbox, Response
from app.plurk.client import tautan_plurk

router = APIRouter(dependencies=[Depends(wajib_login)])
__all__ = ["router", "wajib_login"]


def _thread(db: Session, now: datetime) -> list[dict]:
    p = muat_pengaturan(db)
    hasil = []
    for s in mesin.thread_hidup(db):
        sq = (
            next((x for x in s.questions if x.number == s.question_count), None) if s.question_count else None
        )
        berikut = next((x for x in s.questions if x.number == s.question_count + 1), None)
        fase = int(s.step[1]) if s.step in mesin.FASE else None
        balasan = []
        if sq is not None:
            balasan = db.scalars(
                select(Response)
                .where(Response.session_question_id == sq.id)
                .order_by(Response.plurk_response_id)
            ).all()
        hasil.append(
            {
                "sesi": s,
                "umur": int((now - s.posted_at).total_seconds() // 60) if s.posted_at else None,
                "jam": p.jadwal.jam_sesi[s.slot - 1].strftime("%H.%M")
                if s.slot <= len(p.jadwal.jam_sesi)
                else "",
                "sq": sq,
                "fase": fase,
                "clue2": clues.clue2(sq.question.jawaban, p.karakter_pengganti, p.pemisah_kata) if sq else "",
                "clue3": clues.clue3(sq.question.jawaban, p.karakter_pengganti, p.pemisah_kata) if sq else "",
                "berikut": berikut if berikut and berikut.step == "belum" else None,
                "balasan": balasan,
                "tautan": tautan_plurk(s.plurk_id) if s.plurk_id else None,
            }
        )
    return hasil


def _peringatan(db: Session, now: datetime) -> list[tuple[str, str]]:
    st = db.get_one(BotState, 1)
    p = muat_pengaturan(db)
    w: list[tuple[str, str]] = []
    if st.heartbeat_at is None or (jam_nyata() - st.heartbeat_at) > timedelta(minutes=3):
        w.append(("bahaya", "Bot tidak mengirim detak lebih dari 3 menit (kontainer bot mati atau macet)."))
    if st.last_error:
        waktu = st.last_error_at.strftime("%d/%m %H.%M") if st.last_error_at else ""
        w.append(("bahaya", f"Error terakhir ({waktu} WIB): {st.last_error}"))
    gagal = db.scalar(select(func.count()).where(Outbox.status == "failed")) or 0
    if gagal:
        w.append(("bahaya", f"{gagal} posting gagal dikirim (5× percobaan)."))
    tertunda = db.scalar(select(func.count()).where(Outbox.status == "pending", Outbox.attempts > 0)) or 0
    if tertunda:
        w.append(("info", f"{tertunda} posting tertunda (anti-flood), dicoba lagi tiap tick."))
    if p.mode_uji and not p.mode_uji_limited_to:
        w.append(("bahaya", "Mode uji aktif tetapi ID akun admin belum diisi: plurk akan terlihat publik."))
    for s in stok_topik(db):
        if s.topik.is_active and s.total and s.sisa / s.total < 0.1:
            w.append(
                (
                    "info",
                    f"Stok topik {s.topik.name} tersisa {s.sisa / s.total:.0%}; akan diputar ulang otomatis.",
                )
            )
    if sum(s.total for s in stok_topik(db) if s.topik.is_active) < 50:
        w.append(("bahaya", "Stok soal aktif kurang dari 50 (5 sesi). Unggah bank soal."))
    return w


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    now = sekarang(db)
    p = muat_pengaturan(db)
    hari = now.date()
    sesi_hari = {s.slot: s for s in db.scalars(select(GameSession).where(GameSession.play_date == hari))}
    jadwal = []
    if p.jadwal.hari_aktif_pada(hari):
        for i, jam in enumerate(p.jadwal.jam_sesi, start=1):
            s = sesi_hari.get(i)
            if s is None:
                ket = "Terjadwal" if datetime.combine(hari, jam, tzinfo=now.tzinfo) > now else "Tidak dibuka"
            elif s.status == "die":
                menang = sum(1 for q in s.questions if q.winner_player_id)
                ket = f"Selesai · {menang}/{s.question_count} terjawab"
            else:
                ket = f"Berlangsung ({s.status})"
            jadwal.append((jam.strftime("%H.%M"), i, ket))
    mulai, nomor = p.jadwal.sesi_berikutnya(now)
    stok = stok_topik(db)
    total_aktif = sum(s.total for s in stok if s.topik.is_active)
    return render(
        request,
        db,
        "dashboard.html",
        "dashboard",
        hari=f"{NAMA_HARI[hari.weekday()]}, {hari.day}/{hari.month}/{hari.year}",
        hari_aktif=p.jadwal.hari_aktif_pada(hari),
        ringkas=ringkasan_hari(db, hari),
        berikut=(mulai, nomor),
        thread=_thread(db, now),
        peringatan=_peringatan(db, now),
        jadwal=jadwal,
        top5=peringkat(db, week_start=awal_minggu(hari), limit=5),
        stok=stok,
        total_aktif=total_aktif,
    )


@router.get("/partial/thread", response_class=HTMLResponse)
def partial_thread(request: Request, db: Session = Depends(get_db)):
    sesi = getattr(request.state, "sesi", None)
    return templates.TemplateResponse(
        request, "_thread.html", {"thread": _thread(db, sekarang(db)), "csrf": sesi.csrf if sesi else ""}
    )


@router.post("/kontrol/{aksi}")
def kontrol(aksi: str, db: Session = Depends(get_db)):
    status = {"jalankan": "aktif", "jeda": "jeda", "hentikan": "hentikan", "berhenti": "berhenti"}.get(aksi)
    if status is None:
        raise HTTPException(404)
    db.get_one(BotState, 1).status = status
    audit(db, f"bot_{status}")
    db.commit()
    pesan = {
        "aktif": "Bot dijalankan. Sesi dibuka sesuai jadwal.",
        "jeda": "Jeda: thread berjalan dibiarkan selesai, tidak ada sesi baru.",
        "hentikan": "Hentikan sekarang: semua thread ditutup pada tick berikutnya (≤ 1 menit).",
        "berhenti": "Bot berhenti.",
    }[status]
    return kembali("/", ok=pesan)


@router.post("/sesi/{sesi_id}/lewati")
def lewati(sesi_id: int, db: Session = Depends(get_db)):
    sesi = db.get(GameSession, sesi_id)
    if sesi is None or sesi.status == "die":
        return kembali("/", err="Sesi tidak ditemukan atau sudah selesai.")
    sq = mesin.lewati_soal(db, sesi, random.Random())
    if sq is None:
        return kembali("/", err="Tidak ada soal berikutnya yang bisa diganti.")
    audit(db, "lewati_soal", sesi=sesi_id, nomor=sq.number, soal_baru=sq.question_id)
    db.commit()
    return kembali("/", ok=f"Soal #{sq.number} sesi {sesi.slot} diganti.")
