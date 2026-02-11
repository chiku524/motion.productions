"""
Sensible name generator for registry discoveries (Pure, Temporal, Semantic, Interpretation).

Requirement (REGISTRY_FOUNDATION): names must be semantic (meaningful, possibly non-existent
words) or clearly in the category of names. No gibberish. No underscores — resemble actual
names (e.g. Suntor, Velvet, Rainrise).

Algorithm: combine 2 parts (start + end) from curated lists of real-word or name-like
syllables. Output: single word, title case (e.g. Suntor, Velvet). Pronounceable, consistent.
See docs/NAME_GENERATOR.md.
"""
import re
from typing import Any

# Start parts — semantic or name-like (real words or plausible name roots)
_START = [
    "am", "vel", "cor", "sil", "riv", "mist", "dawn", "dusk", "wave", "drift",
    "soft", "deep", "cool", "warm", "calm", "star", "sky", "sea", "frost", "dew",
    "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow",
    "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook",
    "sun", "lune", "mar", "sol", "aur", "coral", "amber", "azure", "ember",
    "lark", "fern", "birch", "cliff", "marsh", "glen", "thor", "wyn", "el",
]
# End parts — complete to form semantic or name-like words (e.g. -wood, -well, -ton)
_END = [
    "ber", "vet", "al", "ver", "er", "en", "ow", "or", "um", "in", "ar",
    "ace", "ine", "ure", "ish", "ing", "lyn", "tor", "nel", "ton", "ley",
    "well", "brook", "field", "wood", "light", "fall", "rise", "ford", "dale",
    "mont", "view", "crest", "haven", "mere", "wyn", "son", "ley", "worth",
]

# Known semantic words (real or name-like). Used first so the generator is precise and
# produces meaningful names for many undiscovered elements. Extended as needed.
_REAL_WORDS = [
    "amber", "velvet", "coral", "silver", "river", "mist", "dawn", "dusk", "wave", "drift",
    "soft", "deep", "cool", "warm", "calm", "star", "sky", "sea", "frost", "dew",
    "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow",
    "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook",
    "sun", "ember", "azure", "lark", "fern", "cliff", "marsh", "glen", "haven",
    "fall", "rise", "ford", "dale", "mont", "view", "crest", "mere", "worth",
]

# Max length for the invented word (slightly higher for variety and name count)
_MAX_WORD_LEN = 14
# Domain to prefix (short; keeps full name readable)
_DOMAIN_PREFIX: dict[str, str] = {
    "color": "color",
    "sound": "sound",
    "motion": "motion",
    "time": "time",
    "lighting": "light",
    "composition": "comp",
    "graphics": "graph",
    "temporal": "tempo",
    "technical": "tech",
    "blends": "blend",
    "audio": "audio",
    "audio_semantic": "audio",
    "full_blend": "blend",
    "themes": "theme",
    "plots": "plot",
    "settings": "setting",
    "genre": "genre",
    "mood": "mood",
    "scene_type": "scene",
    "style": "style",
    "gradient": "grad",
    "camera": "cam",
    "transition": "trans",
    "depth": "depth",
}


def _words_from_prompt(prompt: str, max_words: int = 3) -> list[str]:
    """Extract meaningful words from prompt (3+ letters)."""
    words = re.findall(r"[a-z]{3,}", (prompt or "").lower())
    return words[:max_words]


def _invent_word(seed: int) -> str:
    """
    Invent a short, semantic or name-like word from seed. Precision: prefer known
    real words from _REAL_WORDS so the generator produces meaningful names for
    many undiscovered elements. Fallback: start + end parts (no gibberish).
    """
    r = abs(seed) % (2**31)
    # Prefer known semantic word when possible (deterministic, large space)
    word_idx = r % len(_REAL_WORDS)
    candidate = _REAL_WORDS[word_idx]
    if 4 <= len(candidate) <= _MAX_WORD_LEN:
        return candidate
    # Else build from start + end (semantic parts only)
    s_idx = (r >> 7) % len(_START)
    start = _START[s_idx]
    for k in range(len(_END)):
        r = (r * 7919 + 1237 + k) % (2**31)
        e_idx = r % len(_END)
        end = _END[e_idx]
        if start and end and start[-1] == end[0]:
            continue
        word = start + end
        if len(word) > _MAX_WORD_LEN:
            word = word[:_MAX_WORD_LEN]
        if len(word) < 4:
            word = word + end[: min(len(end), 4 - len(word))]
        return word[:_MAX_WORD_LEN]
    return (start + _END[0])[:_MAX_WORD_LEN]


def generate_sensible_name(
    domain: str,
    value_hint: str = "",
    *,
    existing_names: set[str] | None = None,
    use_prefix: bool = False,
) -> str:
    """
    Generate a sensible, short name for a registry entry.
    Format: single word, title case (e.g. Suntor, Velvet) — no underscores.
    Resembles actual names. Word is 4–14 chars; pronounceable.
    """
    existing = existing_names or set()
    seed = hash((domain, value_hint, len(existing))) % (2**31)

    for i in range(200):
        word = _invent_word(seed + i * 7919)
        if len(word) < 4:
            continue
        candidate = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if candidate not in existing:
            return candidate

    suffix = abs(hash((domain, value_hint, seed))) % 100000
    return f"Novel{suffix:05d}"


def _combine_words(words: list[str], max_len: int = 14) -> str:
    """Combine prompt words into one short token (e.g. azure + serene -> azureserene)."""
    if not words:
        return ""
    combined = "".join(w for w in words if w)[:max_len].lower()
    return combined if len(combined) >= 4 else ""


def generate_blend_name(
    domain: str,
    prompt: str = "",
    *,
    existing_names: set[str] | None = None,
) -> str:
    """
    Generate a unique, sensible name for a blend. No underscores — resembles
    actual names (e.g. Suntor, Velvet). Tries: (1) combined prompt words;
    (2) invented word; (3) numeric fallback.
    """
    existing = existing_names or set()
    words = _words_from_prompt(prompt)

    if words:
        raw = _combine_words(words)
        if raw and raw not in existing:
            return raw[0].upper() + raw[1:].lower() if len(raw) > 1 else raw.upper()

    sensible = generate_sensible_name(domain, prompt, existing_names=existing, use_prefix=False)
    if sensible not in existing:
        return sensible

    seed = hash((domain, prompt, len(existing))) % (2**31)
    for i in range(100):
        word = _invent_word(seed + i * 4567)
        candidate = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if candidate not in existing:
            return candidate

    return f"Blend{abs(hash((domain, prompt))) % 100000:05d}"
