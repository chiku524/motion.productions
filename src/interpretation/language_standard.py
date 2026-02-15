"""
Language standard for the interpretation loop.

Defines the set algorithms and functions for interpreting prompts in a standard
of language: primarily English, with support for dialects and slang/lingo.
All resolution uses origin/primitive keyword mappings plus built-in and
extracted (linguistic registry) values.

Algorithm order:
  1. Normalize prompt (trim, length cap, extract words).
  2. For each domain: lookup = merge(base_keywords, builtin_linguistic, fetched_registry).
  3. Resolve each word via lookup; first match wins per domain.
  4. Negations and duration use dedicated patterns.
  5. Extracted mappings (span → canonical) feed linguistic registry growth.
"""

import re
from typing import Any

# -----------------------------------------------------------------------------
# 1. Built-in slang/lingo and dialect (seed for linguistic registry)
# Canonical values align with procedural KEYWORD_* origins.
# -----------------------------------------------------------------------------

BUILTIN_LINGUISTIC: dict[str, dict[str, str]] = {
    "palette": {"lit": "warm_sunset", "chill": "ocean", "vibing": "neon", "mellow": "dreamy", "lowkey": "night"},
    "motion": {"chill": "slow", "lit": "pulse", "mellow": "flow", "vibing": "pulse"},
    "lighting": {"lit": "documentary", "lowkey": "noir", "chill": "golden_hour"},
}

# Dialect: normalize to one form for lookup (US preferred; parser accepts both)
DIALECT_NORMALIZE: dict[str, str] = {
    "colour": "color",
    "grey": "gray",
    "centre": "center",
    "realise": "realize",
    "analyse": "analyze",
}

# Slang set for variant_type classification (linguistic extraction)
SLANG_SPANS: set[str] = {"lit", "chill", "vibing", "poppin", "lowkey", "glowy", "mellow"}

# Domains that use the linguistic merge (same order as parser resolution)
STANDARD_DOMAINS: tuple[str, ...] = (
    "palette",
    "motion",
    "lighting",
    "gradient",
    "camera",
    "genre",
    "shape",
    "pacing",
    "composition_balance",
    "composition_symmetry",
    "tension",
    "audio_tempo",
    "audio_mood",
    "audio_presence",
)


# Common contractions → expanded form (for negation/mood extraction)
_CONTRACTIONS: dict[str, str] = {
    "don't": "do not", "dont": "do not",
    "doesn't": "does not", "doesnt": "does not",
    "didn't": "did not", "didnt": "did not",
    "won't": "will not", "wont": "will not",
    "can't": "cannot", "cant": "cannot",
    "couldn't": "could not", "couldnt": "could not",
    "shouldn't": "should not", "shouldnt": "should not",
    "wouldn't": "would not", "wouldnt": "would not",
    "isn't": "is not", "isnt": "is not",
    "aren't": "are not", "arent": "are not",
    "wasn't": "was not", "wasnt": "was not",
    "weren't": "were not", "werent": "were not",
    "hasn't": "has not", "hasnt": "has not",
    "haven't": "have not", "havent": "have not",
    "hadn't": "had not", "hadnt": "had not",
    "it's": "it is", "its": "it is",
    "that's": "that is", "thats": "that is",
    "there's": "there is", "theres": "there is",
    "what's": "what is", "whats": "what is",
}


def expand_contractions(text: str) -> str:
    """
    Expand common contractions so negation and mood patterns match correctly.
    E.g. "don't want calm" → "do not want calm" so "not" is available for negation.
    """
    if not text:
        return text
    s = text
    for cont, exp in _CONTRACTIONS.items():
        s = re.sub(r"\b" + re.escape(cont) + r"\b", exp, s, flags=re.IGNORECASE)
    return s


def normalize_prompt_for_interpretation(prompt: str, max_length: int = 2000) -> str:
    """
    Normalize raw input before interpretation.
    Algorithm: expand contractions, strip, length cap.
    Contractions expanded so negation patterns (not X, no X) match correctly.
    """
    if not isinstance(prompt, str):
        return ""
    s = expand_contractions(prompt.strip())
    if len(s) > max_length:
        s = s[:max_length].rstrip()
    return s


def normalize_word_for_lookup(word: str) -> str:
    """
    Normalize a single word for lookup (e.g. dialect variant → canonical form).
    Used so "colour" and "color" both resolve.
    """
    if not word:
        return ""
    w = word.lower().strip()
    return DIALECT_NORMALIZE.get(w, w)


def merge_linguistic_lookup(
    domain: str,
    base_keywords: dict[str, str],
    builtin: dict[str, dict[str, str]] | None = None,
    fetched: dict[str, dict[str, str]] | None = None,
) -> dict[str, str]:
    """
    Merge lookup for one domain: origin/primitive keywords first, then built-in
    slang/dialect, then fetched linguistic registry (extracted from past runs).
    Order ensures primitives are the standard; learned mappings extend coverage.
    """
    out = dict(base_keywords)
    builtin = builtin or {}
    if domain in builtin:
        out.update(builtin[domain])
    if fetched and domain in fetched:
        out.update(fetched[domain])
    return out


def resolve_word_to_canonical(
    word: str,
    lookup: dict[str, str],
    *,
    normalize_dialect: bool = True,
) -> str | None:
    """
    Resolve a single word to canonical value using the merged lookup.
    Returns None if no mapping; otherwise the canonical value.
    """
    w = normalize_word_for_lookup(word) if normalize_dialect else word.lower().strip()
    return lookup.get(w)


def infer_variant_type(span: str, canonical: str) -> str:
    """
    Classify how span maps to canonical: synonym, dialect, or slang.
    Used when extracting linguistic mappings for registry growth.
    """
    s, c = span.lower(), canonical.lower()
    if s == c:
        return "synonym"
    for a, b in DIALECT_NORMALIZE.items():
        if (s == a and c == b) or (s == b and c == a):
            return "dialect"
    if s in SLANG_SPANS:
        return "slang"
    return "synonym"
