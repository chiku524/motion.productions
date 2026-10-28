"""
Mission-aware growth targets from GET /api/registries/mission.

Used by automate_loop / sound_loop / sound_origin_sweep to bias discovery
toward underfilled hue families and missing sound origins.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Subjects that tend to render into each hue family (prompt bias)
FAMILY_SUBJECTS: dict[str, list[str]] = {
    "red": ["red", "crimson", "fire", "flame", "scarlet"],
    "orange": ["orange", "amber", "sunset", "copper"],
    "yellow": ["yellow", "gold", "sun", "lemon"],
    "green": ["green", "forest", "emerald", "moss"],
    "teal": ["teal", "cyan", "aqua", "turquoise"],
    "blue": ["blue", "ocean", "azure", "navy", "indigo"],
    "purple": ["purple", "violet", "lavender", "plum"],
    "pink": ["pink", "magenta", "rose", "fuchsia"],
    "brown": ["brown", "earth", "umber", "wood"],
    "gray": ["gray", "grey", "slate", "silver", "fog"],
    "white": ["white", "snow", "ivory", "pearl"],
    "black": ["black", "night", "void", "obsidian"],
}

SHADE_CUES: dict[str, list[str]] = {
    "deep": ["deep", "dark", "shadowed", "rich"],
    "mid": ["balanced", "clear", "mid-tone"],
    "light": ["light", "pale", "soft", "bright"],
    "muted": ["muted", "dusty", "desaturated", "foggy"],
}


def fetch_mission(api_base: str) -> dict[str, Any] | None:
    if not api_base:
        return None
    try:
        from ..api_client import api_get
        return api_get(api_base.rstrip("/"), "/api/registries/mission") or None
    except Exception as e:
        logger.debug("mission fetch failed: %s", e)
        return None


def color_family_counts(mission: dict[str, Any] | None) -> dict[str, int]:
    """Count per hue family for EVERY known family.

    Families absent from the mission payload (older Workers dropped zero-count families, which is
    how white was never targeted) are treated as empty (count 0).
    """
    counts = {fid: 0 for fid in FAMILY_SUBJECTS}
    if not mission:
        return counts
    for f in (mission.get("colors") or {}).get("families") or []:
        fid = str(f.get("id") or "")
        if fid:
            counts[fid] = int(f.get("count") or 0)
    return counts


def underfilled_color_families(mission: dict[str, Any] | None, *, max_n: int = 4) -> list[str]:
    """Families ranked emptiest first (missing families count as 0). Deterministic ranking."""
    if not mission or not ((mission.get("colors") or {}).get("families")):
        return list(FAMILY_SUBJECTS.keys())[:max_n]
    counts = color_family_counts(mission)
    ranked = sorted(counts, key=lambda fid: (counts[fid], fid))
    return ranked[:max_n]


def underfill_weights(counts: dict[str, int], *, floor: float = 0.02) -> dict[str, float]:
    """Selection weight per key, decreasing smoothly with how filled it already is.

    weight = 1 / (1 + count/scale)^2 with scale = max(1, mean count), so an empty key weighs 1.0,
    a key at the mean ~0.25 and a key 10x the mean ~0.01 (floored so nothing is ever impossible).
    """
    if not counts:
        return {}
    scale = max(1.0, sum(counts.values()) / len(counts))
    return {k: max(floor, 1.0 / (1.0 + max(0, c) / scale) ** 2) for k, c in counts.items()}


def missing_sound_origins(mission: dict[str, Any] | None) -> list[str]:
    from .blend_depth import SOUND_ORIGIN_PRIMITIVES

    present = set((mission or {}).get("sound", {}).get("origins_present") or [])
    missing = [p for p in SOUND_ORIGIN_PRIMITIVES if p not in present]
    return missing


def sound_origin_counts(mission: dict[str, Any] | None) -> dict[str, int]:
    """Rows touching each sound primitive; falls back to present/absent (1/0) on older Workers."""
    from .blend_depth import SOUND_ORIGIN_PRIMITIVES

    sound = (mission or {}).get("sound") or {}
    raw = sound.get("origin_counts")
    if isinstance(raw, dict) and raw:
        return {p: int(raw.get(p) or 0) for p in SOUND_ORIGIN_PRIMITIVES}
    present = set(sound.get("origins_present") or [])
    return {p: (1 if p in present else 0) for p in SOUND_ORIGIN_PRIMITIVES}


def pick_target_color_family(
    api_base: str = "", mission: dict[str, Any] | None = None, rng: Any = None
) -> str | None:
    """Weighted-random hue family: emptier families are likelier, but all can be drawn."""
    from ..random_utils import weighted_choice

    m = mission if mission is not None else fetch_mission(api_base)
    weights = underfill_weights(color_family_counts(m))
    return weighted_choice(list(weights), list(weights.values()), rng)


def pick_target_sound_origin(
    api_base: str = "", mission: dict[str, Any] | None = None, rng: Any = None
) -> str | None:
    """Lead sound drawn from ALL primitives, weighted by underfill (silence heavily damped)."""
    from ..random_utils import weighted_choice

    m = mission if mission is not None else fetch_mission(api_base)
    weights = underfill_weights(sound_origin_counts(m))
    if "silence" in weights:
        weights["silence"] *= 0.15  # a silent lead is rarely a useful sound discovery
    return weighted_choice(list(weights), list(weights.values()), rng)


def pick_target_sound_v2_cells(
    n: int = 8,
    *,
    config: dict[str, Any] | None = None,
    mission: dict[str, Any] | None = None,
    rng: Any = None,
) -> list[int]:
    """Up to n sound.L1 (v2) cell ordinals nobody has measured yet (local store + Worker seen bitmap).

    Untried cells come first; cells the synth repeatedly failed to hit are deprioritised, never excluded.
    """
    from . import sound_v2

    return sound_v2.pick_unseen_cells(n, config=config, mission=mission, rng=rng)


def color_family_prompt_bits(family: str, shade: str | None = None) -> tuple[str, str]:
    """Return (subject, shade_cue) for prompt assembly."""
    from ..random_utils import secure_choice

    subjects = FAMILY_SUBJECTS.get(family) or [family]
    subject = secure_choice(subjects)
    cue = ""
    if shade and shade in SHADE_CUES:
        cue = secure_choice(SHADE_CUES[shade])
    elif family in ("white", "black", "gray"):
        cue = secure_choice(SHADE_CUES.get("mid", ["clear"]))
    else:
        cue = secure_choice(SHADE_CUES["light"] + SHADE_CUES["deep"])
    return subject, cue


def classify_color_family_rgb(r: float, g: float, b: float) -> str:
    """Python mirror of Worker colorBrowse.classifyColorFamily (for parity checks)."""
    R, G, B = float(r) / 255.0, float(g) / 255.0, float(b) / 255.0
    mx, mn = max(R, G, B), min(R, G, B)
    lightness = (mx + mn) / 2
    if mx == mn:
        h, s = 0.0, 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if lightness > 0.5 else d / (mx + mn)
        if mx == R:
            h = ((G - B) / d + (6 if G < B else 0)) / 6
        elif mx == G:
            h = ((B - R) / d + 2) / 6
        else:
            h = ((R - G) / d + 4) / 6
        h *= 360
    if lightness >= 0.92 and s < 0.2:
        return "white"
    if lightness <= 0.08:
        return "black"
    if s < 0.12:
        return "gray"
    if lightness < 0.45 and s >= 0.12 and 15 <= h < 55:
        return "brown"
    if h < 15 or h >= 345:
        return "red"
    if h < 40:
        return "orange"
    if h < 70:
        return "yellow"
    if h < 160:
        return "green"
    if h < 195:
        return "teal"
    if h < 255:
        return "blue"
    if h < 290:
        return "purple"
    return "pink"
