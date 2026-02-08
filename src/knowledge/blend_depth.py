"""
Blend depth: compute how far down each side of a blend is with respect to origins.
primitive_depths = {primitive_name: weight} — how much each origin contributed.
"""
from typing import Any


def _palette_mean_rgb(name: str) -> tuple[float, float, float]:
    """Mean RGB of a palette. Used as origin primitive for color depth."""
    from ..procedural.data.palettes import PALETTES
    colors = PALETTES.get(name, PALETTES["default"])
    if not colors:
        return 128.0, 128.0, 128.0
    n = len(colors)
    r = sum(c[0] for c in colors) / n
    g = sum(c[1] for c in colors) / n
    b = sum(c[2] for c in colors) / n
    return r, g, b


def compute_color_depth(r: float, g: float, b: float) -> dict[str, float]:
    """
    Compute primitive depths for an extracted color.
    Finds the 2 closest palette means and weights that would produce this RGB.
    """
    from ..procedural.data.palettes import PALETTES
    rgb = (r, g, b)
    best: list[tuple[str, float]] = []
    for name in PALETTES:
        mr, mg, mb = _palette_mean_rgb(name)
        dist = (r - mr) ** 2 + (g - mg) ** 2 + (b - mb) ** 2
        best.append((name, dist ** 0.5))
    best.sort(key=lambda x: x[1])
    if len(best) < 2:
        return {best[0][0]: 1.0} if best else {}
    # Two closest primitives; solve for weights that approximate rgb
    p1, d1 = best[0]
    p2, d2 = best[1]
    m1 = _palette_mean_rgb(p1)
    m2 = _palette_mean_rgb(p2)
    # weight toward p1: w1; toward p2: w2. w1 + w2 = 1.
    # rgb ≈ w1*m1 + w2*m2. Use inverse distance for weights.
    total = d1 + d2
    if total <= 0:
        return {p1: 0.5, p2: 0.5}
    w2 = d1 / total  # closer to p1 -> more weight on p1
    w1 = 1.0 - w2
    return {p1: round(w1, 3), p2: round(w2, 3)}


def compute_motion_depth(motion_level: float, motion_trend: str) -> dict[str, float]:
    """
    Map motion level/trend to primitive depths.
    speed primitives: static (0), slow (~5), medium (~10), fast (~20+)
    """
    speeds = ["static", "slow", "medium", "fast"]
    levels = [0.0, 5.0, 12.0, 25.0]
    w = [0.0] * 4
    for i in range(4):
        if i == 0:
            w[i] = max(0, 1 - motion_level / 5)
        elif i == 3:
            w[i] = max(0, (motion_level - 15) / 15)
        else:
            d = abs(motion_level - levels[i])
            w[i] = max(0, 1 - d / 10)
    total = sum(w)
    if total <= 0:
        w[1] = 1.0
        total = 1.0
    return {speeds[i]: round(w[i] / total, 3) for i in range(4) if w[i] > 0.01}


def compute_lighting_depth(brightness: float, contrast: float, saturation: float) -> dict[str, float]:
    """Map lighting values to primitive depths (contrast_ratio, key_intensity approx)."""
    depths: dict[str, float] = {}
    # Contrast ratio: flat < normal < high < chiaroscuro
    c_norm = contrast / 50.0 if contrast else 0.5
    depths["flat"] = max(0, 1 - c_norm)
    depths["normal"] = max(0, 0.8 - abs(c_norm - 0.5))
    depths["high"] = max(0, c_norm - 0.3)
    depths["chiaroscuro"] = max(0, c_norm - 0.7)
    total = sum(depths.values())
    if total <= 0:
        depths["normal"] = 1.0
        total = 1.0
    return {k: round(v / total, 3) for k, v in depths.items() if v > 0.01}


def compute_composition_depth(
    center_x: float,
    center_y: float,
    luminance_balance: float,
) -> dict[str, float]:
    """Map composition to primitive depths (balance, framing approx)."""
    depths: dict[str, float] = {}
    # Balance: left_heavy (cx<0.4), balanced (0.4-0.6), right_heavy (cx>0.6)
    if center_x < 0.4:
        depths["left_heavy"] = 1 - center_x / 0.4
    elif center_x > 0.6:
        depths["right_heavy"] = (center_x - 0.6) / 0.4
    else:
        depths["balanced"] = 1 - abs(center_x - 0.5) * 2
    if luminance_balance < 0.4:
        depths["top_heavy"] = 1 - luminance_balance / 0.4
    elif luminance_balance > 0.6:
        depths["bottom_heavy"] = (luminance_balance - 0.6) / 0.4
    else:
        depths.setdefault("balanced", 0)
        depths["balanced"] += 0.5
    total = sum(depths.values())
    if total <= 0:
        depths["balanced"] = 1.0
        total = 1.0
    return {k: round(v / total, 3) for k, v in depths.items() if v > 0.01}


def compute_graphics_depth(
    edge_density: float,
    spatial_variance: float,
    busyness: float,
) -> dict[str, float]:
    """Map graphics to primitive depths (numeric origins)."""
    return {
        "edge_density": round(min(1.0, edge_density), 3),
        "spatial_variance": round(min(1.0, spatial_variance), 3),
        "busyness": round(min(1.0, busyness), 3),
    }


def compute_temporal_depth(duration: float, motion_trend: str) -> dict[str, float]:
    """Map temporal to primitive depths (pacing: fast/normal/slow, story_beats)."""
    depths: dict[str, float] = {}
    # Pacing from duration: short = fast, long = slow
    if duration < 3:
        depths["fast"] = 1 - duration / 3
    elif duration > 10:
        depths["slow"] = min(1, (duration - 10) / 20)
    else:
        depths["normal"] = 1 - abs(duration - 5) / 5
    total = sum(depths.values())
    if total <= 0:
        depths["normal"] = 1.0
    return {k: round(v, 3) for k, v in depths.items() if v > 0.01}


def compute_technical_depth(width: int, height: int, fps: float) -> dict[str, float]:
    """Map technical to primitive depths (resolution, fps)."""
    depths: dict[str, float] = {}
    res = (width, height)
    resolutions = [(256, 256), (512, 512), (720, 480), (1280, 720), (1920, 1080)]
    best = min(resolutions, key=lambda r: abs(r[0] - width) + abs(r[1] - height))
    depths[f"resolution_{best[0]}x{best[1]}"] = 1.0
    fps_vals = [12, 24, 30, 60]
    closest = min(fps_vals, key=lambda f: abs(f - fps))
    depths[f"fps_{closest}"] = 1.0
    return depths


def compute_full_blend_depths(domains: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    """
    Compute primitive depths for each domain in a full blend.
    Returns {domain: {primitive: depth}}.
    """
    result: dict[str, dict[str, float]] = {}
    d = domains

    if "color" in d:
        cd = d["color"]
        rgb = cd.get("dominant_rgb", cd.get("dominant_color_rgb", (0, 0, 0)))
        if rgb and len(rgb) >= 3:
            try:
                result["color"] = compute_color_depth(
                    float(rgb[0]), float(rgb[1]), float(rgb[2])
                )
            except (TypeError, ValueError):
                pass

    if "motion" in d:
        md = d["motion"]
        result["motion"] = compute_motion_depth(
            float(md.get("motion_level", 0)),
            str(md.get("motion_trend", "steady")),
        )

    if "lighting" in d:
        ld = d["lighting"]
        result["lighting"] = compute_lighting_depth(
            float(ld.get("brightness", ld.get("mean_brightness", 128))),
            float(ld.get("contrast", ld.get("mean_contrast", 50))),
            float(ld.get("saturation", 1.0)),
        )

    if "composition" in d:
        cd = d["composition"]
        if cd:
            result["composition"] = compute_composition_depth(
                float(cd.get("center_of_mass_x", 0.5)),
                float(cd.get("center_of_mass_y", 0.5)),
                float(cd.get("luminance_balance", 0.5)),
            )

    if "graphics" in d:
        gd = d["graphics"]
        if gd:
            result["graphics"] = compute_graphics_depth(
                float(gd.get("edge_density", 0)),
                float(gd.get("spatial_variance", 0)),
                float(gd.get("busyness", 0)),
            )

    if "temporal" in d:
        td = d["temporal"]
        result["temporal"] = compute_temporal_depth(
            float(td.get("duration_seconds", 5)),
            str(td.get("motion_trend", "steady")),
        )

    if "technical" in d:
        td = d["technical"]
        if td and (td.get("width") is not None or td.get("height") is not None):
            result["technical"] = compute_technical_depth(
                int(td.get("width", 512)),
                int(td.get("height", 512)),
                float(td.get("fps", 24)),
            )

    return result
