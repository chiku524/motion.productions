"""
Perceptual color space (Oklab) for look-faithful blending and interpolation.

Linear RGB mixes of complementary hues collapse through gray, so sunset, ocean,
and neon palettes read muddy. Oklab keeps chroma on the intended hue path.
Formulas: Björn Ottosson, public domain.
"""
from __future__ import annotations

from typing import Sequence


def _cbrt(x: float) -> float:
    if x <= 0.0:
        return 0.0
    return x ** (1.0 / 3.0)


def _srgb_to_linear(c: float) -> float:
    c = max(0.0, min(1.0, c))
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_srgb(c: float) -> float:
    if c <= 0.0031308:
        return 12.92 * c
    return 1.055 * (max(0.0, c) ** (1.0 / 2.4)) - 0.055


def _channel_01(v: float) -> float:
    """Accept 0–1 or 0–255 channel values."""
    x = float(v)
    if x > 1.0:
        return max(0.0, min(1.0, x / 255.0))
    return max(0.0, min(1.0, x))


def rgb_to_oklab(rgb: Sequence[float]) -> tuple[float, float, float]:
    """sRGB 0–255 or 0–1 → Oklab (L, a, b)."""
    r = _srgb_to_linear(_channel_01(rgb[0]))
    g = _srgb_to_linear(_channel_01(rgb[1]))
    b = _srgb_to_linear(_channel_01(rgb[2]))
    l_ = _cbrt(0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b)
    m_ = _cbrt(0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b)
    s_ = _cbrt(0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    b2 = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return (L, a, b2)


def oklab_to_rgb(lab: Sequence[float]) -> tuple[int, int, int]:
    """Oklab → sRGB 0–255 ints."""
    L, a, b = float(lab[0]), float(lab[1]), float(lab[2])
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_
    r = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    b2 = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return (
        max(0, min(255, int(_linear_to_srgb(r) * 255.0 + 0.5))),
        max(0, min(255, int(_linear_to_srgb(g) * 255.0 + 0.5))),
        max(0, min(255, int(_linear_to_srgb(b2) * 255.0 + 0.5))),
    )


def lerp_rgb_oklab(
    rgb_a: Sequence[float],
    rgb_b: Sequence[float],
    weight: float,
) -> tuple[int, int, int]:
    """Interpolate two colors in Oklab (weight 0 = a, 1 = b)."""
    w = max(0.0, min(1.0, float(weight)))
    La, aa, ba = rgb_to_oklab(rgb_a)
    Lb, ab, bb = rgb_to_oklab(rgb_b)
    return oklab_to_rgb((
        La * (1.0 - w) + Lb * w,
        aa * (1.0 - w) + ab * w,
        ba * (1.0 - w) + bb * w,
    ))


def oklab_distance(rgb_a: Sequence[float], rgb_b: Sequence[float]) -> float:
    """Squared Oklab distance — smaller means a closer perceptual match."""
    La, aa, ba = rgb_to_oklab(rgb_a)
    Lb, ab, bb = rgb_to_oklab(rgb_b)
    dL, da, db = La - Lb, aa - ab, ba - bb
    return dL * dL + da * da + db * db


def nearest_palette_color(
    target: Sequence[float],
    palette: Sequence[Sequence[float]],
) -> tuple[int, int, int]:
    """Pick the palette entry closest to target in Oklab."""
    if not palette:
        return (int(target[0]), int(target[1]), int(target[2]))
    best = palette[0]
    best_d = float("inf")
    for c in palette:
        d = oklab_distance(target, c)
        if d < best_d:
            best_d = d
            best = c
    return (int(best[0]), int(best[1]), int(best[2]))


def lerp_palette_oklab_arrays(
    palette: Sequence[Sequence[float]],
    i0: "object",
    i1: "object",
    frac: "object",
) -> tuple["object", "object", "object"]:
    """
    Vectorized Oklab lerp of a small palette across HxW index maps.
    i0, i1: int arrays; frac: float array in 0–1. Returns (r, g, b) float 0–255.
    """
    import numpy as np

    labs = np.array([rgb_to_oklab(c) for c in palette], dtype=np.float32)
    f = np.asarray(frac, dtype=np.float32)
    ia = np.asarray(i0)
    ib = np.asarray(i1)
    L = labs[ia, 0] * (1.0 - f) + labs[ib, 0] * f
    a = labs[ia, 1] * (1.0 - f) + labs[ib, 1] * f
    b = labs[ia, 2] * (1.0 - f) + labs[ib, 2] * f
    return _oklab_to_rgb_arrays(L, a, b)


def _oklab_to_rgb_arrays(L, a, b):
    import numpy as np

    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_
    lr = +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    lg = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    lb = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    return (
        np.clip(_linear_to_srgb_np(lr) * 255.0, 0, 255),
        np.clip(_linear_to_srgb_np(lg) * 255.0, 0, 255),
        np.clip(_linear_to_srgb_np(lb) * 255.0, 0, 255),
    )


def palette_stops_from_rgb(r: float, g: float, b: float) -> list[tuple[int, int, int]]:
    """Four gradient stops around one registry RGB so creation can use a named color as a palette."""
    ri = max(0, min(255, int(round(float(r)))))
    gi = max(0, min(255, int(round(float(g)))))
    bi = max(0, min(255, int(round(float(b)))))
    dark = (max(0, ri // 2), max(0, gi // 2), max(0, bi // 2))
    mid = (ri, gi, bi)
    light = (
        min(255, ri + (255 - ri) // 2),
        min(255, gi + (255 - gi) // 2),
        min(255, bi + (255 - bi) // 2),
    )
    return [dark, mid, mid, light]


def _linear_to_srgb_np(c):
    import numpy as np

    c = np.maximum(c, 0.0)
    return np.where(
        c <= 0.0031308,
        12.92 * c,
        1.055 * np.power(c, 1.0 / 2.4) - 0.055,
    )
