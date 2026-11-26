"""Outbox: semua posting ke Plurk lewat tabel `outbox` dengan dedupe_key.

- antre(): idempotent; dedupe_key yang sama tidak pernah membuat baris kedua.
- Pengirim.kirim(): kirim baris pending (prioritas, lalu urutan masuk) dalam batas posting per tick.
  Posting yang berhasil langsung di-commit, sehingga restart tidak mengulang posting yang sudah terkirim.
"""

import logging
from collections.abc import Callable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import notifikasi
from app.clock import Clock
from app.models import BotState, GameSession, Outbox
from app.plurk.client import PlurkClient, PlurkError, TokenDitolak

log = logging.getLogger(__name__)

PRIORITAS_SESI = 0
PRIORITAS_PERINTAH = 1


def antre(
    db: Session,
    dedupe_key: str,
    content: str,
    now: datetime,
    *,
    kind: str = "response",
    session_id: int | None = None,
    target_plurk_id: int | None = None,
    qualifier: str = ":",
    limited_to: list[int] | None = None,
    no_comments: int = 0,
    priority: int = PRIORITAS_SESI,
) -> Outbox:
    ada = db.scalar(select(Outbox).where(Outbox.dedupe_key == dedupe_key))
    if ada is not None:
        return ada
    row = Outbox(
        dedupe_key=dedupe_key,
        kind=kind,
        priority=priority,
        session_id=session_id,
        target_plurk_id=target_plurk_id,
        content=content,
        qualifier=qualifier,
        limited_to=limited_to,
        no_comments=no_comments,
        status="pending",
        attempts=0,
        created_at=now,
    )
    db.add(row)
    db.flush()
    return row


def hasil_kirim(db: Session, dedupe_key: str) -> int | None:
    """ID Plurk hasil posting yang sudah terkirim, atau None."""
    return db.scalar(select(Outbox.result_id).where(Outbox.dedupe_key == dedupe_key, Outbox.status == "sent"))


class Pengirim:
    def __init__(
        self,
        plurk: PlurkClient,
        clock: Clock,
        *,
        maks_per_tick: int,
        jeda_detik: float,
        maks_gagal: int,
        tidur: Callable[[float], None],
    ):
        self.plurk = plurk
        self.clock = clock
        self.maks_per_tick = maks_per_tick
        self.jeda_detik = jeda_detik
        self.maks_gagal = maks_gagal
        self.tidur = tidur
        self.terpakai = 0
        self.berhenti = False  # anti-flood / error lain: sisa posting dilanjutkan tick berikutnya

    @property
    def sisa(self) -> int:
        return 0 if self.berhenti else max(0, self.maks_per_tick - self.terpakai)

    def kirim(self, db: Session, prioritas_maks: int = PRIORITAS_SESI) -> int:
        """Kirim baris pending sampai jatah tick habis. Kembalikan jumlah posting terkirim."""
        terkirim = 0
        q = (
            select(Outbox)
            .where(Outbox.status == "pending", Outbox.priority <= prioritas_maks)
            .order_by(Outbox.priority, Outbox.id)
        )
        for row in db.scalars(q).all():
            if self.sisa <= 0:
                break
            target = row.target_plurk_id
            if row.kind == "response" and target is None and row.session_id is not None:
                target = db.get_one(GameSession, row.session_id).plurk_id
                if target is None:
                    continue  # plurk sesi belum terkirim; balasan menunggu
            if self.terpakai:
                self.tidur(self.jeda_detik)
            try:
                if row.kind == "plurk":
                    hasil = self.plurk.add_plurk(row.content, row.qualifier, row.limited_to, row.no_comments)
                else:
                    assert target is not None
                    hasil = self.plurk.add_response(target, row.content, row.qualifier)
            except TokenDitolak as e:
                self.berhenti = True
                st = db.get_one(BotState, 1)
                st.status = "berhenti"
                st.last_error = f"Token Plurk ditolak: {e}"
                st.last_error_at = self.clock.now()
                db.commit()
                log.error("token Plurk ditolak; bot dihentikan")
                notifikasi.kirim(
                    "token", "Token Plurk ditolak. Bot dihentikan; periksa .env lalu jalankan lagi."
                )
                break
            except PlurkError as e:
                self.berhenti = True
                row.attempts += 1
                row.last_error = f"{type(e).__name__}: {e}"
                if row.attempts >= self.maks_gagal:
                    row.status = "failed"
                    log.error("outbox %s gagal %d kali: %s", row.dedupe_key, row.attempts, e)
                    notifikasi.kirim("outbox_gagal", f"Posting {row.dedupe_key} gagal {row.attempts}x: {e}")
                else:
                    log.warning("outbox %s ditunda (%s), percobaan %d", row.dedupe_key, e, row.attempts)
                db.commit()
                break

            now = self.clock.now()
            row.status, row.result_id, row.sent_at, row.target_plurk_id = "sent", hasil, now, target
            if row.kind == "plurk" and row.session_id is not None:
                sesi = db.get_one(GameSession, row.session_id)
                sesi.plurk_id, sesi.posted_at = hasil, now
            db.commit()
            self.terpakai += 1
            terkirim += 1
        return terkirim
