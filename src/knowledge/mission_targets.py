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


def underfilled_color_families(mission: dict[str, Any] | None, *, max_n: int = 4) -> list[str]:
    """Families with lowest counts (including missing)."""
    if not mission:
        return list(FAMILY_SUBJECTS.keys())[:max_n]
    families = (mission.get("colors") or {}).get("families") or []
    if not families:
        return list(FAMILY_SUBJECTS.keys())[:max_n]
    ranked = sorted(
        families,
        key=lambda f: (int(f.get("count") or 0), str(f.get("id") or "")),
    )
    ids = [str(f.get("id")) for f in ranked if f.get("id")]
    # Prefer empty/low first
    return ids[:max_n] if ids else list(FAMILY_SUBJECTS.keys())[:max_n]


def missing_sound_origins(mission: dict[str, Any] | None) -> list[str]:
    from .blend_depth import SOUND_ORIGIN_PRIMITIVES

    present = set((mission or {}).get("sound", {}).get("origins_present") or [])
    missing = [p for p in SOUND_ORIGIN_PRIMITIVES if p not in present]
    return missing


def pick_target_color_family(api_base: str = "", mission: dict[str, Any] | None = None) -> str | None:
    from ..random_utils import secure_choice

    m = mission if mission is not None else fetch_mission(api_base)
    under = underfilled_color_families(m, max_n=5)
    return secure_choice(under) if under else None


def pick_target_sound_origin(api_base: str = "", mission: dict[str, Any] | None = None) -> str | None:
    from ..random_utils import secure_choice
    from .blend_depth import SOUND_ORIGIN_PRIMITIVES

    m = mission if mission is not None else fetch_mission(api_base)
    missing = missing_sound_origins(m)
    pool = [p for p in missing if p != "silence"] or [p for p in SOUND_ORIGIN_PRIMITIVES if p != "silence"]
    return secure_choice(pool) if pool else None


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
    l = (mx + mn) / 2
    if mx == mn:
        h, s = 0.0, 0.0
    else:
        d = mx - mn
        s = d / (2 - mx - mn) if l > 0.5 else d / (mx + mn)
        if mx == R:
            h = ((G - B) / d + (6 if G < B else 0)) / 6
        elif mx == G:
            h = ((B - R) / d + 2) / 6
        else:
            h = ((R - G) / d + 4) / 6
        h *= 360
    if l >= 0.92 and s < 0.2:
        return "white"
    if l <= 0.08:
        return "black"
    if s < 0.12:
        return "gray"
    if l < 0.45 and s >= 0.12 and 15 <= h < 55:
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
