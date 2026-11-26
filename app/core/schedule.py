"""Jadwal: hari aktif, slot sesi, sesi berikutnya, dan periode skor mingguan (Rabu-Senin).
Semua waktu dalam WIB; fungsi menerima `now` dari Clock, tidak membaca jam sendiri."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

# date.weekday(): Senin=0 ... Minggu=6
SENIN, SELASA, RABU, KAMIS, JUMAT, SABTU, MINGGU = range(7)
NAMA_HARI = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")


@dataclass(frozen=True)
class Jadwal:
    hari_aktif: frozenset[int] = frozenset({RABU, KAMIS, SABTU, MINGGU, SENIN})
    jam_sesi: tuple[time, ...] = (time(12), time(14), time(16), time(18), time(20))

    @classmethod
    def dari(cls, hari_aktif: Iterable[int], jam_sesi: Iterable[time]) -> "Jadwal":
        return cls(frozenset(hari_aktif), tuple(sorted(jam_sesi)))

    def hari_aktif_pada(self, d: date) -> bool:
        return d.weekday() in self.hari_aktif

    def slot_sesi(self, now: datetime) -> int | None:
        """Nomor sesi (1, 2, ...) bila `now` tepat di menit slot sesi pada hari aktif, selain itu None."""
        if not self.hari_aktif_pada(now.date()):
            return None
        hm = now.time().replace(second=0, microsecond=0)
        for i, jam in enumerate(self.jam_sesi, start=1):
            if hm == jam:
                return i
        return None

    def sesi_berikutnya(self, now: datetime) -> tuple[datetime, int]:
        """(waktu mulai, nomor sesi) sesi pertama yang mulai SETELAH `now`."""
        if not self.hari_aktif or not self.jam_sesi:
            raise ValueError("jadwal kosong")
        for tambah in range(8):
            d = now.date() + timedelta(days=tambah)
            if not self.hari_aktif_pada(d):
                continue
            for i, jam in enumerate(self.jam_sesi, start=1):
                mulai = datetime.combine(d, jam, tzinfo=now.tzinfo)
                if mulai > now:
                    return mulai, i
        raise AssertionError("tidak terjangkau")

    def sesi_terakhir_hari_ini(self, nomor_sesi: int) -> bool:
        return nomor_sesi == len(self.jam_sesi)


# ---------------------------------------------------------------- periode skor mingguan


def awal_minggu(d: date) -> date:
    """week_start = Rabu awal periode Rabu-Senin. Selasa (reset 00.00) sudah masuk periode baru,
    sehingga week_start-nya Rabu esok hari."""
    if d.weekday() == SELASA:
        return d + timedelta(days=1)
    return d - timedelta(days=(d.weekday() - RABU) % 7)


def rentang_minggu(week_start: date) -> tuple[date, date]:
    """(Rabu, Senin) inklusif."""
    return week_start, week_start + timedelta(days=5)


def minggu_klasemen(d: date) -> date:
    """week_start yang ditampilkan perintah klasemen/rank: Selasa -> hasil final minggu lalu."""
    if d.weekday() == SELASA:
        return d - timedelta(days=6)
    return awal_minggu(d)
