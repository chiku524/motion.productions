#!/usr/bin/env python3
"""
Process dispatcher for container deployments: selects the loop script from WORKER_START_SCRIPT.

Dockerfile CMD runs this entrypoint. Set per service:

  - WORKER_START_SCRIPT=sound_loop     → python scripts/sound_loop.py
  - WORKER_START_SCRIPT=interpret_loop → python scripts/interpret_loop.py
  - unset or automate_loop (default) → python scripts/automate_loop.py

Usage: python scripts/worker_start.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (os.environ.get("WORKER_START_SCRIPT") or "automate_loop").strip().lower()

if SCRIPT == "sound_loop":
    script_path = ROOT / "scripts" / "sound_loop.py"
elif SCRIPT == "interpret_loop":
    script_path = ROOT / "scripts" / "interpret_loop.py"
else:
    script_path = ROOT / "scripts" / "automate_loop.py"

if not script_path.exists():
    print(f"worker_start: script not found: {script_path}", file=sys.stderr)
    sys.exit(1)

os.execv(sys.executable, [sys.executable, str(script_path)] + sys.argv[1:])
