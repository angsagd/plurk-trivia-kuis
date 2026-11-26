"""Tes tahap 6: backup/pulihkan, notifikasi Telegram, watchdog bot."""

import gzip
import sqlite3
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select

from app import cli, notifikasi
from app.backup import buat_backup, pulihkan, rotasi
from app.clock import WIB, SystemClock
from app.db import sesi_db
from app.models import BotState, Setting


class Rekam:
    def __init__(self, gagal: bool = False):
        self.pesan: list[tuple[str, dict]] = []
        self.gagal = gagal

    def __call__(self, url, data):
        if self.gagal:
            raise ConnectionError("putus")
        self.pesan.append((url, data))


@pytest.fixture
def rekam(monkeypatch):
    r = Rekam()
    n = notifikasi.Notifier("TOKEN", "123", kirim_http=r, latar=False)
    monkeypatch.setattr(notifikasi, "get_notifier", lambda: n)
    return r


# ---------------------------------------------------------------- notifikasi


def test_notifikasi_anti_spam_dan_paksa(rekam):
    assert notifikasi.kirim("token", "satu")
    assert not notifikasi.kirim("token", "dua")  # jenis sama dalam 1 jam diredam
    assert notifikasi.kirim("lain", "tiga")
    assert notifikasi.kirim("token", "empat", paksa=True)
    assert [d["text"] for _, d in rekam.pesan] == [
        "[Kuis Plurk] satu",
        "[Kuis Plurk] tiga",
        "[Kuis Plurk] empat",
    ]
    assert (
        rekam.pesan[0][0] == "https://api.telegram.org/botTOKEN/sendMessage"
        and rekam.pesan[0][1]["chat_id"] == "123"
    )


def test_notifikasi_nonaktif_dan_error_ditelan(caplog):
    assert not notifikasi.Notifier(None, None).kirim("x", "y")
    n = notifikasi.Notifier("T", "1", kirim_http=Rekam(gagal=True), latar=False)
    assert n.kirim("x", "y")  # tidak melempar error
    assert "notifikasi Telegram gagal: ConnectionError" in caplog.text and "botT" not in caplog.text


def test_token_ditolak_mengirim_notifikasi(engine, rekam):
    from app.plurk.client import TokenDitolak
    from tests.test_engine import Harness, jam

    h = Harness(engine, jam(11, 59))
    h.tick()
    h.fake.gagal = [TokenDitolak("401")]
    h.tick()
    assert any("Token Plurk ditolak" in d["text"] for _, d in rekam.pesan)


def test_watchdog_bot_macet_lalu_pulih(engine, db_path, rekam):
    from app.admin.main import pantau_bot_sekali

    with sesi_db(engine) as db:
        db.get_one(BotState, 1).status = "aktif"
    assert pantau_bot_sekali(None) is False  # belum pernah ada detak
    assert pantau_bot_sekali(False) is False  # tidak mengirim ulang
    with sesi_db(engine) as db:
        db.get_one(BotState, 1).heartbeat_at = SystemClock().now()
    assert pantau_bot_sekali(False) is True
    teks = [d["text"] for _, d in rekam.pesan]
    assert len(teks) == 2 and "tidak mengirim detak" in teks[0] and "kembali normal" in teks[1]


def test_watchdog_diam_saat_bot_berhenti(engine, db_path, rekam):
    from app.admin.main import pantau_bot_sekali

    assert pantau_bot_sekali(None) is True and rekam.pesan == []


# ---------------------------------------------------------------- backup


def test_backup_integritas_dan_pulihkan(engine, db_path, tmp_path):
    with sesi_db(engine) as db:
        db.add(Setting(key="penanda", value={"x": 1}, updated_at=SystemClock().now()))
    now = datetime(2026, 11, 27, 3, 0, tzinfo=WIB)
    hasil = buat_backup(db_path, tmp_path / "backup", now)
    assert hasil.name == "kuis_20261127_030000.db.gz"
    with gzip.open(hasil) as f:
        assert f.read(16) == b"SQLite format 3\x00"
    tujuan = tmp_path / "pulih.db"
    pulihkan(hasil, tujuan)
    con = sqlite3.connect(tujuan)
    assert con.execute("SELECT key FROM settings").fetchone() == ("penanda",)
    con.close()


def test_rotasi_14_hari(tmp_path):
    now = datetime(2026, 11, 27, 3, 0, tzinfo=WIB)
    for hari in (0, 13, 15, 30):
        (tmp_path / f"kuis_{now - timedelta(days=hari):%Y%m%d_%H%M%S}.db.gz").write_bytes(b"x")
    (tmp_path / "catatan.txt").write_text("biarkan")
    dihapus = rotasi(tmp_path, now, 14)
    assert (
        len(dihapus) == 2 and len(list(tmp_path.glob("kuis_*"))) == 2 and (tmp_path / "catatan.txt").exists()
    )


def test_backup_database_tidak_ada(tmp_path):
    with pytest.raises(RuntimeError, match="tidak ditemukan"):
        buat_backup(tmp_path / "tidak_ada.db", tmp_path, datetime(2026, 11, 27, tzinfo=WIB))


def test_pulihkan_backup_rusak(tmp_path):
    rusak = tmp_path / "kuis_rusak.db.gz"
    with gzip.open(rusak, "wb") as f:
        f.write(b"bukan sqlite" * 100)
    with pytest.raises(RuntimeError, match="tidak bisa dipulihkan"):
        pulihkan(rusak, tmp_path / "x.db")
    assert not (tmp_path / "x.db").exists()


def test_cli_backup(engine, db_path, tmp_path, capsys):
    assert cli.main(["backup", "--ke", str(tmp_path / "b")]) == 0
    assert "OK:" in capsys.readouterr().out and len(list((tmp_path / "b").glob("kuis_*.db.gz"))) == 1


def test_cli_uji_notifikasi_tanpa_konfigurasi(capsys):
    notifikasi.get_notifier.cache_clear()
    assert cli.main(["uji-notifikasi"]) == 1
    assert "belum diatur" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        cli.main(["kabari"])
    assert select  # noqa: B018
