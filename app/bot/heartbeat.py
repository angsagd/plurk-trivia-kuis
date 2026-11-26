"""Penanda tick terakhir untuk healthcheck.
Sementara berupa file di volume data; di tahap 2 diganti bot_state.last_tick_at.
Memakai jam nyata (bukan jam palsu) karena yang diukur: apakah proses masih hidup."""

import time
from pathlib import Path

NAMA_FILE = "bot_heartbeat"
BATAS_SEHAT_DETIK = 180


def tulis(data_dir: Path) -> None:
    path = data_dir / NAMA_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(str(time.time()))
    tmp.replace(path)


def umur_detik(data_dir: Path) -> float | None:
    try:
        return time.time() - float((data_dir / NAMA_FILE).read_text())
    except (OSError, ValueError):
        return None


def sehat(data_dir: Path) -> bool:
    umur = umur_detik(data_dir)
    return umur is not None and umur < BATAS_SEHAT_DETIK
