#!/usr/bin/env bash
# Backup harian database produksi (jalankan dari cron host, lihat docs/deploy.md).
#
#   BACKUP_DIR          folder backup di VPS              (default /var/backups/plurk-trivia-kuis)
#   BACKUP_KEEP_DAYS    simpan N hari di VPS & salinan    (default 14)
#   BACKUP_RCLONE       tujuan rclone, mis. "b2:kuis-backup/db"          (opsional)
#   BACKUP_RSYNC        tujuan rsync, mis. "user@nas:/backup/kuis/"      (opsional)
#
# Salinan di luar VPS WAJIB diisi salah satu (BACKUP_RCLONE / BACKUP_RSYNC) untuk produksi.
set -euo pipefail
cd "$(dirname "$0")/.."

BACKUP_DIR="${BACKUP_DIR:-/var/backups/plurk-trivia-kuis}"
BACKUP_KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
COMPOSE=(docker compose -f compose.yml -f compose.prod.yml)

mkdir -p "$BACKUP_DIR"
# Kontainer berjalan sebagai uid 1000 (user "app").
if [ "$(id -u)" = "0" ]; then chown 1000:1000 "$BACKUP_DIR"; fi

"${COMPOSE[@]}" run --rm --no-deps -T -v "$BACKUP_DIR:/backup" bot \
  python -m app.cli backup --ke /backup --simpan "$BACKUP_KEEP_DAYS"

kabari() { "${COMPOSE[@]}" run --rm --no-deps -T bot python -m app.cli kabari "$1" || true; }

if [ -n "${BACKUP_RCLONE:-}" ]; then
  rclone sync "$BACKUP_DIR" "$BACKUP_RCLONE" --include "kuis_*.db.gz" \
    || { kabari "Backup offsite (rclone) gagal"; exit 1; }
elif [ -n "${BACKUP_RSYNC:-}" ]; then
  rsync -a --delete --include "kuis_*.db.gz" --exclude "*" "$BACKUP_DIR/" "$BACKUP_RSYNC" \
    || { kabari "Backup offsite (rsync) gagal"; exit 1; }
else
  echo "PERINGATAN: BACKUP_RCLONE / BACKUP_RSYNC kosong; backup hanya ada di VPS." >&2
fi
echo "Backup selesai."
