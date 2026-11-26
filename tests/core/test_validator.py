from pathlib import Path

import pytest

from app.core.validator import (
    TopikAda,
    ValidasiGagal,
    rencana_unggah,
    text_hash,
    topik_dari_nama_file,
    topik_mirip,
    validasi_ganti_nama,
    validasi_isi,
)

ROOT = Path(__file__).resolve().parents[2]
TOPIK = [TopikAda(1, "02", "Sejarah Indonesia"), TopikAda(2, "04", "Sejarah Dunia")]


@pytest.mark.parametrize(
    "nama, harapan",
    [
        ("trivia_04_sejarah_dunia.txt", ("04", "Sejarah Dunia")),
        ("trivia_07_film_dan_TV.txt", ("07", "Film Dan TV")),
        ("/x/y/trivia_99_contoh.txt", ("99", "Contoh")),
        ("trivia_4_musik.txt", None),
        ("musik.txt", None),
        ("trivia_00_musik.txt", None),
        ("trivia_05_dua__garis.txt", None),
        ("trivia_05_musik.TXT", None),
    ],
)
def test_topik_dari_nama_file(nama, harapan):
    assert topik_dari_nama_file(nama) == harapan


def test_unggah_topik_baru_dan_perbarui():
    assert rencana_unggah("trivia_05_musik.txt", TOPIK).topik_id is None
    r = rencana_unggah("trivia_04_sejarah_dunia.txt", TOPIK)
    assert (r.topik_id, r.nomor, r.nama) == (2, "04", "Sejarah Dunia")
    assert rencana_unggah("trivia_04_SEJARAH_DUNIA.txt", TOPIK).topik_id == 2  # tanpa beda huruf besar/kecil


@pytest.mark.parametrize(
    "nama", ["trivia_4_musik.txt", "musik.txt", "trivia_04_musik.txt", "trivia_09_sejarah_dunia.txt"]
)
def test_unggah_ditolak(nama):
    with pytest.raises(ValidasiGagal):
        rencana_unggah(nama, TOPIK)


def test_ganti_nama():
    assert validasi_ganti_nama("trivia_02_sejarah_nusantara.txt", TOPIK[0], TOPIK) == (
        "02",
        "Sejarah Nusantara",
    )
    assert validasi_ganti_nama("trivia_03_sejarah_indonesia.txt", TOPIK[0], TOPIK) == (
        "03",
        "Sejarah Indonesia",
    )


@pytest.mark.parametrize(
    "nama",
    [
        "trivia_02_sejarah_dunia.txt",  # nama milik topik lain
        "trivia_04_sejarah_nusantara.txt",  # nomor milik topik lain
        "trivia_02_sejarah_indonesia.txt",  # tidak berubah
        "sejarah.txt",
    ],
)
def test_ganti_nama_ditolak(nama):
    with pytest.raises(ValidasiGagal):
        validasi_ganti_nama(nama, TOPIK[0], TOPIK)


def test_validasi_isi_contoh():
    hasil = validasi_isi((ROOT / "contoh" / "trivia_99_contoh.txt").read_text(encoding="utf-8"))
    assert hasil.total == len(hasil.valid) == 8 and hasil.masalah == []


def test_validasi_isi_error_dan_peringatan():
    teks = "﻿" + "\n".join(
        [
            "# komentar",
            "",
            "Soal satu?|Clue|BALI",
            "Soal dua tanpa kolom|BALI",
            "Soal tiga?|Clue|BAL",
            "Soal empat?|Clue|BALI2",
            "Pulau Bali ada di mana?|Clue|BALI",
            "soal   SATU?|Clue lain|JAWA",
            "Soal lima?|Clue|BUNG  KARNO",
            "x" * 181 + "|Clue|BALI",
        ]
    )
    h = validasi_isi(teks)
    kode = {(m.baris, m.kode) for m in h.masalah}
    assert h.total == 8
    assert {(4, "KOLOM"), (5, "JAWABAN_PANJANG"), (6, "JAWABAN_KARAKTER"), (10, "SOAL_PANJANG")} <= kode
    assert {(7, "BOCOR_SOAL"), (8, "DUPLIKAT"), (9, "JAWABAN_SPASI")} <= kode
    assert [v.jawaban for v in h.valid] == ["BALI", "BALI", "JAWA", "BUNG KARNO"]
    assert h.baris_error == 4


def test_text_hash_abaikan_besar_kecil_dan_spasi():
    assert text_hash("Siapa  presiden?") == text_hash(" siapa presiden? ")
    assert text_hash("Siapa presiden?") != text_hash("Siapa wakil presiden?")


def test_topik_mirip():
    baru = {"a", "b", "c", "d"}
    assert topik_mirip(baru, {1: {"a", "b", "c", "x"}, 2: {"d"}}) == 1
    assert topik_mirip(baru, {1: {"a", "b"}, 2: {"c", "d"}}) is None  # tepat separuh: bukan "lebih dari"
    assert topik_mirip(set(), {1: {"a"}}) is None
