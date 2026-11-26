"""Template pesan bot. Teks bawaan di sini; admin bisa menimpanya lewat tabel `templates` (key sama)."""

import logging
from datetime import date, datetime

from sqlalchemy.orm import Session

from app.core.schedule import NAMA_HARI
from app.models import Template

log = logging.getLogger(__name__)

NAMA_BULAN = "Januari Februari Maret April Mei Juni Juli Agustus September Oktober November Desember".split()

TEMPLATE_BAWAAN: dict[str, str] = {
    "sesi_baru": (
        "🎯 Kuis Trivia {hari}, {tanggal} · Sesi {sesi} ({jam} WIB)\n"
        "Maksimal {maks_soal} soal. Jawab lewat balasan; jawaban benar pertama yang menang!"
    ),
    "top10": "🏆 Top 10 minggu ini:\n{top10}",
    "top10_kosong": "🏆 Minggu baru dimulai, papan skor masih kosong. Ayo jadi yang pertama!",
    "ajakan": "Katakan sesuatu jika Anda siap.",
    "siap_soal": "Siap-siap, soal #{n}…",
    "soal": "❓ Soal #{n}: {soal}",
    "clue1": "💡 Clue 1: {clue}",
    "clue2": "💡 Clue 2: {clue}",
    "clue3": "💡 Clue 3: {clue}",
    "pemenang": "✅ {nama} benar! Jawabannya {jawaban}. +{skor} poin.",
    "jawaban_dibuka": "⌛ Belum ada yang benar. Jawabannya: {jawaban}",
    "menunggu": "Kuis menunggu peserta. Katakan sesuatu jika Anda siap.",
    "ranking_hari_ini": "📊 Peringkat hari ini:\n{ranking}",
    "farewell": "Terima kasih sudah bermain! Sesi berikutnya: {sesi_berikutnya}.",
    "farewell_sudah_mulai": "Terima kasih sudah bermain! Sesi berikutnya sudah dimulai: {tautan}",
}


class _Aman(dict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


def format_jam(dt: datetime) -> str:
    return dt.strftime("%H.%M")


def format_tanggal(d: date) -> str:
    return f"{d.day} {NAMA_BULAN[d.month - 1]} {d.year}"


def format_sesi_berikutnya(mulai: datetime, now: datetime) -> str:
    """'hari ini 14.00 WIB' / 'besok 12.00 WIB' / 'Rabu, 2 Desember 2026 12.00 WIB'."""
    selisih = (mulai.date() - now.date()).days
    if selisih == 0:
        hari = "hari ini"
    elif selisih == 1:
        hari = "besok"
    else:
        hari = f"{NAMA_HARI[mulai.weekday()]}, {format_tanggal(mulai.date())}"
    return f"{hari} {format_jam(mulai)} WIB"


def format_daftar(baris: list[tuple[str, int]]) -> str:
    return "\n".join(f"{i}. {nama} — {poin}" for i, (nama, poin) in enumerate(baris, start=1))


def render(db: Session, key: str, batas: int, **nilai: object) -> str:
    """Isi template; teks yang melebihi batas karakter Plurk dipotong dengan '…'."""
    t = db.get(Template, key)
    teks = (t.body if t else TEMPLATE_BAWAAN[key]).format_map(_Aman(nilai))
    if len(teks) > batas:
        log.warning("template %s %d karakter, dipotong ke %d", key, len(teks), batas)
        teks = teks[: batas - 1] + "…"
    return teks
