"""Dependency bersama halaman admin: database, login + CSRF, audit, render template, jam."""

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.admin import auth
from app.bot.pengaturan import muat_pengaturan
from app.clock import SystemClock
from app.config import get_settings
from app.db import get_sessionmaker
from app.models import Admin, AdminAudit, BotState

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


class PerluLogin(Exception):  # noqa: N818
    pass


def get_db() -> Iterator[Session]:
    with get_sessionmaker()() as db:
        yield db


def jam_nyata() -> datetime:
    return SystemClock().now()


def sekarang(db: Session) -> datetime:
    """Jam yang dipakai halaman admin: jam palsu bot di dev (FAKE_NOW/TICK_SECONDS), selain itu jam nyata."""
    st = db.get(BotState, 1)
    if get_settings().jam_palsu and st is not None and st.last_tick_at is not None:
        return st.last_tick_at
    return jam_nyata()


async def wajib_login(request: Request, db: Session = Depends(get_db)) -> auth.SesiAdmin:
    sesi = auth.baca_token(request.cookies.get(auth.COOKIE), jam_nyata())
    if sesi is None or db.get(Admin, sesi.admin_id) is None:
        raise PerluLogin()
    if request.method == "POST":
        form = await request.form()
        token = request.headers.get("X-CSRF-Token") or form.get("csrf")
        if not isinstance(token, str) or not auth.hmac.compare_digest(token, sesi.csrf):
            raise HTTPException(403, "Token CSRF tidak valid. Muat ulang halaman lalu coba lagi.")
    request.state.sesi = sesi
    return sesi


def audit(db: Session, action: str, **detail: Any) -> None:
    db.add(AdminAudit(at=jam_nyata(), action=action, detail=detail))


def kembali(path: str, ok: str | None = None, err: str | None = None):
    from fastapi.responses import RedirectResponse

    q = {k: v for k, v in {"ok": ok, "err": err}.items() if v}
    sambung = "&" if "?" in path else "?"
    return RedirectResponse(path + (sambung + urlencode(q) if q else ""), status_code=303)


def render(request: Request, db: Session, nama: str, aktif: str, **ctx: Any):
    st = db.get(BotState, 1)
    sesi: auth.SesiAdmin | None = getattr(request.state, "sesi", None)
    p = muat_pengaturan(db)
    return templates.TemplateResponse(
        request,
        nama,
        {
            "aktif": aktif,
            "bot": st,
            "csrf": sesi.csrf if sesi else "",
            "mode_uji": p.mode_uji,
            "plurk_mode": get_settings().plurk_mode,
            "ok": request.query_params.get("ok"),
            "err": request.query_params.get("err"),
            "now": sekarang(db),
            **ctx,
        },
    )
