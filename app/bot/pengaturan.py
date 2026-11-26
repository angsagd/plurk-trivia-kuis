"""Pengaturan permainan: nilai bawaan di kode, ditimpa baris tabel `settings` (diubah dari admin).
Dibaca ulang setiap tick sehingga perubahan berlaku <= 1 menit tanpa restart."""

from dataclasses import dataclass, fields
from datetime import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.clues import KARAKTER_PENGGANTI, PEMISAH_KATA
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
    # Perintah lewat mention (tahap 8)
    "perintah_aktif": False,
    "perintah_cooldown_menit": 60,
    "perintah_batas_global_per_jam": 20,
    "perintah_kedaluwarsa_menit": 60,
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
    perintah_aktif: bool
    perintah_cooldown_menit: int
    perintah_batas_global_per_jam: int
    perintah_kedaluwarsa_menit: int

    @property
    def jadwal(self) -> Jadwal:
        return Jadwal.dari(self.hari_aktif, [time.fromisoformat(j) for j in self.jam_sesi])


def simpan_pengaturan(db: Session, now, **nilai: Any) -> None:
    """Tulis pengaturan ke tabel settings (key harus dikenal). Tidak commit."""
    nama = {f.name for f in fields(Pengaturan)}
    for key, v in nilai.items():
        if key not in nama:
            raise KeyError(key)
        db.merge(Setting(key=key, value=v, updated_at=now))
    db.flush()


def muat_pengaturan(db: Session) -> Pengaturan:
    nilai = dict(BAWAAN)
    nama = {f.name for f in fields(Pengaturan)}
    for s in db.scalars(select(Setting)):
        if s.key in nama:
            nilai[s.key] = s.value
    # Nilai lama yang tidak lagi didukung (mis. karakter '-' / '_') kembali ke bawaan, agar bot tidak error.
    if nilai["karakter_pengganti"] not in KARAKTER_PENGGANTI:
        nilai["karakter_pengganti"] = BAWAAN["karakter_pengganti"]
    if nilai["pemisah_kata"] not in PEMISAH_KATA:
        nilai["pemisah_kata"] = BAWAAN["pemisah_kata"]
    return Pengaturan(**nilai)
