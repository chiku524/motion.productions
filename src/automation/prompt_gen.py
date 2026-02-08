"""
Procedural prompt generator. Uses only our keyword data — no external LLM.
Produces diverse prompts for automated knowledge-building.
"""
import random
from typing import Iterator

from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
)

# Unique keywords per category (avoid duplicates across mappings)
SUBJECTS = sorted(set(KEYWORD_TO_PALETTE.keys()))
MODIFIERS_MOTION = [k for k in KEYWORD_TO_MOTION.keys() if k not in SUBJECTS]
MODIFIERS_INTENSITY = [k for k in KEYWORD_TO_INTENSITY.keys() if k not in SUBJECTS]

# Templates: subject + optional modifier
TEMPLATES = [
    "{subject}",
    "{subject}, {modifier}",
    "{subject} {modifier}",
    "{modifier} {subject}",
]


def generate_procedural_prompt(
    *,
    subjects: list[str] | None = None,
    modifiers: list[str] | None = None,
    seed: int | None = None,
    avoid: set[str] | None = None,
) -> str | None:
    """
    Generate one prompt by combining subject + modifier from our keyword data.
    Returns None if no new combination found (avoid set exhausted).
    """
    if seed is not None:
        random.seed(seed)
    subjects = subjects or SUBJECTS
    modifiers = modifiers or (MODIFIERS_MOTION + MODIFIERS_INTENSITY)
    avoid = avoid or set()

    # Try random combinations
    for _ in range(50):
        sub = random.choice(subjects)
        mod = random.choice(modifiers)
        for tmpl in random.sample(TEMPLATES, len(TEMPLATES)):
            if tmpl == "{subject}":
                prompt = sub
            else:
                prompt = tmpl.format(subject=sub, modifier=mod)
            if prompt not in avoid:
                return prompt
    return None


def generate_prompt_batch(
    n: int,
    *,
    avoid: set[str] | None = None,
    seed: int | None = None,
) -> Iterator[str]:
    """
    Generate n distinct prompts. Yields prompts one at a time.
    """
    if seed is not None:
        random.seed(seed)
    avoid = set(avoid) if avoid else set()
    for _ in range(n):
        p = generate_procedural_prompt(avoid=avoid)
        if p is None:
            break
        avoid.add(p)
        yield p
