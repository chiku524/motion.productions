"""Cross-axis coverage tracking (first slice, local only).

Per-axis registries say which colours, motions, sounds... exist; they do not say which COMBINATIONS have been made.
This records, per clip, the pairwise combinations of a few spec axes and reports, for each axis pair, how many
distinct combinations were seen against the product of the distinct values seen on each axis (an honest "observed
universe" denominator: it grows as the axes grow, it is not a fixed target).

Stored as ``<dir>/cross_axis.json`` (pair -> sorted list of "a|b" strings, capped per pair); no D1 writes.
Opt-in with ``LOOP_CROSS_AXIS=1``.
"""
from __future__ import annotations

import itertools
import json
import os
from pathlib import Path
from typing import Any

from .color_cells import _FileLock, atomic_write_bytes

AXES = ("palette_name", "motion_type", "camera_motion", "lighting_preset", "audio_mood", "genre")
PAIR_CAP = 50_000


def enabled() -> bool:
    return (os.environ.get("LOOP_CROSS_AXIS") or "").strip().lower() in ("1", "true", "yes")


def default_dir() -> Path:
    base = os.environ.get("CROSS_AXIS_DIR") or os.path.join(os.environ.get("KNOWLEDGE_DIR", "knowledge"), "cross_axis")
    return Path(base)


def axis_values(spec: Any) -> dict[str, str]:
    out: dict[str, str] = {}
    for a in AXES:
        v = spec.get(a) if isinstance(spec, dict) else getattr(spec, a, None)
        if v is not None and str(v).strip():
            out[a] = str(v).strip().lower()
    return out


class CrossAxisTracker:
    def __init__(self, directory: Path | str | None = None):
        self.dir = Path(directory) if directory else default_dir()
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "cross_axis.json"
        self._lock = self.dir / "cross_axis.lock"

    def _load(self) -> dict[str, Any]:
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(d, dict):
                return d
        except (OSError, ValueError):
            pass
        return {"values": {}, "pairs": {}, "clips": 0}

    def record(self, spec: Any) -> dict[str, int]:
        """Add one clip's axis values; returns {pair: new combinations}."""
        vals = axis_values(spec)
        new: dict[str, int] = {}
        with _FileLock(self._lock):
            d = self._load()
            for a, v in vals.items():
                s = set(d["values"].get(a, []))
                s.add(v)
                d["values"][a] = sorted(s)
            for a, b in itertools.combinations(sorted(vals), 2):
                key = f"{a}x{b}"
                s = set(d["pairs"].get(key, []))
                combo = f"{vals[a]}|{vals[b]}"
                if combo not in s and len(s) < PAIR_CAP:
                    s.add(combo)
                    new[key] = 1
                d["pairs"][key] = sorted(s)
            d["clips"] = int(d.get("clips", 0)) + 1
            atomic_write_bytes(self.path, json.dumps(d, separators=(",", ":")).encode("utf-8"))
        return new

    def report(self) -> dict[str, Any]:
        d = self._load()
        vals = {a: len(v) for a, v in d["values"].items()}
        pairs = {}
        for key, combos in d["pairs"].items():
            a, b = key.split("x", 1)
            universe = vals.get(a, 0) * vals.get(b, 0)
            pairs[key] = {"seen": len(combos), "universe": universe,
                          "pct": round(100.0 * len(combos) / universe, 2) if universe else 0.0}
        least = sorted(pairs.items(), key=lambda kv: kv[1]["pct"])[:3]
        return {"clips": d.get("clips", 0), "axis_values": vals, "pairs": pairs, "least_covered": [k for k, _ in least]}

    def missing_combinations(self, a: str, b: str, limit: int = 20) -> list[tuple[str, str]]:
        """Combinations of already-seen values never made together: candidates for a cross-axis queue."""
        d = self._load()
        a, b = sorted((a, b))
        seen = set(d["pairs"].get(f"{a}x{b}", []))
        out = []
        for va in d["values"].get(a, []):
            for vb in d["values"].get(b, []):
                if f"{va}|{vb}" not in seen:
                    out.append((va, vb))
                    if len(out) >= limit:
                        return out
        return out
