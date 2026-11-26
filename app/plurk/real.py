"""RealPlurk: Plurk API 2.0 lewat OAuth 1.0a (HMAC-SHA1). Dokumentasi: https://www.plurk.com/API

Hal yang BELUM terbukti dan harus diuji di tahap 4 (akun uji + mode uji privat):
- urutan ID balasan naik sesuai urutan masuk (get_responses mengurutkan menurut ID);
- arti `from_response` (offset atau ID); karena itu semua balasan diambil lalu disaring ID > setelah_id;
- format error untuk token tidak valid (dokumentasi hanya menyebut HTTP 400 + error_text);
- qualifier ':' (freestyle) diterima API; batas panjang teks (perkiraan 360).
"""

import json
import logging
from email.utils import parsedate_to_datetime
from typing import Any, Protocol

from requests import RequestException
from requests_oauthlib import OAuth1Session

from app.clock import ke_wib
from app.config import Settings
from app.plurk.client import AntiFlood, PlurkError, PlurkResponse, PlurkUser, TokenDitolak

log = logging.getLogger(__name__)

BASE_URL = "https://www.plurk.com"
TIMEOUT_DETIK = 20
ANONIM_USER_ID = 99999

# Potongan error_text yang menandakan token/kredensial tidak berlaku (selain HTTP 401).
_TANDA_TOKEN = ("invalid access token", "invalid token", "token_rejected", "oauth", "40101", "40106")


class _HttpSession(Protocol):
    def post(self, url: str, data: dict[str, Any], timeout: float) -> Any: ...


class RealPlurk:
    def __init__(self, settings: Settings, session: _HttpSession | None = None):
        kunci = {
            "PLURK_CONSUMER_KEY": settings.plurk_consumer_key,
            "PLURK_CONSUMER_SECRET": settings.plurk_consumer_secret,
            "PLURK_ACCESS_TOKEN": settings.plurk_access_token,
            "PLURK_ACCESS_SECRET": settings.plurk_access_secret,
        }
        kosong = [k for k, v in kunci.items() if v is None or not v.get_secret_value()]
        if session is None and kosong:
            raise ValueError(f"Kredensial Plurk belum diisi di .env: {', '.join(kosong)}")
        self._session: _HttpSession = session or OAuth1Session(
            client_key=_rahasia(settings.plurk_consumer_key),
            client_secret=_rahasia(settings.plurk_consumer_secret),
            resource_owner_key=_rahasia(settings.plurk_access_token),
            resource_owner_secret=_rahasia(settings.plurk_access_secret),
            signature_method="HMAC-SHA1",
        )
        self._saya: PlurkUser | None = None

    # ------------------------------------------------------------ HTTP

    def _panggil(self, path: str, **params: Any) -> Any:
        data = {k: v for k, v in params.items() if v is not None}
        try:
            r = self._session.post(BASE_URL + path, data=data, timeout=TIMEOUT_DETIK)
        except RequestException as e:
            raise PlurkError(f"{path}: koneksi gagal ({type(e).__name__})") from e

        try:
            isi = r.json()
        except ValueError:
            isi = None
        pesan = isi.get("error_text", "") if isinstance(isi, dict) else ""

        if r.status_code == 401 or (r.status_code in (400, 403) and _tanda_token(pesan)):
            raise TokenDitolak(f"{path}: {pesan or r.status_code}")
        if r.status_code >= 400 or (isinstance(isi, dict) and "error_text" in isi):
            if pesan.startswith("anti-flood"):
                raise AntiFlood(f"{path}: {pesan}")
            raise PlurkError(f"{path}: HTTP {r.status_code} {pesan or _potong(getattr(r, 'text', ''))}")
        if isi is None:
            raise PlurkError(f"{path}: jawaban bukan JSON")
        return isi

    # ------------------------------------------------------------ PlurkClient

    def whoami(self) -> PlurkUser:
        """Akun bot (di-cache per proses: cukup satu panggilan /APP/Users/me)."""
        if self._saya is None:
            isi = self._panggil("/APP/Users/me")
            self._saya = PlurkUser(int(isi["id"]), str(isi["nick_name"]))
        return self._saya

    def add_plurk(
        self, content: str, qualifier: str = ":", limited_to: list[int] | None = None, no_comments: int = 0
    ) -> int:
        isi = self._panggil(
            "/APP/Timeline/plurkAdd",
            content=content,
            qualifier=qualifier,
            limited_to=json.dumps(limited_to) if limited_to else None,
            no_comments=no_comments or None,
        )
        return int(isi["plurk_id"])

    def add_response(self, plurk_id: int, content: str, qualifier: str = ":") -> int:
        isi = self._panggil(
            "/APP/Responses/responseAdd", plurk_id=plurk_id, content=content, qualifier=qualifier
        )
        return int(isi["id"])

    def get_responses(self, plurk_id: int, setelah_id: int = 0) -> list[PlurkResponse]:
        isi = self._panggil("/APP/Responses/get", plurk_id=plurk_id, from_response=0)
        pengguna = isi.get("friends") or {}
        hasil = []
        for r in isi.get("responses") or []:
            rid = int(r["id"])
            if rid <= setelah_id:
                continue
            uid = int(r["user_id"])
            if uid == ANONIM_USER_ID:
                nick = str(r.get("handle") or "anonim")
            else:
                info = pengguna.get(str(uid)) or {}
                nick = str(info.get("nick_name") or uid)
            hasil.append(
                PlurkResponse(
                    id=rid,
                    plurk_id=int(r.get("plurk_id") or plurk_id),
                    user_id=uid,
                    nick=nick,
                    content=str(
                        r.get("content_raw") if r.get("content_raw") is not None else r.get("content", "")
                    ),
                    posted=ke_wib(parsedate_to_datetime(r["posted"])),
                )
            )
        hasil.sort(key=lambda x: x.id)
        return hasil

    def accept_friends(self) -> None:
        self._panggil("/APP/Alerts/addAllAsFriends")


def _rahasia(nilai) -> str:
    return nilai.get_secret_value() if nilai is not None else ""


def _tanda_token(pesan: str) -> bool:
    p = pesan.lower()
    return any(t in p for t in _TANDA_TOKEN)


def _potong(teks: str, n: int = 200) -> str:
    return teks if len(teks) <= n else teks[:n] + "…"
