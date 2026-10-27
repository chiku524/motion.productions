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


def is_semantic_name(name: str) -> bool:
    """
    True if name looks semantic/authentic (real word or our generator output).
    Gibberish like 'liworazagura', 'botucaveraka' returns False.
    """
    if not name or not isinstance(name, str):
        return False
    n = name.strip().lower()
    if len(n) < 4:
        return True
    if is_malformed_fusion(n):
        return False
    if n in {w.lower() for w in _REAL_WORDS}:
        return True
    for s in _START:
        if n.startswith(s.lower()):
            return True
    for e in _END:
        if n.endswith(e.lower()):
            return True
    if len(n) <= 8:
        return True
    return False
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


# RGB → semantic color vocabulary (authentic, evocative names)
_RGB_COLOR_VOCAB: dict[str, list[str]] = {
    "shadow": ["shadow", "charcoal", "obsidian", "onyx", "raven", "coal", "ink"],
    "graphite": ["graphite", "iron", "lead", "pewter", "gunmetal"],
    "slate": ["slate", "stone", "flint", "ash", "steel", "silver"],
    "mist": ["mist", "fog", "haze", "pearl", "cloud", "frost"],
    "ember": ["ember", "rust", "copper", "terracotta", "brick"],
    "sunset": ["sunset", "coral", "salmon", "blush", "apricot", "tangerine"],
    "rust": ["rust", "sienna", "ochre", "bronze", "umber"],
    "moss": ["moss", "sage", "fern", "olive", "jade"],
    "forest": ["forest", "pine", "cedar", "evergreen", "laurel"],
    "olive": ["olive", "khaki", "sand", "tan", "taupe"],
    "teal": ["teal", "turquoise", "aqua", "cyan", "mint"],
    "violet": ["violet", "lavender", "lilac", "plum", "amethyst"],
    "ocean": ["ocean", "navy", "indigo", "sapphire", "azure"],
    "midnight": ["midnight", "twilight", "dusk", "deep", "abyss"],
    "neutral": ["stone", "sand", "linen", "ivory", "cream"],
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


def _color_name_from_rgb(
    r: float, g: float, b: float,
    existing: set[str],
    seed_offset: int = 0,
) -> str | None:
    """
    Return a semantic color name from RGB using _RGB_COLOR_VOCAB.
    None if no unique candidate found (caller falls back to _invent_word).
    """
    hint = _rgb_to_semantic_hint(r, g, b)
    vocab = _RGB_COLOR_VOCAB.get(hint, [hint])
    for i, word in enumerate(vocab):
        candidate = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if candidate not in existing:
            return candidate
    # Try compound: hint + modifier from _REAL_WORDS
    modifiers = ["light", "deep", "pale", "soft", "dark", "warm", "cool"]
    r2 = abs(hash((r, g, b, seed_offset))) % (2**31)
    for _ in range(20):
        mod = modifiers[r2 % len(modifiers)]
        base = vocab[r2 % len(vocab)]
        candidate = (mod[0].upper() + mod[1:] + base[0].upper() + base[1:])[:18]
        if len(candidate) >= 6 and candidate not in existing:
            return candidate
        r2 = (r2 * 7919 + 1237) % (2**31)
    return None


def _words_from_prompt(prompt: str, max_words: int = 3) -> list[str]:
    """Extract meaningful words from prompt (3+ letters)."""
    words = re.findall(r"[a-z]{3,}", (prompt or "").lower())
    return words[:max_words]


# Words that may be glued to the end of another word to form a compound ("Ivorymist", "Sunstone").
_COMPOUND_TAILS = [
    "glow", "light", "fall", "rise", "ford", "dale", "mont", "view", "crest", "haven", "mere",
    "stone", "vale", "mist", "bloom", "stream", "ridge", "shore", "brook", "field", "wood", "well",
    "worth", "drift", "wave", "shade", "frost", "leaf", "star", "wind", "cloud", "rain", "fern",
    "pine", "dusk", "dawn", "flow", "haze", "storm", "sky", "sea", "sun", "dew", "rose", "gold",
    "pearl", "sage", "mint", "vine", "ember", "glen", "marsh", "cliff", "lark", "jade", "silk",
]

# Fragments that are NOT words by themselves. Gluing one onto a real word ("wave"+"ow",
# "ivory"+"um", "gold"+"ow") is what produced "waveow"/"ivoryum"/"Sageum"/"Valeow".
_JUNK_SUFFIXES = frozenset({
    "ber", "vet", "al", "ver", "er", "en", "ow", "or", "um", "in", "ar", "ace", "ine", "ure",
    "ish", "lyn", "tor", "nel", "ton", "ley",
})

# Genuine English words that happen to be real word + junk suffix.
_REAL_ENGLISH_FUSIONS = frozenset({
    "golden", "woolen", "silken", "oaken", "flaxen", "marshal", "waver", "flower", "glower",
    "mister", "bloomer", "drifter", "winder", "shader", "stormer",
})

_COLOR_MODIFIERS = ("light", "deep", "pale", "soft", "dark", "warm", "cool")


def is_malformed_fusion(name: str) -> bool:
    """
    True for a real word with a meaningless fragment glued on ("waveow", "ivoryum", "goldow",
    "sageum"). Legitimate compounds ("emberglow", "dawnrise") and real words are not flagged.
    """
    n = re.sub(r"[^a-z]", "", (name or "").lower())
    if len(n) < 5 or n in _REAL_WORDS or n in _REAL_ENGLISH_FUSIONS:
        return False
    for w in _REAL_WORDS:
        if len(w) >= 3 and n.startswith(w) and n[len(w):] in _JUNK_SUFFIXES:
            return True
    return False


def _split_glued(n: str) -> str | None:
    """'darktangerine' -> 'dark tangerine' when it is a known modifier + known color/word."""
    low = n.lower()
    vocab = {w for ws in _RGB_COLOR_VOCAB.values() for w in ws} | set(_RGB_COLOR_VOCAB) | set(_REAL_WORDS)
    for mod in _COLOR_MODIFIERS:
        if low.startswith(mod) and low[len(mod):] in vocab and len(low) > len(mod) + 2:
            return n[: len(mod)] + " " + n[len(mod):]
    return None


def humanize_name(name: str) -> str:
    """Make a stored registry name read like words in a sentence ('DarkTangerine' -> 'Dark Tangerine')."""
    n = (name or "").strip()
    if not n:
        return n
    n = re.sub(r"[_\-\s]+", " ", n)
    n = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", n)
    if " " not in n:
        split = _split_glued(n)
        if split:
            n = split
    return n


def clean_name_for_prompt(name: str) -> str | None:
    """Name safe to put into a user-facing prompt: humanized, or None if it is a malformed fusion."""
    n = (name or "").strip()
    if not n or is_malformed_fusion(n):
        return None
    return humanize_name(n)


def has_malformed_word(text: str) -> bool:
    """True if any word in the text is a malformed fusion (see is_malformed_fusion)."""
    return any(is_malformed_fusion(w) for w in re.findall(r"[A-Za-z]{5,}", text or ""))


def sanitize_prompt_words(text: str) -> str:
    """Split glued modifier+color tokens ('darktangerine' / 'DarkTangerine') inside a finished prompt."""
    def _fix(m: re.Match[str]) -> str:
        return humanize_name(m.group(0))
    return re.sub(r"[A-Za-z]{8,}", _fix, text or "")


def _compound(seed: int, parts: int) -> str:
    """Deterministic compound of real words ('ivory'+'mist'); adjacent parts never repeat or touch letters."""
    r = abs(seed) % (2**31)
    r = (r * 7919 + 1237) % (2**31)
    word = _REAL_WORDS[r % len(_REAL_WORDS)]
    for _ in range(parts - 1):
        for k in range(len(_COMPOUND_TAILS)):
            r = (r * 7919 + 1237 + k) % (2**31)
            tail = _COMPOUND_TAILS[(r >> 5) % len(_COMPOUND_TAILS)]
            if tail == word or word.endswith(tail) or word[-1] == tail[0]:
                continue
            word += tail
            break
    return word


def _invent_word(seed: int) -> str:
    """
    Invent a semantic, well-formed word from seed: a real word, or a compound of real words
    ("Ivorymist", "Sunstonelight"). Never a real word + meaningless fragment ("waveow").
    Deterministic; the compound space (~85 x 55 x 55 ...) is far larger than any registry.
    """
    r = abs(seed) % (2**31)
    mode = (r >> 3) % 5
    if mode == 0:
        candidate = _REAL_WORDS[r % len(_REAL_WORDS)]
        if 4 <= len(candidate) <= _MAX_WORD_LEN:
            return candidate
    parts = 3 if mode == 4 else 2
    for attempt in range(8):
        word = _compound(r + attempt * 104729, parts)
        if 4 <= len(word) <= _MAX_WORD_LEN and not re.search(r"(.)\1\1", word):
            return word
    return _compound(r, 2)[:_MAX_WORD_LEN]


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
    Format: single word, title case (e.g. Velvet, Slate) — no underscores.
    Resembles actual names. Word is 4–18 chars; pronounceable.
    For color domain with rgb_hint: prefers RGB-driven semantic vocabulary.
    """
    existing = existing_names or set()
    hint = value_hint
    r, g, b = None, None, None
    if domain == "color" and rgb_hint and len(rgb_hint) >= 3:
        r, g, b = float(rgb_hint[0]), float(rgb_hint[1]), float(rgb_hint[2])
        hint = _rgb_to_semantic_hint(r, g, b)
    elif hint and domain == "color" and "," in hint:
        try:
            parts = hint.split("_")[0].split(",")
            if len(parts) >= 3:
                r, g, b = float(parts[0]), float(parts[1]), float(parts[2])
                hint = _rgb_to_semantic_hint(r, g, b)
        except (ValueError, IndexError):
            pass

    # Color domain: prefer RGB-driven semantic vocabulary (authentic names)
    if domain == "color" and r is not None and g is not None and b is not None:
        rgb_name = _color_name_from_rgb(r, g, b, existing, seed_offset=len(existing))
        if rgb_name:
            return rgb_name

    seed = hash((domain, hint, len(existing))) % (2**31)

    # Prefer real word matching hint when available
    if hint and hint in _REAL_WORDS:
        cap = hint[0].upper() + hint[1:].lower()
        if cap not in existing:
            return cap

    for i in range(500):
        word = _invent_word(seed + i * 7919)
        if len(word) < 4:
            continue
        candidate = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if candidate not in existing:
            return candidate

    # Exhaustive fallback: longer real-word compounds (never numeric, never word+fragment).
    for parts in (3, 4, 5):
        for i in range(2000):
            word = _compound(seed + i * 15485863, parts)
            candidate = word[0].upper() + word[1:].lower()
            if candidate not in existing and len(candidate) >= 4:
                return candidate
    word = _compound(seed, 5)
    domain_token = (domain or "tone").strip().lower().replace("_", "")[:8] or "tone"
    base = word + domain_token
    candidate = base[0].upper() + base[1:].lower()
    n = 0
    while candidate in existing:
        n += 1
        candidate = (_compound(seed + n, 5) + domain_token).capitalize()
    return candidate


def _combine_words(words: list[str], max_len: int = 14) -> str:
    """Combine prompt words into one short token (e.g. azure + serene -> azureserene)."""
    if not words:
        return ""
    combined = "".join(w for w in words if w)[:max_len].lower()
    return combined if len(combined) >= 4 else ""


def title_case_label(value: str) -> str:
    """Convert snake_case or kebab-case value to a human-readable Title Case label."""
    if not value or not str(value).strip():
        return ""
    parts = re.split(r"[\s_-]+", str(value).strip())
    return " ".join(
        (w[0].upper() + w[1:].lower()) if len(w) > 1 else w.upper()
        for w in parts if w
    )


def narrative_display_name(aspect: str, entry_key: str, value: str = "") -> str:
    """
    Human-readable name for a semantic/narrative entry.
    Uses the canonical value (e.g. 'cinematic', 'golden_hour') in Title Case
    rather than unrelated invented words.
    """
    _ = aspect  # reserved for aspect-specific formatting later
    return title_case_label(value or entry_key or "")


def generate_blend_name(
    domain: str,
    prompt: str = "",
    *,
    existing_names: set[str] | None = None,
) -> str:
    """
    Generate a unique, sensible name for a blend. No underscores — resembles
    actual names (e.g. Suntor, Velvet). Tries: (1) combined prompt words;
    (2) invented word; (3) semantic domain+word fallback (never numeric).
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
    for i in range(200):
        word = _invent_word(seed + i * 4567)
        candidate = word[0].upper() + word[1:].lower() if len(word) > 1 else word.upper()
        if candidate not in existing:
            return candidate

    return generate_sensible_name(domain, prompt or domain, existing_names=existing, use_prefix=False)
