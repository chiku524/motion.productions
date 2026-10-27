"""
Sound v2 (sound.L1) local store, per-clip recorder and unseen-cell sampler.

The store (registry/static/static_sound_v2.json) keeps one entry per cell that was measured OR aimed at:
  count     clips in which the extractor measured the cell (0 = attempted only)
  attempts  closed-loop renders that aimed at the cell (used to deprioritise cells the synth cannot hit)
  evidence_tier observed (measured once) / verified (hit its own target, or re-observed in another clip)

Nothing here fabricates coverage: only keys the extractor measured from a decoded clip are recorded.
Sync cost is bounded: at most SOUND_V2_MAX_PER_CLIP payloads leave per clip, as ordinary ``static_sound``
rows with an ``s2.`` key (no new table, no migration), and remote_sync drops them before it would ever
add a POST. See docs/EXHAUSTIVE_REGISTRY_PLAN.md.
"""
from __future__ import annotations

import os
import random
from typing import Any, Iterable

from . import keyspace as K
from .evidence import OBSERVED, VERIFIED, best_tier, covers, normalize_tier

STORE = "sound_v2"
DEFAULT_MAX_PER_CLIP = 6
# After this many aimed renders without a measured hit a cell is treated as (probably) unreachable by the synth.
UNREACHABLE_AFTER = 8
UNREACHABLE_WEIGHT = 0.02


def max_per_clip() -> int:
    raw = os.environ.get("SOUND_V2_MAX_PER_CLIP", "")
    try:
        n = int(raw) if raw.strip() else DEFAULT_MAX_PER_CLIP
    except ValueError:
        n = DEFAULT_MAX_PER_CLIP
    return max(0, min(n, 20))


def _load(config: dict[str, Any] | None) -> dict[str, Any]:
    from .static_registry import load_static_registry

    data = load_static_registry(STORE, config)
    data.setdefault("entries", [])
    return data


def _save(data: dict[str, Any], config: dict[str, Any] | None) -> None:
    from .static_registry import save_static_registry

    data["count"] = sum(1 for e in data["entries"] if int(e.get("count") or 0) > 0)
    save_static_registry(STORE, data, config)


def _index(data: dict[str, Any]) -> dict[int, dict[str, Any]]:
    return {int(e["ordinal"]): e for e in data["entries"] if "ordinal" in e}


def _entry(idx: dict[int, dict[str, Any]], data: dict[str, Any], ordinal: int) -> dict[str, Any]:
    e = idx.get(ordinal)
    if e is None:
        e = {
            "key": K.sound_v2_ordinal_to_key(ordinal),
            "ordinal": ordinal,
            "cell_id": K.sound_v2_cell_id(ordinal),
            "count": 0,
            "attempts": 0,
            "evidence_tier": "declared",
            "synced": False,
        }
        idx[ordinal] = e
        data["entries"].append(e)
    return e


def _payload(e: dict[str, Any], source_prompt: str) -> dict[str, Any]:
    key = e["key"]
    summary = K.sound_v2_cell_summary(key)
    summary["tier"] = e.get("evidence_tier", OBSERVED)
    amp = float(e.get("amplitude") or 0.0)
    if e.get("peak_hz") is not None:
        summary["peak_hz"] = round(float(e["peak_hz"]), 1)
    bins = summary["bins"]
    return {
        "key": key,
        "name": e["cell_id"],
        "amplitude": round(amp, 5),
        "weight": round(amp, 5),
        "strength_pct": round(min(1.0, amp) * 100.0, 2),
        "tone": f"band{bins['band']}",
        "timbre": K.SOUND_V2_FLAT_LABELS[bins["flat"]],
        "depth_breakdown": summary,
        "evidence_tier": e.get("evidence_tier", OBSERVED),
        "v2_key": key,
        "v2_cell": e["cell_id"],
        "source_prompt": (source_prompt or "sound_v2")[:80],
    }


def record_clip_cells(
    segments: Iterable[dict[str, Any]],
    *,
    config: dict[str, Any] | None = None,
    source_prompt: str = "",
    targets: Iterable[int] | None = None,
    max_payloads: int | None = None,
) -> dict[str, Any]:
    """Record the v2 cells MEASURED in one decoded clip (one observation per distinct cell per clip).

    targets: ordinals the render aimed at. A target measured in the decoded clip is VERIFIED (closed loop);
    an already observed cell seen again in a later clip is VERIFIED too (independent re-observation).
    Returns {"cells": {key: tier}, "new": n, "payloads": [...]} - payloads are capped per clip.
    """
    seen: dict[int, dict[str, Any]] = {}
    for seg in segments or []:
        key = seg.get("v2_key") or K.sound_v2_from_segment(seg)
        if not key or not K.is_sound_v2_key(key):
            continue
        o = K.sound_v2_key_to_ordinal(key)
        cur = seen.setdefault(o, {"n": 0, "seg": seg})
        cur["n"] += 1
    if not seen:
        return {"cells": {}, "new": 0, "payloads": []}
    target_set = {int(t) for t in (targets or [])}
    data = _load(config)
    idx = _index(data)
    cells: dict[str, str] = {}
    new = 0
    for o, info in sorted(seen.items()):
        e = _entry(idx, data, o)
        prior = int(e.get("count") or 0)
        obs = VERIFIED if o in target_set else OBSERVED
        if prior > 0 and obs == OBSERVED:
            obs = VERIFIED  # independent re-observation in a different clip
        e["count"] = prior + 1
        e["evidence_tier"] = best_tier(e.get("evidence_tier") if prior > 0 else "declared", obs)
        if prior == 0:
            new += 1
            seg = info["seg"]
            e["amplitude"] = float(seg.get("amplitude") if seg.get("amplitude") is not None else seg.get("weight") or 0.0)
            if seg.get("peak_hz") is not None:
                e["peak_hz"] = float(seg["peak_hz"])
            e["first_source"] = (source_prompt or "")[:80]
            e["synced"] = False
        cells[e["key"]] = e["evidence_tier"]
    cap = max_per_clip() if max_payloads is None else max(0, int(max_payloads))
    pending = sorted(
        (e for e in data["entries"] if int(e.get("count") or 0) > 0 and not e.get("synced") and covers(e.get("evidence_tier"))),
        key=lambda e: int(e["ordinal"]),
    )[:cap]
    payloads = []
    for e in pending:
        payloads.append(_payload(e, e.get("first_source") or source_prompt))
        e["synced"] = True
    _save(data, config)
    return {"cells": cells, "new": new, "payloads": payloads}


def note_attempts(ordinals: Iterable[int], config: dict[str, Any] | None = None) -> None:
    """Count a closed-loop render that aimed at these cells (hit or miss)."""
    ords = list(dict.fromkeys(int(o) for o in ordinals))
    if not ords:
        return
    data = _load(config)
    idx = _index(data)
    for o in ords:
        e = _entry(idx, data, o)
        e["attempts"] = int(e.get("attempts") or 0) + 1
    _save(data, config)


def covered_ordinals(config: dict[str, Any] | None = None) -> set[int]:
    data = _load(config)
    return {int(e["ordinal"]) for e in data["entries"] if int(e.get("count") or 0) > 0 and covers(e.get("evidence_tier"))}


def decode_bitmap(hex_str: Any, size: int = K.SOUND_V2_SPACE_SIZE) -> set[int]:
    """Ordinals set in the Worker's compact seen-cell bitmap (hex, bit i = ordinal i)."""
    if not isinstance(hex_str, str) or not hex_str:
        return set()
    try:
        n = int(hex_str, 16)
    except ValueError:
        return set()
    return {i for i in range(size) if (n >> i) & 1}


def encode_bitmap(ordinals: Iterable[int], size: int = K.SOUND_V2_SPACE_SIZE) -> str:
    n = 0
    for o in ordinals:
        if 0 <= int(o) < size:
            n |= 1 << int(o)
    return format(n, "x").zfill((size + 3) // 4)


def pick_unseen_cells(
    n: int,
    *,
    config: dict[str, Any] | None = None,
    mission: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> list[int]:
    """Sample up to n distinct v2 cells nobody has seen yet (local store + the Worker's seen bitmap).

    Weight = 1/(1+attempts): untried cells first. After UNREACHABLE_AFTER misses a cell is almost never
    drawn again, so the synth stops burning clips on physically inconsistent cells but is never locked out.
    """
    rng = rng or random.Random()
    seen = covered_ordinals(config)
    v2 = (mission or {}).get("sound_v2") or {}
    seen |= decode_bitmap(v2.get("seen_bitmap"))
    data = _load(config)
    attempts = {int(e["ordinal"]): int(e.get("attempts") or 0) for e in data["entries"] if "ordinal" in e}
    pool = [o for o in range(K.SOUND_V2_SPACE_SIZE) if o not in seen]
    if not pool or n <= 0:
        return []
    weights = []
    for o in pool:
        a = attempts.get(o, 0)
        w = 1.0 / (1.0 + a)
        if a >= UNREACHABLE_AFTER:
            w = UNREACHABLE_WEIGHT
        weights.append(w)
    out: list[int] = []
    for _ in range(min(n, len(pool))):
        i = rng.choices(range(len(pool)), weights=weights, k=1)[0]
        out.append(pool[i])
        pool.pop(i)
        weights.pop(i)
    return out


def coverage_stats(config: dict[str, Any] | None = None) -> dict[str, Any]:
    data = _load(config)
    by = {"observed": 0, "verified": 0}
    attempted_unseen = 0
    for e in data["entries"]:
        if int(e.get("count") or 0) > 0:
            t = normalize_tier(e.get("evidence_tier"), OBSERVED)
            if t in by:
                by[t] += 1
        elif int(e.get("attempts") or 0) > 0:
            attempted_unseen += 1
    covered = by["observed"] + by["verified"]
    return {
        "space": "sound.L1",
        "space_size": K.SOUND_V2_SPACE_SIZE,
        "covered": covered,
        "by_tier": by,
        "attempted_unseen": attempted_unseen,
        "coverage_pct": round(100.0 * covered / K.SOUND_V2_SPACE_SIZE, 3),
    }