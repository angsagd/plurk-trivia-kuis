"""Perintah bawaan & statistik (dibuat otomatis bila belum ada). Logika menjawab mention: tahap 8."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Command, CommandAlias

# key: (jenis, tampil di bantuan, sinonim, template)
BAWAAN: dict[str, tuple[str, bool, list[str], str]] = {
    "jadwal": ("bawaan", True, ["sesi"], "Sesi berikutnya {sesi_berikutnya}. {tautan_sesi}"),
    "klasemen": ("bawaan", True, ["top"], "🏆 Top 10 minggu ini:\n{top10}"),
    "rank": (
        "bawaan",
        True,
        ["peringkat", "skor", "poin"],
        "Kamu #{rank} minggu ini ({poin} poin), {selisih} poin di belakang #{rank_atas}. "
        "Sesi berikutnya {sesi_berikutnya}.",
    ),
    "aturan": (
        "bawaan",
        True,
        ["rule"],
        "Jawab soal lewat balasan di thread kuis. Jawaban benar pertama menang; "
        "makin sedikit clue, makin besar poin.",
    ),
    "bantuan": ("bawaan", True, ["help"], "Kata kunci: {daftar_bantuan}"),
    "rekor": (
        "statistik",
        False,
        [],
        "Rekor {nama}: skor mingguan tertinggi {rekor_mingguan}, tercepat {tercepat}.",
    ),
    "streak": ("statistik", False, [], "{nama} menang di {streak} sesi berturut-turut."),
    "statistik": (
        "statistik",
        False,
        [],
        "{nama}: {total_benar} jawaban benar, paling sering benar di {fase_favorit}.",
    ),
}
ISIAN = {
    "bawaan": (
        "{nama} {rank} {poin} {selisih} {rank_atas} {sesi_berikutnya} {tautan_sesi} {top10} {daftar_bantuan}"
    ),
    "statistik": "{nama} {rekor_mingguan} {tercepat} {streak} {total_benar} {fase_favorit}",
    "kustom": "{nama} {sesi_berikutnya}",
}
ALIAS_KHUSUS = {"?": "bantuan"}  # '?' berdiri sendiri = bantuan (tidak lolos pola kata kunci biasa)


def pastikan_perintah_bawaan(db: Session) -> None:
    for key, (jenis, bantuan, sinonim, template) in BAWAAN.items():
        cmd = db.scalar(select(Command).where(Command.key == key))
        if cmd is None:
            cmd = Command(key=key, kind=jenis, enabled=True, show_in_help=bantuan, template=template)
            db.add(cmd)
            db.flush()
            for a in sinonim + [a for a, k in ALIAS_KHUSUS.items() if k == key]:
                if db.scalar(select(CommandAlias).where(CommandAlias.alias == a)) is None:
                    db.add(CommandAlias(alias=a, command_id=cmd.id))
    db.flush()
