import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_cli_validator_file_contoh():
    r = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools" / "validasi_soal.py"),
            str(ROOT / "contoh" / "trivia_99_contoh.txt"),
        ],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Nama topik          : Contoh" in r.stdout and "Lolos (tanpa error) : 8" in r.stdout
