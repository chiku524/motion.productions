"""
Sound pairings from the static_sound registry — same idea as color pixel pairings.

Frames hold two named instants still. Windows rematch 3–4 sounds over ~1s.
Each loop picks a new combination from primitives + discoveries, not a genre catalog.
"""
from __future__ import annotations

from typing import Any

from ..knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES

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


def sample_sound_pairing(
    knowledge: dict[str, Any] | None,
    *,
    prompt: str = "",
    pair_count: int = 2,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """
    Unique 2–N registry sounds for this clip (named in the prompt first,
    then underused discoveries, then origin primitives).
    """
    n = max(2, min(6, int(pair_count)))
    pair_seed = int(seed) if seed is not None else 1
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

    for prim in SOUND_ORIGIN_PRIMITIVES:
        if prim == "silence":
            continue
        if _name_in_prompt(prim, raw):
            _take(primitive_sound_entry(prim), named)

    rest.sort(key=lambda e: (int(e.get("count") or 0), _stable_key(pair_seed, sound_label(e))))
    out = list(named)
    for e in rest:
        if len(out) >= n:
            break
        out.append(e)
    if len(out) < n:
        for prim in SOUND_ORIGIN_PRIMITIVES:
            if prim == "silence":
                continue
            _take(primitive_sound_entry(prim), out)
            if len(out) >= n:
                break
    return out[:n] if len(out) >= 2 else out


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
