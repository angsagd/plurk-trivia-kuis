#!/usr/bin/env python3
"""
Validator bank soal (CLI) - Plurk Trivia Kuis.
Logika validasi ada di app/core/validator.py (dipakai juga oleh bot & admin).

Nama file: trivia_NN_nama_topik.txt (mis. trivia_04_sejarah_dunia.txt -> 04 "Sejarah Dunia")
Isi      : satu soal per baris, soal|clue|jawaban; baris kosong dan '#' diabaikan.

Pemakaian:
    python3 tools/validasi_soal.py bank_soal.txt
    python3 tools/validasi_soal.py bank_soal.txt --laporan laporan.csv --bersih bank_bersih.txt
"""

import argparse
import csv
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.matching import jumlah_huruf  # noqa: E402
from app.core.validator import topik_dari_nama_file, validasi_isi  # noqa: E402

SOAL_PER_MINGGU = 250  # 5 hari x 5 sesi x 10 soal


def main() -> None:
    ap = argparse.ArgumentParser(description="Validator bank soal Plurk Trivia Kuis")
    ap.add_argument("file", help="file bank soal (soal|clue|jawaban per baris)")
    ap.add_argument("--laporan", help="tulis semua masalah ke file CSV")
    ap.add_argument("--bersih", help="tulis soal yang lolos (tanpa ERROR) ke file baru, jawaban dirapikan")
    ap.add_argument("--tampil", type=int, default=20, help="jumlah masalah yang ditampilkan (default 20)")
    args = ap.parse_args()

    try:
        hasil = validasi_isi(Path(args.file).read_text(encoding="utf-8"))
    except UnicodeDecodeError:
        print("Gagal membaca file: simpan file dengan encoding UTF-8.")
        sys.exit(2)

    jenis = Counter(m.kode for m in hasil.masalah)
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
    print(f"Total soal dibaca   : {hasil.total}")
    print(f"Lolos (tanpa error) : {len(hasil.valid)}")
    print(f"Baris dengan error  : {hasil.baris_error}")
    print(f"Peringatan          : {hasil.jumlah_peringatan}")
    if hasil.valid:
        minggu = len(hasil.valid) / SOAL_PER_MINGGU
        print(f"Stok soal           : ± {minggu:.1f} minggu ({SOAL_PER_MINGGU} soal/minggu)")
        sebaran = Counter(jumlah_huruf(v.jawaban) for v in hasil.valid)
        print("\nSebaran panjang jawaban (huruf: jumlah soal):")
        for k in sorted(sebaran):
            print(f"  {k:>2}: {sebaran[k]}")

    if jenis:
        print("\nRingkasan masalah:")
        for kode, n in jenis.most_common():
            print(f"  {kode:<18} {n}")

    if hasil.masalah and args.tampil:
        print(f"\nContoh masalah (maks {args.tampil}):")
        for m in hasil.masalah[: args.tampil]:
            potong = m.isi if len(m.isi) <= 70 else m.isi[:67] + "..."
            print(f"  baris {m.baris:>5} [{m.tingkat}] {m.pesan}")
            print(f"              {potong}")

    if args.laporan:
        with open(args.laporan, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["baris", "tingkat", "kode", "pesan", "isi"])
            w.writerows((m.baris, m.tingkat, m.kode, m.pesan, m.isi) for m in hasil.masalah)
        print(f"\nLaporan lengkap ditulis ke: {args.laporan}")

    if args.bersih:
        with open(args.bersih, "w", encoding="utf-8") as f:
            for v in hasil.valid:
                f.write(f"{v.soal}|{v.clue}|{v.jawaban}\n")
        print(f"Soal yang lolos ditulis ke: {args.bersih}")

    sys.exit(1 if (hasil.baris_error or not topik) else 0)


if __name__ == "__main__":
    main()
