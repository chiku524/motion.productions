"""
Generate unique names for successful blends.
Combines existing words or invents new words that have never been used.
"""
import re
import hashlib
from typing import Any

# Syllable roots for inventing new words (consonant-vowel patterns)
_CONSONANTS = "blckdrflgrklmnprstvz"
_VOWELS = "aeiou"

# Word stems for combination (existing domain words)
_STEMS = [
    "wave", "flow", "glow", "hue", "pulse", "drift", "shine", "fade",
    "deep", "soft", "sharp", "cold", "warm", "dim", "bright", "dark",
    "vel", "cor", "lum", "cin", "aur", "nex", "vex", "mir", "sol",
]


def _words_from_prompt(prompt: str, max_words: int = 3) -> list[str]:
    """Extract meaningful words from prompt for combination."""
    words = re.findall(r"[a-z]{3,}", (prompt or "").lower())
    return words[:max_words]


def _invent_word(seed: int) -> str:
    """Invent a pronounceable word from seed. Never repeats for same seed."""
    r = seed % 10000
    parts = []
    for _ in range(2, 4):
        c = _CONSONANTS[r % len(_CONSONANTS)]
        r //= len(_CONSONANTS)
        v = _VOWELS[r % len(_VOWELS)]
        r //= len(_VOWELS)
        parts.append(c + v)
    return "".join(parts)


def _combine_words(words: list[str], max_len: int = 12) -> str:
    """Combine words into a new phrase (e.g. azure + serene -> azureserene)."""
    if not words:
        return ""
    combined = "".join(w for w in words if w)
    return combined[:max_len].lower() if combined else ""


def generate_blend_name(
    domain: str,
    prompt: str = "",
    *,
    existing_names: set[str] | None = None,
) -> str:
    """
    Generate a unique name for a blend. Tries:
    1. Combine prompt words (e.g. azureserene)
    2. Combine domain + invented syllable (e.g. color_velumir)
    3. Pure invented word (e.g. corlenta)
    """
    existing = existing_names or set()
    words = _words_from_prompt(prompt)

    # Approach 1: combine prompt words
    if words:
        candidate = _combine_words(words)
        if candidate and candidate not in existing:
            return candidate

    # Approach 2: domain + invented
    seed = hash((domain, prompt, len(existing))) % (2**31)
    for i in range(100):
        invented = _invent_word(seed + i * 7919)
        candidate = f"{domain}_{invented}"
        if candidate not in existing:
            return candidate

    # Approach 3: pure invented
    for i in range(100):
        c1 = _invent_word(seed + i * 1237)
        c2 = _invent_word(seed + i * 4567)
        candidate = f"{c1}{c2}"
        if len(candidate) >= 5 and candidate not in existing:
            return candidate

    return f"blend_{hash((domain, prompt)) % 100000:05d}"
