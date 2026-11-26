"""Satu tick bot. Tahap 0: kerangka saja (catat waktu). Urutan kerja lengkap ada di CLAUDE.md."""

import logging
from datetime import datetime
from pathlib import Path

from app.bot import heartbeat

log = logging.getLogger(__name__)


def jalankan_tick(now: datetime, data_dir: Path) -> None:
    # 1. last_tick_at = sekarang
    heartbeat.tulis(data_dir)
    log.info("tick %s WIB", now.strftime("%a %Y-%m-%d %H:%M"))
