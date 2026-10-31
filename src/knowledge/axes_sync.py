"""Budgeted sync of opacity-plane and cross-axis coverage COUNTS to D1 (table axis_coverage, migration 0104).

Off unless LOOP_AXES_SYNC=1. At most one sync per AXES_SYNC_INTERVAL_S (default 6 h) across all containers (shared
state file + lock on the knowledge volume). Only keys whose (seen, universe) changed since the last acknowledged sync
are sent, so a quiet day costs 0 rows and the worst case is 32 rows per sync (~128/day at the default interval).
Booked to the ``survey`` ledger bucket (write_budget.budget_for_path). Never raises.
"""
from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Callable

from .color_cells import _FileLock, atomic_write_bytes

logger = logging.getLogger(__name__)

PUSH_PATH = "/api/coverage/axes"
TABLE_MISSING_BACKOFF_S = 24 * 3600
MAX_KEYS = 32


def enabled() -> bool:
    return (os.environ.get("LOOP_AXES_SYNC") or "").strip().lower() in ("1", "true", "yes")


def interval_s() -> float:
    try:
        return max(600.0, float(os.environ.get("AXES_SYNC_INTERVAL_S") or 6 * 3600))
    except ValueError:
        return 6 * 3600.0


def state_dir() -> Path:
    from .cross_axis import default_dir

    return default_dir()


def collect(opacity_counts: dict | None, cross_report: dict | None) -> dict[str, tuple[int, int]]:
    """{key: (seen, universe)} for the Worker's allow-listed keys."""
    out: dict[str, tuple[int, int]] = {}
    if opacity_counts:
        size = int(opacity_counts.get("size") or 0)
        out["opacity.total"] = (int(opacity_counts.get("covered") or 0), size)
        levels = list(opacity_counts.get("per_alpha_level") or [])
        per = size // len(levels) if levels else 0
        for i, n in enumerate(levels[:16]):
            out[f"opacity.level.{i}"] = (int(n), per)
    for key, p in ((cross_report or {}).get("pairs") or {}).items():
        out[f"pair.{key}"] = (int(p.get("seen") or 0), int(p.get("universe") or 0))
    return out


def _load(path: Path) -> dict:
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def maybe_sync(api_base: str, *, now: float | None = None, post: Callable[..., Any] | None = None,
               counts: dict[str, tuple[int, int]] | None = None, directory: Path | None = None) -> dict:
    t = time.time() if now is None else now
    try:
        if not enabled():
            return {"status": "disabled"}
        if not api_base:
            return {"status": "no_api"}
        d = Path(directory) if directory else state_dir()
        d.mkdir(parents=True, exist_ok=True)
        lock = _FileLock(d / "axes_sync.lock", timeout=0.2, stale=900.0)
        try:
            lock.__enter__()
        except TimeoutError:
            return {"status": "busy"}
        try:
            return _locked(api_base, t, post, counts, d)
        finally:
            lock.__exit__(None, None, None)
    except Exception as e:
        logger.warning("axes sync failed: %s", e)
        return {"status": "error", "error": str(e)[:200]}


def _locked(api_base, t, post, counts, d: Path) -> dict:
    sp = d / "axes_sync_state.json"
    st = _load(sp)
    if t < float(st.get("backoff_until") or 0):
        return {"status": "backoff", "reason": st.get("backoff_reason")}
    if t - float(st.get("last_attempt") or 0) < interval_s():
        return {"status": "not_due"}
    if post is None:
        from ..api_client import api_post, free_tier_cooldown_remaining

        if free_tier_cooldown_remaining() > 0:
            return {"status": "cooldown"}
        post = api_post
    if counts is None:
        from .cross_axis import CrossAxisTracker
        from .opacity_plane import OpacityPlane

        counts = collect(OpacityPlane().counts(), CrossAxisTracker(d).report())
    sent = st.get("sent") or {}
    changed = [{"key": k, "seen": s, "universe": u} for k, (s, u) in sorted(counts.items())
               if sent.get(k) != [s, u]][:MAX_KEYS]
    st["last_attempt"] = t
    if not changed:
        atomic_write_bytes(sp, json.dumps(st).encode("utf-8"))
        return {"status": "nothing_changed"}
    out: dict = {"status": "synced", "items": len(changed)}
    try:
        res = post(api_base, PUSH_PATH, {"items": changed}, timeout=60)
        if isinstance(res, dict) and res.get("recorded") is True:
            for it in changed:
                sent[it["key"]] = [it["seen"], it["universe"]]
            st["sent"] = sent
            out["rows_written"] = int(res.get("rows_written") or 0)
        elif isinstance(res, dict) and res.get("reason") == "table_missing":
            st["backoff_until"], st["backoff_reason"] = t + TABLE_MISSING_BACKOFF_S, "table_missing"
            out["status"] = "table_missing"
        else:
            out["status"] = "not_recorded"
    except Exception as e:
        out["status"], out["error"] = "error", str(e)[:200]
    atomic_write_bytes(sp, json.dumps(st).encode("utf-8"))
    return out
