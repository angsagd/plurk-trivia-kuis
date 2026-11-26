"""Pencocokan jawaban: normalisasi teks dan pencarian jawaban sebagai kata utuh."""

import re
import unicodedata

# Huruf yang tidak terurai lewat NFKD (bukan huruf dasar + tanda aksen).
_HURUF_KHUSUS = str.maketrans(
    {"ð": "d", "đ": "d", "þ": "th", "ø": "o", "ł": "l", "ı": "i", "æ": "ae", "œ": "oe", "ß": "ss"}
)

# Pemisah antar kata jawaban: 0-3 karakter bukan huruf dan bukan angka.
# "bung karno", "bung-karno", "bung - karno", "bungkarno" cocok; "bung 12345 karno" tidak.
MAKS_PEMISAH = 3
_PEMISAH = rf"[^a-z0-9]{{0,{MAKS_PEMISAH}}}"


def normalisasi(teks: str) -> str:
    """Huruf kecil, buang aksen (é->e, ö->o, ð->d), hapus titik ("A.T." -> "at")."""
    t = unicodedata.normalize("NFKD", teks.lower().translate(_HURUF_KHUSUS))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.translate(_HURUF_KHUSUS).replace(".", "")


def jumlah_huruf(jawaban: str) -> int:
    """Jumlah huruf jawaban; spasi tidak dihitung."""
    return len(jawaban.replace(" ", ""))


def rapikan_jawaban(jawaban: str) -> str:
    """Huruf besar, spasi ganda dirapatkan: ' bung  karno ' -> 'BUNG KARNO'."""
    return re.sub(r"\s+", " ", jawaban.strip()).upper()


def pola_kata_utuh(jawaban: str) -> re.Pattern[str]:
    """Pola jawaban sebagai kata utuh. Teks yang dicari HARUS sudah dinormalisasi()."""
    kata = normalisasi(jawaban).split()
    inti = _PEMISAH.join(re.escape(k) for k in kata)
    return re.compile(r"(?<![a-z])" + inti + r"(?![a-z])")


def cocok(jawaban: str, teks: str) -> bool:
    """True bila jawaban tertulis sebagai kata utuh di teks (case-insensitive, tanpa aksen/titik)."""
    return pola_kata_utuh(jawaban).search(normalisasi(teks)) is not None
