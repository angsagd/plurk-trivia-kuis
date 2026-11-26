"""Konfigurasi dari environment (.env / .env.dev), dibaca lewat pydantic-settings."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_ignore_empty=True, extra="ignore")

    plurk_mode: Literal["real", "fake"] = "fake"
    plurk_consumer_key: SecretStr | None = None
    plurk_consumer_secret: SecretStr | None = None
    plurk_access_token: SecretStr | None = None
    plurk_access_secret: SecretStr | None = None

    app_secret_key: SecretStr | None = None
    app_timezone: str = "Asia/Jakarta"
    db_path: Path = Path("/app/data/kuis.db")

    fake_now: datetime | None = None
    tick_seconds: int = 60

    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None

    @property
    def data_dir(self) -> Path:
        return self.db_path.parent

    @property
    def jam_palsu(self) -> bool:
        """Jam palsu dipakai bila FAKE_NOW diisi atau tick dipercepat."""
        return self.fake_now is not None or self.tick_seconds != 60

    @model_validator(mode="after")
    def _cek(self) -> "Settings":
        if self.tick_seconds < 1:
            raise ValueError("TICK_SECONDS minimal 1")
        if self.plurk_mode == "real" and self.jam_palsu:
            raise ValueError("PLURK_MODE=real tidak boleh memakai FAKE_NOW / TICK_SECONDS selain 60")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
