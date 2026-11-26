import pytest

from app.core.clues import clue2, clue3, pola
from app.core.scoring import hitung_skor


def test_skor_soekarno():
    assert [hitung_skor("SOEKARNO", f) for f in range(4)] == [8, 4, 3, 2]


def test_skor_spasi_tidak_dihitung():
    assert hitung_skor("MOHAMMAD HATTA", 0) == 13
    assert hitung_skor("MOHAMMAD HATTA", 1) == 7


def test_skor_input_salah():
    with pytest.raises(ValueError):
        hitung_skor("BALI", 4)
    with pytest.raises(ValueError):
        hitung_skor("BALI", 0, rumus="tidak_ada")


def test_clue_mohammad_hatta():
    assert clue2("MOHAMMAD HATTA") == "13 huruf: ======== ====="
    assert clue3("MOHAMMAD HATTA") == "M======= ====A"


def test_clue_satu_kata_dan_karakter_lain():
    assert clue3("BALI", ".") == "B..I"
    assert clue2("BUNG KARNO", "＿", " / ") == "9 huruf: ＿＿＿＿ / ＿＿＿＿＿"
    assert pola("A BC", "＿") == "＿ ＿＿"
    assert clue3("J K ROWLING") == "J = ======G"


@pytest.mark.parametrize("karakter", ["*", "-", "_"])  # '-' dan '_' diformat Plurk (coret / garis bawah)
def test_clue_karakter_tidak_dikenal(karakter):
    with pytest.raises(ValueError):
        clue2("BALI", karakter)
