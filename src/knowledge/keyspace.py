"""
Versioned exact key spaces (python half; the Worker mirrors it in cloudflare/src/soundKeyspace.ts).

Sound v2 ("sound.L1") records what the extractor actually MEASURES per 1/24 s frame instead of the
three coarse v1 fields (amplitude, 3-bin tone, 10 timbre labels):

    amp(12 log bins) x band(8 octave bins) x flatness(4) x attack(4) x zcr(4) = 6144 cells

A cell has a compact deterministic key, e.g. ``s2.07-3-1-2-0`` (fields in that order), and a mixed-radix
ordinal (cell id) 0..6143. Bin edges are frozen under ``SOUND_V2_VERSION``; changing any edge needs a new
version prefix, never an in-place edit. v1 keys (``0.12_mid_hum``) are untouched and keep working.

Pure functions, stdlib only, no I/O. Parity vectors live in tests/vectors/sound_v2_vectors.json and are
asserted by both pytest and the Worker tests.
"""
from __future__ import annotations

import math
import re
from typing import Any

SOUND_V2_VERSION = 2
SOUND_V2_PREFIX = "s2."

# Amplitude: normalised RMS 0..1. Bin 0 is everything below A_MIN (-60 dBFS); bins 1..11 are equal 5.45 dB
# steps (log scale) from A_MIN up to 1.0.
SOUND_V2_AMP_MIN = 0.001
SOUND_V2_AMP_BINS = 12
# Octave bands over the measured peak frequency (Hz): [0,100) [100,200) ... [6400, inf)
SOUND_V2_BAND_EDGES: tuple[float, ...] = (100.0, 200.0, 400.0, 800.0, 1600.0, 3200.0, 6400.0)
SOUND_V2_BAND_BINS = len(SOUND_V2_BAND_EDGES) + 1  # 8
# Spectral flatness 0..1 (tonal -> noisy)
SOUND_V2_FLAT_EDGES: tuple[float, ...] = (0.15, 0.30, 0.50)
# Attack ratio 0..1 = first-half RMS share (<0.35 rising, <0.5 steady, <0.65 decaying, else impulsive)
SOUND_V2_ATTACK_EDGES: tuple[float, ...] = (0.35, 0.50, 0.65)
# Zero-crossing rate 0..1
SOUND_V2_ZCR_EDGES: tuple[float, ...] = (0.02, 0.06, 0.15)

SOUND_V2_RADICES: tuple[int, ...] = (SOUND_V2_AMP_BINS, SOUND_V2_BAND_BINS, 4, 4, 4)
SOUND_V2_SPACE_SIZE = 12 * 8 * 4 * 4 * 4  # 6144
SOUND_V2_FIELDS = ("amp", "band", "flat", "attack", "zcr")
SOUND_V2_ATTACK_LABELS = ("rising", "steady", "decaying", "impulsive")
SOUND_V2_FLAT_LABELS = ("tonal", "mostly_tonal", "mixed", "noisy")
SOUND_V2_ZCR_LABELS = ("slow", "low", "mid", "busy")

_KEY_RE = re.compile(r"^s2\.(\d{2})-(\d)-(\d)-(\d)-(\d)$")


def _edge_bin(value: float, edges: tuple[float, ...]) -> int:
    for i, e in enumerate(edges):
        if value < e:
            return i
    return len(edges)


def _num(v: Any, default: float = 0.0) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def amp_bin(amplitude: Any) -> int:
    a = _num(amplitude)
    if a < SOUND_V2_AMP_MIN:
        return 0
    span = math.log(1.0 / SOUND_V2_AMP_MIN)
    idx = 1 + int((math.log(min(a, 1.0) / SOUND_V2_AMP_MIN) / span) * (SOUND_V2_AMP_BINS - 1))
    return min(SOUND_V2_AMP_BINS - 1, idx)


def band_bin(peak_hz: Any) -> int:
    return _edge_bin(max(0.0, _num(peak_hz)), SOUND_V2_BAND_EDGES)


def flat_bin(flatness: Any) -> int:
    return _edge_bin(_num(flatness, 0.5), SOUND_V2_FLAT_EDGES)


def attack_bin(attack_ratio: Any) -> int:
    return _edge_bin(_num(attack_ratio), SOUND_V2_ATTACK_EDGES)


def zcr_bin(zcr: Any) -> int:
    return _edge_bin(_num(zcr), SOUND_V2_ZCR_EDGES)


def sound_v2_bins(
    amplitude: Any, peak_hz: Any, spectral_flatness: Any, attack_ratio: Any, zcr: Any
) -> tuple[int, int, int, int, int]:
    return (
        amp_bin(amplitude),
        band_bin(peak_hz),
        flat_bin(spectral_flatness),
        attack_bin(attack_ratio),
        zcr_bin(zcr),
    )


def sound_v2_ordinal(bins: tuple[int, ...]) -> int:
    """Mixed-radix ordinal (cell id) of a bin tuple; most significant field = amp."""
    if len(bins) != len(SOUND_V2_RADICES):
        raise ValueError("expected 5 bins")
    n = 0
    for b, radix in zip(bins, SOUND_V2_RADICES):
        if not 0 <= int(b) < radix:
            raise ValueError(f"bin {b} out of range for radix {radix}")
        n = n * radix + int(b)
    return n


def decode_sound_v2_ordinal(ordinal: int) -> tuple[int, int, int, int, int]:
    if not 0 <= int(ordinal) < SOUND_V2_SPACE_SIZE:
        raise ValueError(f"ordinal {ordinal} outside 0..{SOUND_V2_SPACE_SIZE - 1}")
    n = int(ordinal)
    out: list[int] = []
    for radix in reversed(SOUND_V2_RADICES):
        out.append(n % radix)
        n //= radix
    return tuple(reversed(out))  # type: ignore[return-value]


def sound_v2_key_from_bins(bins: tuple[int, ...]) -> str:
    a, b, f, k, z = (int(x) for x in bins)
    sound_v2_ordinal((a, b, f, k, z))  # validates ranges
    return f"{SOUND_V2_PREFIX}{a:02d}-{b}-{f}-{k}-{z}"


def sound_v2_key(
    amplitude: Any, peak_hz: Any, spectral_flatness: Any, attack_ratio: Any, zcr: Any
) -> str:
    return sound_v2_key_from_bins(sound_v2_bins(amplitude, peak_hz, spectral_flatness, attack_ratio, zcr))


def is_sound_v2_key(key: Any) -> bool:
    return isinstance(key, str) and _KEY_RE.match(key) is not None and _bins_valid(key)


def _bins_valid(key: str) -> bool:
    m = _KEY_RE.match(key)
    return bool(m) and all(int(g) < r for g, r in zip(m.groups(), SOUND_V2_RADICES))


def parse_sound_v2_key(key: str) -> tuple[int, int, int, int, int]:
    m = _KEY_RE.match(key or "")
    if not m or not _bins_valid(key):
        raise ValueError(f"not a sound v2 key: {key!r}")
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def sound_v2_key_to_ordinal(key: str) -> int:
    return sound_v2_ordinal(parse_sound_v2_key(key))


def sound_v2_ordinal_to_key(ordinal: int) -> str:
    return sound_v2_key_from_bins(decode_sound_v2_ordinal(ordinal))


def sound_v2_cell_id(key_or_ordinal: Any) -> str:
    """Stable cell id string, e.g. 'sound.L1#00417'."""
    n = key_or_ordinal if isinstance(key_or_ordinal, int) else sound_v2_key_to_ordinal(str(key_or_ordinal))
    return f"sound.L1#{int(n):05d}"


def sound_v2_amp_range(bin_idx: int) -> tuple[float, float]:
    """[lo, hi) normalised-RMS range covered by an amplitude bin."""
    if bin_idx <= 0:
        return 0.0, SOUND_V2_AMP_MIN
    span = math.log(1.0 / SOUND_V2_AMP_MIN)
    step = span / (SOUND_V2_AMP_BINS - 1)
    lo = SOUND_V2_AMP_MIN * math.exp((bin_idx - 1) * step)
    hi = SOUND_V2_AMP_MIN * math.exp(bin_idx * step)
    return lo, min(1.0, hi)


def _range_of(edges: tuple[float, ...], idx: int, top: float) -> tuple[float, float]:
    lo = 0.0 if idx == 0 else edges[idx - 1]
    hi = edges[idx] if idx < len(edges) else top
    return lo, hi


def sound_v2_cell_center(ordinal: int) -> dict[str, float]:
    """Representative measured values (bin centres) for synthesising a cell. Not an inverse guarantee."""
    a, b, f, k, z = decode_sound_v2_ordinal(ordinal)
    alo, ahi = sound_v2_amp_range(a)
    blo, bhi = _range_of(SOUND_V2_BAND_EDGES, b, 12800.0)
    flo, fhi = _range_of(SOUND_V2_FLAT_EDGES, f, 1.0)
    klo, khi = _range_of(SOUND_V2_ATTACK_EDGES, k, 1.0)
    zlo, zhi = _range_of(SOUND_V2_ZCR_EDGES, z, 0.4)
    return {
        "amplitude": math.sqrt(max(alo, 1e-6) * ahi) if a else 0.0005,
        "peak_hz": math.sqrt(max(blo, 50.0) * bhi) if b else 70.0,
        "spectral_flatness": (flo + fhi) / 2,
        "attack_ratio": (klo + khi) / 2,
        "zcr": (zlo + zhi) / 2,
    }


def sound_v2_cell_summary(key: str) -> dict[str, Any]:
    """Compact, JSON-safe description stored in the payload's depth_breakdown (no extra rows)."""
    bins = parse_sound_v2_key(key)
    return {
        "version": SOUND_V2_VERSION,
        "space": "sound.L1",
        "cell_id": sound_v2_cell_id(key),
        "ordinal": sound_v2_ordinal(bins),
        "bins": dict(zip(SOUND_V2_FIELDS, bins)),
    }


def sound_v2_from_segment(sound: dict[str, Any]) -> str | None:
    """v2 key for one extracted audio segment; None if the segment lacks the measured features."""
    if not sound or "spectral_flatness" not in sound or "attack_ratio" not in sound or "zcr" not in sound:
        return None
    if "peak_hz" not in sound:
        return None
    return sound_v2_key(
        sound.get("amplitude") if sound.get("amplitude") is not None else sound.get("weight"),
        sound.get("peak_hz"),
        sound.get("spectral_flatness"),
        sound.get("attack_ratio"),
        sound.get("zcr"),
    )