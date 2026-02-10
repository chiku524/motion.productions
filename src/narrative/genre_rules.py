"""
Genre-specific rules: pacing, lighting, shot rhythm. Phase 5.
"""
from dataclasses import dataclass


@dataclass
class GenreRule:
    """Rules for a genre."""
    default_pacing: float
    lighting_bias: str
    tension_curve: str  # "standard" | "slow_build" | "immediate" | "flat"
    preferred_transition: str


GENRE_RULES: dict[str, GenreRule] = {
    "documentary": GenreRule(
        default_pacing=0.8,
        lighting_bias="documentary",
        tension_curve="slow_build",
        preferred_transition="dissolve",
    ),
    "thriller": GenreRule(
        default_pacing=1.2,
        lighting_bias="moody",
        tension_curve="standard",
        preferred_transition="cut",
    ),
    "ad": GenreRule(
        default_pacing=1.3,
        lighting_bias="golden_hour",
        tension_curve="immediate",
        preferred_transition="cut",
    ),
    "tutorial": GenreRule(
        default_pacing=0.7,
        lighting_bias="neutral",
        tension_curve="flat",
        preferred_transition="dissolve",
    ),
    "educational": GenreRule(
        default_pacing=0.75,
        lighting_bias="documentary",
        tension_curve="slow_build",
        preferred_transition="dissolve",
    ),
    "explainer": GenreRule(
        default_pacing=0.9,
        lighting_bias="neutral",
        tension_curve="standard",
        preferred_transition="dissolve",
    ),
    "general": GenreRule(
        default_pacing=1.0,
        lighting_bias="neutral",
        tension_curve="standard",
        preferred_transition="cut",
    ),
}


def get_genre_rules(genre: str) -> GenreRule:
    """Return rules for genre."""
    return GENRE_RULES.get(genre, GENRE_RULES["general"])
