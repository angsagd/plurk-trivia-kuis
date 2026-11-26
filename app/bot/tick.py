"""Satu tick bot (urutan kerja: lihat CLAUDE.md "Urutan kerja satu tick")."""

import logging
import random
import time
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import Engine

from app import notifikasi
from app.bot import engine as mesin
from app.bot import libur, mention
from app.bot.outbox import Pengirim
from app.bot.pengaturan import muat_pengaturan
from app.clock import Clock, FakeClock, SystemClock
from app.db import get_sessionmaker, sesi_db
from app.models import BotState
from app.plurk.client import PlurkClient

log = logging.getLogger(__name__)

TERIMA_TEMAN_TIAP = 10


def jalankan_tick(
    now: datetime,
    engine: Engine,
    plurk: PlurkClient,
    *,
    clock: Clock | None = None,
    tidur: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
) -> None:
    clock = clock or FakeClock(now)
    with get_sessionmaker(engine)() as db:
        # 1. detak
        st = db.get_one(BotState, 1)
        st.last_tick_at, st.heartbeat_at = now, SystemClock().now()
        st.tick_count += 1
        db.commit()
        log.info(
            "tick #%d %s WIB, status bot: %s", st.tick_count, now.strftime("%a %Y-%m-%d %H:%M"), st.status
        )

        p = muat_pengaturan(db)
        pengirim = Pengirim(
            plurk,
            clock,
            maks_per_tick=p.maks_posting_per_tick,
            jeda_detik=p.jeda_posting_detik,
            maks_gagal=p.maks_gagal_kirim,
            tidur=tidur,
        )
        # 2. lanjutkan rangkaian posting yang tertunda
        pengirim.kirim(db)
        db.refresh(st)
        if st.status == "hentikan":
            # "Hentikan sekarang" dari admin/CLI: semua thread die (langkah 11), lalu berhenti.
            k = mesin.Konteks(db, plurk, pengirim, p, now, plurk.whoami().id, rng or random.Random())
            mesin.hentikan_sekarang(k)
            pengirim.kirim(db)
            return
        # 3. berhenti -> selesai
        if st.status == "berhenti":
            return
        # 4. terima pertemanan tiap 10 tick
        if st.tick_count % TERIMA_TEMAN_TIAP == 0:
            try:
                plurk.accept_friends()
            except Exception:
                log.exception("accept_friends gagal")

        k = mesin.Konteks(db, plurk, pengirim, p, now, plurk.whoami().id, rng or random.Random())
        # 5. mention -> antrean perintah (juga di hari libur). Error di sini tidak boleh mengganggu sesi.
        _aman(db, "baca mention", lambda: mention.baca_mention(k))
        # 6. hari libur: posting terjadwal + juara mingguan (Selasa)
        if not p.jadwal.hari_aktif_pada(now.date()):
            libur.proses(k)
        # 7. majukan setiap thread yang belum die (juga di hari libur, agar thread yang melewati
        #    tengah malam tetap selesai). Thread lain tetap diproses walau satu thread error.
        for sesi in mesin.thread_hidup(db):
            try:
                mesin.majukan_thread(k, sesi)
            except Exception as e:
                db.rollback()
                log.exception("thread sesi %d gagal", sesi.id)
                catat_error(engine, f"sesi {sesi.id}: {type(e).__name__}: {e}")
                notifikasi.kirim("error_thread", f"Thread sesi {sesi.id} error: {type(e).__name__}: {e}")
        # 6/8. hari aktif + status aktif + slot sesi tiba -> buka thread baru (jeda: tidak)
        db.refresh(st)
        if st.status == "aktif":
            slot = p.jadwal.slot_sesi(now, p.toleransi_slot_menit)
            if slot is not None:
                mesin.buka_sesi(k, slot)
        # 9. sisa jatah posting -> jawaban perintah (prioritas rendah)
        _aman(db, "kirim antrean perintah", lambda: mention.kirim_antrean(k))


def _aman(db, nama: str, fungsi) -> None:
    try:
        fungsi()
    except Exception as e:
        db.rollback()
        log.exception("%s gagal", nama)
        notifikasi.kirim(f"error_{nama}", f"{nama} gagal: {type(e).__name__}: {e}")


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
