"""
Registry: persisted learned knowledge. Grows from extraction.
Stores novel colors, motion profiles, and documented blends with unique names.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def get_registry_dir(config: dict[str, Any] | None = None) -> Path:
    """Path to knowledge registry directory."""
    if config is None:
        from ..config import load_config
        config = load_config()
    from ..config import get_output_dir
    out_dir = get_output_dir(config)
    return out_dir.parent / "knowledge"


def _registry_path(registry_dir: Path, name: str) -> Path:
    return registry_dir / f"{name}.json"


def list_documented_blends(config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Return all documented blends with their unique names."""
    reg = load_registry("learned_blends", config)
    return reg.get("blends", [])


def load_registry(name: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load a learned registry (e.g. colors, motion). Returns {} if missing."""
    reg_dir = get_registry_dir(config)
    path = _registry_path(reg_dir, name)
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_registry(name: str, data: dict[str, Any], config: dict[str, Any] | None = None) -> Path:
    """Save a learned registry."""
    reg_dir = get_registry_dir(config)
    reg_dir.mkdir(parents=True, exist_ok=True)
    path = _registry_path(reg_dir, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _color_key(r: float, g: float, b: float, *, tolerance: int = 20) -> str:
    """Quantize RGB to reduce near-duplicates."""
    br = int(r // tolerance) * tolerance
    bg = int(g // tolerance) * tolerance
    bb = int(b // tolerance) * tolerance
    return f"{br},{bg},{bb}"


def is_color_novel(
    r: float, g: float, b: float,
    learned: dict[str, Any],
    *,
    tolerance: int = 25,
) -> bool:
    """True if this color is not already in learned registry."""
    key = _color_key(r, g, b, tolerance=tolerance)
    return key not in learned.get("colors", {})


def add_learned_color(
    r: float, g: float, b: float,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """
    Add a discovered color to the learned registry.
    Returns the unique blend name if this was a novel color, else None.
    """
    reg = load_registry("learned_colors", config)
    colors = reg.get("colors", {})
    key = _color_key(r, g, b, tolerance=25)
    blend_name = None
    if key not in colors:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        colors[key] = {
            "r": round(float(r), 1),
            "g": round(float(g), 1),
            "b": round(float(b), 1),
            "count": 1,
            "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        }
        from .blend_depth import compute_color_depth
        _record_blend(
            name=blend_name,
            domain="color",
            inputs={"key": key},
            output={"r": r, "g": g, "b": b},
            source_prompt=source_prompt,
            primitive_depths=compute_color_depth(r, g, b),
            config=config,
        )
    else:
        colors[key]["count"] = colors[key].get("count", 0) + 1
        if source_prompt and len(colors[key].get("sources", [])) < 5:
            colors[key].setdefault("sources", []).append(source_prompt[:80])
    reg["colors"] = colors
    save_registry("learned_colors", reg, config)
    return blend_name


def _record_blend(
    name: str,
    domain: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
    *,
    source_prompt: str = "",
    primitive_depths: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
) -> None:
    """
    Document a successful blend with its unique name.
    primitive_depths: how far down each side of the blend is w.r.t. origin primitives.
    For single-domain: {primitive: depth}, e.g. {"ocean": 0.6, "fire": 0.4}.
    For full_blend: {domain: {primitive: depth}}.
    """
    reg = load_registry("learned_blends", config)
    blends = reg.get("blends", [])
    entry: dict[str, Any] = {
        "name": name,
        "domain": domain,
        "inputs": inputs,
        "output": output,
        "source_prompt": source_prompt[:120] if source_prompt else "",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    if primitive_depths is not None:
        entry["primitive_depths"] = primitive_depths
    blends.append(entry)
    reg["blends"] = blends[-2000:]  # Keep last 2000
    save_registry("learned_blends", reg, config)


def add_learned_motion_profile(
    motion_level: float,
    motion_std: float,
    motion_trend: str,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """
    Add a discovered motion profile to the learned registry.
    Returns the unique blend name if novel, else None.
    """
    reg = load_registry("learned_motion", config)
    profiles = reg.get("profiles", [])
    level_bucket = round(motion_level, 1)
    trend = motion_trend or "steady"
    key = f"{level_bucket}_{trend}"
    blend_name = None
    found = False
    for p in profiles:
        if p.get("key") == key:
            p["count"] = p.get("count", 0) + 1
            if source_prompt:
                p.setdefault("sources", [])[:] = (p.get("sources", []) + [source_prompt[:80]])[:5]
            found = True
            break
    if not found:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        profiles.append({
            "key": key,
            "motion_level": round(motion_level, 3),
            "motion_std": round(motion_std, 3),
            "motion_trend": trend,
            "count": 1,
            "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        })
        from .blend_depth import compute_motion_depth
        _record_blend(
            name=blend_name,
            domain="motion",
            inputs={"motion_level": motion_level, "motion_std": motion_std, "motion_trend": trend},
            output={"key": key},
            source_prompt=source_prompt,
            primitive_depths=compute_motion_depth(motion_level, trend),
            config=config,
        )
    reg["profiles"] = profiles[-500:]
    save_registry("learned_motion", reg, config)
    return blend_name


def add_learned_lighting_profile(
    brightness: float,
    contrast: float,
    saturation: float,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """Add a discovered lighting profile. Returns blend name if novel."""
    reg = load_registry("learned_lighting", config)
    profiles = reg.get("profiles", [])
    key = f"{round(brightness/25)*25}_{round(contrast,1)}_{round(saturation,1)}"
    found = any(p.get("key") == key for p in profiles)
    if not found:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        profiles.append({
            "key": key,
            "brightness": round(brightness, 2),
            "contrast": round(contrast, 3),
            "saturation": round(saturation, 3),
            "count": 1,
            "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        })
        from .blend_depth import compute_lighting_depth
        _record_blend(name=blend_name, domain="lighting", inputs={"key": key},
            output={"brightness": brightness, "contrast": contrast, "saturation": saturation},
            source_prompt=source_prompt,
            primitive_depths=compute_lighting_depth(brightness, contrast, saturation),
            config=config)
        reg["profiles"] = profiles[-500:]
        save_registry("learned_lighting", reg, config)
        return blend_name
    return None


def add_learned_composition_profile(
    center_x: float,
    center_y: float,
    luminance_balance: float,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """Add a discovered composition profile. Returns blend name if novel."""
    reg = load_registry("learned_composition", config)
    profiles = reg.get("profiles", [])
    key = f"{round(center_x,2)}_{round(center_y,2)}_{round(luminance_balance,2)}"
    found = any(p.get("key") == key for p in profiles)
    if not found:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        profiles.append({
            "key": key,
            "center_x": center_x, "center_y": center_y,
            "luminance_balance": luminance_balance,
            "count": 1, "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        })
        from .blend_depth import compute_composition_depth
        _record_blend(name=blend_name, domain="composition", inputs={"key": key},
            output={"center_x": center_x, "center_y": center_y, "luminance_balance": luminance_balance},
            source_prompt=source_prompt,
            primitive_depths=compute_composition_depth(center_x, center_y, luminance_balance),
            config=config)
        reg["profiles"] = profiles[-500:]
        save_registry("learned_composition", reg, config)
        return blend_name
    return None


def add_learned_graphics_profile(
    edge_density: float,
    spatial_variance: float,
    busyness: float,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """Add a discovered graphics profile. Returns blend name if novel."""
    reg = load_registry("learned_graphics", config)
    profiles = reg.get("profiles", [])
    key = f"{round(edge_density,2)}_{round(spatial_variance,2)}_{round(busyness,2)}"
    found = any(p.get("key") == key for p in profiles)
    if not found:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        profiles.append({
            "key": key,
            "edge_density": edge_density, "spatial_variance": spatial_variance,
            "busyness": busyness,
            "count": 1, "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        })
        from .blend_depth import compute_graphics_depth
        _record_blend(name=blend_name, domain="graphics", inputs={"key": key},
            output={"edge_density": edge_density, "spatial_variance": spatial_variance, "busyness": busyness},
            source_prompt=source_prompt,
            primitive_depths=compute_graphics_depth(edge_density, spatial_variance, busyness),
            config=config)
        reg["profiles"] = profiles[-500:]
        save_registry("learned_graphics", reg, config)
        return blend_name
    return None


def add_learned_temporal_profile(
    duration: float,
    motion_trend: str,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """Add a discovered temporal profile. Returns blend name if novel."""
    reg = load_registry("learned_temporal", config)
    profiles = reg.get("profiles", [])
    key = f"{round(duration,1)}_{motion_trend}"
    found = any(p.get("key") == key for p in profiles)
    if not found:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        profiles.append({
            "key": key,
            "duration": duration, "motion_trend": motion_trend,
            "count": 1, "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        })
        from .blend_depth import compute_temporal_depth
        _record_blend(name=blend_name, domain="temporal", inputs={"key": key},
            output={"duration": duration, "motion_trend": motion_trend},
            source_prompt=source_prompt,
            primitive_depths=compute_temporal_depth(duration, motion_trend),
            config=config)
        reg["profiles"] = profiles[-500:]
        save_registry("learned_temporal", reg, config)
        return blend_name
    return None


def add_learned_technical_profile(
    width: int,
    height: int,
    fps: float,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str | None:
    """Add a discovered technical profile. Returns blend name if novel."""
    reg = load_registry("learned_technical", config)
    profiles = reg.get("profiles", [])
    key = f"{width}x{height}_{fps}"
    found = any(p.get("key") == key for p in profiles)
    if not found:
        from .name_reserve import take as reserve_take
        blend_name = reserve_take(config=config)
        profiles.append({
            "key": key,
            "width": width, "height": height, "fps": fps,
            "count": 1, "sources": [source_prompt[:80]] if source_prompt else [],
            "name": blend_name,
        })
        from .blend_depth import compute_technical_depth
        _record_blend(name=blend_name, domain="technical", inputs={"key": key},
            output={"width": width, "height": height, "fps": fps},
            source_prompt=source_prompt,
            primitive_depths=compute_technical_depth(width, height, fps),
            config=config)
        reg["profiles"] = profiles[-500:]
        save_registry("learned_technical", reg, config)
        return blend_name
    return None


def extract_and_record_full_blend(
    domains: dict[str, dict[str, Any]],
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
) -> str:
    """
    Blend extraction: record the full blend of all domains as a single discovery.
    The combination of origins that produced this output gets a unique name.
    Records primitive_depths for each domain: how far down each side of the blend
    is with respect to origin primitives.
    Returns the blend name.
    """
    from .name_reserve import take as reserve_take
    from .blend_depth import compute_full_blend_depths
    blend_name = reserve_take(config=config)
    primitive_depths = compute_full_blend_depths(domains)
    _record_blend(
        name=blend_name,
        domain="full_blend",
        inputs={"domains": list(domains.keys())},
        output=domains,
        source_prompt=source_prompt,
        primitive_depths=primitive_depths,
        config=config,
    )
    return blend_name
