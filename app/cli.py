"""CLI: python -m app.cli <perintah>. Perintah lain (seed, tick, simulasi, ...) menyusul di tahap 2-3."""

import argparse
import sys
import urllib.request

from app.bot import heartbeat
from app.config import get_settings


def health(target: str) -> int:
    if target == "admin":
        try:
            with urllib.request.urlopen("http://127.0.0.1:8000/health", timeout=5) as r:
                ok = r.status == 200
        except OSError:
            ok = False
    else:
        ok = heartbeat.sehat(get_settings().data_dir)
    print("sehat" if ok else "tidak sehat")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.cli")
    sub = ap.add_subparsers(dest="perintah", required=True)
    p = sub.add_parser("health", help="cek kesehatan kontainer (dipakai healthcheck Docker)")
    p.add_argument("target", choices=["admin", "bot"])
    args = ap.parse_args(argv)
    if args.perintah == "health":
        return health(args.target)
    return 2


if __name__ == "__main__":
    sys.exit(main())
