"""Pengaturan permainan: nilai bawaan di kode, ditimpa baris tabel `settings` (diubah dari admin).
Dibaca ulang setiap tick sehingga perubahan berlaku <= 1 menit tanpa restart."""

from dataclasses import dataclass, fields
from datetime import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.schedule import Jadwal
from app.models import Setting

BAWAAN: dict[str, Any] = {
    "hari_aktif": [0, 2, 3, 5, 6],  # date.weekday(): Senin=0; libur Selasa(1) & Jumat(4)
    "jam_sesi": ["12:00", "14:00", "16:00", "18:00", "20:00"],
    "toleransi_slot_menit": 5,  # tick yang terlewat (restart) masih boleh membuka sesi
    "maks_soal": 10,
    "umur_hold_menit": 60,
    "maks_karakter_balasan": 40,
    "maks_per_fase": 3,
    "karakter_pengganti": "=",
    "pemisah_kata": " ",
    "rumus_skor": "ceil_bagi",
    "batas_teks": 360,
    "maks_posting_per_tick": 2,
    "jeda_posting_detik": 3.0,
    "maks_gagal_kirim": 5,
    "qualifier": ":",
    "mode_uji": False,
    "mode_uji_limited_to": [],  # ID akun Plurk admin; dipakai bila mode_uji
}


@dataclass(frozen=True)
class Pengaturan:
    hari_aktif: list[int]
    jam_sesi: list[str]
    toleransi_slot_menit: int
    maks_soal: int
    umur_hold_menit: int
    maks_karakter_balasan: int
    maks_per_fase: int
    karakter_pengganti: str
    pemisah_kata: str
    rumus_skor: str
    batas_teks: int
    maks_posting_per_tick: int
    jeda_posting_detik: float
    maks_gagal_kirim: int
    qualifier: str
    mode_uji: bool
    mode_uji_limited_to: list[int]

    @property
    def jadwal(self) -> Jadwal:
        return Jadwal.dari(self.hari_aktif, [time.fromisoformat(j) for j in self.jam_sesi])


def muat_pengaturan(db: Session) -> Pengaturan:
    nilai = dict(BAWAAN)
    nama = {f.name for f in fields(Pengaturan)}
    for s in db.scalars(select(Setting)):
        if s.key in nama:
            nilai[s.key] = s.value
    return Pengaturan(**nilai)
