#!/usr/bin/env python3
"""
Run D1 migrations for motion.productions (current and any future migrations).
Works on all platforms (no bash required). Uses wrangler from the cloudflare/ directory.

Retries on D1 CPU limit (7429) or transient errors with exponential backoff.

No-op migrations whose only statement is `SELECT 1` (comments allowed) skip **remote D1 execute**
entirely: only `d1_migrations` is updated. On very large DBs, even `SELECT 1` via Wrangler can hit CPU 7429;
`learned_dynamic_meta` DDL is handled by the Worker (`ensureLearnedDynamicMetaTable`).

Usage:
  python scripts/run_d1_migrations.py           # apply to remote (batch)
  python scripts/run_d1_migrations.py --local   # apply to local D1 (development)
  python scripts/run_d1_migrations.py --one-by-one --remote   # apply one migration at a time with long pauses (avoids CPU limit on large tables)
  python scripts/run_d1_migrations.py --one-by-one --remote --only 0018_learned_temporal_depth.sql,0019_learned_technical_depth.sql
      # apply only these files (skips wrangler batch apply — use when batch fails 7429 on an earlier pending migration)

  # "duplicate column" on apply: schema already matches but d1_migrations has no row — record without running ALTER:
  python scripts/run_d1_migrations.py --remote --record-applied-only 0012_1_static_colors_depth.sql
  python scripts/run_d1_migrations.py --remote --record-depth-breakdown-preset
      # records nine 0012_/0016_ files; use only if those columns already exist, then apply 0020 (batch or --only).
  python scripts/run_d1_migrations.py --remote --record-depth-breakdown-preset --record-delay 120 --max-attempts 8
      # large remote D1 may return 7429 between INSERTs; increase delay and retries.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CLOUDFLARE_DIR = REPO_ROOT / "cloudflare"
MIGRATIONS_DIR = CLOUDFLARE_DIR / "migrations"
DB_NAME = "motion-productions-db"

DEPTH_BREAKDOWN_PRESET: tuple[str, ...] = (
    "0012_1_static_colors_depth.sql",
    "0012_2b_static_sound_strength.sql",
    "0012_2_static_sound_depth.sql",
    "0012_3_narrative_depth.sql",
    "0012_4_learned_audio_depth.sql",
    "0016_1_learned_motion_depth.sql",
    "0016_2_learned_gradient_depth.sql",
    "0016_3_learned_camera_depth.sql",
    "0016_4_learned_lighting_depth.sql",
)


# Retry on D1 CPU limit (7429) or timeouts; give DB time to recover
MAX_ATTEMPTS = 5
INITIAL_DELAY_SEC = 30
BACKOFF_MULTIPLIER = 1.5

# One-by-one: pause between each migration so D1 can recover (large ALTERs can hit CPU limit)
ONE_BY_ONE_DELAY_SEC = 120

# After each successful d1_migrations INSERT (record-applied-only); large D1 often needs 60–120s+
RECORD_APPLIED_DELAY_SEC = 90


def _migration_body_without_line_comments(sql: str) -> str:
    """Strip full-line -- comments; strip trailing -- on a line."""
    out_lines: list[str] = []
    for line in sql.splitlines():
        s = line.strip()
        if s.startswith("--"):
            continue
        if "--" in line:
            line = line[: line.index("--")]
        out_lines.append(line)
    return "\n".join(out_lines).strip()


def _migration_is_trivial_select_one(path: Path) -> bool:
    """
    True if the file is only SELECT 1 (optional semicolon), ignoring comments.
    Wrangler `d1 execute --file` uses a heavy import path that can hit D1 CPU 7429 on very
    large databases even for SELECT 1; `d1 execute --command` avoids that path.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    body = _migration_body_without_line_comments(text).rstrip(";").strip().upper()
    return body == "SELECT 1"


def _execute_migration_sql(target: str, path: Path) -> subprocess.CompletedProcess:
    """
    Run migration SQL via wrangler.
    Trivial `SELECT 1` no-ops: skip execute on remote/local when it would only touch bookkeeping —
    large remote D1 databases can return 7429 even for `SELECT 1` (file import or --command).
    """
    if _migration_is_trivial_select_one(path):
        if target == "--remote":
            print(
                "  (no-op migration: skip D1 execute on remote (avoids 7429 on very large DBs); "
                "recording d1_migrations only. Schema for 0018/0019 is Worker-managed.)",
            )
            return subprocess.CompletedProcess([], 0, "", "")
        print("  (no-op migration: using --command SELECT 1 for local D1)")
        return _run(
            [
                "npx",
                "wrangler",
                "d1",
                "execute",
                DB_NAME,
                target,
                "--command",
                "SELECT 1",
            ],
        )
    return _run(
        ["npx", "wrangler", "d1", "execute", DB_NAME, target, "--file", str(path)],
    )


def _run(cmd: list[str], capture: bool = False) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=CLOUDFLARE_DIR,
        shell=sys.platform == "win32",
        capture_output=capture,
        text=capture,
    )


def _get_applied_migrations(target: str) -> set[str]:
    """Return set of migration filenames already applied (from d1_migrations table)."""
    result = _run(
        [
            "npx", "wrangler", "d1", "execute", DB_NAME, target,
            "--command", "SELECT name FROM d1_migrations",
            "--json",
        ],
        capture=True,
    )
    if result.returncode != 0:
        return set()
    out = (result.stdout or "").strip()
    # Wrangler may mix stderr; try to find a JSON array or object
    for chunk in (out.split("\n"), [out]):
        for s in chunk:
            s = s.strip()
            if not s or s[0] not in "[{":
                continue
            try:
                data = json.loads(s)
                if isinstance(data, list):
                    results = []
                    for item in data:
                        results.extend((item or {}).get("results") or [])
                else:
                    results = (data or {}).get("results") or []
                names = {row.get("name") for row in results if row and row.get("name")}
                if names:
                    return names
            except (json.JSONDecodeError, TypeError):
                continue
    return set()


def _record_migration(name: str, target: str) -> bool:
    """Insert migration name into d1_migrations so wrangler considers it applied."""
    applied = _get_applied_migrations(target)
    if name in applied:
        print(f"  (already in d1_migrations: {name})")
        return True
    # SQLite single-quote escape: ' -> ''
    safe = name.replace("'", "''")
    # OR IGNORE: name may already exist if SELECT d1_migrations failed earlier but row was inserted before
    cmd = [
        "npx", "wrangler", "d1", "execute", DB_NAME, target,
        "--command", f"INSERT OR IGNORE INTO d1_migrations (name) VALUES ('{safe}')",
    ]
    result = _run(cmd)
    if result.returncode == 0:
        return True
    if name in _get_applied_migrations(target):
        print(f"  (record insert failed but {name} is present in d1_migrations - OK)", file=sys.stderr)
        return True
    return False


def run_one_by_one(
    target: str, delay_sec: int, start_after: str | None = None, allow_initial: bool = False
) -> int:
    """Apply each pending migration with wrangler d1 execute --file, then record it; pause between each."""
    all_files = sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)
    if not all_files:
        print("No migration files found.", file=sys.stderr)
        return 1
    applied = _get_applied_migrations(target)
    pending = [f for f in all_files if f.name not in applied]
    if start_after:
        pending = [f for f in pending if f.name > start_after]
    if not pending:
        print("No pending migrations.")
        return 0
    # Safeguard: if applied list was empty and we're about to run 0000_initial, avoid re-running on existing DB
    if not allow_initial and pending[0].name == "0000_initial.sql" and not applied:
        print(
            "No applied migrations found (d1_migrations query may have failed or returned no rows).",
            file=sys.stderr,
        )
        print(
            "Aborting to avoid re-running 0000_initial.sql on an existing DB. Options:",
            file=sys.stderr,
        )
        print(
            "  --start-after 0011_learned_gradient_camera.sql   # only run 0012_1 and later",
            file=sys.stderr,
        )
        print(
            "  --allow-initial   # if the DB is truly empty, run from 0000",
            file=sys.stderr,
        )
        return 1
    print(f"Applying {len(pending)} migration(s) one-by-one (delay {delay_sec}s between each)...")
    for i, path in enumerate(pending, 1):
        print(f"[{i}/{len(pending)}] {path.name} ...")
        result = _execute_migration_sql(target, path)
        if result.returncode != 0:
            print(f"Failed to apply {path.name}", file=sys.stderr)
            return result.returncode
        if not _record_migration(path.name, target):
            print(f"Applied {path.name} but failed to record in d1_migrations.", file=sys.stderr)
            return 1
        if i < len(pending):
            print(f"Waiting {delay_sec}s before next migration...")
            time.sleep(delay_sec)
    print("Done.")
    return 0


def run_record_applied_only(
    target: str,
    names: list[str],
    delay_between_sec: int,
    per_name_max_attempts: int,
) -> int:
    """INSERT migration names into d1_migrations without executing migration SQL."""
    to_process: list[str] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        if not name.endswith(".sql"):
            name = name + ".sql"
        path = MIGRATIONS_DIR / name
        if not path.is_file():
            print(f"Error: migration file not found: {path}", file=sys.stderr)
            return 1
        to_process.append(name)

    for i, name in enumerate(to_process, 1):
        if name in _get_applied_migrations(target):
            print(f"Skip [{i}/{len(to_process)}] (already in d1_migrations): {name}")
            continue
        print(f"Recording (no SQL execute) [{i}/{len(to_process)}]: {name}")
        attempt_delay = float(INITIAL_DELAY_SEC)
        ok = False
        for attempt in range(1, per_name_max_attempts + 1):
            if _record_migration(name, target):
                ok = True
                break
            if attempt < per_name_max_attempts:
                print(
                    f"  D1 record failed (attempt {attempt}/{per_name_max_attempts}); "
                    f"waiting {attempt_delay:.0f}s (e.g. CPU 7429 / transient)...",
                    file=sys.stderr,
                )
                time.sleep(attempt_delay)
                attempt_delay = min(300.0, attempt_delay * BACKOFF_MULTIPLIER)
        if not ok:
            print(f"Failed to record {name} after {per_name_max_attempts} attempts.", file=sys.stderr)
            return 1
        if i < len(to_process) and delay_between_sec > 0:
            print(f"Waiting {delay_between_sec}s before next record (cool down D1)...", file=sys.stderr)
            time.sleep(delay_between_sec)
    print("Done (d1_migrations updated). Next: run batch apply or --one-by-one --only 0020_....sql")
    return 0


def run_only_named(
    target: str,
    names: list[str],
    delay_sec: int,
) -> int:
    """Apply exactly the listed migration filenames (in order), if not already applied."""
    applied = _get_applied_migrations(target)
    to_run: list[Path] = []
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        if not name.endswith(".sql"):
            name = name + ".sql"
        path = MIGRATIONS_DIR / name
        if not path.is_file():
            print(f"Migration file not found: {path}", file=sys.stderr)
            return 1
        if name in applied:
            print(f"Skip (already applied): {name}")
            continue
        to_run.append(path)
    if not to_run:
        print("Nothing to apply (all listed migrations already applied or invalid names).")
        return 0
    print(f"Applying {len(to_run)} named migration(s) ({target}), delay {delay_sec}s between each...")
    for i, path in enumerate(to_run, 1):
        print(f"[{i}/{len(to_run)}] {path.name} ...")
        result = _execute_migration_sql(target, path)
        if result.returncode != 0:
            print(f"Failed to apply {path.name}", file=sys.stderr)
            return result.returncode
        if not _record_migration(path.name, target):
            print(f"Applied {path.name} but failed to record in d1_migrations.", file=sys.stderr)
            return 1
        if i < len(to_run):
            print(f"Waiting {delay_sec}s before next migration...")
            time.sleep(delay_sec)
    print("Done.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run D1 migrations (current and future). Run from repo root."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--local",
        action="store_true",
        help="Apply migrations to local D1 (development).",
    )
    group.add_argument(
        "--remote",
        action="store_true",
        help="Apply migrations to remote D1 (default).",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=MAX_ATTEMPTS,
        help=f"Max migration attempts on failure (default {MAX_ATTEMPTS}).",
    )
    parser.add_argument(
        "--one-by-one",
        action="store_true",
        help="Apply one migration file at a time with a long pause between each (avoids D1 CPU limit on large tables).",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=ONE_BY_ONE_DELAY_SEC,
        help=f"Seconds to wait between migrations when using --one-by-one (default {ONE_BY_ONE_DELAY_SEC}).",
    )
    parser.add_argument(
        "--start-after",
        type=str,
        metavar="NAME",
        help="One-by-one only: run only migrations whose filename is after NAME (e.g. 0011_learned_gradient_camera.sql).",
    )
    parser.add_argument(
        "--allow-initial",
        action="store_true",
        help="One-by-one only: allow running from 0000_initial.sql when no applied migrations are found.",
    )
    parser.add_argument(
        "--only",
        type=str,
        metavar="NAMES",
        help="Comma-separated migration filenames to apply (use with --one-by-one). Skips batch apply; "
        "only runs these files via d1 execute + d1_migrations insert. Example: 0018_....sql,0019_....sql",
    )
    parser.add_argument(
        "--record-applied-only",
        type=str,
        metavar="NAMES",
        help="Comma-separated migration filenames: INSERT into d1_migrations only (no SQL). "
        "Use when columns already exist but Wrangler still lists the file as pending.",
    )
    parser.add_argument(
        "--record-depth-breakdown-preset",
        action="store_true",
        help=f"Same as --record-applied-only for the nine depth migrations ({DEPTH_BREAKDOWN_PRESET[0]} …). "
        "Only use if production schema already includes those ALTERs.",
    )
    parser.add_argument(
        "--record-delay",
        type=int,
        default=RECORD_APPLIED_DELAY_SEC,
        metavar="SEC",
        help=f"Seconds to wait after each successful record-applied INSERT before the next (default {RECORD_APPLIED_DELAY_SEC}). "
        "Large remote D1 often needs 90–180 to avoid 7429.",
    )
    args = parser.parse_args()

    if not (CLOUDFLARE_DIR / "wrangler.jsonc").exists():
        print("Error: cloudflare/wrangler.jsonc not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    target = "--local" if args.local else "--remote"  # default is remote

    if args.record_depth_breakdown_preset:
        print(
            "Recording depth-breakdown preset (no SQL execute). "
            "Ensure production already has these columns or you will corrupt migration state.",
            file=sys.stderr,
        )
        sys.exit(
            run_record_applied_only(
                target,
                list(DEPTH_BREAKDOWN_PRESET),
                args.record_delay,
                args.max_attempts,
            )
        )

    if args.record_applied_only:
        names = [n.strip() for n in args.record_applied_only.split(",") if n.strip()]
        if not names:
            print("Error: --record-applied-only is empty.", file=sys.stderr)
            sys.exit(2)
        sys.exit(run_record_applied_only(target, names, args.record_delay, args.max_attempts))

    if args.only and not args.one_by_one:
        print("Error: --only requires --one-by-one.", file=sys.stderr)
        sys.exit(2)

    if args.one_by_one:
        if args.only:
            names = [n.strip() for n in args.only.split(",") if n.strip()]
            if not names:
                print("Error: --only is empty.", file=sys.stderr)
                sys.exit(2)
            sys.exit(run_only_named(target, names, args.delay))
        sys.exit(
            run_one_by_one(
                target,
                args.delay,
                start_after=args.start_after,
                allow_initial=args.allow_initial,
            )
        )

    delay = INITIAL_DELAY_SEC
    last_result = None

    for attempt in range(1, args.max_attempts + 1):
        if attempt > 1:
            print(f"Migration attempt {attempt} of {args.max_attempts}...")
        else:
            print(f"Applying D1 migrations ({target}) from {CLOUDFLARE_DIR} ...")

        result = _run(
            ["npx", "wrangler", "d1", "migrations", "apply", DB_NAME, target],
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
