"""Peringkat: periode, filter topik, cari, detail pemain, koreksi skor, blokir, ekspor CSV."""

import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.admin.deps import audit, get_db, jam_nyata, kembali, render, sekarang, wajib_login
from app.admin.query import detail_pemain, tabel_peringkat
from app.core.schedule import awal_minggu
from app.models import Player, ScoreAdjustment, Topic

router = APIRouter(dependencies=[Depends(wajib_login)])
PERIODE = {"hari": "Hari ini", "minggu": "Minggu ini", "semua": "Semua waktu", "rentang": "Rentang tanggal"}


def _rentang(periode: str, hari: date, dari: str, sampai: str) -> tuple[date | None, date | None, str]:
    if periode == "hari":
        return hari, hari, f"{hari:%d/%m/%Y}"
    if periode == "minggu":
        ws = awal_minggu(hari)
        return ws, ws + timedelta(days=5), f"Rabu {ws:%d/%m} – Senin {ws + timedelta(days=5):%d/%m/%Y}"
    if periode == "rentang":
        try:
            a, b = date.fromisoformat(dari), date.fromisoformat(sampai)
        except ValueError:
            a = b = hari
        return a, b, f"{a:%d/%m/%Y} – {b:%d/%m/%Y}"
    return None, None, "Semua waktu"


@router.get("/peringkat", response_class=HTMLResponse)
def halaman(
    request: Request,
    periode: str = "minggu",
    dari: str = "",
    sampai: str = "",
    topik: int = 0,
    cari: str = "",
    pemain: int = 0,
    db: Session = Depends(get_db),
):
    hari = sekarang(db).date()
    a, b, judul = _rentang(periode if periode in PERIODE else "minggu", hari, dari, sampai)
    baris = tabel_peringkat(db, a, b, topik or None, cari or None)
    dipilih = db.get(Player, pemain) if pemain else None
    return render(
        request,
        db,
        "peringkat.html",
        "peringkat",
        periode=periode,
        daftar_periode=PERIODE,
        dari=dari or (a.isoformat() if a else ""),
        sampai=sampai or (b.isoformat() if b else ""),
        topik=topik,
        cari=cari,
        topik_list=db.scalars(select(Topic).order_by(Topic.number)).all(),
        judul=judul,
        baris=baris,
        dipilih=dipilih,
        detail=detail_pemain(db, dipilih, hari) if dipilih else None,
        minggu_ini=awal_minggu(hari),
        query=request.url.query,
    )


@router.get("/peringkat/csv")
def ekspor(
    periode: str = "minggu", dari: str = "", sampai: str = "", topik: int = 0, cari: str = "",
    db: Session = Depends(get_db),
):  # fmt: skip
    a, b, _ = _rentang(periode, sekarang(db).date(), dari, sampai)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["peringkat", "pemain", "skor", "benar", "sesi_ikut", "rata_rata_terjawab", "diblokir"])
    for i, r in enumerate(tabel_peringkat(db, a, b, topik or None, cari or None), start=1):
        w.writerow([i, r.nick, r.skor, r.benar, r.sesi_ikut, r.rata_fase, "ya" if r.diblokir else ""])
    nama = f"peringkat_{periode}_{(a or date.min).isoformat()}.csv"
    return StreamingResponse(
        iter(["﻿" + buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nama}"'},
    )


@router.post("/peringkat/pemain/{pid}/koreksi")
def koreksi(
    pid: int,
    poin: int = Form(...),
    alasan: str = Form(""),
    minggu: str = Form(""),
    db: Session = Depends(get_db),
):
    p = db.get(Player, pid)
    tujuan = f"/peringkat?pemain={pid}"
    if p is None:
        return kembali("/peringkat", err="Pemain tidak ditemukan.")
    if not alasan.strip():
        return kembali(tujuan, err="Alasan koreksi wajib diisi.")
    if poin == 0 or abs(poin) > 1000:
        return kembali(tujuan, err="Poin koreksi harus bukan nol dan maksimal ±1000.")
    try:
        ws = awal_minggu(date.fromisoformat(minggu)) if minggu else awal_minggu(sekarang(db).date())
    except ValueError:
        return kembali(tujuan, err="Tanggal minggu tidak valid.")
    db.add(
        ScoreAdjustment(
            player_id=pid, week_start=ws, points=poin, reason=alasan.strip()[:500], created_at=jam_nyata()
        )
    )
    audit(db, "koreksi_skor", pemain=p.nick, poin=poin, minggu=ws.isoformat(), alasan=alasan.strip()[:500])
    db.commit()
    return kembali(tujuan, ok=f"Koreksi {poin:+d} poin untuk {p.nick} tersimpan.")


@router.post("/peringkat/pemain/{pid}/blokir")
def blokir(pid: int, db: Session = Depends(get_db)):
    p = db.get(Player, pid)
    if p is None:
        return kembali("/peringkat", err="Pemain tidak ditemukan.")
    p.is_blocked = not p.is_blocked
    audit(db, "blokir_pemain" if p.is_blocked else "buka_blokir_pemain", pemain=p.nick)
    db.commit()
    return kembali(
        f"/peringkat?pemain={pid}", ok=f"{p.nick} {'diblokir' if p.is_blocked else 'tidak diblokir lagi'}."
    )
