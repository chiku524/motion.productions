"""
Extract every aspect within video files — base knowledge extraction.
Uses only our algorithms; no external model.
"""
from pathlib import Path

import numpy as np

from ..analysis.metrics import (
    brightness_and_contrast,
    color_histogram,
    color_variance,
    dominant_colors,
    edge_density,
    frame_difference,
    gradient_strength,
    saturation_and_hue,
    spatial_variance,
    center_of_mass,
)
from .schema import BaseKnowledgeExtract


def _closest_palette(r: float, g: float, b: float) -> tuple[str, float]:
    """Find which of our palettes (by mean color) is closest to (r,g,b)."""
    from ..procedural.data.palettes import PALETTES
    best_name = "default"
    best_dist = 1e9
    for name, colors in PALETTES.items():
        mr = sum(c[0] for c in colors) / len(colors)
        mg = sum(c[1] for c in colors) / len(colors)
        mb = sum(c[2] for c in colors) / len(colors)
        d = (r - mr) ** 2 + (g - mg) ** 2 + (b - mb) ** 2
        if d < best_dist:
            best_dist = d
            best_name = name
    return best_name, float(best_dist ** 0.5)


def _motion_trend(per_frame_motion: list[float]) -> str:
    """Determine if motion is increasing, decreasing, or steady over time."""
    if len(per_frame_motion) < 3:
        return "steady"
    n = len(per_frame_motion)
    first_third = sum(per_frame_motion[: n // 3]) / max(1, n // 3)
    last_third = sum(per_frame_motion[-n // 3 :]) / max(1, n // 3)
    diff = last_third - first_third
    if diff > 2.0:
        return "increasing"
    if diff < -2.0:
        return "decreasing"
    return "steady"


def _luminance_balance(frame: np.ndarray) -> float:
    """0 = dark-biased, 0.5 = balanced, 1 = light-biased."""
    bc = brightness_and_contrast(frame)
    b = bc["brightness"]
    return min(1.0, max(0.0, b / 255.0))


def extract_from_video(
    video_path: str | Path,
    *,
    max_frames: int = 60,
    sample_every: int = 1,
    bins: int = 16,
) -> BaseKnowledgeExtract:
    """
    Extract every aspect within a video file.
    Returns a comprehensive BaseKnowledgeExtract.
    """
    path = Path(video_path)
    if not path.exists():
        raise FileNotFoundError(f"Video not found: {path}")

    try:
        import imageio
    except ImportError:
        raise ImportError(
            "extract_from_video needs imageio. pip install imageio imageio-ffmpeg"
        ) from None

    reader = imageio.get_reader(str(path))
    try:
        meta = reader.get_meta_data()
    except Exception:
        meta = {}
    fps = meta.get("fps", 24.0)
    size = meta.get("size")
    width = size[0] if size and isinstance(size, (tuple, list)) and len(size) >= 2 else None
    height = size[1] if size and isinstance(size, (tuple, list)) and len(size) >= 2 else None

    frames_list: list = []
    for i, fr in enumerate(reader):
        if i >= max_frames * max(1, sample_every):
            break
        if i % sample_every == 0:
            frames_list.append(fr)
    reader.close()

    if not frames_list:
        raise ValueError(f"No frames could be read from {path}")

    frames = [np.asarray(f) for f in frames_list]
    if frames[0].ndim == 2:
        frames = [np.stack([f, f, f], axis=-1) for f in frames]
    elif frames[0].shape[-1] == 4:
        frames = [f[:, :, :3].copy() for f in frames]

    # Infer width/height from first frame if meta missing
    h, w = frames[0].shape[:2]
    width = width if width is not None else w
    height = height if height is not None else h

    n = len(frames)
    duration_seconds = n / fps if fps and n else 0.0

    # Per-frame metrics
    per_brightness: list[float] = []
    per_motion: list[float] = []
    per_saturation: list[float] = []
    per_hue: list[float] = []
    per_color_var: list[float] = []
    hist_sum_r = None
    hist_sum_g = None
    hist_sum_b = None

    mid_idx = len(frames) // 2
    edge_den = 0.0
    spat_var = 0.0
    grad_str = 0.0
    cx, cy = 0.5, 0.5
    lum_bal = 0.5

    for i, fr in enumerate(frames):
        bc = brightness_and_contrast(fr)
        per_brightness.append(bc["brightness"])
        sh = saturation_and_hue(fr)
        per_saturation.append(sh["saturation"])
        per_hue.append(sh["hue"])
        per_color_var.append(color_variance(fr))

        if i > 0:
            diff = frame_difference(frames[i - 1], fr)
            per_motion.append(diff)

        h = color_histogram(fr, bins=bins)
        if hist_sum_r is None:
            hist_sum_r = h["r"].copy()
            hist_sum_g = h["g"].copy()
            hist_sum_b = h["b"].copy()
        else:
            hist_sum_r += h["r"]
            hist_sum_g += h["g"]
            hist_sum_b += h["b"]

        # Graphics: sample from middle frame
        if i == mid_idx:
            edge_den = edge_density(fr)
            spat_var = spatial_variance(fr)
            grad_str = gradient_strength(fr)
            cx, cy = center_of_mass(fr)
            lum_bal = _luminance_balance(fr)

    # Aggregate
    mean_brightness = sum(per_brightness) / len(per_brightness) if per_brightness else 0.0
    mean_contrast = brightness_and_contrast(frames[mid_idx])["contrast"]
    mean_saturation = sum(per_saturation) / len(per_saturation) if per_saturation else 0.0
    mean_hue = sum(per_hue) / len(per_hue) if per_hue else 0.0
    brightness_std_over_time = float(np.std(per_brightness)) if per_brightness else 0.0
    color_std_over_time = float(np.std(per_color_var)) if per_color_var else 0.0

    motion_level = sum(per_motion) / len(per_motion) if per_motion else 0.0
    motion_std = float(np.std(per_motion)) if per_motion else 0.0
    motion_trend = _motion_trend(per_motion)

    dom = dominant_colors(frames[mid_idx], n=1)
    dominant_rgb = dom[0] if dom else (0.0, 0.0, 0.0)
    closest_palette, palette_distance = _closest_palette(*dominant_rgb)

    # Normalize center of mass to 0-1 (frame coords are 0..w-1, 0..h-1)
    cx_norm = cx / w if w else 0.5
    cy_norm = cy / h if h else 0.5

    busyness = 0.5 * edge_den + 0.5 * spat_var

    total = max(hist_sum_r.sum() + hist_sum_g.sum() + hist_sum_b.sum(), 1e-9)
    hist_r_norm = (hist_sum_r / total).tolist()
    hist_g_norm = (hist_sum_g / total).tolist()
    hist_b_norm = (hist_sum_b / total).tolist()

    return BaseKnowledgeExtract(
        path=str(path.resolve()),
        width=width,
        height=height,
        fps=fps,
        duration_seconds=duration_seconds,
        num_frames_sampled=n,
        mean_brightness=mean_brightness,
        mean_contrast=mean_contrast,
        mean_saturation=mean_saturation,
        mean_hue=mean_hue,
        dominant_color_rgb=dominant_rgb,
        histogram_r=hist_r_norm,
        histogram_g=hist_g_norm,
        histogram_b=hist_b_norm,
        color_variance=float(np.mean(per_color_var)) if per_color_var else 0.0,
        color_std_over_time=color_std_over_time,
        edge_density=edge_den,
        spatial_variance=spat_var,
        gradient_strength=grad_str,
        busyness=busyness,
        motion_level=motion_level,
        motion_std=motion_std,
        motion_trend=motion_trend,
        motion_per_frame=per_motion,
        brightness_per_frame=per_brightness[:60],
        brightness_std_over_time=brightness_std_over_time,
        center_of_mass_x=cx_norm,
        center_of_mass_y=cy_norm,
        luminance_balance=lum_bal,
        closest_palette=closest_palette,
        palette_distance=palette_distance,
    )
