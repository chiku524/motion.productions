"""
Scene graph: stylized entity layers with keyframed motion (Phase 2+).

No external assets required — circle/rect/arrow/character + setting props
(tree/fish/wave/building/cloud).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

_ENTITY_KINDS = frozenset({
    "circle", "rect", "arrow", "character",
    "tree", "fish", "wave", "building", "cloud",
})
_PROP_KINDS = frozenset({"tree", "fish", "wave", "building", "cloud"})


@dataclass
class LayerKeyframe:
    t: float  # seconds
    x: float = 0.5  # normalized 0–1
    y: float = 0.5
    scale: float = 1.0
    rot: float = 0.0  # radians
    opacity: float = 1.0


@dataclass
class SceneLayer:
    id: str
    kind: str  # circle | rect | arrow | character | tree | fish | wave | building | cloud
    color: tuple[int, int, int] = (220, 60, 60)
    z: int = 1
    keyframes: list[LayerKeyframe] = field(default_factory=list)
    sfx_on: list[str] = field(default_factory=list)  # e.g. ["bounce"]
    bounce: bool = False
    expression: str = "neutral"  # happy | sad | angry | calm | excited | nervous | neutral
    personality: str = "neutral"  # playful | serious | energetic | shy | confident | neutral
    gag: str = "none"  # none | squash | spin | wink | flourish | double_take

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["color"] = list(self.color)
        return d


@dataclass
class SceneGraph:
    layers: list[SceneLayer] = field(default_factory=list)

    def to_dict_list(self) -> list[dict[str, Any]]:
        return [layer.to_dict() for layer in self.layers]


def _lerp(a: float, b: float, u: float) -> float:
    return a + (b - a) * u


def sample_layer_at(layer: SceneLayer | dict[str, Any], t: float) -> dict[str, float]:
    """Interpolate layer pose at time t (seconds)."""
    if isinstance(layer, dict):
        kfs = layer.get("keyframes") or []
        kind = layer.get("kind", "circle")
    else:
        kfs = [asdict(k) if hasattr(k, "__dataclass_fields__") else k for k in layer.keyframes]
        kind = layer.kind
    if not kfs:
        return {"x": 0.5, "y": 0.5, "scale": 1.0, "rot": 0.0, "opacity": 1.0, "kind": kind}
    kfs = sorted(kfs, key=lambda k: float(k.get("t", 0)))
    if t <= float(kfs[0].get("t", 0)):
        k = kfs[0]
        return {
            "x": float(k.get("x", 0.5)),
            "y": float(k.get("y", 0.5)),
            "scale": float(k.get("scale", 1.0)),
            "rot": float(k.get("rot", 0.0)),
            "opacity": float(k.get("opacity", 1.0)),
            "kind": kind,
        }
    if t >= float(kfs[-1].get("t", 0)):
        k = kfs[-1]
        return {
            "x": float(k.get("x", 0.5)),
            "y": float(k.get("y", 0.5)),
            "scale": float(k.get("scale", 1.0)),
            "rot": float(k.get("rot", 0.0)),
            "opacity": float(k.get("opacity", 1.0)),
            "kind": kind,
        }
    for i in range(len(kfs) - 1):
        t0 = float(kfs[i].get("t", 0))
        t1 = float(kfs[i + 1].get("t", 0))
        if t0 <= t <= t1:
            u = 0.0 if t1 <= t0 else (t - t0) / (t1 - t0)
            # Bounce easing: ease toward floor contacts
            a, b = kfs[i], kfs[i + 1]
            return {
                "x": _lerp(float(a.get("x", 0.5)), float(b.get("x", 0.5)), u),
                "y": _lerp(float(a.get("y", 0.5)), float(b.get("y", 0.5)), u),
                "scale": _lerp(float(a.get("scale", 1.0)), float(b.get("scale", 1.0)), u),
                "rot": _lerp(float(a.get("rot", 0.0)), float(b.get("rot", 0.0)), u),
                "opacity": _lerp(float(a.get("opacity", 1.0)), float(b.get("opacity", 1.0)), u),
                "kind": kind,
            }
    k = kfs[-1]
    return {
        "x": float(k.get("x", 0.5)),
        "y": float(k.get("y", 0.5)),
        "scale": float(k.get("scale", 1.0)),
        "rot": float(k.get("rot", 0.0)),
        "opacity": float(k.get("opacity", 1.0)),
        "kind": kind,
    }


def _trajectory_path(
    trajectory: str,
    *,
    duration: float,
    bounce: bool,
    gag: str = "none",
    pacing: float = 1.0,
) -> list[LayerKeyframe]:
    """Build keyframes for a simple directional path (optional gag + pacing)."""
    duration = max(0.35, float(duration or 4.0))
    pacing = max(0.5, min(1.5, float(pacing or 1.0)))
    # Faster pacing compresses motion into the first portion of the window
    motion_dur = duration / pacing if pacing > 1.0 else duration * pacing
    motion_dur = min(duration, max(0.25, motion_dur))
    traj = (trajectory or "none").lower()
    gag = (gag or "none").lower()
    start = {"x": 0.5, "y": 0.5}
    end = {"x": 0.5, "y": 0.5}
    if traj == "left":
        start, end = {"x": 0.85, "y": 0.5}, {"x": 0.15, "y": 0.5}
    elif traj == "right":
        start, end = {"x": 0.15, "y": 0.5}, {"x": 0.85, "y": 0.5}
    elif traj == "up":
        start, end = {"x": 0.5, "y": 0.85}, {"x": 0.5, "y": 0.2}
    elif traj == "down":
        start, end = {"x": 0.5, "y": 0.2}, {"x": 0.5, "y": 0.85}
    elif traj == "toward":
        kfs = [
            LayerKeyframe(t=0.0, x=0.5, y=0.55, scale=0.5, rot=0.0),
            LayerKeyframe(t=motion_dur, x=0.5, y=0.5, scale=1.6, rot=0.35 if gag in ("flourish", "spin") else 0.0),
        ]
        if gag == "flourish":
            kfs.insert(1, LayerKeyframe(t=motion_dur * 0.5, x=0.5, y=0.48, scale=1.1, rot=3.14))
        return kfs
    elif traj == "away":
        return [
            LayerKeyframe(t=0.0, x=0.5, y=0.5, scale=1.4),
            LayerKeyframe(t=motion_dur, x=0.5, y=0.55, scale=0.4),
        ]
    elif traj == "none" and bounce:
        kfs: list[LayerKeyframe] = []
        n_bounces = max(2, int(motion_dur / 0.7))
        for i in range(n_bounces + 1):
            t = motion_dur * (i / n_bounces)
            y = 0.75 if i % 2 == 0 else 0.35
            scale = 0.75 if (i % 2 == 0 and gag in ("squash", "none") and bounce) else (1.12 if i % 2 else 1.0)
            kfs.append(LayerKeyframe(t=t, x=0.5, y=y, scale=scale))
        return kfs

    if bounce:
        kfs = []
        n = max(3, int(motion_dur / 0.6))
        for i in range(n + 1):
            u = i / n
            t = motion_dur * u
            x = start["x"] + (end["x"] - start["x"]) * u
            phase = (u * n) % 1.0
            y_base = start["y"] + (end["y"] - start["y"]) * u
            y = y_base - 0.25 * (4 * phase * (1 - phase))
            floor = i % 2 == 0
            if floor:
                y = max(y_base, 0.72)
            # Phase F: squash on floor contact, stretch at apex
            if gag in ("squash", "none") or bounce:
                scale = 0.72 if floor else 1.15
            else:
                scale = 1.0
            rot = 0.0
            if gag == "spin":
                rot = u * 6.28
            kfs.append(LayerKeyframe(t=t, x=x, y=min(0.9, max(0.15, y)), scale=scale, rot=rot))
        return kfs

    kfs = [
        LayerKeyframe(t=0.0, x=start["x"], y=start["y"], scale=1.0, rot=0.0),
        LayerKeyframe(t=motion_dur, x=end["x"], y=end["y"], scale=1.0, rot=6.28 if gag == "spin" else 0.0),
    ]
    if gag == "double_take" and motion_dur > 0.6:
        mid = motion_dur * 0.45
        mx = start["x"] + (end["x"] - start["x"]) * 0.45
        my = start["y"] + (end["y"] - start["y"]) * 0.45
        kfs = [
            LayerKeyframe(t=0.0, x=start["x"], y=start["y"], scale=1.0),
            LayerKeyframe(t=mid, x=mx, y=my, scale=1.0),
            LayerKeyframe(t=mid + 0.28, x=mx, y=my, scale=1.05),  # hold / look-back
            LayerKeyframe(t=motion_dur, x=end["x"], y=end["y"], scale=1.0),
        ]
    elif gag == "flourish":
        kfs.insert(1, LayerKeyframe(
            t=motion_dur * 0.5,
            x=(start["x"] + end["x"]) / 2,
            y=min(0.35, (start["y"] + end["y"]) / 2 - 0.1),
            scale=1.2,
            rot=3.14,
        ))
    return kfs


def _offset_keyframes(kfs: list[LayerKeyframe], t_start: float, t_end: float) -> list[LayerKeyframe]:
    """Shift local 0..dur keyframes into [t_start, t_end] and bookend with opacity fades."""
    t_start = max(0.0, float(t_start))
    t_end = max(t_start + 0.05, float(t_end))
    if not kfs:
        return [
            LayerKeyframe(t=t_start, opacity=0.0),
            LayerKeyframe(t=t_end, opacity=0.0),
        ]
    local_max = max(float(k.t) for k in kfs) or 1.0
    window = t_end - t_start
    out: list[LayerKeyframe] = []
    # Invisible before window
    first = kfs[0]
    out.append(LayerKeyframe(t=max(0.0, t_start - 0.02), x=first.x, y=first.y, scale=first.scale, rot=first.rot, opacity=0.0))
    for k in kfs:
        u = float(k.t) / local_max if local_max > 0 else 0.0
        out.append(LayerKeyframe(
            t=t_start + u * window,
            x=k.x,
            y=k.y,
            scale=k.scale,
            rot=k.rot,
            opacity=1.0 if k.opacity > 0 else 0.0,
        ))
    last = kfs[-1]
    out.append(LayerKeyframe(t=t_end, x=last.x, y=last.y, scale=last.scale, rot=last.rot, opacity=0.0))
    return out


def _color_from_hint(
    hint: str | None,
    palette_colors: list[tuple[int, int, int]] | None = None,
    *,
    prop_color: tuple[int, int, int] | None = None,
) -> tuple[int, int, int]:
    if prop_color and isinstance(prop_color, (list, tuple)) and len(prop_color) >= 3:
        return (int(prop_color[0]), int(prop_color[1]), int(prop_color[2]))
    named = {
        "warm": (220, 90, 50),
        "cool": (60, 120, 200),
        "red": (220, 60, 60),
        "blue": (50, 100, 220),
        "green": (40, 160, 80),
        "fire": (230, 90, 40),
        "ocean": (40, 120, 200),
        "neon": (180, 60, 220),
        "forest": (34, 120, 55),
        "night": (40, 40, 80),
        "warm_sunset": (240, 120, 50),
    }
    if hint and hint in named:
        return named[hint]
    if palette_colors:
        mid = palette_colors[len(palette_colors) // 2]
        return (int(mid[0]), int(mid[1]), int(mid[2]))
    return (220, 60, 60)


def build_scene_graph_from_instruction(
    instruction: Any,
    *,
    duration_seconds: float | None = None,
    palette_colors: list[tuple[int, int, int]] | None = None,
) -> SceneGraph:
    """Build a SceneGraph from InterpretedInstruction.entities."""
    from .props import (
        drift_prop_keyframes,
        jump_arc_keyframes,
        static_prop_keyframes,
        PROP_COLORS,
    )

    duration = float(
        duration_seconds
        or getattr(instruction, "duration_seconds", None)
        or 4.0
    )
    entities = list(getattr(instruction, "entities", None) or [])
    layers: list[SceneLayer] = []
    for i, ent in enumerate(entities):
        if not isinstance(ent, dict):
            continue
        kind = str(ent.get("kind") or "circle")
        if kind not in _ENTITY_KINDS:
            kind = "circle"
        traj = str(ent.get("trajectory") or "none")
        bounce = bool(ent.get("bounce"))
        gag = str(ent.get("gag") or ("squash" if bounce else "none")).lower()
        pacing = float(ent.get("pacing") or 1.0)
        t_start = ent.get("t_start")
        t_end = ent.get("t_end")
        # Infer trajectory from directionality if missing
        if traj == "none" and kind not in _PROP_KINDS:
            d = str(ent.get("directionality") or getattr(instruction, "motion_directionality", "none"))
            if d == "horizontal":
                traj = "left"
            elif d == "vertical":
                traj = "down" if bounce else "up"
            elif d == "diagonal":
                traj = "right"
            elif d == "radial":
                traj = "toward"
        prop_color = ent.get("prop_color")
        if isinstance(prop_color, (list, tuple)) and len(prop_color) >= 3:
            color = (int(prop_color[0]), int(prop_color[1]), int(prop_color[2]))
        elif kind in PROP_COLORS and not ent.get("color_hint"):
            color = PROP_COLORS[kind]
        else:
            color = _color_from_hint(ent.get("color_hint"), palette_colors)

        is_prop = bool(ent.get("is_prop")) or kind in _PROP_KINDS
        prop_motion = str(ent.get("prop_motion") or traj or "none")

        if is_prop and kind in _PROP_KINDS:
            px = float(ent.get("prop_x", 0.5))
            py = float(ent.get("prop_y", 0.5))
            pscale = float(ent.get("prop_scale", 1.0))
            if prop_motion == "jump" or (kind == "fish" and bounce):
                raw_kfs = jump_arc_keyframes(duration=duration, start_x=px, end_x=min(0.9, px + 0.55), water_y=py)
            elif prop_motion in ("left", "right", "up", "down") and kind in ("wave", "cloud", "fish"):
                raw_kfs = drift_prop_keyframes(duration=duration, trajectory=prop_motion, y=py, scale=pscale)
            else:
                raw_kfs = static_prop_keyframes(
                    duration=duration, x=px, y=py, scale=pscale, sway=kind in ("tree", "building")
                )
            kfs = [
                LayerKeyframe(
                    t=float(k["t"]),
                    x=float(k["x"]),
                    y=float(k["y"]),
                    scale=float(k.get("scale", 1.0)),
                    rot=float(k.get("rot", 0.0)),
                    opacity=float(k.get("opacity", 1.0)),
                )
                for k in raw_kfs
            ]
            z = int(ent.get("z", 0))
        elif t_start is not None and t_end is not None:
            local_dur = max(0.35, float(t_end) - float(t_start))
            local_kfs = _trajectory_path(traj, duration=local_dur, bounce=bounce, gag=gag, pacing=pacing)
            kfs = _offset_keyframes(local_kfs, float(t_start), float(t_end))
            z = i + 1
        else:
            kfs = _trajectory_path(traj, duration=duration, bounce=bounce, gag=gag, pacing=pacing)
            z = i + 1

        sfx_on = list(ent.get("sfx_on") or [])
        if bounce and "bounce" not in sfx_on and kind not in _PROP_KINDS:
            sfx_on.append("bounce")
        layers.append(
            SceneLayer(
                id=str(ent.get("id") or f"e{i}"),
                kind=kind,
                color=color,
                z=z if is_prop else (i + 1 if not is_prop else z),
                keyframes=kfs,
                sfx_on=sfx_on,
                bounce=bounce,
                expression=str(ent.get("expression") or "neutral"),
                personality=str(ent.get("personality") or "neutral"),
                gag=gag,
            )
        )
    return SceneGraph(layers=layers)


def sfx_events_from_scene_graph(
    graph: SceneGraph,
    *,
    duration_seconds: float,
) -> list[dict[str, Any]]:
    """Emit bounce/impact events at floor-contact keyframes."""
    events: list[dict[str, Any]] = []
    for layer in graph.layers:
        if "bounce" not in (layer.sfx_on or []) and not layer.bounce:
            continue
        # Floor contacts: local y maxima (lower on screen = higher y in our coords)
        kfs = layer.keyframes
        for i, kf in enumerate(kfs):
            y = kf.y
            is_floor = y >= 0.65
            if is_floor:
                events.append({
                    "kind": "bounce",
                    "t_sec": float(kf.t),
                    "strength": 0.85,
                    "layer_id": layer.id,
                })
            elif i > 0 and i < len(kfs) - 1:
                # Local peak toward floor
                if kfs[i - 1].y < y and kfs[i + 1].y < y and y > 0.55:
                    events.append({
                        "kind": "bounce",
                        "t_sec": float(kf.t),
                        "strength": 0.7,
                        "layer_id": layer.id,
                    })
    # Deduplicate near-simultaneous events
    events.sort(key=lambda e: e["t_sec"])
    deduped: list[dict[str, Any]] = []
    for e in events:
        if deduped and abs(e["t_sec"] - deduped[-1]["t_sec"]) < 0.08:
            continue
        if 0 <= e["t_sec"] <= duration_seconds + 0.05:
            deduped.append(e)
    return deduped


def walk_cycle_keyframes(
    *,
    duration: float,
    direction: str = "left",
    personality: str = "neutral",
) -> list[LayerKeyframe]:
    """Simple character walk: horizontal drift with bobbing (Phase D personality)."""
    duration = max(1.0, float(duration))
    x0, x1 = (0.8, 0.2) if direction == "left" else (0.2, 0.8)
    # Personality modulates step rate and bob amplitude
    pers = (personality or "neutral").lower()
    step_sec = 0.35
    bob = 0.04
    scale_base = 1.0
    if pers == "energetic":
        step_sec, bob, scale_base = 0.22, 0.07, 1.08
    elif pers == "playful":
        step_sec, bob, scale_base = 0.28, 0.06, 1.05
    elif pers == "shy":
        step_sec, bob, scale_base = 0.45, 0.02, 0.9
    elif pers == "serious":
        step_sec, bob, scale_base = 0.4, 0.015, 1.0
    elif pers == "confident":
        step_sec, bob, scale_base = 0.32, 0.035, 1.1
    steps = max(4, int(duration / step_sec))
    kfs: list[LayerKeyframe] = []
    for i in range(steps + 1):
        u = i / steps
        t = duration * u
        x = x0 + (x1 - x0) * u
        y = 0.55 + (bob if i % 2 else -bob * 0.5)
        kfs.append(LayerKeyframe(t=t, x=x, y=y, scale=scale_base))
    return kfs
