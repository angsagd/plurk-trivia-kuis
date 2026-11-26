"""Backup SQLite lewat backup API (aman walau bot sedang menulis), cek integritas, gzip, rotasi."""

import gzip
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

POLA = "kuis_*.db.gz"


def buat_backup(db_path: Path, folder: Path, now: datetime, simpan_hari: int = 14) -> Path:
    """Tulis <folder>/kuis_YYYYmmdd_HHMMSS.db.gz lalu hapus backup lebih tua dari `simpan_hari`.
    RuntimeError bila database sumber tidak ada atau hasil backup gagal cek integritas."""
    if not db_path.exists():
        raise RuntimeError(f"database tidak ditemukan: {db_path}")
    folder.mkdir(parents=True, exist_ok=True)
    nama = f"kuis_{now:%Y%m%d_%H%M%S}"
    mentah = folder / f".{nama}.db.tmp"
    try:
        src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        dst = sqlite3.connect(mentah)
        with dst:
            src.backup(dst)
        cek = dst.execute("PRAGMA integrity_check").fetchone()[0]
        dst.close()
        src.close()
        if cek != "ok":
            raise RuntimeError(f"integrity_check backup gagal: {cek}")
        hasil = folder / f"{nama}.db.gz"
        with mentah.open("rb") as f_in, gzip.open(hasil, "wb", compresslevel=6) as f_out:
            shutil.copyfileobj(f_in, f_out)
    finally:
        mentah.unlink(missing_ok=True)
    rotasi(folder, now, simpan_hari)
    return hasil


def rotasi(folder: Path, now: datetime, simpan_hari: int) -> list[Path]:
    batas = now - timedelta(days=simpan_hari)
    dihapus = []
    for f in folder.glob(POLA):
        try:
            waktu = datetime.strptime(f.name[5:20], "%Y%m%d_%H%M%S").replace(tzinfo=now.tzinfo)
        except ValueError:
            continue
        if waktu < batas:
            f.unlink()
            dihapus.append(f)
    return dihapus


def pulihkan(backup: Path, tujuan: Path) -> None:
    """Ekstrak backup .db.gz ke `tujuan`. Hentikan bot & admin dulu bila menimpa database aktif."""
    tmp = tujuan.with_suffix(".pulih.tmp")
    try:
        with gzip.open(backup, "rb") as f_in, tmp.open("wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
        con = sqlite3.connect(tmp)
        try:
            cek = con.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            con.close()
        if cek != "ok":
            raise RuntimeError(f"backup rusak: {cek}")
    except (OSError, sqlite3.DatabaseError) as e:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"backup tidak bisa dipulihkan: {e}") from e
    except RuntimeError:
        tmp.unlink(missing_ok=True)
        raise
    for akhiran in ("-wal", "-shm"):
        Path(str(tujuan) + akhiran).unlink(missing_ok=True)
    tmp.replace(tujuan)
