"""
Remote sync: POST discoveries to the Cloudflare API (D1/KV).
When api_base is set, growth persists to D1 instead of local JSON.

Batching: Workers Paid allows 1000 queries/request; ~3 per item.
We send max 200 items per request for efficiency (fewer round-trips).
"""
from typing import Any

# Match API DISCOVERIES_MAX_ITEMS (reduced for D1 CPU stability under 6-worker concurrency)
DISCOVERIES_MAX_ITEMS = 50


def _chunk_discoveries(discoveries: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Split discoveries into chunks of at most DISCOVERIES_MAX_ITEMS items each.
    Order matches API processing: static_colors, static_sound, narrative, colors,
    blends, motion, lighting, composition, graphics, temporal, technical,
    audio_semantic, time, gradient, camera, transition, depth.
    """
    job_id = discoveries.pop("job_id", None)
    chunks: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    count = 0
    narrative_aspects = ("genre", "mood", "plots", "settings", "themes", "style", "scene_type")
    list_keys = (
        "static_colors", "static_sound", "colors", "blends", "motion", "lighting",
        "composition", "graphics", "temporal", "technical", "audio_semantic",
        "time", "gradient", "camera", "transition", "depth",
    )

    def flush() -> None:
        nonlocal current, count
        if current:
            chunks.append(current)
        current = {}
        count = 0

    # Narrative: dict of aspect -> list
    narr = discoveries.get("narrative") or {}
    for aspect in narrative_aspects:
        items = narr.get(aspect) or []
        for item in items:
            if count >= DISCOVERIES_MAX_ITEMS:
                flush()
            if "narrative" not in current:
                current["narrative"] = {}
            if aspect not in current["narrative"]:
                current["narrative"][aspect] = []
            current["narrative"][aspect].append(item)
            count += 1

    # List categories
    for key in list_keys:
        items = discoveries.get(key) or []
        for item in items:
            if count >= DISCOVERIES_MAX_ITEMS:
                flush()
            if key not in current:
                current[key] = []
            current[key].append(item)
            count += 1

    if current:
        chunks.append(current)

    # Attach job_id only to last chunk (single discovery_runs row per logical batch)
    # If no items but job_id present, send one empty chunk to record discovery_runs
    if job_id:
        if chunks:
            chunks[-1]["job_id"] = job_id
        else:
            chunks.append({"job_id": job_id})

    return chunks


def growth_metrics(added: dict[str, Any]) -> dict[str, Any]:
    """
    Summary metrics from a growth run. Use for logging/diagnostics.
    Returns: total_added, static_added, dynamic_added, by_aspect.
    """
    static_keys = ("static_colors", "static_sound")
    dynamic_prefix = "dynamic_"
    static_total = sum(added.get(k, 0) for k in static_keys)
    dynamic_total = sum(
        v for k, v in added.items()
        if k.startswith(dynamic_prefix) and isinstance(v, (int, float))
    )
    return {
        "total_added": static_total + dynamic_total,
        "static_added": static_total,
        "dynamic_added": dynamic_total,
        "by_aspect": {k: v for k, v in added.items() if v},
    }


def post_discoveries(
    api_base: str,
    discoveries: dict[str, Any],
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    POST discoveries to /api/knowledge/discoveries.
    Batches into chunks of max 14 items to stay under D1 query limit (50/request).
    Returns merged API response. Uses retry on 5xx/connection errors.
    When job_id is provided, records for discovery rate metric (on last chunk).
    """
    from ..api_client import api_request_with_retry
    payload = dict(discoveries)
    if job_id:
        payload["job_id"] = job_id
    chunks = _chunk_discoveries(payload)
    if not chunks:
        return {}
    merged: dict[str, Any] = {"status": "recorded", "results": {}}
    for chunk in chunks:
        # Worker may take a while under load; use 90s to reduce read timeouts.
        # D1-heavy: extra retries with longer backoff on D1_ERROR (api_client handles that)
        resp = api_request_with_retry(
            api_base, "POST", "/api/knowledge/discoveries", data=chunk, timeout=90, max_retries=5
        )
        merged["truncated"] = merged.get("truncated", False) or resp.get("truncated", False)
        res = resp.get("results", {})
        for k, v in res.items():
            merged["results"][k] = merged["results"].get(k, 0) + v
    return merged


def post_static_discoveries(
    api_base: str,
    static_colors: list[dict[str, Any]],
    static_sound: list[dict[str, Any]] | None = None,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    POST per-frame static discoveries to /api/knowledge/discoveries.
    Writes to D1 static_colors and static_sound tables. Uses sensible names from Python when provided.
    """
    discoveries: dict[str, Any] = {
        "static_colors": static_colors,
        "static_sound": static_sound or [],
    }
    return post_discoveries(api_base, discoveries, job_id=job_id)


def post_narrative_discoveries(
    api_base: str,
    novel_for_sync: dict[str, list[dict[str, Any]]],
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    POST narrative discoveries (themes, plots, settings, genre, mood, scene_type) to /api/knowledge/discoveries.
    Writes to D1 narrative_entries table. Uses sensible names from Python when provided.
    """
    discoveries: dict[str, Any] = {"narrative": novel_for_sync}
    return post_discoveries(api_base, discoveries, job_id=job_id)


def post_dynamic_discoveries(
    api_base: str,
    novel_for_sync: dict[str, list[dict[str, Any]]],
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    POST per-window dynamic discoveries (motion, lighting, composition, graphics, temporal, technical)
    to /api/knowledge/discoveries. Only sends keys that have at least one entry.
    """
    dynamic_keys = ("motion", "time", "gradient", "camera", "lighting", "composition", "graphics", "temporal", "technical", "audio_semantic", "transition", "depth")
    discoveries: dict[str, Any] = {
        k: novel_for_sync.get(k, []) for k in dynamic_keys if novel_for_sync.get(k)
    }
    if not discoveries:
        return {}
    return post_discoveries(api_base, discoveries, job_id=job_id)


def post_all_discoveries(
    api_base: str,
    static_colors: list[dict[str, Any]],
    static_sound: list[dict[str, Any]],
    dynamic_novel: dict[str, list[dict[str, Any]]],
    narrative_novel: dict[str, list[dict[str, Any]]] | None = None,
    *,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Batch POST static + dynamic + narrative discoveries in a single API call.
    Reduces round-trips when all three registries have new entries.
    """
    discoveries: dict[str, Any] = {
        "static_colors": static_colors or [],
        "static_sound": static_sound or [],
    }
    dynamic_keys = ("motion", "time", "gradient", "camera", "lighting", "composition", "graphics", "temporal", "technical", "audio_semantic", "transition", "depth")
    for k in dynamic_keys:
        if dynamic_novel.get(k):
            discoveries[k] = dynamic_novel[k]
    if narrative_novel:
        discoveries["narrative"] = narrative_novel
    if job_id:
        discoveries["job_id"] = job_id

    has_any = bool(static_colors or static_sound)
    has_any = has_any or any(dynamic_novel.get(k) for k in dynamic_keys)
    has_any = has_any or bool(narrative_novel and any(narrative_novel.values()))
    if not has_any:
        # Still POST with job_id to record discovery run for diagnostics (API inserts discovery_runs row)
        if job_id:
            return post_discoveries(api_base, {"job_id": job_id})
        return {}
    return post_discoveries(api_base, discoveries, job_id=job_id)


def grow_and_sync_to_api(
    analysis: dict[str, Any],
    *,
    prompt: str = "",
    api_base: str = "",
    spec: Any = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    """
    Whole-video composite growth: extract discoveries from analysis and POST to API.
    Produces learned_colors, learned_motion, learned_blends (whole-video aggregates).

    Distinct from per-instance growth (grow_all_from_video / post_all_discoveries):
    - Per-instance: per-frame static (static_colors, static_sound) + per-window dynamic
      (motion, lighting, gradient, etc.) + narrative. Single video read; batch POST.
    - grow_and_sync_to_api: whole-video summary (dominant color, motion profile, blends).
      Complements per-instance; both run in the loop. No overlap in static_colors/static_sound.
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
    from .blend_names import generate_sensible_name, generate_blend_name

    if not api_base:
        return {"error": "api_base required"}

    used_names: set[str] = set()
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

    # Color (with depth_breakdown vs 16 primitives for learned_colors — living plan Priority 1)
    dom = analysis.get("dominant_color_rgb")
    if dom and len(dom) >= 3:
        r = max(0, min(255, float(dom[0])))
        g = max(0, min(255, float(dom[1])))
        b = max(0, min(255, float(dom[2])))
        key = _color_key(r, g, b, tolerance=25)
        color_name = generate_sensible_name("color", key, existing_names=used_names, rgb_hint=(r, g, b))
        used_names.add(color_name)
        depth_breakdown = compute_color_depth(r, g, b)  # 16 primitives; Worker stores in learned_colors
        discoveries["colors"].append({
            "key": key,
            "r": r,
            "g": g,
            "b": b,
            "name": color_name,
            "source_prompt": prompt[:80] if prompt else "",
            "depth_breakdown": depth_breakdown,
        })
        discoveries["blends"].append({
            "name": color_name,
            "domain": "color",
            "inputs": {"key": key},
            "output": {"r": r, "g": g, "b": b},
            "primitive_depths": depth_breakdown,
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Motion
    motion_level = float(analysis.get("motion_level", 0))
    motion_std = float(analysis.get("motion_std", 0))
    motion_trend = str(analysis.get("motion_trend", "steady"))
    level_bucket = round(motion_level, 1)
    mkey = f"{level_bucket}_{motion_trend}"
    motion_name = generate_sensible_name("motion", mkey, existing_names=used_names)
    used_names.add(motion_name)
    motion_depth = compute_motion_depth(motion_level, motion_trend)
    discoveries["motion"].append({
        "key": mkey,
        "motion_level": motion_level,
        "motion_std": motion_std,
        "motion_trend": motion_trend,
        "name": motion_name,
        "source_prompt": prompt[:80] if prompt else "",
        "depth_breakdown": motion_depth,
    })
    discoveries["blends"].append({
        "name": motion_name,
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
    light_name = generate_sensible_name("lighting", lkey, existing_names=used_names)
    used_names.add(light_name)
    lighting_depth = compute_lighting_depth(brightness, contrast, saturation)
    discoveries["lighting"].append({
        "key": lkey,
        "brightness": brightness,
        "contrast": contrast,
        "saturation": saturation,
        "name": light_name,
        "source_prompt": prompt[:80] if prompt else "",
        "depth_breakdown": lighting_depth,
    })
    discoveries["blends"].append({
        "name": light_name,
        "domain": "lighting",
        "inputs": {"key": lkey},
        "output": {"brightness": brightness, "contrast": contrast, "saturation": saturation},
        "primitive_depths": compute_lighting_depth(brightness, contrast, saturation),
        "source_prompt": prompt[:120] if prompt else "",
    })

    # Full blend from domains
    domains = analysis_dict_to_domains(analysis)
    primitive_depths = compute_full_blend_depths(domains)
    blend_hint = ",".join(domains.keys())[:60] if domains else ""
    full_name = generate_blend_name("full_blend", blend_hint, existing_names=used_names)
    used_names.add(full_name)
    discoveries["blends"].append({
        "name": full_name,
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
        comp_name = generate_sensible_name("composition", ckey, existing_names=used_names)
        used_names.add(comp_name)
        comp_depth = compute_composition_depth(cx, cy, lb)
        discoveries["composition"].append({
            "key": ckey,
            "center_x": cx,
            "center_y": cy,
            "luminance_balance": lb,
            "name": comp_name,
            "source_prompt": prompt[:80] if prompt else "",
            "depth_breakdown": comp_depth,
        })
        discoveries["blends"].append({
            "name": comp_name,
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
        graph_name = generate_sensible_name("graphics", gkey, existing_names=used_names)
        used_names.add(graph_name)
        graph_depth = compute_graphics_depth(ed, sv, busy)
        discoveries["graphics"].append({
            "key": gkey,
            "edge_density": ed,
            "spatial_variance": sv,
            "busyness": busy,
            "name": graph_name,
            "source_prompt": prompt[:80] if prompt else "",
            "depth_breakdown": graph_depth,
        })
        discoveries["blends"].append({
            "name": graph_name,
            "domain": "graphics",
            "inputs": {"key": gkey},
            "output": {"edge_density": ed, "spatial_variance": sv, "busyness": busy},
            "primitive_depths": compute_graphics_depth(ed, sv, busy),
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Temporal
    duration = float(analysis.get("duration_seconds", 5))
    tkey = f"{round(duration,1)}_{motion_trend}"
    temp_name = generate_sensible_name("temporal", tkey, existing_names=used_names)
    used_names.add(temp_name)
    temporal_depth = compute_temporal_depth(duration, motion_trend)
    discoveries["temporal"].append({
        "key": tkey,
        "duration": duration,
        "motion_trend": motion_trend,
        "name": temp_name,
        "source_prompt": prompt[:80] if prompt else "",
        "depth_breakdown": temporal_depth,
    })
    discoveries["blends"].append({
        "name": temp_name,
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
        tech_name = generate_sensible_name("technical", tekkey, existing_names=used_names)
        used_names.add(tech_name)
        tech_depth = compute_technical_depth(w, h, fps)
        discoveries["technical"].append({
            "key": tekkey,
            "width": w,
            "height": h,
            "fps": fps,
            "name": tech_name,
            "source_prompt": prompt[:80] if prompt else "",
            "depth_breakdown": tech_depth,
        })
        discoveries["blends"].append({
            "name": tech_name,
            "domain": "technical",
            "inputs": {"key": tekkey},
            "output": {"width": w, "height": h, "fps": fps},
            "primitive_depths": compute_technical_depth(w, h, fps),
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Gradient, Camera, Transitions, Audio, Narrative — from spec (intended values; growth prioritised)
    if spec is not None:
        gradient_type = getattr(spec, "gradient_type", "vertical") or "vertical"
        grad_name = generate_blend_name("gradient", gradient_type, existing_names=used_names)
        used_names.add(grad_name)
        discoveries["blends"].append({
            "name": grad_name,
            "domain": "gradient",
            "inputs": {"gradient_type": gradient_type},
            "output": {"gradient_type": gradient_type},
            "primitive_depths": {gradient_type: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        camera = getattr(spec, "camera_motion", "static") or "static"
        cam_name = generate_blend_name("camera", camera, existing_names=used_names)
        used_names.add(cam_name)
        discoveries["blends"].append({
            "name": cam_name,
            "domain": "camera",
            "inputs": {"camera_motion": camera},
            "output": {"camera_motion": camera},
            "primitive_depths": {camera: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        transition_in = getattr(spec, "transition_in", "cut") or "cut"
        transition_out = getattr(spec, "transition_out", "cut") or "cut"
        transition_key = f"{transition_in}_{transition_out}"
        trans_name = generate_blend_name("transitions", transition_key, existing_names=used_names)
        used_names.add(trans_name)
        discoveries["blends"].append({
            "name": trans_name,
            "domain": "transitions",
            "inputs": {"transition_in": transition_in, "transition_out": transition_out},
            "output": {"key": transition_key},
            "primitive_depths": {transition_key: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        audio_tempo = getattr(spec, "audio_tempo", "medium") or "medium"
        audio_mood = getattr(spec, "audio_mood", "neutral") or "neutral"
        audio_presence = getattr(spec, "audio_presence", "ambient") or "ambient"
        audio_name = generate_blend_name("audio", f"{audio_tempo}_{audio_mood}", existing_names=used_names)
        used_names.add(audio_name)
        discoveries["blends"].append({
            "name": audio_name,
            "domain": "audio",
            "inputs": {"tempo": audio_tempo, "mood": audio_mood, "presence": audio_presence},
            "output": {"tempo": audio_tempo, "mood": audio_mood, "presence": audio_presence},
            "primitive_depths": {audio_tempo: 1.0, audio_mood: 1.0, audio_presence: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })
        genre_val = getattr(spec, "genre", "general") or "general"
        tension = getattr(spec, "tension_curve", "standard") or "standard"
        narr_name = generate_blend_name("narrative", f"{genre_val}_{tension}", existing_names=used_names)
        used_names.add(narr_name)
        discoveries["blends"].append({
            "name": narr_name,
            "domain": "narrative",
            "inputs": {"genre": genre_val, "tension_curve": tension},
            "output": {"genre": genre_val, "tension_curve": tension},
            "primitive_depths": {genre_val: 1.0, tension: 1.0},
            "source_prompt": prompt[:120] if prompt else "",
        })

    # Ensure any remaining blends without names get semantic names
    for b in discoveries.get("blends", []):
        if not (b.get("name") or str(b.get("name", "")).strip()):
            hint = prompt[:60] if prompt else str(b.get("output", ""))[:40]
            b["name"] = generate_blend_name(b.get("domain", "blend"), hint, existing_names=used_names)
            used_names.add(b["name"])

    return post_discoveries(api_base, discoveries, job_id=job_id)
