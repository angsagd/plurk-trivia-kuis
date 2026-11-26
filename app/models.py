"""Model database (19 tabel). Waktu selalu WaktuWIB; tanggal main (play_date, week_start) = date WIB.
Nilai status disimpan sebagai teks; daftar nilai yang sah ada di komentar tiap kolom."""

from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, WaktuWIB

# ---------------------------------------------------------------- pengaturan & status bot


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(WaktuWIB())


class BotState(Base):
    """Selalu satu baris (id = 1), dibuat oleh migrasi pertama."""

    __tablename__ = "bot_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="berhenti")  # aktif / jeda / berhenti
    last_tick_at: Mapped[datetime | None] = mapped_column(WaktuWIB())  # waktu Clock (bisa jam palsu di dev)
    heartbeat_at: Mapped[datetime | None] = mapped_column(WaktuWIB())  # jam nyata, untuk healthcheck
    tick_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(WaktuWIB())


# ---------------------------------------------------------------- bank soal


class Topic(Base):
    __tablename__ = "topics"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(2), unique=True)  # dari nama file, '01'-'99'
    name: Mapped[str] = mapped_column(String(100))  # dari nama file, mis. 'Sejarah Dunia'
    name_key: Mapped[str] = mapped_column(String(100), unique=True)  # name.casefold() = identitas topik
    filename: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    cycle: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(WaktuWIB())
    updated_at: Mapped[datetime] = mapped_column(WaktuWIB())

    questions: Mapped[list["Question"]] = relationship(back_populates="topic")


class Question(Base):
    __tablename__ = "questions"
    __table_args__ = (
        UniqueConstraint("topic_id", "text_hash"),
        Index("ix_questions_topic_used_cycle", "topic_id", "used_cycle"),
        Index("ix_questions_text_hash", "text_hash"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    text_hash: Mapped[str] = mapped_column(String(64))
    soal: Mapped[str] = mapped_column(Text)
    clue: Mapped[str] = mapped_column(Text)
    jawaban: Mapped[str] = mapped_column(String(40))
    letters: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    used_cycle: Mapped[int] = mapped_column(Integer, default=0)
    times_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(WaktuWIB())
    updated_at: Mapped[datetime] = mapped_column(WaktuWIB())

    topic: Mapped[Topic] = relationship(back_populates="questions")


# ---------------------------------------------------------------- pemain, sesi, balasan, skor


class Player(Base):
    __tablename__ = "players"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plurk_user_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    nick: Mapped[str] = mapped_column(String(64))
    display_name: Mapped[str | None] = mapped_column(String(128))
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    first_seen: Mapped[datetime] = mapped_column(WaktuWIB())


class GameSession(Base):
    """Satu sesi = satu thread (plurk). State per thread disimpan di sini."""

    __tablename__ = "sessions"
    __table_args__ = (UniqueConstraint("play_date", "slot"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    play_date: Mapped[date] = mapped_column(Date)  # tanggal WIB
    slot: Mapped[int] = mapped_column(Integer)  # nomor sesi hari itu (1-5)
    plurk_id: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(8), default="hold")  # hold / active / die
    posted_at: Mapped[datetime | None] = mapped_column(WaktuWIB())  # awal umur thread
    step: Mapped[str] = mapped_column(String(16), default="01")  # langkah alur (01-11)
    question_count: Mapped[int] = mapped_column(Integer, default=0)
    cycle_start_response_id: Mapped[int | None] = mapped_column(BigInteger)
    last_response_id: Mapped[int | None] = mapped_column(BigInteger)  # balasan terakhir yang terbaca
    ever_ran_question: Mapped[bool] = mapped_column(Boolean, default=False)
    test_mode: Mapped[bool] = mapped_column(Boolean, default=False)
    ended_at: Mapped[datetime | None] = mapped_column(WaktuWIB())

    questions: Mapped[list["SessionQuestion"]] = relationship(
        back_populates="session", order_by="SessionQuestion.number"
    )


class SessionQuestion(Base):
    __tablename__ = "session_questions"
    __table_args__ = (UniqueConstraint("session_id", "number"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    number: Mapped[int] = mapped_column(Integer)  # 1-10
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"))
    step: Mapped[str] = mapped_column(String(16), default="belum")  # belum / fase0-3 / selesai
    marker_ids: Mapped[list[int]] = mapped_column(JSON, default=list)  # ID balasan bot: soal, clue1-3
    reveal_response_id: Mapped[int | None] = mapped_column(BigInteger)  # balasan "jawaban dibuka"
    winner_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    winner_response_id: Mapped[int | None] = mapped_column(BigInteger)
    winner_phase: Mapped[int | None] = mapped_column(Integer)
    points: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime | None] = mapped_column(WaktuWIB())
    ended_at: Mapped[datetime | None] = mapped_column(WaktuWIB())

    session: Mapped[GameSession] = relationship(back_populates="questions")
    question: Mapped[Question] = relationship()


class Response(Base):
    """Semua balasan pemain di thread kuis (balasan bot sendiri tidak disimpan)."""

    __tablename__ = "responses"
    __table_args__ = (Index("ix_responses_sq_plurk", "session_question_id", "plurk_response_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plurk_response_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"), index=True)
    session_question_id: Mapped[int | None] = mapped_column(ForeignKey("session_questions.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    content: Mapped[str] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(WaktuWIB())
    phase: Mapped[int | None] = mapped_column(Integer)
    # benar / salah / lewat_batas / terlalu_panjang / di_luar_soal / diblokir; NULL = di luar siklus soal
    status: Mapped[str | None] = mapped_column(String(16))


class Score(Base):
    """Satu baris per poin yang didapat; peringkat = jumlah pada rentang tanggal."""

    __tablename__ = "scores"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    session_question_id: Mapped[int] = mapped_column(ForeignKey("session_questions.id"), unique=True)
    points: Mapped[int] = mapped_column(Integer)
    play_date: Mapped[date] = mapped_column(Date, index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)  # Rabu awal periode


class ScoreAdjustment(Base):
    __tablename__ = "score_adjustments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    week_start: Mapped[date] = mapped_column(Date, index=True)
    points: Mapped[int] = mapped_column(Integer)  # boleh negatif
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(WaktuWIB())


# ---------------------------------------------------------------- posting


class Template(Base):
    __tablename__ = "templates"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    body: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(WaktuWIB())


class Outbox(Base):
    __tablename__ = "outbox"
    __table_args__ = (Index("ix_outbox_status_id", "status", "id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(128), unique=True)  # mis. 'sesi:12:soal:3:clue1'
    kind: Mapped[str] = mapped_column(String(16))  # plurk / response
    priority: Mapped[int] = mapped_column(Integer, default=0)  # 0 = sesi, 1 = jawaban perintah
    session_id: Mapped[int | None] = mapped_column(ForeignKey("sessions.id"))
    target_plurk_id: Mapped[int | None] = mapped_column(BigInteger)
    content: Mapped[str] = mapped_column(Text)
    qualifier: Mapped[str] = mapped_column(String(16), default=":")
    limited_to: Mapped[list[int] | None] = mapped_column(JSON)
    no_comments: Mapped[int] = mapped_column(Integer, default=0)  # Plurk: 0 boleh, 1 nonaktif, 2 teman
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending / sent / failed / dibatalkan
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    result_id: Mapped[int | None] = mapped_column(BigInteger)  # plurk_id / response_id dari Plurk
    created_at: Mapped[datetime] = mapped_column(WaktuWIB())
    sent_at: Mapped[datetime | None] = mapped_column(WaktuWIB())


class ScheduledPost(Base):
    __tablename__ = "scheduled_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_at: Mapped[datetime] = mapped_column(WaktuWIB(), index=True)
    qualifier: Mapped[str] = mapped_column(String(16), default=":")
    content: Mapped[str] = mapped_column(Text)
    allow_comments: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(
        String(12), default="terjadwal"
    )  # terjadwal / terkirim / gagal / batal
    outbox_id: Mapped[int | None] = mapped_column(ForeignKey("outbox.id"))
    created_at: Mapped[datetime] = mapped_column(WaktuWIB())


# ---------------------------------------------------------------- admin


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(WaktuWIB(), index=True)
    action: Mapped[str] = mapped_column(String(64))
    detail: Mapped[Any] = mapped_column(JSON, default=dict)


class Admin(Base):
    __tablename__ = "admins"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    totp_secret: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(WaktuWIB())
    last_login_at: Mapped[datetime | None] = mapped_column(WaktuWIB())


# ---------------------------------------------------------------- perintah lewat mention


class Command(Base):
    __tablename__ = "commands"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(32), unique=True)
    kind: Mapped[str] = mapped_column(String(12))  # bawaan / statistik / kustom
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    show_in_help: Mapped[bool] = mapped_column(Boolean, default=False)
    template: Mapped[str | None] = mapped_column(Text)


class CommandAlias(Base):
    __tablename__ = "command_aliases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alias: Mapped[str] = mapped_column(String(32), unique=True)
    command_id: Mapped[int] = mapped_column(ForeignKey("commands.id", ondelete="CASCADE"))


class CommandResponse(Base):
    __tablename__ = "command_responses"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    command_id: Mapped[int] = mapped_column(ForeignKey("commands.id", ondelete="CASCADE"), index=True)
    body: Mapped[str] = mapped_column(Text)


class CommandRequest(Base):
    __tablename__ = "command_requests"
    __table_args__ = (
        UniqueConstraint("plurk_id", "response_id"),
        Index("ix_command_requests_cooldown", "player_id", "command_id", "received_at"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plurk_id: Mapped[int] = mapped_column(BigInteger)
    response_id: Mapped[int] = mapped_column(BigInteger, default=0)  # 0 = mention di plurk itu sendiri
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    command_id: Mapped[int | None] = mapped_column(ForeignKey("commands.id"))
    received_at: Mapped[datetime] = mapped_column(WaktuWIB())
    # antre / dijawab / cooldown / batas_global / kedaluwarsa / nonaktif / bukan_teman / diblokir
    status: Mapped[str] = mapped_column(String(16))
    outbox_id: Mapped[int | None] = mapped_column(ForeignKey("outbox.id"))
    sent_at: Mapped[datetime | None] = mapped_column(WaktuWIB())
