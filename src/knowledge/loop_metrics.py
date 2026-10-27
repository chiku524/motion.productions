"""
Per-container loop metrics: one small rotating JSONL file per loop container.

Each loop iteration that rendered a clip appends one record:

    {"ts": "...Z", "t": 1790000000, "name": "explorer", "workflow": "explorer", "focus": "frame",
     "job_id": "...", "outcome": "accepted|rejected|unchecked|error", "rerolls": 1,
     "new_cells": 3, "post_items": 36, "post_requests": 1, "write_requests": 6,
     "write_failed": 0, "elapsed_s": 14.2}

* ``outcome`` - ``accepted`` (passed the content-novelty gate), ``rejected`` (still a near-duplicate
  after every re-roll: not published, no discoveries posted), ``unchecked`` (novelty gate off or the
  fingerprint could not be computed), ``error`` (the iteration failed).
* ``rerolls`` - extra renders the gate asked for (attempts - 1).
* ``new_cells`` - registry values the clip's growth step newly observed.
* ``post_items`` / ``post_requests`` - discovery items / POSTs sent to /api/knowledge/discoveries.
* ``write_requests`` / ``write_failed`` - every non-GET API call attempt made during the iteration.

The file lives on the shared ``knowledge/`` volume and is size-capped: when it passes ``max_bytes`` it
is rotated to ``<file>.1`` (one generation kept), so a container never uses more than ~2 x max_bytes.
Summarise with ``python scripts/loop_metrics.py``. Logging never raises into the loop.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_MAX_BYTES = 512 * 1024  # ~2,500 records per generation
FILE_PREFIX = "loop_metrics_"


def metrics_enabled() -> bool:
    return os.environ.get("LOOP_METRICS", "1").strip().lower() not in ("0", "false", "off", "no")


def default_metrics_dir() -> Path:
    env = (os.environ.get("LOOP_METRICS_DIR") or "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent / "knowledge" / "metrics"


def metrics_name(workflow_type: str = "", extraction_focus: str = "") -> str:
    """Container label: LOOP_METRICS_NAME (set per compose service), else workflow[-focus]."""
    env = (os.environ.get("LOOP_METRICS_NAME") or "").strip()
    if env:
        return env
    parts = [p for p in (workflow_type, extraction_focus) if p]
    return "-".join(parts) or "loop"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:48] or "loop"


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, "") or default))
    except ValueError:
        return default


class LoopMetricsLog:
    """Append-only, size-capped JSONL writer. One writer per file (one per container)."""

    def __init__(self, directory: str | Path | None = None, name: str = "loop", max_bytes: int | None = None):
        self.dir = Path(directory) if directory else default_metrics_dir()
        self.name = _safe(name)
        self.max_bytes = max(1024, int(max_bytes or _env_int("LOOP_METRICS_MAX_BYTES", DEFAULT_MAX_BYTES)))
        self.path = self.dir / f"{FILE_PREFIX}{self.name}.jsonl"

    def log(self, **fields: Any) -> bool:
        record = {"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "t": int(time.time()), "name": self.name}
        record.update(fields)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self._rotate_if_needed()
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(json.dumps(record, separators=(",", ":"), default=str) + "\n")
            return True
        except Exception as e:  # metrics must never break the loop
            logger.debug("loop metrics write skipped: %s", e)
            return False

    def _rotate_if_needed(self) -> None:
        try:
            if self.path.stat().st_size < self.max_bytes:
                return
        except OSError:
            return
        os.replace(self.path, self.path.with_name(self.path.name + ".1"))