"""Aplikasi admin web (FastAPI + Jinja2 + HTMX). Satu akun admin; semua halaman wajib login."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from app.admin import auth
from app.admin.deps import PerluLogin, audit, get_db, jam_nyata, templates
from app.admin.routes import dashboard, libur, log, pengaturan, peringkat, perintah, riwayat, soal
from app.config import get_settings
from app.db import get_sessionmaker
from app.perintah import pastikan_perintah_bawaan


@asynccontextmanager
async def lifespan(_app: FastAPI):
    auth._kunci()  # gagal cepat bila APP_SECRET_KEY kosong
    with get_sessionmaker()() as db:
        pastikan_perintah_bawaan(db)
        db.commit()
    yield


app = FastAPI(
    title="Plurk Trivia Kuis — Admin", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")

CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
    "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
)


@app.middleware("http")
async def header_keamanan(request: Request, call_next):
    r = await call_next(request)
    r.headers.setdefault("Content-Security-Policy", CSP)
    r.headers.setdefault("X-Frame-Options", "DENY")
    r.headers.setdefault("X-Content-Type-Options", "nosniff")
    r.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.url.path != "/health" and not request.url.path.startswith("/static"):
        r.headers.setdefault("Cache-Control", "no-store")
    return r


@app.exception_handler(PerluLogin)
async def ke_login(request: Request, _exc: PerluLogin):
    if request.headers.get("HX-Request"):
        return HTMLResponse("", headers={"HX-Redirect": "/login"})
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
def halaman_login(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "login.html", {"err": request.query_params.get("err")})


@app.post("/login")
def login(
    request: Request,
    username: str = Form(""),
    password: str = Form(""),
    totp: str = Form(""),
    db: Session = Depends(get_db),
):
    now = jam_nyata()
    if auth.login_diblokir(db, now):
        audit(db, "login_diblokir", username=username[:64])
        db.commit()
        return RedirectResponse("/login?err=Terlalu+banyak+login+gagal.+Coba+lagi+15+menit+lagi.", 303)
    admin = auth.verifikasi(db, username, password, totp)
    if admin is None:
        audit(db, "login_gagal", username=username[:64], ip=request.client.host if request.client else None)
        db.commit()
        return RedirectResponse("/login?err=Username,+password,+atau+kode+TOTP+salah.", 303)
    admin.last_login_at = now
    audit(db, "login", username=admin.username)
    db.commit()
    r = RedirectResponse("/", status_code=303)
    r.set_cookie(
        auth.COOKIE,
        auth.buat_token(admin.id, now),
        max_age=int(auth.UMUR_SESI.total_seconds()),
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="strict",
    )
    return r


@app.post("/logout")
def logout(sesi: auth.SesiAdmin = Depends(dashboard.wajib_login), db: Session = Depends(get_db)):
    audit(db, "logout")
    db.commit()
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(auth.COOKIE)
    return r


for modul in (dashboard, peringkat, soal, pengaturan, libur, riwayat, perintah, log):
    app.include_router(modul.router)
