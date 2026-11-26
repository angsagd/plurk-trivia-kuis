"""Rumus skor. Sementara: ceil(jumlah_huruf / (1 + clue_keluar)). Rumus dipilih lewat pengaturan."""

import math
from collections.abc import Callable

from app.core.matching import jumlah_huruf

RumusSkor = Callable[[int, int], int]  # (jumlah_huruf, jumlah_clue_keluar) -> skor


def ceil_bagi(n_huruf: int, n_clue: int) -> int:
    return math.ceil(n_huruf / (1 + n_clue))


RUMUS: dict[str, RumusSkor] = {"ceil_bagi": ceil_bagi}
RUMUS_DEFAULT = "ceil_bagi"


def hitung_skor(jawaban: str, fase: int, rumus: str = RUMUS_DEFAULT) -> int:
    """fase = jumlah clue yang sudah keluar saat jawaban benar (0-3)."""
    if not 0 <= fase <= 3:
        raise ValueError(f"fase harus 0-3, bukan {fase}")
    try:
        fungsi = RUMUS[rumus]
    except KeyError:
        raise ValueError(f"rumus skor tidak dikenal: {rumus}") from None
    return fungsi(jumlah_huruf(jawaban), fase)
