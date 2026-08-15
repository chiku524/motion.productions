"""
Photoreal 3D primitives (Roadmap 7.3).

No external OBJ/glTF catalog. Each subject is a small recipe of analytic
meshes (sphere, capsule, cylinder, cone, box) authored from kind + form seed.
Albedo comes from the layer color after registry bind. Lighting uses real
normals and the same key/fill/rim/ambient model as the 2.5D path.
"""
from __future__ import annotations

from typing import Any

from ..procedural.parser import SceneSpec

# Local part recipes: offsets/radii are fractions of the layer radius.
# Unique form seeds scale these — never a fixed asset file.
_KIND_PARTS: dict[str, list[dict[str, Any]]] = {
    "character": [
        {"shape": "capsule", "dx": 0.0, "dy": 0.18, "rx": 0.55, "ry": 0.72, "role": "body"},
        {"shape": "sphere", "dx": 0.0, "dy": -0.62, "rx": 0.42, "ry": 0.42, "role": "head"},
    ],
    "tree": [
        {"shape": "cylinder", "dx": 0.0, "dy": 0.48, "rx": 0.18, "ry": 0.55, "role": "trunk"},
        {"shape": "sphere", "dx": 0.0, "dy": -0.22, "rx": 0.95, "ry": 0.82, "role": "canopy"},
    ],
    "building": [
        {"shape": "box", "dx": 0.0, "dy": 0.04, "rx": 0.72, "ry": 0.95, "role": "body"},
    ],
    "cloud": [
        {"shape": "sphere", "dx": -0.32, "dy": 0.04, "rx": 0.58, "ry": 0.40, "role": "puff"},
        {"shape": "sphere", "dx": 0.28, "dy": 0.00, "rx": 0.64, "ry": 0.42, "role": "puff"},
        {"shape": "sphere", "dx": 0.00, "dy": -0.16, "rx": 0.50, "ry": 0.36, "role": "puff"},
    ],
    "circle": [
        {"shape": "sphere", "dx": 0.0, "dy": 0.0, "rx": 1.0, "ry": 1.0, "role": "body"},
    ],
    "vehicle": [
        {"shape": "box", "dx": 0.0, "dy": -0.06, "rx": 0.95, "ry": 0.38, "role": "body"},
        {"shape": "sphere", "dx": -0.48, "dy": 0.28, "rx": 0.24, "ry": 0.24, "role": "wheel"},
        {"shape": "sphere", "dx": 0.48, "dy": 0.28, "rx": 0.24, "ry": 0.24, "role": "wheel"},
    ],
    "fish": [
        {"shape": "sphere", "dx": 0.08, "dy": 0.0, "rx": 0.85, "ry": 0.46, "role": "body"},
        {"shape": "cone", "dx": -0.70, "dy": 0.0, "rx": 0.32, "ry": 0.28, "role": "tail"},
    ],
    "wave": [
        {"shape": "sphere", "dx": 0.0, "dy": 0.10, "rx": 1.10, "ry": 0.38, "role": "body"},
    ],
    "bird": [
        {"shape": "sphere", "dx": 0.0, "dy": 0.0, "rx": 0.42, "ry": 0.30, "role": "body"},
        {"shape": "cone", "dx": 0.40, "dy": -0.04, "rx": 0.28, "ry": 0.14, "role": "beak"},
    ],
    "star": [
        {"shape": "sphere", "dx": 0.0, "dy": 0.0, "rx": 0.55, "ry": 0.55, "role": "body"},
    ],
    "rect": [
        {"shape": "box", "dx": 0.0, "dy": 0.0, "rx": 0.72, "ry": 0.55, "role": "body"},
    ],
}


def mesh_recipe_for_kind(kind: str, form: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    Load the primitive recipe for a subject kind, scaled by the per-video form.

    This is the 7.3 loader: recipes, not a file catalog.
    """
    key = str(kind or "circle").lower().strip()
    if key == "composed":
        key = "circle"
    base = _KIND_PARTS.get(key) or _KIND_PARTS["circle"]
    form = form or {}
    mul = float(form.get("radius_mul") or 1.0)
    aspect = float(form.get("aspect") or 1.0)
    # 2D forms store head/body as fractions of layer radius (~0.45 / ~0.72).
    head_nudge = float(form.get("head_scale") or 0.45) / 0.45
    body_nudge = float(form.get("body_scale") or 0.72) / 0.72
    out: list[dict[str, Any]] = []
    for part in base:
        p = dict(part)
        role = str(p.get("role") or "body")
        scale = mul
        if role == "head":
            scale *= head_nudge
        elif role in ("body", "canopy", "puff"):
            scale *= body_nudge
        p["rx"] = float(p["rx"]) * scale * (aspect if role != "head" else 1.0)
        p["ry"] = float(p["ry"]) * scale
        p["dx"] = float(p["dx"]) * scale
        p["dy"] = float(p["dy"]) * scale
        out.append(p)
    return out


def _albedo_for_part(
    role: str,
    base: tuple[int, int, int],
) -> tuple[float, float, float]:
    r, g, b = float(base[0]), float(base[1]), float(base[2])
    if role == "trunk":
        return (max(20.0, r * 0.45), max(16.0, g * 0.35), max(10.0, b * 0.22))
    if role == "wheel":
        return (max(18.0, r * 0.25), max(18.0, g * 0.25), max(18.0, b * 0.25))
    if role == "canopy":
        return (r * 0.55 + 20.0, min(255.0, g * 1.05 + 18.0), b * 0.45)
    return (r, g, b)


def _shade(
    albedo: tuple[float, float, float],
    nx: "np.ndarray",  # noqa: F821
    ny: "np.ndarray",  # noqa: F821
    nz: "np.ndarray",  # noqa: F821
    lighting_model: tuple[float, float, float, float],
) -> "np.ndarray":  # noqa: F821
    import numpy as np

    key, fill, rim, ambient = lighting_model
    lx, ly, lz = -0.55, -0.72, 0.48
    inv = 1.0 / max(1e-6, (lx * lx + ly * ly + lz * lz) ** 0.5)
    lx, ly, lz = lx * inv, ly * inv, lz * inv
    ndotl = np.clip(nx * lx + ny * ly + nz * lz, 0.0, 1.0)
    fx, fy, fz = 0.42, 0.32, 0.22
    ndotf = np.clip(nx * fx + ny * fy + nz * fz, 0.0, 1.0)
    rim_w = np.clip(1.0 - np.clip(nz, 0.0, 1.0), 0.0, 1.0) ** 2
    light = (
        float(ambient) * 0.55
        + float(key) * ndotl
        + float(fill) * ndotf * 0.50
        + float(rim) * rim_w * 0.70
    )
    light = np.clip(light, 0.22, 1.85)
    spec = (ndotl ** 16.0) * float(key) * 36.0
    r = np.clip(albedo[0] * light + spec, 0, 255)
    g = np.clip(albedo[1] * light + spec, 0, 255)
    b = np.clip(albedo[2] * light + spec, 0, 255)
    return np.stack([r, g, b], axis=-1)


def _raster_sphere(lx, ly, rx, ry):
    import numpy as np

    r = max(1e-6, 0.5 * (float(rx) + float(ry)))
    sx = lx / max(1e-6, float(rx) / r)
    sy = ly / max(1e-6, float(ry) / r)
    d2 = sx * sx + sy * sy
    inside = d2 <= r * r
    z = np.sqrt(np.clip(r * r - d2, 0.0, None))
    inv = 1.0 / r
    return inside, z, sx * inv, sy * inv, z * inv


def _raster_capsule(lx, ly, rx, ry):
    import numpy as np

    half = max(1e-6, float(ry) * 0.55)
    rad = max(1e-6, float(rx))
    # Cylinder body between two sphere caps
    cy = np.clip(ly, -half, half)
    dx = lx
    dy = ly - cy
    d2 = dx * dx + dy * dy
    inside = d2 <= rad * rad
    z = np.sqrt(np.clip(rad * rad - d2, 0.0, None))
    inv = 1.0 / rad
    return inside, z, dx * inv, dy * inv, z * inv


def _raster_cylinder(lx, ly, rx, ry):
    import numpy as np

    half = max(1e-6, float(ry))
    rad = max(1e-6, float(rx))
    body = (np.abs(ly) <= half) & (np.abs(lx) <= rad)
    z = np.sqrt(np.clip(rad * rad - lx * lx, 0.0, None))
    inv = 1.0 / rad
    nx = lx * inv
    nz = z * inv
    ny = np.where(np.abs(ly) > half * 0.92, np.sign(ly), 0.0)
    return body, z, nx, ny, nz


def _raster_cone(lx, ly, rx, ry):
    import numpy as np

    half = max(1e-6, float(ry))
    rad = max(1e-6, float(rx))
    t = np.clip((ly + half) / (2.0 * half), 0.0, 1.0)
    cr = rad * (1.0 - t)
    inside = (np.abs(ly) <= half) & (np.abs(lx) <= cr + 1e-6)
    z = np.sqrt(np.clip(cr * cr - lx * lx, 0.0, None))
    inv = 1.0 / max(1e-6, cr)
    return inside, z, lx * inv, 0.35 * np.ones_like(lx), z * inv


def _raster_box(lx, ly, rx, ry):
    import numpy as np

    hx, hy = max(1e-6, float(rx)), max(1e-6, float(ry))
    inside = (np.abs(lx) <= hx) & (np.abs(ly) <= hy)
    z = np.minimum(hx - np.abs(lx), hy - np.abs(ly))
    z = np.clip(z, 0.0, min(hx, hy))
    # Face normals: front (z) unless near an edge
    edge_x = np.abs(lx) / hx
    edge_y = np.abs(ly) / hy
    nx = np.where(edge_x > edge_y, np.sign(lx), 0.0)
    ny = np.where(edge_y >= edge_x, np.sign(ly), 0.0)
    nz = np.where((edge_x < 0.82) & (edge_y < 0.82), 1.0, 0.25)
    nlen = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
    return inside, z, nx / nlen, ny / nlen, nz / nlen


_RASTER = {
    "sphere": _raster_sphere,
    "capsule": _raster_capsule,
    "cylinder": _raster_cylinder,
    "cone": _raster_cone,
    "box": _raster_box,
}


def rasterize_parts(
    parts: list[dict[str, Any]],
    xx: "np.ndarray",  # noqa: F821
    yy: "np.ndarray",  # noqa: F821
    cx: float,
    cy: float,
    radius: float,
    albedo: tuple[int, int, int],
    lighting_model: tuple[float, float, float, float],
) -> tuple["np.ndarray", "np.ndarray"]:  # noqa: F821
    """Z-composite primitive parts → (rgb float HxWx3, alpha HxW)."""
    import numpy as np

    h, w = xx.shape
    zbuf = np.full((h, w), -1e9, dtype=np.float32)
    rgb = np.zeros((h, w, 3), dtype=np.float32)
    alpha = np.zeros((h, w), dtype=np.float32)
    r = max(1e-6, float(radius))
    for part in parts:
        fn = _RASTER.get(str(part.get("shape") or "sphere"), _raster_sphere)
        px = cx + float(part.get("dx", 0.0)) * r
        py = cy + float(part.get("dy", 0.0)) * r
        rx = float(part.get("rx", 0.4)) * r
        ry = float(part.get("ry", 0.4)) * r
        inside, z, nx, ny, nz = fn(xx - px, yy - py, rx, ry)
        shade = _shade(_albedo_for_part(str(part.get("role") or "body"), albedo), nx, ny, nz, lighting_model)
        closer = inside & (z > zbuf)
        zbuf = np.where(closer, z, zbuf)
        rgb = np.where(closer[..., None], shade, rgb)
        alpha = np.where(closer, 1.0, alpha)
    return rgb, alpha


def overlay_mesh_subjects(
    frame: "np.ndarray",  # noqa: F821
    spec: SceneSpec,
    *,
    t: float = 0.0,
) -> "np.ndarray":  # noqa: F821
    """Draw 3D primitive subjects over the photoreal frame (covers 2D blobs)."""
    import numpy as np

    from ..creation.scene_graph import composition_balance_offset, sample_layer_at
    from ..lighting.grading import get_lighting_model
    from ..procedural.forms import layer_form
    from .consumer import nearest_registry_color

    layers = getattr(spec, "scene_layers", None) or []
    if not layers:
        return frame

    h, w = frame.shape[:2]
    y = np.linspace(0.0, 1.0, h, dtype=np.float32)
    x = np.linspace(0.0, 1.0, w, dtype=np.float32)
    yy = np.broadcast_to(y[:, None], (h, w))
    xx = np.broadcast_to(x[None, :], (h, w))
    dx, dy = composition_balance_offset(getattr(spec, "composition_balance", "balanced") or "balanced")
    inst = getattr(spec, "instance", None) or {}
    bind = inst.get("photoreal_bind") if isinstance(inst, dict) else {}
    catalog = list((bind or {}).get("palette") or getattr(spec, "palette_colors", None) or [])
    catalog_t = [tuple(int(c) for c in rgb[:3]) for rgb in catalog if rgb and len(rgb) >= 3]
    lighting = get_lighting_model(
        str((bind or {}).get("lighting") or getattr(spec, "lighting_preset", None) or "neutral")
    )
    out = frame.astype(np.float32)
    ordered = sorted(
        (L for L in layers if isinstance(L, dict)),
        key=lambda L: int(L.get("z", 1)),
    )
    for layer in ordered:
        kind = str(layer.get("kind") or "circle")
        if kind in ("arrow", "text"):
            continue
        pose = sample_layer_at(layer, t)
        cx = max(0.04, min(0.96, float(pose["x"]) + dx))
        cy = max(0.04, min(0.96, float(pose["y"]) + dy))
        scale = max(0.18, float(pose["scale"]))
        radius = 0.14 * scale
        opacity = float(pose.get("opacity") or 1.0)
        if opacity < 0.05:
            continue
        color = layer.get("color") or (180, 80, 60)
        albedo = (int(color[0]), int(color[1]), int(color[2]))
        if catalog_t:
            albedo = nearest_registry_color(albedo, catalog_t)
        form = layer_form(layer, kind)
        parts = mesh_recipe_for_kind(kind, form)
        rgb, a = rasterize_parts(parts, xx, yy, cx, cy, radius, albedo, lighting)
        a = a * opacity
        out = out * (1.0 - a[..., None]) + rgb * a[..., None]
    return np.clip(out, 0, 255).astype(np.uint8)
