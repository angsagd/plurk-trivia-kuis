from app.core.judging import Balasan, Status, fase_balasan, nilai_balasan

BOT = 1
SOAL, CLUE1, CLUE2, CLUE3 = 100, 200, 300, 400


def nilai(balasan, marker=(SOAL,), **kw):
    return nilai_balasan(balasan, "BALI", list(marker), bot_id=BOT, **kw)


def test_fase_balasan():
    m = [SOAL, CLUE1, CLUE2, CLUE3]
    assert [fase_balasan(i, m) for i in (50, 150, 250, 350, 450)] == [-1, 0, 1, 2, 3]


def test_pemenang_id_terkecil_bukan_urutan_masuk_list():
    h = nilai([Balasan(120, 8, "bali"), Balasan(110, 7, "Bali!")])
    assert h.pemenang.balasan.id == 110 and h.pemenang.fase == 0
    assert h.status == {110: Status.BENAR, 120: Status.DI_LUAR_SOAL}


def test_fase_pemenang_mengikuti_penanda():
    h = nilai([Balasan(250, 7, "bali")], marker=(SOAL, CLUE1, CLUE2))
    assert h.pemenang.fase == 1


def test_sebelum_soal_di_luar_soal():
    h = nilai([Balasan(90, 7, "bali"), Balasan(130, 8, "bali")])
    assert h.status[90] is Status.DI_LUAR_SOAL and h.pemenang.balasan.id == 130


def test_balasan_bot_dibuang_dan_pemain_diblokir():
    h = nilai([Balasan(110, BOT, "BALI"), Balasan(120, 9, "bali"), Balasan(130, 7, "bali")], diblokir={9})
    assert 110 not in h.status
    assert h.status[120] is Status.DIBLOKIR
    assert h.pemenang.balasan.id == 130


def test_terlalu_panjang():
    teks = "bali " + "x" * 36  # 41 karakter
    assert len(teks) == 41
    h = nilai([Balasan(110, 7, teks), Balasan(120, 7, "bali" + "x" * 0)])
    assert h.status[110] is Status.TERLALU_PANJANG
    assert h.pemenang.balasan.id == 120
    assert nilai([Balasan(110, 7, ("bali " + "x" * 35))]).status[110] is Status.BENAR  # 40 karakter


def test_balasan_keempat_per_fase_lewat_batas():
    bs = [Balasan(110 + i, 7, t) for i, t in enumerate(["a", "b", "c", "bali"])]
    h = nilai(bs)
    assert [h.status[b.id] for b in bs] == [Status.SALAH] * 3 + [Status.LEWAT_BATAS]
    assert h.pemenang is None


def test_batas_per_fase_direset_di_fase_berikutnya():
    bs = [Balasan(110 + i, 7, "x") for i in range(3)] + [Balasan(210, 7, "bali")]
    h = nilai(bs, marker=(SOAL, CLUE1))
    assert h.status[210] is Status.BENAR and h.pemenang.fase == 1


def test_setelah_jawaban_dibuka_di_luar_soal():
    h = nilai([Balasan(510, 7, "bali")], marker=(SOAL, CLUE1, CLUE2, CLUE3), penutup_id=500)
    assert h.status[510] is Status.DI_LUAR_SOAL and h.pemenang is None


def test_deterministik_saat_dinilai_ulang():
    bs = [Balasan(110, 7, "x"), Balasan(120, 8, "bali")]
    assert nilai(bs).status == nilai(list(reversed(bs))).status
