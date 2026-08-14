"""
Cel cartoon kit — starting visual grammar for the cartoon loop.

Uses Pillow ImageDraw (already in the stack) as the 2D drawing library:
hard ink outlines, flat fills, readable modern-day rooms. This path does not
use the soft-blob character / horizon-band renderer.

Unique per clip via registry colors + seed (hair, clothes, room offsets).
"""
from __future__ import annotations

import random
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


INK = (28, 22, 30)


def _as_rgb(c: Any, fallback: tuple[int, int, int] = (210, 90, 100)) -> tuple[int, int, int]:
    if isinstance(c, (tuple, list)) and len(c) >= 3:
        return (int(c[0]), int(c[1]), int(c[2]))
    return fallback


def _mix(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] * (1.0 - t) + b[i] * t) for i in range(3))  # type: ignore[return-value]


def _shade(c: tuple[int, int, int], f: float) -> tuple[int, int, int]:
    return tuple(int(max(0, min(255, v * f))) for v in c)  # type: ignore[return-value]


def _palette(spec: Any) -> list[tuple[int, int, int]]:
    raw = getattr(spec, "palette_colors", None) or []
    out = [_as_rgb(c) for c in raw if c is not None]
    if len(out) < 2:
        out.extend([(236, 196, 92), (72, 148, 168), (232, 118, 96)])
    return out


def _stroke(width: int) -> int:
    return max(3, width // 140)


def _ink_ellipse(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill, stroke: int) -> None:
    x0, y0, x1, y1 = box
    s = stroke
    draw.ellipse((x0 - s, y0 - s, x1 + s, y1 + s), fill=INK)
    draw.ellipse(box, fill=fill)


def _ink_round(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], radius: int, fill, stroke: int) -> None:
    x0, y0, x1, y1 = box
    s = stroke
    draw.rounded_rectangle((x0 - s, y0 - s, x1 + s, y1 + s), radius=radius + s, fill=INK)
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def _ink_rect(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill, stroke: int) -> None:
    x0, y0, x1, y1 = box
    s = stroke
    draw.rectangle((x0 - s, y0 - s, x1 + s, y1 + s), fill=INK)
    draw.rectangle(box, fill=fill)


def _ink_poly(draw: ImageDraw.ImageDraw, pts: list[tuple[int, int]], fill, stroke: int) -> None:
    if len(pts) < 3:
        return
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    cx = sum(xs) / len(pts)
    cy = sum(ys) / len(pts)
    outer = []
    for x, y in pts:
        dx, dy = x - cx, y - cy
        n = (dx * dx + dy * dy) ** 0.5 or 1.0
        outer.append((int(x + dx / n * stroke), int(y + dy / n * stroke)))
    draw.polygon(outer, fill=INK)
    draw.polygon(pts, fill=fill)


def _window(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], glass, stroke: int) -> None:
    x0, y0, x1, y1 = box
    _ink_round(draw, box, max(4, (x1 - x0) // 10), glass, stroke)
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    draw.line((mx, y0 + stroke, mx, y1 - stroke), fill=INK, width=max(2, stroke - 1))
    draw.line((x0 + stroke, my, x1 - stroke, my), fill=INK, width=max(2, stroke - 1))


def _draw_room(
    draw: ImageDraw.ImageDraw,
    w: int,
    h: int,
    setting: str,
    colors: list[tuple[int, int, int]],
    rng: random.Random,
    stroke: int,
) -> int:
    """Paint a modern-day cartoon interior/street. Returns floor y in pixels."""
    wall = _mix(colors[1 % len(colors)], (232, 214, 196), 0.55)
    floor = _shade(_mix(colors[0], (140, 110, 90), 0.45), 0.72)
    accent = colors[0]
    sky = _mix(colors[-1], (164, 206, 232), 0.7)
    floor_y = int(h * (0.70 + rng.uniform(-0.03, 0.03)))
    s = setting.strip().lower() or "apartment"

    if s in ("street", "park", "subway"):
        if s == "park":
            draw.rectangle((0, 0, w, floor_y), fill=_mix(sky, (186, 220, 164), 0.25))
            draw.rectangle((0, floor_y, w, h), fill=_mix((92, 156, 86), accent, 0.2))
            draw.line((0, floor_y, w, floor_y), fill=INK, width=stroke)
            path = [(int(w * 0.38), h), (int(w * 0.48), floor_y), (int(w * 0.58), floor_y), (int(w * 0.72), h)]
            _ink_poly(draw, path, _mix((196, 176, 128), floor, 0.4), stroke)
            tx = int(w * 0.16)
            _ink_rect(draw, (tx, int(h * 0.42), tx + int(w * 0.05), floor_y), (118, 78, 48), stroke)
            _ink_ellipse(draw, (tx - int(w * 0.08), int(h * 0.18), tx + int(w * 0.14), int(h * 0.48)), (62, 140, 78), stroke)
            bx0, by0 = int(w * 0.72), int(h * 0.58)
            _ink_round(draw, (bx0, by0, bx0 + int(w * 0.2), floor_y - stroke), 8, _shade(accent, 0.85), stroke)
        elif s == "subway":
            draw.rectangle((0, 0, w, h), fill=_shade(wall, 0.55))
            draw.rectangle((0, floor_y, w, h), fill=(48, 48, 52))
            draw.line((0, floor_y, w, floor_y), fill=INK, width=stroke)
            stripe_y = int(h * 0.22)
            _ink_rect(draw, (0, stripe_y, w, stripe_y + int(h * 0.045)), (236, 196, 48), stroke)
            _window(draw, (int(w * 0.08), int(h * 0.28), int(w * 0.42), int(h * 0.52)), (40, 70, 110), stroke)
            seat_y = int(h * 0.52)
            _ink_round(draw, (int(w * 0.06), seat_y, int(w * 0.94), floor_y), 10, (92, 108, 168), stroke)
            pole_x = int(w * 0.78)
            _ink_rect(draw, (pole_x, int(h * 0.08), pole_x + stroke * 2, floor_y), (200, 200, 208), stroke)
        else:
            draw.rectangle((0, 0, w, floor_y), fill=_mix(sky, (176, 196, 216), 0.4))
            draw.rectangle((0, floor_y, w, h), fill=(92, 92, 98))
            draw.line((0, floor_y, w, floor_y), fill=INK, width=stroke)
            curb = int(h * 0.82)
            draw.rectangle((0, floor_y, w, curb), fill=(168, 168, 172))
            draw.line((0, curb, w, curb), fill=INK, width=max(2, stroke - 1))
            b1 = int(w * 0.04)
            _ink_rect(draw, (b1, int(h * 0.12), int(w * 0.34), floor_y), _mix(wall, (180, 160, 170), 0.3), stroke)
            _window(draw, (int(w * 0.10), int(h * 0.22), int(w * 0.22), int(h * 0.38)), sky, stroke)
            _window(draw, (int(w * 0.10), int(h * 0.44), int(w * 0.22), int(h * 0.58)), sky, stroke)
            _ink_rect(draw, (int(w * 0.62), int(h * 0.08), int(w * 0.96), floor_y), _mix(accent, (120, 140, 170), 0.45), stroke)
            _window(draw, (int(w * 0.70), int(h * 0.18), int(w * 0.88), int(h * 0.40)), sky, stroke)
        return floor_y

    # Interiors: wall + floor + window + furniture
    draw.rectangle((0, 0, w, floor_y), fill=wall)
    draw.rectangle((0, floor_y, w, h), fill=floor)
    draw.line((0, floor_y, w, floor_y), fill=INK, width=stroke)
    base = int(h * 0.08)
    draw.rectangle((0, 0, w, base), fill=_shade(wall, 0.88))
    draw.line((0, base, w, base), fill=INK, width=max(2, stroke - 1))
    _window(draw, (int(w * 0.08), int(h * 0.14), int(w * 0.34), int(h * 0.42)), sky, stroke)

    if s == "kitchen":
        counter_y = int(h * 0.58)
        _ink_rect(draw, (int(w * 0.02), counter_y, int(w * 0.62), floor_y), _mix(floor, (196, 150, 110), 0.35), stroke)
        _ink_rect(draw, (int(w * 0.02), counter_y - int(h * 0.04), int(w * 0.62), counter_y), _shade(accent, 0.9), stroke)
        _ink_rect(draw, (int(w * 0.08), int(h * 0.16), int(w * 0.28), int(h * 0.30)), _shade(wall, 0.8), stroke)
        fridge_x = int(w * 0.72)
        _ink_round(draw, (fridge_x, int(h * 0.22), int(w * 0.96), floor_y), 10, (236, 238, 242), stroke)
        draw.line((fridge_x + stroke, int(h * 0.48), int(w * 0.96) - stroke, int(h * 0.48)), fill=INK, width=max(2, stroke - 1))
        hx = fridge_x + int(w * 0.03)
        _ink_ellipse(draw, (hx, int(h * 0.34), hx + stroke * 3, int(h * 0.40)), (200, 200, 208), stroke)
    elif s == "cafe":
        _ink_ellipse(draw, (int(w * 0.62), int(h * 0.08), int(w * 0.78), int(h * 0.16)), _shade(accent, 0.7), stroke)
        draw.line((int(w * 0.70), int(h * 0.16), int(w * 0.70), int(h * 0.48)), fill=INK, width=stroke)
        tx0, ty0 = int(w * 0.52), int(h * 0.52)
        _ink_round(draw, (tx0, ty0, tx0 + int(w * 0.36), ty0 + int(h * 0.08)), 12, _mix(accent, (160, 110, 80), 0.4), stroke)
        _ink_rect(draw, (int(w * 0.68), ty0 + int(h * 0.08), int(w * 0.72), floor_y), (120, 80, 56), stroke)
        _ink_round(draw, (int(w * 0.46), int(h * 0.50), int(w * 0.56), floor_y), 8, _shade(colors[1 % len(colors)], 0.85), stroke)
    elif s == "bedroom":
        _ink_round(draw, (int(w * 0.48), int(h * 0.46), int(w * 0.96), floor_y), 12, _mix(accent, (180, 150, 190), 0.4), stroke)
        _ink_rect(draw, (int(w * 0.52), int(h * 0.40), int(w * 0.92), int(h * 0.50)), (244, 236, 228), stroke)
        _ink_round(draw, (int(w * 0.38), int(h * 0.52), int(w * 0.50), int(h * 0.62)), 6, _shade(wall, 0.75), stroke)
    elif s == "office":
        desk_y = int(h * 0.58)
        _ink_rect(draw, (int(w * 0.48), desk_y, int(w * 0.96), desk_y + int(h * 0.06)), (168, 140, 110), stroke)
        _ink_rect(draw, (int(w * 0.70), desk_y + int(h * 0.06), int(w * 0.76), floor_y), (120, 96, 76), stroke)
        _ink_rect(draw, (int(w * 0.62), int(h * 0.34), int(w * 0.88), desk_y), (48, 52, 60), stroke)
        _ink_rect(draw, (int(w * 0.66), int(h * 0.38), int(w * 0.84), int(h * 0.52)), sky, max(2, stroke - 1))
    else:
        # apartment / interior default: sofa + TV
        _ink_round(draw, (int(w * 0.42), int(h * 0.52), int(w * 0.92), floor_y), 14, _mix(accent, (96, 120, 168), 0.35), stroke)
        _ink_rect(draw, (int(w * 0.08), int(h * 0.48), int(w * 0.30), int(h * 0.62)), (36, 36, 42), stroke)
        _ink_rect(draw, (int(w * 0.11), int(h * 0.51), int(w * 0.27), int(h * 0.59)), (80, 140, 180), max(2, stroke - 1))
    return floor_y


def _draw_character(
    draw: ImageDraw.ImageDraw,
    cx: int,
    floor_y: int,
    size: int,
    clothes: tuple[int, int, int],
    skin: tuple[int, int, int],
    hair: tuple[int, int, int],
    rng: random.Random,
    stroke: int,
    *,
    expression: str = "neutral",
    hold_phone: bool = False,
    smear: float = 0.0,
) -> None:
    """Modern-TV cartoon figure: big head, ink, hoodie/tee, planted on the floor."""
    stretch = 1.0 + 0.22 * max(0.0, smear)
    head_r = int(size * 0.22)
    body_w = int(size * 0.28 * stretch)
    body_h = int(size * 0.34)
    foot_y = floor_y - stroke
    hip_y = foot_y - int(size * 0.28)
    shoulder_y = hip_y - body_h + int(size * 0.04)
    head_cy = shoulder_y - head_r + int(size * 0.04)
    hair_style = rng.randrange(3)
    clothes_style = rng.randrange(2)

    # Far arm / legs first
    arm_w = int(size * 0.07)
    leg_w = int(size * 0.08)
    swing = int(size * 0.04 * smear)
    _ink_round(
        draw,
        (cx - body_w // 2 - arm_w, shoulder_y + int(size * 0.04), cx - body_w // 2 + arm_w // 2, hip_y + int(size * 0.06)),
        arm_w,
        skin,
        stroke,
    )
    _ink_round(
        draw,
        (cx - leg_w - int(size * 0.04) - swing, hip_y, cx - int(size * 0.01) - swing, foot_y),
        leg_w,
        _shade(clothes, 0.75),
        stroke,
    )
    _ink_round(
        draw,
        (cx + int(size * 0.01) + swing, hip_y, cx + leg_w + int(size * 0.04) + swing, foot_y),
        leg_w,
        _shade(clothes, 0.7),
        stroke,
    )
    # Shoes
    _ink_ellipse(draw, (cx - int(size * 0.16) - swing, foot_y - int(size * 0.04), cx - int(size * 0.02) - swing, foot_y + int(size * 0.03)), INK, max(2, stroke - 1))
    _ink_ellipse(draw, (cx + int(size * 0.02) + swing, foot_y - int(size * 0.04), cx + int(size * 0.16) + swing, foot_y + int(size * 0.03)), INK, max(2, stroke - 1))

    # Torso
    _ink_round(draw, (cx - body_w // 2, shoulder_y, cx + body_w // 2, hip_y + int(size * 0.04)), int(size * 0.08), clothes, stroke)
    if clothes_style == 0:
        # hoodie pocket
        pw = int(body_w * 0.55)
        _ink_round(
            draw,
            (cx - pw // 2, hip_y - int(size * 0.10), cx + pw // 2, hip_y),
            6,
            _shade(clothes, 0.82),
            max(2, stroke - 1),
        )

    # Near arm (maybe holding phone)
    near = (
        cx + body_w // 2 - arm_w // 2,
        shoulder_y + int(size * 0.02),
        cx + body_w // 2 + arm_w + int(size * 0.02),
        hip_y + int(size * 0.02),
    )
    if hold_phone:
        near = (
            cx + body_w // 2 - arm_w,
            shoulder_y - int(size * 0.02),
            cx + body_w // 2 + arm_w,
            head_cy + head_r,
        )
    _ink_round(draw, near, arm_w, skin, stroke)
    if hold_phone:
        px0 = cx + body_w // 2 + int(size * 0.02)
        py0 = head_cy + int(head_r * 0.2)
        _ink_round(draw, (px0, py0, px0 + int(size * 0.07), py0 + int(size * 0.12)), 4, (40, 44, 52), stroke)

    # Head + hair
    hx0, hy0 = cx - head_r, head_cy - head_r
    hx1, hy1 = cx + head_r, head_cy + head_r
    if clothes_style == 0:
        _ink_ellipse(draw, (hx0 - int(size * 0.02), hy0 + int(head_r * 0.4), hx1 + int(size * 0.02), hy1 + int(head_r * 0.15)), clothes, stroke)
    _ink_ellipse(draw, (hx0, hy0, hx1, hy1), skin, stroke)
    if hair_style == 0:
        _ink_ellipse(draw, (hx0 - int(size * 0.02), hy0 - int(head_r * 0.35), hx1 + int(size * 0.02), head_cy + int(head_r * 0.15)), hair, stroke)
        draw.ellipse((hx0 + stroke, head_cy - int(head_r * 0.15), hx1 - stroke, hy1 - stroke), fill=skin)
    elif hair_style == 1:
        _ink_poly(
            draw,
            [
                (cx - int(head_r * 0.9), head_cy - int(head_r * 0.1)),
                (cx - int(head_r * 0.2), hy0 - int(head_r * 0.55)),
                (cx + int(head_r * 0.85), head_cy - int(head_r * 0.2)),
            ],
            hair,
            stroke,
        )
        _ink_ellipse(draw, (hx0, hy0, hx1, head_cy + int(head_r * 0.2)), hair, stroke)
        draw.ellipse((hx0 + stroke, head_cy - int(head_r * 0.2), hx1 - stroke, hy1 - stroke), fill=skin)
    else:
        _ink_ellipse(draw, (hx0, hy0 - int(head_r * 0.15), hx1, head_cy), hair, stroke)

    # Face
    eye_y = head_cy - int(head_r * 0.08)
    eye_dx = int(head_r * 0.38)
    eye_r = max(3, int(head_r * 0.16))
    if expression in ("happy", "excited"):
        for sign in (-1, 1):
            ex = cx + sign * eye_dx
            draw.arc((ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r), 200, 340, fill=INK, width=max(2, stroke - 1))
    else:
        for sign in (-1, 1):
            ex = cx + sign * eye_dx
            _ink_ellipse(draw, (ex - eye_r, eye_y - eye_r, ex + eye_r, eye_y + eye_r), (252, 252, 252), max(2, stroke - 1))
            pr = max(2, eye_r // 2)
            draw.ellipse((ex - pr, eye_y - pr + 1, ex + pr, eye_y + pr + 1), fill=INK)
    mouth_y = head_cy + int(head_r * 0.42)
    mw = int(head_r * (0.55 if expression in ("happy", "excited") else 0.35))
    if expression == "sad":
        draw.arc((cx - mw, mouth_y, cx + mw, mouth_y + int(head_r * 0.35)), 20, 160, fill=INK, width=max(2, stroke - 1))
    elif expression in ("happy", "excited"):
        draw.arc((cx - mw, mouth_y - int(head_r * 0.2), cx + mw, mouth_y + int(head_r * 0.35)), 20, 160, fill=INK, width=max(2, stroke - 1))
    else:
        draw.line((cx - mw // 2, mouth_y, cx + mw // 2, mouth_y), fill=INK, width=max(2, stroke - 1))


def render_cel_frame(
    spec: Any,
    t: float,
    width: int,
    height: int,
    *,
    seed: int = 0,
) -> np.ndarray:
    """One RGB uint8 frame: room kit + inked character, posed from scene layers."""
    w, h = int(width), int(height)
    colors = _palette(spec)
    inst = getattr(spec, "instance", None) if isinstance(getattr(spec, "instance", None), dict) else {}
    origin = inst.get("loop_origin") if isinstance(inst.get("loop_origin"), dict) else None
    if origin:
        extra = []
        for p in origin.get("palette") or []:
            if isinstance(p, dict) and p.get("r") is not None:
                extra.append(_as_rgb((p.get("r"), p.get("g"), p.get("b"))))
        if extra:
            colors = extra + colors
    setting = str(getattr(spec, "setting", None) or "apartment")
    prompt = str(getattr(spec, "raw_prompt", "") or "").lower()
    rng = random.Random(int(seed) + sum(ord(c) for c in setting))
    stroke = _stroke(w)
    img = Image.new("RGB", (w, h), _mix(colors[1 % len(colors)], (232, 214, 196), 0.55))
    draw = ImageDraw.Draw(img)
    floor_y = _draw_room(draw, w, h, setting, colors, rng, stroke)

    layers = getattr(spec, "scene_layers", None) or []
    char = next((L for L in layers if isinstance(L, dict) and L.get("kind") == "character"), None)
    pose = {"x": 0.42, "y": 0.55, "scale": 1.0, "rot": 0.0}
    expression = "neutral"
    if char is not None:
        from ..creation.scene_graph import sample_layer_at
        pose = sample_layer_at(char, float(t), smoothness=getattr(spec, "motion_smoothness", "smooth") or "smooth")
        expression = str(char.get("expression") or "neutral").lower()
        c_hint = char.get("color")
        if c_hint:
            colors = [_as_rgb(c_hint)] + colors
    cx = int(max(0.18, min(0.82, float(pose.get("x") or 0.42))) * w)
    smear = max(0.0, float(pose.get("scale") or 1.0) - 1.0)
    size = int(h * 0.62 * max(0.85, min(1.2, float(pose.get("scale") or 1.0))))
    skin = _mix((242, 196, 164), colors[0], 0.12)
    clothes = colors[0]
    hair = _shade(colors[1 % len(colors)], 0.55)
    hold_phone = "phone" in prompt
    _draw_character(
        draw,
        cx,
        floor_y,
        size,
        clothes,
        skin,
        hair,
        rng,
        stroke,
        expression=expression,
        hold_phone=hold_phone,
        smear=smear,
    )
    return np.asarray(img, dtype=np.uint8)
