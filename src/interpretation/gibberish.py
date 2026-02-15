"""
Gibberish prompt detection for interpretation pipeline.

Filters random tokens and nonsensical prompts before storing in interpretations.
Preserves accuracy and precision of the interpretation registry.
"""
import re

# Known English words (common + video/creation domain). Extend as needed.
_KNOWN_WORDS: set[str] = {
    # Common
    "a", "an", "the", "and", "or", "but", "in", "on", "at", "to", "for", "of",
    "with", "by", "from", "as", "is", "was", "are", "were", "be", "been",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "can", "may", "might", "must", "shall", "about", "into", "through", "during",
    "video", "motion", "flow", "calm", "slow", "fast", "bright", "dark", "soft",
    "dreamy", "abstract", "cinematic", "minimal", "realistic", "style", "feel",
    "look", "vibe", "mood", "tone", "color", "colours", "blue", "red", "green",
    "ocean", "sunset", "night", "day", "golden", "hour", "warm", "cool",
    "gradient", "smooth", "gentle", "peaceful", "energetic", "dynamic",
    "static", "pan", "zoom", "tilt", "tracking", "handheld", "documentary",
    "neon", "pastel", "vintage", "modern", "retro", "nostalgic", "melancholic",
    "serene", "dramatic", "subtle", "bold", "muted", "vibrant", "intense",
    "explainer", "tutorial", "explain", "gradual", "symmetric", "silence",
    "ambient", "music", "sfx", "balanced", "slight", "bilateral", "centered",
    # Slang / dialect
    "lit", "chill", "vibing", "vibes", "lowkey", "glowy", "mellow",
}

# Regex: gibberish patterns (long consonant clusters, repeated syllables, etc.)
_GIBBERISH_PATTERN = re.compile(
    r"(?:"
    r"(?:[bcdfghjklmnpqrstvwxz]{4,})"  # 4+ consonants in a row
    r"|(?:([a-z]{2})\1{2,})"  # same 2-char syllable repeated 3+ times (e.g. rara)
    r"|(?:[qxjz]{2,})"  # rare letters repeated
    r")",
    re.IGNORECASE,
)


def _word_known_ratio(text: str) -> float:
    """Fraction of words (3+ chars) that are known. 0–1."""
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    if not words:
        return 1.0
    known = sum(1 for w in words if w in _KNOWN_WORDS)
    return known / len(words)


def _has_gibberish_pattern(text: str) -> bool:
    """True if text matches gibberish regex patterns."""
    return bool(_GIBBERISH_PATTERN.search(text or ""))


def _avg_word_length(text: str) -> float:
    """Average word length. Gibberish often has long invented words."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    if not words:
        return 0.0
    return sum(len(w) for w in words) / len(words)


def is_gibberish_prompt(prompt: str, *, strict: bool = False) -> bool:
    """
    True if prompt appears to be gibberish (random tokens, nonsense).

    Uses: known-word ratio, gibberish regex, avg word length, long unknown words.
    strict=True: reject more aggressively (e.g. for interpretation registry).
    """
    if not prompt or not isinstance(prompt, str):
        return True
    text = prompt.strip()
    if len(text) < 3:
        return False  # Very short prompts pass
    text_lower = text.lower()

    if _has_gibberish_pattern(text_lower):
        return True
    ratio = _word_known_ratio(text_lower)
    avg_len = _avg_word_length(text_lower)
    words = re.findall(r"[a-z]{3,}", text_lower)

    # Long unknown words (e.g. "lixakafereka", "liworazagura") strongly suggest gibberish
    long_unknown = [w for w in words if len(w) >= 10 and w not in _KNOWN_WORDS]
    if long_unknown:
        return True

    if strict:
        if ratio < 0.25 and avg_len > 6:
            return True
        if ratio < 0.15:
            return True
    else:
        if ratio < 0.15 and avg_len > 7:
            return True

    return False


def filter_gibberish_prompts(prompts: list[str], *, strict: bool = True) -> list[str]:
    """Return only non-gibberish prompts."""
    return [p for p in prompts if p and not is_gibberish_prompt(p, strict=strict)]
