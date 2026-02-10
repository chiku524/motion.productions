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

from .extractor_per_instance import extract_static_per_frame, extract_dynamic_per_window
from .static_registry import load_static_registry, save_static_registry
from .dynamic_registry import load_dynamic_registry, save_dynamic_registry
from .registry import _color_key
from .blend_names import generate_sensible_name


def _static_color_key(color: dict[str, Any], tolerance: int = 25) -> str:
    r = color.get("r", 0)
    g = color.get("g", 0)
    b = color.get("b", 0)
    return _color_key(float(r), float(g), float(b), tolerance=tolerance)


def _static_sound_key(sound: dict[str, Any]) -> str:
    if not sound:
        return ""
    amp = sound.get("amplitude") or sound.get("weight") or 0
    tone = sound.get("tone") or "unknown"
    return f"{round(float(amp), 2)}_{tone}"


def derive_audio_semantic_from_spec(spec: Any) -> dict[str, Any]:
    """
    Build one audio_semantic dict from spec (audio_presence -> role: ambient|music|sfx).
    Use until semantic audio classification from decoded audio is implemented.
    """
    presence = getattr(spec, "audio_presence", None) or "ambient"
    role = "music" if presence == "full" else ("sfx" if presence == "sfx" else "ambient")
    return {"role": role, "type": role}


def derive_static_sound_from_spec(spec: Any) -> dict[str, Any]:
    """
    Build one static sound dict from creation spec (audio_mood, audio_tempo, audio_presence).
    Use when per-frame audio extraction is not yet implemented, so we still record intended sound.
    """
    mood = getattr(spec, "audio_mood", None) or "neutral"
    tempo = getattr(spec, "audio_tempo", None) or "medium"
    presence = getattr(spec, "audio_presence", None) or "ambient"
    # Map presence to a simple amplitude hint; tone from mood
    weight = 0.3 if presence == "silence" else (0.7 if presence == "full" else 0.5)
    return {"amplitude": weight, "weight": weight, "tone": str(mood), "timbre": str(presence)}


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


def _audio_semantic_key(audio: dict[str, Any]) -> str:
    role = (audio.get("role") or audio.get("type") or "ambient").strip().lower()
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
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    name = generate_sensible_name("color", key, existing_names=names)
    entry: dict[str, Any] = {
        "key": key,
        "r": round(float(color.get("r", 0)), 1),
        "g": round(float(color.get("g", 0)), 1),
        "b": round(float(color.get("b", 0)), 1),
        "brightness": color.get("brightness"),
        "luminance": color.get("luminance", color.get("brightness")),
        "contrast": color.get("contrast"),
        "saturation": color.get("saturation"),
        "chroma": color.get("chroma", color.get("saturation")),
        "hue": color.get("hue"),
        "color_variance": color.get("color_variance"),
        "opacity": color.get("opacity", 1.0),
        "name": name,
        "count": 1,
        "sources": [source_prompt[:80]] if source_prompt else [],
    }
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_static_registry("color", data, config)
    if out_novel is not None:
        out_novel.append({
            "key": key,
            "r": entry["r"], "g": entry["g"], "b": entry["b"],
            "brightness": entry.get("brightness"), "luminance": entry.get("luminance"),
            "contrast": entry.get("contrast"), "saturation": entry.get("saturation"),
            "chroma": entry.get("chroma"), "hue": entry.get("hue"),
            "color_variance": entry.get("color_variance"), "opacity": entry.get("opacity"),
            "source_prompt": source_prompt[:80] if source_prompt else "",
            "name": name,
        })
    return name


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
    entry = {
        "key": key,
        "amplitude": sound.get("amplitude"),
        "weight": sound.get("weight"),
        "tone": sound.get("tone"),
        "timbre": sound.get("timbre"),
        "name": name,
        "count": 1,
        "sources": [source_prompt[:80]] if source_prompt else [],
    }
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_static_registry("sound", data, config)
    if out_novel is not None:
        out_novel.append({
            "key": key,
            "amplitude": entry.get("amplitude"),
            "weight": entry.get("weight"),
            "tone": entry.get("tone"),
            "timbre": entry.get("timbre"),
            "source_prompt": source_prompt[:80] if source_prompt else "",
            "name": name,
        })
    return name


def _ensure_dynamic_in_registry(
    aspect: str,
    key: str,
    entry_payload: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
    api_payload: dict[str, Any] | None = None,
) -> str | None:
    """Generic: add one dynamic entry if key not in registry. Returns name if added. If out_novel and api_payload given, appends API payload when added."""
    data = load_dynamic_registry(aspect, config)
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
) -> str | None:
    motion = window.get("motion", {})
    key = _motion_key(motion)
    payload = {
        "motion_level": motion.get("level"),
        "motion_std": motion.get("std"),
        "motion_trend": motion.get("trend", "steady"),
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
    }
    return _ensure_dynamic_in_registry("motion", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_time_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    time_dict = window.get("time", {})
    key = _time_key(time_dict)
    payload = {"duration": time_dict.get("duration"), "fps": time_dict.get("fps"), "rate": time_dict.get("rate", time_dict.get("fps"))}
    api = {"key": key, "duration": payload["duration"], "fps": payload["fps"], "rate": payload.get("rate", payload["fps"])}
    return _ensure_dynamic_in_registry("time", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_lighting_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    lighting = window.get("lighting", {})
    key = _lighting_key(lighting)
    api = {"key": key, "brightness": lighting.get("brightness", 128), "contrast": lighting.get("contrast", 50), "saturation": lighting.get("saturation", 1.0)}
    return _ensure_dynamic_in_registry("lighting", key, dict(lighting), source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_composition_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    comp = window.get("composition", {})
    key = _composition_key(comp)
    api = {"key": key, "center_x": comp.get("center_x", 0.5), "center_y": comp.get("center_y", 0.5), "luminance_balance": comp.get("luminance_balance", 0.5)}
    return _ensure_dynamic_in_registry("composition", key, dict(comp), source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_graphics_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    graphics = window.get("graphics", {})
    key = _graphics_key(graphics)
    api = {"key": key, "edge_density": graphics.get("edge_density", 0), "spatial_variance": graphics.get("spatial_variance", 0), "busyness": graphics.get("busyness", 0)}
    return _ensure_dynamic_in_registry("graphics", key, dict(graphics), source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_temporal_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    key = _temporal_key(window)
    time_dict = window.get("time", {})
    motion = window.get("motion", {})
    payload = {"duration": time_dict.get("duration"), "motion_trend": motion.get("trend", "steady")}
    api = {"key": key, "duration": payload["duration"], "motion_trend": payload["motion_trend"]}
    return _ensure_dynamic_in_registry("temporal", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_technical_in_registry(
    window: dict[str, Any],
    *,
    width: int = 0,
    height: int = 0,
    fps: float = 24,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    time_dict = window.get("time", {})
    f = time_dict.get("fps", fps)
    key = _technical_key(window, width=width, height=height, fps=f)
    payload = {"width": width, "height": height, "fps": f}
    api = {"key": key, "width": width, "height": height, "fps": f}
    return _ensure_dynamic_in_registry("technical", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


def ensure_dynamic_audio_semantic_in_registry(
    window: dict[str, Any],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: list[dict[str, Any]] | None = None,
) -> str | None:
    """Add audio_semantic (role/type) to dynamic registry if novel; when out_novel given, append API payload when added."""
    audio = window.get("audio_semantic", {})
    if not audio:
        return None
    key = _audio_semantic_key(audio)
    if not key:
        return None
    role = audio.get("role", "ambient")
    payload = {"role": role, "type": audio.get("type", role)}
    api = {"key": key, "role": role}
    return _ensure_dynamic_in_registry("audio_semantic", key, payload, source_prompt=source_prompt, config=config, out_novel=out_novel, api_payload=api)


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

    out_static_colors = novel_for_sync["static_colors"] if collect_novel_for_sync else None
    out_sound = novel_for_sync["static_sound"] if collect_novel_for_sync else None

    # Static only: every frame (color + sound)
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

    # Spec-derived static sound (when audio extraction not yet implemented)
    if spec is not None:
        sound_from_spec = derive_static_sound_from_spec(spec)
        if ensure_static_sound_in_registry(
            sound_from_spec, source_prompt=prompt, config=config, out_novel=out_sound
        ):
            added["static_sound"] += 1

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
        "dynamic_lighting": 0,
        "dynamic_composition": 0,
        "dynamic_graphics": 0,
        "dynamic_temporal": 0,
        "dynamic_technical": 0,
        "dynamic_audio_semantic": 0,
    }
    novel_for_sync: dict[str, list[dict[str, Any]]] = {
        "motion": [],
        "time": [],
        "lighting": [],
        "composition": [],
        "graphics": [],
        "temporal": [],
        "technical": [],
        "audio_semantic": [],
    }
    path = Path(video_path)
    if not path.exists():
        return added, novel_for_sync

    _, fps, width, height = _read_frames(path, max_frames=max_frames, sample_every=sample_every)
    out_motion = novel_for_sync["motion"] if collect_novel_for_sync else None
    out_time = novel_for_sync["time"] if collect_novel_for_sync else None
    out_lighting = novel_for_sync["lighting"] if collect_novel_for_sync else None
    out_composition = novel_for_sync["composition"] if collect_novel_for_sync else None
    out_graphics = novel_for_sync["graphics"] if collect_novel_for_sync else None
    out_temporal = novel_for_sync["temporal"] if collect_novel_for_sync else None
    out_technical = novel_for_sync["technical"] if collect_novel_for_sync else None
    out_audio_semantic = novel_for_sync["audio_semantic"] if collect_novel_for_sync else None

    for window in extract_dynamic_per_window(
        path, window_seconds=window_seconds, max_frames=max_frames, sample_every=sample_every
    ):
        if ensure_dynamic_motion_in_registry(window, source_prompt=prompt, config=config, out_novel=out_motion):
            added["dynamic_motion"] += 1
        if ensure_dynamic_time_in_registry(window, source_prompt=prompt, config=config, out_novel=out_time):
            added["dynamic_time"] += 1
        if ensure_dynamic_lighting_in_registry(window, source_prompt=prompt, config=config, out_novel=out_lighting):
            added["dynamic_lighting"] += 1
        if ensure_dynamic_composition_in_registry(window, source_prompt=prompt, config=config, out_novel=out_composition):
            added["dynamic_composition"] += 1
        if ensure_dynamic_graphics_in_registry(window, source_prompt=prompt, config=config, out_novel=out_graphics):
            added["dynamic_graphics"] += 1
        if ensure_dynamic_temporal_in_registry(window, source_prompt=prompt, config=config, out_novel=out_temporal):
            added["dynamic_temporal"] += 1
        if ensure_dynamic_technical_in_registry(
            window, width=width, height=height, fps=fps, source_prompt=prompt, config=config, out_novel=out_technical
        ):
            added["dynamic_technical"] += 1
        if ensure_dynamic_audio_semantic_in_registry(window, source_prompt=prompt, config=config, out_novel=out_audio_semantic):
            added["dynamic_audio_semantic"] += 1

    if spec is not None:
        audio_semantic = derive_audio_semantic_from_spec(spec)
        fake_window = {"audio_semantic": audio_semantic}
        if ensure_dynamic_audio_semantic_in_registry(fake_window, source_prompt=prompt, config=config, out_novel=out_audio_semantic):
            added["dynamic_audio_semantic"] += 1

    return added, novel_for_sync
