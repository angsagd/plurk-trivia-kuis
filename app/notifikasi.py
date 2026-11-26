"""Notifikasi ke admin lewat Telegram (opsional: aktif bila TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID diisi).

- Tidak pernah melempar error ke pemanggil dan tidak memblokir tick (dikirim di thread latar).
- Jenis yang sama paling banyak sekali per `JEDA_SAMA` (anti-spam), per proses.
"""

import logging
import threading
import time
from collections.abc import Callable
from functools import lru_cache

import requests

from app.config import get_settings

log = logging.getLogger(__name__)
JEDA_SAMA = 3600  # detik
API = "https://api.telegram.org/bot{token}/sendMessage"


class Notifier:
    def __init__(
        self,
        token: str | None,
        chat_id: str | None,
        kirim_http: Callable[[str, dict], None] | None = None,
        latar: bool = True,
    ):
        self.token, self.chat_id = token, chat_id
        self._kirim_http = kirim_http or self._post
        self._latar = latar
        self._terakhir: dict[str, float] = {}
        self._kunci = threading.Lock()

    @property
    def aktif(self) -> bool:
        return bool(self.token and self.chat_id)

    def _post(self, url: str, data: dict) -> None:
        requests.post(url, data=data, timeout=10).raise_for_status()

    def _kirim(self, teks: str) -> None:
        try:
            self._kirim_http(API.format(token=self.token), {"chat_id": self.chat_id, "text": teks})
        except Exception as e:  # jaringan / token Telegram salah: cukup log (tanpa URL yang memuat token)
            log.warning("notifikasi Telegram gagal: %s", type(e).__name__)

    def kirim(self, jenis: str, teks: str, paksa: bool = False) -> bool:
        """True bila pesan dijadwalkan terkirim (bukan diredam anti-spam / nonaktif)."""
        log.warning("NOTIFIKASI [%s] %s", jenis, teks)
        if not self.aktif:
            return False
        with self._kunci:
            sekarang = time.monotonic()
            if not paksa and sekarang - self._terakhir.get(jenis, -JEDA_SAMA - 1) < JEDA_SAMA:
                return False
            self._terakhir[jenis] = sekarang
        isi = f"[Kuis Plurk] {teks}"[:4000]
        if self._latar:
            threading.Thread(target=self._kirim, args=(isi,), daemon=True).start()
        else:
            self._kirim(isi)
        return True

    def reset(self, jenis: str) -> None:
        with self._kunci:
            self._terakhir.pop(jenis, None)


@lru_cache
def get_notifier() -> Notifier:
    s = get_settings()
    token = s.telegram_bot_token.get_secret_value() if s.telegram_bot_token else None
    return Notifier(token, s.telegram_chat_id)


def kirim(jenis: str, teks: str, paksa: bool = False) -> bool:
    return get_notifier().kirim(jenis, teks, paksa)
