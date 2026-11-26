"""CLI: python -m app.cli <perintah>.

  health admin|bot          cek kesehatan kontainer (healthcheck Docker)
  seed --dir DIR            impor semua trivia_NN_*.txt di DIR (+ pemain contoh bila PLURK_MODE=fake)
  buat-admin --username U   buat akun admin / ganti password (--reset)

Perintah tick, simulasi, thread menyusul di tahap 3."""

import argparse
import getpass
import sys
import urllib.request
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import select

from app.bank_soal import impor_topik
from app.bot.tick import sehat
from app.clock import SystemClock
from app.config import get_settings
from app.core.validator import ValidasiGagal
from app.db import get_engine, sesi_db
from app.models import Admin, AdminAudit, Player

# Pemain karangan untuk dev (FakePlurk); ID di luar rentang wajar ID Plurk asli.
PEMAIN_CONTOH = [(900_000_000 + i, f"pemain{i:02d}", f"Pemain Contoh {i}") for i in range(1, 9)]
MIN_PANJANG_PASSWORD = 12


def health(target: str) -> int:
    if target == "admin":
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as r:
                ok = r.status == 200
        except OSError:
            ok = False
    else:
        try:
            ok = sehat(get_engine())
        except Exception:
            ok = False
    print("sehat" if ok else "tidak sehat")
    return 0 if ok else 1


def seed(folder: str, pemain_contoh: bool) -> int:
    now = SystemClock().now()
    files = sorted(Path(folder).glob("*.txt"))
    if not files:
        print(f"Tidak ada file .txt di {folder}")
        return 1
    gagal = 0
    for f in files:
        try:
            with sesi_db() as db:
                lap = impor_topik(db, f.name, f.read_text(encoding="utf-8"), now)
                db.add(
                    AdminAudit(at=now, action="seed_topik", detail={"file": f.name, "topik_id": lap.topik_id})
                )
            print(lap.ringkasan())
        except ValidasiGagal as e:
            gagal += 1
            print(f"DITOLAK {f.name}: {e}")
        except UnicodeDecodeError:
            gagal += 1
            print(f"DITOLAK {f.name}: file harus UTF-8")

    if pemain_contoh:
        with sesi_db() as db:
            ada = set(db.scalars(select(Player.plurk_user_id)))
            baru = [
                Player(plurk_user_id=i, nick=n, display_name=d, first_seen=now)
                for i, n, d in PEMAIN_CONTOH
                if i not in ada
            ]
            db.add_all(baru)
        print(f"Pemain contoh: {len(baru)} dibuat, {len(PEMAIN_CONTOH) - len(baru)} sudah ada")
    return 1 if gagal else 0


def buat_admin(username: str, reset: bool, password_stdin: bool) -> int:
    if password_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Ulangi password: "):
            print("Password tidak sama.")
            return 1
    if len(password) < MIN_PANJANG_PASSWORD:
        print(f"Password minimal {MIN_PANJANG_PASSWORD} karakter.")
        return 1

    now = SystemClock().now()
    hash_ = PasswordHasher().hash(password)
    with sesi_db() as db:
        admin = db.scalar(select(Admin).where(Admin.username == username))
        if admin is None:
            if db.scalar(select(Admin.id).limit(1)) is not None:
                print(
                    "Sudah ada akun admin (proyek ini memakai satu akun). Pakai --reset untuk ganti password."
                )
                return 1
            db.add(Admin(username=username, password_hash=hash_, created_at=now))
            aksi = "admin_dibuat"
        elif reset:
            admin.password_hash = hash_
            aksi = "admin_password_direset"
        else:
            print(f"Admin '{username}' sudah ada. Pakai --reset untuk ganti password.")
            return 1
        db.add(AdminAudit(at=now, action=aksi, detail={"username": username, "lewat": "cli"}))
    print(f"OK: {aksi.replace('_', ' ')} ({username})")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="perintah", required=True)

    p = sub.add_parser("health", help="cek kesehatan kontainer (dipakai healthcheck Docker)")
    p.add_argument("target", choices=["admin", "bot"])

    p = sub.add_parser("seed", help="impor bank soal dari folder lokal")
    p.add_argument("--dir", required=True, help="folder berisi trivia_NN_nama_topik.txt")
    p.add_argument("--tanpa-pemain", action="store_true", help="jangan buat pemain contoh")

    p = sub.add_parser("buat-admin", help="buat akun admin atau ganti password")
    p.add_argument("--username", required=True)
    p.add_argument("--reset", action="store_true", help="ganti password admin yang sudah ada")
    p.add_argument("--password-stdin", action="store_true", help="baca password dari stdin (tanpa prompt)")

    args = ap.parse_args(argv)
    if args.perintah == "health":
        return health(args.target)
    if args.perintah == "seed":
        contoh = not args.tanpa_pemain and get_settings().plurk_mode == "fake"
        return seed(args.dir, contoh)
    if args.perintah == "buat-admin":
        return buat_admin(args.username, args.reset, args.password_stdin)
    return 2


if __name__ == "__main__":
    sys.exit(main())
