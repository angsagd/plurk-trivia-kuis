import pytest

from app.config import Settings, get_settings

_VARIABEL = [f.upper() for f in Settings.model_fields]


@pytest.fixture(autouse=True)
def _env_bersih(monkeypatch):
    """Tes tidak boleh terpengaruh .env.dev / .env milik kontainer."""
    for nama in _VARIABEL:
        monkeypatch.delenv(nama, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
