"""Clue 2 (jumlah huruf + pola per kata) dan clue 3 (huruf awal & akhir seluruh jawaban).
Clue 1 adalah teks clue dari bank soal."""

# Diuji di Plurk asli (27 Nov 2026): "--" menjadi teks coret dan "__" menjadi garis bawah di tampilan Plurk,
# sehingga "-" dan "_" tidak dipakai. "=", "." dan "＿" (garis bawah lebar) tampil utuh.
KARAKTER_PENGGANTI = ("=", ".", "＿")
PEMISAH_KATA = (" ", " / ")


def _cek(karakter: str, pemisah: str) -> None:
    if karakter not in KARAKTER_PENGGANTI:
        raise ValueError(f"karakter pengganti tidak dikenal: {karakter!r}")
    if pemisah not in PEMISAH_KATA:
        raise ValueError(f"pemisah kata tidak dikenal: {pemisah!r}")


def pola(jawaban: str, karakter: str = "=", pemisah: str = " ") -> str:
    """MOHAMMAD HATTA -> '======== ====='."""
    _cek(karakter, pemisah)
    return pemisah.join(karakter * len(k) for k in jawaban.split())


def clue2(jawaban: str, karakter: str = "=", pemisah: str = " ") -> str:
    """MOHAMMAD HATTA -> '13 huruf: ======== ====='."""
    n = len(jawaban.replace(" ", ""))
    return f"{n} huruf: {pola(jawaban, karakter, pemisah)}"


def clue3(jawaban: str, karakter: str = "=", pemisah: str = " ") -> str:
    """MOHAMMAD HATTA -> 'M======= ====A' (awal & akhir seluruh jawaban, bukan per kata)."""
    _cek(karakter, pemisah)
    kata = jawaban.upper().split()
    bagian = [karakter * len(k) for k in kata]
    bagian[0] = kata[0][0] + bagian[0][1:]
    bagian[-1] = bagian[-1][:-1] + kata[-1][-1]
    return pemisah.join(bagian)
