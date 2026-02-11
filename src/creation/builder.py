"""
Build output from extracted knowledge.
Converts InterpretedInstruction (+ optional knowledge lookup) → SceneSpec for rendering.
INTENDED_LOOP: Use strictly pure elements/blends from STATIC registry (and origins); no templates.
When interpretation used defaults (no keyword matched), pick from registry (learned_gradient,
learned_camera, learned_motion) so growth is prioritised and pure elements can blend across frames;
only fall back to origin primitives when registry is empty.
"""
from typing import Any

from ..random_utils import secure_choice

from ..interpretation import InterpretedInstruction
from ..procedural.parser import SceneSpec
from ..procedural.data.palettes import PALETTES
from ..procedural.data.keywords import (
    DEFAULT_GRADIENT,
    DEFAULT_MOTION,
    DEFAULT_CAMERA,
)
from ..knowledge.origins import GRAPHICS_ORIGINS, CAMERA_ORIGINS

# Renderer-valid sets (used only to filter registry values; no fixed list used for creation)
_GRADIENT_VALID = frozenset(GRAPHICS_ORIGINS["gradient_type"])
_MOTION_VALID = frozenset(("slow", "wave", "flow", "fast", "pulse"))
_CAMERA_VALID = frozenset((
    "static", "zoom", "zoom_out", "pan", "rotate", "dolly", "crane",
    "tilt", "roll", "truck", "pedestal", "arc", "tracking", "whip_pan", "birds_eye",
))


def _pool_from_knowledge(
    knowledge: dict[str, Any] | None,
    learned_key: str,
    origin_key: str,
    valid_set: frozenset[str],
) -> list[str]:
    """Registry-first pool: learned_* if non-empty (filtered to valid), else origin_* from API, else empty (caller uses origins module)."""
    learned = (knowledge or {}).get(learned_key) or []
    pool = [v for v in learned if isinstance(v, str) and v.strip() and v in valid_set]
    if pool:
        return pool
    origin = (knowledge or {}).get(origin_key) or []
    return [v for v in origin if isinstance(v, str) and v.strip() and v in valid_set]


def _random_motion_from_registry(knowledge: dict[str, Any] | None) -> str | None:
    """Pick a motion type at random from learned_motion (registry). Returns None if empty."""
    learned = (knowledge or {}).get("learned_motion", []) or []
    if not learned:
        return None
    m = secure_choice(learned[:20])
    if not isinstance(m, dict):
        return None
    trend = m.get("motion_trend") or (m.get("key") or "").split("_")[-1]
    trend_to_motion = {"steady": "flow", "pulsing": "pulse", "wave": "wave", "slow": "slow", "fast": "fast", "medium": "flow", "static": "slow"}
    motion = trend_to_motion.get(trend, trend)
    return motion if motion in _MOTION_VALID else None


def build_spec_from_instruction(
    instruction: InterpretedInstruction,
    *,
    knowledge: dict[str, Any] | None = None,
) -> SceneSpec:
    """
    Build a SceneSpec from an InterpretedInstruction.

    If knowledge is provided (from learning/aggregate), uses it to refine
    palette/motion/intensity when the instruction is ambiguous or when
    knowledge suggests better parameters for desired outcomes.

    Args:
        instruction: Precise interpretation of user input
        knowledge: Optional aggregated learning (by_keyword, by_palette, overall)

    Returns:
        SceneSpec ready for the procedural renderer
    """
    palette = instruction.palette_name
    motion = instruction.motion_type
    intensity = instruction.intensity
    gradient = getattr(instruction, "gradient_type", "vertical") or "vertical"
    camera = getattr(instruction, "camera_motion", "static") or "static"
    shape = getattr(instruction, "shape_overlay", "none") or "none"
    shot = getattr(instruction, "shot_type", "medium") or "medium"
    transition = getattr(instruction, "transition_in", "cut") or "cut"
    lighting = getattr(instruction, "lighting_preset", "neutral") or "neutral"
    genre_val = getattr(instruction, "genre", "general") or "general"
    composition_balance = getattr(instruction, "composition_balance", "balanced") or "balanced"
    composition_symmetry = getattr(instruction, "composition_symmetry", "slight") or "slight"
    pacing_factor = getattr(instruction, "pacing_factor", 1.0)
    tension_curve = getattr(instruction, "tension_curve", "standard") or "standard"
    audio_tempo = getattr(instruction, "audio_tempo", "medium") or "medium"
    audio_mood = getattr(instruction, "audio_mood", "neutral") or "neutral"
    audio_presence = getattr(instruction, "audio_presence", "ambient") or "ambient"
    style_val = getattr(instruction, "style", None)
    tone_val = getattr(instruction, "tone", None)
    # Style/tone can refine lighting when style implies a look
    if style_val and lighting == "neutral":
        style_to_lighting = {"cinematic": "neutral", "noir": "noir", "abstract": "moody", "minimal": "documentary", "realistic": "documentary", "anime": "golden_hour"}
        lighting = style_to_lighting.get(style_val, lighting)
    if tone_val and lighting == "neutral":
        tone_to_lighting = {"dreamy": "golden_hour", "dark": "noir", "bright": "documentary", "calm": "documentary", "energetic": "neon", "moody": "moody"}
        lighting = tone_to_lighting.get(tone_val, lighting)
    text_overlay = getattr(instruction, "text_overlay", None)
    text_position = getattr(instruction, "text_position", "center") or "center"
    educational_template = getattr(instruction, "educational_template", None)
    depth_parallax = getattr(instruction, "depth_parallax", False)

    # Optional: refine from knowledge
    if knowledge:
        palette, motion, intensity = _refine_from_knowledge(
            palette, motion, intensity,
            instruction.keywords,
            knowledge,
        )
        audio_tempo, audio_mood, audio_presence = _refine_audio_from_knowledge(
            audio_tempo, audio_mood, audio_presence,
            knowledge,
        )

    # INTENDED_LOOP: Blend primitives + learned (don't just pick templates)
    palette_colors = _build_palette_from_blending(
        instruction, knowledge, palette,
    )
    motion = _build_motion_from_blending(
        instruction, knowledge, motion,
    )
    lighting = _build_lighting_from_blending(instruction, lighting)
    composition_balance = _build_composition_balance_from_blending(instruction, composition_balance)
    composition_symmetry = _build_composition_symmetry_from_blending(instruction, composition_symmetry)

    # Registry-only: no fixed lists — use learned_* or origin_* from knowledge (API); only if both empty use origins module
    if gradient == DEFAULT_GRADIENT:
        pool = _pool_from_knowledge(knowledge, "learned_gradient", "origin_gradient", _GRADIENT_VALID)
        gradient = secure_choice(pool) if pool else secure_choice(tuple(GRAPHICS_ORIGINS["gradient_type"]))
    if motion == DEFAULT_MOTION:
        motion = _random_motion_from_registry(knowledge)
        if not motion:
            origin_m = (knowledge or {}).get("origin_motion") or []
            pool = [v for v in origin_m if isinstance(v, str) and v in _MOTION_VALID]
            motion = secure_choice(pool) if pool else secure_choice(tuple(_MOTION_VALID))
    if camera == DEFAULT_CAMERA:
        pool = _pool_from_knowledge(knowledge, "learned_camera", "origin_camera", _CAMERA_VALID)
        camera = secure_choice(pool) if pool else secure_choice([v for v in CAMERA_ORIGINS["motion_type"] if v in _CAMERA_VALID] or list(_CAMERA_VALID))

    return SceneSpec(
        palette_name=palette,
        motion_type=motion,
        palette_colors=palette_colors,
        intensity=intensity,
        raw_prompt=instruction.raw_prompt,
        gradient_type=gradient,
        camera_motion=camera,
        shape_overlay=shape,
        shot_type=shot,
        transition_in=transition,
        transition_out=transition,
        lighting_preset=lighting,
        genre=genre_val,
        style=style_val or "cinematic",
        composition_balance=composition_balance,
        composition_symmetry=composition_symmetry,
        pacing_factor=pacing_factor,
        tension_curve=tension_curve,
        audio_tempo=audio_tempo,
        audio_mood=audio_mood,
        audio_presence=audio_presence,
        text_overlay=text_overlay,
        text_position=text_position,
        educational_template=educational_template,
        depth_parallax=depth_parallax,
    )


def _build_palette_from_blending(
    instruction: InterpretedInstruction,
    knowledge: dict[str, Any] | None,
    fallback_palette_name: str,
) -> list[tuple[int, int, int]]:
    """
    Blend primitives (and optionally learned values) → single palette per domain.
    Blending is caused by: multiple prompt keywords (each contributing primitive RGB)
    and optionally learned/discovered colors. No single palette name lookup for output.
    """
    from ..knowledge.blending import blend_palettes, blend_colors

    # Prefer primitive RGB lists from interpretation (prompt → values, not names)
    primitive_lists = getattr(instruction, "color_primitive_lists", None) or []
    if primitive_lists:
        result = list(primitive_lists[0])
        for other in primitive_lists[1:]:
            result = blend_palettes(result, other, weight=0.5)
    else:
        hints = getattr(instruction, "palette_hints", []) or [fallback_palette_name]
        if not hints:
            hints = [fallback_palette_name]
        result = list(PALETTES.get(hints[0], PALETTES["default"]))
        for name in hints[1:]:
            other = PALETTES.get(name, PALETTES["default"])
            result = blend_palettes(result, other, weight=0.5)

    # Optionally blend with learned color (novel from discoveries) — stronger weight for visible variety
    learned = (knowledge or {}).get("learned_colors", {}) or {}
    if learned:
        items = list(learned.items())[:8]
        if items:
            key, data = secure_choice(items)
            if isinstance(data, dict) and "r" in data and "g" in data and "b" in data:
                lr, lg, lb = data["r"], data["g"], data["b"]
                learned_rgb = (float(lr), float(lg), float(lb))
                mid = len(result) // 2
                blended = blend_colors(
                    (result[mid][0], result[mid][1], result[mid][2]),
                    learned_rgb,
                    weight=0.28,
                )
                result = list(result)
                result[mid] = blended
                for j in (0, -1):
                    result[j] = blend_colors(
                        (result[j][0], result[j][1], result[j][2]),
                        learned_rgb,
                        weight=0.15,
                    )

    return result if result else list(PALETTES["default"])


def _build_motion_from_blending(
    instruction: InterpretedInstruction,
    knowledge: dict[str, Any] | None,
    fallback_motion: str,
) -> str:
    """
    Blend motion primitives (and optionally learned) → single motion value.
    Blending is caused by: multiple prompt keywords (motion_hints) and optionally learned_motion.
    """
    from ..knowledge.blending import blend_motion_params

    hints = getattr(instruction, "motion_hints", []) or [fallback_motion]
    if not hints:
        hints = [fallback_motion]

    result = hints[0]
    for hint in hints[1:]:
        result = blend_motion_params(result, hint, weight=0.5)

    # Optionally blend with learned motion (from discoveries) — stronger weight for visible variety
    learned = (knowledge or {}).get("learned_motion", []) or []
    if learned:
        m = secure_choice(learned[:15]) if learned else None
        if isinstance(m, dict):
            trend = m.get("motion_trend") or m.get("key", "").split("_")[-1]
            if trend and trend in ("static", "slow", "medium", "fast", "steady", "pulsing", "wave"):
                trend_to_motion = {"steady": "flow", "pulsing": "pulse", "wave": "wave"}
                learned_motion = trend_to_motion.get(trend, trend)
                result = blend_motion_params(result, learned_motion, weight=0.35)

    return result


def _build_lighting_from_blending(instruction: InterpretedInstruction, fallback: str) -> str:
    """Blend lighting preset hints → single lighting preset (primitive-level)."""
    from ..knowledge.blending import blend_lighting_preset_names
    hints = getattr(instruction, "lighting_hints", []) or [fallback]
    if not hints:
        return fallback
    result = hints[0]
    for h in hints[1:]:
        result = blend_lighting_preset_names(result, h, weight=0.5)
    return result


def _build_composition_balance_from_blending(instruction: InterpretedInstruction, fallback: str) -> str:
    """Blend composition balance hints → single value (primitive-level)."""
    from ..knowledge.blending import blend_balance
    hints = getattr(instruction, "composition_balance_hints", []) or [fallback]
    if not hints:
        return fallback
    result = hints[0]
    for h in hints[1:]:
        result = blend_balance(result, h, weight=0.5)
    return result


def _build_composition_symmetry_from_blending(instruction: InterpretedInstruction, fallback: str) -> str:
    """Blend composition symmetry hints → single value (primitive-level)."""
    from ..knowledge.blending import blend_symmetry
    hints = getattr(instruction, "composition_symmetry_hints", []) or [fallback]
    if not hints:
        return fallback
    result = hints[0]
    for h in hints[1:]:
        result = blend_symmetry(result, h, weight=0.5)
    return result


def _refine_from_knowledge(
    palette: str,
    motion: str,
    intensity: float,
    keywords: list[str],
    knowledge: dict[str, Any],
) -> tuple[str, str, float]:
    """
    Optionally refine palette/motion/intensity from accumulated knowledge.
    Uses by_keyword and by_palette to pick parameters that produced good outcomes.
    """
    by_keyword = knowledge.get("by_keyword", {})
    by_palette = knowledge.get("by_palette", {})
    overall = knowledge.get("overall", {})

    # If we have keyword stats, prefer palette/motion that had high counts and reasonable motion
    best_motion = motion
    best_intensity = intensity
    MOTION_LOW, MOTION_HIGH = 1.0, 25.0  # "good" motion range from analysis

    for kw in keywords:
        data = by_keyword.get(kw, {})
        if not data:
            continue
        count = data.get("count", 0)
        mean_motion = data.get("mean_motion_level", 0)
        if count >= 2 and MOTION_LOW <= mean_motion <= MOTION_HIGH:
            # This keyword produced good motion; keep current params
            best_motion = motion
            best_intensity = intensity
            break

    # If palette has good stats, keep it
    pal_data = by_palette.get(palette, {})
    if pal_data.get("count", 0) >= 2:
        pal_motion = pal_data.get("mean_motion_level", 0)
        if not (MOTION_LOW <= pal_motion <= MOTION_HIGH):
            # Palette tended to produce bad motion; slightly adjust intensity
            if pal_motion < MOTION_LOW:
                best_intensity = min(1.0, intensity + 0.1)
            else:
                best_intensity = max(0.1, intensity - 0.1)

    return palette, best_motion, best_intensity


def _refine_audio_from_knowledge(
    tempo: str,
    mood: str,
    presence: str,
    knowledge: dict[str, Any],
) -> tuple[str, str, str]:
    """Refine audio params from learned_audio discoveries so audio progresses with the loop."""
    learned = knowledge.get("learned_audio", [])
    if not learned:
        return tempo, mood, presence
    # Use most recent discoveries to influence: pick most frequent values when we have defaults
    from collections import Counter
    tempos = Counter(a.get("tempo", "medium") for a in learned if isinstance(a.get("tempo"), str))
    moods = Counter(a.get("mood", "neutral") for a in learned if isinstance(a.get("mood"), str))
    presences = Counter(a.get("presence", "ambient") for a in learned if isinstance(a.get("presence"), str))
    if tempos and (tempo == "medium" or not tempos.get(tempo, 0)):
        tempo = tempos.most_common(1)[0][0]
    if moods and (mood == "neutral" or not moods.get(mood, 0)):
        mood = moods.most_common(1)[0][0]
    if presences and (presence == "ambient" or not presences.get(presence, 0)):
        presence = presences.most_common(1)[0][0]
    return tempo, mood, presence
