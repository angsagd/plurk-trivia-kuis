"""Query untuk halaman admin (dashboard, peringkat, stok soal)."""

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta

from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.models import GameSession, Player, Question, Response, Score, ScoreAdjustment, SessionQuestion, Topic

NAMA_FASE = ("Soal", "Clue 1", "Clue 2", "Clue 3")


@dataclass
class BarisPeringkat:
    player_id: int
    nick: str
    skor: int
    benar: int
    sesi_ikut: int
    rata_fase: str
    diblokir: bool


def tabel_peringkat(
    db: Session,
    dari: date | None,
    sampai: date | None,
    topik_id: int | None = None,
    cari: str | None = None,
) -> list[BarisPeringkat]:
    q = (
        select(Score.player_id, func.sum(Score.points), func.count(), func.avg(SessionQuestion.winner_phase))
        .join(SessionQuestion, SessionQuestion.id == Score.session_question_id)
        .join(Question, Question.id == SessionQuestion.question_id)
        .group_by(Score.player_id)
    )
    if dari:
        q = q.where(Score.play_date >= dari)
    if sampai:
        q = q.where(Score.play_date <= sampai)
    if topik_id:
        q = q.where(Question.topic_id == topik_id)
    data: dict[int, list] = {pid: [skor, benar, fase] for pid, skor, benar, fase in db.execute(q)}

    if not topik_id:  # koreksi admin tidak terkait topik
        qa = select(ScoreAdjustment.player_id, func.sum(ScoreAdjustment.points)).group_by(
            ScoreAdjustment.player_id
        )
        if dari:
            qa = qa.where(ScoreAdjustment.week_start >= dari - timedelta(days=6))
        if sampai:
            qa = qa.where(ScoreAdjustment.week_start <= sampai)
        for pid, poin in db.execute(qa):
            data.setdefault(pid, [0, 0, None])[0] += poin

    qs = (
        select(Response.player_id, func.count(distinct(Response.session_id)))
        .join(GameSession, GameSession.id == Response.session_id)
        .group_by(Response.player_id)
    )
    if dari:
        qs = qs.where(GameSession.play_date >= dari)
    if sampai:
        qs = qs.where(GameSession.play_date <= sampai)
    sesi = dict(db.execute(qs).all())

    pemain = {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(data)))} if data else {}
    hasil = []
    for pid, (skor, benar, fase) in data.items():
        p = pemain[pid]
        if cari and cari.lower() not in p.nick.lower():
            continue
        hasil.append(
            BarisPeringkat(
                pid,
                p.nick,
                int(skor),
                int(benar),
                sesi.get(pid, 0),
                NAMA_FASE[round(fase)] if fase is not None else "—",
                p.is_blocked,
            )  # fmt: skip
        )
    hasil.sort(key=lambda b: (b.diblokir, -b.skor, b.nick.lower()))
    return hasil


@dataclass
class StokTopik:
    topik: Topic
    total: int
    sisa: int
    peluang: float


def stok_topik(db: Session) -> list[StokTopik]:
    hasil = []
    for t in db.scalars(select(Topic).order_by(Topic.number)):
        total = db.scalar(select(func.count()).where(Question.topic_id == t.id, Question.is_active)) or 0
        sisa = (
            db.scalar(
                select(func.count()).where(
                    Question.topic_id == t.id, Question.is_active, Question.used_cycle < t.cycle
                )
            )
            or 0
        )
        hasil.append(StokTopik(t, total, sisa, 0.0))
    bobot = sum(s.total for s in hasil if s.topik.is_active) or 1
    for s in hasil:
        s.peluang = s.total / bobot if s.topik.is_active else 0.0
    return hasil


def ringkasan_hari(db: Session, hari: date) -> dict:
    sesi_ids = list(db.scalars(select(GameSession.id).where(GameSession.play_date == hari)))
    if not sesi_ids:
        return {"pemain": 0, "jawaban": 0, "diabaikan": 0, "tampil": 0, "terjawab": 0, "fase_umum": "—"}
    r = select(Response).where(Response.session_id.in_(sesi_ids))
    jawaban = db.scalar(select(func.count()).select_from(r.subquery())) or 0
    pemain = db.scalar(
        select(func.count(distinct(Response.player_id))).where(Response.session_id.in_(sesi_ids))
    )
    diabaikan = db.scalar(
        select(func.count()).where(
            Response.session_id.in_(sesi_ids), Response.status.in_(["lewat_batas", "terlalu_panjang"])
        )
    )
    sq = db.scalars(
        select(SessionQuestion).where(
            SessionQuestion.session_id.in_(sesi_ids), SessionQuestion.step != "belum"
        )
    ).all()
    fase = Counter(x.winner_phase for x in sq if x.winner_phase is not None)
    return {
        "pemain": pemain or 0,
        "jawaban": jawaban,
        "diabaikan": diabaikan or 0,
        "tampil": len(sq),
        "terjawab": sum(1 for x in sq if x.winner_player_id),
        "fase_umum": NAMA_FASE[fase.most_common(1)[0][0]] if fase else "—",
    }


def detail_pemain(db: Session, pemain: Player, hari_ini: date) -> dict:
    total = db.scalar(select(func.sum(Score.points)).where(Score.player_id == pemain.id)) or 0
    total += (
        db.scalar(select(func.sum(ScoreAdjustment.points)).where(ScoreAdjustment.player_id == pemain.id)) or 0
    )
    # juara mingguan: minggu yang sudah selesai, pemain ini di posisi #1
    per_minggu: dict[date, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for pid, ws, poin in db.execute(select(Score.player_id, Score.week_start, Score.points)):
        per_minggu[ws][pid] += poin
    for pid, ws, poin in db.execute(
        select(ScoreAdjustment.player_id, ScoreAdjustment.week_start, ScoreAdjustment.points)
    ):
        per_minggu[ws][pid] += poin
    juara = sum(
        1
        for ws, skor in per_minggu.items()
        if ws + timedelta(days=5) < hari_ini and skor and max(skor, key=lambda k: skor[k]) == pemain.id
    )
    menang = db.execute(
        select(
            Question.jawaban,
            Topic.name,
            SessionQuestion.winner_phase,
            SessionQuestion.points,
            GameSession.play_date,
        )
        .join(Question, Question.id == SessionQuestion.question_id)
        .join(Topic, Topic.id == Question.topic_id)
        .join(GameSession, GameSession.id == SessionQuestion.session_id)
        .where(SessionQuestion.winner_player_id == pemain.id)
        .order_by(SessionQuestion.id.desc())
    ).all()
    topik = Counter(m[1] for m in menang)
    koreksi = db.scalars(
        select(ScoreAdjustment)
        .where(ScoreAdjustment.player_id == pemain.id)
        .order_by(ScoreAdjustment.id.desc())
    ).all()
    return {
        "total": total,
        "juara": juara,
        "topik_terkuat": topik.most_common(1)[0][0] if topik else "—",
        "menang": menang[:10],
        "koreksi": koreksi,
    }
