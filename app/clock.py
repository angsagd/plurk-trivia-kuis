"""Sumber waktu. Kode lain TIDAK memanggil datetime.now() langsung; selalu lewat Clock.
Semua waktu dalam WIB (Asia/Jakarta), apa pun zona waktu server."""

from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

WIB = ZoneInfo("Asia/Jakarta")


def ke_wib(dt: datetime) -> datetime:
    """Waktu tanpa zona dianggap sudah WIB; waktu berzona dikonversi ke WIB."""
    return dt.replace(tzinfo=WIB) if dt.tzinfo is None else dt.astimezone(WIB)


def awal_menit(dt: datetime) -> datetime:
    return dt.replace(second=0, microsecond=0)


def detik_ke_menit_berikutnya(dt: datetime) -> float:
    """Sisa detik sampai detik ke-0 menit berikutnya (selalu > 0)."""
    return (awal_menit(dt) + timedelta(minutes=1) - dt).total_seconds()


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(WIB)


class FakeClock:
    """Jam palsu untuk dev & tes: diam sampai dimajukan."""

    def __init__(self, start: datetime):
        self._now = ke_wib(start)

    def now(self) -> datetime:
        return self._now

    def set(self, dt: datetime) -> None:
        self._now = ke_wib(dt)

    def advance(self, **kwargs: float) -> datetime:
        self._now += timedelta(**kwargs)
        return self._now
