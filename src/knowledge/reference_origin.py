"""
Loop origin from a reference video.

A specialized loop (cartoon, later others) can start from measurements of an
existing clip: colors, sounds, motion windows, hold/snap timing. Those values
are grown into the registries like any other discovery.

The source frames are not stored or replayed. The origin is a recipe + named
registry entries, so generation stays ours (cel kit, pixel field, …) while
the starting palette and timing come from a real picture.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

import numpy as np

from ..analysis.metrics import frame_difference


_VALID_LOOPS = frozenset({"cartoon", "explorer", "balanced", "sound", "main"})


def origin_path(loop: str = "cartoon", *, config: dict[str, Any] | None = None) -> Path:
    env = (os.environ.get("LOOP_ORIGIN_PATH") or "").strip()
    if env and loop == "cartoon":
        return Path(env)
    from .registry import get_registry_dir
    return get_registry_dir(config) / "loop_origins" / f"{loop}.json"


def load_loop_origin(loop: str = "cartoon", *, config: dict[str, Any] | None = None) -> dict[str, Any] | None:
    path = origin_path(loop, config=config)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_loop_origin(
    recipe: dict[str, Any],
    *,
    loop: str = "cartoon",
    config: dict[str, Any] | None = None,
) -> Path:
    path = origin_path(loop, config=config)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(recipe, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _quantize_palette(frames: list[np.ndarray], *, n: int = 8, step: int = 16) -> list[dict[str, int]]:
    """Most frequent quantized RGBs, skipping near-black ink."""
    counts: dict[tuple[int, int, int], int] = {}
    for frame in frames[:48]:
        if frame.ndim != 3 or frame.shape[-1] < 3:
            continue
        small = frame[::4, ::4, :3].astype(np.int32)
        q = (small // step) * step
        ink = 0.299 * q[..., 0] + 0.587 * q[..., 1] + 0.114 * q[..., 2] < 40
        flat = q.reshape(-1, 3)
        mask = ~ink.reshape(-1)
        for r, g, b in flat[mask]:
            key = (int(r), int(g), int(b))
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])[: max(3, n)]
    return [{"r": r, "g": g, "b": b} for (r, g, b), _ in ranked]


def _unique_quantized(frames: list[np.ndarray], *, step: int = 16) -> int:
    seen: set[tuple[int, int, int]] = set()
    for frame in frames[:24]:
        if frame.ndim != 3:
            continue
        q = (frame[::6, ::6, :3].astype(np.int32) // step) * step
        for r, g, b in q.reshape(-1, 3):
            seen.add((int(r), int(g), int(b)))
    return len(seen)


def _ink_frac(frames: list[np.ndarray]) -> float:
    if not frames:
        return 0.0
    fracs = []
    for frame in frames[:12]:
        luma = 0.299 * frame[..., 0] + 0.587 * frame[..., 1] + 0.114 * frame[..., 2]
        fracs.append(float((luma < 50).mean()))
    return float(np.mean(fracs)) if fracs else 0.0


def _hold_snap(frames: list[np.ndarray], fps: float) -> dict[str, float]:
    if len(frames) < 3:
        return {"hold_frac": 0.85, "snap_frac": 0.08, "hold_seconds": 1.0, "snap_seconds": 0.2}
    diffs = [frame_difference(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    med = float(np.median(diffs))
    thr = max(med * 2.2, 1.8)
    hold_mask = [d < thr for d in diffs]
    hold_frac = sum(1 for h in hold_mask if h) / max(1, len(hold_mask))
    snap_frac = 1.0 - hold_frac

    def _mean_run(mask: list[bool], want: bool) -> float:
        runs: list[int] = []
        n = 0
        for v in mask:
            if v is want:
                n += 1
            elif n:
                runs.append(n)
                n = 0
        if n:
            runs.append(n)
        return float(np.mean(runs)) if runs else 1.0

    hold_s = _mean_run(hold_mask, True) / max(1.0, fps)
    snap_s = _mean_run(hold_mask, False) / max(1.0, fps)
    return {
        "hold_frac": round(hold_frac, 4),
        "snap_frac": round(snap_frac, 4),
        "hold_seconds": round(max(0.15, min(2.5, hold_s)), 3),
        "snap_seconds": round(max(0.05, min(0.6, snap_s)), 3),
    }


def measure_frames(
    frames: list[np.ndarray],
    *,
    fps: float = 24.0,
    loop: str = "cartoon",
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a loop-origin recipe from decoded frames. No source pixels are kept."""
    timing = _hold_snap(frames, float(fps) or 24.0)
    palette = _quantize_palette(frames)
    return {
        "loop": loop if loop in _VALID_LOOPS else "cartoon",
        "source": source or {},
        "note": "Measurements only; source frames are not stored or replayed.",
        "fps": round(float(fps) or 24.0, 3),
        "frame_count": len(frames),
        "palette": palette,
        "unique_colors_q16": _unique_quantized(frames),
        "ink_frac": round(_ink_frac(frames), 4),
        **timing,
        "style": "cartoon" if loop == "cartoon" else None,
        "render_engine": "cel" if loop == "cartoon" else None,
    }


def measure_reference_video(
    video_path: str | Path,
    *,
    loop: str = "cartoon",
    max_frames: int = 72,
    sample_every: int = 1,
) -> dict[str, Any]:
    from .extractor_per_instance import _read_frames

    path = Path(video_path)
    frames, fps, _w, _h = _read_frames(path, max_frames=max_frames, sample_every=sample_every)
    digest = hashlib.sha256(path.read_bytes()[: 1024 * 256]).hexdigest()[:16]
    source = {
        "filename": path.name,
        "bytes": path.stat().st_size,
        "sha256_head": digest,
    }
    return measure_frames(frames, fps=fps, loop=loop, source=source)


def _attach_palette_names(recipe: dict[str, Any], novel_colors: list[dict[str, Any]]) -> None:
    named = [c for c in (novel_colors or []) if isinstance(c, dict) and c.get("name")]
    for swatch in recipe.get("palette") or []:
        if not isinstance(swatch, dict):
            continue
        best = None
        best_d = 1e18
        sr, sg, sb = int(swatch.get("r") or 0), int(swatch.get("g") or 0), int(swatch.get("b") or 0)
        for c in named:
            d = (sr - int(c.get("r") or 0)) ** 2 + (sg - int(c.get("g") or 0)) ** 2 + (sb - int(c.get("b") or 0)) ** 2
            if d < best_d:
                best_d = d
                best = c
        if best and best_d < 48 ** 2:
            swatch["name"] = str(best.get("name"))


def ingest_reference_video(
    video_path: str | Path,
    *,
    loop: str = "cartoon",
    api_base: str | None = None,
    config: dict[str, Any] | None = None,
    prompt: str | None = None,
) -> dict[str, Any]:
    """
    Measure a reference clip, grow registries from it, save the loop origin recipe.

    Use a clip you have rights to (your own, CC0, public domain). Do not ingest
    a copyrighted show in order to copy it.
    """
    path = Path(video_path)
    loop = loop.strip().lower() or "cartoon"
    if loop not in _VALID_LOOPS:
        loop = "cartoon"
    label = prompt or f"reference origin for {loop} loop"
    recipe = measure_reference_video(path, loop=loop)
    from .growth_per_instance import grow_all_from_video

    added, novel = grow_all_from_video(
        path,
        prompt=label,
        config=config,
        sample_every=1,
        window_seconds=1.0,
        collect_novel_for_sync=True,
        extraction_focus="all",
        static_focus="both",
    )
    _attach_palette_names(recipe, novel.get("static_colors") or [])
    recipe["growth_added"] = {k: v for k, v in added.items() if v}
    out = save_loop_origin(recipe, loop=loop, config=config)
    recipe["saved_to"] = str(out)
    if api_base:
        from .remote_sync import post_all_discoveries

        post_all_discoveries(
            api_base.rstrip("/"),
            novel.get("static_colors") or [],
            novel.get("static_sound") or [],
            novel,
            novel.get("narrative") if isinstance(novel.get("narrative"), dict) else None,
        )
        recipe["synced"] = True
    return recipe
