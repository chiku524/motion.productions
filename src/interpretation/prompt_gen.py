"""
Generate diverse, user-like prompts for the interpretation workflow.
Includes slang, dialect, and informal variants to expand the linguistic registry.
"""
import random
from typing import Any

from ..random_utils import secure_choice, secure_random
from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_LIGHTING,
    KEYWORD_TO_GENRE,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_PACING,
    KEYWORD_TO_AUDIO_MOOD,
)

# Slang / informal equivalents: canonical -> [variants]
SLANG_VARIANTS: dict[str, list[str]] = {
    "calm": ["chill", "laid-back", "mellow", "relaxed"],
    "bright": ["lit", "vibrant", "poppin", "glowing"],
    "dark": ["moody", "dim", "lowkey", "shadowy"],
    "fast": ["quick", "speedy", "brisk", "snappy"],
    "slow": ["chill", "easy", "gentle", "smooth"],
    "dreamy": ["ethereal", "soft", "hazy", "soft-focused"],
    "neon": ["neon", "lit", "electric", "glowy"],
    "ocean": ["sea", "water", "aqua", "blue"],
    "night": ["dark", "nocturnal", "late-night"],
    "peaceful": ["chill", "calm", "serene", "tranquil"],
    "energetic": ["lit", "vibing", "dynamic", "pulse"],
    "cinematic": ["film-like", "movie-style", "cinematic"],
    "documentary": ["doc-style", "real", "natural"],
}

# Dialect: US variant -> UK variant (or vice versa)
DIALECT_PAIRS: list[tuple[str, str]] = [
    ("color", "colour"),
    ("gray", "grey"),
    ("center", "centre"),
    ("realize", "realise"),
    ("analyze", "analyse"),
]

# Informal phrasings: {formal} -> {informal}
INFORMAL_PHRASES: dict[str, str] = {
    "dreamy atmosphere": "dreamy vibes",
    "calm and serene": "chill and peaceful",
    "slow motion": "slow-mo",
    "in a documentary style": "doc-style",
    "with cinematic feel": "cinematic vibes",
    "fast paced": "fast-paced",
    "golden hour": "golden hour lighting",
}

# Templates for user-like prompts (varied, natural)
TEMPLATES = [
    "{subject} with {mod}",
    "{mod} {subject}",
    "{subject}, {mod}",
    "something {mod} {subject}",
    "{subject} vibe",
    "{mod} {subject} aesthetic",
    "{subject} in {mod} style",
    "{subject} — {mod}",
    "a {mod} {subject}",
    "{subject} feeling {mod}",
]


def _get_domain_keywords() -> dict[str, list[str]]:
    """Extract keywords by domain for variety."""
    return {
        "palette": list(KEYWORD_TO_PALETTE.keys())[:40],
        "motion": list(KEYWORD_TO_MOTION.keys())[:30],
        "lighting": list(KEYWORD_TO_LIGHTING.keys())[:15],
        "genre": list(KEYWORD_TO_GENRE.keys())[:12],
        "gradient": list(KEYWORD_TO_GRADIENT.keys())[:8],
        "camera": list(KEYWORD_TO_CAMERA.keys())[:12],
        "pacing": list(KEYWORD_TO_PACING.keys())[:8],
        "audio_mood": list(KEYWORD_TO_AUDIO_MOOD.keys())[:10],
    }


def _apply_variant(word: str, variant_mode: str) -> str:
    """Apply slang, dialect, or informal variant to a word."""
    w = word.lower()
    if variant_mode == "slang" and secure_random() < 0.4:
        for canonical, variants in SLANG_VARIANTS.items():
            if w == canonical:
                return secure_choice(variants)
        # Reverse: variants -> canonical
        for canonical, variants in SLANG_VARIANTS.items():
            if w in variants:
                return secure_choice([canonical] + variants)
    if variant_mode == "dialect" and secure_random() < 0.25:
        for us, uk in DIALECT_PAIRS:
            if w == us:
                return uk
            if w == uk:
                return us
    return word


def generate_interpretation_prompt(
    *,
    avoid: set[str] | None = None,
    knowledge: dict[str, Any] | None = None,
    seed: int | None = None,
    use_slang: bool = True,
    use_dialect: bool = True,
) -> str | None:
    """
    Generate one user-like prompt for the interpretation workflow.
    Uses varied English (slang, dialect, informal) to expand linguistic coverage.
    """
    if seed is not None:
        random.seed(seed)
    avoid = avoid or set()

    domain_kw = _get_domain_keywords()
    subjects = domain_kw["palette"] + domain_kw["motion"][:8]
    modifiers = (
        domain_kw["motion"] + domain_kw["lighting"] + domain_kw["genre"]
        + domain_kw["gradient"][:4] + domain_kw["pacing"][:4]
    )
    subjects = [s for s in subjects if not s.startswith("_")]
    modifiers = [m for m in modifiers if not m.startswith("_")]

    if not subjects or not modifiers:
        return None

    variant_mode = "slang" if use_slang and secure_random() < 0.35 else "standard"
    if use_dialect and secure_random() < 0.2:
        variant_mode = "dialect"

    sub = secure_choice(subjects)
    mod = secure_choice(modifiers)

    sub = _apply_variant(sub, variant_mode)
    mod = _apply_variant(mod, variant_mode)

    tmpl = secure_choice(TEMPLATES)
    try:
        prompt = tmpl.format(subject=sub, mod=mod)
    except (KeyError, ValueError):
        prompt = f"{sub} with {mod}"

    if prompt:
        prompt = prompt.strip()
        if prompt and prompt not in avoid:
            return prompt
    return None


def generate_interpretation_prompt_batch(
    n: int,
    *,
    avoid: set[str] | None = None,
    knowledge: dict[str, Any] | None = None,
    seed: int | None = None,
) -> list[str]:
    """Generate n distinct prompts for interpretation workflow."""
    avoid = set(avoid) if avoid else set()
    out: list[str] = []
    for _ in range(n * 3):
        if len(out) >= n:
            break
        p = generate_interpretation_prompt(
            avoid=avoid,
            knowledge=knowledge,
            seed=seed,
            use_slang=True,
            use_dialect=True,
        )
        if p and p not in avoid:
            avoid.add(p)
            out.append(p)
    return out
