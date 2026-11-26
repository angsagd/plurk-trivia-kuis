"""Koneksi SQLite (mode WAL) dan tipe kolom waktu WIB."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Engine, String, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.types import TypeDecorator

from app.clock import WIB


class WaktuWIB(TypeDecorator[datetime]):
    """Datetime berzona, disimpan sebagai teks ISO WIB lebar tetap
    ('2026-11-30T12:00:00.000000+07:00') sehingga urutan teks = urutan waktu."""

    impl = String(32)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> str | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("waktu tanpa zona tidak boleh disimpan; pakai Clock")
        return value.astimezone(WIB).isoformat(timespec="microseconds")

    def process_result_value(self, value: str | None, dialect) -> datetime | None:
        return None if value is None else datetime.fromisoformat(value).astimezone(WIB)


class Base(DeclarativeBase):
    pass


def buat_engine(db_path: Path | str) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}")

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    return engine


@lru_cache
def get_engine() -> Engine:
    from app.config import get_settings

    path = get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return buat_engine(path)


def get_sessionmaker(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(engine or get_engine(), expire_on_commit=False)


@contextmanager
def sesi_db(engine: Engine | None = None) -> Iterator[Session]:
    """Satu transaksi: commit bila sukses, rollback bila error."""
    with get_sessionmaker(engine)() as s:
        try:
            yield s
            s.commit()
        except BaseException:
            s.rollback()
            raise
