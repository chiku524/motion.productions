"""
OBJ / compact-glTF mesh loader and primitive tessellator.

Photoreal subjects can come from a file (`layer.mesh_path`) or from the
kind+form recipe tessellated into the same Mesh. No catalog of stock
characters — files are optional; recipes stay unique per seed.
"""
from __future__ import annotations

import base64
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class Mesh:
    """Triangle mesh in the same space as the photoreal overlay (x,y screen, z toward camera)."""

    vertices: list[tuple[float, float, float]]
    normals: list[tuple[float, float, float]]
    faces: list[tuple[int, int, int]]

    def __bool__(self) -> bool:
        return bool(self.faces) and bool(self.vertices)


def _norm(x: float, y: float, z: float) -> tuple[float, float, float]:
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return (x / n, y / n, z / n)


def parse_obj(text: str) -> Mesh:
    """Parse Wavefront OBJ (v, vn, f). Quads become two triangles."""
    verts: list[tuple[float, float, float]] = []
    norms: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    face_n: list[tuple[int, int, int] | None] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        tag = parts[0]
        if tag == "v" and len(parts) >= 4:
            verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif tag == "vn" and len(parts) >= 4:
            norms.append((float(parts[1]), float(parts[2]), float(parts[3])))
        elif tag == "f" and len(parts) >= 4:
            idxs: list[int] = []
            nidxs: list[int] = []
            for tok in parts[1:]:
                bits = tok.split("/")
                idxs.append(int(bits[0]))
                if len(bits) >= 3 and bits[2]:
                    nidxs.append(int(bits[2]))
            # OBJ is 1-based; negatives count from end
            def _vi(i: int) -> int:
                return i - 1 if i > 0 else len(verts) + i

            def _ni(i: int) -> int:
                return i - 1 if i > 0 else len(norms) + i

            vis = [_vi(i) for i in idxs]
            nis = [_ni(i) for i in nidxs] if len(nidxs) == len(idxs) else []
            for k in range(1, len(vis) - 1):
                faces.append((vis[0], vis[k], vis[k + 1]))
                if nis:
                    face_n.append((nis[0], nis[k], nis[k + 1]))
                else:
                    face_n.append(None)
    out_n = _normals_for_faces(verts, faces, norms, face_n)
    return Mesh(vertices=verts, normals=out_n, faces=faces)


def _normals_for_faces(
    verts: list[tuple[float, float, float]],
    faces: list[tuple[int, int, int]],
    norms: list[tuple[float, float, float]],
    face_n: list[tuple[int, int, int] | None],
) -> list[tuple[float, float, float]]:
    if len(norms) == len(verts) and all(fn is None for fn in face_n):
        return [_norm(*n) for n in norms]
    # Average corner normals; fall back to face normal
    acc = [(0.0, 0.0, 0.0) for _ in verts]
    for fi, (a, b, c) in enumerate(faces):
        fn = face_n[fi] if fi < len(face_n) else None
        if fn and norms:
            for vi, ni in zip((a, b, c), fn, strict=False):
                if 0 <= ni < len(norms) and 0 <= vi < len(verts):
                    nx, ny, nz = norms[ni]
                    ax, ay, az = acc[vi]
                    acc[vi] = (ax + nx, ay + ny, az + nz)
            continue
        ax, ay, az = verts[a]
        bx, by, bz = verts[b]
        cx, cy, cz = verts[c]
        ux, uy, uz = bx - ax, by - ay, bz - az
        vx, vy, vz = cx - ax, cy - ay, cz - az
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        for vi in (a, b, c):
            sx, sy, sz = acc[vi]
            acc[vi] = (sx + nx, sy + ny, sz + nz)
    return [_norm(*n) if (n[0] or n[1] or n[2]) else (0.0, 0.0, 1.0) for n in acc]


def write_obj(mesh: Mesh) -> str:
    """Serialize a Mesh to OBJ text (v, vn, f with matching indices)."""
    lines = ["# motion.productions photoreal mesh"]
    for x, y, z in mesh.vertices:
        lines.append(f"v {x:.6f} {y:.6f} {z:.6f}")
    for x, y, z in mesh.normals:
        lines.append(f"vn {x:.6f} {y:.6f} {z:.6f}")
    for a, b, c in mesh.faces:
        lines.append(f"f {a + 1}//{a + 1} {b + 1}//{b + 1} {c + 1}//{c + 1}")
    return "\n".join(lines) + "\n"


def parse_gltf(data: dict[str, Any] | str) -> Mesh:
    """
    Load a mesh from compact JSON `{vertices, faces, normals?}` or a minimal
    glTF 2.0 document (first primitive POSITION + optional NORMAL / indices).
    """
    if isinstance(data, str):
        data = json.loads(data)
    if not isinstance(data, dict):
        return Mesh(vertices=[], normals=[], faces=[])
    if "vertices" in data and "faces" in data:
        verts = [tuple(float(c) for c in v[:3]) for v in data["vertices"]]
        faces = [tuple(int(i) for i in f[:3]) for f in data["faces"]]
        norms_in = data.get("normals") or []
        norms = [tuple(float(c) for c in n[:3]) for n in norms_in] if norms_in else []
        if len(norms) != len(verts):
            norms = _normals_for_faces(verts, faces, [], [None] * len(faces))
        return Mesh(vertices=verts, normals=norms, faces=faces)
    return _parse_gltf2(data)


def _parse_gltf2(doc: dict[str, Any]) -> Mesh:
    meshes = doc.get("meshes") or []
    accessors = doc.get("accessors") or []
    views = doc.get("bufferViews") or []
    buffers = doc.get("buffers") or []
    if not meshes or not accessors:
        return Mesh(vertices=[], normals=[], faces=[])
    prims = (meshes[0].get("primitives") or []) if isinstance(meshes[0], dict) else []
    if not prims:
        return Mesh(vertices=[], normals=[], faces=[])
    prim = prims[0]
    attrs = prim.get("attributes") or {}
    pos = _read_accessor(doc, accessors, views, buffers, attrs.get("POSITION"))
    nrm = _read_accessor(doc, accessors, views, buffers, attrs.get("NORMAL"))
    idx = _read_accessor(doc, accessors, views, buffers, prim.get("indices"), integers=True)
    if not pos:
        return Mesh(vertices=[], normals=[], faces=[])
    verts = [(pos[i], pos[i + 1], pos[i + 2]) for i in range(0, len(pos) - 2, 3)]
    if idx:
        faces = [(int(idx[i]), int(idx[i + 1]), int(idx[i + 2])) for i in range(0, len(idx) - 2, 3)]
    else:
        faces = [(i, i + 1, i + 2) for i in range(0, len(verts) - 2, 3)]
    if nrm and len(nrm) >= len(verts) * 3:
        norms = [(nrm[i], nrm[i + 1], nrm[i + 2]) for i in range(0, len(verts) * 3, 3)]
    else:
        norms = _normals_for_faces(verts, faces, [], [None] * len(faces))
    return Mesh(vertices=verts, normals=norms, faces=faces)


def _read_accessor(
    doc: dict[str, Any],
    accessors: list,
    views: list,
    buffers: list,
    index: Any,
    *,
    integers: bool = False,
) -> list[float] | list[int]:
    if index is None:
        return []
    try:
        acc = accessors[int(index)]
    except (TypeError, ValueError, IndexError):
        return []
    if not isinstance(acc, dict):
        return []
    if "values" in acc and isinstance(acc["values"], list):
        return list(acc["values"])
    view_i = acc.get("bufferView")
    if view_i is None:
        return []
    try:
        view = views[int(view_i)]
        buf = buffers[int(view.get("buffer", 0))]
    except (TypeError, ValueError, IndexError):
        return []
    raw = _buffer_bytes(buf)
    if not raw:
        return []
    offset = int(view.get("byteOffset") or 0) + int(acc.get("byteOffset") or 0)
    count = int(acc.get("count") or 0)
    ctype = str(acc.get("componentType") or (5123 if integers else 5126))
    typ = str(acc.get("type") or ("SCALAR" if integers else "VEC3"))
    comps = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}.get(typ, 3)
    import struct

    fmt = {5126: "f", 5123: "H", 5125: "I", 5121: "B", 5120: "b", 5122: "h"}.get(int(ctype) if str(ctype).isdigit() else 5126, "f")
    n = count * comps
    chunk = raw[offset : offset + n * struct.calcsize(fmt)]
    vals = list(struct.unpack("<" + fmt * n, chunk)) if len(chunk) == n * struct.calcsize(fmt) else []
    return vals


def _buffer_bytes(buf: dict[str, Any]) -> bytes:
    uri = str(buf.get("uri") or "")
    if uri.startswith("data:") and "," in uri:
        payload = uri.split(",", 1)[1]
        try:
            return base64.b64decode(payload)
        except Exception:
            return b""
    return b""


def load_mesh(source: str | Path | dict[str, Any] | Mesh) -> Mesh:
    """Load from Mesh, dict, OBJ/glTF text, or a filesystem path."""
    if isinstance(source, Mesh):
        return source
    if isinstance(source, dict):
        return parse_gltf(source)
    path = Path(str(source))
    if path.is_file():
        text = path.read_text(encoding="utf-8", errors="replace")
        if path.suffix.lower() in (".gltf", ".json"):
            return parse_gltf(text)
        return parse_obj(text)
    text = str(source).strip()
    if text.startswith("{") or text.startswith("["):
        return parse_gltf(text)
    if "\nv " in f"\n{text}" or text.startswith("v "):
        return parse_obj(text)
    # Resolve relative to assets/meshes
    for root in (Path.cwd(), Path(__file__).resolve().parents[2]):
        cand = root / "assets" / "meshes" / str(source)
        if cand.is_file():
            return load_mesh(cand)
    return Mesh(vertices=[], normals=[], faces=[])


def tessellate_part(
    shape: str,
    dx: float,
    dy: float,
    rx: float,
    ry: float,
    *,
    segs: int = 8,
    rings: int = 5,
) -> Mesh:
    """Unit-local tessellation; rx/ry are already in world (normalized) units."""
    shape = (shape or "sphere").lower()
    rz = 0.5 * (abs(rx) + abs(ry))
    if shape == "box":
        return _tess_box(dx, dy, rx, ry, rz)
    if shape == "cylinder":
        return _tess_cylinder(dx, dy, rx, ry, segs)
    if shape == "cone":
        return _tess_cone(dx, dy, rx, ry, segs)
    if shape == "capsule":
        return _tess_capsule(dx, dy, rx, ry, segs, rings)
    return _tess_sphere(dx, dy, rx, ry, rz, segs, rings)


def tessellate_parts(parts: list[dict[str, Any]], *, radius: float) -> Mesh:
    """Merge recipe parts into one Mesh, scaled by layer radius."""
    r = max(1e-6, float(radius))
    verts: list[tuple[float, float, float]] = []
    norms: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    for part in parts:
        mesh = tessellate_part(
            str(part.get("shape") or "sphere"),
            float(part.get("dx", 0.0)) * r,
            float(part.get("dy", 0.0)) * r,
            float(part.get("rx", 0.4)) * r,
            float(part.get("ry", 0.4)) * r,
        )
        off = len(verts)
        verts.extend(mesh.vertices)
        norms.extend(mesh.normals)
        faces.extend((a + off, b + off, c + off) for a, b, c in mesh.faces)
    return Mesh(vertices=verts, normals=norms, faces=faces)


def translate_mesh(mesh: Mesh, cx: float, cy: float) -> Mesh:
    verts = [(x + cx, y + cy, z) for x, y, z in mesh.vertices]
    return Mesh(vertices=verts, normals=list(mesh.normals), faces=list(mesh.faces))


def _tess_sphere(dx, dy, rx, ry, rz, segs, rings) -> Mesh:
    segs = max(6, int(segs))
    rings = max(4, int(rings))
    verts: list[tuple[float, float, float]] = []
    norms: list[tuple[float, float, float]] = []
    for i in range(rings + 1):
        v = i / rings
        phi = v * math.pi
        sp, cp = math.sin(phi), math.cos(phi)
        for j in range(segs + 1):
            u = j / segs
            th = u * 2.0 * math.pi
            ct, st = math.cos(th), math.sin(th)
            nx, ny, nz = sp * ct, cp, sp * st
            verts.append((dx + rx * nx, dy + ry * ny, rz * nz))
            norms.append(_norm(nx / max(rx, 1e-6), ny / max(ry, 1e-6), nz / max(rz, 1e-6)))
    faces: list[tuple[int, int, int]] = []
    stride = segs + 1
    for i in range(rings):
        for j in range(segs):
            a = i * stride + j
            b = a + stride
            faces.append((a, b, a + 1))
            faces.append((a + 1, b, b + 1))
    return Mesh(vertices=verts, normals=norms, faces=faces)


def _tess_box(dx, dy, rx, ry, rz) -> Mesh:
    hx, hy, hz = abs(rx), abs(ry), abs(rz)
    corners = [
        (dx - hx, dy - hy, -hz),
        (dx + hx, dy - hy, -hz),
        (dx + hx, dy + hy, -hz),
        (dx - hx, dy + hy, -hz),
        (dx - hx, dy - hy, hz),
        (dx + hx, dy - hy, hz),
        (dx + hx, dy + hy, hz),
        (dx - hx, dy + hy, hz),
    ]
    faces_i = [
        (0, 1, 2), (0, 2, 3),
        (4, 6, 5), (4, 7, 6),
        (0, 4, 5), (0, 5, 1),
        (2, 6, 7), (2, 7, 3),
        (0, 3, 7), (0, 7, 4),
        (1, 5, 6), (1, 6, 2),
    ]
    return Mesh(
        vertices=corners,
        normals=_normals_for_faces(corners, faces_i, [], [None] * len(faces_i)),
        faces=faces_i,
    )


def _tess_cylinder(dx, dy, rx, ry, segs) -> Mesh:
    segs = max(6, int(segs))
    half = abs(ry)
    rad = abs(rx)
    verts: list[tuple[float, float, float]] = []
    norms: list[tuple[float, float, float]] = []
    for sign in (-1.0, 1.0):
        for j in range(segs):
            th = j / segs * 2.0 * math.pi
            ct, st = math.cos(th), math.sin(th)
            verts.append((dx + rad * ct, dy + sign * half, rad * st))
            norms.append(_norm(ct, 0.0, st))
    faces: list[tuple[int, int, int]] = []
    for j in range(segs):
        a, b = j, (j + 1) % segs
        c, d = j + segs, (j + 1) % segs + segs
        faces.append((a, b, d))
        faces.append((a, d, c))
    return Mesh(vertices=verts, normals=norms, faces=faces)


def _tess_cone(dx, dy, rx, ry, segs) -> Mesh:
    segs = max(6, int(segs))
    half = abs(ry)
    rad = abs(rx)
    tip = (dx, dy - half, 0.0)
    verts = [tip]
    norms = [_norm(0.0, -1.0, 0.0)]
    for j in range(segs):
        th = j / segs * 2.0 * math.pi
        ct, st = math.cos(th), math.sin(th)
        verts.append((dx + rad * ct, dy + half, rad * st))
        norms.append(_norm(ct, 0.35, st))
    faces = [(0, 1 + j, 1 + (j + 1) % segs) for j in range(segs)]
    return Mesh(vertices=verts, normals=norms, faces=faces)


def _tess_capsule(dx, dy, rx, ry, segs, rings) -> Mesh:
    half = abs(ry) * 0.55
    rad = abs(rx)
    top = _tess_sphere(dx, dy - half, rad, rad, rad, segs, max(3, rings // 2))
    bot = _tess_sphere(dx, dy + half, rad, rad, rad, segs, max(3, rings // 2))
    cyl = _tess_cylinder(dx, dy, rad, half, segs)
    verts = list(top.vertices) + list(bot.vertices) + list(cyl.vertices)
    norms = list(top.normals) + list(bot.normals) + list(cyl.normals)
    faces = list(top.faces)
    off = len(top.vertices)
    faces.extend((a + off, b + off, c + off) for a, b, c in bot.faces)
    off = len(top.vertices) + len(bot.vertices)
    faces.extend((a + off, b + off, c + off) for a, b, c in cyl.faces)
    return Mesh(vertices=verts, normals=norms, faces=faces)
