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
    "juara_mingguan": "🏆 Juara minggu ini ({rentang}): {juara}!\n{top10}",
    # Variasi jawaban perintah lewat mention (template utama ada di tabel commands)
    "perintah_jadwal_berlangsung": "Sesi sedang berlangsung, ayo ikut: {tautan_sesi}",
    "perintah_rank_kosong": "{nama} belum punya poin minggu ini. Ikut sesi berikutnya {sesi_berikutnya}!",
    "perintah_rank_satu": "Kamu #1 minggu ini ({poin} poin)! Sesi berikutnya {sesi_berikutnya}.",
    "perintah_klasemen_kosong": "Belum ada skor minggu ini. Sesi berikutnya {sesi_berikutnya}.",
}

# Nama tampilan & isian yang tersedia per template (untuk halaman admin).
LABEL_TEMPLATE: dict[str, tuple[str, str]] = {
    "sesi_baru": ("Plurk sesi (01)", "{hari} {tanggal} {sesi} {jam} {maks_soal}"),
    "top10": ("Top 10 mingguan (02)", "{top10}"),
    "top10_kosong": ("Top 10 kosong (02, minggu baru)", ""),
    "ajakan": ("Ajakan siap (03)", ""),
    "siap_soal": ("Siap soal (04)", "{n}"),
    "soal": ("Soal (05)", "{n} {soal}"),
    "clue1": ("Clue 1", "{clue}"),
    "clue2": ("Clue 2", "{clue}"),
    "clue3": ("Clue 3", "{clue}"),
    "pemenang": ("Pemenang soal", "{nama} {jawaban} {skor}"),
    "jawaban_dibuka": ("Jawaban dibuka", "{jawaban}"),
    "menunggu": ("Kuis menunggu peserta (10b2)", ""),
    "ranking_hari_ini": ("Ranking hari ini (11)", "{ranking}"),
    "farewell": ("Farewell", "{sesi_berikutnya}"),
    "farewell_sudah_mulai": ("Farewell, sesi berikutnya sudah dimulai", "{tautan}"),
    "juara_mingguan": ("Juara mingguan (Selasa)", "{rentang} {juara} {top10}"),
    "perintah_jadwal_berlangsung": ("Perintah jadwal: sesi sedang berlangsung", "{nama} {tautan_sesi}"),
    "perintah_rank_kosong": ("Perintah rank: belum ada poin", "{nama} {sesi_berikutnya}"),
    "perintah_rank_satu": ("Perintah rank: peringkat #1", "{nama} {poin} {sesi_berikutnya}"),
    "perintah_klasemen_kosong": ("Perintah klasemen: belum ada skor", "{sesi_berikutnya}"),
}

CONTOH_ISIAN: dict[str, object] = {
    "hari": "Senin", "tanggal": "30 November 2026", "sesi": 2, "jam": "14.00", "maks_soal": 10,
    "top10": "1. pemain_a — 42\n2. pemain_b — 37\n3. pemain_c — 21", "n": 4,
    "soal": "Pulau di Indonesia yang dijuluki Pulau Dewata?", "clue": "Terkenal dengan Pura Tanah Lot",
    "nama": "pemain_a", "jawaban": "BALI", "skor": 4, "ranking": "1. pemain_a — 12\n2. pemain_b — 8",
    "sesi_berikutnya": "hari ini 16.00 WIB", "tautan": "https://www.plurk.com/p/abc123",
    "rentang": "25–30 November", "juara": "pemain_a", "tautan_sesi": "https://www.plurk.com/p/abc123",
    "poin": 42,
}  # fmt: skip


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
