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
    if not sound:
        return ""
    amp = sound.get("amplitude") or sound.get("weight") or 0
    tone = sound.get("tone") or "unknown"
    timbre = sound.get("timbre") or ""
    tempo = sound.get("tempo") or ""
    return f"{round(float(amp), 2)}_{tone}_{timbre}_{tempo}".rstrip("_")


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


def derive_static_sound_from_spec(spec: Any) -> dict[str, Any]:
    """
    Build one static sound dict from creation spec (audio_mood, audio_tempo, audio_presence).
    Use when per-frame audio extraction is not yet implemented, so we still record intended sound.
    Key includes mood, tempo, presence so each combo becomes a distinct registry entry.
    """
    mood = getattr(spec, "audio_mood", None) or "neutral"
    tempo = getattr(spec, "audio_tempo", None) or "medium"
    presence = getattr(spec, "audio_presence", None) or "ambient"
    weight = 0.3 if presence == "silence" else (0.7 if presence == "full" else 0.5)
    return {
        "amplitude": weight,
        "weight": weight,
        "tone": str(mood),
        "timbre": str(presence),
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
    return f"{mtype}_{speed}"


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
) -> str | None:
    """
    If this color is not in the static registry, add it with a sensible name.
    Returns the assigned name if added, else None (already present).
    If out_novel is provided and the color was added, appends the API payload to out_novel.
    """
    key = _static_color_key(color)
    if not key:
        return None
    data = load_static_registry("color", config)
    existing = _entries_keys(data)
    if key in existing:
        for e in data.get("entries", []):
            if e.get("key") == key:
                e["count"] = e.get("count", 0) + 1
                if source_prompt and len(e.get("sources", [])) < 5:
                    e.setdefault("sources", []).append(source_prompt[:80])
                break
        save_static_registry("color", data, config)
        return None
    r_val = float(color.get("r", 0))
    g_val = float(color.get("g", 0))
    b_val = float(color.get("b", 0))
    opacity_val = float(color.get("opacity", 1.0))
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    name = generate_sensible_name("color", key, existing_names=names, rgb_hint=(r_val, g_val, b_val))
    # Depth breakdown required: origin color % and opacity level (per REGISTRY_FOUNDATION)
    from .blend_depth import compute_color_depth
    origin_colors = compute_color_depth(r_val, g_val, b_val)
    # Flat structure: primitive weights (0–1) + opacity; API/backfill expect flattenable depth
    depth_breakdown: dict[str, Any] = {
        **{k: round(v * 100) for k, v in origin_colors.items()},
        "opacity": round(opacity_val * 100),
    }
    # Static = pure only: R, G, B, opacity; depth_breakdown = weights of origin + opaque level
    entry: dict[str, Any] = {
        "key": key,
        "r": round(r_val, 1),
        "g": round(g_val, 1),
        "b": round(b_val, 1),
        "opacity": round(opacity_val, 2),
        "name": name,
        "count": 1,
        "sources": [source_prompt[:80]] if source_prompt else [],
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
            "source_prompt": source_prompt[:80] if source_prompt else "",
            "name": name,
        })
    return name


def ensure_static_primitives_seeded(config: dict[str, Any] | None = None) -> None:
    """
    Ensure every primitive (origin) color and sound is in the static registry.
    Idempotent: only adds entries whose key is missing. Call at start of grow_from_video.
    """
    for color in STATIC_COLOR_PRIMITIVES:
        ensure_static_color_in_registry(color, config=config)
    for sound in STATIC_SOUND_PRIMITIVES:
        ensure_static_sound_in_registry(sound, config=config)


def ensure_dynamic_primitives_seeded(config: dict[str, Any] | None = None) -> None:
    """
    Seed dynamic registry with origin primitives (gradient, camera, transition, audio_semantic)
    so every known non-pure origin exists for depth and workflow. Idempotent.
    """
    origins = get_all_origins()
    for gtype in (origins.get("graphics") or {}).get("gradient_type", ["vertical", "horizontal", "radial", "angled"]):
        window = {"gradient": {"gradient_type": gtype, "strength": 0.0}}
        ensure_dynamic_gradient_in_registry(window, config=config)
    for mtype in (origins.get("camera") or {}).get("motion_type", ["static", "pan", "tilt", "dolly", "crane", "zoom", "zoom_out", "handheld"]):
        window = {"camera": {"motion_type": mtype, "speed": "medium"}}
        ensure_dynamic_camera_in_registry(window, config=config)
    for ttype in (origins.get("transition") or {}).get("type", ["cut", "fade", "dissolve", "wipe"]):
        window = {"transition": {"type": ttype, "duration_seconds": 0.0}}
        ensure_dynamic_transition_in_registry(window, config=config)
    # Audio semantic: one canonical entry per presence (role) so origins are seeded
    audio_origins = origins.get("audio") or {}
    for presence in audio_origins.get("presence", ["silence", "ambient", "music", "sfx", "full"]):
        role = "ambient" if presence in ("silence", "ambient") else ("music" if presence == "music" else "sfx" if presence == "sfx" else "music")
        window = {"audio_semantic": {"role": role, "mood": "neutral", "tempo": "medium", "presence": presence}}
        ensure_dynamic_audio_semantic_in_registry(window, config=config)


def ensure_static_sound_in_registry(
    sound: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    If this sound profile is not in the static registry, add it with a sensible name.
    Returns the assigned name if added, else None. No-op if sound is empty (no audio extraction yet).
    If out_novel is provided and the sound was added, appends the API payload to out_novel.
    """
    if not sound:
        return None
    key = _static_sound_key(sound)
    if not key:
        return None
    data = load_static_registry("sound", config)
    existing = _entries_keys(data)
    if key in existing:
        for e in data.get("entries", []):
            if e.get("key") == key:
                e["count"] = e.get("count", 0) + 1
                if source_prompt:
                    e.setdefault("sources", []).append(source_prompt[:80])
                break
        save_static_registry("sound", data, config)
        return None
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    name = generate_sensible_name("sound", key, existing_names=names)
    amp = float(sound.get("amplitude") or sound.get("weight") or 0)
    tone = (sound.get("tone") or "mid").strip()
    from .blend_depth import compute_sound_depth
    depth_breakdown = compute_sound_depth(amp, tone)
    strength_pct = depth_breakdown.get("strength_pct") if isinstance(depth_breakdown, dict) else amp
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
        "sources": [source_prompt[:80]] if source_prompt else [],
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
            "source_prompt": source_prompt[:80] if source_prompt else "",
            "name": name,
        })
    return name


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
) -> str | None:
    """Generic: add one dynamic entry if key not in registry. Returns name if added.
    When registry_cache is provided, uses cached registry data to avoid repeated disk reads."""
    if registry_cache is not None and aspect in registry_cache:
        data = registry_cache[aspect]
    else:
        data = load_dynamic_registry(aspect, config)
        if registry_cache is not None:
            registry_cache[aspect] = data
    existing = _entries_keys(data)
    if key in existing:
        for e in data.get("entries", []):
            if e.get("key") == key:
                e["count"] = e.get("count", 0) + 1
                if source_prompt:
                    e.setdefault("sources", []).append(source_prompt[:80])
                break
        save_dynamic_registry(aspect, data, config)
        return None
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    name = generate_sensible_name(aspect, key, existing_names=names)
    entry = {"key": key, "name": name, "count": 1, "sources": [source_prompt[:80]] if source_prompt else [], **entry_payload}
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_dynamic_registry(aspect, data, config)
    if out_novel is not None and api_payload is not None:
        out_novel.append({**api_payload, "source_prompt": source_prompt[:80] if source_prompt else ""})
    return name


def ensure_dynamic_motion_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    from .blend_depth import compute_motion_depth
    motion = window.get("motion", {})
    key = _motion_key(motion)
    motion_level = float(motion.get("level", 0))
    motion_trend = str(motion.get("trend", "steady"))
    payload = {
        "motion_level": motion.get("level"),
        "motion_std": motion.get("std"),
        "motion_trend": motion_trend,
        "motion_direction": motion.get("direction", "neutral"),
        "motion_rhythm": motion.get("rhythm", "steady"),
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
    return _ensure_dynamic_in_registry("motion", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_time_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    time_dict = window.get("time", {})
    key = _time_key(time_dict)
    payload = {"duration": time_dict.get("duration"), "fps": time_dict.get("fps"), "rate": time_dict.get("rate", time_dict.get("fps"))}
    api = {"key": key, "duration": payload["duration"], "fps": payload["fps"], "rate": payload.get("rate", payload["fps"])}
    return _ensure_dynamic_in_registry("time", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_lighting_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    from .blend_depth import compute_lighting_depth
    lighting = window.get("lighting", {})
    key = _lighting_key(lighting)
    brightness = float(lighting.get("brightness", 128))
    contrast = float(lighting.get("contrast", 50))
    saturation = float(lighting.get("saturation", 1.0))
    api = {
        "key": key,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "depth_breakdown": compute_lighting_depth(brightness, contrast, saturation),
    }
    return _ensure_dynamic_in_registry("lighting", key, dict(lighting), source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_composition_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    comp = window.get("composition", {})
    key = _composition_key(comp)
    api = {"key": key, "center_x": comp.get("center_x", 0.5), "center_y": comp.get("center_y", 0.5), "luminance_balance": comp.get("luminance_balance", 0.5)}
    return _ensure_dynamic_in_registry("composition", key, dict(comp), source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_graphics_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    graphics = window.get("graphics", {})
    key = _graphics_key(graphics)
    api = {"key": key, "edge_density": graphics.get("edge_density", 0), "spatial_variance": graphics.get("spatial_variance", 0), "busyness": graphics.get("busyness", 0)}
    return _ensure_dynamic_in_registry("graphics", key, dict(graphics), source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_temporal_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    key = _temporal_key(window)
    time_dict = window.get("time", {})
    motion = window.get("motion", {})
    payload = {"duration": time_dict.get("duration"), "motion_trend": motion.get("trend", "steady")}
    api = {"key": key, "duration": payload["duration"], "motion_trend": payload["motion_trend"]}
    return _ensure_dynamic_in_registry("temporal", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


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
) -> str | None:
    time_dict = window.get("time", {})
    f = time_dict.get("fps", fps)
    key = _technical_key(window, width=width, height=height, fps=f)
    payload = {"width": width, "height": height, "fps": f}
    api = {"key": key, "width": width, "height": height, "fps": f}
    return _ensure_dynamic_in_registry("technical", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_gradient_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Add gradient (type + strength) to dynamic registry if novel."""
    grad = window.get("gradient", {})
    if not grad:
        return None
    key = _gradient_key(grad)
    gradient_type = grad.get("gradient_type", "angled")
    payload = {"gradient_type": gradient_type, "strength": grad.get("strength", 0)}
    # depth_breakdown: single primitive = gradient type (REGISTRY_FOUNDATION)
    api = {
        "key": key,
        "gradient_type": payload["gradient_type"],
        "strength": payload["strength"],
        "depth_breakdown": {gradient_type: 1.0},
    }
    return _ensure_dynamic_in_registry("gradient", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_camera_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Add camera motion (type + speed) to dynamic registry if novel."""
    cam = window.get("camera", {})
    if not cam:
        return None
    key = _camera_key(cam)
    motion_type = cam.get("motion_type", "static")
    payload = {"motion_type": motion_type, "speed": cam.get("speed", "medium")}
    # depth_breakdown: single primitive = motion_type (CAMERA_ORIGINS)
    api = {
        "key": key,
        "motion_type": payload["motion_type"],
        "speed": payload["speed"],
        "depth_breakdown": {motion_type: 1.0},
    }
    return _ensure_dynamic_in_registry("camera", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_transition_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Add transition (type, duration) to dynamic registry if novel."""
    trans = window.get("transition", {})
    if not trans or not trans.get("type"):
        return None
    key = _transition_key(trans)
    payload = {"type": trans.get("type", "cut"), "duration_seconds": trans.get("duration_seconds", trans.get("duration", 0))}
    api = {"key": key, "type": payload["type"], "duration_seconds": payload["duration_seconds"]}
    return _ensure_dynamic_in_registry("transition", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_depth_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
) -> str | None:
    """Add depth (parallax, layer_count) to dynamic registry if novel."""
    dep = window.get("depth", {})
    if not dep:
        return None
    key = _depth_key(dep)
    payload = {"parallax_strength": dep.get("parallax_strength", 0), "layer_count": dep.get("layer_count", 1)}
    api = {"key": key, "parallax_strength": payload["parallax_strength"], "layer_count": payload["layer_count"]}
    return _ensure_dynamic_in_registry("depth", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


def ensure_dynamic_audio_semantic_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    registry_cache: dict[str, dict[str, Any]] | None = None,
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
    return _ensure_dynamic_in_registry("audio_semantic", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api, registry_cache=registry_cache)


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
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Unified growth: single video read for both static and dynamic extraction.
    Runs per-frame static growth (color, sound) and per-window dynamic growth
    (motion, lighting, gradient, camera, etc.) in one pass.
    extraction_focus: "all" (default) | "frame" | "window"
      - "frame": only per-frame extraction and static growth (pure/static registry); all new values get authentic names.
      - "window": only per-window extraction and dynamic growth (+ narrative from spec); blends only.
      - "all": both (current behaviour).
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

    out_static_colors = novel_for_sync["static_colors"] if (collect_novel_for_sync and do_frame) else None
    out_sound = novel_for_sync["static_sound"] if (collect_novel_for_sync and do_frame) else None

    if do_frame:
        for frame in _extract_static_from_preloaded(frames, fps, audio_segments):
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
