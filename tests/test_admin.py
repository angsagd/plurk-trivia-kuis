"""Tes tahap 5: admin web (login, keamanan, 8 halaman, aksi utama)."""

import io
import re
from datetime import timedelta

import pyotp
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import cli
from app.bot.pengaturan import muat_pengaturan
from app.db import sesi_db
from app.models import (
    AdminAudit,
    BotState,
    Command,
    CommandAlias,
    GameSession,
    Player,
    Question,
    ScheduledPost,
    ScoreAdjustment,
    SessionQuestion,
    Template,
    Topic,
)
from tests.test_engine import ANDI, BUDI, Harness, jam

PASSWORD = "password-admin-panjang"


@pytest.fixture
def h(engine, monkeypatch):
    monkeypatch.setenv("APP_SECRET_KEY", "k" * 48)
    monkeypatch.setenv("COOKIE_SECURE", "false")
    monkeypatch.setenv("TICK_SECONDS", "5")  # jam palsu: halaman admin memakai jam bot
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert cli.main(["buat-admin", "--username", "admin", "--password-stdin"]) == 0
    return Harness(engine, jam(11, 59))


@pytest.fixture
def klien(h):
    from app.admin.main import app

    with TestClient(app) as c:
        yield c


def masuk(klien: TestClient, password: str = PASSWORD, totp: str = "") -> str:
    r = klien.post(
        "/login", data={"username": "admin", "password": password, "totp": totp}, follow_redirects=False
    )
    assert r.status_code == 303 and r.headers["location"] == "/", r.headers.get("location")
    return csrf(klien)


def csrf(klien: TestClient, path: str = "/log") -> str:
    m = re.search(r'name="csrf" value="([0-9a-f]+)"', klien.get(path).text)
    assert m
    return m.group(1)


def post(klien, path, token, **data):
    return klien.post(path, data={"csrf": token, **data}, follow_redirects=False)


def pesan(r) -> str:
    from urllib.parse import parse_qs, urlparse

    q = parse_qs(urlparse(r.headers["location"]).query)
    return (q.get("ok") or q.get("err") or [""])[0]


# ====================================================================== keamanan

HALAMAN = ["/", "/peringkat", "/soal", "/pengaturan", "/libur", "/riwayat", "/perintah", "/log"]


@pytest.mark.parametrize("path", HALAMAN)
def test_belum_login_dialihkan(klien, path):
    r = klien.get(path, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"


def test_htmx_belum_login_hx_redirect(klien):
    r = klien.get("/partial/thread", headers={"HX-Request": "true"})
    assert r.headers["HX-Redirect"] == "/login"


def test_login_cookie_aman(h, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    from app.admin.main import app
    from app.config import get_settings

    get_settings.cache_clear()
    with TestClient(app) as c:
        r = c.post("/login", data={"username": "admin", "password": PASSWORD}, follow_redirects=False)
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie


def test_header_keamanan(klien):
    r = klien.get("/login")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"


def test_login_salah_dan_batas_5_kali(klien, h):
    for _ in range(5):
        r = klien.post("/login", data={"username": "admin", "password": "salah"}, follow_redirects=False)
        assert "salah" in r.headers["location"]
    r = klien.post("/login", data={"username": "admin", "password": PASSWORD}, follow_redirects=False)
    assert "Terlalu+banyak" in r.headers["location"]
    with sesi_db(h.engine) as db:
        assert db.scalar(select(func.count()).where(AdminAudit.action == "login_gagal")) == 5


def test_post_tanpa_csrf_ditolak(klien):
    masuk(klien)
    r = klien.post("/kontrol/jalankan", data={}, follow_redirects=False)
    assert r.status_code == 403
    r = klien.post("/kontrol/jalankan", data={"csrf": "0" * 32}, follow_redirects=False)
    assert r.status_code == 403


def test_cookie_palsu_ditolak(klien):
    klien.cookies.set("kuis_sesi", "eyJhIjoxfQ.palsu")
    assert klien.get("/", follow_redirects=False).status_code == 303


def test_totp(klien, h, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(PASSWORD + "\n"))
    assert cli.main(["buat-admin", "--username", "admin", "--reset", "--totp", "--password-stdin"]) == 0
    r = klien.post("/login", data={"username": "admin", "password": PASSWORD}, follow_redirects=False)
    assert r.headers["location"].startswith("/login")
    with sesi_db(h.engine) as db:
        from app.models import Admin

        rahasia = db.scalar(select(Admin.totp_secret))
    masuk(klien, totp=pyotp.TOTP(rahasia).now())


def test_logout(klien):
    token = masuk(klien)
    post(klien, "/logout", token)
    klien.cookies.clear()
    assert klien.get("/", follow_redirects=False).status_code == 303


# ====================================================================== halaman dengan data


def siapkan_data(h: Harness) -> None:
    """Satu sesi berjalan dengan pemenang, satu soal sudah tampil, dan pemain."""
    h.tick(3)
    h.balas(ANDI, "siap")
    h.tick(2)  # active, soal #1
    h.balas(BUDI, h.jawaban_sekarang())
    h.tick()  # pemenang + 04


@pytest.mark.parametrize(
    "path", [*HALAMAN, "/partial/thread", "/riwayat/1", "/peringkat?pemain=1&periode=semua"]
)
def test_semua_halaman_tampil(klien, h, path):
    siapkan_data(h)
    masuk(klien)
    r = klien.get(path)
    assert r.status_code == 200, r.text[:500]


def test_dashboard_menampilkan_thread_dan_jawaban(klien, h):
    siapkan_data(h)
    masuk(klien)
    teks = klien.get("/partial/thread").text
    assert "Sesi 1" in teks and "active" in teks and "Lewati soal berikutnya" in teks


# ====================================================================== kontrol


def test_kontrol_jalankan_jeda_hentikan(klien, h):
    siapkan_data(h)
    token = masuk(klien)
    assert "Jeda" in pesan(post(klien, "/kontrol/jeda", token))
    post(klien, "/kontrol/hentikan", token)
    with sesi_db(h.engine) as db:
        assert db.get_one(BotState, 1).status == "hentikan"
    h.tick(2)
    with sesi_db(h.engine) as db:
        assert db.get_one(BotState, 1).status == "berhenti"
        assert all(s.status == "die" for s in db.scalars(select(GameSession)))
    assert h.posting_bot()[-1].startswith("Terima kasih sudah bermain!")


def test_lewati_soal_berikutnya(klien, h):
    siapkan_data(h)
    token = masuk(klien)
    with sesi_db(h.engine) as db:
        lama = db.scalar(select(SessionQuestion.question_id).where(SessionQuestion.number == 2))
    r = post(klien, "/sesi/1/lewati", token)
    assert "diganti" in pesan(r)
    with sesi_db(h.engine) as db:
        baru = db.scalar(select(SessionQuestion.question_id).where(SessionQuestion.number == 2))
        semua = list(db.scalars(select(SessionQuestion.question_id)))
    assert baru != lama and len(set(semua)) == len(semua)


# ====================================================================== bank soal

BANK = "Ibu kota negara Jepang?|Dahulu bernama Edo|TOKYO\nPlanet terbesar?|Bintik Merah Raksasa|JUPITER\n"


def unggah(klien, token, nama, isi):
    return klien.post(
        "/soal/unggah", data={"csrf": token}, files={"berkas": (nama, isi.encode(), "text/plain")}
    )


def test_unggah_pratinjau_lalu_simpan(klien, h):
    token = masuk(klien)
    r = unggah(klien, token, "trivia_05_campuran.txt", BANK)
    assert "[05] Campuran" in r.text and "topik baru" in r.text and "Simpan ke bank soal" in r.text
    with sesi_db(h.engine) as db:
        assert db.scalar(select(Topic).where(Topic.number == "05")) is None  # pratinjau tidak menyimpan
    isi_b64 = re.search(r'name="isi_b64" value="([^"]+)"', r.text).group(1)
    r = post(klien, "/soal/simpan", token, nama_file="trivia_05_campuran.txt", isi_b64=isi_b64)
    assert "2 soal baru" in pesan(r)
    with sesi_db(h.engine) as db:
        assert (
            db.scalar(
                select(func.count()).where(
                    Question.topic_id == db.scalar(select(Topic.id).where(Topic.number == "05"))
                )
            )
            == 2
        )
        assert (
            db.scalar(select(AdminAudit).where(AdminAudit.action == "unggah_topik")).detail["soal_baru"] == 2
        )


@pytest.mark.parametrize("nama", ["trivia_4_musik.txt", "musik.txt"])
def test_unggah_nama_file_salah(klien, nama):
    token = masuk(klien)
    assert "Nama file" in unggah(klien, token, nama, BANK).text


def test_unggah_bukan_utf8(klien):
    token = masuk(klien)
    r = klien.post(
        "/soal/unggah",
        data={"csrf": token},
        files={"berkas": ("trivia_05_x.txt", "Soal é|c|BALI".encode("latin-1"))},
    )
    assert "UTF-8" in r.text


def test_ganti_nama_dan_tawaran_kemiripan(klien, h):
    token = masuk(klien)
    # dua soal yang sama persis dengan topik karangan milik harness (nomor 01)
    sama = (
        "Soal karangan nomor 1?|Petunjuk karangan nomor 1|JAWABAA\n"
        "Soal karangan nomor 2?|Petunjuk karangan nomor 2|JAWABAB\n"
    )
    r = unggah(klien, token, "trivia_01_nama_baru.txt", sama)
    assert "Nomor 01 sudah dipakai" in r.text
    r = unggah(klien, token, "trivia_09_nama_baru.txt", sama)
    assert "Lebih dari separuh soal" in r.text and "Karangan" in r.text
    with sesi_db(h.engine) as db:
        tid = db.scalar(select(Topic.id).where(Topic.number == "01"))
    r = post(klien, f"/soal/topik/{tid}/ganti-nama", token, nama_file="trivia_01_sejarah_karangan.txt")
    assert "Sejarah Karangan" in pesan(r)
    r = post(klien, f"/soal/topik/{tid}/ganti-nama", token, nama_file="trivia_01_sejarah_karangan.txt")
    assert "sama dengan nama sekarang" in pesan(r)
    with sesi_db(h.engine) as db:
        t = db.get_one(Topic, tid)
        assert (t.number, t.name, t.filename) == ("01", "Sejarah Karangan", "trivia_01_sejarah_karangan.txt")
        assert db.scalar(select(func.count()).where(Question.topic_id == tid)) == 30  # riwayat soal tetap


def test_topik_dan_soal_nonaktif(klien, h):
    token = masuk(klien)
    post(klien, "/soal/topik/1/aktif", token)
    post(klien, "/soal/1/aktif", token, kembali_ke="/soal?cari=nomor")
    with sesi_db(h.engine) as db:
        assert not db.get_one(Topic, 1).is_active and not db.get_one(Question, 1).is_active
    assert "Soal karangan nomor 1?" in klien.get("/soal?cari=nomor+1%3F").text


# ====================================================================== pengaturan


def test_simpan_jadwal_aturan_rumus_clue_mode_uji(klien, h):
    token = masuk(klien)
    r = klien.post(
        "/pengaturan/jadwal",
        data={"csrf": token, "mulai": "10:00", "selesai": "16:00", "interval": "180", "hari": ["0", "2"]},
        follow_redirects=False,
    )
    assert "10:00, 13:00" in pesan(r)
    aturan = {
        "maks_soal": 5,
        "umur_hold_menit": 45,
        "maks_karakter_balasan": 30,
        "maks_per_fase": 2,
        "maks_posting_per_tick": 3,
        "batas_teks": 300,
        "jeda_posting_detik": 1,
    }
    assert "disimpan" in pesan(post(klien, "/pengaturan/aturan", token, **aturan))
    assert "harus" in pesan(post(klien, "/pengaturan/aturan", token, **{**aturan, "maks_soal": 11}))
    post(klien, "/pengaturan/clue", token, karakter="_", pemisah=" / ")
    assert "Isi ID akun" in pesan(post(klien, "/pengaturan/mode-uji", token, aktif="1", akun=""))
    post(klien, "/pengaturan/mode-uji", token, aktif="1", akun="123, 456")
    with sesi_db(h.engine) as db:
        p = muat_pengaturan(db)
    assert p.jam_sesi == ["10:00", "13:00"] and p.hari_aktif == [0, 2]
    assert (p.maks_soal, p.maks_posting_per_tick, p.karakter_pengganti, p.pemisah_kata) == (5, 3, "_", " / ")
    assert p.mode_uji and p.mode_uji_limited_to == [123, 456]


def test_template_simpan_pratinjau_reset(klien, h):
    token = masuk(klien)
    assert "Template disimpan" in pesan(
        post(klien, "/pengaturan/template", token, key="ajakan", isi="Siapa siap? Balas apa saja!")
    )
    h.tick(3)
    assert h.posting_bot()[-1] == "Siapa siap? Balas apa saja!"
    assert "tidak valid" in pesan(post(klien, "/pengaturan/template", token, key="ajakan", isi="rusak {"))
    r = klien.get("/pengaturan/pratinjau-template", params={"isi": "Halo {nama}"})
    assert "Halo pemain_a" in r.text
    post(klien, "/pengaturan/template", token, key="ajakan", isi="x", aksi="reset")
    with sesi_db(h.engine) as db:
        assert db.get(Template, "ajakan") is None


def test_kirim_uji_privat_clue(klien, h):
    token = masuk(klien)
    assert "Isi ID akun" in pesan(post(klien, "/pengaturan/uji-clue", token))
    post(klien, "/pengaturan/mode-uji", token, akun="777")
    assert "diantre" in pesan(post(klien, "/pengaturan/uji-clue", token))
    h.status_bot("berhenti")
    h.tick()
    assert h.fake.jumlah_plurk() == 1
    row = h.fake.db.execute("SELECT content, limited_to FROM plurks").fetchone()
    assert "Clue 2: 13 huruf" in row[0] and row[1] == "777"


# ====================================================================== peringkat


def test_koreksi_blokir_csv(klien, h):
    siapkan_data(h)
    token = masuk(klien)
    with sesi_db(h.engine) as db:
        budi = db.scalar(select(Player).where(Player.nick == "budi"))
    assert "wajib" in pesan(post(klien, f"/peringkat/pemain/{budi.id}/koreksi", token, poin=5, alasan=""))
    assert "+5" in pesan(
        post(klien, f"/peringkat/pemain/{budi.id}/koreksi", token, poin=5, alasan="bonus uji")
    )
    teks = klien.get("/peringkat?periode=minggu").text
    assert "budi" in teks and "<strong>12</strong>" in teks  # 7 poin (benar di fase Soal) + 5 koreksi
    csv = klien.get("/peringkat/csv?periode=minggu").text
    assert "1,budi,12,1,1,Soal," in csv
    post(klien, f"/peringkat/pemain/{budi.id}/blokir", token)
    with sesi_db(h.engine) as db:
        assert db.get_one(Player, budi.id).is_blocked
        assert db.scalar(select(ScoreAdjustment.reason)) == "bonus uji"


# ====================================================================== libur


def test_posting_libur_dan_juara_mingguan(klien, h):
    siapkan_data(h)  # budi menang minggu 25 Nov - 30 Nov
    token = masuk(klien)
    r = post(klien, "/libur", token, tanggal="2026-11-30", jam="15:00", isi="x")
    assert "hari aktif" in pesan(r)
    r = post(
        klien,
        "/libur",
        token,
        tanggal="2026-12-01",
        jam="10:00",
        qualifier="says",
        isi="Info libur hari ini",
        balasan="1",
    )
    assert "dijadwalkan" in pesan(r)
    assert "Info libur hari ini" in klien.get("/libur").text
    # Selasa 1 Des: 10:00 posting terjadwal, 12:00 juara mingguan
    h.clock.set(jam(9, 59, hari=jam(0).replace(day=1, month=12)))
    h.tick(2)
    assert h.fake.jumlah_plurk() == 2  # sesi Senin + posting libur
    h.clock.set(jam(12, 0, hari=jam(0).replace(day=1, month=12)))
    h.tick()
    isi = [r[0] for r in h.fake.db.execute("SELECT content FROM plurks ORDER BY id")]
    assert isi[1] == "Info libur hari ini" and isi[2].startswith(
        "🏆 Juara minggu ini (25–30 November): budi!"
    )
    h.tick()
    assert h.fake.jumlah_plurk() == 3  # juara mingguan tidak dobel
    with sesi_db(h.engine) as db:
        sp = db.scalar(select(ScheduledPost))
        assert sp.status == "antre" and sp.qualifier == "says"
    assert "terkirim" in klien.get("/libur").text


# ====================================================================== perintah


def test_perintah_bawaan_kustom_dan_bentrok(klien, h):
    token = masuk(klien)
    with sesi_db(h.engine) as db:
        assert {c.key for c in db.scalars(select(Command))} >= {
            "jadwal",
            "klasemen",
            "rank",
            "bantuan",
            "rekor",
        }
        assert db.scalar(select(CommandAlias).where(CommandAlias.alias == "?")) is not None
    r = post(klien, "/perintah-kustom", token, key="top", respons="hai")
    assert "sudah dipakai" in pesan(r)
    r = post(
        klien, "/perintah-kustom", token, key="halo", alias="hai, hello", respons="Halo {nama}! Kamu #{rank}"
    )
    assert "isian tidak diizinkan" in pesan(r)
    r = post(klien, "/perintah-kustom", token, key="Halo", alias="hai, hello", respons="Halo {nama}!")
    assert "ditambahkan" in pesan(r)
    with sesi_db(h.engine) as db:
        halo = db.scalar(select(Command).where(Command.key == "halo"))
        rank = db.scalar(select(Command).where(Command.key == "rank"))
    assert "sudah dipakai" in pesan(
        post(klien, f"/perintah/{rank.id}", token, alias="peringkat, hai", template="x", aktif="1")
    )
    assert "isian tidak dikenal" in pesan(
        post(klien, f"/perintah/{rank.id}", token, alias="skor", template="{rahasia}", aktif="1")
    )
    assert "disimpan" in pesan(
        post(
            klien,
            f"/perintah/{rank.id}",
            token,
            alias="skor, poin",
            template="#{rank}, {poin} poin",
            aktif="1",
        )
    )
    post(klien, f"/perintah/{halo.id}/respons", token, isi="Hai juga, {nama}!")
    assert "halo" in klien.get(f"/perintah?pilih={halo.id}").text
    assert "dihapus" in pesan(post(klien, f"/perintah/{halo.id}/hapus", token))
    assert "Hanya kata kunci kustom" in pesan(post(klien, f"/perintah/{rank.id}/hapus", token))
    post(klien, "/perintah/fitur", token, aktif="1", cooldown=30, batas=10, kedaluwarsa=60)
    with sesi_db(h.engine) as db:
        p = muat_pengaturan(db)
        assert p.perintah_aktif and p.perintah_cooldown_menit == 30
        assert set(db.scalars(select(CommandAlias.alias).where(CommandAlias.command_id == rank.id))) == {
            "skor",
            "poin",
        }


def test_log_admin_mencatat_aksi(klien):
    token = masuk(klien)
    post(klien, "/kontrol/jalankan", token)
    teks = klien.get("/log").text
    assert "bot_aktif" in teks and "login" in teks


def test_sekarang_memakai_jam_bot_di_dev(klien, h):
    h.tick()
    masuk(klien)
    assert "Senin, 30/11/2026" in klien.get("/").text
    assert h.clock.now() - jam(11, 59) == timedelta(minutes=1)
