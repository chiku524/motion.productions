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
from ..knowledge.blend_depth import COLOR_ORIGIN_PRIMITIVES
from ..knowledge.origins import GRAPHICS_ORIGINS, CAMERA_ORIGINS
from ..procedural.data.keywords import (
    DEFAULT_CAMERA,
    DEFAULT_GRADIENT,
    DEFAULT_INTENSITY,
    DEFAULT_LIGHTING,
    DEFAULT_MOTION,
    DEFAULT_PALETTE,
    DEFAULT_SHOT,
    SETTING_VISUAL_DEFAULTS,
)
from ..procedural.data.palettes import PALETTES
from ..procedural.parser import SceneSpec
from ..random_utils import secure_choice, secure_random, weighted_choice_favor_underused, weighted_choice_favor_recent

logger = logging.getLogger(__name__)

# Renderer-valid sets (used only to filter registry values; no fixed list used for creation)
_GRADIENT_VALID = frozenset(GRAPHICS_ORIGINS["gradient_type"])
_MOTION_VALID = frozenset(("slow", "wave", "flow", "fast", "pulse"))
_CAMERA_VALID = frozenset((
    "static", "zoom", "zoom_out", "pan", "rotate", "dolly", "crane",
    "tilt", "roll", "truck", "pedestal", "arc", "tracking", "whip_pan", "birds_eye",
    "handheld",
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


def _has_subject_look(instruction: InterpretedInstruction) -> bool:
    """True when the prompt already specifies a scene (don't randomize camera/gradient)."""
    if getattr(instruction, "entities", None):
        return True
    if getattr(instruction, "setting", None):
        return True
    if getattr(instruction, "educational_template", None):
        return True
    return False


def _motion_recipe_from_registry(
    knowledge: dict[str, Any] | None,
    *,
    avoid_motion: list[str] | None = None,
    seed_hint: str | None = None,
) -> dict[str, Any] | None:
    """Pick a learned_motion profile as numeric recipe (level/std/rhythm), not a 5-name enum."""
    from ..procedural.motion import label_from_motion_level

    learned = (knowledge or {}).get("learned_motion", []) or []
    avoid = set(avoid_motion or [])
    valid: list[dict[str, Any]] = []
    for m in learned[:40]:
        if not isinstance(m, dict):
            continue
        try:
            level = float(m.get("motion_level") if m.get("motion_level") is not None else 8.0)
        except (TypeError, ValueError):
            continue
        std = 0.0
        try:
            std = float(m.get("motion_std") or 0.0)
        except (TypeError, ValueError):
            std = 0.0
        trend = (m.get("motion_trend") or "steady").strip().lower()
        rhythm_col = (m.get("motion_rhythm") or "").strip().lower()
        rhythm = rhythm_col if rhythm_col in ("steady", "pulsing", "wave", "random") else (
            trend if trend in ("steady", "pulsing", "wave", "random") else "steady"
        )
        direction = (m.get("motion_direction") or "none").strip().lower()
        if direction in ("", "neutral"):
            direction = "none"
        if direction not in ("none", "horizontal", "vertical", "diagonal", "radial"):
            direction = "none"
        label = label_from_motion_level(level, rhythm)
        if label in avoid:
            continue
        valid.append({
            "level": level,
            "std": std,
            "rhythm": rhythm,
            "direction": direction,
            "label": label,
            "count": m.get("count", 0),
        })
    if not valid:
        return None
    if seed_hint:
        idx = hash(seed_hint) % len(valid)
        idx = idx if idx >= 0 else -idx
        return valid[idx]
    picked = weighted_choice_favor_underused(valid, lambda p: p.get("count", 0))
    return picked if picked is not None else secure_choice(valid)


def _level_from_motion_label(motion: str) -> float:
    from ..procedural.motion import _label_to_level_rhythm
    level, _rhythm = _label_to_level_rhythm(motion)
    return level


def _intensity_from_learned_motion(knowledge: dict[str, Any] | None) -> float | None:
    """Map learned motion_level (typically 0–25) onto SceneSpec.intensity (0–1)."""
    learned = (knowledge or {}).get("learned_motion") or []
    levels: list[float] = []
    for m in learned:
        if not isinstance(m, dict) or "motion_level" not in m:
            continue
        try:
            levels.append(float(m.get("motion_level") or 0))
        except (TypeError, ValueError):
            continue
    if not levels:
        return None
    sample = levels[:8]
    avg = sum(sample) / len(sample)
    return max(0.15, min(1.0, avg / 20.0))


_PIXEL_PAIRING_PHRASES = (
    "pure mesh",
    "pure color",
    "color mesh",
    "per-frame pure",
    "rainbow mesh",
    "pixel field",
    "pixel mesh",
    "pixel wash",
    "color field",
    "abstract mesh",
    "abstract pixel",
    "pixel pairing",
    "paired with",
    "static frame",
    "motion window",
    "per-frame pairing",
    "window blend",
    "dynamic pairing",
    "still pixel",
    "color pairing",
    "sound pairing",
    "static sound",
    "dynamic sound",
)

_WINDOW_PAIRING_PHRASES = (
    "motion window",
    "dynamic pairing",
    "dynamic sound",
    "window blend",
    "moving window",
    "across a motion",
)

_STATIC_FRAME_PHRASES = (
    "static frame",
    "per-frame pairing",
    "still pixel",
    "per-frame pure",
    "static sound",
)


def _wants_pixel_pairing(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(p in low for p in _PIXEL_PAIRING_PHRASES)


def _wants_window_pairing(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(p in low for p in _WINDOW_PAIRING_PHRASES)


def _wants_static_frame_pairing(prompt: str) -> bool:
    low = (prompt or "").lower()
    return any(p in low for p in _STATIC_FRAME_PHRASES)


def build_spec_from_instruction(
    instruction: InterpretedInstruction,
    *,
    knowledge: dict[str, Any] | None = None,
    creation_seed: int | None = None,
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
    raw_prompt = getattr(instruction, "raw_prompt", "") or ""
    wants_pairing = _wants_pixel_pairing(raw_prompt)
    window_pairing = _wants_window_pairing(raw_prompt)
    static_frame_pairing = _wants_static_frame_pairing(raw_prompt)
    intensity = instruction.intensity
    if abs(float(intensity) - float(DEFAULT_INTENSITY)) < 1e-9:
        learned_i = _intensity_from_learned_motion(knowledge)
        if learned_i is not None:
            intensity = learned_i
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
    audio_genre = getattr(instruction, "audio_genre", "none") or "none"
    audio_vocals = bool(getattr(instruction, "audio_vocals", False))
    motion_directionality = getattr(instruction, "motion_directionality", "none") or "none"
    motion_smoothness = getattr(instruction, "motion_smoothness", "smooth") or "smooth"
    motion_rhythm = getattr(instruction, "motion_rhythm", "steady") or "steady"
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
        genre_val, style_val, mood_from_narrative = _refine_narrative_from_knowledge(
            knowledge, genre_val, style_val
        )
        if mood_from_narrative and (not tone_val or tone_val == "neutral"):
            tone_val = mood_from_narrative

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
    motion_directionality = _build_directionality_from_blending(instruction, motion_directionality)
    motion_smoothness = _build_smoothness_from_blending(instruction, motion_smoothness)
    motion_rhythm = _build_rhythm_from_blending(instruction, motion_rhythm)
    audio_tempo, audio_mood, audio_presence = _build_audio_from_blending(
        instruction, audio_tempo, audio_mood, audio_presence
    )
    if audio_genre != "none" and audio_presence == "ambient":
        audio_presence = "music"
    lighting = _build_lighting_from_blending(instruction, lighting)
    composition_balance = _build_composition_balance_from_blending(instruction, composition_balance)
    composition_symmetry = _build_composition_symmetry_from_blending(instruction, composition_symmetry)

    # Setting look first so forest/ocean/night aren't overwritten by registry random.
    setting = getattr(instruction, "setting", None)
    if setting:
        vis = SETTING_VISUAL_DEFAULTS.get(setting) or {}
        if vis.get("palette") and palette in (DEFAULT_PALETTE, "default"):
            palette = vis["palette"]
            if vis["palette"] in PALETTES:
                palette_colors = list(PALETTES[vis["palette"]])
        if vis.get("lighting") and lighting in (DEFAULT_LIGHTING, "neutral"):
            lighting = vis["lighting"]
        if vis.get("gradient") and gradient == DEFAULT_GRADIENT:
            gradient = vis["gradient"]

    lock_look = _has_subject_look(instruction)
    motion_level: float | None = None
    motion_std: float | None = None
    # Registry exploration only when the prompt has no subject/setting look to preserve.
    if gradient == DEFAULT_GRADIENT and not lock_look:
        pool = _pool_from_knowledge(knowledge, "learned_gradient", "origin_gradient", _GRADIENT_VALID)
        gradient = secure_choice(pool) if pool else secure_choice(tuple(GRAPHICS_ORIGINS["gradient_type"]))
    if motion == DEFAULT_MOTION:
        recipe = _motion_recipe_from_registry(
            knowledge,
            avoid_motion=list(avoid_motion),
            seed_hint=instruction.raw_prompt,
        )
        if recipe:
            motion = recipe["label"]
            motion_level = float(recipe["level"])
            motion_std = float(recipe.get("std") or 0.0)
            if recipe.get("rhythm") and motion_rhythm == "steady":
                motion_rhythm = str(recipe["rhythm"])
            if recipe.get("direction") and motion_directionality == "none":
                motion_directionality = str(recipe["direction"])
        elif not lock_look:
            origin_m = (knowledge or {}).get("origin_motion") or []
            pool = [v for v in origin_m if isinstance(v, str) and v in _MOTION_VALID and v not in avoid_motion]
            motion = secure_choice(pool) if pool else secure_choice(tuple(v for v in _MOTION_VALID if v not in avoid_motion) or tuple(_MOTION_VALID))
    if motion_level is None:
        motion_level = _level_from_motion_label(motion)
    if wants_pairing:
        if window_pairing:
            motion_level = max(float(motion_level or 8.0), 9.0)
        elif static_frame_pairing:
            motion_level = min(float(motion_level or 2.5), 3.5)
            if motion_std is not None:
                motion_std = min(float(motion_std), 1.5)
            else:
                motion_std = 0.4
    if camera == DEFAULT_CAMERA and not lock_look:
        pool = _pool_from_knowledge(knowledge, "learned_camera", "origin_camera", _CAMERA_VALID)
        camera = secure_choice(pool) if pool else secure_choice([v for v in CAMERA_ORIGINS["motion_type"] if v in _CAMERA_VALID] or list(_CAMERA_VALID))

    # Pixel pairing: unique 2–4 registry colors this clip; otherwise full discovery pool
    pair_n = None
    if wants_pairing:
        pair_n = 4 if window_pairing else (2 if static_frame_pairing else 3)
    pair_seed = creation_seed if creation_seed is not None else None
    pure_colors = _build_pure_color_pool(
        knowledge,
        instruction,
        avoid_palette=avoid_palette,
        pair_count=pair_n,
        seed=pair_seed,
    )
    creation_mode = "pure_per_frame" if pure_colors else "blended"

    # Unique sound pairing from the registry (own spectrum: static instants vs motion windows)
    from ..audio.pairing import sample_sound_pairing

    sound_pairing: str | None = None
    if wants_pairing:
        sound_pairing = "window" if window_pairing else "frame"
        sound_n = 4 if window_pairing else 2
        pure_sounds = sample_sound_pairing(
            knowledge,
            prompt=raw_prompt,
            pair_count=sound_n,
            seed=pair_seed,
        ) or None
        audio_genre = "none"
        audio_vocals = False
        if (audio_presence or "").lower() in ("music", "full"):
            audio_presence = "ambient"
    else:
        # Object / mini-scene path: keep a small underused sample when present
        pure_sounds = None
        static_sound = (knowledge or {}).get("static_sound") or []
        if static_sound:
            n = min(4, max(2, len(static_sound)))
            sampled: list[dict[str, Any]] = []
            for _ in range(n):
                s = weighted_choice_favor_underused(static_sound, lambda e: e.get("count", 0) if isinstance(e, dict) else 0)
                if s is not None:
                    sampled.append(dict(s) if isinstance(s, dict) else s)
            pure_sounds = sampled or None

    # Scene graph (Phase 2+): entities → keyframed layers + bounce SFX timings
    from .scene_graph import (
        build_scene_graph_from_instruction,
        sfx_events_from_scene_graph,
        walk_cycle_keyframes,
    )
    from .narrative_script import (
        build_educational_script,
        script_beats_to_dicts,
        script_to_entities_and_sfx,
    )

    duration_hint = float(getattr(instruction, "duration_seconds", None) or 4.0)
    wants_pure = wants_pairing
    entities = [] if wants_pure else list(getattr(instruction, "entities", None) or [])
    if wants_pure:
        instruction.entities = []
    script_beats: list[dict] | None = None
    music_sections: list[str] | None = None

    # Phase 5 / Roadmap B: educational template → multi-beat entities + SFX
    # Always build beats/music when a template is set — merge prompt entities as subject look.
    if not wants_pure and getattr(instruction, "educational_template", None):
        topic = (getattr(instruction, "text_overlay", None) or "the topic").strip()
        narr = build_educational_script(
            topic,
            total_duration=max(5.0, duration_hint),
            style=str(getattr(instruction, "educational_template", None) or "educational"),
        )
        ents, sfx_from_script = script_to_entities_and_sfx(narr)
        seed = entities[0] if entities and isinstance(entities[0], dict) else None
        if seed:
            for e in ents:
                if not isinstance(e, dict):
                    continue
                for key in ("kind", "color_hint", "label", "personality", "directionality"):
                    if seed.get(key):
                        e[key] = seed[key]
                # Keep per-beat expression from the script; fill only if missing
                e["expression"] = e.get("expression") or seed.get("expression") or "neutral"
        entities = ents
        instruction.entities = entities
        if not getattr(instruction, "sfx_events", None):
            instruction.sfx_events = sfx_from_script
        script_beats = script_beats_to_dicts(narr)
        music_sections = [b.music_section for b in narr.beats]
        if not text_overlay and narr.beats:
            text_overlay = narr.beats[0].text

    # Phase E: free-form "then" mini-scripts override single-entity expansion
    freeform_applied = False
    if duration_hint <= 12.0 and not wants_pure and not getattr(instruction, "educational_template", None):
        from .script_parse import (
            freeform_entities_from_prompt,
            parse_freeform_mini_script,
            split_script_clauses,
        )
        raw_prompt = getattr(instruction, "raw_prompt", "") or ""
        if split_script_clauses(raw_prompt):
            base = entities[0] if entities and isinstance(entities[0], dict) else None
            narr = parse_freeform_mini_script(raw_prompt, total_duration=duration_hint)
            parsed = freeform_entities_from_prompt(
                raw_prompt,
                base_entity=base,
                total_duration=duration_hint,
            )
            if parsed and narr:
                ents, sfx_from_script = parsed
                entities = ents
                instruction.entities = entities
                instruction.sfx_events = sfx_from_script
                script_beats = script_beats_to_dicts(narr)
                music_sections = [b.music_section for b in narr.beats]
                if not text_overlay and narr.beats and narr.beats[0].text:
                    text_overlay = narr.beats[0].text
                freeform_applied = True

    # Short mini-scenes: if we have a single bouncing/walking entity, expand to a 3-beat arc
    # Skip when the prompt already set an entertainment gag (spin/flourish/…) — keep it intact
    _PROMPT_GAGS = frozenset(("spin", "flourish", "double_take", "wink"))
    seed_gag = ""
    if entities and isinstance(entities[0], dict):
        seed_gag = str(entities[0].get("gag") or "").lower()
    if (
        not wants_pure
        and not freeform_applied
        and entities
        and duration_hint <= 8.0
        and len(entities) == 1
        and isinstance(entities[0], dict)
        and (entities[0].get("bounce") or entities[0].get("kind") == "character")
        and not getattr(instruction, "educational_template", None)
        and seed_gag not in _PROMPT_GAGS
    ):
        from .narrative_script import build_mini_scene_script, script_beats_to_dicts
        from ..procedural.scene_instance import scene_rng
        action = "walk" if entities[0].get("kind") == "character" else "bounce"
        br = scene_rng(getattr(instruction, "raw_prompt", "") or "", creation_seed, "beats")
        w1 = br.uniform(0.18, 0.32)
        w3 = br.uniform(0.22, 0.36)
        w2 = max(0.28, 1.0 - w1 - w3)
        narr = build_mini_scene_script(
            total_duration=duration_hint,
            action=action,
            topic=entities[0].get("label"),
            weights=[w1, w2, w3],
        )
        kind = entities[0].get("kind") or "circle"
        ents, sfx_from_script = script_to_entities_and_sfx(narr, entity_kind=kind if kind != "character" else "circle")
        # Preserve character look from the prompt; per-beat faces live on script_beats
        for e in ents:
            e["kind"] = kind
            e["color_hint"] = entities[0].get("color_hint")
            e["directionality"] = entities[0].get("directionality") or e.get("directionality")
            e["expression"] = entities[0].get("expression") or e.get("expression") or "neutral"
            e["personality"] = entities[0].get("personality") or e.get("personality") or "neutral"
        entities = ents
        instruction.entities = entities
        if not getattr(instruction, "sfx_events", None):
            instruction.sfx_events = sfx_from_script
        if script_beats is None:
            script_beats = script_beats_to_dicts(narr)
            music_sections = [b.music_section for b in narr.beats]

    # Geometry is created per video from the prompt + seed. Named learned_entities
    # appear only when the prompt cites them (form recipes), never as cloned extras.

    # Phase 5: character walk cycles when entity kind is character
    for ent in entities:
        if isinstance(ent, dict) and ent.get("kind") == "character" and not ent.get("trajectory"):
            ent["trajectory"] = "left" if motion_directionality == "horizontal" else "right"

    # Setting props: trees/fish/waves/buildings/clouds behind named foreground subjects
    if setting and entities and not wants_pure:
        from .props import merge_setting_props
        entities = merge_setting_props(
            entities,
            setting,
            duration=duration_hint,
            prompt=getattr(instruction, "raw_prompt", "") or "",
            creation_seed=creation_seed,
        )
        instruction.entities = entities

    graph = build_scene_graph_from_instruction(
        instruction,
        duration_seconds=duration_hint,
        palette_colors=palette_colors,
        creation_seed=creation_seed,
    )
    # Attach walk-cycle keyframes for characters (personality modulates bob)
    # Skip when a gag already built spin/flourish/double_take keyframes
    _WALK_SAFE_GAGS = frozenset(("none", "squash", "wink", ""))
    for layer in graph.layers:
        gag = (getattr(layer, "gag", None) or "none").lower()
        if (
            layer.kind == "character"
            and len(layer.keyframes) <= 2
            and gag in _WALK_SAFE_GAGS
        ):
            direction = "left"
            if layer.keyframes and layer.keyframes[-1].x > layer.keyframes[0].x:
                direction = "right"
            layer.keyframes = walk_cycle_keyframes(
                duration=duration_hint,
                direction=direction,
                personality=layer.personality or "neutral",
            )
    # composition_balance is applied at render time (see renderer._render_layers_rgba)
    # so keyframe trajectories stay in local space and framing stays consistent.
    scene_layers = graph.to_dict_list() if graph.layers else None
    if scene_layers and shape == "none":
        shape = "circle"  # ensure overlay path exists as fallback

    sfx_events = list(getattr(instruction, "sfx_events", None) or [])
    # Fill timings from scene graph bounce contacts
    graph_events = sfx_events_from_scene_graph(graph, duration_seconds=duration_hint)
    if graph_events:
        sfx_events = graph_events
    else:
        # Placeholder events without t_sec → schedule evenly for bounce kinds
        from ..audio.event_sfx import infer_bounce_events
        kinds = [e.get("kind") for e in sfx_events if isinstance(e, dict)]
        if "bounce" in kinds or any(
            isinstance(e, dict) and e.get("bounce") for e in entities
        ):
            sfx_events = infer_bounce_events(duration_hint)
    # Weather SFX for rain/snow/forest settings (skip abstract mesh clips)
    if not wants_pure:
        try:
            from ..audio.event_sfx import infer_weather_events
            weather_ev = infer_weather_events(setting, duration_hint)
            if weather_ev:
                sfx_events = list(sfx_events) + weather_ev
        except ImportError:
            pass

    # Mini-scenes with entities: blended palette gradients (setting themes), not rainbow mesh
    if (entities or scene_layers) and not wants_pure:
        creation_mode = "blended"
        pure_colors = None

    # Match camera to subject motion when the prompt never named a move
    if camera == DEFAULT_CAMERA and entities:
        from ..procedural.look import camera_for_subject_motion
        camera = camera_for_subject_motion(entities)

    from ..procedural.scene_instance import instantiate_scene

    instance = instantiate_scene(
        prompt=instruction.raw_prompt or "",
        setting=setting,
        creation_seed=creation_seed,
        palette_colors=palette_colors,
        intensity=intensity,
        shot_type=shot,
        default_shot=DEFAULT_SHOT,
    )

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
        setting=setting,
        composition_balance=composition_balance,
        composition_symmetry=composition_symmetry,
        pacing_factor=pacing_factor,
        tension_curve=tension_curve,
        audio_tempo=audio_tempo,
        audio_mood=audio_mood,
        audio_presence=audio_presence,
        audio_genre=audio_genre,
        audio_vocals=audio_vocals,
        motion_directionality=motion_directionality,
        motion_smoothness=motion_smoothness,
        motion_rhythm=motion_rhythm,
        motion_level=motion_level,
        motion_std=motion_std,
        sfx_events=sfx_events or None,
        scene_layers=scene_layers,
        text_overlay=text_overlay,
        text_position=text_position,
        educational_template=educational_template,
        script_beats=script_beats,
        music_sections=music_sections,
        depth_parallax=depth_parallax,
        film_look=bool(
            depth_parallax
            or (style_val or "").lower() in ("realistic", "photoreal")
        ),
        render_engine=(
            "enhanced"
            if (style_val or "").lower() in ("realistic", "photoreal")
            else "procedural"
        ),
        pure_colors=pure_colors,
        creation_mode=creation_mode,
        pure_sounds=pure_sounds,
        sound_pairing=sound_pairing,
        camera_steadiness=_resolve_camera_steadiness(instruction, camera, shot),
        color_temperature=_resolve_color_temperature(instruction, lighting),
        instance=instance,
    )

    _validate_spec_against_instruction(spec, instruction)
    return spec


def _resolve_camera_steadiness(instruction: InterpretedInstruction, camera: str, shot: str) -> str:
    """Map prompt/camera/shot cues to steadiness origin values."""
    words = set(getattr(instruction, "keywords", None) or [])
    raw = (getattr(instruction, "raw_prompt", None) or "").lower()
    if "shaky" in words or "shaky" in raw or "unstable" in raw:
        return "shaky"
    if (
        camera == "handheld"
        or shot == "handheld"
        or "handheld" in words
        or "documentary" in words
    ):
        return "handheld"
    if "locked" in words or "tripod" in raw:
        return "locked"
    return "stable"


def _resolve_color_temperature(instruction: InterpretedInstruction, lighting: str) -> str:
    """Warm / cool / neutral from prompt words or lighting preset."""
    words = set(getattr(instruction, "keywords", None) or [])
    raw = (getattr(instruction, "raw_prompt", None) or "").lower()
    if any(w in words or w in raw for w in ("warm", "golden", "sunset", "amber", "orange")):
        return "warm"
    if any(w in words or w in raw for w in ("cool", "cold", "blue", "icy", "winter", "snow")):
        return "cool"
    lighting = (lighting or "").lower()
    if lighting in ("golden_hour",):
        return "warm"
    if lighting in ("noir", "neon", "moody"):
        return "cool"
    return "neutral"


def _rgb_from_color_dict(data: Any) -> tuple[int, int, int] | None:
    if not isinstance(data, dict) or "r" not in data or "g" not in data or "b" not in data:
        return None
    r, g, b = int(round(float(data["r"]))), int(round(float(data["g"]))), int(round(float(data["b"])))
    return (
        max(0, min(255, r)),
        max(0, min(255, g)),
        max(0, min(255, b)),
    )


def _stable_pair_key(seed: int, rgb: tuple[int, int, int]) -> int:
    return (int(seed) * 1000003 + rgb[0] * 13 + rgb[1] * 47 + rgb[2] * 97) & 0x7FFFFFFF


def _name_in_prompt(name: str, raw: str) -> bool:
    s = (name or "").strip().lower()
    if not s or len(s) < 3:
        return False
    if " " in s:
        return s in raw
    tokens = raw.replace(":", " ").replace(",", " ").replace(".", " ").split()
    return s in tokens


def _prompt_named_rgbs(
    knowledge: dict[str, Any] | None,
    instruction: InterpretedInstruction,
) -> list[tuple[int, int, int]]:
    """Registry colors whose names appear in the prompt — the pairing the loop asked for."""
    raw = (getattr(instruction, "raw_prompt", "") or "").lower()
    if not raw:
        return []
    found: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    by_name = (knowledge or {}).get("color_by_name") or {}
    if isinstance(by_name, dict):
        for nm, data in by_name.items():
            if not _name_in_prompt(str(nm or ""), raw):
                continue
            rgb = _rgb_from_color_dict(data) if isinstance(data, dict) else None
            if rgb is not None and rgb not in seen:
                seen.add(rgb)
                found.append(rgb)
    static = (knowledge or {}).get("static_colors") or {}
    if isinstance(static, dict):
        for data in static.values():
            if not isinstance(data, dict):
                continue
            if not _name_in_prompt(str(data.get("name") or ""), raw):
                continue
            rgb = _rgb_from_color_dict(data)
            if rgb is not None and rgb not in seen:
                seen.add(rgb)
                found.append(rgb)
    return found


def _sample_color_pairing(
    pool: list[tuple[int, int, int]],
    instruction: InterpretedInstruction,
    knowledge: dict[str, Any] | None,
    *,
    pair_count: int,
    seed: int | None,
) -> list[tuple[int, int, int]]:
    """Unique 2–N registry colors for this clip (named first, then underused / seed-picked)."""
    n = max(2, min(6, int(pair_count)))
    pair_seed = int(seed) if seed is not None else 1
    named = _prompt_named_rgbs(knowledge, instruction)
    unique_pool: list[tuple[int, int, int]] = []
    seen: set[tuple[int, int, int]] = set()
    for rgb in named + list(pool):
        if rgb in seen:
            continue
        seen.add(rgb)
        unique_pool.append(rgb)
    if not unique_pool:
        return pool[:n] if pool else []
    named_set = set(named)
    rest = [c for c in unique_pool if c not in named_set]
    rest.sort(key=lambda rgb: _stable_pair_key(pair_seed, rgb))
    out = list(named)
    for rgb in rest:
        if len(out) >= n:
            break
        out.append(rgb)
    if len(out) < 2:
        out = unique_pool[:n]
    return out[:n]


def _build_pure_color_pool(
    knowledge: dict[str, Any] | None,
    instruction: InterpretedInstruction,
    *,
    avoid_palette: set[str] | None = None,
    pair_count: int | None = None,
    seed: int | None = None,
) -> list[tuple[int, int, int]]:
    """
    Build registry colors for pixel pairing / pure-per-frame creation.

    Default (pair_count unset): origin primitives + static_colors (count-inverse).
    When pair_count is set: a unique 2–N pairing for this clip from named prompt
    colors plus underused discoveries — new combination each loop.
    """
    _ = avoid_palette
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
            t = _rgb_from_color_dict(data)
            if t is None:
                continue
            count = int(data.get("count", 0) or 0) if isinstance(data, dict) else 0
            mult = max(1, min(max_copies, int(count_scale / (1.0 + count))))
            for _ in range(mult):
                pool.append(t)
            if t not in seen:
                seen.add(t)

    # 2. Static (per-frame discovered) — with count-inverse multiplicity
    static = (knowledge or {}).get("static_colors") or {}
    if isinstance(static, dict):
        _add_with_count_inverse(static.items())

    # 3. learned_colors only when static registry is empty (static is the mission-correct store)
    if not static:
        learned = (knowledge or {}).get("learned_colors") or {}
        if isinstance(learned, dict):
            _add_with_count_inverse(learned.items())

    if pair_count is not None and pair_count > 0:
        return _sample_color_pairing(
            pool, instruction, knowledge, pair_count=pair_count, seed=seed
        )
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
        hints = [h for h in (getattr(instruction, "palette_hints", None) or []) if h not in avoid]
        static_rgb_pool = _static_rgb_pool(knowledge)
        default_only = (not hints) or set(hints) <= {fallback_palette_name, "default", DEFAULT_PALETTE}
        if default_only:
            # Prefer discovered static RGB over named PALETTES catalog
            if static_rgb_pool:
                from ..random_utils import secure_choice as _sc
                picked: list[tuple[int, int, int]] = []
                pool_rgb = list(static_rgb_pool)
                for _ in range(min(4, len(pool_rgb))):
                    c = _sc(pool_rgb)
                    if c is not None:
                        picked.append(c)
                        pool_rgb = [x for x in pool_rgb if x != c]
                if picked:
                    return picked if len(picked) >= 2 else picked + picked
            pool = [k for k in PALETTES if k not in avoid]
            name_to_count: dict[str, int] = {k: 0 for k in pool}
            for _key, data in ((knowledge or {}).get("static_colors") or {}).items():
                if not isinstance(data, dict):
                    continue
                name = (data.get("name") or "").strip()
                if name and name not in avoid:
                    if name not in pool:
                        pool.append(name)
                    name_to_count[name] = name_to_count.get(name, 0) + int(data.get("count", 0) or 0)
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
        resolved: list[list[tuple[int, int, int]]] = []
        for name in hints:
            stops = _rgb_stops_for_name(name, knowledge)
            if stops:
                resolved.append(stops)
        if not resolved:
            resolved = [list(PALETTES.get("default", list(PALETTES.values())[0]))]
        result = list(resolved[0])
        for other in resolved[1:]:
            result = blend_palettes(result, other, weight=0.5)

    # Tint with a static registry color when the prompt did not name one
    static = (knowledge or {}).get("static_colors") or {}
    if static and not avoid:
        items = list(static.items())[:8]
        if items:
            seed_hint = getattr(instruction, "raw_prompt", "") or ""
            idx = hash(seed_hint) % len(items)
            idx = idx if idx >= 0 else -idx
            _key, data = items[idx]
            if isinstance(data, dict) and "r" in data and "g" in data and "b" in data:
                learned_rgb = (float(data["r"]), float(data["g"]), float(data["b"]))
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


def _build_directionality_from_blending(instruction: InterpretedInstruction, fallback: str) -> str:
    from ..knowledge.blending import blend_directionality
    hints = [h for h in (getattr(instruction, "motion_directionality_hints", None) or [fallback]) if h]
    if not hints:
        return fallback or "none"
    result = hints[0]
    for h in hints[1:]:
        result = blend_directionality(result, h, weight=0.5)
    return result


def _build_smoothness_from_blending(instruction: InterpretedInstruction, fallback: str) -> str:
    from ..knowledge.blending import blend_smoothness
    val = getattr(instruction, "motion_smoothness", None) or fallback
    return blend_smoothness(val, fallback, weight=0.35) if val != fallback else val


def _build_rhythm_from_blending(instruction: InterpretedInstruction, fallback: str) -> str:
    from ..knowledge.blending import blend_rhythm
    val = getattr(instruction, "motion_rhythm", None) or fallback
    return blend_rhythm(val, fallback, weight=0.35) if val != fallback else val


def _rgb_stops_for_name(
    name: str,
    knowledge: dict[str, Any] | None,
) -> list[tuple[int, int, int]] | None:
    """Registry RGB by name, then hardcoded PALETTES as primitive fallback."""
    from ..knowledge.color_space import palette_stops_from_rgb

    needle = (name or "").strip().lower()
    if not needle:
        return None
    for data in ((knowledge or {}).get("static_colors") or {}).values():
        if not isinstance(data, dict):
            continue
        if (data.get("name") or "").strip().lower() != needle:
            continue
        try:
            return palette_stops_from_rgb(data["r"], data["g"], data["b"])
        except (KeyError, TypeError, ValueError):
            continue
    if name in PALETTES:
        return list(PALETTES[name])
    return None


def _static_rgb_pool(knowledge: dict[str, Any] | None) -> list[tuple[int, int, int]]:
    pool: list[tuple[int, int, int]] = []
    for data in ((knowledge or {}).get("static_colors") or {}).values():
        if not isinstance(data, dict):
            continue
        try:
            pool.append((int(data["r"]), int(data["g"]), int(data["b"])))
        except (KeyError, TypeError, ValueError):
            continue
    return pool


def _build_audio_from_blending(
    instruction: InterpretedInstruction,
    tempo: str,
    mood: str,
    presence: str,
) -> tuple[str, str, str]:
    from ..knowledge.blending import blend_audio_tempo, blend_audio_mood, blend_audio_presence
    hints = getattr(instruction, "audio_hints", None) or []
    for h in hints:
        if h in ("slow", "medium", "fast"):
            tempo = blend_audio_tempo(tempo, h, weight=0.4)
        elif h in ("silence", "ambient", "music", "sfx", "full"):
            presence = blend_audio_presence(presence, h, weight=0.4)
        else:
            mood = blend_audio_mood(mood, h, weight=0.35)
    return tempo, mood, presence


def _build_motion_from_blending(
    instruction: InterpretedInstruction,
    knowledge: dict[str, Any] | None,
    fallback_motion: str,
    *,
    avoid_motion: set[str] | None = None,
    seed_hint: str | None = None,
) -> str:
    """Blend prompt motion_hints only. Learned motion is applied as a numeric recipe, not remapped onto five labels."""
    from ..knowledge.blending import blend_motion_params

    avoid = avoid_motion or set()
    hints = [h for h in (getattr(instruction, "motion_hints", []) or [fallback_motion]) if h not in avoid]
    if not hints:
        hints = [fallback_motion] if fallback_motion not in avoid else [m for m in _MOTION_VALID if m not in avoid]
        hints = hints or ["flow"]

    result = hints[0]
    for hint in hints[1:]:
        result = blend_motion_params(result, hint, weight=0.5)
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


def _refine_narrative_from_knowledge(
    knowledge: dict[str, Any] | None,
    genre_val: str,
    style_val: str | None,
) -> tuple[str, str | None, str | None]:
    """
    Prefer Semantic registry values when genre/style are still defaults.
    Returns (genre, style, mood_or_tone).
    """
    narrative = (knowledge or {}).get("narrative") or {}
    mood_out: str | None = None

    def _pick(aspect: str) -> str | None:
        entries = narrative.get(aspect) or []
        if not entries:
            return None
        # Prefer underused named entries
        scored = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            val = (e.get("value") or e.get("key") or e.get("name") or "").strip()
            if not val:
                continue
            scored.append((int(e.get("count", 0) or 0), val))
        if not scored:
            return None
        scored.sort(key=lambda t: t[0])
        # Bias toward lower count (underused)
        from ..random_utils import weighted_choice_favor_underused
        values = [v for _, v in scored]
        counts = {v: c for c, v in scored}
        chosen = weighted_choice_favor_underused(values, lambda v: counts.get(v, 0))
        return chosen or values[0]

    if genre_val in ("general", "", "default"):
        picked = _pick("genre")
        if picked:
            genre_val = picked.replace(" ", "_").lower()
    if not style_val or style_val in ("cinematic", "default"):
        # Only override default cinematic when registry has a clear style and we want variety
        picked = _pick("style")
        if picked and (not style_val or style_val == "default"):
            style_val = picked.replace(" ", "_").lower()
        elif picked and style_val == "cinematic":
            # 50% chance to explore registry style over default cinematic
            from ..random_utils import secure_random
            if secure_random() < 0.5:
                style_val = picked.replace(" ", "_").lower()
    mood_pick = _pick("mood")
    if mood_pick:
        mood_out = mood_pick.replace(" ", "_").lower()
    return genre_val, style_val, mood_out


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
