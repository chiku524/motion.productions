"""
Per-video values that discovery can store.

Registry pairings reshuffle known cells. Each generation also stamps new
quantized color bins and a new pure-sound amplitude so growth has something
novel to name. Same creation_seed reproduces the stamp; a new seed does not.
"""
from __future__ import annotations

from typing import Any

from ..random_utils import fresh_seed

# Matches static color keys (tolerance 25 → bins 0, 25, …, 250).
_COLOR_BINS = tuple(range(0, 256, 25))
_MAX_FIELD_COLORS = 24
_NOVEL_COLORS = 2


def _bin(rgb: tuple[int, int, int] | list[int]) -> tuple[int, int, int]:
    return tuple(int(int(c) // 25) * 25 for c in rgb[:3])  # type: ignore[return-value]


def _occupied_bins(
    colors: list[tuple[int, int, int]],
    knowledge: dict[str, Any] | None,
) -> set[tuple[int, int, int]]:
    from ..knowledge.blend_depth import COLOR_ORIGIN_PRIMITIVES

    occupied: set[tuple[int, int, int]] = set()
    for _name, rgb in COLOR_ORIGIN_PRIMITIVES:
        occupied.add(_bin(rgb))
    for rgb in colors:
        if rgb and len(rgb) >= 3:
            occupied.add(_bin(rgb))
    static = (knowledge or {}).get("static_colors") or {}
    if isinstance(static, dict):
        for data in static.values():
            if isinstance(data, dict) and "r" in data:
                occupied.add(_bin((int(data["r"]), int(data["g"]), int(data["b"]))))
    by_name = (knowledge or {}).get("color_by_name") or {}
    if isinstance(by_name, dict):
        for data in by_name.values():
            if isinstance(data, dict) and "r" in data:
                occupied.add(_bin((int(data["r"]), int(data["g"]), int(data["b"]))))
    return occupied


def _novel_bins(seed: int, occupied: set[tuple[int, int, int]], n: int) -> list[tuple[int, int, int]]:
    import random

    rng = random.Random(int(seed) & 0x7FFFFFFF)
    cells = [(r, g, b) for r in _COLOR_BINS for g in _COLOR_BINS for b in _COLOR_BINS]
    rng.shuffle(cells)
    out: list[tuple[int, int, int]] = []
    for cell in cells:
        if cell in occupied or cell in out:
            continue
        out.append(cell)
        if len(out) >= n:
            break
    return out


def _novel_sound(
    sounds: list[dict[str, Any]],
    knowledge: dict[str, Any] | None,
    seed: int,
) -> dict[str, Any] | None:
    import random

    from ..knowledge.growth_per_instance import _static_sound_key

    if not sounds:
        return None
    existing: set[str] = set()
    for s in (knowledge or {}).get("static_sound") or []:
        if isinstance(s, dict):
            key = _static_sound_key(s)
            if key:
                existing.add(key)
    for s in sounds:
        key = _static_sound_key(s)
        if key:
            existing.add(key)
    rng = random.Random((int(seed) ^ 0x5A17C3) & 0x7FFFFFFF)
    base = dict(sounds[-1])
    for _ in range(160):
        amp = round(rng.randrange(2, 96) / 100.0, 2)
        candidate = dict(base)
        candidate["amplitude"] = amp
        candidate["weight"] = amp
        key = _static_sound_key(candidate)
        if key and key not in existing:
            return candidate
    return None


def stamp_unique_discovery_values(
    colors: list[tuple[int, int, int]] | None,
    sounds: list[dict[str, Any]] | None,
    knowledge: dict[str, Any] | None,
    seed: int | None,
) -> tuple[list[tuple[int, int, int]], list[dict[str, Any]] | None, dict[str, Any]]:
    """
    Append novel color bins (or replace the tail at the field cap) and retune
    the last sound's amplitude so this video's discovery payload is unique.
    """
    use_seed = int(seed) if seed is not None else fresh_seed()
    field = [tuple(int(c) for c in rgb[:3]) for rgb in (colors or []) if rgb and len(rgb) >= 3]
    occupied = _occupied_bins(field, knowledge)
    novels = _novel_bins(use_seed, occupied, _NOVEL_COLORS)
    # Keep the field size the prompt pairing already chose. Novel bins replace the
    # tail so named colors at the front stay, and discovery still sees new cells.
    for i, rgb in enumerate(novels):
        if len(field) > len(novels):
            field[len(field) - 1 - i] = rgb
        elif len(field) < _MAX_FIELD_COLORS:
            field.append(rgb)

    sound_list = [dict(s) for s in (sounds or []) if isinstance(s, dict)]
    novel_sound = _novel_sound(sound_list, knowledge, use_seed)
    if novel_sound is not None and sound_list:
        sound_list[-1] = novel_sound

    discovery = {
        "colors": [
            {"r": int(r), "g": int(g), "b": int(b), "opacity": 1.0}
            for r, g, b in novels
        ],
        "sounds": [novel_sound] if novel_sound else [],
    }
    return field, (sound_list or None), discovery
