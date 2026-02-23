#!/usr/bin/env python3
"""
Railway start dispatcher: run the correct script based on RAILWAY_START_SCRIPT.

railway.toml uses a single startCommand for all services. Set this env var per service:
  - RAILWAY_START_SCRIPT=sound_loop     → python scripts/sound_loop.py (Sound workflow)
  - RAILWAY_START_SCRIPT=interpret_loop → python scripts/interpret_loop.py (Interpretation)
  - unset or automate_loop (default)   → python scripts/automate_loop.py (Explorer/Exploiter/Balanced)

Usage: python scripts/railway_start.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (os.environ.get("RAILWAY_START_SCRIPT") or "automate_loop").strip().lower()

if SCRIPT == "sound_loop":
    script_path = ROOT / "scripts" / "sound_loop.py"
elif SCRIPT == "interpret_loop":
    script_path = ROOT / "scripts" / "interpret_loop.py"
else:
    script_path = ROOT / "scripts" / "automate_loop.py"

if not script_path.exists():
    print(f"railway_start: script not found: {script_path}", file=sys.stderr)
    sys.exit(1)

# Replace this process with the target script (no wrapper left in process tree)
os.execv(sys.executable, [sys.executable, str(script_path)] + sys.argv[1:])
