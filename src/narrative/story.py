"""
Story beats and emotional arcs. Phase 5.
"""


# Story beat phases (0-1 normalized time)
STORY_BEATS: dict[str, tuple[float, float]] = {
    "setup": (0.0, 0.25),
    "development": (0.25, 0.6),
    "climax": (0.6, 0.85),
    "resolution": (0.85, 1.0),
}


def get_tension_at(t_normalized: float, curve: str = "standard") -> float:
    """
    Return tension/emotional intensity at normalized time (0-1).
    curve: flat | slow_build | standard | immediate
    """
    t = max(0.0, min(1.0, float(t_normalized)))
    c = (curve or "standard").lower().replace(" ", "_")
    if c == "flat":
        return 0.55
    if c == "immediate":
        # Peak early, then ease down
        if t < 0.15:
            return 0.5 + 0.5 * (t / 0.15)
        if t < 0.45:
            return 1.0 - 0.25 * ((t - 0.15) / 0.3)
        return 0.75 - 0.35 * ((t - 0.45) / 0.55)
    if c == "slow_build":
        # Stay low longer, climax late
        if t < 0.45:
            return 0.25 + 0.25 * (t / 0.45)
        if t < 0.8:
            return 0.5 + 0.5 * ((t - 0.45) / 0.35)
        return 1.0 - 0.55 * ((t - 0.8) / 0.2)
    # standard classic arc
    if t < 0.25:
        return 0.3 + 0.4 * (t / 0.25)
    if t < 0.6:
        return 0.7 + 0.2 * ((t - 0.25) / 0.35)
    if t < 0.85:
        return 0.9 + 0.1 * ((t - 0.6) / 0.25)
    return 1.0 - 0.7 * ((t - 0.85) / 0.15)


def get_beat_at(t_normalized: float) -> str:
    """Return story beat name at normalized time."""
    t = max(0, min(1, t_normalized))
    for name, (lo, hi) in STORY_BEATS.items():
        if lo <= t < hi:
            return name
    return "resolution"
