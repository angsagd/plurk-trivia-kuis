"""Aturan kata kunci perintah lewat mention (validasi saat admin menyimpan)."""

import re
import string
from collections.abc import Iterable

POLA_KATA_KUNCI = re.compile(r"^[a-z0-9]{2,20}$")
ISIAN_KUSTOM = frozenset({"nama", "sesi_berikutnya"})  # respons kustom hanya boleh isian ringan


def rapikan_kata_kunci(teks: str) -> str:
    return teks.strip().lower()


def cek_kata_kunci(baru: Iterable[str], terpakai: Iterable[str]) -> list[str]:
    """Daftar error (kosong = lolos). `baru` = kata kunci + sinonim perintah yang disimpan;
    `terpakai` = kata kunci & sinonim milik perintah LAIN."""
    error = []
    lain = {rapikan_kata_kunci(t) for t in terpakai}
    dilihat: set[str] = set()
    for k in (rapikan_kata_kunci(x) for x in baru):
        if not POLA_KATA_KUNCI.match(k):
            error.append(f"'{k}': hanya huruf kecil a-z dan angka, 2-20 karakter")
        elif k in lain:
            error.append(f"'{k}' sudah dipakai perintah lain")
        elif k in dilihat:
            error.append(f"'{k}' ditulis dua kali")
        dilihat.add(k)
    return error


def isian_template(teks: str) -> set[str]:
    """Nama isian {..} dalam template; ValueError bila format kurung kurawal rusak."""
    return {nama for _, nama, _, _ in string.Formatter().parse(teks) if nama}


def cek_respons_kustom(teks: str, batas: int) -> list[str]:
    error = []
    if not teks.strip():
        return ["respons kosong"]
    try:
        asing = isian_template(teks) - ISIAN_KUSTOM
    except ValueError:
        return ["kurung kurawal { } tidak seimbang"]
    if asing:
        error.append(
            f"isian tidak diizinkan: {', '.join(sorted(asing))} (boleh: {{nama}}, {{sesi_berikutnya}})"
        )
    if len(teks) > batas:
        error.append(f"{len(teks)} karakter, melebihi batas {batas}")
    return error


_TANDA_AKHIR = "!?.,;:…~)(\"'"


def parse_perintah(teks: str, nick_bot: str) -> str | None:
    """Kata kunci dari mention di AWAL teks, atau None bila bukan perintah.

    '@kuisbot rank', '@kuisbot: Rank?', '@kuisbot RANK aku berapa' -> 'rank'; '@kuisbot ?' -> '?'.
    'eh @kuisbot rank' (mention tidak di awal) -> None. '@kuisbot keren banget!' -> 'keren'
    (bukan kata kunci; pemanggil mengabaikannya). Argumen setelah kata kunci diabaikan."""
    m = re.match(
        rf"@{re.escape(nick_bot)}(?![A-Za-z0-9_])\s*:?(.*)$", teks.strip(), re.IGNORECASE | re.DOTALL
    )
    if m is None:
        return None
    sisa = m.group(1).split()
    if not sisa:
        return None
    kata = sisa[0]
    if kata == "?":
        return "?"
    kata = kata.rstrip(_TANDA_AKHIR).lower()
    return kata if POLA_KATA_KUNCI.match(kata) else None
