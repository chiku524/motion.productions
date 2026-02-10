#!/usr/bin/env python3
"""
Run D1 migrations for motion.productions (current and any future migrations).
Works on all platforms (no bash required). Uses wrangler from the cloudflare/ directory.

Usage:
  python scripts/run_d1_migrations.py           # apply to remote
  python scripts/run_d1_migrations.py --local   # apply to local D1 (development)
"""
import argparse
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_DIR = REPO_ROOT / "cloudflare"
DB_NAME = "motion-productions-db"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run D1 migrations (current and future). Run from repo root."
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Apply migrations to local D1 (development). Default is remote.",
    )
    args = parser.parse_args()

    if not (CLOUDFLARE_DIR / "wrangler.jsonc").exists():
        print("Error: cloudflare/wrangler.jsonc not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    target = "--local" if args.local else "--remote"
    print(f"Applying D1 migrations ({target}) from {CLOUDFLARE_DIR} ...")
    result = subprocess.run(
        ["npx", "wrangler", "d1", "migrations", "apply", DB_NAME, target],
        cwd=CLOUDFLARE_DIR,
        shell=sys.platform == "win32",
    )
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("Done.")


if __name__ == "__main__":
    main()
