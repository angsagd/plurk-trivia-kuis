"""Perintah lewat mention (tahap 8). Lihat "Perintah lewat mention" di CLAUDE.md.

Langkah 5 tiap tick : baca alert 'mentioned' -> saring -> simpan ke command_requests (status awal).
Langkah 9 tiap tick : kirim antrean 'antre' hanya pada sisa jatah posting setelah sesi; isi jawaban dihitung
                      saat dikirim; tertunda > kedaluwarsa_menit -> 'kedaluwarsa'.
Setiap alert hanya diproses sekali (unik plurk_id + response_id), jadi hasil edit plurk diabaikan.
"""

import logging
import random
import time
from collections import Counter, defaultdict
from datetime import timedelta

from sqlalchemy import func, select

from app.bot import messages
from app.bot.outbox import PRIORITAS_PERINTAH, antre
from app.bot.peringkat import peringkat
from app.core.commands import parse_perintah
from app.core.schedule import minggu_klasemen
from app.models import (
    Command,
    CommandAlias,
    CommandRequest,
    CommandResponse,
    GameSession,
    Outbox,
    Player,
    Score,
    ScoreAdjustment,
    SessionQuestion,
)
from app.plurk.client import Mention, PlurkError, tautan_plurk

log = logging.getLogger(__name__)

MAKS_MENTION_PER_TICK = 10
UMUR_CACHE_TEMAN = 600  # detik
NAMA_FASE = ("Soal", "Clue 1", "Clue 2", "Clue 3")
_cache_teman: dict[int, tuple[float, set[int]]] = {}  # id(plurk client) -> (waktu, id teman)


def _teman(k) -> set[int]:
    kunci = id(k.plurk)
    ada = _cache_teman.get(kunci)
    if ada is None or time.monotonic() - ada[0] > UMUR_CACHE_TEMAN:
        ada = (time.monotonic(), k.plurk.get_friend_ids())
        _cache_teman[kunci] = ada
    return ada[1]


def _cari_perintah(db, kata: str) -> Command | None:
    cmd = db.scalar(select(Command).where(Command.key == kata))
    if cmd is None:
        alias = db.scalar(select(CommandAlias).where(CommandAlias.alias == kata))
        cmd = db.get(Command, alias.command_id) if alias else None
    return cmd


def _teks_mention(k, m: Mention) -> tuple[str, int]:
    """(teks mention, owner_id plurk)."""
    info = k.plurk.get_plurk(m.plurk_id)
    if not m.response_id:
        return info.content, info.owner_id
    for r in k.plurk.get_responses(m.plurk_id, 0):
        if r.id == m.response_id:
            return r.content, info.owner_id
    raise PlurkError(f"balasan {m.response_id} tidak ditemukan di plurk {m.plurk_id}")


def baca_mention(k) -> int:
    """Langkah 5. Kembalikan jumlah mention baru yang dicatat."""
    db, p, now = k.db, k.p, k.now
    if not p.perintah_aktif:
        return 0
    try:
        mentions = sorted(k.plurk.get_mentions(), key=lambda m: (m.posted, m.plurk_id, m.response_id))
    except PlurkError as e:
        log.warning("gagal membaca mention: %s", e)
        return 0
    thread_kuis = set(db.scalars(select(GameSession.plurk_id).where(GameSession.plurk_id.is_not(None))))
    nick_bot = k.plurk.whoami().nick
    dicatat = 0
    for m in mentions:
        if dicatat >= MAKS_MENTION_PER_TICK:
            break
        sudah = db.scalar(
            select(CommandRequest.id).where(
                CommandRequest.plurk_id == m.plurk_id, CommandRequest.response_id == m.response_id
            )
        )
        if sudah:
            continue
        req = CommandRequest(
            plurk_id=m.plurk_id, response_id=m.response_id, received_at=m.posted, status="diabaikan"
        )
        db.add(req)
        dicatat += 1
        if m.user_id == k.bot_id:
            continue
        if now - m.posted > timedelta(minutes=p.perintah_kedaluwarsa_menit):
            req.status = "kedaluwarsa"  # mis. alert lama saat fitur baru dinyalakan
            continue
        if m.plurk_id in thread_kuis:
            continue  # di dalam thread kuis: mention = balasan biasa
        try:
            teks, pemilik = _teks_mention(k, m)
        except PlurkError as e:
            log.warning("mention %s/%s tidak terbaca: %s", m.plurk_id, m.response_id, e)
            continue
        req.text = teks[:300]
        kata = parse_perintah(teks, nick_bot)
        req.keyword = kata
        if kata is None:
            continue
        cmd = _cari_perintah(db, kata)
        if cmd is None:
            continue  # kata kunci tidak dikenal: diabaikan diam-diam

        pemain = db.scalar(select(Player).where(Player.plurk_user_id == m.user_id))
        if pemain is None:
            pemain = Player(plurk_user_id=m.user_id, nick=m.nick or str(m.user_id), first_seen=m.posted)
            db.add(pemain)
            db.flush()
        req.player_id, req.command_id = pemain.id, cmd.id

        if not cmd.enabled:
            req.status = "nonaktif"
        elif pemain.is_blocked:
            req.status = "diblokir"
        elif pemilik != k.bot_id and (pemilik not in _teman(k) or m.user_id not in _teman(k)):
            req.status = "bukan_teman"
        elif db.scalar(
            select(CommandRequest.id).where(
                CommandRequest.player_id == pemain.id,
                CommandRequest.command_id == cmd.id,
                CommandRequest.status.in_(["antre", "dijawab"]),
                CommandRequest.received_at > m.posted - timedelta(minutes=p.perintah_cooldown_menit),
            )
        ):
            req.status = "cooldown"
        elif (
            db.scalar(
                select(func.count()).where(
                    CommandRequest.status.in_(["antre", "dijawab"]),
                    CommandRequest.received_at > now - timedelta(hours=1),
                )
            )
            or 0
        ) >= p.perintah_batas_global_per_jam:
            req.status = "batas_global"
        else:
            req.status = "antre"
        db.flush()
    db.commit()
    return dicatat


def kirim_antrean(k) -> int:
    """Langkah 9: jawab antrean memakai SISA jatah posting tick ini. Kembalikan jumlah terkirim."""
    db, p, now = k.db, k.p, k.now
    # Sinkron status dari outbox (jawaban yang tertunda anti-flood lalu terkirim di tick lain).
    for req in db.scalars(
        select(CommandRequest).where(CommandRequest.status == "antre", CommandRequest.outbox_id.is_not(None))
    ):
        ob = db.get(Outbox, req.outbox_id)
        if ob is not None and ob.status == "sent":
            req.status, req.sent_at = "dijawab", ob.sent_at
        elif ob is not None and ob.status == "failed":
            req.status = "kedaluwarsa"
    db.commit()

    terkirim = 0
    for req in db.scalars(
        select(CommandRequest).where(CommandRequest.status == "antre", CommandRequest.outbox_id.is_(None))
        .order_by(CommandRequest.received_at)
    ).all():  # fmt: skip
        if now - req.received_at > timedelta(minutes=p.perintah_kedaluwarsa_menit):
            req.status = "kedaluwarsa"
            continue
        if k.pengirim.sisa <= 0 or not p.perintah_aktif:
            break
        cmd = db.get(Command, req.command_id) if req.command_id else None
        pemain = db.get(Player, req.player_id) if req.player_id else None
        if cmd is None or pemain is None or not cmd.enabled:
            req.status = "nonaktif"
            continue
        teks = jawab(k, cmd, pemain)
        ob = antre(
            db, f"cmd:{req.id}", teks, now, target_plurk_id=req.plurk_id, qualifier=p.qualifier,
            priority=PRIORITAS_PERINTAH,
        )  # fmt: skip
        req.outbox_id = ob.id
        db.commit()
        k.pengirim.kirim(db, prioritas_maks=PRIORITAS_PERINTAH)
        db.refresh(ob)
        if ob.status == "sent":
            req.status, req.sent_at = "dijawab", ob.sent_at
            terkirim += 1
    db.commit()
    return terkirim


# ---------------------------------------------------------------- isi jawaban


def _sesi_berikutnya(k) -> str:
    mulai, _ = k.p.jadwal.sesi_berikutnya(k.now)
    return messages.format_sesi_berikutnya(mulai, k.now)


def _rekor(db, pemain: Player) -> tuple[str, str]:
    mingguan: dict = defaultdict(int)
    for ws, poin in db.execute(select(Score.week_start, Score.points).where(Score.player_id == pemain.id)):
        mingguan[ws] += poin
    for ws, poin in db.execute(
        select(ScoreAdjustment.week_start, ScoreAdjustment.points).where(
            ScoreAdjustment.player_id == pemain.id
        )
    ):
        mingguan[ws] += poin
    from app.models import Question, Response

    tercepat = None
    for sq, jawaban, posted in db.execute(
        select(SessionQuestion, Question.jawaban, Response.posted_at)
        .join(Question, Question.id == SessionQuestion.question_id)
        .join(Response, Response.plurk_response_id == SessionQuestion.winner_response_id)
        .where(SessionQuestion.winner_player_id == pemain.id)
    ):
        if sq.started_at is None:
            continue
        detik = max(0, int((posted - sq.started_at).total_seconds()))
        if tercepat is None or detik < tercepat[0]:
            tercepat = (detik, jawaban)
    rekor = str(max(mingguan.values())) if mingguan else "0"
    return rekor, (f"{tercepat[0]} detik ({tercepat[1]})" if tercepat else "-")


def _streak(db, pemain: Player) -> int:
    n = 0
    for s in db.scalars(
        select(GameSession).where(GameSession.ever_ran_question).order_by(GameSession.id.desc())
    ):
        menang = any(q.winner_player_id == pemain.id for q in s.questions)
        if menang:
            n += 1
        elif s.status != "die":
            continue  # sesi yang masih berjalan belum memutus streak
        else:
            break
    return n


def jawab(k, cmd: Command, pemain: Player) -> str:
    db, now, batas = k.db, k.now, k.p.batas_teks
    # Semua isian yang dikenal untuk jenis ini default kosong, agar template lama/ubahan admin tidak
    # pernah menampilkan "{isian}" mentah ke pemain.
    from app.perintah import ISIAN

    nilai: dict[str, object] = {x.strip("{}"): "" for x in ISIAN.get(cmd.kind, "").split()}
    nilai |= {"nama": pemain.nick, "sesi_berikutnya": _sesi_berikutnya(k)}
    template = cmd.template or ""

    if cmd.kind == "kustom":
        pilihan = db.scalars(select(CommandResponse.body).where(CommandResponse.command_id == cmd.id)).all()
        template = random.choice(pilihan) if pilihan else ""
    elif cmd.key == "jadwal":
        berjalan = db.scalar(
            select(GameSession)
            .where(GameSession.status != "die", GameSession.plurk_id.is_not(None))
            .order_by(GameSession.id.desc())
        )
        if berjalan is not None and berjalan.plurk_id is not None:
            return messages.render(
                db,
                "perintah_jadwal_berlangsung",
                batas,
                **(nilai | {"tautan_sesi": tautan_plurk(berjalan.plurk_id)}),
            )
    elif cmd.key in ("klasemen", "rank"):
        minggu = minggu_klasemen(now.date())  # Selasa -> hasil final minggu lalu
        semua = peringkat(db, week_start=minggu, limit=None)
        if cmd.key == "klasemen":
            if not semua:
                return messages.render(db, "perintah_klasemen_kosong", batas, **nilai)
            nilai["top10"] = messages.format_daftar(semua[:10])
        else:
            posisi = next((i for i, (nick, _) in enumerate(semua) if nick == pemain.nick), None)
            if posisi is None:
                return messages.render(db, "perintah_rank_kosong", batas, **nilai)
            poin = semua[posisi][1]
            if posisi == 0:
                return messages.render(db, "perintah_rank_satu", batas, **(nilai | {"poin": poin}))
            nilai |= {
                "rank": posisi + 1,
                "poin": poin,
                "selisih": semua[posisi - 1][1] - poin,
                "rank_atas": posisi,
            }
    elif cmd.key == "bantuan":
        kunci = db.scalars(
            select(Command.key).where(Command.enabled, Command.show_in_help).order_by(Command.key)
        )
        nilai["daftar_bantuan"] = ", ".join(kunci)
    elif cmd.key == "rekor":
        nilai["rekor_mingguan"], nilai["tercepat"] = _rekor(db, pemain)
    elif cmd.key == "streak":
        nilai["streak"] = _streak(db, pemain)
    elif cmd.key == "statistik":
        fase = Counter(
            db.scalars(
                select(SessionQuestion.winner_phase).where(SessionQuestion.winner_player_id == pemain.id)
            )
        )
        nilai["total_benar"] = sum(fase.values())
        nilai["fase_favorit"] = NAMA_FASE[fase.most_common(1)[0][0]] if fase else "-"

    try:
        teks = " ".join(template.format_map(messages._Aman(nilai)).split(" ")).strip()
    except (ValueError, IndexError):
        teks = template
    return teks if len(teks) <= batas else teks[: batas - 1] + "…"


def kosongkan_cache_teman() -> None:
    _cache_teman.clear()
