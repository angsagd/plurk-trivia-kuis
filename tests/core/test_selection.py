import random
from collections import Counter

from app.core.selection import KandidatSoal, StokTopik, bentrok, pilih_soal, pilih_topik


def buat_topik(tid, n, cycle=1, used_cycle=0, mulai=0):
    soal = [
        KandidatSoal(
            tid * 10_000 + i,
            tid,
            f"Soal {tid}-{i}?",
            f"Clue {tid}-{i}",
            f"JAWAB{chr(65 + tid)}{i:04d}",
            used_cycle,
        )
        for i in range(mulai, mulai + n)
    ]
    return StokTopik(tid, cycle, soal)


def test_bobot_topik_500_vs_1500():
    rng = random.Random(42)
    hitung = Counter(pilih_topik({1: 500, 2: 1500}, rng) for _ in range(10_000))
    assert 2.8 < hitung[2] / hitung[1] < 3.2


def test_pilih_10_soal_unik_dan_used_cycle():
    stok = [buat_topik(1, 50), buat_topik(2, 50)]
    h = pilih_soal(stok, random.Random(1))
    assert len(h.soal) == 10 and len({s.id for s in h.soal}) == 10
    assert all(h.used_cycle[s.id] == 1 for s in h.soal)
    assert h.cycle_baru == {} and h.peringatan == []


def test_hanya_soal_dengan_used_cycle_kurang_dari_cycle():
    t = StokTopik(
        1,
        2,
        [KandidatSoal(i, 1, f"S{i}?", f"C{i}", f"JAWAB{i:03d}".replace("0", "X"), 2) for i in range(5)]
        + [KandidatSoal(99, 1, "S99?", "C99", "SISA", 1)],
    )
    h = pilih_soal([t], random.Random(3), n=1)
    assert [s.id for s in h.soal] == [99]


def test_topik_habis_cycle_naik_hanya_topik_itu():
    habis = buat_topik(1, 20, cycle=1, used_cycle=1)
    stok = [habis, buat_topik(2, 20)]
    h = pilih_soal(stok, random.Random(5), n=10)
    assert h.cycle_baru == {1: 2}
    assert all(h.used_cycle[s.id] == 2 for s in h.soal if s.topik_id == 1)


def test_tolak_jawaban_bocor_dan_sama():
    a = KandidatSoal(1, 1, "Pulau dewata?", "Dekat Lombok", "BALI")
    b = KandidatSoal(2, 1, "Pulau mana yang dekat Bali?", "Ada Gili", "LOMBOK")
    c = KandidatSoal(3, 1, "Pulau seribu pura?", "Dewata", "BALI")
    d = KandidatSoal(4, 1, "Kota gudeg?", "Jawa", "YOGYAKARTA")
    assert bentrok(a, b) and bentrok(a, c) and not bentrok(a, d)


def test_pilih_menghindari_soal_thread_lain():
    berjalan = KandidatSoal(1, 1, "Pulau dewata?", "Dekat Lombok", "BALI")
    lain = [
        KandidatSoal(2, 1, "Pulau mana yang dekat Bali?", "Ada Gili", "LOMBOK"),
        KandidatSoal(3, 1, "Kota gudeg?", "Jawa", "YOGYAKARTA"),
    ]
    t = StokTopik(1, 1, [berjalan, *lain])
    for seed in range(30):
        h = pilih_soal([t], random.Random(seed), n=1, sudah_ada=[berjalan])
        assert [s.id for s in h.soal] == [3]


def test_cadangan_setelah_maks_percobaan():
    berjalan = KandidatSoal(1, 1, "Pulau dewata?", "x", "BALI")
    t = StokTopik(1, 1, [berjalan, KandidatSoal(2, 1, "Dekat Bali?", "y", "LOMBOK")])
    h = pilih_soal([t], random.Random(0), n=1, sudah_ada=[berjalan])
    assert [s.id for s in h.soal] == [2] and "percobaan" in h.peringatan[0]


def test_stok_kurang_dari_10():
    h = pilih_soal([buat_topik(1, 4)], random.Random(0))
    assert len(h.soal) == 4 and "habis" in h.peringatan[-1]


def test_lewati_soal_memakai_aturan_sama():
    stok = [buat_topik(1, 30)]
    sesi = pilih_soal(stok, random.Random(9)).soal
    pengganti = pilih_soal(stok, random.Random(10), n=1, sudah_ada=sesi).soal[0]
    assert pengganti.id not in {s.id for s in sesi}
