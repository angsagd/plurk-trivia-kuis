"""Proses bot: tidur sampai detik ke-0 tiap menit (WIB), jalankan satu tick, ulangi.
Tick selalu berurutan. SIGTERM/SIGINT: tick yang sedang berjalan diselesaikan dulu."""

import logging
import signal
import threading

from app.bot.tick import jalankan_tick
from app.clock import FakeClock, SystemClock, awal_menit, detik_ke_menit_berikutnya
from app.config import Settings, get_settings

log = logging.getLogger("app.bot")


def jalankan(settings: Settings, berhenti: threading.Event, maks_tick: int | None = None) -> int:
    """Kembalikan jumlah tick yang dijalankan."""
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    jumlah = 0

    if settings.jam_palsu:
        sistem = SystemClock().now()
        clock = FakeClock(settings.fake_now or awal_menit(sistem))
        log.info("jam palsu mulai %s, 1 tick (= 1 menit) tiap %s detik", clock.now(), settings.tick_seconds)
        while not berhenti.is_set() and (maks_tick is None or jumlah < maks_tick):
            jalankan_tick(clock.now(), settings.data_dir)
            jumlah += 1
            if berhenti.wait(settings.tick_seconds):
                break
            clock.advance(minutes=1)
    else:
        clock = SystemClock()
        log.info("jam sistem, tick tiap detik ke-0 (WIB)")
        while not berhenti.is_set() and (maks_tick is None or jumlah < maks_tick):
            if berhenti.wait(detik_ke_menit_berikutnya(clock.now())):
                break
            jalankan_tick(awal_menit(clock.now()), settings.data_dir)
            jumlah += 1

    log.info("bot berhenti setelah %d tick", jumlah)
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
