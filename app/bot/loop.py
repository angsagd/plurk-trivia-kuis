"""Proses bot: tidur sampai detik ke-0 tiap menit (WIB), jalankan satu tick, ulangi.
Tick selalu berurutan. SIGTERM/SIGINT: tick yang sedang berjalan diselesaikan dulu."""

import logging
import signal
import threading

from app import notifikasi
from app.bot.tick import catat_error, jalankan_tick
from app.clock import FakeClock, SystemClock, awal_menit, detik_ke_menit_berikutnya
from app.config import Settings, get_settings
from app.db import buat_engine
from app.plurk import buat_plurk

log = logging.getLogger("app.bot")


def jalankan(settings: Settings, berhenti: threading.Event, maks_tick: int | None = None) -> int:
    """Kembalikan jumlah tick yang dijalankan."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    engine = buat_engine(settings.db_path)
    jumlah = 0

    def tick(now) -> None:
        # Satu tick gagal tidak menghentikan loop; error dicatat ke bot_state.last_error.
        try:
            jalankan_tick(now, engine, plurk, clock=clock, tidur=tidur)
        except Exception as e:
            log.exception("tick %s gagal", now)
            catat_error(engine, f"{type(e).__name__}: {e}")
            notifikasi.kirim("error_tick", f"Tick gagal: {type(e).__name__}: {e}")

    clock: FakeClock | SystemClock
    if settings.jam_palsu:
        sistem = SystemClock().now()
        clock = FakeClock(settings.fake_now or awal_menit(sistem))
        # Jam palsu dipercepat: jeda antar posting ikut diperpendek.
        tidur = lambda detik: berhenti.wait(min(detik, settings.tick_seconds / 10))  # noqa: E731
    else:
        clock = SystemClock()
        tidur = berhenti.wait
    plurk = buat_plurk(settings, clock)

    if isinstance(clock, FakeClock):
        log.info("jam palsu mulai %s, 1 tick (= 1 menit) tiap %s detik", clock.now(), settings.tick_seconds)
        while not berhenti.is_set() and (maks_tick is None or jumlah < maks_tick):
            tick(clock.now())
            jumlah += 1
            if berhenti.wait(settings.tick_seconds):
                break
            clock.advance(minutes=1)
    else:
        log.info("jam sistem, tick tiap detik ke-0 (WIB)")
        while not berhenti.is_set() and (maks_tick is None or jumlah < maks_tick):
            if berhenti.wait(detik_ke_menit_berikutnya(clock.now())):
                break
            tick(awal_menit(clock.now()))
            jumlah += 1

    log.info("bot berhenti setelah %d tick", jumlah)
    engine.dispose()
    return jumlah


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    berhenti = threading.Event()

    def _sinyal(signum, _frame):
        log.info("sinyal %s diterima, menyelesaikan tick berjalan", signal.Signals(signum).name)
        berhenti.set()

    signal.signal(signal.SIGTERM, _sinyal)
    signal.signal(signal.SIGINT, _sinyal)
    jalankan(get_settings(), berhenti)


if __name__ == "__main__":
    main()
