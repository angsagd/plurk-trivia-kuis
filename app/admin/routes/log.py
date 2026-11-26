"""Log admin: isi admin_audit (terbaru dulu)."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.deps import get_db, render, wajib_login
from app.models import AdminAudit

router = APIRouter(dependencies=[Depends(wajib_login)])
PER_HALAMAN = 50


@router.get("/log", response_class=HTMLResponse)
def halaman(request: Request, hal: int = 1, db: Session = Depends(get_db)):
    hal = max(1, hal)
    total = db.scalar(select(func.count()).select_from(AdminAudit)) or 0
    baris = db.scalars(
        select(AdminAudit).order_by(AdminAudit.id.desc()).offset((hal - 1) * PER_HALAMAN).limit(PER_HALAMAN)
    ).all()
    return render(request, db, "log.html", "log", baris=baris, hal=hal, ada_berikut=hal * PER_HALAMAN < total)
