"""Penilaian balasan pemain dalam satu soal.

Fungsi murni: dipanggil ulang tiap tick dengan SEMUA balasan yang sudah terbaca; hasilnya
deterministik karena hanya bergantung pada urutan ID balasan, bukan waktu bot memeriksa.
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from app.core.matching import cocok

MAKS_KARAKTER = 40
MAKS_PER_FASE = 3


class Status(StrEnum):
    BENAR = "benar"
    SALAH = "salah"
    LEWAT_BATAS = "lewat_batas"
    TERLALU_PANJANG = "terlalu_panjang"
    DI_LUAR_SOAL = "di_luar_soal"
    DIBLOKIR = "diblokir"


@dataclass(frozen=True)
class Balasan:
    id: int
    pemain_id: int
    teks: str


@dataclass(frozen=True)
class Pemenang:
    balasan: Balasan
    fase: int  # 0 = sebelum clue, 1-3 = setelah clue ke-n


@dataclass
class HasilPenilaian:
    status: dict[int, Status] = field(default_factory=dict)  # id balasan -> status
    fase: dict[int, int] = field(default_factory=dict)  # id balasan -> fase (hanya yang dinilai)
    pemenang: Pemenang | None = None


def fase_balasan(balasan_id: int, marker_ids: Sequence[int]) -> int:
    """Fase = jumlah penanda (soal, clue 1-3) sebelum balasan, dikurangi satu.
    -1 berarti balasan masuk sebelum soal diposting."""
    return sum(1 for m in marker_ids if m < balasan_id) - 1


def nilai_balasan(
    balasan: Iterable[Balasan],
    jawaban: str,
    marker_ids: Sequence[int],
    *,
    bot_id: int,
    diblokir: frozenset[int] | set[int] = frozenset(),
    penutup_id: int | None = None,
    maks_karakter: int = MAKS_KARAKTER,
    maks_per_fase: int = MAKS_PER_FASE,
) -> HasilPenilaian:
    """Nilai semua balasan untuk satu soal.

    marker_ids : ID balasan bot [soal, clue1, clue2, clue3] yang sudah diposting (urut).
    penutup_id : ID balasan bot "jawaban dibuka"; balasan sesudahnya di_luar_soal.

    Aturan (urut): balasan bot dibuang -> diblokir -> sebelum soal / setelah penutup /
    setelah pemenang = di_luar_soal -> balasan ke-(maks_per_fase+1) dst. per pemain per fase
    = lewat_batas -> > maks_karakter = terlalu_panjang -> cocok = benar (yang pertama menang) / salah.
    """
    if not marker_ids:
        raise ValueError("marker_ids kosong: soal belum diposting")
    hasil = HasilPenilaian()
    hitungan: Counter[tuple[int, int]] = Counter()

    for b in sorted(balasan, key=lambda x: x.id):
        if b.pemain_id == bot_id:
            continue
        if b.pemain_id in diblokir:
            hasil.status[b.id] = Status.DIBLOKIR
            continue
        fase = fase_balasan(b.id, marker_ids)
        if fase < 0 or hasil.pemenang is not None or (penutup_id is not None and b.id > penutup_id):
            hasil.status[b.id] = Status.DI_LUAR_SOAL
            continue

        hasil.fase[b.id] = fase
        hitungan[(b.pemain_id, fase)] += 1
        if hitungan[(b.pemain_id, fase)] > maks_per_fase:
            hasil.status[b.id] = Status.LEWAT_BATAS
        elif len(b.teks.strip()) > maks_karakter:
            hasil.status[b.id] = Status.TERLALU_PANJANG
        elif cocok(jawaban, b.teks):
            hasil.status[b.id] = Status.BENAR
            hasil.pemenang = Pemenang(b, fase)
        else:
            hasil.status[b.id] = Status.SALAH
    return hasil
