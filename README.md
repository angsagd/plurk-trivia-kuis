# Plurk Trivia Kuis

Bot kuis trivia otomatis di [Plurk](https://www.plurk.com), lengkap dengan halaman admin web.

Bot membuka satu thread kuis (satu plurk) per sesi, memposting soal, memberi clue bertahap, menilai balasan pemain,
mencatat skor, dan mengumumkan peringkat. Semua berjalan sesuai jadwal tanpa campur tangan admin.

## Fitur

- **Sesi terjadwal**: hari aktif Rabu, Kamis, Sabtu, Minggu, Senin; sesi tiap 2 jam pukul 12.00–20.00 WIB; maks 10 soal per sesi.
- **Thread hemat posting**: thread menunggu peserta (`hold`), berjalan saat ada balasan (`active`), dan ditutup bila sepi 60 menit (`die`).
- **Clue bertahap**: clue teks dari bank soal → jumlah huruf + pola (`======== =====`) → huruf awal & akhir (`M======= ====A`).
- **Penilaian adil**: pemenang = jawaban benar pertama menurut urutan ID balasan; pencocokan kata utuh, tidak peka huruf besar/kecil,
  aksen, titik, dan pemisah kata.
- **Skor & peringkat** harian, mingguan (Rabu–Senin), dan sepanjang waktu; koreksi skor manual.
- **Bank soal per topik**: satu file teks per topik, diunggah lewat admin dengan validasi dan pratinjau.
- **Perintah lewat mention** (opsional): `jadwal`, `klasemen`, `rank`, `aturan`, `bantuan`, statistik tersembunyi, dan easter egg kustom.
- **Posting hari libur** terjadwal dan pengumuman juara mingguan otomatis.
- **Mode uji**: semua posting sesi dibuat privat untuk akun admin.
- **Admin web**: dashboard live, peringkat, bank soal, kontrol & pengaturan, template pesan, riwayat sesi, perintah, log audit.

## Teknologi

Python 3.12 · FastAPI + Jinja2 + HTMX · SQLite (WAL) · SQLAlchemy 2 + Alembic · Plurk API 2.0 (OAuth 1.0a) ·
Docker Compose · pytest + ruff.

Satu image Docker dipakai dua kontainer yang berbagi database SQLite:

| Kontainer | Tugas |
| --- | --- |
| `bot` | Menjalankan satu *tick* tiap menit (WIB): kirim antrean posting, baca balasan & mention, majukan thread, buka sesi baru |
| `admin` | Halaman admin web (di produksi di belakang reverse proxy HTTPS, mis. Traefik) |

## Struktur

```
app/
  core/    aturan permainan sebagai fungsi murni (pencocokan, penilaian, skor, clue, validator, pemilihan soal, jadwal, perintah)
  bot/     mesin thread, outbox, tick, template pesan, mention
  plurk/   PlurkClient: RealPlurk (API asli) dan FakePlurk (simulasi untuk dev & tes)
  admin/   aplikasi web FastAPI
  cli.py   perintah operasional (python -m app.cli …)
alembic/   migrasi database
contoh/    contoh format bank soal
docs/      panduan deploy dan mockup admin
scripts/   backup.sh, update.sh
tests/     tes otomatis
tools/     validasi_soal.py (cek file bank soal tanpa Docker)
```

## Menjalankan di lokal

Prasyarat: Docker dengan Docker Compose v2.

```bash
cp .env.example .env.dev          # PLURK_MODE=fake: tanpa akun Plurk sungguhan
docker compose up -d --build      # admin di http://localhost:8000
docker compose run --rm bot python -m app.cli buat-admin --username admin
docker compose run --rm bot python -m app.cli seed --dir contoh   # impor contoh bank soal
```

Untuk dev, isi `.env.dev` dengan `COOKIE_SECURE=false`. Agar sesi cepat dicoba, pakai juga `FAKE_NOW=2026-11-30T11:58` dan `TICK_SECONDS=5`,
sehingga jam palsu maju 1 menit tiap 5 detik.

Simulasi satu sesi dengan pemain palsu:

```bash
docker compose run --rm bot python -m app.cli status aktif
docker compose run --rm -T bot timeout 150 python -m app.cli simulasi --pemain 8 --benar 0.3
docker compose run --rm bot python -m app.cli thread
```

Tes dan lint:

```bash
docker compose run --rm bot pytest
docker compose run --rm bot ruff check .
```

## Format bank soal

Satu file per topik, bernama `trivia_NN_nama_topik.txt`. `NN` adalah nomor urut dua digit, dan nama topik diambil dari nama file.
Isinya satu baris per soal dengan format `soal|clue|jawaban`. Baris yang diawali `#` adalah komentar.

```
# trivia_99_contoh.txt
Siapa presiden pertama Republik Indonesia?|Dijuluki Putra Sang Fajar, lahir di Surabaya|SOEKARNO
```

Aturan singkat: soal dan clue masing-masing maks 180 karakter; jawaban hanya huruf A–Z dan spasi, 4–20 huruf.
Lihat `contoh/trivia_99_contoh.txt`, lalu cek file Anda dengan:

```bash
python3 tools/validasi_soal.py path/ke/trivia_01_topik.txt
```

## Produksi

Panduan langkah demi langkah ada di [`docs/deploy.md`](docs/deploy.md). Panduan itu mencakup:

- pemasangan di VPS dengan Traefik
- isi `.env`
- backup harian
- update dan pemulihan
- keamanan

Ringkasnya:

```bash
docker compose -f compose.yml -f compose.prod.yml build
docker compose -f compose.yml -f compose.prod.yml run --rm --no-deps bot alembic upgrade head
docker compose -f compose.yml -f compose.prod.yml up -d
```

Token Plurk untuk akun bot dibuat lewat [Plurk App](https://www.plurk.com/PlurkApp/) dan disimpan di `.env`, yang tidak pernah di-commit.

## Keamanan & data

Repo ini publik. Kredensial (`.env*`), bank soal asli, database, dan backup **tidak pernah** masuk Git maupun image Docker.
Contoh di repo hanya memakai soal karangan. Jika menemukan masalah keamanan, laporkan secara privat ke pemilik repo,
bukan lewat issue publik.

## Dokumentasi pengembang

Spesifikasi lengkap ada di [`CLAUDE.md`](CLAUDE.md): aturan permainan, mekanik thread, skema database, keputusan per tahap, dan tes wajib.

## Lisensi

[MIT](LICENSE). Lisensi ini hanya berlaku untuk kode di repo ini, tidak termasuk bank soal asli, yang memang tidak dipublikasikan.
