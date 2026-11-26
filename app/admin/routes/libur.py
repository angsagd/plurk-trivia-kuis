"""Posting hari libur: jadwal posting Selasa/Jumat, status kirim, uji privat, juara mingguan otomatis."""

from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.deps import audit, get_db, jam_nyata, kembali, render, sekarang, wajib_login
from app.admin.routes.pengaturan import _kirim_uji
from app.bot import libur as bot_libur
from app.bot import messages
from app.bot.pengaturan import muat_pengaturan
from app.bot.peringkat import peringkat
from app.clock import WIB
from app.core.schedule import NAMA_HARI, SELASA, awal_minggu
from app.models import Outbox, ScheduledPost

router = APIRouter(dependencies=[Depends(wajib_login)])
QUALIFIER = [":", "says", "shares", "asks", "thinks", "feels", "likes", "loves", "wants", "will", "has"]


def _hari_libur(db: Session, mulai: date, jumlah: int = 6) -> list[date]:
    p = muat_pengaturan(db)
    hasil, d = [], mulai
    while len(hasil) < jumlah and d < mulai + timedelta(days=60):
        if not p.jadwal.hari_aktif_pada(d):
            hasil.append(d)
        d += timedelta(days=1)
    return hasil


def _label(d: date) -> str:
    return f"{NAMA_HARI[d.weekday()]}, {messages.format_tanggal(d)}"


@router.get("/libur", response_class=HTMLResponse)
def halaman(request: Request, ubah: int = 0, db: Session = Depends(get_db)):
    now = sekarang(db)
    hari = _hari_libur(db, now.date())
    akan = db.scalars(
        select(ScheduledPost).where(ScheduledPost.status == "terjadwal").order_by(ScheduledPost.run_at)
    ).all()
    lewat = db.scalars(
        select(ScheduledPost)
        .where(ScheduledPost.status != "terjadwal")
        .order_by(ScheduledPost.run_at.desc())
        .limit(20)
    ).all()
    outbox = {
        o.id: o.status
        for o in db.scalars(select(Outbox).where(Outbox.id.in_([s.outbox_id for s in lewat if s.outbox_id])))
    }
    grup = []
    for d in hari[:4]:
        isi = [s for s in akan if s.run_at.date() == d]
        juara = None
        if d.weekday() == SELASA:
            ws = awal_minggu(d) - timedelta(days=7)
            top = peringkat(db, week_start=ws, limit=3)
            juara = ", ".join(f"{n} {p}" for n, p in top) or "(belum ada skor minggu ini)"
        grup.append((d, _label(d), isi, juara))
    dipilih = db.get(ScheduledPost, ubah) if ubah else None
    return render(
        request, db, "libur.html", "libur",
        grup=grup, lewat=[(s, bot_libur.status_tampil(s, outbox.get(s.outbox_id))) for s in lewat],
        pilihan_hari=[(d.isoformat(), _label(d)) for d in hari], qualifier=QUALIFIER, dipilih=dipilih,
        batas=muat_pengaturan(db).batas_teks, jam_juara=bot_libur.JAM_JUARA_MINGGUAN.strftime("%H.%M"),
    )  # fmt: skip


@router.post("/libur")
def simpan(
    tanggal: str = Form(...),
    jam: str = Form(...),
    qualifier: str = Form(":"),
    isi: str = Form(...),
    balasan: str = Form(""),
    post_id: int = Form(0),
    db: Session = Depends(get_db),
):
    p = muat_pengaturan(db)
    try:
        run_at = datetime.combine(date.fromisoformat(tanggal), time.fromisoformat(jam), tzinfo=WIB)
    except ValueError:
        return kembali("/libur", err="Tanggal atau jam tidak valid.")
    isi = isi.replace("\r\n", "\n").strip()
    if p.jadwal.hari_aktif_pada(run_at.date()):
        return kembali("/libur", err="Tanggal itu hari aktif kuis; posting libur hanya untuk hari libur.")
    if run_at <= sekarang(db):
        return kembali("/libur", err="Waktu posting sudah lewat.")
    if not isi or len(isi) > p.batas_teks:
        return kembali("/libur", err=f"Isi posting wajib diisi, maksimal {p.batas_teks} karakter.")
    if qualifier not in QUALIFIER:
        return kembali("/libur", err="Qualifier tidak dikenal.")
    sp = db.get(ScheduledPost, post_id) if post_id else None
    if sp is not None and sp.status != "terjadwal":
        return kembali("/libur", err="Posting yang sudah dikirim tidak bisa diubah.")
    if sp is None:
        sp = ScheduledPost(created_at=jam_nyata(), status="terjadwal", run_at=run_at, content=isi)
        db.add(sp)
    sp.run_at, sp.qualifier, sp.content, sp.allow_comments = run_at, qualifier, isi, bool(balasan)
    db.flush()
    audit(db, "libur_simpan", id=sp.id, run_at=run_at.isoformat(), isi=isi[:200])
    db.commit()
    return kembali("/libur", ok=f"Posting dijadwalkan {_label(run_at.date())} {run_at:%H.%M} WIB.")


@router.post("/libur/{pid}/batal")
def batal(pid: int, db: Session = Depends(get_db)):
    sp = db.get(ScheduledPost, pid)
    if sp is None or sp.status != "terjadwal":
        return kembali("/libur", err="Posting tidak ditemukan atau sudah dikirim.")
    sp.status = "batal"
    audit(db, "libur_batal", id=pid)
    db.commit()
    return kembali("/libur", ok="Posting dibatalkan.")


@router.post("/libur/uji")
def uji(isi: str = Form(...), db: Session = Depends(get_db)):
    err = _kirim_uji(db, isi.replace("\r\n", "\n").strip())
    return kembali(
        "/libur", err=err, ok=None if err else "Plurk uji privat diantre; terkirim pada tick berikutnya."
    )
