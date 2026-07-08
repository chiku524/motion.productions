#!/usr/bin/env python3
"""
Process dispatcher for container deployments: selects the loop script from WORKER_START_SCRIPT.

Dockerfile CMD runs this entrypoint. Set per service:

  - WORKER_START_SCRIPT=sound_loop          → python scripts/sound_loop.py
  - WORKER_START_SCRIPT=interpret_loop      → python scripts/interpret_loop.py
  - WORKER_START_SCRIPT=generate_bridge     → python scripts/generate_bridge.py --learn
  - WORKER_START_SCRIPT=procedural_render   → python scripts/procedural_render_server.py
  - unset or automate_loop (default)        → python scripts/automate_loop.py

Usage: python scripts/worker_start.py
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = (os.environ.get("WORKER_START_SCRIPT") or "automate_loop").strip().lower()

extra_args: list[str] = []

if SCRIPT == "sound_loop":
    script_path = ROOT / "scripts" / "sound_loop.py"
elif SCRIPT == "interpret_loop":
    script_path = ROOT / "scripts" / "interpret_loop.py"
elif SCRIPT in ("generate_bridge", "webjobs", "bridge"):
    script_path = ROOT / "scripts" / "generate_bridge.py"
    if (os.environ.get("BRIDGE_LEARN") or "1").strip() not in ("0", "false", "False"):
        extra_args.append("--learn")
    interval = (os.environ.get("BRIDGE_INTERVAL_SECONDS") or "").strip()
    if interval.isdigit():
        extra_args.extend(["--interval", interval])
    api_base = (os.environ.get("API_BASE") or "").strip()
    if api_base:
        extra_args.extend(["--api-base", api_base])
elif SCRIPT in ("procedural_render", "procedural-render", "render"):
    script_path = ROOT / "scripts" / "procedural_render_server.py"
else:
    script_path = ROOT / "scripts" / "automate_loop.py"

if not script_path.exists():
    print(f"worker_start: script not found: {script_path}", file=sys.stderr)
    sys.exit(1)

os.execv(sys.executable, [sys.executable, str(script_path)] + extra_args + sys.argv[1:])
