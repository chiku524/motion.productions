"""
Narrative: story beats, emotional arcs, genre templates. Phase 5.
"""
from .story import STORY_BEATS, get_tension_at
from .genre_rules import GENRE_RULES, get_genre_rules

__all__ = [
    "STORY_BEATS",
    "get_tension_at",
    "GENRE_RULES",
    "get_genre_rules",
]
