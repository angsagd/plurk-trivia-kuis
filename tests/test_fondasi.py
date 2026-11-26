"""Tes tahap 0: jam WIB, konfigurasi, loop bot, healthcheck, admin."""

import threading
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app import cli
from app.admin.main import app
from app.bot.loop import jalankan
from app.bot.tick import sehat
from app.clock import WIB, FakeClock, SystemClock, detik_ke_menit_berikutnya, ke_wib
from app.config import Settings


def test_system_clock_selalu_wib():
    now = SystemClock().now()
    assert now.tzinfo is WIB
    assert now.utcoffset().total_seconds() == 7 * 3600


def test_ke_wib():
    assert ke_wib(datetime(2026, 11, 30, 5, 0, tzinfo=UTC)) == datetime(2026, 11, 30, 12, 0, tzinfo=WIB)
    assert ke_wib(datetime(2026, 11, 30, 12, 0)).tzinfo is WIB


def test_fake_clock_maju():
    c = FakeClock(datetime(2026, 11, 30, 11, 58))
    c.advance(minutes=3)
    assert c.now() == datetime(2026, 11, 30, 12, 1, tzinfo=WIB)


@pytest.mark.parametrize("detik, harapan", [(0.0, 60.0), (59.5, 0.5), (30.25, 29.75)])
def test_detik_ke_menit_berikutnya(detik, harapan):
    dt = datetime(2026, 11, 30, 12, 0, tzinfo=WIB).replace(
        second=int(detik), microsecond=round((detik % 1) * 1_000_000)
    )
    assert detik_ke_menit_berikutnya(dt) == pytest.approx(harapan)


def test_config_real_tolak_jam_palsu():
    with pytest.raises(ValidationError):
        Settings(plurk_mode="real", tick_seconds=5)
    with pytest.raises(ValidationError):
        Settings(plurk_mode="real", fake_now=datetime(2026, 11, 30, 11, 58))
    assert not Settings(plurk_mode="real").jam_palsu


def test_config_env_kosong_diabaikan(monkeypatch):
    monkeypatch.setenv("FAKE_NOW", "")
    monkeypatch.setenv("TICK_SECONDS", "5")
    s = Settings()
    assert s.fake_now is None and s.tick_seconds == 5 and s.jam_palsu


def test_loop_jam_palsu_menjalankan_tick(db_path, engine, caplog):
    s = Settings(db_path=db_path, fake_now=datetime(2026, 11, 30, 11, 58), tick_seconds=1)
    caplog.set_level("INFO")
    # maks_tick=1: satu tick, tunggu 1 detik, lalu berhenti.
    assert jalankan(s, threading.Event(), maks_tick=1) == 1
    assert sehat(engine)
    assert "2026-11-30 11:58" in caplog.text


def test_loop_berhenti_saat_sinyal(db_path):
    s = Settings(db_path=db_path, tick_seconds=30)
    berhenti = threading.Event()
    t = threading.Timer(0.2, berhenti.set)
    t.start()
    assert jalankan(s, berhenti) == 1  # tick pertama selesai, lalu berhenti tanpa menunggu 30 detik
    t.cancel()


def test_tick_gagal_tidak_menghentikan_loop(tmp_path, caplog):
    # Database belum dimigrasi: tick gagal, loop tetap jalan dan mencatat error ke log.
    s = Settings(db_path=tmp_path / "kosong.db", fake_now=datetime(2026, 11, 30, 12, 0), tick_seconds=1)
    assert jalankan(s, threading.Event(), maks_tick=2) == 2
    assert "gagal" in caplog.text


def test_cli_health_bot(db_path, engine):
    assert cli.main(["health", "bot"]) == 1  # belum pernah tick
    from app.bot.tick import jalankan_tick
    from app.clock import SystemClock
    from app.plurk.fake import FakePlurk

    clock = SystemClock()
    jalankan_tick(clock.now(), engine, FakePlurk(clock))
    assert cli.main(["health", "bot"]) == 0


def test_admin_health():
    r = TestClient(app).get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}
