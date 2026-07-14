"""
Growth from per-instance extraction: add to registry if not found.
All three registries (static, dynamic, narrative) evolve via growth. Compare extracted
values to the appropriate registry; if novel, add with a sensible generated name when
unknown. grow_from_video() = static (color, sound); grow_dynamic_from_video() = dynamic
(non-pure, multi-frame, e.g. new styles from blending sunset + sunrise); narrative
via grow_narrative_from_spec(). Works with local JSON registries; can batch and sync
to API (D1) when api_base is set.
"""
from pathlib import Path
from typing import Any

from .extractor_per_instance import (
    extract_static_per_frame,
    extract_dynamic_per_window,
    read_video_once,
    _extract_static_from_preloaded,
    _extract_dynamic_from_preloaded,
)
from .static_registry import (
    load_static_registry,
    save_static_registry,
    STATIC_COLOR_PRIMITIVES,
    STATIC_SOUND_PRIMITIVES,
)
from .dynamic_registry import load_dynamic_registry, save_dynamic_registry
from .origins import get_all_origins
from .registry import _color_key
from .blend_names import generate_sensible_name


def _static_color_key(color: dict[str, Any], tolerance: int = 25, opacity_steps: int = 21) -> str:
    """Key includes R,G,B and opacity so each color at each level of opaqueness is distinct (pure blend)."""
    r = color.get("r", 0)
    g = color.get("g", 0)
    b = color.get("b", 0)
    opacity = float(color.get("opacity", 1.0))
    # Quantize opacity to steps 0, 0.05, ..., 1.0 so we name each level
    o_step = round(opacity * (opacity_steps - 1)) / (opacity_steps - 1) if opacity_steps > 1 else round(opacity, 2)
    rgb_key = _color_key(float(r), float(g), float(b), tolerance=tolerance)
    return f"{rgb_key}_{round(o_step, 2)}"


def _static_sound_key(sound: dict[str, Any]) -> str:
    """
    Standard key for pure sound (one instant): amplitude_tone_timbre.
    Per REGISTRY_FOUNDATION, Pure sound uses only primitive tones (low, mid, high, silent, neutral).
    Semantic mood words (calm, tense, dark, uplifting) are normalized to primitives so keys stay consistent.
    """
    if not sound:
        return ""
    from .blend_depth import normalize_tone_to_primitive, normalize_timbre_to_primitive
    amp = float(sound.get("amplitude") or sound.get("weight") or 0)
    raw_tone = (sound.get("tone") or "unknown").strip().lower()
    raw_timbre = (sound.get("timbre") or sound.get("primitive") or raw_tone or "unknown").strip().lower()
    tone = normalize_tone_to_primitive(raw_tone)
    timbre = normalize_timbre_to_primitive(raw_timbre, amplitude=amp, tone=tone)
    return f"{round(amp, 2)}_{tone}_{timbre}"


def derive_audio_semantic_from_spec(spec: Any) -> dict[str, Any]:
    """
    Build one audio_semantic dict from spec: role (ambient|music|sfx), mood, tempo.
    Recorded in DYNAMIC (audio_semantic) so spec-derived sound is non-pure / time-bound.
    """
    presence = getattr(spec, "audio_presence", None) or "ambient"
    role = "music" if presence == "full" else ("sfx" if presence == "sfx" else "ambient")
    mood = getattr(spec, "audio_mood", None) or "neutral"
    tempo = getattr(spec, "audio_tempo", None) or "medium"
    return {"role": role, "type": role, "mood": str(mood), "tempo": str(tempo), "presence": str(presence)}


def derive_static_sound_from_spec(
    spec: Any,
    *,
    prefer_primitives: list[str] | None = None,
) -> dict[str, Any]:
    """
    Build one static sound dict from creation spec (audio_mood, audio_tempo, audio_presence).
    Prefer under-touched origin noises (rustle/click/whoosh/…) when prefer_primitives is set
    so Pure sound coverage advances toward all SOUND_ORIGIN_PRIMITIVES.
    Per REGISTRY_FOUNDATION, Pure sound uses only primitive tones (low, mid, high, silent, neutral).
    """
    import random
    from .blend_depth import classify_sound_primitive, normalize_tone_to_primitive, SOUND_ORIGIN_PRIMITIVES
    mood = getattr(spec, "audio_mood", None) or "neutral"
    tempo = getattr(spec, "audio_tempo", None) or "medium"
    presence = getattr(spec, "audio_presence", None) or "ambient"
    weight = 0.3 if presence == "silence" else (0.7 if presence == "full" else 0.5)
    tone = normalize_tone_to_primitive(str(mood))
    if random.random() < 0.25:
        tone = random.choice(("mid", "neutral", "low", "high"))
    primitive = classify_sound_primitive(weight, tone)
    # Bias toward missing origin noises when coverage reports gaps (mission: touch every primitive).
    prefer = [p for p in (prefer_primitives or []) if p in SOUND_ORIGIN_PRIMITIVES and p != "silence"]
    if prefer and random.random() < 0.7:
        primitive = random.choice(prefer)
    elif random.random() < 0.45:
        # Slightly overweight under-discovered everyday noises vs tonal defaults.
        underused = ("rustle", "click", "whoosh", "drip", "thump", "hum", "hiss")
        pool = [p for p in underused if p in SOUND_ORIGIN_PRIMITIVES]
        if not pool:
            pool = [p for p in SOUND_ORIGIN_PRIMITIVES if p != "silence"]
        primitive = random.choice(pool)
    return {
        "amplitude": weight,
        "weight": weight,
        "tone": tone,
        "timbre": primitive,
        "primitive": primitive,
        "tempo": str(tempo),
    }


def _motion_key(motion: dict[str, Any]) -> str:
    level = motion.get("level", 0)
    trend = motion.get("trend", "steady")
    direction = motion.get("direction", "neutral")
    rhythm = motion.get("rhythm", "steady")
    return f"{round(float(level), 1)}_{trend}_{direction}_{rhythm}"


def _time_key(time_dict: dict[str, Any]) -> str:
    duration = time_dict.get("duration", 0)
    fps = time_dict.get("fps", 24)
    return f"{round(float(duration), 1)}_{round(float(fps), 1)}"


def _lighting_key(lighting: dict[str, Any]) -> str:
    b = lighting.get("brightness", 128)
    c = lighting.get("contrast", 50)
    s = lighting.get("saturation", 1.0)
    return f"{round(float(b) / 25) * 25}_{round(float(c), 1)}_{round(float(s), 1)}"


def _composition_key(comp: dict[str, Any]) -> str:
    cx = comp.get("center_x", 0.5)
    cy = comp.get("center_y", 0.5)
    lb = comp.get("luminance_balance", 0.5)
    return f"{round(float(cx), 2)}_{round(float(cy), 2)}_{round(float(lb), 2)}"


def _graphics_key(graphics: dict[str, Any]) -> str:
    ed = graphics.get("edge_density", 0)
    sv = graphics.get("spatial_variance", 0)
    busy = graphics.get("busyness", 0)
    return f"{round(float(ed), 2)}_{round(float(sv), 2)}_{round(float(busy), 2)}"


def _temporal_key(window: dict[str, Any]) -> str:
    motion = window.get("motion", {})
    trend = motion.get("trend", "steady")
    time_dict = window.get("time", {})
    duration = time_dict.get("duration", 1.0)
    return f"{round(float(duration), 1)}_{trend}"


def _technical_key(window: dict[str, Any], width: int = 0, height: int = 0, fps: float = 24) -> str:
    time_dict = window.get("time", {})
    f = time_dict.get("fps", fps)
    return f"{int(width)}x{int(height)}_{round(float(f), 1)}"


def _gradient_key(grad: dict[str, Any]) -> str:
    gtype = (grad.get("gradient_type") or "angled").strip().lower()
    strength = round(float(grad.get("strength", 0) or 0), 2)
    return f"{gtype}_{strength}"


def _camera_key(cam: dict[str, Any]) -> str:
    mtype = (cam.get("motion_type") or "static").strip().lower()
    speed = (cam.get("speed") or "medium").strip().lower()
    steadiness = (cam.get("steadiness") or "stable").strip().lower()
    return f"{mtype}_{speed}_{steadiness}"


def _transition_key(trans: dict[str, Any]) -> str:
    ttype = (trans.get("type") or "cut").strip().lower()
    dur = round(float(trans.get("duration_seconds", trans.get("duration", 0)) or 0), 2)
    return f"{ttype}_{dur}"


def _depth_key(dep: dict[str, Any]) -> str:
    para = round(float(dep.get("parallax_strength", 0) or 0), 2)
    layers = int(dep.get("layer_count", 1) or 1)
    return f"{para}_{layers}"


def _audio_semantic_key(audio: dict[str, Any]) -> str:
    role = (audio.get("role") or audio.get("type") or "ambient").strip().lower()
    mood = (audio.get("mood") or "").strip().lower()
    tempo = (audio.get("tempo") or "").strip().lower()
    if mood or tempo:
        return f"{role}_{mood}_{tempo}".rstrip("_")
    return role


def _entries_keys(data: dict[str, Any]) -> set[str]:
    return {e.get("key", "") for e in data.get("entries", []) if e.get("key")}


def ensure_static_color_in_registry(
    color: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """
    If this color is not in the static registry, add it with a sensible name.
    Returns the assigned name if added, else None (already present).
    If out_novel is provided and the color was added, appends the API payload to out_novel.
    When force_novel=True, always append the API payload (for D1 primitive reseed).
    """
    key = _static_color_key(color)
    if not key:
        return None
    data = load_static_registry("color", config)
    entries = data.get("entries", [])
    existing = {e.get("key", "") for e in entries if e.get("key")}
    r_val = max(0, min(255, float(color.get("r", 0))))
    g_val = max(0, min(255, float(color.get("g", 0))))
    b_val = max(0, min(255, float(color.get("b", 0))))
    opacity_val = max(0.0, min(1.0, float(color.get("opacity", 1.0))))
    from .blend_depth import compute_color_depth
    origin_colors = compute_color_depth(r_val, g_val, b_val)
    depth_breakdown: dict[str, Any] = {
        **{k: round(v * 100) for k, v in origin_colors.items()},
        "opacity": round(opacity_val * 100),
    }
    if key in existing:
        entries_by_key = {e.get("key"): e for e in entries if e.get("key")}
        e = entries_by_key.get(key)
        name = (e or {}).get("name") or ""
        if e is not None:
            e["count"] = e.get("count", 0) + 1
            if source_prompt and len(e.get("sources", [])) < 5:
                e.setdefault("sources", []).append(source_prompt[:80])
            if not e.get("depth_breakdown"):
                e["depth_breakdown"] = depth_breakdown
            name = e.get("name") or name
        save_static_registry("color", data, config)
        if force_novel and out_novel is not None:
            out_novel.append({
                "key": key,
                "r": round(r_val, 1), "g": round(g_val, 1), "b": round(b_val, 1),
                "opacity": round(opacity_val, 2),
                "depth_breakdown": e.get("depth_breakdown", depth_breakdown) if e else depth_breakdown,
                "source_prompt": source_prompt[:80] if source_prompt else "primitive_seed",
                "name": name,
            })
        return None
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    name = generate_sensible_name("color", key, existing_names=names, rgb_hint=(r_val, g_val, b_val))
    # Static = pure only: R, G, B, opacity; depth_breakdown = weights of origin + opaque level
    entry: dict[str, Any] = {
        "key": key,
        "r": round(r_val, 1),
        "g": round(g_val, 1),
        "b": round(b_val, 1),
        "opacity": round(opacity_val, 2),
        "name": name,
        "count": 1,
        "sources": [source_prompt[:80]] if source_prompt else ["primitive_seed"],
        "depth_breakdown": depth_breakdown,
    }
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_static_registry("color", data, config)
    if out_novel is not None:
        out_novel.append({
            "key": key,
            "r": entry["r"], "g": entry["g"], "b": entry["b"],
            "opacity": entry["opacity"],
            "depth_breakdown": depth_breakdown,
            "source_prompt": source_prompt[:80] if source_prompt else "primitive_seed",
            "name": name,
        })
    return name


def ensure_static_primitives_seeded(
    config: dict[str, Any] | None = None,
    *,
    out_colors: list[dict[str, Any]] | None = None,
    out_sounds: list[dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> dict[str, int]:
    """
    Seed the static registries (color + sound mesh) with origin/primitive values.
    Primitives are the base set; discovered blends are added by the loop. Idempotent.
    When out_colors/out_sounds are set (optionally with force_novel), collect API payloads for D1.
    """
    added = {"static_colors": 0, "static_sound": 0}
    for color in STATIC_COLOR_PRIMITIVES:
        if ensure_static_color_in_registry(
            color, source_prompt="primitive_seed", config=config, out_novel=out_colors, force_novel=force_novel
        ):
            added["static_colors"] += 1
        elif force_novel:
            added["static_colors"] += 0  # payload forced into out_colors
    for sound in STATIC_SOUND_PRIMITIVES:
        if ensure_static_sound_in_registry(
            sound, source_prompt="primitive_seed", config=config, out_novel=out_sounds, force_novel=force_novel
        ):
            added["static_sound"] += 1
    return added


def ensure_dynamic_primitives_seeded(
    config: dict[str, Any] | None = None,
    *,
    novel_for_sync: dict[str, list[dict[str, Any]]] | None = None,
    force_novel: bool = False,
) -> dict[str, int]:
    """
    Seed dynamic registry with all origin primitives so every known non-pure value exists.
    Covers: gradient, camera (type×speed×steadiness), transition (+durations), audio_semantic
    (tempo×mood×presence), motion axes, lighting axes, composition, graphics shapes,
    time, temporal, technical, depth. Idempotent.
    When novel_for_sync is provided, collect API payloads (use force_novel=True for D1 reseed).
    """
    origins = get_all_origins()
    seed = "primitive_seed"
    buckets = novel_for_sync if novel_for_sync is not None else {}
    counts: dict[str, int] = {}

    def _bucket(aspect: str) -> list[dict[str, Any]] | None:
        if novel_for_sync is None:
            return None
        if aspect not in buckets:
            buckets[aspect] = []
        return buckets[aspect]

    def _add(aspect: str, added_name: str | None) -> None:
        if added_name:
            counts[aspect] = counts.get(aspect, 0) + 1

    # Gradient
    for gtype in (origins.get("graphics") or {}).get("gradient_type", ["vertical", "horizontal", "radial", "angled"]):
        for strength in (0.0, 0.35, 0.7, 1.0):
            window = {"gradient": {"gradient_type": gtype, "strength": strength}}
            _add("gradient", ensure_dynamic_gradient_in_registry(
                window, source_prompt=seed, config=config, out_novel=_bucket("gradient"), force_novel=force_novel
            ))
    # Graphics: shape overlays + representative texture bands
    for shape in (origins.get("graphics") or {}).get("shape_overlay", ["none", "circle", "rect", "arrow", "character"]):
        # Encode shape in edge/busyness proxies until extractor stores shape explicitly.
        ed = 0.1 if shape == "none" else (0.35 if shape == "circle" else (0.45 if shape == "rect" else 0.55))
        window = {"graphics": {"edge_density": ed, "spatial_variance": ed * 0.8, "busyness": ed * 0.6, "shape_overlay": shape}}
        _add("graphics", ensure_dynamic_graphics_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("graphics"), force_novel=force_novel
        ))
    for ed, sv, busy in ((0.1, 0.1, 0.1), (0.3, 0.3, 0.25), (0.6, 0.5, 0.5), (0.9, 0.8, 0.85)):
        window = {"graphics": {"edge_density": ed, "spatial_variance": sv, "busyness": busy}}
        _add("graphics", ensure_dynamic_graphics_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("graphics"), force_novel=force_novel
        ))
    # Camera: full motion_type × speed × steadiness
    camera_origins = origins.get("camera") or {}
    for mtype in camera_origins.get("motion_type", []):
        for speed in camera_origins.get("speed", ["slow", "medium", "fast"]):
            for steadiness in camera_origins.get("steadiness", ["locked", "stable", "handheld", "shaky"]):
                window = {"camera": {"motion_type": mtype, "speed": speed, "steadiness": steadiness}}
                _add("camera", ensure_dynamic_camera_in_registry(
                    window, source_prompt=seed, config=config, out_novel=_bucket("camera"), force_novel=force_novel
                ))
    # Transition × duration
    transition_origins = origins.get("transition") or {}
    for ttype in transition_origins.get("type", ["cut", "fade", "dissolve", "wipe"]):
        for dur in transition_origins.get("duration_seconds", [0.0, 0.25, 0.5, 1.0]):
            window = {"transition": {"type": ttype, "duration_seconds": dur}}
            _add("transition", ensure_dynamic_transition_in_registry(
                window, source_prompt=seed, config=config, out_novel=_bucket("transition"), force_novel=force_novel
            ))
    # Audio semantic: full tempo × mood × presence grid
    audio_origins = origins.get("audio") or {}
    tempos = list(audio_origins.get("tempo", ["slow", "medium", "fast"]))
    moods = list(audio_origins.get("mood", ["neutral"]))
    presences = list(audio_origins.get("presence", ["silence", "ambient", "music", "sfx", "full"]))
    for presence in presences:
        role = (
            "ambient" if presence in ("silence", "ambient")
            else ("music" if presence == "music" else "sfx" if presence == "sfx" else "music")
        )
        for tempo in tempos:
            for mood in moods:
                window = {"audio_semantic": {"role": role, "mood": mood, "tempo": tempo, "presence": presence}}
                _add("audio_semantic", ensure_dynamic_audio_semantic_in_registry(
                    window, source_prompt=seed, config=config, out_novel=_bucket("audio_semantic"), force_novel=force_novel
                ))
    # Motion axes
    motion_origins = origins.get("motion") or {}
    level_by_speed = {"static": 0.0, "slow": 5.0, "medium": 12.0, "fast": 25.0}
    for speed in motion_origins.get("speed", ["static", "slow", "medium", "fast"]):
        level = level_by_speed.get(speed, 12.0)
        window = {"motion": {"level": level, "trend": "steady", "direction": "neutral", "rhythm": "steady"}}
        _add("motion", ensure_dynamic_motion_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("motion"), force_novel=force_novel
        ))
    for rhythm in motion_origins.get("rhythm", ["steady", "pulsing", "wave", "random"]):
        window = {"motion": {"level": 12.0, "trend": rhythm, "direction": "neutral", "rhythm": rhythm}}
        _add("motion", ensure_dynamic_motion_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("motion"), force_novel=force_novel
        ))
    for smoothness in motion_origins.get("smoothness", ["jerky", "rough", "smooth", "fluid"]):
        window = {"motion": {"level": 12.0, "trend": f"smoothness:{smoothness}", "direction": "neutral", "rhythm": "steady"}}
        _add("motion", ensure_dynamic_motion_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("motion"), force_novel=force_novel
        ))
    for directionality in motion_origins.get("directionality", ["none", "horizontal", "vertical", "diagonal", "radial"]):
        window = {"motion": {"level": 12.0, "trend": "steady", "direction": directionality, "rhythm": "steady"}}
        _add("motion", ensure_dynamic_motion_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("motion"), force_novel=force_novel
        ))
    for accel in motion_origins.get("acceleration", ["constant", "ease_in", "ease_out", "ease_in_out"]):
        window = {"motion": {"level": 12.0, "trend": f"accel:{accel}", "direction": "neutral", "rhythm": "steady"}}
        _add("motion", ensure_dynamic_motion_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("motion"), force_novel=force_novel
        ))
    # Lighting: contrast, temperature, key/fill/rim/ambient encoded via brightness/contrast/saturation
    lighting_origins = origins.get("lighting") or {}
    for ratio in lighting_origins.get("contrast_ratio", ["flat", "normal", "high", "chiaroscuro"]):
        contrast = 25 if ratio == "flat" else (50 if ratio == "normal" else (75 if ratio == "high" else 90))
        window = {"lighting": {"brightness": 125, "contrast": contrast, "saturation": 1.0}}
        _add("lighting", ensure_dynamic_lighting_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("lighting"), force_novel=force_novel
        ))
    temp_brightness = {"warm": 150, "neutral": 125, "cool": 100}
    for temp in lighting_origins.get("color_temperature", ["warm", "neutral", "cool"]):
        window = {
            "lighting": {
                "brightness": temp_brightness.get(temp, 125),
                "contrast": 50,
                "saturation": 1.1 if temp == "warm" else (0.9 if temp == "cool" else 1.0),
            }
        }
        _add("lighting", ensure_dynamic_lighting_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("lighting"), force_novel=force_novel
        ))
    for key_i in lighting_origins.get("key_intensity", [0.5, 0.75, 1.0, 1.25]):
        window = {"lighting": {"brightness": 80 + key_i * 80, "contrast": 50, "saturation": 1.0}}
        _add("lighting", ensure_dynamic_lighting_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("lighting"), force_novel=force_novel
        ))
    for fill in lighting_origins.get("fill_ratio", [0.2, 0.4, 0.6, 0.8]):
        window = {"lighting": {"brightness": 100 + fill * 40, "contrast": 30 + fill * 40, "saturation": 1.0}}
        _add("lighting", ensure_dynamic_lighting_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("lighting"), force_novel=force_novel
        ))
    for rim in lighting_origins.get("rim_strength", [0.0, 0.2, 0.5, 0.8]):
        window = {"lighting": {"brightness": 110 + rim * 30, "contrast": 55 + rim * 20, "saturation": 1.0 + rim * 0.1}}
        _add("lighting", ensure_dynamic_lighting_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("lighting"), force_novel=force_novel
        ))
    for ambient in lighting_origins.get("ambient_level", [0.2, 0.4, 0.6, 0.8]):
        window = {"lighting": {"brightness": 60 + ambient * 120, "contrast": 40, "saturation": 0.9 + ambient * 0.2}}
        _add("lighting", ensure_dynamic_lighting_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("lighting"), force_novel=force_novel
        ))
    # Composition
    composition_origins = origins.get("composition") or {}
    framing_centers = {
        "wide": (0.5, 0.5, 0.35),
        "medium": (0.5, 0.5, 0.5),
        "close": (0.5, 0.45, 0.65),
        "extreme_close": (0.5, 0.4, 0.8),
        "pov": (0.55, 0.5, 0.55),
    }
    for framing in composition_origins.get("framing", list(framing_centers.keys())):
        cx, cy, lb = framing_centers.get(framing, (0.5, 0.5, 0.5))
        window = {"composition": {"center_x": cx, "center_y": cy, "luminance_balance": lb, "framing": framing}}
        _add("composition", ensure_dynamic_composition_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("composition"), force_novel=force_novel
        ))
    balance_centers = [
        (0.2, 0.5, 0.5), (0.5, 0.5, 0.5), (0.8, 0.5, 0.5), (0.5, 0.2, 0.5), (0.5, 0.8, 0.5),
    ]
    for cx, cy, lb in balance_centers:
        window = {"composition": {"center_x": cx, "center_y": cy, "luminance_balance": lb}}
        _add("composition", ensure_dynamic_composition_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("composition"), force_novel=force_novel
        ))
    for symmetry in composition_origins.get("symmetry", ["asymmetric", "slight", "bilateral"]):
        offset = 0.12 if symmetry == "asymmetric" else (0.04 if symmetry == "slight" else 0.0)
        window = {"composition": {"center_x": 0.5 + offset, "center_y": 0.5, "luminance_balance": 0.5, "symmetry": symmetry}}
        _add("composition", ensure_dynamic_composition_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("composition"), force_novel=force_novel
        ))
    # Time
    for duration in (1.0, 2.0, 5.0, 10.0):
        for fps in (24.0, 30.0):
            window = {"time": {"duration": duration, "fps": fps}}
            _add("time", ensure_dynamic_time_in_registry(
                window, source_prompt=seed, config=config, out_novel=_bucket("time"), force_novel=force_novel
            ))
    # Temporal
    temporal_origins = origins.get("temporal") or {}
    for duration in temporal_origins.get("shot_length_seconds", [1.0, 2.0, 4.0, 6.0, 10.0]):
        window = {"time": {"duration": duration}, "motion": {"trend": "steady"}}
        _add("temporal", ensure_dynamic_temporal_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("temporal"), force_novel=force_novel
        ))
    for beat in temporal_origins.get("story_beats", ["setup", "development", "climax", "resolution"]):
        window = {"time": {"duration": 2.0}, "motion": {"trend": f"beat:{beat}"}}
        _add("temporal", ensure_dynamic_temporal_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("temporal"), force_novel=force_novel
        ))
    for cut in temporal_origins.get("cut_frequency", ["none", "rare", "normal", "fast", "rapid"]):
        window = {"time": {"duration": 1.0}, "motion": {"trend": f"cut:{cut}"}}
        _add("temporal", ensure_dynamic_temporal_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("temporal"), force_novel=force_novel
        ))
    for pacing in temporal_origins.get("pacing", [0.5, 0.75, 1.0, 1.25, 1.5]):
        window = {"time": {"duration": 2.0 * pacing}, "motion": {"trend": f"pacing:{pacing}"}}
        _add("temporal", ensure_dynamic_temporal_in_registry(
            window, source_prompt=seed, config=config, out_novel=_bucket("temporal"), force_novel=force_novel
        ))
    # Technical
    tech_origins = origins.get("technical") or {}
    for res in tech_origins.get("resolution", [(512, 512), (1280, 720), (1920, 1080)]):
        w, h = res[0], res[1]
        for fps in tech_origins.get("fps", [24, 30]):
            window = {"time": {"fps": float(fps)}}
            _add("technical", ensure_dynamic_technical_in_registry(
                window, width=w, height=h, fps=float(fps), source_prompt=seed, config=config,
                out_novel=_bucket("technical"), force_novel=force_novel
            ))
    # Depth
    depth_origins = origins.get("depth") or {}
    for para in depth_origins.get("parallax_strength", [0.0, 0.05, 0.1, 0.2]):
        for layers in depth_origins.get("layer_count", [1, 2, 3, 4]):
            window = {"depth": {"parallax_strength": para, "layer_count": layers}}
            _add("depth", ensure_dynamic_depth_in_registry(
                window, source_prompt=seed, config=config, out_novel=_bucket("depth"), force_novel=force_novel
            ))
    return counts


def ensure_static_sound_in_registry(
    sound: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """
    Record a pure sound (one instant/frame) in the mesh (static_sound registry).
    The mesh holds origin/primitive values (seeded) plus discovered blends. This value
    is stored as a blend of primitives (depth_breakdown = origin_noises). If novel,
    add with a sensible name so the mesh grows. Returns the assigned name if added,
    else None. No-op if sound is empty. If out_novel is set and added, appends payload.
    When force_novel=True, always append the API payload (for D1 primitive reseed).
    """
    if not sound:
        return None
    key = _static_sound_key(sound)
    if not key:
        return None
    data = load_static_registry("sound", config)
    entries = data.get("entries", [])
    existing = {e.get("key", "") for e in entries if e.get("key")}
    amp = float(sound.get("amplitude") or sound.get("weight") or 0)
    from .blend_depth import compute_sound_depth, normalize_tone_to_primitive
    raw_tone = (sound.get("tone") or "mid").strip()
    tone = normalize_tone_to_primitive(raw_tone)
    depth_breakdown = compute_sound_depth(
        amp, tone,
        primitive=sound.get("primitive"),
        spectral_flatness=sound.get("spectral_flatness"),
        attack_ratio=sound.get("attack_ratio"),
        zcr=sound.get("zcr"),
    )
    strength_pct = depth_breakdown.get("strength_pct") if isinstance(depth_breakdown, dict) else amp
    if key in existing:
        entries_by_key = {e.get("key"): e for e in entries if e.get("key")}
        e = entries_by_key.get(key)
        name = (e or {}).get("name") or ""
        if e is not None:
            e["count"] = e.get("count", 0) + 1
            if source_prompt:
                e.setdefault("sources", []).append(source_prompt[:80])
            if not e.get("depth_breakdown"):
                e["depth_breakdown"] = depth_breakdown
            name = e.get("name") or name
            strength_pct = e.get("strength_pct", strength_pct)
        save_static_registry("sound", data, config)
        if force_novel and out_novel is not None:
            out_novel.append({
                "key": key,
                "amplitude": (e or {}).get("amplitude", sound.get("amplitude")),
                "weight": (e or {}).get("weight", sound.get("weight")),
                "strength_pct": strength_pct,
                "tone": (e or {}).get("tone", sound.get("tone")),
                "timbre": (e or {}).get("timbre", sound.get("timbre")),
                "depth_breakdown": (e or {}).get("depth_breakdown", depth_breakdown),
                "source_prompt": source_prompt[:80] if source_prompt else "primitive_seed",
                "name": name,
            })
        return None
    names = {e.get("name", "") for e in entries if e.get("name")}
    name = generate_sensible_name("sound", key, existing_names=names)
    entry = {
        "key": key,
        "amplitude": sound.get("amplitude"),
        "weight": sound.get("weight"),
        "strength_pct": strength_pct,
        "tone": sound.get("tone"),
        "timbre": sound.get("timbre"),
        "tempo": sound.get("tempo", ""),
        "name": name,
        "count": 1,
        "sources": [source_prompt[:80]] if source_prompt else ["primitive_seed"],
        "depth_breakdown": depth_breakdown,
    }
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_static_registry("sound", data, config)
    if out_novel is not None:
        out_novel.append({
            "key": key,
            "amplitude": entry.get("amplitude"),
            "weight": entry.get("weight"),
            "strength_pct": strength_pct,
            "tone": entry.get("tone"),
            "timbre": entry.get("timbre"),
            "depth_breakdown": depth_breakdown,
            "source_prompt": source_prompt[:80] if source_prompt else "primitive_seed",
            "name": name,
        })
    return name


def grow_static_sound_from_audio_segments(
    audio_segments: list[dict[str, Any]],
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
    collect_novel_for_sync: bool = False,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Grow the pure-sound mesh (static_sound registry) from per-frame segments.
    Origin/primitive values are already in the mesh; each segment = one instant of noise,
    expressed as a blend of primitives (depth_breakdown). New discoveries are recorded
    in the registry; mesh is synced to the API and used next run. Returns: (added counts, novel payloads).
    """
    added: dict[str, Any] = {"static_sound": 0}
    novel_list: list[dict[str, Any]] = []
    ensure_static_primitives_seeded(config)
    out_novel = novel_list if collect_novel_for_sync else None
    for sound in audio_segments:
        if ensure_static_sound_in_registry(
            sound, source_prompt=prompt, config=config, out_novel=out_novel
        ):
            added["static_sound"] += 1
    return added, novel_list


DYNAMIC_ASPECTS = (
    "motion", "time", "gradient", "camera", "lighting", "composition",
    "graphics", "temporal", "technical", "audio_semantic", "transition", "depth",
)


def _ensure_dynamic_in_registry(
    aspect: str,
    key: str,
    entry_payload: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    api_payload: dict[str, Any] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """Generic: add one dynamic entry if key not in registry. Returns name if added.
    When registry_cache is provided, uses cached registry data to avoid repeated disk reads.
    When force_novel=True, append API payload even if the key already exists (D1 reseed)."""
    if registry_cache is not None and aspect in registry_cache:
        data = registry_cache[aspect]
    else:
        data = load_dynamic_registry(aspect, config)
        if registry_cache is not None:
            registry_cache[aspect] = data
    existing = _entries_keys(data)
    if key in existing:
        name = ""
        for e in data.get("entries", []):
            if e.get("key") == key:
                e["count"] = e.get("count", 0) + 1
                if source_prompt:
                    e.setdefault("sources", []).append(source_prompt[:80])
                name = e.get("name") or ""
                break
        save_dynamic_registry(aspect, data, config)
        if force_novel and out_novel is not None and api_payload is not None:
            payload = {**api_payload, "source_prompt": source_prompt[:80] if source_prompt else "primitive_seed"}
            if name:
                payload["name"] = name
            out_novel.append(payload)
        return None
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    name = generate_sensible_name(aspect, key, existing_names=names)
    entry = {"key": key, "name": name, "count": 1, "sources": [source_prompt[:80]] if source_prompt else ["primitive_seed"], **entry_payload}
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_dynamic_registry(aspect, data, config)
    if out_novel is not None and api_payload is not None:
        out_novel.append({**api_payload, "name": name, "source_prompt": source_prompt[:80] if source_prompt else "primitive_seed"})
    return name


def ensure_dynamic_motion_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    from .blend_depth import compute_motion_depth
    motion = window.get("motion", {})
    key = _motion_key(motion)
    motion_level = float(motion.get("level", 0))
    motion_trend = str(motion.get("trend", "steady"))
    motion_std = float(motion.get("std") if motion.get("std") is not None else 0.0)
    payload = {
        "motion_level": motion_level,
        "motion_std": motion_std,
        "motion_trend": motion_trend,
        "motion_direction": motion.get("direction", "neutral"),
        "motion_rhythm": motion.get("rhythm", "steady"),
        "depth_breakdown": compute_motion_depth(motion_level, motion_trend),
    }
    api = {
        "key": key,
        "motion_level": payload["motion_level"],
        "motion_std": payload["motion_std"],
        "motion_trend": payload["motion_trend"],
        "motion_direction": payload["motion_direction"],
        "motion_rhythm": payload["motion_rhythm"],
        "depth_breakdown": compute_motion_depth(motion_level, motion_trend),
    }
    return _ensure_dynamic_in_registry("motion", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_time_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    time_dict = window.get("time", {})
    key = _time_key(time_dict)
    payload = {"duration": time_dict.get("duration"), "fps": time_dict.get("fps"), "rate": time_dict.get("rate", time_dict.get("fps"))}
    api = {"key": key, "duration": payload["duration"], "fps": payload["fps"], "rate": payload.get("rate", payload["fps"])}
    return _ensure_dynamic_in_registry("time", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_lighting_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    from .blend_depth import compute_lighting_depth
    lighting = window.get("lighting", {})
    key = _lighting_key(lighting)
    brightness = float(lighting.get("brightness", 128))
    contrast = float(lighting.get("contrast", 50))
    saturation = float(lighting.get("saturation", 1.0))
    depth = compute_lighting_depth(brightness, contrast, saturation)
    payload = {**dict(lighting), "depth_breakdown": depth}
    api = {
        "key": key,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("lighting", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_composition_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    from .blend_depth import compute_composition_depth
    comp = window.get("composition", {})
    key = _composition_key(comp)
    cx = float(comp.get("center_x", 0.5))
    cy = float(comp.get("center_y", 0.5))
    lb = float(comp.get("luminance_balance", 0.5))
    depth = compute_composition_depth(cx, cy, lb)
    payload = {**dict(comp), "depth_breakdown": depth}
    api = {
        "key": key,
        "center_x": cx,
        "center_y": cy,
        "luminance_balance": lb,
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("composition", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_graphics_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    from .blend_depth import compute_graphics_depth
    graphics = window.get("graphics", {})
    key = _graphics_key(graphics)
    ed = float(graphics.get("edge_density", 0))
    sv = float(graphics.get("spatial_variance", 0))
    busy = float(graphics.get("busyness", 0))
    depth = compute_graphics_depth(ed, sv, busy)
    payload = {**dict(graphics), "depth_breakdown": depth}
    api = {
        "key": key,
        "edge_density": ed,
        "spatial_variance": sv,
        "busyness": busy,
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("graphics", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_temporal_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    from .blend_depth import compute_temporal_depth
    key = _temporal_key(window)
    time_dict = window.get("time", {})
    motion = window.get("motion", {})
    duration = float(time_dict.get("duration", 5))
    motion_trend = str(motion.get("trend", "steady"))
    depth = compute_temporal_depth(duration, motion_trend)
    payload = {"duration": duration, "motion_trend": motion_trend, "depth_breakdown": depth}
    api = {
        "key": key,
        "duration": payload["duration"],
        "motion_trend": payload["motion_trend"],
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("temporal", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_technical_in_registry(
    window: dict[str, Any],
    *,
    width: int = 0,
    height: int = 0,
    fps: float = 24,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    from .blend_depth import compute_technical_depth
    time_dict = window.get("time", {})
    f = float(time_dict.get("fps", fps))
    w = int(width or 512)
    h = int(height or 512)
    key = _technical_key(window, width=w, height=h, fps=f)
    depth = compute_technical_depth(w, h, f)
    payload = {"width": w, "height": h, "fps": f, "depth_breakdown": depth}
    api = {
        "key": key,
        "width": w,
        "height": h,
        "fps": f,
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("technical", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_gradient_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """Add gradient (type + strength) to dynamic registry if novel."""
    grad = window.get("gradient", {})
    if not grad:
        return None
    key = _gradient_key(grad)
    gradient_type = grad.get("gradient_type", "angled")
    depth = {gradient_type: 1.0}
    payload = {"gradient_type": gradient_type, "strength": grad.get("strength", 0), "depth_breakdown": depth}
    api = {
        "key": key,
        "gradient_type": payload["gradient_type"],
        "strength": payload["strength"],
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("gradient", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_camera_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """Add camera motion (type + speed) to dynamic registry if novel."""
    cam = window.get("camera", {})
    if not cam:
        return None
    key = _camera_key(cam)
    motion_type = cam.get("motion_type", "static")
    speed = cam.get("speed", "medium")
    steadiness = cam.get("steadiness", "stable")
    depth = {motion_type: 1.0}
    payload = {
        "motion_type": motion_type,
        "speed": speed,
        "steadiness": steadiness,
        "depth_breakdown": depth,
    }
    api = {
        "key": key,
        "motion_type": motion_type,
        "speed": speed,
        "steadiness": steadiness,
        "depth_breakdown": depth,
    }
    return _ensure_dynamic_in_registry("camera", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_transition_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """Add transition (type, duration) to dynamic registry if novel."""
    trans = window.get("transition", {})
    if not trans or not trans.get("type"):
        return None
    key = _transition_key(trans)
    ttype = trans.get("type", "cut")
    depth = {ttype: 1.0}
    payload = {"type": ttype, "duration_seconds": trans.get("duration_seconds", trans.get("duration", 0)), "depth_breakdown": depth}
    api = {"key": key, "type": payload["type"], "duration_seconds": payload["duration_seconds"], "depth_breakdown": depth}
    return _ensure_dynamic_in_registry("transition", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_depth_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """Add depth (parallax, layer_count) to dynamic registry if novel."""
    dep = window.get("depth", {})
    if not dep:
        return None
    key = _depth_key(dep)
    parallax = dep.get("parallax_strength", 0)
    layers = dep.get("layer_count", 1)
    depth = {"parallax_strength": round(float(parallax), 3), "layer_count": int(layers)}
    payload = {"parallax_strength": parallax, "layer_count": layers, "depth_breakdown": depth}
    api = {"key": key, "parallax_strength": payload["parallax_strength"], "layer_count": payload["layer_count"], "depth_breakdown": depth}
    return _ensure_dynamic_in_registry("depth", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def ensure_dynamic_audio_semantic_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
    force_novel: bool = False,
) -> str | None:
    """Add audio_semantic (role, mood, tempo) to dynamic registry if novel."""
    audio = window.get("audio_semantic", {})
    if not audio:
        return None
    key = _audio_semantic_key(audio)
    if not key:
        return None
    role = audio.get("role", "ambient")
    mood = (audio.get("mood") or "").strip()
    tempo = (audio.get("tempo") or "").strip()
    presence = (audio.get("presence") or "").strip()
    payload = {
        "role": role,
        "type": audio.get("type", role),
        "mood": mood,
        "tempo": tempo,
        "presence": presence,
    }
    # Depth breakdown: what this non-pure blend consists of (per REGISTRY_FOUNDATION)
    depth_breakdown: dict[str, Any] = {"role": role, "mood": mood or "neutral", "tempo": tempo or "medium", "presence": presence or "ambient"}
    payload["depth_breakdown"] = depth_breakdown
    api = {"key": key, "role": role, "mood": mood, "tempo": tempo, "depth_breakdown": depth_breakdown}
    return _ensure_dynamic_in_registry("audio_semantic", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache, force_novel=force_novel)


def grow_from_video(
    video_path: str | Path,
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
    max_frames: int | None = None,
    sample_every: int = 1,
    window_seconds: float = 1.0,
    collect_novel_for_sync: bool = False,
    spec: Any = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Run per-frame static extraction only; add every novel static value to the registry
    with a sensible name. Growth does not touch dynamic elements (motion, lighting, etc.)
    so that algorithmic/functional precision is preserved.

    When spec is provided and collect_novel_for_sync, also records one spec-derived static
    sound (from audio_mood/tempo/presence) so sound learning is active before per-frame
    audio extraction exists.

    Returns:
        added: counts per aspect (static_colors, static_sound only).
        novel_for_sync: if collect_novel_for_sync, payloads to POST to API
          (static_colors, static_sound only). Dynamic keys are absent; use other
          recording paths for dynamic registries if needed.
    """
    added: dict[str, Any] = {
        "static_colors": 0,
        "static_sound": 0,
    }
    novel_for_sync: dict[str, list[dict[str, Any]]] = {
        "static_colors": [],
        "static_sound": [],
    }
    path = Path(video_path)
    if not path.exists():
        return added, novel_for_sync

    ensure_static_primitives_seeded(config)

    out_static_colors = novel_for_sync["static_colors"] if collect_novel_for_sync else None
    out_sound = novel_for_sync["static_sound"] if collect_novel_for_sync else None

    # Static only: every frame (color + sound); primitives already seeded above
    for frame in extract_static_per_frame(
        path, max_frames=max_frames, sample_every=sample_every
    ):
        if ensure_static_color_in_registry(
            frame.get("color", {}),
            source_prompt=prompt,
            config=config,
            out_novel=out_static_colors,
        ):
            added["static_colors"] += 1
        if ensure_static_sound_in_registry(
            frame.get("sound", {}), source_prompt=prompt, config=config, out_novel=out_sound
        ):
            added["static_sound"] += 1

    # Spec-derived sound (mood/tempo/presence) is recorded in DYNAMIC, not static.
    # See grow_dynamic_from_video: derive_audio_semantic_from_spec with mood/tempo.

    return added, novel_for_sync


def grow_dynamic_from_video(
    video_path: str | Path,
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
    max_frames: int | None = None,
    sample_every: int = 1,
    window_seconds: float = 1.0,
    collect_novel_for_sync: bool = False,
    spec: Any = None,
) -> tuple[dict[str, Any], dict[str, list[dict[str, Any]]]]:
    """
    Growth in the DYNAMIC registry: add novel non-pure (multi-frame) values
    with a sensible name when unknown. Each window = 2+ frames combined;
    values (motion, time, lighting, etc.) are compared to the dynamic registry;
    if novel → add with name. Blending non-pure blends (e.g. sunset + sunrise)
    can form new non-pure blends that become new 'styles' in the dynamic registry.
    All three registries (static, dynamic, narrative) evolve via growth; unknown
    elements/blends get a sensible generated name in every registry.

    Returns:
        added: counts per dynamic aspect (motion, time, lighting, ...).
        novel_for_sync: if collect_novel_for_sync, payloads for API (dynamic keys only).
    """
    from .extractor_per_instance import _read_frames

    added: dict[str, Any] = {
        "dynamic_motion": 0,
        "dynamic_time": 0,
        "dynamic_gradient": 0,
        "dynamic_camera": 0,
        "dynamic_lighting": 0,
        "dynamic_composition": 0,
        "dynamic_graphics": 0,
        "dynamic_temporal": 0,
        "dynamic_technical": 0,
        "dynamic_audio_semantic": 0,
        "dynamic_transition": 0,
        "dynamic_depth": 0,
    }
    novel_for_sync: dict[str, list[dict[str, Any]]] = {
        "motion": [],
        "time": [],
        "gradient": [],
        "camera": [],
        "lighting": [],
        "composition": [],
        "graphics": [],
        "temporal": [],
        "technical": [],
        "audio_semantic": [],
        "transition": [],
        "depth": [],
    }
    path = Path(video_path)
    if not path.exists():
        return added, novel_for_sync

    ensure_dynamic_primitives_seeded(config)

    _, fps, width, height = _read_frames(path, max_frames=max_frames, sample_every=sample_every)
    out_motion = novel_for_sync["motion"] if collect_novel_for_sync else None
    out_time = novel_for_sync["time"] if collect_novel_for_sync else None
    out_gradient = novel_for_sync["gradient"] if collect_novel_for_sync else None
    out_camera = novel_for_sync["camera"] if collect_novel_for_sync else None
    out_lighting = novel_for_sync["lighting"] if collect_novel_for_sync else None
    out_composition = novel_for_sync["composition"] if collect_novel_for_sync else None
    out_graphics = novel_for_sync["graphics"] if collect_novel_for_sync else None
    out_temporal = novel_for_sync["temporal"] if collect_novel_for_sync else None
    out_technical = novel_for_sync["technical"] if collect_novel_for_sync else None
    out_audio_semantic = novel_for_sync["audio_semantic"] if collect_novel_for_sync else None
    out_transition = novel_for_sync["transition"] if collect_novel_for_sync else None
    out_depth = novel_for_sync["depth"] if collect_novel_for_sync else None

    registry_cache: dict[str, dict[str, Any]] = {}

    for window in extract_dynamic_per_window(
        path, window_seconds=window_seconds, max_frames=max_frames, sample_every=sample_every
    ):
        if ensure_dynamic_motion_in_registry(window, source_prompt=prompt, config=config, out_novel=out_motion):
            added["dynamic_motion"] += 1
        if ensure_dynamic_time_in_registry(window, source_prompt=prompt, config=config, out_novel=out_time, registry_cache=registry_cache):
            added["dynamic_time"] += 1
        if ensure_dynamic_gradient_in_registry(window, source_prompt=prompt, config=config, out_novel=out_gradient, registry_cache=registry_cache):
            added["dynamic_gradient"] += 1
        if ensure_dynamic_camera_in_registry(window, source_prompt=prompt, config=config, out_novel=out_camera, registry_cache=registry_cache):
            added["dynamic_camera"] += 1
        if ensure_dynamic_lighting_in_registry(window, source_prompt=prompt, config=config, out_novel=out_lighting, registry_cache=registry_cache):
            added["dynamic_lighting"] += 1
        if ensure_dynamic_composition_in_registry(window, source_prompt=prompt, config=config, out_novel=out_composition, registry_cache=registry_cache):
            added["dynamic_composition"] += 1
        if ensure_dynamic_graphics_in_registry(window, source_prompt=prompt, config=config, out_novel=out_graphics, registry_cache=registry_cache):
            added["dynamic_graphics"] += 1
        if ensure_dynamic_temporal_in_registry(window, source_prompt=prompt, config=config, out_novel=out_temporal, registry_cache=registry_cache):
            added["dynamic_temporal"] += 1
        if ensure_dynamic_technical_in_registry(
            window, width=width, height=height, fps=fps, source_prompt=prompt, config=config, out_novel=out_technical, registry_cache=registry_cache
        ):
            added["dynamic_technical"] += 1
        if ensure_dynamic_audio_semantic_in_registry(window, source_prompt=prompt, config=config, out_novel=out_audio_semantic, registry_cache=registry_cache):
            added["dynamic_audio_semantic"] += 1
        if ensure_dynamic_transition_in_registry(window, source_prompt=prompt, config=config, out_novel=out_transition, registry_cache=registry_cache):
            added["dynamic_transition"] += 1
        if ensure_dynamic_depth_in_registry(window, source_prompt=prompt, config=config, out_novel=out_depth, registry_cache=registry_cache):
            added["dynamic_depth"] += 1

    if spec is not None:
        audio_semantic = derive_audio_semantic_from_spec(spec)
        fake_window = {"audio_semantic": audio_semantic}
        if ensure_dynamic_audio_semantic_in_registry(fake_window, source_prompt=prompt, config=config, out_novel=out_audio_semantic, registry_cache=registry_cache):
            added["dynamic_audio_semantic"] += 1

    return added, novel_for_sync


def grow_all_from_video(
    video_path: str | Path,
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
    max_frames: int | None = None,
    sample_every: int = 1,
    window_seconds: float = 1.0,
    collect_novel_for_sync: bool = False,
    spec: Any = None,
    extraction_focus: str = "all",
    static_focus: str = "both",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Unified growth: single video read for both static and dynamic extraction.
    Runs per-frame static growth (color, sound) and per-window dynamic growth
    (motion, lighting, gradient, camera, etc.) in one pass.
    extraction_focus: "all" (default) | "frame" | "window"
      - "frame": only per-frame extraction and static growth (pure/static registry); all new values get authentic names.
      - "window": only per-window extraction and dynamic growth (+ narrative from spec); blends only.
      - "all": both (current behaviour).
    static_focus: "both" (default) | "color" | "sound"
      - When doing frame extraction: "color" = grow only static_colors; "sound" = grow only static_sound; "both" = both.
    Returns: (added, novel_for_sync) with combined counts and payloads.
    """
    added: dict[str, Any] = {
        "static_colors": 0,
        "static_sound": 0,
        "dynamic_motion": 0,
        "dynamic_time": 0,
        "dynamic_gradient": 0,
        "dynamic_camera": 0,
        "dynamic_lighting": 0,
        "dynamic_composition": 0,
        "dynamic_graphics": 0,
        "dynamic_temporal": 0,
        "dynamic_technical": 0,
        "dynamic_audio_semantic": 0,
        "dynamic_transition": 0,
        "dynamic_depth": 0,
    }
    novel_for_sync: dict[str, Any] = {
        "static_colors": [],
        "static_sound": [],
        "motion": [],
        "time": [],
        "gradient": [],
        "camera": [],
        "lighting": [],
        "composition": [],
        "graphics": [],
        "temporal": [],
        "technical": [],
        "audio_semantic": [],
        "transition": [],
        "depth": [],
    }
    path = Path(video_path)
    if not path.exists():
        return added, novel_for_sync

    do_frame = extraction_focus in ("all", "frame")
    do_window = extraction_focus in ("all", "window")

    ensure_static_primitives_seeded(config) if do_frame else None
    ensure_dynamic_primitives_seeded(config) if do_window else None

    try:
        frames, fps, width, height, audio_segments = read_video_once(
            path, max_frames=max_frames, sample_every=sample_every
        )
    except (FileNotFoundError, ValueError) as e:
        import logging
        logging.getLogger(__name__).warning("grow_all_from_video: could not read video: %s", e)
        return added, novel_for_sync

    out_static_colors = novel_for_sync["static_colors"] if (collect_novel_for_sync and (do_frame or do_window)) else None
    out_sound = novel_for_sync["static_sound"] if (collect_novel_for_sync and do_frame) else None

    do_static_color = do_frame and (static_focus in ("both", "color"))
    do_static_sound = do_frame and (static_focus in ("both", "sound"))
    if do_frame:
        for frame in _extract_static_from_preloaded(frames, fps, audio_segments):
            if do_static_color and ensure_static_color_in_registry(
                frame.get("color", {}),
                source_prompt=prompt,
                config=config,
                out_novel=out_static_colors,
            ):
                added["static_colors"] += 1
            if do_static_sound and ensure_static_sound_in_registry(
                frame.get("sound", {}), source_prompt=prompt, config=config, out_novel=out_sound
            ):
                added["static_sound"] += 1
        # When decoded audio was empty (or no segments), still grow static_sound from spec so the registry gets entries
        if do_static_sound and spec and added["static_sound"] == 0:
            spec_sound = derive_static_sound_from_spec(spec)
            if spec_sound and ensure_static_sound_in_registry(
                spec_sound, source_prompt=prompt, config=config, out_novel=out_sound
            ):
                added["static_sound"] += 1

    out_motion = novel_for_sync["motion"] if (collect_novel_for_sync and do_window) else None
    out_time = novel_for_sync["time"] if (collect_novel_for_sync and do_window) else None
    out_gradient = novel_for_sync["gradient"] if (collect_novel_for_sync and do_window) else None
    out_camera = novel_for_sync["camera"] if (collect_novel_for_sync and do_window) else None
    out_lighting = novel_for_sync["lighting"] if (collect_novel_for_sync and do_window) else None
    out_composition = novel_for_sync["composition"] if (collect_novel_for_sync and do_window) else None
    out_graphics = novel_for_sync["graphics"] if (collect_novel_for_sync and do_window) else None
    out_temporal = novel_for_sync["temporal"] if (collect_novel_for_sync and do_window) else None
    out_technical = novel_for_sync["technical"] if (collect_novel_for_sync and do_window) else None
    out_audio_semantic = novel_for_sync["audio_semantic"] if (collect_novel_for_sync and do_window) else None
    out_transition = novel_for_sync["transition"] if (collect_novel_for_sync and do_window) else None
    out_depth = novel_for_sync["depth"] if (collect_novel_for_sync and do_window) else None

    registry_cache: dict[str, dict[str, Any]] = {}

    if do_window:
        for window in _extract_dynamic_from_preloaded(
            frames, fps, width, height,
            window_seconds=window_seconds,
            audio_segments=audio_segments,
        ):
            # Strict: window temporal blend (pixels combined over 1s) → new pure value if novel (e.g. black+white→grey)
            tb = window.get("temporal_blend_rgb")
            if tb and len(tb) >= 3:
                if ensure_static_color_in_registry(
                    {"r": tb[0], "g": tb[1], "b": tb[2], "opacity": 1.0},
                    source_prompt=prompt,
                    config=config,
                    out_novel=out_static_colors,
                ):
                    added["static_colors"] += 1
            if ensure_dynamic_motion_in_registry(window, source_prompt=prompt, config=config, out_novel=out_motion, registry_cache=registry_cache):
                added["dynamic_motion"] += 1
            if ensure_dynamic_time_in_registry(window, source_prompt=prompt, config=config, out_novel=out_time, registry_cache=registry_cache):
                added["dynamic_time"] += 1
            if ensure_dynamic_gradient_in_registry(window, source_prompt=prompt, config=config, out_novel=out_gradient, registry_cache=registry_cache):
                added["dynamic_gradient"] += 1
            if ensure_dynamic_camera_in_registry(window, source_prompt=prompt, config=config, out_novel=out_camera, registry_cache=registry_cache):
                added["dynamic_camera"] += 1
            if ensure_dynamic_lighting_in_registry(window, source_prompt=prompt, config=config, out_novel=out_lighting, registry_cache=registry_cache):
                added["dynamic_lighting"] += 1
            if ensure_dynamic_composition_in_registry(window, source_prompt=prompt, config=config, out_novel=out_composition, registry_cache=registry_cache):
                added["dynamic_composition"] += 1
            if ensure_dynamic_graphics_in_registry(window, source_prompt=prompt, config=config, out_novel=out_graphics, registry_cache=registry_cache):
                added["dynamic_graphics"] += 1
            if ensure_dynamic_temporal_in_registry(window, source_prompt=prompt, config=config, out_novel=out_temporal, registry_cache=registry_cache):
                added["dynamic_temporal"] += 1
            if ensure_dynamic_technical_in_registry(
                window, width=width, height=height, fps=fps, source_prompt=prompt, config=config, out_novel=out_technical, registry_cache=registry_cache
            ):
                added["dynamic_technical"] += 1
            if ensure_dynamic_audio_semantic_in_registry(window, source_prompt=prompt, config=config, out_novel=out_audio_semantic, registry_cache=registry_cache):
                added["dynamic_audio_semantic"] += 1
            if ensure_dynamic_transition_in_registry(window, source_prompt=prompt, config=config, out_novel=out_transition, registry_cache=registry_cache):
                added["dynamic_transition"] += 1
            if ensure_dynamic_depth_in_registry(window, source_prompt=prompt, config=config, out_novel=out_depth, registry_cache=registry_cache):
                added["dynamic_depth"] += 1

        if spec is not None:
            audio_semantic = derive_audio_semantic_from_spec(spec)
            fake_window = {"audio_semantic": audio_semantic}
            if ensure_dynamic_audio_semantic_in_registry(fake_window, source_prompt=prompt, config=config, out_novel=out_audio_semantic, registry_cache=registry_cache):
                added["dynamic_audio_semantic"] += 1

    return added, novel_for_sync
