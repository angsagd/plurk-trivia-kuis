#!/usr/bin/env bash
# Update produksi: git pull -> backup -> build -> migrasi -> up -d -> cek kesehatan.
# Ditolak selama jam sesi (11.00-23.00 WIB) di hari aktif, kecuali dengan --paksa.
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose -f compose.yml -f compose.prod.yml)

jam=$(TZ=Asia/Jakarta date +%H)
hari=$(TZ=Asia/Jakarta date +%u)  # 1=Senin ... 7=Minggu; libur: 2 (Selasa), 5 (Jumat)
if [ "${1:-}" != "--paksa" ] && [ "$hari" != 2 ] && [ "$hari" != 5 ] && [ "$jam" -ge 11 ] && [ "$jam" -lt 23 ]; then
  echo "Sekarang jam sesi di hari aktif. Update sebelum 11.00 / setelah 23.00 WIB, hari libur, atau pakai --paksa." >&2
  exit 1
fi

git pull --ff-only
scripts/backup.sh
"${COMPOSE[@]}" build
"${COMPOSE[@]}" run --rm --no-deps -T bot alembic upgrade head
"${COMPOSE[@]}" up -d --remove-orphans
echo "Menunggu healthcheck..."
sleep 30
"${COMPOSE[@]}" ps
