#!/usr/bin/env python3
"""
Validator bank soal - Plurk Trivia Kuis

Nama file (= identitas topik):
    trivia_NN_nama_topik.txt
    NN        : nomor topik dua digit (01-99), unik
    nama_topik: huruf/angka, antar kata dipisah garis bawah
    Nama topik dibentuk dari nama_topik: garis bawah -> spasi, huruf awal tiap
    kata -> kapital (kata yang sudah memuat huruf kapital dibiarkan apa adanya).
    Contoh: trivia_04_sejarah_dunia.txt -> nomor 04, topik "Sejarah Dunia"

Format isi: satu soal per baris, dipisah tanda pipa
    soal|clue|jawaban

Baris kosong dan baris yang diawali '#' diabaikan (untuk komentar).

Ketentuan:
  - soal  : wajib, maksimal 180 karakter
  - clue  : wajib, maksimal 180 karakter
  - jawaban: hanya huruf A-Z dan spasi; 4-20 huruf (spasi tidak dihitung)

Pemakaian:
    python3 validasi_soal.py bank_soal.txt
    python3 validasi_soal.py bank_soal.txt --laporan laporan.csv --bersih bank_bersih.txt
"""

import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import Counter

MAKS_SOAL = 180
MAKS_CLUE = 180
MIN_HURUF = 4
MAKS_HURUF = 20
SOAL_PER_MINGGU = 250  # 5 hari x 5 sesi x 10 soal

POLA_JAWABAN = re.compile(r"^[A-Za-z ]+$")
POLA_NAMA_FILE = re.compile(r"^trivia_(\d{2})_([A-Za-z0-9]+(?:_[A-Za-z0-9]+)*)\.txt$")


def topik_dari_nama_file(path: str):
    """Kembalikan (nomor, nama_topik) dari nama file, atau None bila formatnya salah."""
    m = POLA_NAMA_FILE.match(os.path.basename(path))
    if not m or m.group(1) == "00":
        return None
    kata = [w if any(c.isupper() for c in w) else w[:1].upper() + w[1:] for w in m.group(2).split("_")]
    return m.group(1), " ".join(kata)


def jumlah_huruf(jawaban: str) -> int:
    return len(jawaban.replace(" ", ""))


def rapikan_jawaban(jawaban: str) -> str:
    return re.sub(r"\s+", " ", jawaban.strip()).upper()


# Huruf yang tidak terurai lewat NFKD (bukan huruf + tanda aksen).
_HURUF_KHUSUS = str.maketrans(
    {
        "ð": "d",
        "đ": "d",
        "þ": "th",
        "ø": "o",
        "ł": "l",
        "ı": "i",
        "æ": "ae",
        "œ": "oe",
        "ß": "ss",
    }
)

# Pemisah antar kata jawaban: 0-3 karakter spasi/tanda baca (bukan huruf, bukan angka).
# "bung karno", "bung-karno", "bung - karno", "bungkarno" cocok; "bung 12345 karno" tidak.
MAKS_PEMISAH = 3
_PEMISAH = rf"[^a-z0-9]{{0,{MAKS_PEMISAH}}}"


def normalisasi(teks: str) -> str:
    """Huruf kecil, buang aksen (é->e, ö->o, ð->d), hapus titik ("A.T." -> "at").
    Dipakai pada balasan pemain maupun teks soal/clue sebelum dicocokkan."""
    t = unicodedata.normalize("NFKD", teks.lower().translate(_HURUF_KHUSUS))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return t.translate(_HURUF_KHUSUS).replace(".", "")


def pola_kata_utuh(jawaban: str) -> re.Pattern:
    """Jawaban sebagai kata utuh; pemisah antar kata fleksibel (spasi/tanda baca pendek atau tanpa spasi).
    Teks yang dicari HARUS sudah melewati normalisasi(), mis. pola.search(normalisasi(balasan)).
    Aturan yang sama nanti dipakai bot untuk menilai balasan pemain."""
    kata = normalisasi(jawaban).split()
    inti = _PEMISAH.join(re.escape(k) for k in kata)
    return re.compile(r"(?<![a-z])" + inti + r"(?![a-z])")


def cocok(jawaban: str, teks: str) -> bool:
    """True bila jawaban tertulis sebagai kata utuh di teks."""
    return pola_kata_utuh(jawaban).search(normalisasi(teks)) is not None


def normal_teks(t: str) -> str:
    return re.sub(r"\s+", " ", t.strip().lower())


def validasi(path):
    masalah = []  # (baris, tingkat, kode, pesan, isi)
    valid = []  # (baris, soal, clue, jawaban)
    total = 0
    soal_terlihat = {}

    with open(path, encoding="utf-8-sig") as f:
        for no, mentah in enumerate(f, start=1):
            baris = mentah.rstrip("\r\n")
            if not baris.strip() or baris.lstrip().startswith("#"):
                continue
            total += 1
            bagian = baris.split("|")
            if len(bagian) != 3:
                masalah.append(
                    (
                        no,
                        "ERROR",
                        "KOLOM",
                        f"harus 3 kolom (soal|clue|jawaban), ditemukan {len(bagian)}",
                        baris,
                    )
                )
                continue

            soal, clue, jawaban = (b.strip() for b in bagian)
            err = []
            warn = []

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
                aneh = sorted(set(c for c in jawaban if not (c.isascii() and (c.isalpha() or c == " "))))
                err.append(("JAWABAN_KARAKTER", f"jawaban mengandung karakter terlarang: {' '.join(aneh)}"))
            else:
                n = jumlah_huruf(jawaban)
                if not (MIN_HURUF <= n <= MAKS_HURUF):
                    err.append(("JAWABAN_PANJANG", f"jawaban {n} huruf (harus {MIN_HURUF}-{MAKS_HURUF})"))
                if jawaban != re.sub(r"\s+", " ", jawaban):
                    warn.append(("JAWABAN_SPASI", "spasi ganda di jawaban (akan dirapikan otomatis)"))

            if not err:
                pola = pola_kata_utuh(jawaban)
                if pola.search(normalisasi(soal)):
                    warn.append(("BOCOR_SOAL", "jawaban tertulis di dalam soal"))
                if pola.search(normalisasi(clue)):
                    warn.append(("BOCOR_CLUE", "jawaban tertulis di dalam clue"))

            kunci = normal_teks(soal)
            if soal and kunci in soal_terlihat:
                warn.append(("DUPLIKAT", f"soal sama dengan baris {soal_terlihat[kunci]}"))
            elif soal:
                soal_terlihat[kunci] = no

            for kode, pesan in err:
                masalah.append((no, "ERROR", kode, pesan, baris))
            for kode, pesan in warn:
                masalah.append((no, "PERINGATAN", kode, pesan, baris))
            if not err:
                valid.append((no, soal, clue, rapikan_jawaban(jawaban)))

    return total, valid, masalah


def main():
    ap = argparse.ArgumentParser(description="Validator bank soal Plurk Trivia Kuis")
    ap.add_argument("file", help="file bank soal (soal|clue|jawaban per baris)")
    ap.add_argument("--laporan", help="tulis semua masalah ke file CSV")
    ap.add_argument("--bersih", help="tulis soal yang lolos (tanpa ERROR) ke file baru, jawaban dirapikan")
    ap.add_argument(
        "--tampil", type=int, default=20, help="jumlah masalah yang ditampilkan di layar (default 20)"
    )
    args = ap.parse_args()

    try:
        total, valid, masalah = validasi(args.file)
    except UnicodeDecodeError:
        print("Gagal membaca file: simpan file dengan encoding UTF-8.")
        sys.exit(2)

    n_err_baris = len({m[0] for m in masalah if m[1] == "ERROR"})
    n_warn = sum(1 for m in masalah if m[1] == "PERINGATAN")
    jenis = Counter(m[2] for m in masalah)

    topik = topik_dari_nama_file(args.file)
    print("=" * 60)
    print("HASIL VALIDASI BANK SOAL")
    print("=" * 60)
    if topik:
        print(f"Nomor topik         : {topik[0]}")
        print(f"Nama topik          : {topik[1]}")
    else:
        print("Nama file           : ERROR - harus berformat trivia_NN_nama_topik.txt")
        print("                      (mis. trivia_04_sejarah_dunia.txt)")
    print(f"Total soal dibaca   : {total}")
    print(f"Lolos (tanpa error) : {len(valid)}")
    print(f"Baris dengan error  : {n_err_baris}")
    print(f"Peringatan          : {n_warn}")
    if valid:
        minggu = len(valid) / SOAL_PER_MINGGU
        print(f"Stok soal           : ± {minggu:.1f} minggu ({SOAL_PER_MINGGU} soal/minggu)")
        sebaran = Counter(jumlah_huruf(v[3]) for v in valid)
        print("\nSebaran panjang jawaban (huruf: jumlah soal):")
        for k in sorted(sebaran):
            print(f"  {k:>2}: {sebaran[k]}")

    if jenis:
        print("\nRingkasan masalah:")
        for kode, n in jenis.most_common():
            print(f"  {kode:<18} {n}")

    if masalah:
        print(f"\nContoh masalah (maks {args.tampil}):")
        for no, tingkat, _kode, pesan, isi in masalah[: args.tampil]:
            potong = isi if len(isi) <= 70 else isi[:67] + "..."
            print(f"  baris {no:>5} [{tingkat}] {pesan}")
            print(f"              {potong}")

    if args.laporan:
        with open(args.laporan, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["baris", "tingkat", "kode", "pesan", "isi"])
            w.writerows(masalah)
        print(f"\nLaporan lengkap ditulis ke: {args.laporan}")

    if args.bersih:
        with open(args.bersih, "w", encoding="utf-8") as f:
            for _, soal, clue, jawaban in valid:
                f.write(f"{soal}|{clue}|{jawaban}\n")
        print(f"Soal yang lolos ditulis ke: {args.bersih}")

    sys.exit(1 if (n_err_baris or not topik) else 0)


if __name__ == "__main__":
    main()
