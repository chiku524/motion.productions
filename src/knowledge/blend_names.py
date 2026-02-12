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
    "slate", "mist", "sage", "flax", "iron", "stone", "oak", "pine", "cedar",
    "willow", "maple", "ivory", "copper", "bronze", "chalk", "linen", "wool",
]

# End parts — complete to form semantic or name-like words (e.g. -wood, -well, -ton)
_END = [
    "ber", "vet", "al", "ver", "er", "en", "ow", "or", "um", "in", "ar",
    "ace", "ine", "ure", "ish", "ing", "lyn", "tor", "nel", "ton", "ley",
    "well", "brook", "field", "wood", "light", "fall", "rise", "ford", "dale",
    "mont", "view", "crest", "haven", "mere", "wyn", "son", "ley", "worth",
    "stone", "vale", "mist", "glow", "bloom", "stream", "ridge", "shore",
]

# Known semantic words (real or name-like). Extended for large name space.
_REAL_WORDS = [
    "amber", "velvet", "coral", "silver", "river", "mist", "dawn", "dusk", "wave", "drift",
    "soft", "deep", "cool", "warm", "calm", "star", "sky", "sea", "frost", "dew",
    "rose", "gold", "pearl", "sage", "mint", "vine", "bloom", "shade", "glow",
    "flow", "haze", "vale", "storm", "leaf", "cloud", "wind", "rain", "brook",
    "sun", "ember", "azure", "lark", "fern", "cliff", "marsh", "glen", "haven",
    "fall", "rise", "ford", "dale", "mont", "view", "crest", "mere", "worth",
    "slate", "stone", "iron", "flax", "oak", "pine", "cedar", "willow", "maple",
    "ivory", "copper", "bronze", "chalk", "linen", "wool", "silk", "jade",
    "aurora", "twilight", "midnight", "sundown", "starlight", "moonlight",
    "forest", "meadow", "prairie", "grove", "canopy", "thicket", "bramble",
]

# Max length for the invented word (18 for variety; names stay readable)
_MAX_WORD_LEN = 18
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


def _rgb_to_semantic_hint(r: float, g: float, b: float) -> str:
    """Map RGB to a semantic hint for color naming (e.g. grayish blue → slate)."""
    r, g, b = float(r), float(g), float(b)
    mx = max(r, g, b)
    mn = min(r, g, b)
    if mx < 50:
        return "shadow"
    if mx - mn < 40:  # Low saturation = grayish
        lum = (r + g + b) / 3
        if lum < 80:
            return "graphite"
        if lum < 140:
            return "slate"
        return "mist"
    # Dominant hue
    if r >= g and r >= b and r > 0:
        if b > g:
            return "ember"
        return "sunset" if r > 180 else "rust"
    if g >= r and g >= b and g > 0:
        if r > b:
            return "moss"
        return "forest" if g > 120 else "olive"
    if b >= r and b >= g and b > 0:
        if g > r:
            return "teal"
        if r > g:
            return "violet"
        return "ocean" if b > 140 else "midnight"
    return "neutral"


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
    rgb_hint: tuple[float, float, float] | None = None,
) -> str:
    """
    Generate a sensible, short name for a registry entry.
    Format: single word, title case (e.g. Suntor, Velvet) — no underscores.
    Resembles actual names. Word is 4–18 chars; pronounceable.
    When rgb_hint is provided (for color domain), uses semantic hint (slate, ember, etc.).
    """
    existing = existing_names or set()
    hint = value_hint
    if domain == "color" and rgb_hint and len(rgb_hint) >= 3:
        hint = _rgb_to_semantic_hint(rgb_hint[0], rgb_hint[1], rgb_hint[2])
    elif hint and domain == "color" and "," in hint:
        # key like "100,100,150_1.0" → extract RGB
        try:
            parts = hint.split("_")[0].split(",")
            if len(parts) >= 3:
                r, g, b = float(parts[0]), float(parts[1]), float(parts[2])
                hint = _rgb_to_semantic_hint(r, g, b)
        except (ValueError, IndexError):
            pass
    seed = hash((domain, hint, len(existing))) % (2**31)

    # Prefer real word matching hint when available
    if hint and hint in _REAL_WORDS:
        cap = hint[0].upper() + hint[1:].lower()
        if cap not in existing:
            return cap

    for i in range(300):
        word = _invent_word(seed + i * 7919)
        if len(word) < 4:
            continue
        candidate = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if candidate not in existing:
            return candidate

    suffix = abs(hash((domain, hint, seed))) % 100000
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
