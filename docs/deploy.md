# Deploy produksi (VPS + Traefik)

Panduan langkah demi langkah. Semua perintah dijalankan di VPS dari folder repo
(mis. `/opt/plurk-trivia-kuis`). Singkatan yang dipakai di bawah:

```bash
alias kuis='docker compose -f compose.yml -f compose.prod.yml'
```

Repo ini publik: **`.env`, bank soal, dan database tidak pernah ada di Git**. `.env` dibuat langsung di VPS;
bank soal diunggah lewat halaman admin.

## 0. Cek VPS (sekali)

| Cek | Perintah | Catat untuk `.env` |
| --- | --- | --- |
| Arsitektur CPU | `uname -m` | (image selalu di-build di VPS) |
| Docker Compose v2 | `docker compose version` | |
| Mode network Traefik | `docker inspect <container-traefik> --format '{{.HostConfig.NetworkMode}}'` | `host` → tidak perlu apa-apa; network bersama → `TRAEFIK_NETWORK` + `-f compose.traefik-net.yml` |
| Entrypoint HTTPS | konfigurasi Traefik (`--entrypoints.<nama>.address=:443`) | `TRAEFIK_ENTRYPOINT` |
| Certresolver | konfigurasi Traefik (`--certificatesresolvers.<nama>...`) | `TRAEFIK_CERTRESOLVER` |
| Jam server (NTP) | `timedatectl` → `System clock synchronized: yes` | jadwal bergantung pada menit yang tepat; zona waktu server boleh apa saja (aplikasi memakai WIB), tapi jam cron mengikuti zona server |
| DNS | record A subdomain admin → IP VPS | `ADMIN_HOST` |

## 1. Pemasangan pertama

```bash
git clone https://github.com/angsagd/plurk-trivia-kuis.git ~/plurk-trivia-kuis   # user dengan grup docker; tidak perlu sudo
cd ~/plurk-trivia-kuis
cp .env.example .env && chmod 600 .env
```

Isi `.env`:

- `PLURK_MODE=real` dan empat kredensial Plurk (token permanen dari https://www.plurk.com/OAuth/test).
- `APP_SECRET_KEY`: `openssl rand -hex 32`.
- `DB_PATH=/app/data/kuis.db`, `FAKE_NOW=` kosong, `TICK_SECONDS=60`, `COOKIE_SECURE=true`.
- `ADMIN_HOST`, `TRAEFIK_ENTRYPOINT`, `TRAEFIK_CERTRESOLVER` dari langkah 0 (`TRAEFIK_NETWORK` hanya bila Traefik di network bersama).
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (opsional, sangat disarankan).

```bash
kuis build
kuis run --rm --no-deps bot alembic upgrade head
kuis run --rm --no-deps bot python -m app.cli cek-plurk          # OK: token valid untuk akun ...
kuis run --rm --no-deps bot python -m app.cli uji-notifikasi     # pesan uji ke Telegram
kuis run --rm --no-deps bot python -m app.cli buat-admin --username admin --totp
kuis up -d
kuis ps                                                          # admin & bot "healthy" (bot ±2 menit)
```

Bot mulai dengan status **berhenti**. Lalu, lewat `https://<ADMIN_HOST>`:

1. Bank soal → unggah semua `trivia_NN_*.txt` dari laptop.
2. Kontrol & pengaturan → isi ID akun Plurk admin, aktifkan **Mode uji**, "Kirim plurk uji (privat)".
3. Jalankan bot; ikuti satu sesi penuh di akun uji. Setelah yakin, matikan mode uji.

## 2. Backup harian

```bash
crontab -e
# 03.30 WIB setiap hari. Jam cron mengikuti zona waktu server (`date`): WITA -> 04.30, UTC -> 20.30.
30 3 * * * cd ~/plurk-trivia-kuis && BACKUP_DIR=$HOME/backups/plurk-trivia-kuis BACKUP_RCLONE="remote:kuis-backup/db" scripts/backup.sh >> $HOME/backups/kuis-backup.log 2>&1
```

- Backup disimpan di `BACKUP_DIR` (bawaan `/var/backups/plurk-trivia-kuis`; tanpa root pakai `$HOME/backups/...`) selama 14 hari dan **disalin ke luar VPS** lewat
  `BACKUP_RCLONE` (rclone, mis. Backblaze B2 / Google Drive) atau `BACKUP_RSYNC` (`user@host:/path/`).
- Backup gagal (database / offsite) → notifikasi Telegram.
- Uji pemulihan sebulan sekali di laptop: salin satu `kuis_*.db.gz`, lalu
  `docker compose run --rm -v "$PWD/cadangan:/cadangan" bot python -m app.cli pulihkan /cadangan/kuis_....db.gz --ke /app/data/pulih.db`.

## 3. Update

Di luar jam sesi (sebelum 11.00 / setelah 23.00 WIB) atau di hari libur:

```bash
cd ~/plurk-trivia-kuis && scripts/update.sh
```

Skrip ini: `git pull --ff-only` → backup → build → `alembic upgrade head` → `up -d` → `ps`.
Di jam sesi hari aktif ia menolak kecuali `--paksa`.

## 4. Pemulihan database

```bash
kuis stop bot admin
kuis run --rm --no-deps -v /var/backups/plurk-trivia-kuis:/backup bot \
  python -m app.cli pulihkan /backup/kuis_YYYYmmdd_HHMMSS.db.gz
kuis up -d
```

## 5. Operasional

| Hal | Cara |
| --- | --- |
| Status | Dashboard admin (tick terakhir, thread, peringatan) · `kuis ps` |
| Log | `kuis logs -f bot` / `kuis logs -f admin` (dibatasi 3 × 10 MB) |
| Notifikasi | Telegram: token Plurk ditolak, posting gagal 5×, error tick/thread, stok soal habis, backup gagal, **bot macet > 3 menit** (dipantau kontainer admin) |
| Hentikan kuis | Dashboard → "Hentikan sekarang", atau `kuis run --rm --no-deps bot python -m app.cli status hentikan` |
| Token Plurk ditolak | Bot otomatis `berhenti`. Perbarui token di `.env`, `kuis up -d`, cek `cek-plurk`, lalu Jalankan dari dashboard |

## 6. Keamanan

- Hanya kontainer admin yang bergabung ke network Traefik; tidak ada `ports:` di produksi.
- Kontainer berjalan sebagai user non-root dengan root filesystem read-only, `no-new-privileges`, tanpa capability.
- Admin: argon2 + TOTP, cookie `Secure/HttpOnly/SameSite=Strict`, CSRF, 5 login gagal → blokir 15 menit.
- Ingin membatasi akses admin ke IP tertentu? Tambahkan middleware Traefik `ipAllowList` lewat label di
  file override lokal VPS (jangan commit domain/IP ke repo publik).
- Jika rahasia terlanjur ter-commit: **rotasi** rahasianya (Plurk, `APP_SECRET_KEY`, Telegram); menghapus file tidak cukup.
