"""Satu tick bot. Tahap 2: catat last_tick_at / heartbeat di bot_state.
Urutan kerja lengkap (outbox, thread, perintah) menyusul di tahap 3; lihat CLAUDE.md."""

import logging
from datetime import datetime

from sqlalchemy import Engine

from app.clock import SystemClock
from app.db import sesi_db
from app.models import BotState

log = logging.getLogger(__name__)


def jalankan_tick(now: datetime, engine: Engine) -> None:
    with sesi_db(engine) as db:
        st = db.get_one(BotState, 1)
        # 1. last_tick_at = sekarang
        st.last_tick_at = now
        st.heartbeat_at = SystemClock().now()
        st.tick_count += 1
        log.info(
            "tick #%d %s WIB, status bot: %s", st.tick_count, now.strftime("%a %Y-%m-%d %H:%M"), st.status
        )


def catat_error(engine: Engine, pesan: str) -> None:
    try:
        with sesi_db(engine) as db:
            st = db.get_one(BotState, 1)
            st.last_error = pesan[:2000]
            st.last_error_at = SystemClock().now()
    except Exception:  # database sendiri bermasalah: cukup log
        log.exception("gagal mencatat error ke bot_state")


def sehat(engine: Engine, batas_detik: int = 180) -> bool:
    """Bot sehat bila heartbeat (jam nyata) < 3 menit."""
    with sesi_db(engine) as db:
        st = db.get(BotState, 1)
        if st is None or st.heartbeat_at is None:
            return False
        return (SystemClock().now() - st.heartbeat_at).total_seconds() < batas_detik
