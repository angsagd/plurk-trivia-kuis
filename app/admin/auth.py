"""Login admin: argon2 + TOTP opsional, cookie sesi bertanda tangan HMAC, token CSRF, batas login gagal.

Cookie `kuis_sesi` = base64url(JSON {a: admin_id, t: dibuat, n: nonce}) + "." + HMAC-SHA256(APP_SECRET_KEY).
Token CSRF diturunkan dari nonce sesi (HMAC), dikirim lewat field form `csrf` atau header `X-CSRF-Token`.
"""

import base64
import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Admin, AdminAudit

COOKIE = "kuis_sesi"
UMUR_SESI = timedelta(hours=12)
MAKS_GAGAL = 5
JENDELA_GAGAL = timedelta(minutes=15)
_PH = PasswordHasher()


@dataclass(frozen=True)
class SesiAdmin:
    admin_id: int
    nonce: str
    csrf: str


def _kunci() -> bytes:
    k = get_settings().app_secret_key
    if k is None or len(k.get_secret_value()) < 32:
        raise RuntimeError("APP_SECRET_KEY wajib diisi (minimal 32 karakter acak) untuk admin web")
    return k.get_secret_value().encode()


def _tanda(data: bytes) -> str:
    return hmac.new(_kunci(), data, hashlib.sha256).hexdigest()


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(teks: str) -> bytes:
    return base64.urlsafe_b64decode(teks + "=" * (-len(teks) % 4))


def buat_token(admin_id: int, now: datetime) -> str:
    isi = _b64(json.dumps({"a": admin_id, "t": int(now.timestamp()), "n": secrets.token_hex(16)}).encode())
    return f"{isi}.{_tanda(isi.encode())}"


def baca_token(token: str | None, now: datetime) -> SesiAdmin | None:
    if not token or token.count(".") != 1:
        return None
    isi, tanda = token.split(".")
    if not hmac.compare_digest(tanda, _tanda(isi.encode())):
        return None
    try:
        data = json.loads(_unb64(isi))
        admin_id, dibuat, nonce = int(data["a"]), int(data["t"]), str(data["n"])
    except (ValueError, KeyError, TypeError):
        return None
    if now.timestamp() - dibuat > UMUR_SESI.total_seconds() or dibuat > now.timestamp() + 60:
        return None
    return SesiAdmin(admin_id, nonce, _tanda(f"csrf:{nonce}".encode())[:32])


def login_diblokir(db: Session, now: datetime) -> bool:
    gagal = db.scalar(
        select(func.count())
        .select_from(AdminAudit)
        .where(AdminAudit.action == "login_gagal", AdminAudit.at >= now - JENDELA_GAGAL)
    )
    return (gagal or 0) >= MAKS_GAGAL


def verifikasi(db: Session, username: str, password: str, kode_totp: str) -> Admin | None:
    """Admin bila username, password, dan (bila aktif) kode TOTP benar."""
    admin = db.scalar(select(Admin).where(Admin.username == username))
    if admin is None:
        _PH.hash(password)  # samakan waktu proses dengan username yang ada
        return None
    try:
        _PH.verify(admin.password_hash, password)
    except (VerificationError, InvalidHashError):
        return None
    if admin.totp_secret and not pyotp.TOTP(admin.totp_secret).verify(kode_totp.strip(), valid_window=1):
        return None
    if _PH.check_needs_rehash(admin.password_hash):
        admin.password_hash = _PH.hash(password)
    return admin
