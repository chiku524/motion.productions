"""
Pixel-field emergence: independent pairings can mass into objects, settings, scenery.

Generation stays a pixel field (no premade scene layers). After render, this
module looks at the field and:
  - scores origin settings / scene primitives the layout already resembles
  - matches spatial masses against registered entity profiles
  - names leftover coherent masses as novel discoveries

Stumbled-upon hits POST the existing key so D1 increments count.
Novel hits get a non-gibberish name and a new key.
"""
from __future__ import annotations

from typing import Any

import numpy as np

from .completion_targets import SETTING_PRIMITIVES
from .entity_registry import entity_profile_key


_MAX_SETTINGS = 2
_MAX_ENTITIES = 4
_GRID = 32
_SETTING_SCORE_MIN = 0.42
_REGION_MIN_FRAC = 0.035
_REGION_MAX_FRAC = 0.55


def _luma(r: float, g: float, b: float) -> float:
    return 0.299 * r + 0.587 * g + 0.114 * b


def _sat(r: float, g: float, b: float) -> float:
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx < 1e-6:
        return 0.0
    return (mx - mn) / mx


def _color_hint(r: float, g: float, b: float) -> str:
    if r >= g and r >= b and r - min(g, b) > 18:
        return "red"
    if b >= r and b >= g and b - min(r, g) > 18:
        return "blue"
    if g >= r and g >= b and g - min(r, b) > 18:
        return "forest"
    return "none"


def _hue_bucket(r: float, g: float, b: float) -> int:
    """0 shadow, 1 gray, 2 red, 3 yellow, 4 green, 5 cyan, 6 blue, 7 magenta."""
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx < 40:
        return 0
    if mx - mn < 28:
        return 1
    if r >= g and r >= b:
        return 3 if g > b + 20 else 2
    if g >= r and g >= b:
        return 5 if b > r + 20 else 4
    return 7 if r > g + 20 else 6


def _downsample(frame: np.ndarray, size: int = _GRID) -> np.ndarray:
    h, w = frame.shape[:2]
    ys = np.linspace(0, max(h - 1, 0), size).astype(np.int32)
    xs = np.linspace(0, max(w - 1, 0), size).astype(np.int32)
    return frame[ys][:, xs].astype(np.float32)


def _band_means(grid: np.ndarray) -> dict[str, dict[str, float]]:
    h = grid.shape[0]
    sky = grid[: max(1, int(h * 0.30))]
    mid = grid[int(h * 0.30) : int(h * 0.70)]
    ground = grid[int(h * 0.70) :]
    out: dict[str, dict[str, float]] = {}
    for name, band in (("sky", sky), ("mid", mid), ("ground", ground)):
        if band.size == 0:
            band = grid
        r = float(band[:, :, 0].mean())
        g = float(band[:, :, 1].mean())
        b = float(band[:, :, 2].mean())
        out[name] = {"r": r, "g": g, "b": b, "luma": _luma(r, g, b), "sat": _sat(r, g, b)}
    return out


def _layout_stats(frame: np.ndarray) -> dict[str, Any]:
    grid = _downsample(frame)
    bands = _band_means(grid)
    r = float(grid[:, :, 0].mean())
    g = float(grid[:, :, 1].mean())
    b = float(grid[:, :, 2].mean())
    luma = _luma(r, g, b)
    sat = _sat(r, g, b)
    contrast = float(np.std(0.299 * grid[:, :, 0] + 0.587 * grid[:, :, 1] + 0.114 * grid[:, :, 2]))
    split = abs(bands["sky"]["luma"] - bands["ground"]["luma"])
    return {
        "grid": grid,
        "bands": bands,
        "r": r,
        "g": g,
        "b": b,
        "luma": luma,
        "sat": sat,
        "contrast": contrast,
        "split": split,
    }


def score_settings(stats: dict[str, Any]) -> list[tuple[str, float]]:
    """How much the pixel field resembles each origin setting (recognition, not drawing)."""
    bands = stats["bands"]
    sky, mid, ground = bands["sky"], bands["mid"], bands["ground"]
    luma, sat, contrast, split = stats["luma"], stats["sat"], stats["contrast"], stats["split"]
    scores: dict[str, float] = {s: 0.0 for s in SETTING_PRIMITIVES}

    def _boost(name: str, amount: float) -> None:
        if name in scores:
            scores[name] += amount

    if luma < 55:
        _boost("night", 0.55)
        _boost("noir", 0.25)
        _boost("space", 0.20 if sat < 0.25 else 0.08)
    if luma > 170:
        _boost("day", 0.40)
        _boost("beach", 0.12)
    if sat < 0.18 and contrast > 35:
        _boost("noir", 0.35)
        _boost("moody", 0.15)
    if sat > 0.55 and (mid["b"] > 140 or sky["b"] > 140) and (mid["r"] > 120 or mid["g"] < 80):
        _boost("neon", 0.40)

    if ground["b"] > ground["r"] + 20 and ground["b"] > ground["g"] and luma > 40:
        _boost("ocean", 0.38)
        _boost("underwater", 0.12)
    if mid["b"] > mid["r"] + 18 and mid["b"] > mid["g"]:
        _boost("ocean", 0.18)
        _boost("underwater", 0.28 if luma < 140 else 0.10)
    if ground["r"] > 150 and ground["g"] > 120 and ground["b"] < ground["r"] - 20 and luma > 120:
        _boost("beach", 0.40)
        _boost("desert", 0.18)
    if mid["g"] > mid["r"] + 18 and mid["g"] > mid["b"] + 8:
        _boost("forest", 0.45)
    if ground["r"] > ground["b"] + 25 and ground["g"] > 80 and ground["b"] < 110 and luma > 90:
        _boost("desert", 0.38)
        _boost("golden_hour", 0.12)
    if sky["r"] > 160 and sky["g"] > 90 and sky["b"] < sky["r"] - 15:
        _boost("golden_hour", 0.42)
    if split > 40 and sky["luma"] > ground["luma"] + 15:
        _boost("mountain", 0.22)
        _boost("exterior", 0.18)
        _boost("day", 0.10)
    if contrast > 28 and sat < 0.35 and 60 < luma < 160:
        _boost("city", 0.22)
        _boost("rain", 0.12)
    if sat < 0.22 and 70 < luma < 150 and contrast < 22:
        _boost("interior", 0.20)
        _boost("studio", 0.16)
    if split < 12 and contrast > 40:
        _boost("abstract", 0.30)
    if luma < 90 and sky["b"] > sky["r"] and sky["luma"] > 30:
        _boost("night", 0.12)

    ranked = [(k, v) for k, v in scores.items() if v >= _SETTING_SCORE_MIN]
    ranked.sort(key=lambda kv: (-kv[1], kv[0]))
    return ranked[:_MAX_SETTINGS]


def _quantize(grid: np.ndarray) -> np.ndarray:
    h, w = grid.shape[:2]
    labels = np.zeros((h, w), dtype=np.int32)
    for y in range(h):
        for x in range(w):
            r, g, b = float(grid[y, x, 0]), float(grid[y, x, 1]), float(grid[y, x, 2])
            li = 0 if _luma(r, g, b) < 70 else (1 if _luma(r, g, b) < 160 else 2)
            labels[y, x] = _hue_bucket(r, g, b) * 3 + li
    return labels


def _connected_regions(labels: np.ndarray) -> list[np.ndarray]:
    h, w = labels.shape
    seen = np.zeros((h, w), dtype=bool)
    regions: list[np.ndarray] = []
    total = h * w
    min_cells = max(4, int(_REGION_MIN_FRAC * total))
    max_cells = int(_REGION_MAX_FRAC * total)
    for y in range(h):
        for x in range(w):
            if seen[y, x]:
                continue
            lab = int(labels[y, x])
            stack = [(y, x)]
            seen[y, x] = True
            cells: list[tuple[int, int]] = []
            while stack:
                cy, cx = stack.pop()
                cells.append((cy, cx))
                for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < h and 0 <= nx < w and not seen[ny, nx] and int(labels[ny, nx]) == lab:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
            n = len(cells)
            if n < min_cells or n > max_cells:
                continue
            mask = np.zeros((h, w), dtype=bool)
            for cy, cx in cells:
                mask[cy, cx] = True
            regions.append(mask)
    regions.sort(key=lambda m: int(m.sum()), reverse=True)
    return regions[:8]


def _guess_kind(region: dict[str, Any]) -> str:
    cy = region["cy"]
    aspect = region["aspect"]  # height / width
    compact = region["compact"]
    luma = region["luma"]
    hint = region["color_hint"]
    frac = region["frac"]
    if cy < 0.30 and luma > 160 and aspect < 0.75:
        return "cloud"
    if cy < 0.28 and luma > 190 and frac < 0.08:
        return "star"
    if cy > 0.70 and hint == "blue" and aspect < 0.65:
        return "wave"
    if aspect > 1.25 and hint == "forest" and 0.25 < cy < 0.75:
        return "tree"
    if aspect > 1.15 and compact > 0.40 and hint in ("none", "red") and 0.30 < cy < 0.80:
        return "building"
    if cy > 0.62 and aspect < 0.70 and hint != "blue" and compact > 0.35:
        return "vehicle"
    if 0.08 < frac < 0.22 and compact > 0.45 and 0.30 < cy < 0.75:
        return "character"
    if hint == "blue" and 0.35 < cy < 0.80 and compact > 0.40:
        return "fish"
    if cy < 0.40 and aspect < 0.80 and luma > 140:
        return "bird"
    return "composed"


def extract_regions(frame: np.ndarray) -> list[dict[str, Any]]:
    grid = _downsample(frame)
    labels = _quantize(grid)
    h, w = labels.shape
    total = float(h * w)
    out: list[dict[str, Any]] = []
    for mask in _connected_regions(labels):
        ys, xs = np.where(mask)
        if ys.size == 0:
            continue
        y0, y1 = int(ys.min()), int(ys.max())
        x0, x1 = int(xs.min()), int(xs.max())
        bh = max(1, y1 - y0 + 1)
        bw = max(1, x1 - x0 + 1)
        cells = float(mask.sum())
        mean = grid[mask].mean(axis=0)
        r, g, b = float(mean[0]), float(mean[1]), float(mean[2])
        region = {
            "r": r,
            "g": g,
            "b": b,
            "luma": _luma(r, g, b),
            "cy": ((y0 + y1) / 2.0) / max(h - 1, 1),
            "cx": ((x0 + x1) / 2.0) / max(w - 1, 1),
            "aspect": bh / float(bw),
            "compact": cells / float(bh * bw),
            "frac": cells / total,
            "color_hint": _color_hint(r, g, b),
        }
        region["kind"] = _guess_kind(region)
        out.append(region)
    return out


def _match_registered_entity(region: dict[str, Any], knowledge: dict[str, Any] | None) -> dict[str, Any] | None:
    kind = region["kind"]
    hint = region["color_hint"]
    best: dict[str, Any] | None = None
    for ent in (knowledge or {}).get("learned_entities") or []:
        if not isinstance(ent, dict):
            continue
        ek = str(ent.get("kind") or "").strip().lower()
        if ek != kind:
            continue
        eh = str(ent.get("color_hint") or "none").strip().lower() or "none"
        if eh not in ("none", "", hint) and hint not in ("none", "", eh):
            continue
        best = ent
        break
    return best


def _entity_payload(
    region: dict[str, Any],
    *,
    prompt: str,
    registered: dict[str, Any] | None,
    existing_names: set[str],
    stumbled: bool,
) -> dict[str, Any]:
    kind = str((registered or {}).get("kind") or region["kind"] or "composed")
    hint = str((registered or {}).get("color_hint") or region["color_hint"] or "none")
    traj = str((registered or {}).get("trajectory") or "none")
    if registered and registered.get("key"):
        key = str(registered["key"])
        label = str(registered.get("label") or registered.get("name") or kind)
        name = str(registered.get("name") or label)
    else:
        from .blend_names import generate_sensible_name

        name = generate_sensible_name(
            "color",
            value_hint=kind,
            existing_names=existing_names,
            rgb_hint=(region["r"], region["g"], region["b"]),
        )
        existing_names.add(name)
        label = name
        key = entity_profile_key(kind, color_hint=hint, trajectory=traj)
    return {
        "key": key,
        "kind": kind,
        "trajectory": traj,
        "bounce": int(registered.get("bounce") or 0) if registered else 0,
        "color_hint": hint if hint != "none" else None,
        "label": label,
        "directionality": str((registered or {}).get("directionality") or "none"),
        "expression": "neutral",
        "personality": "neutral",
        "gag": "none",
        "name": name,
        "source_prompt": (prompt or "")[:80],
        "entity_json": {
            "kind": kind,
            "color_hint": hint,
            "label": label,
            "emergence": "pixel_field",
            "stumbled": bool(stumbled),
            "rgb": [round(region["r"]), round(region["g"]), round(region["b"])],
            "cy": round(float(region["cy"]), 3),
            "frac": round(float(region["frac"]), 3),
        },
    }


def _setting_payload(value: str, *, prompt: str, name: str | None = None) -> dict[str, Any]:
    key = str(value).strip().lower()
    from .blend_names import narrative_display_name

    display = name or narrative_display_name("settings", key, value)
    return {
        "key": key,
        "value": value,
        "name": display,
        "source_prompt": (prompt or "")[:80],
        "depth_breakdown": {key: 1.0},
    }


def emerge_from_frame(
    frame: np.ndarray,
    *,
    prompt: str = "",
    knowledge: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Recognize settings and object-like masses in one RGB frame.
    Returns {settings: [...], entities: [...]} discovery payloads.
    """
    if frame is None or getattr(frame, "ndim", 0) != 3 or frame.shape[-1] < 3:
        return {"settings": [], "entities": []}
    stats = _layout_stats(frame)
    settings: list[dict[str, Any]] = []
    seen_settings: set[str] = set()
    for value, _score in score_settings(stats):
        if value in seen_settings:
            continue
        seen_settings.add(value)
        settings.append(_setting_payload(value, prompt=prompt))
    if not settings and stats["split"] > 25:
        from .blend_names import generate_sensible_name

        name = generate_sensible_name(
            "color",
            value_hint="setting",
            rgb_hint=(stats["r"], stats["g"], stats["b"]),
        )
        key = name.strip().lower()
        if key and key not in seen_settings:
            settings.append(_setting_payload(key, prompt=prompt, name=name))

    existing_names = {
        str(e.get("name") or e.get("label") or "")
        for e in (knowledge or {}).get("learned_entities") or []
        if isinstance(e, dict)
    }
    entities: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for region in extract_regions(frame):
        if len(entities) >= _MAX_ENTITIES:
            break
        registered = _match_registered_entity(region, knowledge)
        stumbled = registered is not None or region["kind"] in (
            "tree", "cloud", "wave", "building", "character", "fish", "star", "vehicle", "bird",
        )
        payload = _entity_payload(
            region,
            prompt=prompt,
            registered=registered,
            existing_names=existing_names,
            stumbled=bool(registered) or (stumbled and region["kind"] != "composed"),
        )
        if payload["key"] in seen_keys:
            continue
        seen_keys.add(payload["key"])
        entities.append(payload)

    return {"settings": settings[:_MAX_SETTINGS], "entities": entities[:_MAX_ENTITIES]}


def grow_emergence_from_frames(
    frames: list[np.ndarray],
    *,
    prompt: str = "",
    knowledge: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    kind: str = "frame",
) -> tuple[dict[str, int], dict[str, Any]]:
    """
    Sample a few frames from a clip and union emergence discoveries.
    Also writes narrative settings into the local registry (count++ / novel name).
    """
    added = {"settings": 0, "entities": 0}
    novel: dict[str, Any] = {"narrative": {"settings": []}, "entities": []}
    if not frames:
        return added, novel
    n = len(frames)
    if (kind or "frame") == "window" and n > 3:
        idxs = [0, n // 3, (2 * n) // 3, n - 1]
    elif n >= 3:
        idxs = [0, n // 2, n - 1]
    else:
        idxs = list(range(n))
    seen_set: set[str] = set()
    seen_ent: set[str] = set()
    for i in idxs:
        found = emerge_from_frame(frames[i], prompt=prompt, knowledge=knowledge)
        for item in found.get("settings") or []:
            key = str(item.get("key") or "")
            if not key or key in seen_set:
                continue
            seen_set.add(key)
            from .narrative_registry import ensure_narrative_in_registry

            ensure_narrative_in_registry(
                "settings",
                key,
                source_prompt=prompt,
                config=config,
                out_novel=novel["narrative"],
                force_novel=True,
            )
            added["settings"] += 1
        for item in found.get("entities") or []:
            key = str(item.get("key") or "")
            if not key or key in seen_ent:
                continue
            seen_ent.add(key)
            novel["entities"].append(item)
            added["entities"] += 1
    return added, novel


def merge_emergence_payloads(
    novel_for_sync: dict[str, Any],
    narrative_novel: dict[str, list[dict[str, Any]]] | None,
    entity_novel: list[dict[str, Any]] | None,
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Union emergence settings/entities into the loop's discovery payloads."""
    narrative_novel = dict(narrative_novel or {})
    entity_novel = list(entity_novel or [])
    em_narr = novel_for_sync.get("narrative") or {}
    if isinstance(em_narr, dict):
        for aspect, items in em_narr.items():
            if not items:
                continue
            bucket = list(narrative_novel.get(aspect) or [])
            seen = {str(x.get("key") or "") for x in bucket if isinstance(x, dict)}
            for item in items:
                k = str(item.get("key") or "") if isinstance(item, dict) else ""
                if k and k not in seen:
                    bucket.append(item)
                    seen.add(k)
            narrative_novel[aspect] = bucket
    seen_e = {str(e.get("key") or "") for e in entity_novel if isinstance(e, dict)}
    for e in novel_for_sync.get("entities") or []:
        if not isinstance(e, dict):
            continue
        k = str(e.get("key") or "")
        if k and k not in seen_e:
            entity_novel.append(e)
            seen_e.add(k)
    return narrative_novel, entity_novel
