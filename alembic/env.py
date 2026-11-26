"""Alembic: database = DB_PATH dari app.config, atau sqlalchemy.url bila diisi (dipakai tes)."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy.types import TypeDecorator

from app import models  # noqa: F401  (mendaftarkan semua tabel)
from app.db import Base, buat_engine

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logger", True):
    fileConfig(config.config_file_name)


def render_item(type_, obj, autogen_context):
    """Tipe kustom (WaktuWIB) ditulis sebagai tipe dasarnya agar migrasi tidak bergantung kode app."""
    if type_ == "type" and isinstance(obj, TypeDecorator):
        return f"sa.{obj.impl!r}"
    return False


def _db_path() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url.removeprefix("sqlite:///")
    from app.config import get_settings

    path = get_settings().db_path
    path.parent.mkdir(parents=True, exist_ok=True)
    return str(path)


def run_migrations_online() -> None:
    engine = buat_engine(_db_path())
    with engine.connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=Base.metadata,
            render_as_batch=True,  # SQLite: ALTER TABLE lewat salin-tabel
            render_item=render_item,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Mode offline tidak dipakai; jalankan 'alembic upgrade head'.")
run_migrations_online()
