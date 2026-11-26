from datetime import date, datetime, time, timedelta

import pytest

from app.clock import WIB
from app.core.schedule import Jadwal, awal_minggu, minggu_klasemen, rentang_minggu

J = Jadwal()


def wib(*a):
    return datetime(*a, tzinfo=WIB)


# 30 Nov 2026 = Senin, 1 Des = Selasa, 2 Des = Rabu, 4 Des = Jumat
@pytest.mark.parametrize(
    "now, harapan",
    [
        (wib(2026, 11, 30, 12, 0), 1),
        (wib(2026, 11, 30, 20, 0, 59), 5),
        (wib(2026, 11, 30, 12, 1), None),
        (wib(2026, 11, 30, 22, 30), None),
        (wib(2026, 12, 1, 12, 0), None),  # Selasa
        (wib(2026, 12, 4, 14, 0), None),  # Jumat
        (wib(2026, 12, 2, 18, 0), 4),  # Rabu
    ],
)
def test_slot_sesi(now, harapan):
    assert J.slot_sesi(now) == harapan


def test_hari_aktif():
    aktif = [J.hari_aktif_pada(date(2026, 11, 30) + timedelta(days=i)) for i in range(7)]
    # Sen Sel Rab Kam Jum Sab Min
    assert aktif == [True, False, True, True, False, True, True]


@pytest.mark.parametrize(
    "now, harapan",
    [
        (wib(2026, 11, 30, 11, 58), (wib(2026, 11, 30, 12, 0), 1)),
        (wib(2026, 11, 30, 12, 0), (wib(2026, 11, 30, 14, 0), 2)),
        (wib(2026, 11, 30, 20, 5), (wib(2026, 12, 2, 12, 0), 1)),  # Senin malam -> Rabu (lewati Selasa)
        (wib(2026, 12, 3, 22, 0), (wib(2026, 12, 5, 12, 0), 1)),  # Kamis malam -> Sabtu (lewati Jumat)
    ],
)
def test_sesi_berikutnya(now, harapan):
    assert J.sesi_berikutnya(now) == harapan


def test_jadwal_kustom():
    j = Jadwal.dari([0], [time(19), time(9)])
    assert j.jam_sesi == (time(9), time(19))
    assert j.sesi_berikutnya(wib(2026, 11, 30, 20, 0)) == (wib(2026, 12, 7, 9, 0), 1)
    assert j.sesi_terakhir_hari_ini(2)


@pytest.mark.parametrize(
    "d, harapan",
    [
        (date(2026, 12, 2), date(2026, 12, 2)),  # Rabu
        (date(2026, 12, 6), date(2026, 12, 2)),  # Minggu
        (date(2026, 12, 7), date(2026, 12, 2)),  # Senin
        (date(2026, 12, 8), date(2026, 12, 9)),  # Selasa: periode baru
    ],
)
def test_awal_minggu(d, harapan):
    assert awal_minggu(d) == harapan


def test_rentang_dan_klasemen_selasa():
    assert rentang_minggu(date(2026, 12, 2)) == (date(2026, 12, 2), date(2026, 12, 7))
    assert minggu_klasemen(date(2026, 12, 8)) == date(2026, 12, 2)  # Selasa -> final minggu lalu
    assert minggu_klasemen(date(2026, 12, 7)) == date(2026, 12, 2)
