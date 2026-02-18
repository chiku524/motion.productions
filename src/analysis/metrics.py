"""
Pure algorithms for interpreting video frames: color, motion, consistency.
No external model — our scripts only.
"""
from typing import Any

import numpy as np


def color_histogram(frame: np.ndarray, bins: int = 16) -> dict[str, np.ndarray]:
    """
    Per-channel RGB histogram (0..255 binned). Returns dict with 'r', 'g', 'b'.
    """
    if frame.ndim != 3 or frame.shape[-1] < 3:
        raise ValueError("Expected RGB frame (H, W, 3)")
    r = np.histogram(frame[:, :, 0].ravel(), bins=bins, range=(0, 256))[0].astype(np.float64)
    g = np.histogram(frame[:, :, 1].ravel(), bins=bins, range=(0, 256))[0].astype(np.float64)
    b = np.histogram(frame[:, :, 2].ravel(), bins=bins, range=(0, 256))[0].astype(np.float64)
    total = max(r.sum() + g.sum() + b.sum(), 1e-9)
    return {
        "r": r / total,
        "g": g / total,
        "b": b / total,
    }


def dominant_colors(frame: np.ndarray, n: int = 3) -> list[tuple[float, float, float]]:
    """
    Approximate dominant colors by averaging in grid cells (spatial downscale then mean).
    Returns list of (R, G, B) clamped to 0–255.
    """
    h, w = frame.shape[:2]
    if frame.ndim != 3:
        return []
    step = max(1, min(h, w) // 8)
    r = float(np.clip(frame[::step, ::step, 0].astype(np.float64).mean(), 0, 255))
    g = float(np.clip(frame[::step, ::step, 1].astype(np.float64).mean(), 0, 255))
    b = float(np.clip(frame[::step, ::step, 2].astype(np.float64).mean(), 0, 255))
    return [(r, g, b)]


def frame_difference(frame_a: np.ndarray, frame_b: np.ndarray) -> float:
    """
    Mean absolute difference between two RGB frames (resized to same size if needed).
    Used as a simple "motion" signal between consecutive frames.
    """
    ha, wa = frame_a.shape[:2]
    hb, wb = frame_b.shape[:2]
    if ha != hb or wa != wb:
        min_h, min_w = min(ha, hb), min(wa, wb)
        frame_a = frame_a[:min_h, :min_w].astype(np.float64)
        frame_b = frame_b[:min_h, :min_w].astype(np.float64)
    else:
        frame_a = frame_a.astype(np.float64)
        frame_b = frame_b.astype(np.float64)
    return float(np.abs(frame_a - frame_b).mean())


def brightness_and_contrast(frame: np.ndarray) -> dict[str, float]:
    """Mean brightness (0–255) and std (contrast)."""
    if frame.ndim != 3:
        return {"brightness": 0.0, "contrast": 0.0}
    gray = frame.astype(np.float64)
    gray = 0.299 * gray[:, :, 0] + 0.587 * gray[:, :, 1] + 0.114 * gray[:, :, 2]
    return {
        "brightness": float(gray.mean()),
        "contrast": float(gray.std()),
    }


def saturation_and_hue(frame: np.ndarray) -> dict[str, float]:
    """
    Mean saturation (0–1) and mean hue (0–360) in HSV space.
    Uses precise RGB→HSV conversion.
    """
    if frame.ndim != 3 or frame.shape[-1] < 3:
        return {"saturation": 0.0, "hue": 0.0}
    r = frame[:, :, 0].astype(np.float64) / 255.0
    g = frame[:, :, 1].astype(np.float64) / 255.0
    b = frame[:, :, 2].astype(np.float64) / 255.0
    cmax = np.maximum(np.maximum(r, g), b)
    cmin = np.minimum(np.minimum(r, g), b)
    delta = cmax - cmin
    delta_safe = np.maximum(delta, 1e-9)  # avoid division by zero (np.where evaluates both branches)
    # Divide only where cmax > 0 and finite to avoid RuntimeWarning (invalid value in divide)
    valid = (cmax > 1e-9) & np.isfinite(cmax) & np.isfinite(delta)
    sat = np.zeros_like(r)
    np.divide(delta, cmax, out=sat, where=valid)
    hue = np.zeros_like(r)
    mask_r = (cmax == r) & (delta > 1e-9)
    mask_g = (cmax == g) & (delta > 1e-9)
    mask_b = (cmax == b) & (delta > 1e-9)
    hue = np.where(mask_r, 60 * (((g - b) / delta_safe) % 6), hue)
    hue = np.where(mask_g, 60 * ((b - r) / delta_safe + 2), hue)
    hue = np.where(mask_b, 60 * ((r - g) / delta_safe + 4), hue)
    hue = (hue + 360) % 360
    return {
        "saturation": float(sat.mean()),
        "hue": float(hue.mean()),
    }


def edge_density(frame: np.ndarray) -> float:
    """
    High-frequency energy as a proxy for edge density.
    Uses Sobel-like gradient magnitude (simple, precise).
    """
    if frame.ndim != 3:
        return 0.0
    gray = frame.astype(np.float64)
    gray = 0.299 * gray[:, :, 0] + 0.587 * gray[:, :, 1] + 0.114 * gray[:, :, 2]
    h, w = gray.shape
    gx = np.zeros_like(gray)
    gy = np.zeros_like(gray)
    gx[:, 1:-1] = gray[:, 2:] - gray[:, :-2]
    gy[1:-1, :] = gray[2:, :] - gray[:-2, :]
    mag = np.sqrt(gx * gx + gy * gy)
    return float(mag.mean() / 255.0)


def spatial_variance(frame: np.ndarray) -> float:
    """
    Variance of luminance across spatial blocks (how uniform vs. varied).
    Higher = more spatial variation.
    """
    if frame.ndim != 3:
        return 0.0
    gray = frame.astype(np.float64)
    gray = 0.299 * gray[:, :, 0] + 0.587 * gray[:, :, 1] + 0.114 * gray[:, :, 2]
    block_h, block_w = max(1, gray.shape[0] // 8), max(1, gray.shape[1] // 8)
    blocks = gray[: block_h * (gray.shape[0] // block_h), : block_w * (gray.shape[1] // block_w)]
    blocks = blocks.reshape(-1, block_h * block_w)
    block_means = blocks.mean(axis=1)
    return float(np.var(block_means) / (255.0 * 255.0))


def gradient_strength(frame: np.ndarray) -> float:
    """
    Mean magnitude of luminance gradients (horizontal + vertical).
    """
    if frame.ndim != 3:
        return 0.0
    gray = frame.astype(np.float64)
    gray = 0.299 * gray[:, :, 0] + 0.587 * gray[:, :, 1] + 0.114 * gray[:, :, 2]
    dx = np.abs(gray[:, 1:] - gray[:, :-1])
    dy = np.abs(gray[1:, :] - gray[:-1, :])
    return float((dx.mean() + dy.mean()) / (2 * 255.0))


def gradient_direction(frame: np.ndarray) -> str:
    """
    Dominant gradient orientation from luminance: vertical, horizontal, or angled.
    Used for dynamic registry (non-pure blend over window).
    """
    if frame.ndim != 3:
        return "angled"
    gray = frame.astype(np.float64)
    gray = 0.299 * gray[:, :, 0] + 0.587 * gray[:, :, 1] + 0.114 * gray[:, :, 2]
    dx = np.abs(gray[:, 1:] - gray[:, :-1])
    dy = np.abs(gray[1:, :] - gray[:-1, :])
    mean_dx = float(dx.mean())
    mean_dy = float(dy.mean())
    if mean_dy > mean_dx * 1.2:
        return "vertical"
    if mean_dx > mean_dy * 1.2:
        return "horizontal"
    return "angled"


def center_of_mass(frame: np.ndarray) -> tuple[float, float]:
    """
    Luminance-weighted center of mass (x, y) normalized to 0–1.
    """
    if frame.ndim != 3:
        return 0.5, 0.5
    gray = frame.astype(np.float64)
    gray = 0.299 * gray[:, :, 0] + 0.587 * gray[:, :, 1] + 0.114 * gray[:, :, 2]
    weight = gray + 1e-9
    total = float(weight.sum())
    if total < 1e-9:
        return 0.5, 0.5
    h, w = int(gray.shape[0]), int(gray.shape[1])
    if w <= 0 or h <= 0:
        return 0.5, 0.5
    yy, xx = np.ogrid[:h, :w]
    cx = float((xx * weight).sum() / total / w)
    cy = float((yy * weight).sum() / total / h)
    return cx, cy


def color_variance(frame: np.ndarray) -> float:
    """
    Variance of RGB values across pixels (color spread).
    """
    if frame.ndim != 3 or frame.shape[-1] < 3:
        return 0.0
    flat = frame[:, :, :3].reshape(-1, 3).astype(np.float64)
    return float(np.var(flat) / (255.0 * 255.0))
