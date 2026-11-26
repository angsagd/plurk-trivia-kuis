"""Simulator pemain untuk dev & tes ketahanan (hanya dengan FakePlurk).

Setiap putaran, untuk tiap thread yang belum die:
- hold  : dengan peluang `balas`, satu pemain bilang "siap".
- soal  : tiap pemain dengan peluang `balas` membalas; jawaban benar dengan peluang `benar`.
"""

import random
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GameSession, SessionQuestion
from app.plurk.fake import FakePlurk

TEBAKAN_SALAH = ["apa ya", "hmm", "JAKARTA", "MERAPI", "wkwk", "SURABAYA", "🤔", "BANDUNG", "TORAJA"]
SAPAAN = ["siap!", "ikut", "hadir 🙋", "gas", "ayo"]


@dataclass(frozen=True)
class PemainSim:
    plurk_user_id: int
    nick: str


def putaran(
    db: Session,
    fake: FakePlurk,
    pemain: list[PemainSim],
    rng: random.Random,
    *,
    benar: float,
    balas: float,
    waktu: datetime,
) -> int:
    jumlah = 0
    for sesi in db.scalars(
        select(GameSession).where(GameSession.status != "die", GameSession.plurk_id.is_not(None))
    ):
        assert sesi.plurk_id is not None
        if sesi.status == "hold":
            if rng.random() < balas:
                p = rng.choice(pemain)
                fake.inject_response(sesi.plurk_id, p.plurk_user_id, p.nick, rng.choice(SAPAAN), waktu)
                jumlah += 1
            continue
        if not sesi.step.startswith("f"):
            continue
        sq = db.scalar(
            select(SessionQuestion).where(
                SessionQuestion.session_id == sesi.id, SessionQuestion.number == sesi.question_count
            )
        )
        if sq is None:
            continue
        for p in pemain:
            if rng.random() < balas:
                teks = sq.question.jawaban.lower() if rng.random() < benar else rng.choice(TEBAKAN_SALAH)
                fake.inject_response(sesi.plurk_id, p.plurk_user_id, p.nick, teks, waktu)
                jumlah += 1
    return jumlah
