"""
Sound pairings from the static_sound registry — same idea as color pixel pairings.

Frames hold two named instants still. Windows rematch 3–4 sounds over ~1s.
Each loop picks a new combination from primitives + discoveries, not a genre catalog.
"""
from __future__ import annotations

import random
import secrets
import threading
import zlib
from collections import deque
from typing import Any

from ..knowledge.blend_depth import _TONE_TO_NOISE, SOUND_ORIGIN_PRIMITIVES

_PRIMITIVE_TONE = {
    "silence": "silent",
    "rumble": "low",
    "hum": "low",
    "thump": "low",
    "tone": "mid",
    "rustle": "mid",
    "whoosh": "mid",
    "hiss": "high",
    "click": "high",
    "drip": "high",
}


def primitive_sound_entry(name: str, *, amplitude: float = 0.55) -> dict[str, Any]:
    prim = (name or "tone").strip().lower()
    if prim not in SOUND_ORIGIN_PRIMITIVES:
        prim = "tone"
    return {
        "name": prim,
        "tone": _PRIMITIVE_TONE.get(prim, "mid"),
        "timbre": prim,
        "amplitude": amplitude,
        "count": 0,
    }


def _name_in_prompt(name: str, raw: str) -> bool:
    s = (name or "").strip().lower()
    if not s or len(s) < 3:
        return False
    if " " in s:
        return s in raw
    tokens = raw.replace(":", " ").replace(",", " ").replace(".", " ").split()
    return s in tokens


def sound_label(entry: dict[str, Any]) -> str:
    return str(entry.get("name") or entry.get("timbre") or entry.get("key") or entry.get("tone") or "").strip().lower()


def _stable_key(seed: int, label: str) -> int:
    h = int(seed) * 1000003
    for ch in label:
        h = (h + ord(ch) * 97) & 0x7FFFFFFF
    return h


def named_registry_sounds(knowledge: dict[str, Any] | None) -> list[str]:
    """Named static sounds for prompts; fall back to origin primitives."""
    names: list[str] = []
    seen: set[str] = set()
    for s in (knowledge or {}).get("static_sound") or []:
        if not isinstance(s, dict):
            continue
        label = sound_label(s)
        if label and label not in seen and 1 < len(label) < 40 and label != "silence":
            seen.add(label)
            names.append(label)
    if names:
        return names
    return [p for p in SOUND_ORIGIN_PRIMITIVES if p != "silence"]


# ---------------------------------------------------------------------------
# Diversity-aware primitive resolution + sampling
# ---------------------------------------------------------------------------

#: Audible primitives (everything except silence) - the pool a pairing draws from.
AUDIBLE_PRIMITIVES: tuple[str, ...] = tuple(p for p in SOUND_ORIGIN_PRIMITIVES if p != "silence")

_BAND_PRIMITIVES: dict[str, tuple[str, ...]] = {}
for _p in AUDIBLE_PRIMITIVES:
    _band = _PRIMITIVE_TONE.get(_p, "mid")
    _BAND_PRIMITIVES[_band] = _BAND_PRIMITIVES.get(_band, ()) + (_p,)

#: Recently chosen primitives (process-local, bounded) so consecutive clips spread out.
_HISTORY_LEN = 24
_recent_primitives: deque[str] = deque(maxlen=_HISTORY_LEN)
_history_lock = threading.Lock()


def reset_primitive_history() -> None:
    with _history_lock:
        _recent_primitives.clear()


def recent_primitive_history() -> list[str]:
    with _history_lock:
        return list(_recent_primitives)


def entry_primitive(entry: dict[str, Any]) -> str:
    """
    Resolve a registry sound to one of the 10 origin primitives.

    Order: explicit ``timbre`` -> a primitive named in ``name``/``key`` -> a *spread*
    inside the entry's tone band (stable hash of its identity) rather than collapsing every
    unresolved entry onto one default (mid -> tone, high -> hiss, low -> rumble).
    """
    timbre = str(entry.get("timbre") or "").strip().lower()
    if timbre in SOUND_ORIGIN_PRIMITIVES:
        return timbre
    name = str(entry.get("name") or "").strip().lower()
    key = str(entry.get("key") or "").strip().lower()
    for blob in (name, f"{key} {timbre}"):
        for prim in SOUND_ORIGIN_PRIMITIVES:
            if prim != "silence" and prim in blob:
                return prim
    tone = str(entry.get("tone") or "").strip().lower()
    if tone in ("silent", "silence"):
        return "silence"
    if not name and not key:
        return _TONE_TO_NOISE.get(tone, "tone")
    band = _BAND_PRIMITIVES.get(tone) or _BAND_PRIMITIVES["mid"]
    return band[zlib.crc32(f"{key}|{name}|{timbre}".encode("utf-8")) % len(band)]


def _entry_count(entry: dict[str, Any]) -> int:
    try:
        return max(0, int(entry.get("count") or 0))
    except (TypeError, ValueError):
        return 0


def _primitive_weights(
    buckets: dict[str, list[dict[str, Any]]],
    history: list[str],
) -> dict[str, float]:
    """Weight per audible primitive: favour underfilled, keep a floor, damp recent repeats."""
    totals = {p: sum(_entry_count(e) for e in buckets.get(p, ())) for p in AUDIBLE_PRIMITIVES}
    mean = sum(totals.values()) / max(1, len(totals))
    weights: dict[str, float] = {}
    for p in AUDIBLE_PRIMITIVES:
        under = 1.0 / (1.0 + (totals[p] / mean if mean > 0 else 0.0))  # (0, 1]
        w = 0.45 + under  # floor keeps every primitive reachable
        w *= 0.55 ** history.count(p)  # soft penalty for recent repeats
        weights[p] = max(w, 0.02)
    return weights


def _draw(rng: Any, weights: list[float]) -> int:
    total = sum(weights)
    if total <= 0:
        return rng.randrange(len(weights))
    r = rng.random() * total
    for i, w in enumerate(weights):
        r -= w
        if r < 0:
            return i
    return len(weights) - 1


def sample_sound_pairing(
    knowledge: dict[str, Any] | None,
    *,
    prompt: str = "",
    pair_count: int = 2,
    seed: int | None = None,
    use_history: bool = True,
) -> list[dict[str, Any]]:
    """
    Unique 2-N registry sounds for this clip.

    Sounds named in the prompt come first. The rest are drawn by *weighted random* (not a
    strict least-used sort): first a primitive is chosen with weights that favour underfilled
    primitives but keep every one reachable, damped by recent history; then a registry entry
    of that primitive is drawn (underused entries likelier). A clip never repeats a primitive
    while unused ones remain, so no single primitive can dominate its layers. Primitives with
    no registry entry fall back to the plain primitive sound.
    """
    n = max(2, min(6, int(pair_count)))
    rng: Any = random.Random(int(seed)) if seed is not None else secrets.SystemRandom()
    raw = (prompt or "").lower()
    named: list[dict[str, Any]] = []
    rest: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _take(entry: dict[str, Any], bucket: list[dict[str, Any]]) -> None:
        label = sound_label(entry)
        if not label or label in seen:
            return
        seen.add(label)
        bucket.append(dict(entry))

    for s in (knowledge or {}).get("static_sound") or []:
        if not isinstance(s, dict):
            continue
        label = sound_label(s)
        if label and _name_in_prompt(label, raw):
            _take(s, named)
        else:
            _take(s, rest)

    for prim in AUDIBLE_PRIMITIVES:
        if _name_in_prompt(prim, raw):
            _take(primitive_sound_entry(prim), named)

    buckets: dict[str, list[dict[str, Any]]] = {}
    for e in rest:
        prim = entry_primitive(e)
        if prim != "silence":
            buckets.setdefault(prim, []).append(e)

    out = list(named)[:n]
    used_prims = {entry_primitive(e) for e in out}
    history = recent_primitive_history() if use_history else []
    weights = _primitive_weights(buckets, history)

    guard = 0
    while len(out) < n and guard < 64:
        guard += 1
        labels = {sound_label(o) for o in out}
        avail = [p for p in AUDIBLE_PRIMITIVES if p not in used_prims] or list(AUDIBLE_PRIMITIVES)
        prim = avail[_draw(rng, [weights[p] for p in avail])]
        pool = [e for e in buckets.get(prim, []) if sound_label(e) not in labels]
        if pool:
            e = pool[_draw(rng, [1.0 / (1.0 + _entry_count(x)) ** 0.5 for x in pool])]
            entry = dict(e)
        else:
            entry = primitive_sound_entry(prim, amplitude=round(0.3 + 0.45 * rng.random(), 3))
            if sound_label(entry) in labels:
                used_prims.add(prim)
                continue
        out.append(entry)
        used_prims.add(prim)

    out = out[:n]
    if use_history:
        with _history_lock:
            for e in out:
                _recent_primitives.append(entry_primitive(e))
    return out


def pairing_kind_from_prompt(prompt: str) -> str:
    """frame = static instants; window = rematch over ~1s."""
    low = (prompt or "").lower()
    if any(
        p in low
        for p in (
            "motion window",
            "dynamic pairing",
            "dynamic sound",
            "window blend",
            "moving window",
            "across a motion",
        )
    ):
        return "window"
    return "frame"
