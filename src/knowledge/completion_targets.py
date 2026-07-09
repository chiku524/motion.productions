"""
Completion targets: definition of "registry complete" for each registry.
Sizes are derived from origins.py / blend_depth.py so coverage % matches the
mission (every origin value across Pure / Blended / Semantic).

Used by coverage API (via scripts/gen_registry_constants_ts.py), prompt selection,
and exploit-ratio logic. See docs/REGISTRY_AND_WORKFLOW_IMPROVEMENTS.md.
"""
from __future__ import annotations

from .blend_depth import SOUND_ORIGIN_PRIMITIVES
from .origins import (
    AUDIO_ORIGINS,
    CAMERA_ORIGINS,
    GRAPHICS_ORIGINS,
    MOTION_ORIGINS,
    NARRATIVE_ORIGINS,
)

# Static color: key = quantized RGB (tolerance 25 → 11 steps per channel) + opacity (21 steps)
# 11^3 * 21 ≈ 27_951 — cell space for static_colors_coverage_pct (distinct keys / cells).
# Named CSS primaries live in static_registry.STATIC_COLOR_PRIMITIVES; Worker syncs via gen_color_primaries_ts.py.
STATIC_COLOR_ESTIMATED_CELLS = 11 * 11 * 11 * 21  # 27_951

# Static sound: everyday origin primitives. "Complete" = all present in discoveries.
STATIC_SOUND_PRIMITIVES = list(SOUND_ORIGIN_PRIMITIVES)
STATIC_SOUND_NUM_PRIMITIVES = len(STATIC_SOUND_PRIMITIVES)

# API aspect name -> NARRATIVE_ORIGINS key (tone→mood, tension_curve→plots).
NARRATIVE_ASPECT_TO_ORIGIN: dict[str, str] = {
    "genre": "genre",
    "mood": "tone",
    "style": "style",
    "plots": "tension_curve",  # D1 aspect "plots" stores tension_curve primitives
    "settings": "settings",
    "themes": "themes",
    "scene_type": "scene_type",
}

# Narrative: aspect -> number of origin values (full NARRATIVE_ORIGINS, not a subset).
NARRATIVE_ORIGIN_SIZES: dict[str, int] = {
    api_aspect: len(NARRATIVE_ORIGINS[origin_key])
    for api_aspect, origin_key in NARRATIVE_ASPECT_TO_ORIGIN.items()
    if origin_key in NARRATIVE_ORIGINS
}

# Dynamic canonical sizes (distinct origin keys for coverage %)
DYNAMIC_GRADIENT_ORIGIN_SIZE = len(GRAPHICS_ORIGINS["gradient_type"])
DYNAMIC_CAMERA_ORIGIN_SIZE = len(CAMERA_ORIGINS["motion_type"])
DYNAMIC_MOTION_SPEED_SIZE = len(MOTION_ORIGINS["speed"])
DYNAMIC_MOTION_RHYTHM_SIZE = len(MOTION_ORIGINS["rhythm"])
DYNAMIC_MOTION_SMOOTHNESS_SIZE = len(MOTION_ORIGINS["smoothness"])
DYNAMIC_MOTION_DIRECTIONALITY_SIZE = len(MOTION_ORIGINS["directionality"])
DYNAMIC_MOTION_ACCELERATION_SIZE = len(MOTION_ORIGINS["acceleration"])
DYNAMIC_AUDIO_TEMPO = len(AUDIO_ORIGINS["tempo"])
DYNAMIC_AUDIO_MOOD = len(AUDIO_ORIGINS["mood"])
DYNAMIC_AUDIO_PRESENCE = len(AUDIO_ORIGINS["presence"])

# Entity profiles (Phase C): kind × trajectory × bounce — mission-critical scene axes
ENTITY_KINDS = ["circle", "rect", "arrow", "character"]
ENTITY_TRAJECTORIES = ["left", "right", "up", "down", "toward", "away", "none"]
ENTITY_ESTIMATED_CELLS = len(ENTITY_KINDS) * len(ENTITY_TRAJECTORIES) * 2  # × bounce on/off

# Canonical lists for Worker/UI (keep in sync via gen_registry_constants_ts.py)
DYNAMIC_CANONICAL = {
    "gradient_type": list(GRAPHICS_ORIGINS["gradient_type"]),
    "camera_motion": list(CAMERA_ORIGINS["motion_type"]),
    "motion_speed": list(MOTION_ORIGINS["speed"]),
    "motion_rhythm": list(MOTION_ORIGINS["rhythm"]),
    "motion_smoothness": list(MOTION_ORIGINS["smoothness"]),
    "motion_directionality": list(MOTION_ORIGINS["directionality"]),
    "motion_acceleration": list(MOTION_ORIGINS["acceleration"]),
    # Flat labels used by registries UI (speed + rhythm union, unique, order-preserving)
    "motion": list(
        dict.fromkeys([*MOTION_ORIGINS["speed"], *MOTION_ORIGINS["rhythm"]])
    ),
    "sound_tempo": list(AUDIO_ORIGINS["tempo"]),
    "sound_mood": list(AUDIO_ORIGINS["mood"]),
    "sound_presence": list(AUDIO_ORIGINS["presence"]),
    "sound": [
        *[f"tempo: {t}" for t in AUDIO_ORIGINS["tempo"]],
        *[f"mood: {m}" for m in AUDIO_ORIGINS["mood"]],
        *[f"presence: {p}" for p in AUDIO_ORIGINS["presence"]],
    ],
    "entity_kind": list(ENTITY_KINDS),
    "entity_trajectory": list(ENTITY_TRAJECTORIES),
}


def narrative_origin_size(aspect: str) -> int:
    """Return expected number of origin values for a narrative aspect."""
    return NARRATIVE_ORIGIN_SIZES.get(aspect, 0)


def static_color_coverage_pct(count: int) -> float:
    """Coverage percentage for static color registry (0–100)."""
    if STATIC_COLOR_ESTIMATED_CELLS <= 0:
        return 100.0
    return min(100.0, 100.0 * count / STATIC_COLOR_ESTIMATED_CELLS)


def static_sound_has_all_primitives(primitive_counts: dict[str, int]) -> bool:
    """True if all sound origin primitives appear in discoveries (depth_breakdown or keys)."""
    return all(primitive_counts.get(p, 0) > 0 for p in STATIC_SOUND_PRIMITIVES)


def static_sound_missing_primitives(primitive_counts: dict[str, int]) -> list[str]:
    """Origin noises with zero hits — priority targets for sound_loop / derive_static_sound."""
    return [p for p in STATIC_SOUND_PRIMITIVES if primitive_counts.get(p, 0) <= 0]
