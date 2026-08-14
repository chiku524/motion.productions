"""
Per-video object creation: unique geometry from prompt + seed.

Registries control prompt-controlled *values* (palette, motion, sound).
Object silhouettes are created for each generation — never cloned from a
fixed template or copied from learned_entities.
"""
from __future__ import annotations

import hashlib
import random
from typing import Any

import numpy as np


def form_seed(prompt: str, layer_id: str, extra: int = 0) -> int:
    """Stable 31-bit seed from prompt, layer id, and per-run extra."""
    payload = f"{prompt or ''}\0{layer_id or ''}\0{int(extra)}".encode("utf-8", errors="replace")
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "little") % (2**31)


def create_form(
    kind: str,
    seed: int,
    *,
    prompt: str = "",
    label: str = "",
    setting: str = "",
    trajectory: str = "",
) -> dict[str, Any]:
    """
    Author a unique silhouette recipe for one layer.

    Same (kind, seed, prompt, label, setting, trajectory) → same form.
    Different seeds or prompts → different geometry.
    """
    rng = random.Random(int(seed) % (2**31))
    kind = str(kind or "circle").lower().strip()
    text = f"{prompt} {label} {setting}".lower()
    traj = str(trajectory or "").lower()
    face = -1.0 if traj in ("left", "away") else 1.0
    form: dict[str, Any] = {
        "kind": kind,
        "seed": int(seed),
        "face": face,
        "species": kind,
        "color_dr": rng.randint(-22, 22),
        "color_dg": rng.randint(-22, 22),
        "color_db": rng.randint(-22, 22),
    }
    if kind == "fish":
        form.update(_fish_form(rng, text, face))
    elif kind == "tree":
        form.update(_tree_form(rng, text, setting))
    elif kind == "cloud":
        form.update(_cloud_form(rng))
    elif kind == "building":
        form.update(_building_form(rng, text, setting))
    elif kind == "wave":
        form.update(_wave_form(rng))
    elif kind == "character":
        form.update(_character_form(rng, text))
    elif kind == "bird":
        form.update(_bird_form(rng, text, face))
    elif kind == "star":
        form.update(_star_form(rng, text))
    elif kind == "vehicle":
        form.update(_vehicle_form(rng, text, face))
    elif kind == "composed":
        form.update(_composed_form(rng, text, label))
    else:
        form["radius_mul"] = rng.uniform(0.78, 1.22)
        form["aspect"] = rng.uniform(0.82, 1.18)
    return form


def fish_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> np.ndarray:
    """Connected fish silhouette in local (already rotated) coordinates."""
    r = max(1e-6, float(radius))
    face = float(form.get("face", 1.0))
    if face >= 0:
        face = 1.0
    else:
        face = -1.0
    # +x in fish space is the facing direction
    lx = (xx - cx) * face
    ly = yy - cy

    body_rx = r * float(form.get("body_rx", 0.78))
    body_ry = r * float(form.get("body_ry", 0.38))
    snout_rx = r * float(form.get("snout_rx", 0.28))
    snout_ry = r * float(form.get("snout_ry", 0.22))
    body = _soft_ellipse_local(lx, ly, r * 0.02, 0.0, body_rx, body_ry, soft=0.022)
    snout = _soft_ellipse_local(lx, ly, body_rx * 0.72, 0.0, snout_rx, snout_ry, soft=0.018)

    tail_x = -body_rx * float(form.get("tail_offset", 0.92))
    lobe_rx = r * float(form.get("tail_rx", 0.28))
    lobe_ry = r * float(form.get("tail_ry", 0.22))
    spread = r * float(form.get("tail_spread", 0.28))
    tail_u = _soft_ellipse_local(lx, ly, tail_x, -spread, lobe_rx, lobe_ry, soft=0.02)
    tail_d = _soft_ellipse_local(lx, ly, tail_x, spread, lobe_rx, lobe_ry, soft=0.02)
    # Peduncle connecting tail to body so rotation never leaves a gap
    neck = _soft_ellipse_local(lx, ly, -body_rx * 0.72, 0.0, r * 0.22, body_ry * 0.55, soft=0.018)

    dorsal = _soft_ellipse_local(
        lx, ly,
        r * float(form.get("dorsal_x", -0.05)),
        -body_ry * float(form.get("dorsal_y", 1.15)),
        r * float(form.get("dorsal_rx", 0.22)),
        r * float(form.get("dorsal_ry", 0.18)),
        soft=0.016,
    )
    pectoral = _soft_ellipse_local(
        lx, ly,
        r * float(form.get("pectoral_x", 0.05)),
        body_ry * 0.85,
        r * float(form.get("pectoral_rx", 0.18)),
        r * float(form.get("pectoral_ry", 0.10)),
        soft=0.014,
    )
    return union_masks(body, snout, tail_u, tail_d, neck, dorsal, pectoral, k=0.022)


def fish_eye(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> tuple[np.ndarray, float, float]:
    """Eye disk + its center (for shading)."""
    r = max(1e-6, float(radius))
    face = 1.0 if float(form.get("face", 1.0)) >= 0 else -1.0
    ex = cx + face * r * float(form.get("eye_x", 0.42))
    ey = cy - r * float(form.get("eye_y", 0.08))
    er = r * float(form.get("eye_r", 0.09))
    return _soft_disk(xx, yy, ex, ey, er, soft=0.008), ex, ey


def tree_parts(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> dict[str, np.ndarray]:
    """Trunk, canopy, branches, and leaf speckles unique to this form."""
    r = max(1e-6, float(radius))
    species = str(form.get("species") or "oak")
    trunk_top = cy - r * float(form.get("trunk_top", 0.15))
    trunk_bot = cy + r * float(form.get("trunk_bot", 0.85))
    trunk = _tapered_trunk(
        xx, yy, cx, trunk_top, trunk_bot,
        r * float(form.get("trunk_w_top", 0.07)),
        r * float(form.get("trunk_w_bot", 0.14)),
        soft=0.012,
    )
    branches = np.zeros_like(xx, dtype=np.float32)
    for br in form.get("branches") or []:
        if not isinstance(br, dict):
            continue
        branches = union_masks(
            branches,
            _soft_segment(
                xx, yy,
                cx + r * float(br.get("x0", 0.0)),
                cy + r * float(br.get("y0", 0.05)),
                cx + r * float(br.get("x1", 0.25)),
                cy + r * float(br.get("y1", -0.25)),
                r * float(br.get("w", 0.035)),
            ),
            k=0.016,
        )

    canopy = np.zeros_like(xx, dtype=np.float32)
    if species == "pine":
        apex_y = cy - r * float(form.get("pine_apex", 1.05))
        height = r * float(form.get("pine_h", 1.35))
        layers = max(3, min(6, int(form.get("pine_layers", 4))))
        for i in range(layers):
            u = i / max(1, layers - 1)
            layer_apex = apex_y + height * (0.08 + 0.18 * u)
            layer_h = height * float(form.get("pine_layer_h", 0.42)) * (1.0 - 0.12 * u)
            base = r * (0.38 + 0.42 * u) * float(form.get("pine_flare", 1.0))
            canopy = union_masks(
                canopy,
                _soft_cone(xx, yy, cx, layer_apex, layer_h, base, soft=0.02),
                k=0.022,
            )
    elif species == "palm":
        crown_y = cy - r * 0.55
        for fr in form.get("fronds") or []:
            if not isinstance(fr, dict):
                continue
            canopy = union_masks(
                canopy,
                _soft_ellipse(
                    xx, yy,
                    cx + r * float(fr.get("dx", 0.0)),
                    crown_y + r * float(fr.get("dy", 0.0)),
                    r * float(fr.get("rx", 0.55)),
                    r * float(fr.get("ry", 0.12)),
                    soft=0.02,
                ),
                k=0.02,
            )
        canopy = union_masks(canopy, _soft_disk(xx, yy, cx, crown_y, r * 0.18, soft=0.02), k=0.02)
    else:
        for blob in form.get("blobs") or []:
            if not isinstance(blob, dict):
                continue
            blob_m = _soft_disk(
                xx, yy,
                cx + r * float(blob.get("dx", 0.0)),
                cy + r * float(blob.get("dy", -0.35)),
                r * float(blob.get("s", 0.45)),
                soft=0.03,
            )
            canopy = blob_m if float(np.max(canopy)) < 0.05 else union_masks(canopy, blob_m, k=0.03)
        if float(np.max(canopy)) < 0.05:
            canopy = _soft_disk(xx, yy, cx, cy - r * 0.35, r * 0.7, soft=0.04)

    seed = int(form.get("seed") or 0)
    noise = _hash_noise(xx, yy, seed, scale=float(form.get("leaf_scale", 42.0)))
    leaves = ((noise > float(form.get("leaf_thresh", 0.58))).astype(np.float32) * canopy)
    return {
        "trunk": np.clip(trunk, 0, 1),
        "branches": np.clip(branches, 0, 1),
        "canopy": np.clip(canopy, 0, 1),
        "leaves": np.clip(leaves, 0, 1),
    }


def cloud_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> np.ndarray:
    r = max(1e-6, float(radius))
    mask = np.zeros_like(xx, dtype=np.float32)
    blobs = form.get("blobs") or [
        {"dx": -0.45, "dy": 0.0, "s": 0.55},
        {"dx": 0.0, "dy": -0.15, "s": 0.65},
        {"dx": 0.4, "dy": 0.0, "s": 0.5},
    ]
    for blob in blobs:
        if not isinstance(blob, dict):
            continue
        mask = np.maximum(
            mask,
            _soft_disk(
                xx, yy,
                cx + r * float(blob.get("dx", 0.0)),
                cy + r * float(blob.get("dy", 0.0)),
                r * float(blob.get("s", 0.5)),
                soft=0.05,
            ),
        )
    return np.clip(mask, 0, 1)


def bird_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> np.ndarray:
    r = max(1e-6, float(radius))
    face = 1.0 if float(form.get("face", 1.0)) >= 0 else -1.0
    lx = (xx - cx) * face
    ly = yy - cy
    body = _soft_ellipse_local(lx, ly, 0.0, 0.0, r * float(form.get("body_rx", 0.5)), r * float(form.get("body_ry", 0.28)), soft=0.02)
    head = _soft_ellipse_local(lx, ly, r * 0.42, -r * 0.12, r * float(form.get("head_s", 0.26)), r * float(form.get("head_s", 0.26)) * 0.9, soft=0.016)
    beak = _soft_ellipse_local(lx, ly, r * 0.68, -r * 0.10, r * float(form.get("beak_rx", 0.14)), r * 0.06, soft=0.012)
    lift = r * float(form.get("wing_lift", 0.55))
    wing_u = _soft_ellipse_local(lx, ly, -r * 0.05, -lift, r * float(form.get("wing_rx", 0.5)), r * float(form.get("wing_ry", 0.14)), soft=0.018)
    wing_d = _soft_ellipse_local(lx, ly, -r * 0.02, lift * 0.45, r * float(form.get("wing_rx", 0.5)) * 0.7, r * float(form.get("wing_ry", 0.14)) * 0.7, soft=0.016)
    tail = _soft_ellipse_local(lx, ly, -r * float(form.get("body_rx", 0.5)) * 1.15, 0.0, r * float(form.get("tail_rx", 0.24)), r * float(form.get("tail_ry", 0.12)), soft=0.016)
    return union_masks(body, head, beak, wing_u, wing_d, tail, k=0.02)


def star_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> np.ndarray:
    import math
    r = max(1e-6, float(radius))
    n = max(5, min(8, int(form.get("points", 5))))
    inner = r * float(form.get("inner", 0.3))
    outer = r * float(form.get("outer", 0.9))
    phase = float(form.get("phase", 0.0))
    mask = _soft_disk(xx, yy, cx, cy, r * float(form.get("core", 0.22)), soft=0.02)
    for i in range(n):
        ang = phase + (2.0 * math.pi * i) / n
        px = cx + math.cos(ang) * outer * 0.55
        py = cy + math.sin(ang) * outer * 0.55
        spike = _soft_ellipse(xx, yy, px, py, inner * 0.55, outer * 0.42, soft=0.02)
        mask = union_masks(mask, spike, k=0.018)
    return np.clip(mask, 0, 1)


def vehicle_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> np.ndarray:
    r = max(1e-6, float(radius))
    face = 1.0 if float(form.get("face", 1.0)) >= 0 else -1.0
    bw = r * float(form.get("body_w", 0.9))
    bh = r * float(form.get("body_h", 0.28))
    body = _soft_box(xx, yy, cx, cy + r * 0.06, bw, bh, soft=0.02)
    cabin = _soft_box(
        xx, yy,
        cx + face * r * 0.08,
        cy - r * 0.18,
        r * float(form.get("cabin_w", 0.4)),
        r * float(form.get("cabin_h", 0.28)),
        soft=0.018,
    )
    span = r * float(form.get("wheel_span", 0.45))
    ws = r * float(form.get("wheel_s", 0.18))
    wheel_y = cy + bh + ws * 0.35
    w1 = _soft_disk(xx, yy, cx - face * span, wheel_y, ws, soft=0.016)
    w2 = _soft_disk(xx, yy, cx + face * span * 0.85, wheel_y, ws, soft=0.016)
    return union_masks(body, cabin, w1, w2, k=0.018)


def composed_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> np.ndarray:
    r = max(1e-6, float(radius))
    core = _soft_ellipse(
        xx, yy, cx, cy,
        r * float(form.get("core_rx", 0.42)),
        r * float(form.get("core_ry", 0.32)),
        soft=0.022,
    )
    parts = [core]
    for blob in form.get("blobs") or []:
        if not isinstance(blob, dict):
            continue
        parts.append(_soft_ellipse(
            xx, yy,
            cx + r * float(blob.get("dx", 0.0)),
            cy + r * float(blob.get("dy", 0.0)),
            r * float(blob.get("rx", 0.28)),
            r * float(blob.get("ry", 0.22)),
            soft=0.02,
        ))
    return union_masks(*parts, k=0.02) if parts else core


def building_parts(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
) -> dict[str, np.ndarray]:
    r = max(1e-6, float(radius))
    half_w = r * float(form.get("half_w", 0.55))
    half_h = r * float(form.get("half_h", 1.2))
    body = _soft_box(xx, yy, cx, cy, half_w, half_h, soft=0.022)
    cols = max(2, min(8, int(form.get("win_cols", 4))))
    rows = max(3, min(12, int(form.get("win_rows", 6))))
    wx = np.floor((xx - (cx - half_w)) / max(1e-6, (2 * half_w) / cols))
    wy = np.floor((yy - (cy - half_h)) / max(1e-6, (2 * half_h) / rows))
    pad_x = half_w * float(form.get("win_pad", 0.78))
    pad_y = half_h * 0.82
    inset = (
        (np.abs(xx - cx) < pad_x)
        & (np.abs(yy - cy) < pad_y)
        & (yy > cy - half_h * 0.9)
    )
    windows = (
        inset
        & (np.mod(wx, 2) == 0)
        & (np.mod(wy, 2) == int(form.get("win_row_parity", 0)))
    ).astype(np.float32)
    roof = np.zeros_like(xx, dtype=np.float32)
    roof_kind = str(form.get("roof") or "flat")
    if roof_kind == "peak":
        roof = _soft_cone(
            xx, yy,
            cx, cy - half_h - r * 0.35,
            r * 0.42,
            half_w * 1.05,
            soft=0.02,
        )
    elif roof_kind == "cap":
        roof = _soft_box(xx, yy, cx, cy - half_h, half_w * 1.08, r * 0.08, soft=0.015)
    return {
        "body": np.clip(np.maximum(body, roof), 0, 1),
        "windows": np.clip(windows, 0, 1),
        "roof": np.clip(roof, 0, 1),
    }


def wave_mask(
    xx: np.ndarray,
    yy: np.ndarray,
    cx: float,
    cy: float,
    radius: float,
    form: dict[str, Any],
    t: float,
) -> np.ndarray:
    r = max(1e-6, float(radius))
    freq = float(form.get("freq", 18.0))
    amp = float(form.get("amp", 0.03))
    speed = float(form.get("speed", 3.0))
    phase = float(form.get("phase", 0.0))
    band = np.abs(yy - (cy + amp * np.sin(xx * freq + t * speed + phase))) < r * float(form.get("thick", 0.35))
    fade = np.clip(1.0 - np.abs(xx - cx) / max(1e-6, r * 2.2), 0, 1)
    crest = (
        np.abs(yy - (cy - r * 0.12 + amp * 0.6 * np.sin(xx * freq * 1.4 + t * speed + phase)))
        < r * 0.08
    ).astype(np.float32) * fade * 0.55
    return np.clip(band.astype(np.float32) * fade + crest, 0, 1)


# --- form recipes -----------------------------------------------------------

def _fish_form(rng: random.Random, text: str, face: float) -> dict[str, Any]:
    if any(w in text for w in ("shark", "pike", "barracuda")):
        species = "shark"
        body_ry, tail_spread = 0.28, 0.22
    elif any(w in text for w in ("goldfish", "koi", "carp", "clown")):
        species = "goldfish"
        body_ry, tail_spread = 0.48, 0.38
    elif "tuna" in text or "mackerel" in text:
        species = "tuna"
        body_ry, tail_spread = 0.32, 0.24
    else:
        species = rng.choice(("dart", "round", "reef"))
        body_ry = rng.uniform(0.30, 0.46)
        tail_spread = rng.uniform(0.20, 0.36)
    return {
        "species": species,
        "face": face,
        "body_rx": rng.uniform(0.70, 0.88),
        "body_ry": body_ry,
        "snout_rx": rng.uniform(0.22, 0.34),
        "snout_ry": rng.uniform(0.16, 0.26),
        "tail_offset": rng.uniform(0.82, 1.02),
        "tail_rx": rng.uniform(0.22, 0.34),
        "tail_ry": rng.uniform(0.16, 0.26),
        "tail_spread": tail_spread,
        "dorsal_x": rng.uniform(-0.18, 0.08),
        "dorsal_y": rng.uniform(1.02, 1.28),
        "dorsal_rx": rng.uniform(0.16, 0.28),
        "dorsal_ry": rng.uniform(0.12, 0.22),
        "pectoral_x": rng.uniform(-0.05, 0.18),
        "pectoral_rx": rng.uniform(0.12, 0.22),
        "pectoral_ry": rng.uniform(0.07, 0.13),
        "eye_x": rng.uniform(0.34, 0.50),
        "eye_y": rng.uniform(0.04, 0.14),
        "eye_r": rng.uniform(0.07, 0.11),
        "start_x": rng.uniform(0.12, 0.38),
        "end_x": rng.uniform(0.62, 0.88),
        "jump_peak": rng.uniform(0.22, 0.42),
        "water_y": rng.uniform(0.64, 0.78),
    }


def _tree_form(rng: random.Random, text: str, setting: str) -> dict[str, Any]:
    if any(w in text for w in ("pine", "fir", "spruce", "evergreen", "conifer", "cedar")):
        species = "pine"
    elif any(w in text for w in ("palm", "coconut")):
        species = "palm"
    elif any(w in text for w in ("oak", "maple", "elm", "birch", "willow", "deciduous")):
        species = "oak"
    elif (setting or "").lower() in ("snow", "mountain"):
        species = rng.choice(("pine", "pine", "oak"))
    elif (setting or "").lower() in ("beach", "desert"):
        species = rng.choice(("palm", "round"))
    else:
        species = rng.choice(("oak", "oak", "pine", "round"))
    n_blobs = rng.randint(5, 9)
    blobs = []
    for _ in range(n_blobs):
        blobs.append({
            "dx": rng.uniform(-0.42, 0.42),
            "dy": rng.uniform(-0.72, -0.08),
            "s": rng.uniform(0.28, 0.58),
        })
    n_br = rng.randint(2, 5)
    branches = []
    for _ in range(n_br):
        side = rng.choice((-1.0, 1.0))
        branches.append({
            "x0": rng.uniform(-0.04, 0.04),
            "y0": rng.uniform(-0.05, 0.25),
            "x1": side * rng.uniform(0.18, 0.48),
            "y1": rng.uniform(-0.45, -0.08),
            "w": rng.uniform(0.022, 0.045),
        })
    fronds = []
    for i in range(rng.randint(5, 8)):
        ang = (-0.9 + 1.8 * i / 7.0) + rng.uniform(-0.12, 0.12)
        fronds.append({
            "dx": 0.55 * np.sin(ang) + rng.uniform(-0.05, 0.05),
            "dy": -0.15 + 0.35 * abs(np.cos(ang)),
            "rx": rng.uniform(0.42, 0.62),
            "ry": rng.uniform(0.08, 0.14),
        })
    return {
        "species": species,
        "blobs": blobs,
        "branches": branches,
        "fronds": fronds,
        "trunk_top": rng.uniform(0.05, 0.22),
        "trunk_bot": rng.uniform(0.72, 0.95),
        "trunk_w_top": rng.uniform(0.045, 0.09),
        "trunk_w_bot": rng.uniform(0.10, 0.18),
        "pine_apex": rng.uniform(0.92, 1.18),
        "pine_h": rng.uniform(1.15, 1.45),
        "pine_layers": rng.randint(3, 6),
        "pine_layer_h": rng.uniform(0.36, 0.48),
        "pine_flare": rng.uniform(0.85, 1.15),
        "leaf_scale": rng.uniform(34.0, 56.0),
        "leaf_thresh": rng.uniform(0.50, 0.66),
    }


def _cloud_form(rng: random.Random) -> dict[str, Any]:
    n = rng.randint(4, 8)
    blobs = []
    for _ in range(n):
        blobs.append({
            "dx": rng.uniform(-0.7, 0.7),
            "dy": rng.uniform(-0.28, 0.18),
            "s": rng.uniform(0.32, 0.68),
        })
    return {"species": "cloud", "blobs": blobs}


def _building_form(rng: random.Random, text: str, setting: str) -> dict[str, Any]:
    tall = any(w in text for w in ("tower", "skyscraper", "highrise")) or (setting or "").lower() in ("city", "neon")
    return {
        "species": "tower" if tall else rng.choice(("block", "house", "tower")),
        "half_w": rng.uniform(0.38, 0.62) * (0.75 if tall else 1.0),
        "half_h": rng.uniform(1.05, 1.55) * (1.2 if tall else 1.0),
        "win_cols": rng.randint(3, 7),
        "win_rows": rng.randint(4, 10),
        "win_pad": rng.uniform(0.70, 0.86),
        "win_row_parity": rng.randint(0, 1),
        "roof": rng.choice(("flat", "peak", "cap")),
        "win_warmth": rng.uniform(0.7, 1.15),
    }


def _wave_form(rng: random.Random) -> dict[str, Any]:
    return {
        "species": "wave",
        "freq": rng.uniform(11.0, 26.0),
        "amp": rng.uniform(0.018, 0.048),
        "speed": rng.uniform(2.0, 4.4),
        "phase": rng.uniform(0.0, 6.28),
        "thick": rng.uniform(0.26, 0.42),
    }


def _bird_form(rng: random.Random, text: str, face: float) -> dict[str, Any]:
    small = any(w in text for w in ("sparrow", "finch", "wren", "small"))
    return {
        "species": "sparrow" if small else rng.choice(("gull", "crow", "swift", "heron")),
        "face": face,
        "body_rx": rng.uniform(0.42, 0.62) * (0.85 if small else 1.0),
        "body_ry": rng.uniform(0.22, 0.34),
        "wing_rx": rng.uniform(0.38, 0.62),
        "wing_ry": rng.uniform(0.10, 0.18),
        "wing_lift": rng.uniform(0.35, 0.85),
        "tail_rx": rng.uniform(0.18, 0.32),
        "tail_ry": rng.uniform(0.08, 0.16),
        "beak_rx": rng.uniform(0.10, 0.18),
        "head_s": rng.uniform(0.22, 0.32),
    }


def _star_form(rng: random.Random, text: str) -> dict[str, Any]:
    n = 5 if "star" in text else rng.choice((5, 6, 7))
    return {
        "species": f"{n}-point",
        "points": n,
        "inner": rng.uniform(0.22, 0.38),
        "outer": rng.uniform(0.72, 1.05),
        "phase": rng.uniform(0.0, 1.2),
        "core": rng.uniform(0.16, 0.28),
    }


def _vehicle_form(rng: random.Random, text: str, face: float) -> dict[str, Any]:
    bike = any(w in text for w in ("bike", "bicycle", "cycle", "motorcycle"))
    return {
        "species": "bike" if bike else rng.choice(("car", "van", "bus")),
        "face": face,
        "body_w": rng.uniform(0.72, 1.05) if not bike else rng.uniform(0.55, 0.75),
        "body_h": rng.uniform(0.22, 0.38) if not bike else rng.uniform(0.12, 0.18),
        "cabin_w": rng.uniform(0.32, 0.48),
        "cabin_h": rng.uniform(0.22, 0.38),
        "wheel_s": rng.uniform(0.14, 0.22) if not bike else rng.uniform(0.18, 0.26),
        "wheel_span": rng.uniform(0.38, 0.55),
        "bike": bike,
    }


def _composed_form(rng: random.Random, text: str, label: str) -> dict[str, Any]:
    """Unique blob-stack silhouette keyed by the noun, not a shared template."""
    n = 3 + (sum(ord(c) for c in (label or text or "obj")) % 4)
    blobs: list[dict[str, float]] = []
    for _i in range(n):
        blobs.append({
            "dx": rng.uniform(-0.55, 0.55),
            "dy": rng.uniform(-0.50, 0.50),
            "rx": rng.uniform(0.18, 0.48),
            "ry": rng.uniform(0.14, 0.40),
        })
    return {
        "species": (label or "object").strip().lower()[:40] or "object",
        "blobs": blobs,
        "core_rx": rng.uniform(0.32, 0.55),
        "core_ry": rng.uniform(0.22, 0.42),
    }


def _character_form(rng: random.Random, text: str) -> dict[str, Any]:
    child = any(w in text for w in ("child", "kid", "small"))
    tall = any(w in text for w in ("tall", "giant"))
    return {
        "species": "child" if child else ("tall" if tall else rng.choice(("stocky", "lean", "average"))),
        "head_scale": rng.uniform(0.38, 0.52) * (1.15 if child else 1.0),
        "body_scale": rng.uniform(0.62, 0.82),
        "body_width": rng.uniform(0.42, 0.68) * (0.85 if "lean" in text else 1.0),
        "limb_len": rng.uniform(0.46, 0.68) * (1.12 if tall else 1.0),
        "arm_len": rng.uniform(0.34, 0.50),
        "leg_dx": rng.uniform(0.14, 0.22),
    }


# --- SDF primitives (single source for renderer + forms) -------------------

def _soft_disk(xx, yy, cx, cy, radius, soft=0.03):
    dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    band = max(1e-5, float(soft))
    return np.clip((float(radius) + band - dist) / band, 0.0, 1.0)


def _soft_box(xx, yy, cx, cy, half_w, half_h, soft=0.025):
    dx = np.abs(xx - cx) / max(1e-6, float(half_w))
    dy = np.abs(yy - cy) / max(1e-6, float(half_h))
    m = np.maximum(dx, dy)
    band = max(1e-5, float(soft) / max(min(half_w, half_h), 1e-6))
    return np.clip((1.0 + band - m) / band, 0.0, 1.0)


def _soft_ellipse(xx, yy, cx, cy, rx, ry, soft=0.03):
    nx = (xx - cx) / max(1e-6, float(rx))
    ny = (yy - cy) / max(1e-6, float(ry))
    dist = np.sqrt(nx * nx + ny * ny)
    band = max(1e-5, float(soft) / max(min(rx, ry), 1e-6))
    return np.clip((1.0 + band - dist) / band, 0.0, 1.0)


def _soft_ellipse_local(lx, ly, ox, oy, rx, ry, soft=0.03):
    nx = (lx - ox) / max(1e-6, float(rx))
    ny = (ly - oy) / max(1e-6, float(ry))
    dist = np.sqrt(nx * nx + ny * ny)
    band = max(1e-5, float(soft) / max(min(rx, ry), 1e-6))
    return np.clip((1.0 + band - dist) / band, 0.0, 1.0)


def smooth_max(a: np.ndarray, b: np.ndarray, k: float = 0.028) -> np.ndarray:
    """Polynomial smooth-max so silhouettes join without a hard crease or gap."""
    kk = max(1e-6, float(k))
    h = np.clip(0.5 + 0.5 * (a - b) / kk, 0.0, 1.0)
    return a * h + b * (1.0 - h) + kk * h * (1.0 - h)


def union_masks(*masks: np.ndarray, k: float = 0.028) -> np.ndarray:
    acc = masks[0]
    for m in masks[1:]:
        acc = smooth_max(acc, m, k)
    return np.clip(acc, 0.0, 1.0)


def rotate_into_local(xx, yy, cx: float, cy: float, rot: float):
    """
    Inverse-rotate world samples into object space.

    Authored keyframe rot is the object's heading; sampling must use R(-rot)
    or the silhouette shears against the motion.
    """
    c = float(np.cos(rot))
    s = float(np.sin(rot))
    dx = xx - cx
    dy = yy - cy
    return cx + dx * c + dy * s, cy - dx * s + dy * c


def _tapered_trunk(xx, yy, cx, y_top, y_bot, w_top, w_bot, soft=0.012):
    span = max(1e-6, float(y_bot) - float(y_top))
    t = np.clip((yy - y_top) / span, 0.0, 1.0)
    half_w = float(w_top) + (float(w_bot) - float(w_top)) * t
    dx = np.abs(xx - cx) / np.maximum(half_w, 1e-6)
    in_y = ((yy >= y_top) & (yy <= y_bot)).astype(np.float32)
    band = max(1e-5, float(soft) / max(float(w_bot), 1e-6))
    return np.clip((1.0 + band - dx) / band, 0, 1) * in_y


def _soft_cone(xx, yy, apex_x, apex_y, height, base_half, soft=0.02):
    t = (yy - apex_y) / max(1e-6, float(height))
    valid = ((t > 0.0) & (t < 1.0)).astype(np.float32)
    half = float(base_half) * np.clip(t, 0.08, 1.0)
    dx = np.abs(xx - apex_x) / np.maximum(half, 1e-6)
    band = max(1e-5, float(soft) / max(float(base_half), 1e-6))
    return np.clip((1.0 + band - dx) / band, 0, 1) * valid


def _soft_segment(xx, yy, x0, y0, x1, y1, thickness):
    vx = float(x1) - float(x0)
    vy = float(y1) - float(y0)
    len2 = vx * vx + vy * vy + 1e-8
    t = np.clip(((xx - x0) * vx + (yy - y0) * vy) / len2, 0.0, 1.0)
    px = x0 + t * vx
    py = y0 + t * vy
    dist = np.sqrt((xx - px) ** 2 + (yy - py) ** 2)
    thick = max(1e-6, float(thickness))
    band = thick * 0.45
    return np.clip((thick + band - dist) / band, 0, 1)


def _hash_noise(xx, yy, seed: int, scale: float = 42.0) -> np.ndarray:
    """Integer hash 0–1 (stable per cell). Sin-hash banding distorts leaf detail."""
    gx = np.floor(xx * scale).astype(np.int64)
    gy = np.floor(yy * scale).astype(np.int64)
    n = (
        gx * np.int64(374761393)
        + gy * np.int64(668265263)
        + np.int64(int(seed) & 0x7FFFFFFF) * np.int64(1274126177)
    ) & np.int64(0x7FFFFFFF)
    n = n ^ (n >> np.int64(13))
    n = (n * np.int64(1274126177)) & np.int64(0x7FFFFFFF)
    return n.astype(np.float32) / np.float32(0x7FFFFFFF)


def layer_form(layer: dict[str, Any], kind: str) -> dict[str, Any]:
    """Read form from a layer dict, or author a fallback so tests still render."""
    form = layer.get("form") if isinstance(layer, dict) else None
    if isinstance(form, dict) and form.get("kind"):
        return form
    lid = str((layer or {}).get("id") or kind)
    return create_form(kind, seed=form_seed("", lid), label=str(kind))
