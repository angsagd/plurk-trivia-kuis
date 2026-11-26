"""Tes aturan pencocokan jawaban & nama file di tools/validasi_soal.py.
Hanya memakai data karangan (lihat contoh/trivia_99_contoh.txt), tidak pernah soal dari private/."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from validasi_soal import cocok, normalisasi, topik_dari_nama_file, validasi  # noqa: E402


@pytest.mark.parametrize(
    "balasan, jawaban, harapan",
    [
        ("jawabannya Bali dong!!", "BALI", True),
        ("kebalikan", "BALI", False),
        ("bung-karno", "BUNG KARNO", True),
        ("bungkarno", "BUNG KARNO", True),
        ("bung  karno", "BUNG KARNO", True),
        ("Bung - Karno", "BUNG KARNO", True),
        ("A.T. Mahmud", "AT MAHMUD", True),
        ("Beyoncé", "BEYONCE", True),
        ("Guðnadóttir", "GUDNADOTTIR", True),
        ("hatta", "MOHAMMAD HATTA", False),
        ("bung 12345 karno", "BUNG KARNO", False),
        ("bung yang karno", "BUNG KARNO", False),
        ("balié", "BALI", False),
        ("BALI 🎉", "BALI", True),
        ("SOEKARNO?", "SOEKARNO", True),
    ],
)
def test_cocok(balasan, jawaban, harapan):
    assert cocok(jawaban, balasan) is harapan


def test_normalisasi():
    assert normalisasi("A.T. Mahmud") == "at mahmud"
    assert normalisasi("Guðnadóttir Øresund Straße") == "gudnadottir oresund strasse"


@pytest.mark.parametrize(
    "nama, harapan",
    [
        ("trivia_04_sejarah_dunia.txt", ("04", "Sejarah Dunia")),
        ("trivia_07_film_dan_TV.txt", ("07", "Film Dan TV")),
        ("trivia_99_contoh.txt", ("99", "Contoh")),
        ("trivia_4_musik.txt", None),
        ("musik.txt", None),
        ("trivia_00_musik.txt", None),
        ("trivia_05_dua__garis.txt", None),
    ],
)
def test_topik_dari_nama_file(nama, harapan):
    assert topik_dari_nama_file(nama) == harapan


def test_file_contoh_valid():
    path = ROOT / "contoh" / "trivia_99_contoh.txt"
    assert topik_dari_nama_file(str(path)) is not None
    total, valid, masalah = validasi(str(path))
    assert total == len(valid) == 8
    assert masalah == []
