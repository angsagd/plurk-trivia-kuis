"""Hari libur (Selasa & Jumat): posting terjadwal dari admin + juara mingguan otomatis tiap Selasa."""

from datetime import time, timedelta

from sqlalchemy import select

from app.bot import messages
from app.bot.outbox import antre
from app.bot.peringkat import peringkat
from app.core.schedule import SELASA, awal_minggu
from app.models import ScheduledPost

JAM_JUARA_MINGGUAN = time(12, 0)


def proses(k) -> None:
    """Antre posting yang jatuh tempo lalu kirim (dalam jatah tick)."""
    db, now = k.db, k.now
    for sp in db.scalars(
        select(ScheduledPost).where(ScheduledPost.status == "terjadwal", ScheduledPost.run_at <= now)
    ):
        row = antre(
            db,
            f"libur:{sp.id}",
            sp.content,
            now,
            kind="plurk",
            qualifier=sp.qualifier,
            limited_to=list(k.p.mode_uji_limited_to) if k.p.mode_uji else None,
            no_comments=0 if sp.allow_comments else 1,
        )
        sp.status, sp.outbox_id = "antre", row.id

    if now.weekday() == SELASA and now.time() >= JAM_JUARA_MINGGUAN:
        minggu_lalu = awal_minggu(now.date()) - timedelta(days=7)
        top = peringkat(db, week_start=minggu_lalu, limit=10)
        if top:
            antre(
                db,
                f"juara:{minggu_lalu.isoformat()}",
                k.teks(
                    "juara_mingguan",
                    rentang=f"{minggu_lalu.day}–{(minggu_lalu + timedelta(days=5)).day} "
                    f"{messages.NAMA_BULAN[(minggu_lalu + timedelta(days=5)).month - 1]}",
                    juara=top[0][0],
                    top10=messages.format_daftar(top),
                ),
                now,
                kind="plurk",
                qualifier=k.p.qualifier,
                limited_to=list(k.p.mode_uji_limited_to) if k.p.mode_uji else None,
            )
    db.commit()
    k.pengirim.kirim(db)


def status_tampil(sp: ScheduledPost, outbox_status: str | None) -> str:
    if sp.status == "antre":
        return {"sent": "terkirim", "failed": "gagal"}.get(outbox_status or "", "antre")
    return sp.status
