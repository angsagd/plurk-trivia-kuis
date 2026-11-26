import pytest

from app.core.matching import cocok, jumlah_huruf, normalisasi, rapikan_jawaban


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
        ("bali2", "BALI", True),
    ],
)
def test_cocok(balasan, jawaban, harapan):
    assert cocok(jawaban, balasan) is harapan


def test_normalisasi():
    assert normalisasi("A.T. Mahmud") == "at mahmud"
    assert normalisasi("Guðnadóttir Øresund Straße") == "gudnadottir oresund strasse"


def test_jumlah_huruf_dan_rapikan():
    assert jumlah_huruf("MOHAMMAD HATTA") == 13
    assert rapikan_jawaban("  bung   karno ") == "BUNG KARNO"
