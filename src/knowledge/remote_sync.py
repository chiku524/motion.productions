"""
Remote sync: POST discoveries to the Cloudflare API (D1/KV).
When api_base is set, growth persists to D1 instead of local JSON.
"""
from typing import Any


def post_discoveries(
    api_base: str,
    discoveries: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """
    POST discoveries to /api/knowledge/discoveries.
    Returns API response. Uses retry on 5xx/connection errors.
    Supports static_colors, static_sound (per-frame) and colors, motion, lighting, etc. (dynamic).
    """
    from ..api_client import api_request_with_retry
    resp = api_request_with_retry(api_base, "POST", "/api/knowledge/discoveries", data=discoveries, timeout=30)
    return resp


def post_static_discoveries(
    api_base: str,
    static_colors: list[dict[str, Any]],
    static_sound: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    POST per-frame static discoveries to /api/knowledge/discoveries.
    Writes to D1 static_colors and static_sound tables. Uses sensible names from Python when provided.
    """
    discoveries: dict[str, list[dict[str, Any]]] = {
        "static_colors": static_colors,
        "static_sound": static_sound or [],
    }
    return post_discoveries(api_base, discoveries)


def post_narrative_discoveries(
    api_base: str,
    novel_for_sync: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """
    POST narrative discoveries (themes, plots, settings, genre, mood, scene_type) to /api/knowledge/discoveries.
    Writes to D1 narrative_entries table. Uses sensible names from Python when provided.
    """
    discoveries: dict[str, Any] = {"narrative": novel_for_sync}
    return post_discoveries(api_base, discoveries)


def post_dynamic_discoveries(
    api_base: str,
    novel_for_sync: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """
    POST per-window dynamic discoveries (motion, lighting, composition, graphics, temporal, technical)
    to /api/knowledge/discoveries. Only sends keys that have at least one entry.
    """
    dynamic_keys = ("motion", "time", "lighting", "composition", "graphics", "temporal", "technical", "audio_semantic")
    discoveries: dict[str, list[dict[str, Any]]] = {
        k: novel_for_sync.get(k, []) for k in dynamic_keys if novel_for_sync.get(k)
    }
    if not discoveries:
        return {}
    return post_discoveries(api_base, discoveries)


def grow_and_sync_to_api(
    analysis: dict[str, Any],
    *,
    prompt: str = "",
    api_base: str = "",
    spec: Any = None,
) -> dict[str, Any]:
    """
    Extract discoveries from analysis and POST them to the API.
    Uses D1/KV for persistence. When spec is provided, adds camera, transitions,
    audio, and narrative (spec-intended values) to growth — all domains covered.
    """
    from .domain_extraction import analysis_dict_to_domains
    from .blend_depth import (
        compute_color_depth,
        compute_motion_depth,
        compute_lighting_depth,
        compute_composition_depth,
        compute_graphics_depth,
        compute_temporal_depth,
        compute_technical_depth,
        compute_full_blend_depths,
    )
    from .registry import _color_key

    if not api_base:
        return {"error": "api_base required"}

    discoveries: dict[str, list[dict[str, Any]]] = {
        "colors": [],
        "blends": [],
        "motion": [],
        "lighting": [],
        "composition": [],
        "graphics": [],
        "temporal": [],
        "technical": [],
    }

    # Color
    dom = analysis.get("dominant_color_rgb")
    if dom and len(dom) >= 3:
        r, g, b = float(dom[0]), float(dom[1]), float(dom[2])
        key = _color_key(r, g, b, tolerance=25)
        discoveries["colors"].append({
            "key": key,
            "r": r,
            "g": g,
            "b": b,
            "source_prompt": prompt[:80] if prompt else "",
        })
        discoveries["blends"].append({
            "name": "",  # API will generate
            "domain": "color",
            "inputs": {"key": key},
            "output": {"r": r, "g": g, "b": b},
            "primitive_depths": compute_color_depth(r, g, b),
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Motion
    motion_level = float(analysis.get("motion_level", 0))
    motion_std = float(analysis.get("motion_std", 0))
    motion_trend = str(analysis.get("motion_trend", "steady"))
    level_bucket = round(motion_level, 1)
    mkey = f"{level_bucket}_{motion_trend}"
    discoveries["motion"].append({
        "key": mkey,
        "motion_level": motion_level,
        "motion_std": motion_std,
        "motion_trend": motion_trend,
        "source_prompt": prompt[:80] if prompt else "",
    })
    discoveries["blends"].append({
        "name": "",
        "domain": "motion",
        "inputs": {"motion_level": motion_level, "motion_std": motion_std, "motion_trend": motion_trend},
        "output": {"key": mkey},
        "primitive_depths": compute_motion_depth(motion_level, motion_trend),
        "source_prompt": prompt[:120] if prompt else "",
    })

    # Lighting
    brightness = float(analysis.get("mean_brightness", 128))
    contrast = float(analysis.get("mean_contrast", 50))
    saturation = float(analysis.get("mean_saturation", 1.0))
    lkey = f"{round(brightness/25)*25}_{round(contrast,1)}_{round(saturation,1)}"
    discoveries["lighting"].append({
        "key": lkey,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "source_prompt": prompt[:80] if prompt else "",
    })
    discoveries["blends"].append({
        "name": "",
        "domain": "lighting",
        "inputs": {"key": lkey},
        "output": {"brightness": brightness, "contrast": contrast, "saturation": saturation},
        "primitive_depths": compute_lighting_depth(brightness, contrast, saturation),
        "source_prompt": prompt[:120] if prompt else "",
    })

    # Full blend from domains
    domains = analysis_dict_to_domains(analysis)
    primitive_depths = compute_full_blend_depths(domains)
    discoveries["blends"].append({
        "name": "",
        "domain": "full_blend",
        "inputs": {"domains": list(domains.keys())},
        "output": domains,
        "primitive_depths": primitive_depths,
        "source_prompt": prompt[:120] if prompt else "",
    })

    # Composition (if available)
    if "center_of_mass_x" in analysis or "luminance_balance" in analysis:
        cx = float(analysis.get("center_of_mass_x", 0.5))
        cy = float(analysis.get("center_of_mass_y", 0.5))
        lb = float(analysis.get("luminance_balance", 0.5))
        ckey = f"{round(cx,2)}_{round(cy,2)}_{round(lb,2)}"
        discoveries["composition"].append({
            "key": ckey,
            "center_x": cx,
            "center_y": cy,
            "luminance_balance": lb,
            "source_prompt": prompt[:80] if prompt else "",
        })
        discoveries["blends"].append({
            "name": "",
            "domain": "composition",
            "inputs": {"key": ckey},
            "output": {"center_x": cx, "center_y": cy, "luminance_balance": lb},
            "primitive_depths": compute_composition_depth(cx, cy, lb),
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Graphics (if available)
    if "edge_density" in analysis or "busyness" in analysis:
        ed = float(analysis.get("edge_density", 0))
        sv = float(analysis.get("spatial_variance", 0))
        busy = float(analysis.get("busyness", 0))
        gkey = f"{round(ed,2)}_{round(sv,2)}_{round(busy,2)}"
        discoveries["graphics"].append({
            "key": gkey,
            "edge_density": ed,
            "spatial_variance": sv,
            "busyness": busy,
            "source_prompt": prompt[:80] if prompt else "",
        })
        discoveries["blends"].append({
            "name": "",
            "domain": "graphics",
            "inputs": {"key": gkey},
            "output": {"edge_density": ed, "spatial_variance": sv, "busyness": busy},
            "primitive_depths": compute_graphics_depth(ed, sv, busy),
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Temporal
    duration = float(analysis.get("duration_seconds", 5))
    tkey = f"{round(duration,1)}_{motion_trend}"
    discoveries["temporal"].append({
        "key": tkey,
        "duration": duration,
        "motion_trend": motion_trend,
        "source_prompt": prompt[:80] if prompt else "",
    })
    discoveries["blends"].append({
        "name": "",
        "domain": "temporal",
        "inputs": {"key": tkey},
        "output": {"duration": duration, "motion_trend": motion_trend},
        "primitive_depths": compute_temporal_depth(duration, motion_trend),
        "source_prompt": prompt[:120] if prompt else "",
    })

    # Technical (if available)
    if "width" in analysis or "height" in analysis:
        w = int(analysis.get("width", 512))
        h = int(analysis.get("height", 512))
        fps = float(analysis.get("fps", 24))
        tekkey = f"{w}x{h}_{fps}"
        discoveries["technical"].append({
            "key": tekkey,
            "width": w,
            "height": h,
            "fps": fps,
            "source_prompt": prompt[:80] if prompt else "",
        })
        discoveries["blends"].append({
            "name": "",
            "domain": "technical",
            "inputs": {"key": tekkey},
            "output": {"width": w, "height": h, "fps": fps},
            "primitive_depths": compute_technical_depth(w, h, fps),
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Camera, Transitions, Audio, Narrative — from spec (intended values)
    if spec is not None:
        camera = getattr(spec, "camera_motion", "static") or "static"
        transitions = f"{getattr(spec, 'transition_in', 'cut') or 'cut'}_{getattr(spec, 'transition_out', 'cut') or 'cut'}"
        discoveries["blends"].append({
            "name": "",
            "domain": "camera",
            "inputs": {"camera_motion": camera},
            "output": {"camera_motion": camera},
            "primitive_depths": {camera: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        discoveries["blends"].append({
            "name": "",
            "domain": "transitions",
            "inputs": {"transition_in": getattr(spec, "transition_in", "cut"), "transition_out": getattr(spec, "transition_out", "cut")},
            "output": {"key": transitions},
            "primitive_depths": {transitions: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        audio_tempo = getattr(spec, "audio_tempo", "medium") or "medium"
        audio_mood = getattr(spec, "audio_mood", "neutral") or "neutral"
        audio_presence = getattr(spec, "audio_presence", "ambient") or "ambient"
        discoveries["blends"].append({
            "name": "",
            "domain": "audio",
            "inputs": {"tempo": audio_tempo, "mood": audio_mood, "presence": audio_presence},
            "output": {"tempo": audio_tempo, "mood": audio_mood, "presence": audio_presence},
            "primitive_depths": {audio_tempo: 1.0, audio_mood: 1.0, audio_presence: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        genre_val = getattr(spec, "genre", "general") or "general"
        tension = getattr(spec, "tension_curve", "standard") or "standard"
        discoveries["blends"].append({
            "name": "",
            "domain": "narrative",
            "inputs": {"genre": genre_val, "tension_curve": tension},
            "output": {"genre": genre_val, "tension_curve": tension},
            "primitive_depths": {genre_val: 1.0, tension: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })

    return post_discoveries(api_base, discoveries)
