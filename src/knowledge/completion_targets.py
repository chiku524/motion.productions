"""
Completion targets: definition of "registry complete" for each registry.
Used by coverage API (via shared constants), prompt selection, and exploit-ratio logic.
See docs/REGISTRY_AND_WORKFLOW_IMPROVEMENTS.md.
"""
from typing import Any

# Static color: key = quantized RGB (tolerance 25 → 11 steps per channel) + opacity (21 steps)
# 11^3 * 21 ≈ 27_951 — this is the *cell space* for static_colors_coverage_pct (distinct keys / cells).
# Named CSS primaries live in static_registry.STATIC_COLOR_PRIMITIVES; Worker syncs via gen_color_primaries_ts.py.
STATIC_COLOR_ESTIMATED_CELLS = 11 * 11 * 11 * 21  # 27_951

# Static sound: 4 primitives (silence, rumble, tone, hiss). "Complete" = all four present in discoveries.
STATIC_SOUND_PRIMITIVES = ["silence", "rumble", "tone", "hiss"]
STATIC_SOUND_NUM_PRIMITIVES = 4

# Narrative: aspect -> number of origin values (from NARRATIVE_ORIGINS). API aspect names.
NARRATIVE_ORIGIN_SIZES: dict[str, int] = {
    "genre": 7,
    "mood": 7,
    "style": 5,
    "plots": 4,
    "settings": 8,
    "themes": 8,
    "scene_type": 8,
}

# Dynamic canonical sizes (for coverage % when we count distinct keys)
DYNAMIC_GRADIENT_ORIGIN_SIZE = 4
DYNAMIC_CAMERA_ORIGIN_SIZE = 16
DYNAMIC_AUDIO_TEMPO = 3
DYNAMIC_AUDIO_MOOD = 5
DYNAMIC_AUDIO_PRESENCE = 5


def narrative_origin_size(aspect: str) -> int:
    """Return expected number of origin values for a narrative aspect."""
    return NARRATIVE_ORIGIN_SIZES.get(aspect, 0)


def static_color_coverage_pct(count: int) -> float:
    """Coverage percentage for static color registry (0–100)."""
    if STATIC_COLOR_ESTIMATED_CELLS <= 0:
        return 100.0
    return min(100.0, 100.0 * count / STATIC_COLOR_ESTIMATED_CELLS)


def static_sound_has_all_primitives(primitive_counts: dict[str, int]) -> bool:
    """True if all four sound primitives appear in discoveries (depth_breakdown or keys)."""
    return all(primitive_counts.get(p, 0) > 0 for p in STATIC_SOUND_PRIMITIVES)
