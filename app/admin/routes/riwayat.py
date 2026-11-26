"""Riwayat sesi: arsip sesi, soal, pemenang, semua balasan + status."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.deps import get_db, render, wajib_login
from app.models import GameSession, Player, Response
from app.plurk.client import tautan_plurk

router = APIRouter(dependencies=[Depends(wajib_login)])
PER_HALAMAN = 30


@router.get("/riwayat", response_class=HTMLResponse)
def daftar(request: Request, hal: int = 1, db: Session = Depends(get_db)):
    hal = max(1, hal)
    total = db.scalar(select(func.count()).select_from(GameSession)) or 0
    sesi = db.scalars(
        select(GameSession).order_by(GameSession.id.desc()).offset((hal - 1) * PER_HALAMAN).limit(PER_HALAMAN)
    ).all()
    jumlah_balasan = dict(
        db.execute(
            select(Response.session_id, func.count()).where(Response.session_id.in_([s.id for s in sesi]))
            .group_by(Response.session_id)
        ).all()
    )  # fmt: skip
    return render(
        request, db, "riwayat.html", "riwayat",
        sesi=sesi, balasan=jumlah_balasan, hal=hal, ada_berikut=hal * PER_HALAMAN < total,
    )  # fmt: skip


@router.get("/riwayat/{sid}", response_class=HTMLResponse)
def detail(request: Request, sid: int, db: Session = Depends(get_db)):
    s = db.get(GameSession, sid)
    if s is None:
        raise HTTPException(404)
    balasan = db.scalars(
        select(Response).where(Response.session_id == sid).order_by(Response.plurk_response_id)
    ).all()
    ids = {b.player_id for b in balasan} | {q.winner_player_id for q in s.questions if q.winner_player_id}
    pemain = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(ids)))}
    per_soal: dict[int | None, list] = {}
    for b in balasan:
        per_soal.setdefault(b.session_question_id, []).append(b)
    return render(
        request, db, "riwayat_detail.html", "riwayat",
        s=s, per_soal=per_soal, pemain=pemain, tautan=tautan_plurk(s.plurk_id) if s.plurk_id else None,
    )  # fmt: skip
