"""
Procedural prompt generator. Uses keyword data + learned discoveries for dynamic exploration.
Produces diverse prompts for automated knowledge-building.
"""
import random
from typing import Any, Iterator

from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    KEYWORD_TO_LIGHTING,
    KEYWORD_TO_GENRE,
    KEYWORD_TO_SHOT,
    KEYWORD_TO_TRANSITION,
    KEYWORD_TO_PACING,
    KEYWORD_TO_COMPOSITION_BALANCE,
    KEYWORD_TO_COMPOSITION_SYMMETRY,
    KEYWORD_TO_TENSION,
    KEYWORD_TO_AUDIO_TEMPO,
    KEYWORD_TO_AUDIO_MOOD,
    KEYWORD_TO_AUDIO_PRESENCE,
)

# Base subjects (palette-suggesting keywords)
SUBJECTS_BASE = sorted(set(KEYWORD_TO_PALETTE.keys()))

# All modifier categories — every domain from INTENDED_LOOP represented
_MODS_MOTION = [k for k in KEYWORD_TO_MOTION.keys() if k not in SUBJECTS_BASE]
_MODS_INTENSITY = [k for k in KEYWORD_TO_INTENSITY.keys() if k not in SUBJECTS_BASE]
_MODS_GRADIENT = [k for k in KEYWORD_TO_GRADIENT.keys() if k not in SUBJECTS_BASE]
_MODS_CAMERA = [k for k in KEYWORD_TO_CAMERA.keys() if k not in SUBJECTS_BASE]
_MODS_SHAPE = [k for k in KEYWORD_TO_SHAPE.keys() if k not in SUBJECTS_BASE]
_MODS_LIGHTING = list(KEYWORD_TO_LIGHTING.keys())
_MODS_GENRE = list(KEYWORD_TO_GENRE.keys())
_MODS_SHOT = list(KEYWORD_TO_SHOT.keys())
_MODS_TRANSITION = list(KEYWORD_TO_TRANSITION.keys())
# Temporal: pacing
_MODS_PACING = list(KEYWORD_TO_PACING.keys())
# Composition: balance, symmetry
_MODS_COMPOSITION = list(KEYWORD_TO_COMPOSITION_BALANCE.keys()) + [k for k in KEYWORD_TO_COMPOSITION_SYMMETRY.keys() if k not in KEYWORD_TO_COMPOSITION_BALANCE]
# Narrative: tension curve
_MODS_TENSION = list(KEYWORD_TO_TENSION.keys())
# Audio: tempo, mood, presence
_MODS_AUDIO = list(KEYWORD_TO_AUDIO_TEMPO.keys()) + list(KEYWORD_TO_AUDIO_MOOD.keys()) + list(KEYWORD_TO_AUDIO_PRESENCE.keys())
_MODS_AUDIO = list(dict.fromkeys(m for m in _MODS_AUDIO if m not in SUBJECTS_BASE))

MODIFIERS_BASE = (
    _MODS_MOTION + _MODS_INTENSITY + _MODS_GRADIENT + _MODS_CAMERA + _MODS_SHAPE
    + _MODS_LIGHTING + _MODS_GENRE + _MODS_SHOT + _MODS_TRANSITION
    + _MODS_PACING + _MODS_COMPOSITION + _MODS_TENSION + _MODS_AUDIO
)
MODIFIERS_BASE = [m for m in MODIFIERS_BASE if m not in SUBJECTS_BASE]
MODIFIERS_BASE = list(dict.fromkeys(MODIFIERS_BASE))  # dedupe preserve order

# Templates: single and multi-modifier for larger combination space
TEMPLATES_SINGLE = [
    "{subject}",
    "{subject}, {modifier}",
    "{subject} {modifier}",
    "{modifier} {subject}",
    "{subject} with {modifier}",
]
TEMPLATES_DOUBLE = [
    "{subject}, {mod1} and {mod2}",
    "{subject} {mod1} {mod2}",
    "{mod1} {subject} {mod2}",
    "{subject} with {mod1} and {mod2}",
]
TEMPLATES_ALL = TEMPLATES_SINGLE + TEMPLATES_DOUBLE


def _expand_from_knowledge(knowledge: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """
    Extract additional subjects and modifiers from learned knowledge.
    Returns (extra_subjects, extra_modifiers).
    """
    if not knowledge:
        return [], []

    extra_subjects: list[str] = []
    extra_modifiers: list[str] = []

    # Learned color names (e.g. "blavexo", "kinevo") — use as palette modifiers
    learned_colors = knowledge.get("learned_colors") or {}
    for color_key, data in learned_colors.items():
        if isinstance(data, dict):
            name = data.get("name") or color_key
            if name and isinstance(name, str) and len(name) >= 3:
                extra_modifiers.append(f"{name} tones")
                extra_modifiers.append(f"{name} palette")

    # Learned motion profiles — use as motion modifiers
    learned_motion = knowledge.get("learned_motion") or []
    for m in learned_motion:
        if isinstance(m, dict):
            name = m.get("name")
            trend = m.get("motion_trend", "")
            level = m.get("motion_level", 0)
            if name and isinstance(name, str) and len(name) >= 3:
                extra_modifiers.append(f"{name} motion")
            # Phrase from motion characteristics
            if trend and trend != "steady":
                extra_modifiers.append(f"{trend} drift")
            if level and float(level) > 5:
                extra_modifiers.append("dynamic movement")

    # Proven keywords from learning stats (high-count = works well)
    by_keyword = knowledge.get("by_keyword") or {}
    for kw, stats in list(by_keyword.items())[:50]:
        if isinstance(stats, dict) and stats.get("count", 0) >= 2:
            if kw and isinstance(kw, str) and kw not in SUBJECTS_BASE:
                extra_subjects.append(kw)

    # Proven palettes
    by_palette = knowledge.get("by_palette") or {}
    for pal, stats in list(by_palette.items())[:30]:
        if isinstance(stats, dict) and stats.get("count", 0) >= 1:
            if pal and isinstance(pal, str):
                extra_modifiers.append(f"{pal} style")

    # Dedupe
    extra_subjects = list(dict.fromkeys(s for s in extra_subjects if s))
    extra_modifiers = list(dict.fromkeys(m for m in extra_modifiers if m))
    return extra_subjects, extra_modifiers


def generate_procedural_prompt(
    *,
    subjects: list[str] | None = None,
    modifiers: list[str] | None = None,
    knowledge: dict[str, Any] | None = None,
    seed: int | None = None,
    avoid: set[str] | None = None,
) -> str | None:
    """
    Generate one prompt by combining subject + modifier(s) from keyword data and learned discoveries.
    When knowledge is provided, uses learned colors, motion profiles, and proven keywords.
    Returns None if no new combination found (avoid set exhausted).
    """
    if seed is not None:
        random.seed(seed)

    avoid = avoid or set()

    # Build subject and modifier pools (static + dynamic from knowledge)
    if subjects is not None and modifiers is not None:
        sub_pool = list(subjects)
        mod_pool = list(modifiers)
    else:
        sub_pool = list(SUBJECTS_BASE)
        mod_pool = list(MODIFIERS_BASE)
        extra_subs, extra_mods = _expand_from_knowledge(knowledge)
        sub_pool = list(dict.fromkeys(sub_pool + extra_subs))
        mod_pool = list(dict.fromkeys(mod_pool + extra_mods))

    if not sub_pool or not mod_pool:
        return None

    # Try random combinations (more attempts for larger space)
    max_attempts = 150
    for _ in range(max_attempts):
        sub = random.choice(sub_pool)
        mod1 = random.choice(mod_pool)
        mod2 = random.choice(mod_pool) if len(mod_pool) > 1 else mod1

        # Pick template (single vs double modifier)
        use_double = random.random() < 0.35 and mod1 != mod2
        templates = TEMPLATES_DOUBLE if use_double else TEMPLATES_SINGLE
        tmpl = random.choice(templates)

        try:
            if "mod2" in tmpl:
                prompt = tmpl.format(subject=sub, mod1=mod1, mod2=mod2)
            else:
                prompt = tmpl.format(subject=sub, modifier=mod1)
        except (KeyError, ValueError):
            prompt = f"{sub}, {mod1}"

        if prompt and prompt not in avoid:
            return prompt

    return None


def generate_prompt_batch(
    n: int,
    *,
    avoid: set[str] | None = None,
    knowledge: dict[str, Any] | None = None,
    seed: int | None = None,
) -> Iterator[str]:
    """
    Generate n distinct prompts. Yields prompts one at a time.
    """
    if seed is not None:
        random.seed(seed)
    avoid = set(avoid) if avoid else set()
    for _ in range(n):
        p = generate_procedural_prompt(avoid=avoid, knowledge=knowledge)
        if p is None:
            break
        avoid.add(p)
        yield p
