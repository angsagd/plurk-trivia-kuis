from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import Settings, get_settings
from app.db import buat_engine, get_engine

ROOT = Path(__file__).resolve().parents[1]
_VARIABEL = [f.upper() for f in Settings.model_fields]


@pytest.fixture(autouse=True)
def _env_bersih(monkeypatch):
    """Tes tidak boleh terpengaruh .env.dev / .env milik kontainer."""
    for nama in _VARIABEL:
        monkeypatch.delenv(nama, raising=False)
    get_settings.cache_clear()
    get_engine.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()


def migrasi(db_path: Path) -> None:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.attributes["configure_logger"] = False
    command.upgrade(cfg, "head")


@pytest.fixture
def db_path(tmp_path, monkeypatch) -> Path:
    """Database baru hasil `alembic upgrade head`; DB_PATH ikut diarahkan ke sana."""
    path = tmp_path / "tes.db"
    migrasi(path)
    monkeypatch.setenv("DB_PATH", str(path))
    return path


@pytest.fixture
def engine(db_path):
    e = buat_engine(db_path)
    yield e
    e.dispose()
