"""CLI: python -m app.cli <perintah>.

health admin|bot          cek kesehatan kontainer (healthcheck Docker)
seed --dir DIR            impor semua trivia_NN_*.txt di DIR (+ pemain contoh bila PLURK_MODE=fake)
buat-admin --username U   buat akun admin / ganti password (--reset)
status aktif|jeda|berhenti|hentikan   ubah status bot (hentikan = semua thread langsung die)
tick --now "2026-11-30T12:00"         jalankan satu tick pada jam tertentu (khusus PLURK_MODE=fake)
simulasi --pemain 8 --benar 0.3       pemain tiruan membalas thread FakePlurk (Ctrl-C untuk berhenti)
thread [--sesi ID]                    tampilkan isi thread FakePlurk (default: sesi terbaru)
cek-plurk                             cek kredensial Plurk asli (/APP/Users/me); tidak memposting apa pun
backup --ke DIR [--simpan 14]         backup database (gzip, cek integritas) + hapus backup lama
pulihkan FILE [--ke DB]               pulihkan backup .db.gz (hentikan bot & admin dulu!)
uji-notifikasi                        kirim pesan uji ke Telegram
kabari "teks"                         kirim notifikasi (dipakai skrip host, mis. backup offsite gagal)
uji-plurk --untuk ID                  tahap 4: uji Plurk API asli lewat SATU plurk privat (memposting!)"""

import argparse
import getpass
import random
import sys
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

import pyotp
from argon2 import PasswordHasher
from sqlalchemy import select

from app.bank_soal import impor_topik
from app.bot.simulator import PemainSim, putaran
from app.bot.tick import jalankan_tick, sehat
from app.clock import FakeClock, SystemClock, ke_wib
from app.config import get_settings
from app.core.validator import ValidasiGagal
from app.db import get_engine, sesi_db
from app.models import Admin, AdminAudit, BotState, GameSession, Player
from app.plurk import buat_plurk
from app.plurk.client import PlurkError
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


def buat_admin(username: str, reset: bool, password_stdin: bool, totp: bool = False) -> int:
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
    rahasia_totp = pyotp.random_base32() if totp else None
    with sesi_db() as db:
        admin = db.scalar(select(Admin).where(Admin.username == username))
        if admin is None:
            if db.scalar(select(Admin.id).limit(1)) is not None:
                print(
                    "Sudah ada akun admin (proyek ini memakai satu akun). Pakai --reset untuk ganti password."
                )
                return 1
            db.add(Admin(username=username, password_hash=hash_, totp_secret=rahasia_totp, created_at=now))
            aksi = "admin_dibuat"
        elif reset:
            admin.password_hash = hash_
            if totp:
                admin.totp_secret = rahasia_totp
            aksi = "admin_password_direset"
        else:
            print(f"Admin '{username}' sudah ada. Pakai --reset untuk ganti password.")
            return 1
        db.add(AdminAudit(at=now, action=aksi, detail={"username": username, "lewat": "cli"}))
    print(f"OK: {aksi.replace('_', ' ')} ({username})")
    if rahasia_totp:
        uri = pyotp.TOTP(rahasia_totp).provisioning_uri(name=username, issuer_name="Plurk Trivia Kuis")
        print("TOTP aktif. Masukkan ke aplikasi authenticator (simpan di tempat aman):")
        print(uri)
    return 0


def _fake(clock) -> FakePlurk:
    settings = get_settings()
    if settings.plurk_mode != "fake":
        raise SystemExit("Perintah ini hanya untuk PLURK_MODE=fake.")
    plurk = buat_plurk(settings, clock)
    assert isinstance(plurk, FakePlurk)
    return plurk


def status(nilai: str) -> int:
    """'hentikan' adalah permintaan: tick berikutnya mematikan semua thread (langkah 11), lalu berhenti."""
    now = SystemClock().now()
    with sesi_db() as db:
        db.get_one(BotState, 1).status = nilai
        db.add(AdminAudit(at=now, action=f"bot_{nilai}", detail={"lewat": "cli"}))
    print(f"Status bot: {nilai}")
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


def cek_plurk() -> int:
    """Pakai kredensial di .env walau PLURK_MODE=fake; hanya membaca akun bot."""
    from app.plurk.client import PlurkError
    from app.plurk.real import RealPlurk

    try:
        saya = RealPlurk(get_settings()).whoami()
    except (ValueError, PlurkError) as e:
        print(f"GAGAL: {e}")
        return 1
    print(f"OK: token valid untuk akun {saya.nick} (id {saya.id})")
    return 0


def backup(ke: str, simpan: int) -> int:
    from app.backup import buat_backup

    try:
        hasil = buat_backup(get_settings().db_path, Path(ke), SystemClock().now(), simpan)
    except Exception as e:
        print(f"GAGAL: {e}")
        from app import notifikasi

        notifikasi.get_notifier()._latar = False
        notifikasi.kirim("backup_gagal", f"Backup database gagal: {e}")
        return 1
    print(f"OK: {hasil} ({hasil.stat().st_size // 1024} KB)")
    return 0


def pulihkan(file: str, ke: str | None) -> int:
    from app.backup import pulihkan as _pulihkan

    tujuan = Path(ke) if ke else get_settings().db_path
    try:
        _pulihkan(Path(file), tujuan)
    except Exception as e:
        print(f"GAGAL: {e}")
        return 1
    print(f"OK: {file} dipulihkan ke {tujuan}")
    return 0


def uji_notifikasi() -> int:
    from app import notifikasi

    n = notifikasi.get_notifier()
    if not n.aktif:
        print("Telegram belum diatur: isi TELEGRAM_BOT_TOKEN dan TELEGRAM_CHAT_ID di .env")
        return 1
    n._latar = False
    n.kirim("uji", "Pesan uji notifikasi. Jika ini sampai, notifikasi berfungsi.", paksa=True)
    print("Pesan uji dikirim (cek Telegram; kegagalan dicatat di log).")
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
    p.add_argument("--totp", action="store_true", help="aktifkan TOTP (kode 6 digit) untuk login admin")

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

    sub.add_parser("cek-plurk", help="cek kredensial Plurk asli (tanpa memposting)")

    p = sub.add_parser("backup", help="backup database ke folder")
    p.add_argument("--ke", required=True, help="folder tujuan, mis. /backup")
    p.add_argument("--simpan", type=int, default=14, help="hapus backup lebih tua dari N hari (default 14)")

    p = sub.add_parser("pulihkan", help="pulihkan backup .db.gz")
    p.add_argument("file")
    p.add_argument("--ke", help="file database tujuan (default DB_PATH)")

    sub.add_parser("uji-notifikasi", help="kirim pesan uji ke Telegram")
    p = sub.add_parser("uji-plurk", help="uji Plurk API asli lewat satu plurk privat (memposting)")
    p.add_argument("--untuk", required=True, help="ID akun Plurk yang boleh melihat plurk uji, pisahkan koma")
    p.add_argument("--jeda", type=float, default=3.0, help="detik antar posting (default 3)")

    p = sub.add_parser("kabari", help="kirim notifikasi ke Telegram")
    p.add_argument("teks")

    args = ap.parse_args(argv)
    if args.perintah == "health":
        return health(args.target)
    if args.perintah == "seed":
        contoh = not args.tanpa_pemain and get_settings().plurk_mode == "fake"
        return seed(args.dir, contoh)
    if args.perintah == "buat-admin":
        return buat_admin(args.username, args.reset, args.password_stdin, args.totp)
    if args.perintah == "status":
        return status(args.nilai)
    if args.perintah == "tick":
        return tick_manual(args.now)
    if args.perintah == "simulasi":
        return simulasi(args.pemain, args.benar, args.balas, args.jeda, args.sekali, args.seed)
    if args.perintah == "thread":
        return thread(args.sesi)
    if args.perintah == "cek-plurk":
        return cek_plurk()
    if args.perintah == "backup":
        return backup(args.ke, args.simpan)
    if args.perintah == "pulihkan":
        return pulihkan(args.file, args.ke)
    if args.perintah == "uji-notifikasi":
        return uji_notifikasi()
    if args.perintah == "uji-plurk":
        from app.plurk.real import RealPlurk
        from app.plurk.uji import jalankan

        try:
            untuk = [int(x) for x in args.untuk.replace(" ", "").split(",") if x]
            jalankan(RealPlurk(get_settings()), untuk, args.jeda)
        except (ValueError, PlurkError) as e:
            print(f"GAGAL: {e}")
            return 1
        return 0
    if args.perintah == "kabari":
        from app import notifikasi

        notifikasi.get_notifier()._latar = False
        return 0 if notifikasi.kirim("skrip", args.teks[:1000], paksa=True) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
