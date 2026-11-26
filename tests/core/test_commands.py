from app.core.commands import cek_kata_kunci, cek_respons_kustom

TERPAKAI = ["jadwal", "sesi", "klasemen", "top", "rank", "peringkat", "skor", "poin"]


def test_kata_kunci_bentrok_dengan_top_ditolak():
    assert cek_kata_kunci(["top"], TERPAKAI) == ["'top' sudah dipakai perintah lain"]
    assert cek_kata_kunci(["halo", "Skor"], TERPAKAI) == ["'skor' sudah dipakai perintah lain"]


def test_kata_kunci_valid_dan_format():
    assert cek_kata_kunci(["halo", "hai"], TERPAKAI) == []
    assert cek_kata_kunci(["ha lo"], []) and cek_kata_kunci(["a"], []) and cek_kata_kunci(["halo!"], [])
    assert cek_kata_kunci(["halo", "halo"], []) == ["'halo' ditulis dua kali"]


def test_respons_kustom_isian_dan_panjang():
    assert cek_respons_kustom("Halo {nama}! Sesi berikutnya {sesi_berikutnya}.", 360) == []
    assert "isian tidak diizinkan: rank" in cek_respons_kustom("Kamu #{rank}", 360)[0]
    assert cek_respons_kustom("x" * 361, 360) == ["361 karakter, melebihi batas 360"]
    assert cek_respons_kustom("kurung {rusak", 360) == ["kurung kurawal { } tidak seimbang"]
    assert cek_respons_kustom("  ", 360) == ["respons kosong"]


import pytest  # noqa: E402

from app.core.commands import parse_perintah  # noqa: E402


@pytest.mark.parametrize(
    "teks, harapan",
    [
        ("@kuisbot rank", "rank"),
        ("@kuisbot: Rank?", "rank"),
        ("@kuisbot RANK aku berapa", "rank"),
        ("@kuisbot:rank", "rank"),
        ("  @KuisBot   jadwal.", "jadwal"),
        ("@kuisbot rank minggu", "rank"),
        ("@kuisbot rank @nicklain", "rank"),
        ("@kuisbot ?", "?"),
        ("@kuisbot keren banget!", "keren"),
        ("eh @kuisbot rank", None),
        ("@kuisbotku rank", None),
        ("@kuisbot", None),
        ("@kuisbot ??", None),
        ("@kuisbot 🙏", None),
    ],
)
def test_parse_perintah(teks, harapan):
    assert parse_perintah(teks, "kuisbot") == harapan
