"""Pemilihan soal untuk satu sesi (10 soal) dan 'Lewati soal'.

1. Topik dipilih acak dengan bobot = jumlah soal aktif di topik itu.
2. Soal acak dengan used_cycle < cycle topik.
3. Topik habis -> cycle topik itu naik satu (hanya topik itu yang diputar ulang).
4. Topik yang sama boleh muncul berkali-kali.
5. Kandidat ditolak bila jawabannya tertulis (kata utuh) di soal/clue soal lain di sesi itu
   atau thread lain yang berjalan, atau sebaliknya, atau jawabannya sama (maks 50 percobaan).
"""

import random
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from app.core.matching import cocok

MAKS_PERCOBAAN = 50
SOAL_PER_SESI = 10


@dataclass(frozen=True)
class KandidatSoal:
    id: int
    topik_id: int
    soal: str
    clue: str
    jawaban: str
    used_cycle: int = 0


@dataclass(frozen=True)
class StokTopik:
    id: int
    cycle: int
    soal: Sequence[KandidatSoal]  # hanya soal aktif


@dataclass
class HasilPilih:
    soal: list[KandidatSoal] = field(default_factory=list)
    cycle_baru: dict[int, int] = field(default_factory=dict)  # topik_id -> cycle setelah dinaikkan
    used_cycle: dict[int, int] = field(default_factory=dict)  # soal_id -> nilai used_cycle yang disimpan
    peringatan: list[str] = field(default_factory=list)


def pilih_topik(bobot: Mapping[int, int], rng: random.Random) -> int:
    """Topik acak berbobot jumlah soal aktif."""
    ids = [t for t, n in bobot.items() if n > 0]
    if not ids:
        raise ValueError("tidak ada topik aktif yang berisi soal")
    return rng.choices(ids, weights=[bobot[t] for t in ids])[0]


def bentrok(a: KandidatSoal, b: KandidatSoal) -> bool:
    """True bila jawaban salah satu bocor di soal/clue yang lain, atau jawabannya sama."""
    if a.jawaban == b.jawaban:
        return True
    return any(cocok(x.jawaban, y.soal) or cocok(x.jawaban, y.clue) for x, y in ((a, b), (b, a)))


def pilih_soal(
    stok: Iterable[StokTopik],
    rng: random.Random,
    n: int = SOAL_PER_SESI,
    sudah_ada: Sequence[KandidatSoal] = (),
    maks_percobaan: int = MAKS_PERCOBAAN,
) -> HasilPilih:
    """Pilih n soal. `sudah_ada` = soal lain di sesi ini (untuk Lewati soal) dan soal thread lain
    yang sedang berjalan; soal itu tidak dipilih ulang dan dicek bentrok.
    Pemanggil menyimpan HasilPilih.cycle_baru ke topik dan HasilPilih.used_cycle ke soal."""
    topik = {t.id: t for t in stok if t.soal}
    bobot = {t.id: len(t.soal) for t in topik.values()}
    cycle = {t.id: t.cycle for t in topik.values()}
    hasil = HasilPilih()
    pembanding: list[KandidatSoal] = list(sudah_ada)
    dipakai = {s.id for s in sudah_ada}

    for _ in range(n):
        cadangan: KandidatSoal | None = None
        terpilih: KandidatSoal | None = None
        for _ in range(maks_percobaan):
            if not bobot:
                break
            tid = pilih_topik(bobot, rng)
            tersedia = [s for s in topik[tid].soal if s.used_cycle < cycle[tid] and s.id not in dipakai]
            if not tersedia:
                tersedia = [s for s in topik[tid].soal if s.id not in dipakai]
                if not tersedia:
                    del bobot[tid]  # seluruh soal topik ini sudah ada di sesi / thread lain
                    continue
                cycle[tid] += 1  # topik habis: putar ulang topik ini saja
                hasil.cycle_baru[tid] = cycle[tid]
            kandidat = rng.choice(tersedia)
            if any(bentrok(kandidat, p) for p in pembanding):
                cadangan = kandidat
                continue
            terpilih = kandidat
            break

        if terpilih is None and cadangan is not None:
            terpilih = cadangan
            hasil.peringatan.append(
                f"soal {cadangan.id}: tidak ada kandidat bebas bentrok setelah {maks_percobaan} percobaan"
            )
        if terpilih is None:
            hasil.peringatan.append(f"stok soal habis: hanya {len(hasil.soal)} dari {n} soal terpilih")
            break
        hasil.soal.append(terpilih)
        hasil.used_cycle[terpilih.id] = cycle[terpilih.topik_id]
        pembanding.append(terpilih)
        dipakai.add(terpilih.id)
    return hasil
