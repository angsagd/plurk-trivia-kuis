# Plurk Trivia Kuis

Repo `plurk-trivia-kuis`: bot kuis trivia otomatis di Plurk beserta halaman admin web.
Bahasa proyek: Indonesia. Satu admin (pemilik proyek).

- Blueprint implementasi (rincian lengkap, diagram, skema, tes): https://claude.ai/artifact/LbrY41ksyrrKeoNcadVFXm
- Mockup admin: https://claude.ai/artifact/8v4NLgEWVzQ3LXmdipdEN5 (sumber di `docs/mockup/`, hanya referensi tata letak)

Status: desain selesai (25 Nov 2026; mekanik thread hold/active/die diperbarui 26 Nov 2026). **Tahap 0–6 dan 8 selesai (27 Nov 2026)**; berikutnya tahap 7 (uji coba 1–2 hari, lalu go-live). Produksi sudah terpasang di VPS dan memakai akun Plurk produksi **indotrivia** (sejak 27 Nov 2026; uji coba tahap 7 dengan mode uji privat); detail host/akses hanya di catatan lokal `private/laporan/deploy_vps.md` (repo publik). Ikuti urutan di bagian "Tahapan".

---

## Aturan kerja untuk Claude Code

- Aturan permainan ditulis sebagai **fungsi murni di `app/core/`** (tanpa database, jaringan, atau jam). Bot dan admin memakai fungsi yang sama.
- Setiap aturan di dokumen ini wajib punya tes di `tests/`. Jalankan tes sebelum menyatakan pekerjaan selesai: `docker compose run --rm bot pytest`.
- Bot **tidak pernah** memanggil Plurk langsung; selalu lewat `PlurkClient` (`RealPlurk` / `FakePlurk`). Waktu selalu lewat `Clock` (`SystemClock` / `FakeClock`), tidak memanggil `datetime.now()` langsung.
- Semua waktu dihitung dalam **WIB (`Asia/Jakarta`)**, apa pun zona waktu server atau laptop.
- Jangan pernah menaruh token akun bot asli di `.env.dev`, di kode, atau di Git.
- Perubahan skema database selalu lewat migrasi Alembic.
- Repo ini **publik**: patuhi bagian "Repo publik" di bawah.
- Bila ada keputusan baru dari pemilik proyek, perbarui dokumen ini.
- **Commit tanpa trailer `Co-Authored-By: Claude …`** (keputusan 27 Nov 2026: Claude tidak boleh tercantum sebagai contributor repo). Pesan PR juga tanpa atribusi Claude.

## Repo publik: yang TIDAK boleh di-commit

Repo ini publik. Kredensial dan bank soal hanya ada di laptop dev dan VPS produksi.

| Jangan di-commit | Disimpan di | Dijaga oleh |
| --- | --- | --- |
| `.env`, `.env.dev` (token Plurk, secret aplikasi, password, token Telegram, domain admin) | Laptop dev / VPS | `.gitignore` (`.env`, `.env.*`, kecuali `.env.example`) |
| Bank soal asli (`*.txt` per topik) | `private/bank_soal/` di laptop; di produksi diunggah lewat admin → tersimpan di database | `.gitignore` (`private/`) |
| Laporan review bank soal, catatan perubahan | `private/laporan/` | `.gitignore` (`private/`) |
| Database SQLite & backup (berisi soal, skor, nama pemain) | Volume Docker `data`, folder backup di luar repo | `.gitignore` (`data/`, `backups/`, `*.db`) |

Aturan:
- `.gitignore` dan `.dockerignore` sudah disiapkan; pastikan ada **sebelum commit pertama**.
- Contoh di kode, tes, dokumen, dan mockup hanya memakai soal karangan dari `contoh/trivia_99_contoh.txt` atau fixture tes buatan sendiri — **jangan pernah menyalin soal dari `private/`**.
- `.env.example` hanya berisi nama variabel dan nilai contoh, tanpa nilai asli.
- Domain admin, network Traefik, dan certresolver dibaca dari `.env` (`${ADMIN_HOST}` dll.), tidak ditulis di `compose.prod.yml`.
- Image Docker tidak membawa `private/` maupun `.env` (lihat `.dockerignore`); soal masuk ke produksi hanya lewat unggahan admin.
- Aktifkan *secret scanning* dan *push protection* GitHub. Jika rahasia terlanjur ter-commit: ganti (rotasi) rahasianya; menghapus file saja tidak cukup karena masih ada di riwayat Git.

## Tech stack

| Kebutuhan | Pilihan |
| --- | --- |
| Bahasa | Python 3.12 |
| Admin web | FastAPI + Jinja2 + HTMX, dijalankan uvicorn |
| Database | SQLite mode WAL, satu file di volume Docker |
| ORM / migrasi | SQLAlchemy 2 / Alembic |
| OAuth Plurk | requests + requests-oauthlib (OAuth 1.0a HMAC-SHA1) |
| Konfigurasi | pydantic-settings (`.env`) |
| Login admin | argon2-cffi, opsional pyotp (TOTP) |
| Zona waktu | `zoneinfo` + paket `tzdata` |
| Tes / lint | pytest / ruff |
| Notifikasi (opsional) | Telegram Bot API |

## Arsitektur & infrastruktur

- Satu image Docker (`plurk-trivia-kuis`) dipakai **dua kontainer** yang berbagi volume `data` (file SQLite):
  - `admin`: aplikasi web (port 8000, tidak dibuka ke publik).
  - `bot`: `python -m app.bot.loop` — tidur sampai detik ke-0 tiap menit (WIB), jalankan **satu tick**, ulangi. Tick selalu berurutan (tidak ada tick paralel). Saat menerima sinyal berhenti, selesaikan tick berjalan dulu (`stop_grace_period: 60s`).
- Tidak memakai cron untuk tick. Cron host hanya untuk backup harian.
- Produksi: VPS pemilik proyek yang sudah menjalankan banyak aplikasi Docker, di belakang **Traefik** (HTTPS dari Traefik). Hanya kontainer `admin` yang diberi label Traefik dan bergabung ke network Traefik; tidak ada `ports:` di produksi.
- Admin menulis pengaturan ke database; bot membacanya tiap tick (berlaku ≤ 1 menit, tanpa restart). Jadwal, jam aktif, start/stop **tidak** diatur lewat crontab.
- Healthcheck: `python -m app.cli health admin|bot`; bot dianggap sehat bila `last_tick_at` < 3 menit.

### File compose

- `compose.yml` — dasar (service admin + bot, volume `data`, healthcheck, restart).
- `compose.override.yml` — dev, otomatis dibaca: `.env.dev`, build arg `INSTALL_DEV=true` (pytest, ruff, httpx2), `--reload`, port `8000:8000`, `./app`, `./tests`, `./tools`, `./contoh`, `pyproject.toml` di-mount (tes & lint tanpa rebuild), `./private/bank_soal` di-mount read-only ke `/app/private/bank_soal`.
- Dependensi di `requirements.txt` (produksi) dan `requirements-dev.txt` (dev); `pyproject.toml` berisi konfigurasi pytest & ruff. Lint: `docker compose run --rm bot ruff check .` dan `ruff format .`.
- `compose.prod.yml` — produksi: label Traefik dari variabel `.env` (`${ADMIN_HOST}`, `${TRAEFIK_ENTRYPOINT}`, `${TRAEFIK_CERTRESOLVER}`), batas log 3 × 10 MB. Traefik VPS memakai `network_mode: host`, jadi admin cukup di network default proyek; untuk Traefik di network bersama tambahkan `compose.traefik-net.yml` (`${TRAEFIK_NETWORK}`).
- Produksi dijalankan dengan `docker compose -f compose.yml -f compose.prod.yml …`.

### Pengembangan (Mac + Docker Desktop)

- `.env.dev`: `PLURK_MODE=fake`, `FAKE_NOW=2026-11-30T11:58` (opsional), `TICK_SECONDS=5` (jam palsu maju 1 menit per tick), `DB_PATH=/app/data/dev.db`.
- Database dev di **named volume**, bukan folder Mac (penguncian SQLite di folder bersama Mac tidak andal).
- Dev: kontainer `bot` menjalankan `alembic upgrade head` otomatis sebelum loop (hanya di `compose.override.yml`; produksi tetap eksplisit).
- CLI (`docker compose run --rm bot python -m app.cli …`): `seed --dir private/bank_soal` (impor bank soal lokal + pemain contoh), `status aktif|jeda|berhenti|hentikan`, `tick --now "…"`, `simulasi --pemain 8 --benar 0.3 [--balas 0.5]`, `thread [--sesi N]`, `buat-admin`, `health`.
- Coba sesi di dev: `docker compose up -d` → `… run --rm bot python -m app.cli status aktif` → `… run --rm -T bot timeout 150 python -m app.cli simulasi` → `… run --rm bot python -m app.cli thread`. FakePlurk dev disimpan di `data/fakeplurk.db` (dibagi proses bot & CLI); hapus file itu untuk mulai bersih.
- Sebelum produksi: satu sesi penuh dengan `PLURK_MODE=real` memakai **akun Plurk uji + mode uji privat**.

### Deployment

Status produksi (27 Nov 2026): terpasang di VPS Hostinger (x86_64, template Docker + Traefik). Traefik memakai `network_mode: host` dengan entrypoint khusus aplikasi ini di port 8443 dan certresolver Let's Encrypt; repo di home user non-root yang punya grup `docker` (SSH root dimatikan); zona waktu server bukan WIB, jadi jam cron dikonversi. Backup harian 03.30 WIB, disimpan di VPS saja; tanpa Telegram. Bot memakai akun Plurk produksi (indotrivia); bank soal 10 topik × 500 soal sudah diunggah.

- Kode: Mac → GitHub (**repo publik**, tanpa rahasia dan tanpa soal) → VPS (`git clone`/`git pull` biasa, tidak perlu deploy key).
- Bank soal produksi diunggah lewat halaman admin dari file di laptop; `.env` produksi dibuat langsung di VPS.
- **Image selalu di-build di VPS** (Mac arm64, VPS kemungkinan amd64).
- Update: `scripts/update.sh` (`git pull --ff-only` → backup → `build` → `alembic upgrade head` → `up -d`); menolak jalan pukul 11.00–23.00 WIB di hari aktif kecuali `--paksa`.
- Backup harian (cron host): `scripts/backup.sh` → CLI `backup` (SQLite backup API lewat Python, aman saat bot menulis; `integrity_check`; gzip; simpan 14 hari di `/var/backups/plurk-trivia-kuis`) lalu salin ke luar VPS lewat `BACKUP_RCLONE` atau `BACKUP_RSYNC`. Pulihkan: CLI `pulihkan`.
- Runbook lengkap (cek VPS, `.env`, pemasangan, cron, update, pemulihan, keamanan): `docs/deploy.md`.
- `compose.prod.yml`: root filesystem read-only + `tmpfs /tmp`, `no-new-privileges`, `cap_drop: ALL`; image produksi tanpa pytest/ruff. Sudah diuji di Mac dengan Traefik v3.6 sungguhan (routing HTTPS, host lain 404, cookie Secure di belakang proxy, port 8000 tidak dibuka).
- Notifikasi Telegram (`app/notifikasi.py`, opsional): token Plurk ditolak, outbox gagal 5×, error tick/thread, stok soal kosong, backup gagal, dan **bot macet > 3 menit** — yang terakhir dipantau watchdog di kontainer **admin** (tiap 60 detik), karena bot yang mati tidak bisa melapor. Jenis yang sama paling banyak sekali per jam; tidak pernah memblokir tick. CLI `uji-notifikasi`, `kabari "teks"`.
- NTP host aktif (jadwal bergantung pada menit yang tepat).

## Struktur repo (target)

```
app/
  config.py  db.py  models.py  clock.py  cli.py  bank_soal.py  perintah.py  notifikasi.py  backup.py
  core/      matching.py judging.py scoring.py clues.py validator.py selection.py schedule.py commands.py
  plurk/     client.py real.py fake.py
  bot/       loop.py tick.py engine.py outbox.py messages.py pengaturan.py peringkat.py simulator.py libur.py
  admin/     main.py auth.py deps.py query.py routes/ templates/ static/ (htmx 2.0.4 disimpan lokal + SRI)
alembic/  contoh/  tests/  scripts/backup.sh scripts/update.sh  tools/validasi_soal.py  docs/deploy.md
private/   ← TIDAK di-commit: bank_soal/ (soal asli), laporan/
.gitignore  .dockerignore  .env.example
Dockerfile  compose.yml  compose.override.yml  compose.prod.yml  .env.example  pyproject.toml
```

`tools/validasi_soal.py` adalah CLI tipis di atas `app/core/validator.py` (bisa dijalankan dengan `python3` biasa di laptop, tanpa Docker).
`app/core/` hanya memakai pustaka standar Python; `bot/schedule.py` nanti hanya merangkai `core/schedule.py` dengan pengaturan dari database.

---

## Plurk API

- Plurk API 2.0, OAuth 1.0a (HMAC-SHA1). Dokumentasi: https://www.plurk.com/API
- App: https://www.plurk.com/PlurkApp/ ; token permanen bot dari test console https://www.plurk.com/OAuth/test
- `PlurkClient`:
  - `add_plurk(content, qualifier, limited_to)` → `/APP/Timeline/plurkAdd` (plurk sesi, posting libur; `limited_to` untuk **mode uji privat**)
  - `add_response(plurk_id, content, qualifier)` → `/APP/Responses/responseAdd`
  - `get_responses(plurk_id, from_response)` → `/APP/Responses/get`
  - `accept_friends()` → `/APP/Alerts/addAllAsFriends` (tiap 10 tick)
  - `get_mentions(since)` dan `get_friends()` → endpoint ditentukan di tahap 4 (lihat "Perintah lewat mention"). Kandidat dari dokumentasi: `/APP/Alerts/getActive` & `/APP/Alerts/getHistory` (alert `type: "mentioned"` dengan `plurk_id`, `response_id` — null bila mention di plurk), `/APP/Timeline/getPlurks` `filter=mentioned`, `/APP/FriendsFans/getFriendsByOffset` (`user_id`, `offset`, `limit`)
  - `whoami()` → `/APP/Users/me` (nama lama `/APP/Users/currUser`; cek token, di-cache per proses)
- `RealPlurk` (`app/plurk/real.py`, sudah dibuat sebelum tahap 4): POST ke `https://www.plurk.com/APP/...` dengan `OAuth1Session` (HMAC-SHA1). Error: HTTP 400 + `error_text`; `anti-flood-*` → `AntiFlood`; HTTP 401 atau teks token tidak valid → `TokenDitolak`; selain itu / koneksi gagal → `PlurkError`. Isi balasan memakai `content_raw` (bukan HTML `content`); waktu `posted` (GMT) dikonversi ke WIB.
- `get_responses` sementara mengambil **semua** balasan (`from_response=0`) lalu menyaring ID > `setelah_id`, karena dokumentasi tidak jelas apakah `from_response` offset atau ID. Optimalkan setelah dibuktikan di tahap 4.
- Uji perilaku API asli (tahap 4): `docker compose run --rm bot python -m app.cli uji-plurk --untuk <ID akun admin>` — satu plurk PRIVAT + ±30 balasan (jeda 3 dtk); laporan membuktikan urutan ID, arti `from_response`, `count`, tampilan clue per karakter pengganti, spasi ganda, batas panjang (300/360/361/400/500), anti-flood isi sama, struktur endpoint mention & daftar teman. Simpan laporannya ke `private/laporan/` lalu perbarui dokumen ini.
- Cek token tanpa memposting: `docker compose run --rm bot python -m app.cli cek-plurk` (memakai kredensial `.env`/`.env.dev`, walau `PLURK_MODE=fake`).
- Risiko yang tidak bisa dihindari: koneksi putus SETELAH Plurk menerima posting → outbox mengira gagal → bisa terposting dua kali saat dicoba ulang. Amati di tahap 4.
- Semua posting lewat tabel `outbox` dengan `dedupe_key` (sesi, nomor soal, langkah). Langkah state machine baru maju setelah posting terkirim → restart tidak menyebabkan posting ganda.
- Anti-flood (`anti-flood-same-content`, `anti-flood-too-many-new`): tetap `pending`, coba lagi tick berikutnya; gagal 5× → `failed` + peringatan. Maksimal 2 posting per tick.
- Token ditolak (401): berhenti memposting, isi `last_error`, kirim notifikasi.
- Batas panjang teks disimpan di `settings`: **360, terbukti** (361 → HTTP 400 "Content too long").
- **Hasil uji API asli (27 Nov 2026, akun uji `triviatest` id 18216546, laporan `private/laporan/uji_plurk_20261127.txt`):**
  - ID balasan naik sesuai urutan masuk (ID 15 digit, muat di BigInteger).
  - `/APP/Responses/get` **bisa mengembalikan balasan yang sama dua kali** (ID sama) → `RealPlurk` membuang ID kembar.
  - `from_response` = **offset** (indeks balasan), bukan ID; `count` didukung. Bot tetap mengambil semua lalu menyaring ID.
  - Qualifier `:` dan `limited_to` (plurk privat) diterima; spasi ganda di teks tetap utuh.
  - Balasan berisi sama persis berturut-turut **tidak** kena anti-flood.
  - **Mention terbukti terbaca (27 Nov 2026)** lewat `/APP/Alerts/getActive` dan `/APP/Alerts/getHistory` (30 alert terakhir): alert `type: "mentioned"` berisi `plurk_id`, `response_id` (**null = mention di plurk itu sendiri**, terisi = mention di balasan), `from_user` (dengan `id` & `nick_name`), `posted` (waktu mention, GMT). Keduanya terbaca: mention di plurk milik teman sendiri, dan mention di **balasan pada plurk milik akun lain** (pemiliknya teman bot).
  - `/APP/Timeline/getPlurks filter=mentioned` hanya memuat mention di plurk (bukan di balasan) → tidak dipakai.
  - Rencana tahap 8: tiap tick baca `getHistory` (+ `getActive`), ambil alert `mentioned` yang belum ada di `command_requests` (unik `plurk_id`+`response_id`, 0 = plurk); isi teks dari `/APP/Timeline/getPlurk` (`content_raw`, juga `owner_id` untuk cek teman) atau dari `/APP/Responses/get` (cari ID balasan); teman dari `/APP/FriendsFans/getFriendsByOffset` (cache, paginasi). Mention di plurk milik bukan-teman belum diuji (tetap diabaikan sesuai aturan).

## Jadwal

- Hari aktif: **Rabu, Kamis, Sabtu, Minggu, Senin**. Libur: **Selasa & Jumat** (hanya posting informasi terjadwal dari admin).
- Jam aktif **12.00–22.00 WIB**; sesi tiap 2 jam: **12.00, 14.00, 16.00, 18.00, 20.00** (5 sesi/hari, 50 soal/hari, 250 soal/minggu).
- Maksimal 10 soal per sesi, satu sesi = satu thread (satu plurk). Thread bisa tumpang tindih dengan sesi berikutnya (lihat Mekanik thread).

## Urutan kerja satu tick

1. `bot_state.last_tick_at = sekarang`.
2. Kirim `outbox` tertunda (rangkaian posting yang belum selesai).
3. Status bot **berhenti** → selesai.
4. Tiap 10 tick: `accept_friends()`.
5. Baca mention baru → saring (posisi, kata kunci, teman, blokir, cooldown, batas global) → masukkan antrean perintah. Dijalankan juga di hari libur.
6. Hari libur → kirim `scheduled_posts` yang jatuh tempo, lalu ke langkah 9.
7. Untuk **setiap thread yang belum `die`** → majukan state machine thread itu (lihat bawah). Beberapa thread bisa berjalan bersamaan.
8. Status bot **aktif** dan slot sesi tiba → buka thread baru. Status **jeda** → tidak membuka thread baru (thread yang berjalan tetap dibiarkan selesai).
9. Bila slot posting tick ini masih tersisa → kirim antrean perintah (isi dihitung saat itu; > 60 menit → dibuang).

## Mekanik thread (keputusan 26 Nov 2026, menggantikan alur lama)

Tujuan: tidak memposting sia-sia saat sepi. Satu thread = satu sesi = maks 10 soal.

### Status thread

| Dari → ke | Pemicu |
| --- | --- |
| (muncul) → `hold` | Plurk sesi diposting; **umur thread** dihitung sejak saat ini |
| `hold` → `active` | Ada balasan apa pun di thread (bukan akun bot, bukan pemain diblokir) |
| `hold` → `die` | Umur thread ≥ 60 menit. Dibandingkan dengan **waktu posting balasan**, bukan waktu bot memeriksa: balasan yang diposting sebelum menit ke-60 tetap mengaktifkan thread |
| `active` → `hold` | Tidak ada satu pun balasan sejak "siap soal" (04) diposting sampai pengecekan di langkah 10 |
| `active` → `die` | Soal ke-10 selesai |

- Umur hanya dipakai untuk hold → die. Thread `active` tidak pernah mati karena umur; ia selesai setelah 10 soal (bisa melewati 60 menit, bahkan melewati jam sesi berikutnya).
- "Balasan" = balasan apa pun, termasuk "wkwk" atau emoji tanpa tebakan.
- Siklus soal **tidak pernah dipotong** oleh hold: clue tetap keluar sampai jawaban dibuka walau sepi. Soal tanpa respons tetap dibuka, dihitung dalam jatah 10 soal, dan tercatat terpakai (tidak dikembalikan ke bank).

### Alur

**[hold]**
- 01. Plurk sesi baru: sapaan, hari, nomor sesi.
- 02. Balasan: Top 10 mingguan (minggu baru tanpa skor → teks khusus).
- 03. Balasan: "Katakan sesuatu jika Anda siap." Lalu menunggu:
  - a. Ada balasan → `active`; 04 diposting di tick yang sama.
  - b. Umur ≥ 60 menit → `die`; lompat ke 11.

**[active]**
- 04. "Siap-siap, soal #n…"
- 05. Soal #n (tick berikutnya) → fase 0.
- 06. Ada yang benar → pemenang + skor, lompat ke 10. Belum → **clue 1** (teks clue dari bank) → fase 1.
- 07. Benar → pemenang, lompat ke 10. Belum → **clue 2** (jumlah huruf + pola) → fase 2.
- 08. Benar → pemenang, lompat ke 10. Belum → **clue 3** (huruf awal & akhir) → fase 3.
- 09. Benar → pemenang. Belum → buka jawaban, tanpa pemenang.
- 10. Cek:
  - a. Sudah 10 soal → `die`; lompat ke 11.
  - b1. Ada balasan dalam siklus ini (04 s.d. 10, termasuk setelah jawaban dibuka) → lanjut ke 04 di tick yang sama.
  - b2. Tidak ada balasan → posting "Kuis menunggu peserta. Katakan sesuatu jika Anda siap." (satu posting, menggantikan posting 03) → `hold`; menunggu seperti 03.

**[die]**
- 11. Ranking penjawab **hari ini** — hanya jika thread ini sempat menjalankan minimal 1 soal — lalu farewell + jadwal sesi berikutnya. Jika thread sesi berikutnya sudah dibuka, farewell menyebut "sesi berikutnya sudah dimulai" + tautannya. Sesi terakhir hari itu → jadwal hari aktif berikutnya.

### Posting beruntun (dalam satu tick, tanpa menunggu menit berikutnya)

`01-02-03`, `06a-10b1-04`, `07a-10b1-04`, `08a-10b1-04`, `09a-10b1-04`, `09b-10b1-04`, `10a-11`, `10b2(+tunggu)`, `03a-04`, `03b-11`.
- Beri jeda beberapa detik antar posting dalam satu rangkaian.
- Kena anti-flood → sisa rangkaian dilanjutkan tick berikutnya; status thread baru berpindah setelah seluruh rangkaian terkirim.

### Thread bersamaan

- State disimpan per thread (`sessions.status`, `sessions.posted_at`, langkah, nomor soal).
- Pemilihan soal untuk thread yang berjalan bersamaan saling menghindari soal yang sama dan jawaban yang bocor.

### Kontrol admin

- **Jeda setelah sesi ini**: thread yang berjalan dibiarkan selesai; tidak ada thread baru dibuka.
- **Hentikan sekarang**: semua thread yang belum `die` langsung `die` dan menjalankan langkah 11.

## Perintah lewat mention (keputusan 26 Nov 2026)

Bot menjawab mention di **luar thread kuis** sebagai alat bantu informasi. Fitur ini tersembunyi: tidak diumumkan, tidak ada petunjuk di thread.

### Pemicu
- Mention ke akun bot harus berada **di awal teks** (plurk atau balasan); titik dua setelah mention boleh (`@kuisbot: rank`).
- **Kata kunci = kata pertama setelah mention.** Tidak peka huruf besar/kecil; tanda baca yang menempel di akhir dibuang (`rank?` → `rank`); `?` yang berdiri sendiri = bantuan.
- Teks sesudah kata kunci boleh dan diabaikan (`@kuisbot rank aku berapa sih` = `rank`). Argumen tidak didukung: `rank minggu` atau `rank @nicklain` tetap dijawab sebagai `rank` milik si pemain.
- Teks di antara mention dan kata kunci → bukan perintah (`@kuisbot keren banget!` diabaikan karena `keren` bukan kata kunci).
- Dilayani di luar thread kuis, termasuk plurk bot lain seperti posting hari libur. Di dalam thread kuis, mention diperlakukan sebagai balasan biasa.
- **Pemilik plurk dan pemain yang mention sama-sama harus teman bot.** Pemain diblokir diabaikan.
- Kata kunci tidak dikenal → diabaikan diam-diam.
- Hanya teks saat pertama kali terbaca yang diproses; hasil edit plurk diabaikan.

### Pembatasan
- **Cooldown per perintah per pemain: 1× per 60 menit**, dihitung dari waktu mention. Sinonim = perintah yang sama. Mention dalam cooldown diabaikan diam-diam.
- **Batas global** jawaban per jam (default 20, diatur di admin).
- **Sesi lebih penting dari perintah.** Jawaban masuk antrean prioritas rendah dan hanya dikirim pada slot posting yang tidak dipakai sesi; tertunda beberapa menit itu wajar.
- **Isi jawaban dihitung saat akan dikirim**, bukan saat mention diterima. Jawaban yang tertunda > 60 menit dibuang (`kedaluwarsa`).
- Admin bisa mematikan seluruh fitur, atau per perintah.

### Jenis perintah

| Jenis | Kata kunci (sinonim) | Jawaban |
| --- | --- | --- |
| Bawaan, tampil di bantuan | `jadwal`, `sesi` | Sesi berikutnya. Thread sedang berjalan → "sesi sedang berlangsung" + tautan. Setelah sesi terakhir / hari libur → hari aktif berikutnya |
| Bawaan | `klasemen`, `top` | Top 10 minggu ini. **Selasa → hasil final minggu lalu** |
| Bawaan | `rank`, `peringkat`, `skor`, `poin` | Rank pemain minggu ini, poin, selisih ke peringkat di atasnya, sesi berikutnya. Belum ada poin → pesan khusus. **Selasa → hasil final minggu lalu** |
| Bawaan | `aturan`, `rule` | Ringkasan aturan dari template |
| Bawaan | `bantuan`, `help`, `?` | Daftar kata kunci yang tampil di bantuan |
| Statistik tersembunyi | `rekor` | Skor mingguan tertinggi dan jawaban benar tercepat milik pemain |
| Statistik tersembunyi | `streak` | Jumlah sesi berturut-turut dengan minimal 1 kemenangan |
| Statistik tersembunyi | `statistik` | Total jawaban benar dan fase yang paling sering ditebak benar |
| Kustom (easter egg) | Diatur penuh di admin, mis. `halo`, `makasih`, `bocoran`, `pantun`, `fakta`, `ramal` | Satu atau banyak respons dari database, dipilih acak |

- Semua jawaban singkat dan personal, dari template yang bisa diubah di admin. Contoh `rank`: "Kamu #7 minggu ini (42 poin), 5 poin di belakang #6. Sesi berikutnya 16.00."
- Isian template: `{nama}`, `{rank}`, `{poin}`, `{selisih}`, `{rank_atas}`, `{sesi_berikutnya}`, `{tautan_sesi}`, `{top10}`, `{daftar_bantuan}`; statistik: `{rekor_mingguan}`, `{tercepat}`, `{streak}`, `{total_benar}`, `{fase_favorit}`. Respons kustom hanya boleh memakai isian ringan (`{nama}`, `{sesi_berikutnya}`).
- Kata kunci/sinonim kustom tidak boleh bentrok dengan kata kunci atau sinonim yang sudah ada; panjang respons dicek terhadap batas karakter Plurk.
- Isi respons kustom dan daftar konten (pantun, fakta, ramalan) **disimpan di database**, bukan di kode (repo publik), dan **terpisah dari bank soal** supaya tidak membocorkan soal.

### Implementasi (tahap 8, 27 Nov 2026)

- `app/core/commands.py` `parse_perintah()` (fungsi murni), `app/bot/mention.py` (langkah 5 & 9), CLI `cek-mention` (dry run dengan Plurk asli: membaca alert, menyaring, menghitung jawaban; tidak memposting & tidak menyimpan).
- Sumber mention: alert `mentioned` (`getActive` + `getHistory`), maks 10 alert baru per tick, diurutkan menurut waktu mention. Setiap alert dicatat **sekali** di `command_requests` (unik `plurk_id`+`response_id`) beserta `text` dan `keyword`; status tambahan **`diabaikan`** (bukan perintah, mention tidak di awal, kata kunci tak dikenal, di thread kuis, mention oleh bot sendiri).
- Fitur mati → mention tidak dibaca sama sekali. Saat dinyalakan lagi, alert yang lebih tua dari batas kedaluwarsa langsung dicatat `kedaluwarsa`.
- Urutan saring: `nonaktif` → `diblokir` → `bukan_teman` (pemilik plurk ATAU pemain bukan teman; plurk milik bot dianggap teman) → `cooldown` (perintah sama oleh pemain sama berstatus antre/dijawab dalam 60 menit sejak waktu mention) → `batas_global` (antre+dijawab yang diterima dalam 1 jam terakhir) → `antre`.
- Daftar teman di-cache 10 menit per proses (paginasi `getFriendsByOffset`).
- Jawaban = balasan di plurk tempat mention. Dikirim di langkah 9 hanya dari **sisa** jatah posting setelah sesi (outbox prioritas 1), satu per satu; isinya dihitung tepat sebelum diantre ke outbox.
- Variasi jawaban ada di tabel `templates` (bisa diubah di Kontrol & pengaturan → Template): `perintah_jadwal_berlangsung`, `perintah_rank_kosong`, `perintah_rank_satu` (peringkat #1, tanpa "selisih"), `perintah_klasemen_kosong`. Isian yang dikenal tapi tidak relevan diisi kosong (tidak pernah tampil "{isian}" mentah).
- `rekor`: skor mingguan tertinggi (skor + koreksi) dan jawaban benar tercepat = detik dari soal tampil sampai balasan benar. `streak`: sesi selesai berturut-turut (yang sempat menjalankan soal) dengan ≥ 1 kemenangan; sesi yang masih berjalan tidak memutus streak. `statistik`: total benar + fase paling sering.
- Error di langkah 5/9 tidak pernah mengganggu sesi (ditangkap, dicatat, notifikasi).
- **Sesi penuh di Plurk asli (27 Nov 2026, 00.10–00.51 WIB)**, akun uji `triviatest`, mode uji privat untuk angsagd & indotrivia, database terpisah `uji_real.db`: 10 soal; 6 terjawab di fase Soal/Clue 1/2/3 dengan poin sesuai rumus (12, 3, 4, 5, 11, 3), 4 tanpa pemenang; satu siklus sepi → "Kuis menunggu peserta" → aktif lagi; status balasan `salah`/`benar`/`lewat_batas` muncul; ranking + farewell terkirim. 56 posting outbox, semua terkirim tanpa percobaan ulang; 53 balasan bot di thread = 53 baris outbox (tidak ada posting ganda). Dua clue identik untuk dua soal berbeda (`===== ====`) diterima tanpa anti-flood. Perintah `rank` & `jadwal` dari mention sungguhan **dijawab di Plurk**.
- Dry run dengan Plurk asli (27 Nov 2026): mention `@triviatest rank` (di plurk sendiri) dan `@triviatest jadwal` (di balasan plurk indotrivia) terbaca, lolos cek teman, dan jawabannya benar. Balasan sungguhan ke Plurk belum dikirim.

### Kebutuhan Plurk API (terbukti di tahap 4)
- Membaca mention baru: plurk teman di timeline bot hampir pasti terbaca; mention di **balasan** pada plurk yang tidak diikuti bot belum tentu tersedia lewat API. Jika tidak, fitur tetap jalan dengan cakupan plurk yang terbaca saja.
- Mengecek status pertemanan pemilik plurk dan pemain (cache daftar teman, diperbarui berkala).

### Keputusan implementasi tahap 3 (perlu dikonfirmasi pemilik proyek)

- **Jatah posting per tick = 2** (pengaturan `maks_posting_per_tick`), dibagi semua thread. Akibatnya 01-02-03 terkirim dalam 2 tick, rangkaian 3 posting (mis. pemenang + ranking + farewell) selesai di tick berikutnya, dan thread yang berjalan bersamaan bisa tertunda 1 menit. Naikkan ke 3 bila ingin 01-02-03 dalam satu tick.
- Status thread disimpan saat keputusan dibuat; langkah berikutnya thread itu menunggu sampai seluruh posting miliknya terkirim (pending = tidak maju).
- Siklus tanpa balasan ketika umur thread sudah ≥ 60 menit → langsung `die` (posting 10b2 dilewati, karena balasan sesudah menit 60 tidak bisa lagi mengaktifkan thread).
- Batas umur dibandingkan dengan waktu posting balasan; pemicu `active` dalam hold = balasan dengan ID > balasan terakhir yang terbaca saat thread masuk hold (awal: semua balasan).
- Siklus baru (04) dimulai dari balasan terakhir yang terbaca saat keputusan; balasan setelahnya dihitung untuk cek langkah 10.
- 10 soal dipilih saat sesi dibuka, tetapi `used_cycle`/`times_used` baru dicatat saat soal **ditampilkan**; soal yang tak sempat tampil kembali ke bank.
- Thread yang belum `die` tetap diproses di hari libur (mis. melewati tengah malam); hari libur hanya mencegah sesi baru.
- Sesi boleh dibuka sampai `toleransi_slot_menit` (5) setelah jam slot bila tick terlewat karena restart; satu slot satu sesi (`play_date`, `slot` unik).
- Outbox gagal 5× → `failed`; thread pemiliknya langsung `die` tanpa posting lagi dan `last_error` diisi. Error apa pun dari Plurk menghentikan pengiriman di tick itu (urutan rangkaian terjaga). Token ditolak → status bot `berhenti`.
- Teks yang melebihi `batas_teks` dipotong dengan `…`. Template bawaan ada di `app/bot/messages.py`; tabel `templates` menimpanya per key.
- `PlurkClient.get_responses(plurk_id, setelah_id)` mengembalikan balasan dengan ID > `setelah_id`; RealPlurk yang menerjemahkan ke offset API.
- Hentikan sekarang: semua thread `die` (langkah 11 diantre) lalu status bot `berhenti`; outbox tetap dikirim di langkah 2 tick berikutnya.

## Penilaian jawaban

- Pemenang = jawaban benar **pertama menurut urutan ID balasan**, bukan waktu bot memeriksa.
- Setiap balasan bot (soal/clue) adalah **penanda fase** (`marker_ids`). Fase sebuah jawaban = posisinya di antara penanda. Jawaban sebelum soal muncul, setelah pemenang ditetapkan, atau setelah jawaban dibuka → `di_luar_soal`.
- Fungsi: `core.judging.nilai_balasan()` — murni dan deterministik, dipanggil ulang tiap tick dengan semua balasan yang sudah terbaca.
- Urutan pemeriksaan: balasan bot dibuang → `diblokir` → `di_luar_soal` → `lewat_batas` → `terlalu_panjang` → `benar`/`salah`. Balasan yang terlalu panjang tetap dihitung dalam jatah 3 balasan per fase.
- Buang balasan bot sendiri dan pemain yang diblokir (`diblokir`).
- Hanya **3 balasan pertama per pemain per fase** yang dinilai; sisanya `lewat_batas`.
- Balasan **> 40 karakter** tidak dinilai (`terlalu_panjang`); batas bisa diatur di admin.
- Pencocokan:
  - case-insensitive;
  - jawaban dicari sebagai **kata utuh** dalam balasan (boleh ada teks, tanda baca, emoji lain) — "kebalikan" TIDAK cocok dengan BALI;
  - pemisah antar kata jawaban fleksibel: "Bung-Karno", "bung  karno", "bungkarno" cocok dengan BUNG KARNO;
  - normalisasi dulu: buang aksen (é→e, ö→o, ð→d), hapus titik ("A.T. Mahmud" → "AT Mahmud").
- **Tidak ada jawaban alternatif.** Jawaban di bank dipakai apa adanya (termasuk "THE", nama lengkap, ejaan tertentu); clue 2 memperlihatkan bentuknya.

## Skor (sementara — pemilik proyek sedang meriset rumus lain)

```
skor = ceil(jumlah_huruf_jawaban / (1 + jumlah_clue_yang_sudah_keluar))
```
Spasi tidak dihitung. SOEKARNO (8): 8 / 4 / 3 / 2. Rumus harus mudah diganti (fungsi `core.scoring`, pilihan di pengaturan).

Skor disimpan per baris di `scores` (`play_date`, `week_start`); peringkat = penjumlahan pada rentang tanggal. Periode mingguan **Rabu–Senin**, reset **Selasa 00.00 WIB** (`week_start` = Rabu awal periode). Koreksi manual di `score_adjustments`.

## Clue

- Clue 1: teks clue dari bank soal.
- Clue 2: jumlah huruf (angka) + pola per kata. MOHAMMAD HATTA → `13 huruf: ======== =====`.
- Clue 3: huruf awal dan akhir **seluruh jawaban** (bukan per kata) → `M======= ====A`.
- Karakter pengganti dipilih di admin: `=` (bawaan), `.`, `＿`; pemisah kata: spasi atau ` / `. **Terbukti di Plurk asli:** `--` dirender sebagai teks coret dan `__` sebagai garis bawah, jadi `-` dan `_` tidak dipakai; nilai lama yang tidak didukung otomatis kembali ke `=`.

## Bank soal

- Banyak file, **satu file = satu topik**. Satu baris per soal: `soal|clue|jawaban` (UTF-8, baris `#` = komentar).
- **Nama topik diambil dari nama file**, tidak diketik manual. Format nama file: `trivia_NN_nama_topik.txt`
  - `NN` = nomor topik dua digit (01–99), unik antar topik; dipakai sebagai urutan tampil.
  - `nama_topik` = huruf/angka, antar kata dipisah **satu** garis bawah.
  - Nama topik: garis bawah → spasi, huruf awal tiap kata → kapital; kata yang sudah memuat huruf kapital dibiarkan apa adanya. `trivia_04_sejarah_dunia.txt` → "Sejarah Dunia"; `trivia_07_film_dan_TV.txt` → "Film Dan TV".
  - Nama file yang tidak sesuai format ditolak sebelum isi divalidasi.
  - Identitas topik = nama topik (tanpa membedakan huruf besar/kecil). Unggah file dengan nama topik yang sudah ada → otomatis memperbarui topik itu; tidak ada pilihan "topik baru / perbarui" di admin. Nomor yang sudah dipakai topik lain → ditolak. Nama topik sudah ada tetapi nomornya berbeda → ditolak (ubah nomor lewat Ganti nama).
  - Fungsi referensi: `topik_dari_nama_file()` di `tools/validasi_soal.py`.
- **Ganti nama topik** (tombol di halaman Bank soal): admin mengetik nama file baru dengan format yang sama; nomor dan/atau nama boleh berubah.
  - Divalidasi: format nama file, nama topik dan nomor tidak dipakai topik lain, dan harus benar-benar berbeda dari yang lama.
  - Topik tetap record yang sama, jadi riwayat soal terpakai, siklus, skor, dan statistik topik tidak hilang. Unggahan berikutnya harus memakai nama file baru.
  - Dicatat di `admin_audit` (nama lama → nama baru).
- **Cek kemiripan saat unggah topik baru:** bila lebih dari separuh soal di file (menurut `text_hash`) sudah ada di satu topik lain, tampilkan peringatan "mungkin ini topik X yang diganti nama" dan tawarkan Ganti nama. Admin tetap boleh melanjutkan sebagai topik baru.
- Soal maks 180 karakter; clue maks 180 karakter (masing-masing); jawaban hanya A–Z dan spasi, 4–20 huruf (spasi tidak dihitung).
- Unggah lewat admin → validasi → pratinjau → simpan setelah dikonfirmasi.
- Identitas soal = **hash teks soal yang dinormalisasi** (`text_hash`); unggah ulang memperbarui clue/jawaban tanpa menghapus riwayat.
- Pemilihan soal (10 soal dipilih saat sesi dimulai):
  1. Topik aktif dipilih acak dengan **bobot = jumlah soal aktif** di topik itu.
  2. Soal acak dengan `used_cycle` < `cycle` topik.
  3. Topik habis → `cycle` topik itu naik satu (diputar ulang topik itu saja).
  4. Topik yang sama boleh muncul berkali-kali dalam satu sesi.
  5. Tolak kandidat bila jawabannya tertulis (kata utuh) di soal/clue soal lain di sesi itu, atau sebaliknya; dua soal berjawaban sama juga ditolak. Maks 50 percobaan per soal; bila tetap bentrok, kandidat terakhir dipakai dan dicatat sebagai peringatan.
  - Fungsi: `core.selection.pilih_soal()`; mengembalikan `cycle_baru` per topik dan `used_cycle` per soal untuk disimpan pemanggil. Soal thread lain yang sedang berjalan dikirim lewat `sudah_ada`.
  6. "Lewati soal" dari admin mengganti soal aktif dengan aturan yang sama.
- Format contoh (publik): `contoh/trivia_99_contoh.txt`. Bank soal asli ada di `private/bank_soal/` (tidak di-commit).

## Database (SQLite, 19 tabel)

`settings`, `bot_state` (1 baris), `topics`, `questions`, `players`, `sessions`, `session_questions`, `responses`, `scores`, `score_adjustments`, `templates`, `outbox`, `scheduled_posts`, `admin_audit`, `admins`, `commands`, `command_aliases`, `command_responses`, `command_requests`.
`commands` (key, kind `bawaan`/`statistik`/`kustom`, enabled, show_in_help, template); `command_aliases` (alias unik → command); `command_responses` (respons kustom, dipilih acak); `command_requests` (plurk_id, response_id, player_id, command_id, received_at, status `dijawab`/`cooldown`/`batas_global`/`kedaluwarsa`/`nonaktif`/`bukan_teman`/`diblokir`, sent_at).
`sessions` menyimpan state per thread: `status` (`hold`/`active`/`die`), `posted_at` (awal umur thread), `step`, `question_count`, `cycle_start_response_id` (penanda awal siklus untuk cek respons), `ever_ran_question`.
Status balasan: `benar`, `salah`, `lewat_batas`, `terlalu_panjang`, `di_luar_soal`, `diblokir`. Kolom lengkap ada di blueprint; `app/models.py` adalah sumber kebenaran.

Keputusan tahap 2 (berbeda/tambahan dari blueprint):
- Waktu disimpan lewat tipe `WaktuWIB`: teks ISO WIB lebar tetap (`2026-11-30T12:00:00.000000+07:00`); datetime tanpa zona ditolak. `play_date`/`week_start` = `Date`.
- `bot_state`: tanpa `current_session_id` (thread bisa bersamaan; state ada di `sessions`). Tambahan `heartbeat_at` (jam nyata, untuk healthcheck; `last_tick_at` memakai Clock sehingga bisa jam palsu di dev), `tick_count` (untuk "tiap 10 tick"), `last_error_at`. Baris id=1 dibuat migrasi pertama dengan status `berhenti`.
- `sessions`: tambahan `last_response_id` (balasan terakhir yang terbaca) dan `test_mode`. `session_questions`: tambahan `reveal_response_id`, `started_at`, `ended_at`. `responses`: tambahan `session_id` (balasan di luar siklus soal tetap tersimpan untuk cek hold/active).
- `outbox`: tambahan `priority` (0 sesi, 1 jawaban perintah), `session_id`, `no_comments`, `last_error`, `created_at`, `sent_at`.
- `command_requests`: unik (`plurk_id`, `response_id`; 0 = mention di plurk itu sendiri), status tambahan `antre`, kolom `outbox_id`.
- Impor topik (`app/bank_soal.impor_topik`, dipakai `seed` dan nanti admin): hanya flush, pemanggil yang commit (untuk pratinjau). Soal yang hilang dari file → `is_active = False` (tidak dihapus); baris error dilewati; soal kembar di file disimpan sekali.
- `buat-admin`: hanya satu akun; `--reset` untuk ganti password; `--password-stdin` untuk tanpa prompt; password minimal 12 karakter. Pemain contoh `seed` hanya dibuat bila `PLURK_MODE=fake`.

## Admin web (satu akun)

| Halaman | Rute | Fungsi |
| --- | --- | --- |
| Dashboard | `/` | Status bot, tick terakhir, thread berjalan live dengan status hold/active/die dan umurnya (HTMX 5 dtk), ringkasan hari ini, peringatan, jadwal, Top 5, stok soal per topik |
| Peringkat | `/peringkat` | Hari ini / minggu ini / semua waktu / rentang tanggal, filter topik, detail pemain, koreksi skor (dengan alasan), blokir, ekspor CSV |
| Bank soal | `/soal` | Unggah file topik (nomor & nama topik dibaca dari nama file; topik yang sudah ada otomatis diperbarui; cek kemiripan), ganti nama topik, hasil validasi, aktif/nonaktif topik, cari & nonaktifkan soal |
| Kontrol & pengaturan | `/pengaturan` | Jalankan / jeda setelah sesi / hentikan sekarang, lewati soal, mode uji, karakter pengganti + pratinjau, jadwal, aturan permainan, rumus skor, template pesan (`{waktu}`, `{hari}`, `{sesi}`, `{jam}`, `{sesi_berikutnya}`, `{nama}`, `{skor}`, `{jawaban}`…) |
| Posting hari libur | `/libur` | Jadwal posting Selasa/Jumat, status kirim, kirim uji privat; juara mingguan Selasa otomatis dari template |
| Riwayat sesi | `/riwayat` | Arsip sesi: soal, pemenang, semua balasan + status |
| Perintah & easter egg | `/perintah` | Mati/hidup seluruh fitur, cooldown, batas global; tabel kata kunci (jenis, sinonim, aktif, tampil di bantuan); template jawaban bawaan & statistik; tambah/ubah/hapus kata kunci kustom beserta daftar respons; log perintah |
| Log admin | `/log` | Isi `admin_audit` |

Keamanan: argon2 + opsional TOTP, cookie `HttpOnly`/`Secure`/`SameSite=Strict`, CSRF, batas 5 login gagal per 15 menit, akun dibuat lewat CLI `buat-admin`, semua aksi tercatat di `admin_audit`.

### Keputusan implementasi tahap 5 (perlu dikonfirmasi pemilik proyek)

- **Admin tidak pernah memanggil Plurk.** Aksi yang perlu Plurk ditulis ke database, lalu dijalankan bot di tick berikutnya (≤ 1 menit): "Hentikan sekarang" = status `hentikan` (bot menutup semua thread lalu `berhenti`); "Kirim uji (privat)" = baris outbox `kind=plurk` dengan `limited_to` = ID akun admin (wajib diisi di Mode uji).
- **Lewati soal** mengganti soal **berikutnya** yang belum tampil (soal yang sedang tampil tidak dipotong); tombolnya di kartu thread di Dashboard.
- Sesi login: cookie bertanda tangan HMAC (`APP_SECRET_KEY`, min. 32 karakter) berlaku 12 jam; CSRF lewat field `csrf` atau header `X-CSRF-Token` (HTMX). `COOKIE_SECURE=false` hanya untuk dev tanpa HTTPS. TOTP: `buat-admin --totp` mencetak URI untuk aplikasi authenticator.
- Header: CSP `default-src 'self'` (tanpa CDN/Google Fonts), `X-Frame-Options: DENY`, `Cache-Control: no-store`.
- Jam halaman admin: jam bot (`bot_state.last_tick_at`) bila dev memakai jam palsu; selain itu jam nyata WIB.
- Jadwal diatur dengan mulai/selesai/jarak sesi + centang hari aktif (seperti mockup). Kolom mockup "jarak antar fase" dan "batas jawaban per pemain per menit" tidak dibuat: fase = 1 tick (1 menit) dan batasnya 3 balasan per fase (CLAUDE.md).
- Posting hari libur hanya boleh di hari yang bukan hari aktif; dikirim bot pada langkah 6. **Juara mingguan otomatis tiap Selasa 12.00 WIB** (template `juara_mingguan`, Top 10 minggu lalu; dilewati bila belum ada skor).
- Perintah bawaan & statistik (`app/perintah.py`) dibuat otomatis saat admin start; `?` = sinonim khusus `bantuan`. Kata kunci/sinonim: huruf kecil a-z & angka, 2-20 karakter, tidak bentrok. Respons kustom hanya boleh `{nama}` dan `{sesi_berikutnya}`.
- Pratinjau unggah = impor dijalankan dalam transaksi lalu di-rollback; isi file dibawa ke tombol Simpan sebagai field tersembunyi (base64). Cek kemiripan menawarkan "Ganti nama topik lama → nama file ini lalu perbarui".

Statistik untuk riset skor: fase rata-rata terjawab per soal/topik, % tidak terjawab, panjang jawaban vs kesulitan, sesi/jam teramai.

## Tes wajib (contoh)

| Kasus | Harapan |
| --- | --- |
| "jawabannya Bali dong!!" / "kebalikan" untuk BALI | benar / salah |
| "bung-karno", "bungkarno" untuk BUNG KARNO | benar |
| "A.T. Mahmud", "Beyoncé", "Guðnadóttir" | benar untuk AT MAHMUD, BEYONCE, GUDNADOTTIR |
| "hatta" untuk MOHAMMAD HATTA | salah |
| Balasan 41 karakter / balasan ke-4 dalam satu fase | `terlalu_panjang` / `lewat_batas` |
| Dua jawaban benar dalam satu menit | ID lebih kecil menang |
| SOEKARNO fase 0–3 | 8, 4, 3, 2 |
| Clue MOHAMMAD HATTA dengan `=` | `13 huruf: ======== =====`, `M======= ====A` |
| Topik 500 vs 1.500 soal, 10.000 undian | rasio ≈ 1 : 3 |
| Selasa, Jumat, 22.30 WIB | tidak ada sesi |
| Bot mati di tengah tick | tidak ada posting ganda |
| Thread baru tanpa balasan sampai menit 60 | `die`; hanya farewell (tanpa ranking) |
| Balasan diposting menit 59:50, diperiksa setelah menit 60 | thread menjadi `active` |
| Satu siklus soal tanpa balasan | jawaban tetap dibuka, soal terhitung, lalu `hold` + pesan menunggu |
| Thread `active` melewati menit 60 | tetap berjalan sampai soal ke-10 |
| Dua thread berjalan bersamaan | keduanya diproses tiap tick; tidak ada soal yang sama |
| Thread die setelah sesi berikutnya dibuka | farewell menyebut sesi berikutnya sudah dimulai + tautan |
| `eh @kuisbot rank` (mention tidak di awal) | diabaikan |
| `@kuisbot keren banget!` | diabaikan (bukan kata kunci) |
| `@kuisbot: Rank?` dan `@kuisbot RANK aku berapa` | dijawab sebagai `rank` |
| `rank` lalu `skor` oleh pemain sama dalam 60 menit | yang kedua diabaikan (`cooldown`) |
| Pemain teman mention di plurk milik bukan-teman | diabaikan (`bukan_teman`) |
| `klasemen` / `rank` di hari Selasa | hasil final minggu lalu |
| Jawaban tertunda karena sesi ramai | isi dihitung saat dikirim; > 60 menit dibuang |
| Kata kunci kustom baru bentrok dengan `top` | ditolak saat disimpan di admin |
| Unggah `trivia_04_sejarah_dunia.txt` | topik nomor 04 "Sejarah Dunia" |
| Unggah `trivia_4_musik.txt` atau `musik.txt` | ditolak: format nama file salah |
| Unggah file topik yang namanya sudah ada | topik itu diperbarui, riwayat soal tetap |
| Ganti nama `trivia_02_sejarah_indonesia.txt` → `trivia_02_sejarah_nusantara.txt` | topik sama bernama "Sejarah Nusantara"; riwayat soal & skor tetap |
| Ganti nama ke nama atau nomor milik topik lain | ditolak |
| Unggah topik baru yang > 50% soalnya ada di topik lain | peringatan + tawaran ganti nama |

## Tahapan

| # | Tahap | Selesai bila |
| --- | --- | --- |
| 0 | Fondasi: repo, Dockerfile, 3 file compose, pyproject, ruff, pytest | `docker compose up` jalan di Mac; pytest hijau |
| 1 | Aturan inti `app/core/` | Semua tes aturan lulus |
| 2 | Database: model, migrasi pertama, CLI `seed` | Bank soal dari `private/bank_soal/` terimpor dengan nama topik dari nama file; impor ulang tidak menggandakan |
| 3 | Mesin bot dengan `FakePlurk` + jam palsu + simulator | Mekanik hold/active/die lulus semua skenario tes; dua thread bersamaan berjalan benar; tes ketahanan lulus |
| 4 | `RealPlurk` + mode uji privat | Sesi penuh di akun uji; urutan ID, batas karakter, tampilan clue terverifikasi; cara membaca mention dan status pertemanan terbukti · **selesai 27 Nov 2026** |
| 5 | Admin web 8 halaman | Semua fungsi mockup jalan di Mac |
| 6 | Produksi: VPS, Traefik, backup, notifikasi | HTTPS jalan; healthcheck hijau; backup harian ada · **selesai 27 Nov 2026** |
| 7 | Uji coba 1–2 hari (mode uji, akun asli) → go-live | Sesi berjalan sesuai jadwal tanpa campur tangan |
| 8 | Perintah lewat mention + easter egg | Semua tes perintah lulus; jawaban tidak pernah menggeser posting sesi; fitur bisa dimatikan dari admin · **selesai 27 Nov 2026** |

## Pertanyaan terbuka

- Rumus skor final.
- Gabung posting 02 (Top 10) dan 03 (ajakan) menjadi satu posting atau tidak.
- Tujuan backup di luar VPS (sementara backup hanya di VPS; diputuskan 27 Nov 2026). Notifikasi Telegram: tidak dipakai (27 Nov 2026).
- Mention di plurk milik akun yang **bukan** teman bot: apakah alert tetap muncul (tidak menghalangi; mention itu memang diabaikan).
- Isi awal easter egg kustom (kata kunci dan respons) — dibahas terpisah.

## Isi repo saat ini

- `CLAUDE.md` — dokumen ini
- `README.md` — ringkasan publik (fitur, menjalankan di lokal, format bank soal, produksi)
- Tahap 0: `Dockerfile` (python:3.12-slim, user non-root `app`), `compose.yml`, `compose.override.yml`, `compose.prod.yml`, `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`
- `app/config.py` (pydantic-settings; `PLURK_MODE=real` menolak `FAKE_NOW`/`TICK_SECONDS`≠60), `app/clock.py` (`SystemClock`/`FakeClock`, WIB), `app/bot/loop.py` (tick tiap detik ke-0 WIB atau jam palsu; SIGTERM menyelesaikan tick berjalan), `app/bot/tick.py` (kerangka), `app/admin/main.py` (kerangka + `/health`), `app/cli.py` (`health admin|bot`)
- Tahap 8: `app/core/commands.py` (`parse_perintah`), `app/bot/mention.py`, `PlurkClient.get_mentions/get_plurk/get_friend_ids` (Fake + Real), migrasi `teks perintah` (`command_requests.text`, `.keyword`), CLI `cek-mention`
- Tahap 6 (sisi repo): `app/notifikasi.py`, `app/backup.py`, CLI `backup`/`pulihkan`/`uji-notifikasi`/`kabari`, watchdog bot di admin, `scripts/backup.sh`, `scripts/update.sh`, `docs/deploy.md`, hardening `compose.prod.yml`
- Tahap 5: admin web (`app/admin/`: 8 halaman + login, `routes/` per halaman, `templates/`, `static/`), `app/core/commands.py`, `app/perintah.py`, `app/bot/libur.py`; CLI `buat-admin --totp`
- Tahap 3–4: `app/plurk/` (`client.py` antarmuka + error, `fake.py` FakePlurk SQLite, `real.py` RealPlurk OAuth, belum diuji ke Plurk asli), `app/bot/` (`engine.py` mesin thread, `outbox.py`, `tick.py`, `messages.py`, `pengaturan.py`, `peringkat.py`, `simulator.py`), CLI `status`/`tick`/`simulasi`/`thread`
- Tahap 2: `app/db.py` (SQLite WAL, `WaktuWIB`, `sesi_db`), `app/models.py` (19 tabel), `alembic/` (migrasi `skema awal`), `app/bank_soal.py` (impor topik), CLI `seed` & `buat-admin`; tick menulis `bot_state`, healthcheck bot membaca `bot_state.heartbeat_at`
- Tahap 1: `app/core/` — `matching.py` (normalisasi, kata utuh), `judging.py` (status balasan, pemenang, fase), `scoring.py`, `clues.py`, `validator.py` (nama file, isi, `text_hash`, unggah, ganti nama, kemiripan), `selection.py`, `schedule.py` (hari aktif, slot, sesi berikutnya, periode Rabu–Senin)
- `tools/validasi_soal.py` — CLI validator bank soal di atas `app/core/validator.py`
- `tests/` — `core/` (aturan inti), `test_fondasi.py`, `test_engine.py` (skenario thread, outbox, crash, ketahanan sehari penuh), `test_real_plurk.py` (RealPlurk dengan sesi HTTP palsu), `test_admin.py` (login, CSRF, TOTP, 8 halaman, aksi admin), `test_ops.py` (backup, pulihkan, notifikasi, watchdog), `test_mention.py` (perintah lewat mention), `test_db.py` (migrasi = model, impor, CLI), `test_tools.py`; fixture `db_path`/`engine` membuat database lewat `alembic upgrade head`; `conftest.py` mengosongkan variabel env agar tes tidak terpengaruh `.env.dev`
- `contoh/trivia_99_contoh.txt` — format bank soal dengan 8 soal karangan
- `docs/mockup/` — sumber mockup admin, 6 layar termasuk Perintah & easter egg (`.dc.html`, data contoh)
- `.gitignore`, `.dockerignore`, `.env.example`
- `private/` (lokal saja, tidak di-commit): `bank_soal/` (bank soal asli per topik), `laporan/` (review dan catatan perubahan bank soal)
