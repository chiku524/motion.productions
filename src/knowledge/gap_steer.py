"""Gap-steered prompt selection (opt-in, local, no D1 reads or writes).

Biases the explorer / balanced prompt toward what has not been made yet, while keeping some randomness:

* colour: the hue family with the most UNCOVERED exact cells in the local colour bitset (estimated from a fixed
  random sample of cell ids, so it costs ~ms, not a 16M-cell scan), drawn with weights = uncovered share, or for a
  worker with the stride queue (LOOP_COLOR_QUEUE=1) the family of its next unseen stride cell;
* cross-axis: one never-made pair of already-seen axis values (cross_axis.json), appended as prompt phrases.

Flags: ``LOOP_GAP_STEER=1`` enables; ``LOOP_GAP_STEER_P`` (default 0.7) is the chance a clip is steered (the rest stay
on the existing random/underfill pick); ``LOOP_GAP_STEER_PAIR_P`` (default 0.5) the chance a steered clip also gets a
missing cross-axis pair. Every failure falls back to ``None`` (unsteered).
"""
from __future__ import annotations

import os
import time
from typing import Any, Callable

import numpy as np

SAMPLE_N = 8192
REFRESH_S = 600.0
PAIR_PREFERENCE = ("palette_namexmotion_type", "camera_motionxpalette_name", "audio_moodxlighting_preset",
                   "lighting_presetxpalette_name", "audio_moodxmotion_type")

_cache: dict[str, Any] = {"t": 0.0, "weights": None}


def _f(name: str, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(os.environ.get(name, default))))
    except (TypeError, ValueError):
        return default


def enabled() -> bool:
    return (os.environ.get("LOOP_GAP_STEER") or "").strip().lower() in ("1", "true", "yes")


def family_gap_weights(plane: np.ndarray, *, sample_n: int = SAMPLE_N, seed: int = 1729) -> dict[str, float]:
    """Estimated uncovered cells per hue family (share of the sample), from a packed 2^24-bit plane."""
    from .color_cells import bits_test, id_to_rgb
    from .mission_targets import classify_color_family_rgb

    rng = np.random.default_rng(seed)
    ids = rng.integers(0, 1 << 24, size=sample_n, dtype=np.int64)
    seen = bits_test(plane, ids)
    out: dict[str, float] = {}
    for cid, s in zip(ids.tolist(), seen.tolist()):
        if s:
            continue
        fam = classify_color_family_rgb(*id_to_rgb(int(cid)))
        out[fam] = out.get(fam, 0.0) + 1.0
    total = sum(out.values())
    return {k: v / total for k, v in out.items()} if total else {}


def _covered_plane() -> np.ndarray | None:
    from .color_cells import ColorCellStore

    st = ColorCellStore()
    p = st.planes["observed"] | st.planes["verified"] | st.planes["declared"]
    return p


def gap_family(rand: Callable[[], float], *, plane_loader: Callable[[], np.ndarray | None] = _covered_plane,
               now: float | None = None) -> str | None:
    now = time.time() if now is None else now
    w = _cache.get("weights")
    if w is None or now - float(_cache.get("t") or 0) > REFRESH_S:
        plane = plane_loader()
        w = family_gap_weights(plane) if plane is not None else {}
        _cache.update(t=now, weights=w)
    if not w:
        return None
    r, acc = rand() * sum(w.values()), 0.0
    for fam, v in sorted(w.items()):
        acc += v
        if r <= acc:
            return fam
    return sorted(w)[-1]


def gap_pair(rand: Callable[[], float], tracker: Any = None) -> tuple[str, str, str] | None:
    """(pair key, value a, value b) never made together, or None."""
    from .cross_axis import CrossAxisTracker

    t = tracker or CrossAxisTracker()
    keys = list(PAIR_PREFERENCE)
    start = int(rand() * len(keys)) % len(keys)
    for i in range(len(keys)):
        key = keys[(start + i) % len(keys)]
        a, b = key.split("x", 1)
        miss = t.missing_combinations(a, b, limit=64)
        if miss:
            va, vb = miss[int(rand() * len(miss)) % len(miss)]
            return key, va, vb
    return None


def steer(rand: Callable[[], float], *, use_queue: bool = False, plane_loader: Callable[[], np.ndarray | None] = _covered_plane,
          tracker: Any = None) -> dict[str, Any] | None:
    """Return {"family": str|None, "phrases": [..], "pair": key|None} for a steered clip, or None (unsteered)."""
    if not enabled() or rand() >= _f("LOOP_GAP_STEER_P", 0.7):
        return None
    out: dict[str, Any] = {"family": None, "phrases": [], "pair": None}
    try:
        if not use_queue:  # a stride-queue worker already targets its next unseen exact cell
            out["family"] = gap_family(rand, plane_loader=plane_loader)
    except Exception:
        out["family"] = None
    try:
        if rand() < _f("LOOP_GAP_STEER_PAIR_P", 0.5):
            gp = gap_pair(rand, tracker)
            if gp:
                out["pair"] = gp[0]
                out["phrases"] = [gp[1].replace("_", " "), gp[2].replace("_", " ")]
    except Exception:
        out["pair"], out["phrases"] = None, []
    if not out["family"] and not out["phrases"]:
        return None
    return out
