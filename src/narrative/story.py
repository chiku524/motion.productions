"""
Story beats and emotional arcs. Phase 5.
"""
from typing import Callable


# Story beat phases (0-1 normalized time)
STORY_BEATS: dict[str, tuple[float, float]] = {
    "setup": (0.0, 0.25),
    "development": (0.25, 0.6),
    "climax": (0.6, 0.85),
    "resolution": (0.85, 1.0),
}


def get_tension_at(t_normalized: float) -> float:
    """
    Return tension/emotional intensity at normalized time (0-1).
    Classic arc: low -> rise -> climax -> fall.
    """
    t = max(0, min(1, t_normalized))
    # Simple curve: ramps up to ~0.7, peaks, then drops
    if t < 0.25:
        return 0.3 + 0.4 * (t / 0.25)  # setup: 0.3 -> 0.7
    if t < 0.6:
        return 0.7 + 0.2 * ((t - 0.25) / 0.35)  # development: 0.7 -> 0.9
    if t < 0.85:
        return 0.9 + 0.1 * ((t - 0.6) / 0.25)  # climax: 0.9 -> 1.0
    return 1.0 - 0.7 * ((t - 0.85) / 0.15)  # resolution: 1.0 -> 0.3


def get_beat_at(t_normalized: float) -> str:
    """Return story beat name at normalized time."""
    t = max(0, min(1, t_normalized))
    for name, (lo, hi) in STORY_BEATS.items():
        if lo <= t < hi:
            return name
    return "resolution"
