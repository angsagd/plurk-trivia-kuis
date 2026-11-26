"""RealPlurk (OAuth 1.0a ke Plurk API 2.0) dibuat di tahap 4."""

from app.plurk.client import PlurkUser


class RealPlurk:
    def __init__(self, *args, **kwargs):
        raise NotImplementedError("RealPlurk belum tersedia (tahap 4). Pakai PLURK_MODE=fake.")

    def whoami(self) -> PlurkUser:  # pragma: no cover
        raise NotImplementedError
