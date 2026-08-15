"""
Import measured masses from a loop-origin field (e.g. the Boing promo) as
photoreal meshes.

The source video is not copied or replayed. Indexed field frames already
store palette masses; this module turns stable masses into silhouette
meshes the photoreal overlay can draw.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .obj import Mesh, write_obj


def extract_objects_from_origin(
    origin: dict[str, Any] | None,
    *,
    max_objects: int = 8,
    sample_frames: int = 8,
) -> list[dict[str, Any]]:
    """Find stable masses in the origin field and return mesh-ready object dicts."""
    if not isinstance(origin, dict):
        return []
    field = origin.get("field") or {}
    blobs = field.get("frames") or []
    lut = field.get("lut") or []
    width = int(field.get("width") or 0)
    height = int(field.get("height") or 0)
    if not blobs or not lut or width < 8 or height < 8:
        return []

    from ..knowledge.pixel_emergence import _guess_kind
    from ..knowledge.reference_origin import decode_index_map

    n = len(blobs)
    picks = [int(round(i * (n - 1) / max(1, sample_frames - 1))) for i in range(min(sample_frames, n))]
    seen: dict[tuple[str, int, int], dict[str, Any]] = {}
    for fi in picks:
        idx = decode_index_map(blobs[fi], height, width)
        for region in _regions_from_indices(idx, lut):
            kind = _guess_kind(region)
            key = (kind, int(region["cx"] * 8), int(region["cy"] * 8))
            prev = seen.get(key)
            if prev is None or region["frac"] > prev["frac"]:
                region["kind"] = kind
                seen[key] = region
    ranked = sorted(seen.values(), key=lambda r: -float(r.get("frac") or 0))
    out: list[dict[str, Any]] = []
    for i, region in enumerate(ranked[: max(1, int(max_objects))]):
        mesh = silhouette_mesh(region["mask"])
        if not mesh.faces:
            continue
        color = (
            int(np.clip(region["r"], 0, 255)),
            int(np.clip(region["g"], 0, 255)),
            int(np.clip(region["b"], 0, 255)),
        )
        out.append({
            "id": f"origin_{i}_{region['kind']}",
            "kind": region["kind"],
            "cx": round(float(region["cx"]), 4),
            "cy": round(float(region["cy"]), 4),
            "scale": round(max(0.35, min(1.8, float(region["frac"]) * 8.0)), 3),
            "color": list(color),
            "frac": round(float(region["frac"]), 4),
            "mesh_obj": write_obj(mesh),
            "source": "loop_origin_field",
        })
    return out


def extract_and_store_origin_objects(
    loop: str = "cartoon",
    *,
    config: dict[str, Any] | None = None,
    max_objects: int = 8,
) -> list[dict[str, Any]]:
    """Update the saved loop origin with imported object meshes."""
    from ..knowledge.reference_origin import load_loop_origin, save_loop_origin

    origin = load_loop_origin(loop, config=config)
    objects = extract_objects_from_origin(origin, max_objects=max_objects)
    if origin is None:
        return []
    origin["objects"] = objects
    origin["object_count"] = len(objects)
    save_loop_origin(origin, loop=loop, config=config)
    return objects


def attach_origin_objects(
    scene_layers: list[dict[str, Any]] | None,
    origin: dict[str, Any] | None,
    *,
    max_attach: int = 4,
) -> list[dict[str, Any]]:
    """Add origin meshes as background props (does not clone over the named subject)."""
    layers = list(scene_layers or [])
    objects = (origin or {}).get("objects") if isinstance(origin, dict) else None
    if not objects:
        return layers
    objects = _hydrate_object_meshes(objects)
    used_kinds = {str(L.get("kind") or "") for L in layers}
    added = 0
    for obj in objects:
        if added >= max_attach:
            break
        if not isinstance(obj, dict) or not obj.get("mesh_obj"):
            continue
        kind = str(obj.get("kind") or "composed")
        # Keep the foreground subject unique; origin masses become scenery.
        if kind in used_kinds and kind in ("character", "circle"):
            continue
        cx = float(obj.get("cx") or 0.5)
        cy = float(obj.get("cy") or 0.55)
        scale = float(obj.get("scale") or 0.8)
        color = obj.get("color") or [120, 120, 120]
        layers.append({
            "id": str(obj.get("id") or f"origin_{added}"),
            "kind": kind if kind != "composed" else "circle",
            "color": [int(color[0]), int(color[1]), int(color[2])],
            "z": 0,
            "is_prop": True,
            "mesh_obj": obj["mesh_obj"],
            "origin_object_id": obj.get("id"),
            "keyframes": [
                {"t": 0, "x": cx, "y": cy, "scale": scale, "rot": 0, "opacity": 0.92},
                {"t": 1, "x": cx, "y": cy, "scale": scale, "rot": 0, "opacity": 0.92},
            ],
        })
        added += 1
    return layers


def _hydrate_object_meshes(objects: list[Any]) -> list[Any]:
    """Restore mesh_obj from the saved origin when the job spec was slimmed."""
    if all(not isinstance(o, dict) or o.get("mesh_obj") for o in objects):
        return objects
    from ..knowledge.reference_origin import load_loop_origin

    stored = load_loop_origin("cartoon") or {}
    by_id = {
        str(o.get("id")): o
        for o in (stored.get("objects") or [])
        if isinstance(o, dict) and o.get("id") and o.get("mesh_obj")
    }
    out: list[Any] = []
    for obj in objects:
        if isinstance(obj, dict) and not obj.get("mesh_obj"):
            full = by_id.get(str(obj.get("id") or ""))
            if full:
                obj = {**obj, "mesh_obj": full["mesh_obj"]}
        out.append(obj)
    return out


def silhouette_mesh(mask: np.ndarray, *, depth: float = 0.10) -> Mesh:
    """Extrude a binary mass into a low-poly front-facing mesh (local origin)."""
    if mask.ndim != 2 or not bool(mask.any()):
        return Mesh(vertices=[], normals=[], faces=[])
    # Work in a tight bbox, then downsample so OBJ stays small
    ys, xs = np.where(mask)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    crop = mask[y0:y1, x0:x1]
    ch, cw = crop.shape
    max_side = 18
    step_y = max(1, ch // max_side)
    step_x = max(1, cw // max_side)
    small = crop[::step_y, ::step_x]
    sh, sw = small.shape
    if sh < 2 or sw < 2:
        return Mesh(vertices=[], normals=[], faces=[])
    verts: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    index = np.full((sh, sw), -1, dtype=np.int32)
    for y in range(sh):
        for x in range(sw):
            if not small[y, x]:
                continue
            # Local coords centered on the mass, y down to match overlay
            px = (x / max(sw - 1, 1) - 0.5) * 0.9
            py = (y / max(sh - 1, 1) - 0.5) * 0.9
            edge = _is_edge(small, y, x)
            z = depth * (0.45 if edge else 1.0)
            index[y, x] = len(verts)
            verts.append((px, py, z))
    if len(verts) < 3:
        return Mesh(vertices=[], normals=[], faces=[])
    for y in range(sh - 1):
        for x in range(sw - 1):
            a = int(index[y, x])
            b = int(index[y, x + 1])
            c = int(index[y + 1, x])
            d = int(index[y + 1, x + 1])
            if a >= 0 and b >= 0 and c >= 0:
                faces.append((a, c, b))
            if b >= 0 and c >= 0 and d >= 0:
                faces.append((b, c, d))
    norms = [(0.0, 0.0, 1.0)] * len(verts)
    return Mesh(vertices=verts, normals=norms, faces=faces)


def _is_edge(mask: np.ndarray, y: int, x: int) -> bool:
    h, w = mask.shape
    for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        ny, nx = y + dy, x + dx
        if ny < 0 or nx < 0 or ny >= h or nx >= w or not mask[ny, nx]:
            return True
    return False


def _regions_from_indices(
    idx: np.ndarray,
    lut: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    h, w = idx.shape
    total = float(h * w)
    # Skip ink (0) and the dominant background label
    flat = idx.reshape(-1)
    counts = np.bincount(flat.astype(np.int32), minlength=int(idx.max()) + 1)
    bg = int(np.argmax(counts))
    min_cells = max(24, int(0.012 * total))
    max_cells = int(0.42 * total)
    seen = np.zeros((h, w), dtype=bool)
    out: list[dict[str, Any]] = []
    for y in range(h):
        for x in range(w):
            if seen[y, x]:
                continue
            lab = int(idx[y, x])
            seen[y, x] = True
            if lab == 0 or lab == bg:
                continue
            stack = [(y, x)]
            cells: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and int(idx[ny, nx]) == lab:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            n = len(cells)
            if n < min_cells or n > max_cells:
                continue
            mask = np.zeros((h, w), dtype=bool)
            for cy, cx in cells:
                mask[cy, cx] = True
            ys, xs = np.where(mask)
            y0, y1 = int(ys.min()), int(ys.max())
            x0, x1 = int(xs.min()), int(xs.max())
            swatch = lut[lab] if 0 <= lab < len(lut) else {"r": 120, "g": 120, "b": 120}
            r, g, b = float(swatch.get("r", 120)), float(swatch.get("g", 120)), float(swatch.get("b", 120))
            bh = max(1, y1 - y0 + 1)
            bw = max(1, x1 - x0 + 1)
            out.append({
                "r": r,
                "g": g,
                "b": b,
                "luma": 0.299 * r + 0.587 * g + 0.114 * b,
                "cy": ((y0 + y1) / 2.0) / max(h - 1, 1),
                "cx": ((x0 + x1) / 2.0) / max(w - 1, 1),
                "aspect": bh / float(bw),
                "compact": n / float(bh * bw),
                "frac": n / total,
                "color_hint": "blue" if b > r + 20 and b > g else ("forest" if g > r + 15 else "none"),
                "mask": mask,
            })
    out.sort(key=lambda r: -float(r["frac"]))
    return out[:10]
