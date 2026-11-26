"""Tes tahap 2: migrasi, tipe waktu WIB, impor bank soal, CLI seed & buat-admin."""

import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from argon2 import PasswordHasher
from sqlalchemy import func, select

from app import cli
from app.bank_soal import impor_topik
from app.clock import WIB
from app.core.validator import ValidasiGagal
from app.db import Base, sesi_db
from app.models import Admin, AdminAudit, BotState, Player, Question, Setting, Topic

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 26, 10, 0, tzinfo=WIB)

# Bank soal karangan untuk tes (bukan dari private/).
SOAL_A = """# topik karangan
Ibu kota negara Jepang?|Dahulu bernama Edo|TOKYO
Planet terbesar di tata surya?|Punya Bintik Merah Raksasa|JUPITER
Alat musik bambu dari Jawa Barat?|Dimainkan dengan digoyang|ANGKLUNG
Burung lambang negara Indonesia?|Mencengkeram pita semboyan|GARUDA
"""


def test_migrasi_sama_dengan_model(engine):
    with engine.connect() as conn:
        beda = compare_metadata(MigrationContext.configure(conn, opts={"compare_type": True}), Base.metadata)
    assert beda == []


def test_bot_state_satu_baris_dan_wal(engine):
    with sesi_db(engine) as db:
        st = db.scalars(select(BotState)).all()
        assert len(st) == 1 and st[0].id == 1 and st[0].status == "berhenti"
        assert db.connection().exec_driver_sql("PRAGMA journal_mode").scalar() == "wal"
        assert db.connection().exec_driver_sql("PRAGMA foreign_keys").scalar() == 1


def test_waktu_wib_disimpan_dan_dibaca_berzona(engine):
    with sesi_db(engine) as db:
        db.add(Setting(key="x", value={"a": 1}, updated_at=datetime(2026, 11, 26, 3, 0, tzinfo=UTC)))
    with sesi_db(engine) as db:
        s = db.get_one(Setting, "x")
        assert s.updated_at == datetime(2026, 11, 26, 10, 0, tzinfo=WIB) and s.updated_at.tzinfo is WIB
        assert db.connection().exec_driver_sql("SELECT updated_at FROM settings").scalar() == (
            "2026-11-26T10:00:00.000000+07:00"
        )


def test_waktu_tanpa_zona_ditolak(engine):
    with pytest.raises(Exception, match="tanpa zona"), sesi_db(engine) as db:
        db.add(Setting(key="y", value=1, updated_at=datetime(2026, 11, 26, 10, 0)))


def jumlah(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def test_impor_topik_baru_nama_dari_file(engine):
    with sesi_db(engine) as db:
        lap = impor_topik(db, "trivia_04_sejarah_dunia.txt", SOAL_A, NOW)
    assert (lap.nomor, lap.nama, lap.topik_baru, lap.soal_baru) == ("04", "Sejarah Dunia", True, 4)
    with sesi_db(engine) as db:
        t = db.scalar(select(Topic))
        assert (t.number, t.name, t.name_key, t.cycle) == ("04", "Sejarah Dunia", "sejarah dunia", 1)
        q = db.scalar(select(Question).where(Question.jawaban == "JUPITER"))
        assert q.letters == 7 and q.used_cycle == 0 and q.is_active


def test_impor_ulang_tidak_menggandakan_dan_riwayat_tetap(engine):
    with sesi_db(engine) as db:
        impor_topik(db, "trivia_04_sejarah_dunia.txt", SOAL_A, NOW)
        db.scalar(select(Question).where(Question.jawaban == "TOKYO")).used_cycle = 1
    ubah = (
        SOAL_A.replace("Dahulu bernama Edo", "Kota terpadat di dunia").replace(
            "Burung lambang negara Indonesia?|Mencengkeram pita semboyan|GARUDA\n", ""
        )
        + "Candi Buddha terbesar di Magelang?|Dinasti Syailendra|BOROBUDUR\n"
    )
    with sesi_db(engine) as db:
        lap = impor_topik(db, "trivia_04_Sejarah_Dunia.txt", ubah, NOW)
    assert (lap.topik_baru, lap.soal_baru, lap.diperbarui, lap.tetap, lap.dinonaktifkan) == (
        False,
        1,
        1,
        2,
        1,
    )
    with sesi_db(engine) as db:
        assert jumlah(db, Topic) == 1 and jumlah(db, Question) == 5
        tokyo = db.scalar(select(Question).where(Question.jawaban == "TOKYO"))
        assert tokyo.clue == "Kota terpadat di dunia" and tokyo.used_cycle == 1
        assert not db.scalar(select(Question).where(Question.jawaban == "GARUDA")).is_active
    with sesi_db(engine) as db:  # impor persis sama: tidak ada perubahan
        lap = impor_topik(db, "trivia_04_sejarah_dunia.txt", ubah, NOW)
    assert (lap.soal_baru, lap.diperbarui, lap.dinonaktifkan, lap.tetap) == (0, 0, 0, 4)


def test_impor_lewati_baris_error_dan_duplikat(engine):
    teks = SOAL_A + "Soal rusak tanpa kolom\nIbu kota negara Jepang?|Clue lain|TOKYO\n"
    with sesi_db(engine) as db:
        lap = impor_topik(db, "trivia_01_campuran.txt", teks, NOW)
        assert lap.validasi.baris_error == 1 and lap.duplikat_di_file == 1 and lap.soal_baru == 4


@pytest.mark.parametrize("nama", ["musik.txt", "trivia_4_musik.txt", "trivia_04_musik.txt"])
def test_impor_ditolak(engine, nama):
    with sesi_db(engine) as db:
        impor_topik(db, "trivia_04_sejarah_dunia.txt", SOAL_A, NOW)
    with pytest.raises(ValidasiGagal), sesi_db(engine) as db:
        impor_topik(db, nama, SOAL_A, NOW)


def test_impor_topik_baru_mirip_topik_lain(engine):
    with sesi_db(engine) as db:
        impor_topik(db, "trivia_02_sejarah_indonesia.txt", SOAL_A, NOW)
    with sesi_db(engine) as db:
        lap = impor_topik(db, "trivia_03_sejarah_nusantara.txt", SOAL_A, NOW)
        assert lap.topik_baru and lap.mirip_dengan == "Sejarah Indonesia"
        assert "PERINGATAN" in lap.ringkasan()


def test_cli_seed_contoh_dan_ulang(db_path, engine, monkeypatch, capsys):
    monkeypatch.setenv("PLURK_MODE", "fake")
    assert cli.main(["seed", "--dir", str(ROOT / "contoh")]) == 0
    assert cli.main(["seed", "--dir", str(ROOT / "contoh")]) == 0
    out = capsys.readouterr().out
    assert "[99] Contoh (topik baru)" in out and "[99] Contoh (diperbarui)" in out
    with sesi_db(engine) as db:
        assert jumlah(db, Topic) == 1 and jumlah(db, Question) == 8
        assert jumlah(db, Player) == len(cli.PEMAIN_CONTOH)
        assert jumlah(db, AdminAudit, AdminAudit.action == "seed_topik") == 2


def test_cli_seed_file_salah_nama(db_path, tmp_path, capsys):
    (tmp_path / "bank").mkdir()
    (tmp_path / "bank" / "musik.txt").write_text(SOAL_A, encoding="utf-8")
    assert cli.main(["seed", "--dir", str(tmp_path / "bank")]) == 1
    assert "DITOLAK musik.txt" in capsys.readouterr().out


def test_cli_buat_admin(db_path, engine, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("password-yang-panjang\n"))
    assert cli.main(["buat-admin", "--username", "admin", "--password-stdin"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("pendek\n"))
    assert cli.main(["buat-admin", "--username", "admin", "--reset", "--password-stdin"]) == 1
    monkeypatch.setattr("sys.stdin", io.StringIO("password-lain-yang-panjang\n"))
    assert cli.main(["buat-admin", "--username", "lain", "--password-stdin"]) == 1  # hanya satu akun
    monkeypatch.setattr("sys.stdin", io.StringIO("password-baru-yang-panjang\n"))
    assert cli.main(["buat-admin", "--username", "admin", "--reset", "--password-stdin"]) == 0
    with sesi_db(engine) as db:
        a = db.scalar(select(Admin))
        assert PasswordHasher().verify(a.password_hash, "password-baru-yang-panjang")
        assert "password" not in str(db.scalars(select(AdminAudit.detail)).all())
