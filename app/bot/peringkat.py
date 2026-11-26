"""Peringkat = penjumlahan baris `scores` pada rentang tanggal (+ koreksi admin untuk mingguan)."""

from collections import defaultdict
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Player, Score, ScoreAdjustment


def peringkat(
    db: Session, *, play_date: date | None = None, week_start: date | None = None, limit: int | None = 10
) -> list[tuple[str, int]]:
    """[(nick, poin)] urut poin turun lalu nick. Pemain diblokir tidak ditampilkan."""
    total: dict[int, int] = defaultdict(int)
    q = select(Score.player_id, func.sum(Score.points)).group_by(Score.player_id)
    if play_date is not None:
        q = q.where(Score.play_date == play_date)
    if week_start is not None:
        q = q.where(Score.week_start == week_start)
        adj = (
            select(ScoreAdjustment.player_id, func.sum(ScoreAdjustment.points))
            .where(ScoreAdjustment.week_start == week_start)
            .group_by(ScoreAdjustment.player_id)
        )
        for pid, poin in db.execute(adj):
            total[pid] += poin
    for pid, poin in db.execute(q):
        total[pid] += poin

    if not total:
        return []
    pemain = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(total)))}
    hasil = [
        (pemain[pid].nick, poin) for pid, poin in total.items() if not pemain[pid].is_blocked and poin > 0
    ]
    hasil.sort(key=lambda x: (-x[1], x[0].lower()))
    return hasil[:limit] if limit else hasil
