"""Validasi bank soal: nama file topik, isi file, identitas soal, unggah & ganti nama topik."""

import hashlib
import os
import re
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.matching import cocok, jumlah_huruf, rapikan_jawaban

MAKS_SOAL = 180
MAKS_CLUE = 180
MIN_HURUF = 4
MAKS_HURUF = 20

POLA_JAWABAN = re.compile(r"^[A-Za-z ]+$")
POLA_NAMA_FILE = re.compile(r"^trivia_(\d{2})_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)\.txt$")
CONTOH_NAMA_FILE = "trivia_04_sejarah_dunia.txt"


class ValidasiGagal(ValueError):
    """Pesan error ditujukan ke admin (bahasa Indonesia)."""


# ---------------------------------------------------------------- nama file & topik


def topik_dari_nama_file(path: str) -> tuple[str, str] | None:
    """('04', 'Sejarah Dunia') dari 'trivia_04_sejarah_dunia.txt', atau None bila format salah.
    Kata yang sudah memuat huruf kapital dibiarkan: film_dan_TV -> 'Film Dan TV'."""
    m = POLA_NAMA_FILE.match(os.path.basename(path))
    if not m or m.group(1) == "00":
        return None
    kata = [w if any(c.isupper() for c in w) else w[:1].upper() + w[1:] for w in m.group(2).split("_")]
    return m.group(1), " ".join(kata)


def kunci_topik(nama: str) -> str:
    """Identitas topik = nama tanpa membedakan huruf besar/kecil."""
    return nama.casefold()


@dataclass(frozen=True)
class TopikAda:
    id: int
    nomor: str
    nama: str


@dataclass(frozen=True)
class RencanaUnggah:
    nomor: str
    nama: str
    topik_id: int | None  # None = topik baru; selain itu = topik yang diperbarui


def _wajib_topik(nama_file: str) -> tuple[str, str]:
    topik = topik_dari_nama_file(nama_file)
    if topik is None:
        raise ValidasiGagal(
            f"Nama file '{os.path.basename(nama_file)}' salah: harus trivia_NN_nama_topik.txt "
            f"(NN = 01-99), mis. {CONTOH_NAMA_FILE}"
        )
    return topik


def rencana_unggah(nama_file: str, topik_ada: Iterable[TopikAda]) -> RencanaUnggah:
    """Tentukan apakah unggahan membuat topik baru atau memperbarui topik bernama sama.
    Ditolak bila format nama file salah, atau nomornya dipakai topik lain."""
    nomor, nama = _wajib_topik(nama_file)
    semua = list(topik_ada)
    sama = next((t for t in semua if kunci_topik(t.nama) == kunci_topik(nama)), None)
    if sama is not None and sama.nomor != nomor:
        raise ValidasiGagal(
            f"Topik '{sama.nama}' sudah ada dengan nomor {sama.nomor}. "
            "Untuk mengubah nomor, pakai tombol Ganti nama."
        )
    pemilik_nomor = next((t for t in semua if t.nomor == nomor and t is not sama), None)
    if pemilik_nomor is not None:
        raise ValidasiGagal(f"Nomor {nomor} sudah dipakai topik '{pemilik_nomor.nama}'.")
    return RencanaUnggah(nomor, nama, sama.id if sama else None)


def validasi_ganti_nama(
    nama_file_baru: str, topik: TopikAda, topik_ada: Iterable[TopikAda]
) -> tuple[str, str]:
    """Kembalikan (nomor, nama) baru untuk topik, atau ValidasiGagal."""
    nomor, nama = _wajib_topik(nama_file_baru)
    if nomor == topik.nomor and nama == topik.nama:
        raise ValidasiGagal("Nama file baru sama dengan nama sekarang.")
    for t in topik_ada:
        if t.id == topik.id:
            continue
        if kunci_topik(t.nama) == kunci_topik(nama):
            raise ValidasiGagal(f"Nama topik '{nama}' sudah dipakai topik lain (nomor {t.nomor}).")
        if t.nomor == nomor:
            raise ValidasiGagal(f"Nomor {nomor} sudah dipakai topik '{t.nama}'.")
    return nomor, nama


# ---------------------------------------------------------------- isi file


def normal_teks_soal(soal: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", soal).strip().lower())


def text_hash(soal: str) -> str:
    """Identitas soal = hash teks soal yang dinormalisasi (huruf kecil, spasi dirapatkan)."""
    return hashlib.sha256(normal_teks_soal(soal).encode("utf-8")).hexdigest()


class Tingkat(StrEnum):
    ERROR = "ERROR"
    PERINGATAN = "PERINGATAN"


@dataclass(frozen=True)
class Masalah:
    baris: int
    tingkat: Tingkat
    kode: str
    pesan: str
    isi: str


@dataclass(frozen=True)
class SoalValid:
    baris: int
    soal: str
    clue: str
    jawaban: str  # sudah dirapikan (huruf besar, spasi tunggal)
    text_hash: str


@dataclass
class HasilValidasi:
    total: int = 0
    valid: list[SoalValid] = field(default_factory=list)
    masalah: list[Masalah] = field(default_factory=list)

    @property
    def baris_error(self) -> int:
        return len({m.baris for m in self.masalah if m.tingkat is Tingkat.ERROR})

    @property
    def jumlah_peringatan(self) -> int:
        return sum(1 for m in self.masalah if m.tingkat is Tingkat.PERINGATAN)


def validasi_isi(teks: str) -> HasilValidasi:
    """Validasi isi file bank soal (format soal|clue|jawaban per baris; '#' = komentar)."""
    hasil = HasilValidasi()
    terlihat: dict[str, int] = {}
    teks = teks.removeprefix("﻿")

    for no, baris in enumerate(teks.splitlines(), start=1):
        if not baris.strip() or baris.lstrip().startswith("#"):
            continue
        hasil.total += 1
        bagian = baris.split("|")
        if len(bagian) != 3:
            pesan = f"harus 3 kolom (soal|clue|jawaban), ditemukan {len(bagian)}"
            hasil.masalah.append(Masalah(no, Tingkat.ERROR, "KOLOM", pesan, baris))
            continue

        soal, clue, jawaban = (b.strip() for b in bagian)
        err: list[tuple[str, str]] = []
        warn: list[tuple[str, str]] = []

        if not soal:
            err.append(("SOAL_KOSONG", "soal kosong"))
        elif len(soal) > MAKS_SOAL:
            err.append(("SOAL_PANJANG", f"soal {len(soal)} karakter (maks {MAKS_SOAL})"))

        if not clue:
            err.append(("CLUE_KOSONG", "clue kosong"))
        elif len(clue) > MAKS_CLUE:
            err.append(("CLUE_PANJANG", f"clue {len(clue)} karakter (maks {MAKS_CLUE})"))

        if not jawaban:
            err.append(("JAWABAN_KOSONG", "jawaban kosong"))
        elif not POLA_JAWABAN.match(jawaban):
            aneh = sorted({c for c in jawaban if not (c.isascii() and (c.isalpha() or c == " "))})
            err.append(("JAWABAN_KARAKTER", f"jawaban mengandung karakter terlarang: {' '.join(aneh)}"))
        else:
            n = jumlah_huruf(jawaban)
            if not MIN_HURUF <= n <= MAKS_HURUF:
                err.append(("JAWABAN_PANJANG", f"jawaban {n} huruf (harus {MIN_HURUF}-{MAKS_HURUF})"))
            if jawaban != re.sub(r"\s+", " ", jawaban):
                warn.append(("JAWABAN_SPASI", "spasi ganda di jawaban (akan dirapikan otomatis)"))

        if not err:
            if cocok(jawaban, soal):
                warn.append(("BOCOR_SOAL", "jawaban tertulis di dalam soal"))
            if cocok(jawaban, clue):
                warn.append(("BOCOR_CLUE", "jawaban tertulis di dalam clue"))

        kunci = normal_teks_soal(soal)
        if soal and kunci in terlihat:
            warn.append(("DUPLIKAT", f"soal sama dengan baris {terlihat[kunci]}"))
        elif soal:
            terlihat[kunci] = no

        hasil.masalah += [Masalah(no, Tingkat.ERROR, k, p, baris) for k, p in err]
        hasil.masalah += [Masalah(no, Tingkat.PERINGATAN, k, p, baris) for k, p in warn]
        if not err:
            hasil.valid.append(SoalValid(no, soal, clue, rapikan_jawaban(jawaban), text_hash(soal)))
    return hasil


def topik_mirip(hash_baru: Iterable[str], hash_per_topik: Mapping[int, set[str]]) -> int | None:
    """Topik lain yang memuat > separuh soal file baru (menurut text_hash), atau None.
    Dipakai saat unggah topik baru: 'mungkin ini topik X yang diganti nama'."""
    baru = set(hash_baru)
    if not baru:
        return None
    terbaik = max(hash_per_topik.items(), key=lambda kv: len(baru & kv[1]), default=None)
    if terbaik is not None and len(baru & terbaik[1]) * 2 > len(baru):
        return terbaik[0]
    return None
