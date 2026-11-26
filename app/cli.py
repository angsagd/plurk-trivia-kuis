"""CLI: python -m app.cli <perintah>.

health admin|bot          cek kesehatan kontainer (healthcheck Docker)
seed --dir DIR            impor semua trivia_NN_*.txt di DIR (+ pemain contoh bila PLURK_MODE=fake)
buat-admin --username U   buat akun admin / ganti password (--reset)
status aktif|jeda|berhenti|hentikan   ubah status bot (hentikan = semua thread langsung die)
tick --now "2026-11-30T12:00"         jalankan satu tick pada jam tertentu (khusus PLURK_MODE=fake)
simulasi --pemain 8 --benar 0.3       pemain tiruan membalas thread FakePlurk (Ctrl-C untuk berhenti)
thread [--sesi ID]                    tampilkan isi thread FakePlurk (default: sesi terbaru)"""

import argparse
import getpass
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

from argon2 import PasswordHasher
from sqlalchemy import select

from app.bank_soal import impor_topik
from app.bot import engine as mesin
from app.bot.outbox import Pengirim
from app.bot.pengaturan import muat_pengaturan
from app.bot.simulator import PemainSim, putaran
from app.bot.tick import jalankan_tick, sehat
from app.clock import FakeClock, SystemClock, ke_wib
from app.config import get_settings
from app.core.validator import ValidasiGagal
from app.db import get_engine, sesi_db
from app.models import Admin, AdminAudit, BotState, GameSession, Player
from app.plurk import buat_plurk
from app.plurk.fake import FakePlurk

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


def _fake(clock) -> FakePlurk:
    settings = get_settings()
    if settings.plurk_mode != "fake":
        raise SystemExit("Perintah ini hanya untuk PLURK_MODE=fake.")
    plurk = buat_plurk(settings, clock)
    assert isinstance(plurk, FakePlurk)
    return plurk


def status(nilai: str) -> int:
    now = SystemClock().now()
    with sesi_db() as db:
        st = db.get_one(BotState, 1)
        if nilai == "hentikan":
            plurk = buat_plurk(get_settings(), SystemClock())
            p = muat_pengaturan(db)
            pengirim = Pengirim(
                plurk, SystemClock(), maks_per_tick=0, jeda_detik=0, maks_gagal=5, tidur=time.sleep
            )
            k = mesin.Konteks(
                db, plurk, pengirim, p, st.last_tick_at or now, plurk.whoami().id, random.Random()
            )
            n = mesin.hentikan_sekarang(k)
            print(f"{n} thread dihentikan; ranking/farewell dikirim pada tick berikutnya.")
        else:
            st.status = nilai
        db.add(AdminAudit(at=now, action=f"bot_{nilai}", detail={"lewat": "cli"}))
    print(f"Status bot: {'berhenti' if nilai == 'hentikan' else nilai}")
    return 0


def tick_manual(waktu: str) -> int:
    now = ke_wib(datetime.fromisoformat(waktu)).replace(second=0, microsecond=0)
    clock = FakeClock(now)
    jalankan_tick(now, get_engine(), _fake(clock), clock=clock, tidur=lambda _: None)
    return thread(None)


def simulasi(jumlah: int, benar: float, balas: float, jeda: float, sekali: bool, seed: int | None) -> int:
    rng = random.Random(seed)
    with sesi_db() as db:
        pemain = [PemainSim(p.plurk_user_id, p.nick) for p in db.scalars(select(Player).limit(jumlah))]
    if not pemain:
        print("Belum ada pemain. Jalankan `seed` dulu (membuat pemain contoh di mode fake).")
        return 1
    terakhir = None
    while True:
        with sesi_db() as db:
            tick_at = db.get_one(BotState, 1).last_tick_at
            if tick_at is not None and tick_at != terakhir:
                terakhir = tick_at
                time.sleep(min(jeda, 2.0))  # beri waktu bot menyelesaikan posting tick ini
                waktu = tick_at + timedelta(seconds=30)
                fake = _fake(FakeClock(waktu))
                n = putaran(db, fake, pemain, rng, benar=benar, balas=balas, waktu=waktu)
                fake.tutup()
                if n:
                    print(f"{waktu:%H:%M:%S} {n} balasan")
        if sekali:
            return 0
        time.sleep(jeda)


def thread(sesi_id: int | None) -> int:
    with sesi_db() as db:
        q = select(GameSession).order_by(GameSession.id.desc())
        sesi = db.get(GameSession, sesi_id) if sesi_id else db.scalars(q).first()
        if sesi is None or sesi.plurk_id is None:
            print("Belum ada thread.")
            return 1
        fake = _fake(SystemClock())
        isi = fake.plurk(sesi.plurk_id)
        print(
            f"== Sesi {sesi.id} · {sesi.play_date} slot {sesi.slot} · {sesi.status}/{sesi.step} · "
            f"soal {sesi.question_count} · plurk {sesi.plurk_id}"
        )
        if isi:
            print(f"[{isi[1][11:16]}] kuisbot: {isi[0]}")
        for r in fake.semua_balasan(sesi.plurk_id):
            print(f"[{r.posted:%H:%M:%S}] {r.nick}: {r.content}")
        fake.tutup()
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

    p = sub.add_parser("status", help="ubah status bot")
    p.add_argument("nilai", choices=["aktif", "jeda", "berhenti", "hentikan"])

    p = sub.add_parser("tick", help="jalankan satu tick (PLURK_MODE=fake)")
    p.add_argument("--now", required=True, help='jam WIB, mis. "2026-11-30T12:00"')

    p = sub.add_parser("simulasi", help="pemain tiruan membalas thread FakePlurk")
    p.add_argument("--pemain", type=int, default=8)
    p.add_argument("--benar", type=float, default=0.3, help="peluang jawaban benar (0-1)")
    p.add_argument("--balas", type=float, default=0.5, help="peluang tiap pemain membalas per tick (0-1)")
    p.add_argument("--jeda", type=float, default=1.0, help="detik antar pengecekan tick baru")
    p.add_argument("--sekali", action="store_true", help="satu putaran saja")
    p.add_argument("--seed", type=int)

    p = sub.add_parser("thread", help="tampilkan isi thread FakePlurk")
    p.add_argument("--sesi", type=int)

    args = ap.parse_args(argv)
    if args.perintah == "health":
        return health(args.target)
    if args.perintah == "seed":
        contoh = not args.tanpa_pemain and get_settings().plurk_mode == "fake"
        return seed(args.dir, contoh)
    if args.perintah == "buat-admin":
        return buat_admin(args.username, args.reset, args.password_stdin)
    if args.perintah == "status":
        return status(args.nilai)
    if args.perintah == "tick":
        return tick_manual(args.now)
    if args.perintah == "simulasi":
        return simulasi(args.pemain, args.benar, args.balas, args.jeda, args.sekali, args.seed)
    if args.perintah == "thread":
        return thread(args.sesi)
    return 2


if __name__ == "__main__":
    sys.exit(main())
