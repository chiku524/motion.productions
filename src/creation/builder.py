"""
Build output from extracted knowledge.
Converts InterpretedInstruction (+ optional knowledge lookup) → SceneSpec for rendering.

Parameterization (data-driven creation): Every decision is driven by registry/API data, not
hardcoded defaults. Palette: when default/empty, pick from full PALETTES set (and learned
color names in registry). Motion/gradient/camera: registry-first pools; 50% random vs
deterministic for motion. Audio: learned_audio + static_sound; 35% pick random entry for
variety. Pure colors: origin + static_colors + learned_colors. Pure sounds: sample from
static_sound mesh (3–5 per run) for future audio mixing. No single fixed default that
ignores the registry.
"""
import logging
from typing import Any

from ..interpretation import InterpretedInstruction
from ..procedural.parser import SceneSpec
from ..random_utils import secure_choice, weighted_choice_favor_underused, weighted_choice_favor_recent
from ..knowledge.blend_depth import COLOR_ORIGIN_PRIMITIVES

logger = logging.getLogger(__name__)
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
    *,
    exclude: set[str] | None = None,
) -> list[str]:
    """Merged pool: origin + learned (deduped), so creation always has both primitives and discoveries; selection is randomized."""
    exclude = exclude or set()
    origin = (knowledge or {}).get(origin_key) or []
    origin_str = [v for v in origin if isinstance(v, str) and v.strip() and v in valid_set and v not in exclude]
    learned = (knowledge or {}).get(learned_key) or []
    learned_str: list[str] = []
    for v in learned:
        if isinstance(v, str) and v.strip() and v in valid_set and v not in exclude:
            learned_str.append(v)
        elif isinstance(v, dict) and v.get("key"):
            w = (v.get("key") or v.get("gradient_type") or v.get("camera_motion") or v.get("motion_type")) or ""
            if isinstance(w, str) and w.strip() and w in valid_set and w not in exclude:
                learned_str.append(w)
    seen: set[str] = set()
    pool: list[str] = []
    for v in origin_str + learned_str:
        if v not in seen:
            seen.add(v)
            pool.append(v)
    return pool


def _profile_key_to_motion_type(profile: dict[str, Any] | str) -> str | None:
    """
    Map learned_motion profile (dict or profile_key string) → creation motion_type.
    profile_key format: level_trend_direction_rhythm (e.g. 5.2_steady_horizontal_steady).
    """
    if isinstance(profile, dict):
        trend = profile.get("motion_trend")
        key = profile.get("key", "")
    else:
        key = str(profile)
        parts = key.split("_")
        trend = parts[1] if len(parts) >= 2 else parts[-1]
    trend = (trend or "").strip().lower() or (key.split("_")[-1] if "_" in key else "")
    mapping = {
        "steady": "flow", "pulsing": "pulse", "wave": "wave", "slow": "slow",
        "fast": "fast", "medium": "flow", "static": "slow", "increasing": "fast",
        "decreasing": "slow", "neutral": "flow",
    }
    motion = mapping.get(trend, trend)
    return motion if motion in _MOTION_VALID else None


def _motion_from_registry(
    knowledge: dict[str, Any] | None,
    *,
    avoid_motion: list[str] | None = None,
    seed_hint: str | None = None,
) -> str | None:
    """
    Pick a motion type from learned_motion (registry).
    Excludes avoid_motion. When seed_hint provided, uses deterministic selection.
    """
    learned = (knowledge or {}).get("learned_motion", []) or []
    avoid = set(avoid_motion or [])
    valid_profiles = []
    for m in learned[:30]:
        if not isinstance(m, dict):
            continue
        motion = _profile_key_to_motion_type(m)
        if motion and motion in _MOTION_VALID and motion not in avoid:
            valid_profiles.append((m, motion))
    if not valid_profiles:
        return None
    if seed_hint:
        idx = hash(seed_hint) % len(valid_profiles)
        idx = idx if idx >= 0 else -idx
        _, motion = valid_profiles[idx]
        return motion
    # Bias toward underused (lower count) motion profiles
    picked = weighted_choice_favor_underused(valid_profiles, lambda p: p[0].get("count", 0))
    if picked is None:
        _, motion = secure_choice(valid_profiles)
    else:
        _, motion = picked
    return motion


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

    avoid_motion = set(getattr(instruction, "avoid_motion", None) or [])
    avoid_palette = set(getattr(instruction, "avoid_palette", None) or [])

    # Optional: refine from knowledge (respects avoid lists and explicit user intent)
    if knowledge:
        palette, motion, intensity = _refine_from_knowledge(
            palette, motion, intensity,
            instruction.keywords,
            knowledge,
            avoid_motion=avoid_motion,
            avoid_palette=avoid_palette,
        )
        audio_tempo, audio_mood, audio_presence = _refine_audio_from_knowledge(
            audio_tempo, audio_mood, audio_presence,
            knowledge,
        )

    # INTENDED_LOOP: Blend primitives + learned (enforce avoid lists)
    palette_colors = _build_palette_from_blending(
        instruction, knowledge, palette,
        avoid_palette=avoid_palette,
    )
    motion = _build_motion_from_blending(
        instruction, knowledge, motion,
        avoid_motion=avoid_motion,
        seed_hint=instruction.raw_prompt,
    )
    lighting = _build_lighting_from_blending(instruction, lighting)
    composition_balance = _build_composition_balance_from_blending(instruction, composition_balance)
    composition_symmetry = _build_composition_symmetry_from_blending(instruction, composition_symmetry)

    # Registry-only: no fixed lists — use learned_* or origin_* (excluding avoid_motion/avoid_palette)
    if gradient == DEFAULT_GRADIENT:
        pool = _pool_from_knowledge(knowledge, "learned_gradient", "origin_gradient", _GRADIENT_VALID)
        gradient = secure_choice(pool) if pool else secure_choice(tuple(GRAPHICS_ORIGINS["gradient_type"]))
    if motion == DEFAULT_MOTION:
        motion = _motion_from_registry(
            knowledge,
            avoid_motion=list(avoid_motion),
            seed_hint=instruction.raw_prompt,
        )
        if not motion:
            origin_m = (knowledge or {}).get("origin_motion") or []
            pool = [v for v in origin_m if isinstance(v, str) and v in _MOTION_VALID and v not in avoid_motion]
            motion = secure_choice(pool) if pool else secure_choice(tuple(v for v in _MOTION_VALID if v not in avoid_motion) or tuple(_MOTION_VALID))
    if camera == DEFAULT_CAMERA:
        pool = _pool_from_knowledge(knowledge, "learned_camera", "origin_camera", _CAMERA_VALID)
        camera = secure_choice(pool) if pool else secure_choice([v for v in CAMERA_ORIGINS["motion_type"] if v in _CAMERA_VALID] or list(_CAMERA_VALID))

    # Pure-per-frame creation (§7): pool = origin primitives + discovered static (learned) colors
    pure_colors = _build_pure_color_pool(knowledge, instruction, avoid_palette=avoid_palette)
    creation_mode = "pure_per_frame" if pure_colors else "blended"

    # Pure sounds from registry: sample 3–5 per-instant sounds (bias toward underused)
    pure_sounds: list[dict[str, Any]] | None = None
    static_sound = (knowledge or {}).get("static_sound") or []
    if static_sound:
        n = min(5, max(3, len(static_sound)), len(static_sound))
        pure_sounds = []
        for _ in range(n):
            s = weighted_choice_favor_underused(static_sound, lambda e: e.get("count", 0) if isinstance(e, dict) else 0)
            if s is not None:
                pure_sounds.append(dict(s) if isinstance(s, dict) else s)
        pure_sounds = pure_sounds if pure_sounds else None

    spec = SceneSpec(
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
        pure_colors=pure_colors,
        creation_mode=creation_mode,
        pure_sounds=pure_sounds,
    )

    _validate_spec_against_instruction(spec, instruction)
    return spec


def _build_pure_color_pool(
    knowledge: dict[str, Any] | None,
    instruction: InterpretedInstruction,
    *,
    avoid_palette: set[str] | None = None,
) -> list[tuple[int, int, int]]:
    """
    Build full pool of pure colors for random-per-pixel creation.

    Each pixel in each frame gets a random value from this pool; motion over a window
    combines pixels (captured at extraction as temporal blend → new pure or dynamic).
    Pool = origin primitives + static_colors (per-frame discovered) + learned_colors (whole-video).
    Creation biasing: underused colors (lower count) get higher multiplicity in the pool
    so they are picked more often, breaking the high-count feedback loop (REGISTRY_REVIEW).
    """
    pool: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()

    # 1. Origin primitives (always included once each)
    for _name, (r, g, b) in COLOR_ORIGIN_PRIMITIVES:
        t = (int(round(r)), int(round(g)), int(round(b)))
        if t not in seen:
            seen.add(t)
            pool.append(t)

    def _add_with_count_inverse(
        data_iter,
        *,
        max_copies: int = 5,
        count_scale: float = 8.0,
    ) -> None:
        """Add colors to pool with multiplicity inversely proportional to count (favor underused)."""
        for _key, data in data_iter:
            if not isinstance(data, dict) or "r" not in data or "g" not in data or "b" not in data:
                continue
            r, g, b = int(round(float(data["r"]))), int(round(float(data["g"]))), int(round(float(data["b"])))
            r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))
            t = (r, g, b)
            count = int(data.get("count", 0) or 0)
            # Multiplicity: more copies when count is low (explore underused)
            mult = max(1, min(max_copies, int(count_scale / (1.0 + count))))
            for _ in range(mult):
                pool.append(t)
            if t not in seen:
                seen.add(t)

    # 2. Static (per-frame discovered) — with count-inverse multiplicity
    static = (knowledge or {}).get("static_colors") or {}
    if isinstance(static, dict):
        _add_with_count_inverse(static.items())

    # 3. Learned (whole-video) — with count-inverse multiplicity
    learned = (knowledge or {}).get("learned_colors") or {}
    if isinstance(learned, dict):
        _add_with_count_inverse(learned.items())

    return pool


def _validate_spec_against_instruction(
    spec: SceneSpec,
    instruction: InterpretedInstruction,
) -> None:
    """
    Log if spec violates instruction (e.g. avoid_motion/avoid_palette).
    Does not modify spec; used for diagnostics and precision audits.
    """
    avoid_m = set(getattr(instruction, "avoid_motion", None) or [])
    avoid_p = set(getattr(instruction, "avoid_palette", None) or [])
    issues: list[str] = []
    if spec.motion_type in avoid_m:
        issues.append(f"motion_type={spec.motion_type} in avoid_motion")
    if spec.palette_name in avoid_p:
        issues.append(f"palette_name={spec.palette_name} in avoid_palette")
    if issues:
        logger.warning(
            "Spec violates instruction avoid lists: %s (prompt=%s)",
            "; ".join(issues),
            (instruction.raw_prompt or "")[:80],
        )


def _build_palette_from_blending(
    instruction: InterpretedInstruction,
    knowledge: dict[str, Any] | None,
    fallback_palette_name: str,
    *,
    avoid_palette: set[str] | None = None,
) -> list[tuple[int, int, int]]:
    """
    Blend primitives (and optionally learned values) → single palette per domain.
    Excludes avoid_palette from hints. Never blends with avoided palette names.
    """
    from ..knowledge.blending import blend_palettes, blend_colors

    avoid = avoid_palette or set()

    # Prefer primitive RGB lists from interpretation (prompt → values, not names)
    primitive_lists = getattr(instruction, "color_primitive_lists", None) or []
    palette_hints = getattr(instruction, "palette_hints", None) or []
    # Filter out avoid_palette: color_primitive_lists[i] corresponds to palette_hints[i]
    if primitive_lists and palette_hints:
        filtered = [
            primitive_lists[i]
            for i in range(min(len(primitive_lists), len(palette_hints)))
            if palette_hints[i] not in avoid
        ]
        primitive_lists = filtered if filtered else []
    if primitive_lists:
        result = list(primitive_lists[0])
        for other in primitive_lists[1:]:
            result = blend_palettes(result, other, weight=0.5)
    else:
        hints = getattr(instruction, "palette_hints", []) or [fallback_palette_name]
        hints = [h for h in hints if h not in avoid]
        # Registry-first: no single hardcoded default; when default/empty, pick 2–3 from full set (wider exploration)
        if not hints:
            pool = [k for k in PALETTES if k not in avoid]
            name_to_count: dict[str, int] = {k: 0 for k in pool}
            if knowledge and (knowledge.get("learned_colors") or knowledge.get("static_colors")):
                learned = knowledge.get("learned_colors") or {}
                for _key, data in learned.items():
                    if isinstance(data, dict):
                        name = (data.get("name") or "").strip()
                        if name and name in PALETTES and name not in avoid:
                            if name not in pool:
                                pool.append(name)
                            name_to_count[name] = int(data.get("count", 0) or 0)
                for _key, data in (knowledge.get("static_colors") or {}).items():
                    if isinstance(data, dict):
                        name = (data.get("name") or "").strip()
                        if name and name in PALETTES and name not in avoid and name in name_to_count:
                            name_to_count[name] = int(data.get("count", 0) or 0)
            # Pick 2–3 distinct palette hints, biased toward underused
            n_hints = min(3, max(2, len(pool))) if len(pool) >= 2 else 1
            hints = []
            pool_copy = list(pool)
            for _ in range(n_hints):
                if not pool_copy:
                    break
                chosen = weighted_choice_favor_underused(pool_copy, lambda n: name_to_count.get(n, 0))
                if chosen is None:
                    chosen = secure_choice(pool_copy)
                if chosen is not None:
                    hints.append(chosen)
                    pool_copy = [x for x in pool_copy if x != chosen]
            if not hints:
                hints = [fallback_palette_name] if fallback_palette_name not in avoid else list(PALETTES.keys())[:1]
            if not hints:
                hints = ["default"]
        result = list(PALETTES.get(hints[0], PALETTES.get("default", list(PALETTES.values())[0])))
        for name in hints[1:]:
            other = PALETTES.get(name, PALETTES.get("default", list(PALETTES.values())[0]))
            result = blend_palettes(result, other, weight=0.5)

    # Optionally blend with learned color (novel from discoveries) — deterministic by prompt when avoid empty
    learned = (knowledge or {}).get("learned_colors", {}) or {}
    if learned and not avoid:
        items = list(learned.items())[:8]
        if items:
            seed_hint = getattr(instruction, "raw_prompt", "") or ""
            idx = hash(seed_hint) % len(items)
            idx = idx if idx >= 0 else -idx
            key, data = items[idx]
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

    return result if result else list(PALETTES.get("default", list(PALETTES.values())[0]))


def _build_motion_from_blending(
    instruction: InterpretedInstruction,
    knowledge: dict[str, Any] | None,
    fallback_motion: str,
    *,
    avoid_motion: set[str] | None = None,
    seed_hint: str | None = None,
) -> str:
    """
    Blend motion primitives (and optionally learned) → single motion value.
    Excludes avoid_motion. Uses deterministic learned selection when seed_hint provided.
    """
    from ..knowledge.blending import blend_motion_params

    avoid = avoid_motion or set()
    hints = [h for h in (getattr(instruction, "motion_hints", []) or [fallback_motion]) if h not in avoid]
    if not hints:
        hints = [fallback_motion] if fallback_motion not in avoid else [m for m in _MOTION_VALID if m not in avoid]
        hints = hints or ["flow"]

    result = hints[0]
    for hint in hints[1:]:
        result = blend_motion_params(result, hint, weight=0.5)

    # Optionally blend with learned motion — exclude avoid, deterministic by seed_hint
    learned = (knowledge or {}).get("learned_motion", []) or []
    valid_learned: list[tuple[dict, str]] = []
    for m in learned[:20]:
        if not isinstance(m, dict):
            continue
        motion = _profile_key_to_motion_type(m)
        if motion and motion in _MOTION_VALID and motion not in avoid:
            valid_learned.append((m, motion))
    if valid_learned:
        # Variety: 50% random from registry, 50% deterministic by seed so runs are unpredictable
        from ..random_utils import secure_random
        if seed_hint and secure_random() >= 0.5:
            idx = hash(seed_hint) % len(valid_learned)
            idx = idx if idx >= 0 else -idx
        else:
            idx = int(secure_random() * len(valid_learned)) % len(valid_learned)
        _, learned_motion = valid_learned[idx]
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
    *,
    avoid_motion: set[str] | None = None,
    avoid_palette: set[str] | None = None,
) -> tuple[str, str, float]:
    """
    Optionally refine palette/motion/intensity from accumulated knowledge.
    Respects avoid lists; does not override explicit user choices (keywords matched).
    Only adjusts intensity when palette had poor motion stats; never changes palette/motion
    to an avoided value.
    """
    avoid_m = avoid_motion or set()
    avoid_p = avoid_palette or set()
    by_keyword = knowledge.get("by_keyword", {})
    by_palette = knowledge.get("by_palette", {})
    best_palette = palette
    best_motion = motion
    best_intensity = intensity
    MOTION_LOW, MOTION_HIGH = 1.0, 25.0

    # When user had explicit keyword matches, preserve palette and motion; only adjust intensity conservatively
    if keywords:
        for kw in keywords:
            data = by_keyword.get(kw, {})
            if not data:
                continue
            count = data.get("count", 0)
            mean_motion = data.get("mean_motion_level", 0)
            if count >= 2 and MOTION_LOW <= mean_motion <= MOTION_HIGH:
                return best_palette, best_motion, best_intensity

    # If palette has poor stats, only adjust intensity slightly; never change palette to avoid
    pal_data = by_palette.get(palette, {})
    if pal_data.get("count", 0) >= 2 and palette not in avoid_p:
        pal_motion = pal_data.get("mean_motion_level", 0)
        if not (MOTION_LOW <= pal_motion <= MOTION_HIGH):
            if pal_motion < MOTION_LOW:
                best_intensity = min(1.0, intensity + 0.1)
            else:
                best_intensity = max(0.1, intensity - 0.1)

    return best_palette, best_motion, best_intensity


def _refine_audio_from_knowledge(
    tempo: str,
    mood: str,
    presence: str,
    knowledge: dict[str, Any],
) -> tuple[str, str, str]:
    """Refine audio from learned_audio and static_sound; bias toward underused/recent."""
    from ..random_utils import secure_choice, secure_random
    # Pure sound mesh: discovered per-instant sounds can influence mood/tone (bias underused)
    static_sound = knowledge.get("static_sound") or []
    if static_sound and (mood == "neutral" or not mood):
        entry = weighted_choice_favor_underused(static_sound, lambda e: e.get("count", 0) if isinstance(e, dict) else 0)
        if entry is None:
            entry = secure_choice(static_sound)
        if isinstance(entry, dict):
            tone = (entry.get("tone") or "").strip().lower()
            tone_to_mood = {"low": "calm", "mid": "neutral", "high": "uplifting", "silent": "neutral", "silence": "neutral"}
            if tone and tone_to_mood.get(tone):
                mood = tone_to_mood[tone]
    # Blended (learned_audio): 35% pick from registry (bias recent), else most_common
    learned = knowledge.get("learned_audio", [])
    if not learned:
        return tempo, mood, presence
    use_random = secure_random() < 0.35
    if use_random:
        a = weighted_choice_favor_recent(learned, lambda x: x.get("created_at") if isinstance(x, dict) else None)
        if a is None:
            a = secure_choice(learned)
        if isinstance(a, dict):
            if tempo == "medium" or not a.get("tempo"):
                tempo = (a.get("tempo") or "medium")
            if mood == "neutral" or not a.get("mood"):
                mood = (a.get("mood") or "neutral")
            if presence == "ambient" or not a.get("presence"):
                presence = (a.get("presence") or "ambient")
        return tempo, mood, presence
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
