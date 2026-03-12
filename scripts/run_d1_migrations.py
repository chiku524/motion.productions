#!/usr/bin/env python3
"""
Run D1 migrations for motion.productions (current and any future migrations).
Works on all platforms (no bash required). Uses wrangler from the cloudflare/ directory.

Retries on D1 CPU limit (7429) or transient errors with exponential backoff.

Usage:
  python scripts/run_d1_migrations.py           # apply to remote
  python scripts/run_d1_migrations.py --local   # apply to local D1 (development)
"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_DIR = REPO_ROOT / "cloudflare"
DB_NAME = "motion-productions-db"

# Retry on D1 CPU limit (7429) or timeouts; give DB time to recover
MAX_ATTEMPTS = 5
INITIAL_DELAY_SEC = 30
BACKOFF_MULTIPLIER = 1.5


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run D1 migrations (current and future). Run from repo root."
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="Apply migrations to local D1 (development). Default is remote.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=MAX_ATTEMPTS,
        help=f"Max migration attempts on failure (default {MAX_ATTEMPTS}).",
    )
    args = parser.parse_args()

    if not (CLOUDFLARE_DIR / "wrangler.jsonc").exists():
        print("Error: cloudflare/wrangler.jsonc not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    target = "--local" if args.local else "--remote"
    delay = INITIAL_DELAY_SEC
    last_result = None

    for attempt in range(1, args.max_attempts + 1):
        if attempt > 1:
            print(f"Migration attempt {attempt} of {args.max_attempts}...")
        else:
            print(f"Applying D1 migrations ({target}) from {CLOUDFLARE_DIR} ...")

        result = subprocess.run(
            ["npx", "wrangler", "d1", "migrations", "apply", DB_NAME, target],
            cwd=CLOUDFLARE_DIR,
            shell=sys.platform == "win32",
        )
        last_result = result

        if result.returncode == 0:
            print("Done.")
            return

        # D1 CPU limit (7429) or transient: back off and retry
        print(
            f"D1 migration failed (exit {result.returncode}), waiting {int(delay)}s before retry...",
            file=sys.stderr,
        )
        time.sleep(delay)
        delay = min(300, delay * BACKOFF_MULTIPLIER)

    print("Migrations failed after {} attempts.".format(args.max_attempts), file=sys.stderr)
    sys.exit(last_result.returncode if last_result is not None else 1)


if __name__ == "__main__":
    main()
