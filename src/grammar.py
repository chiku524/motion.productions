"""Small grammar helpers for generated prompts (a/an agreement)."""
from __future__ import annotations

import functools
import re
from typing import Any, Callable

# Vowel letter but consonant ("yoo"/"w") sound: "a unicorn", "a user", "a one-off", "a European".
_A_SOUND = re.compile(r"^(uni|use|usu|uti|uro|ura|uku|ubi|eu|ewe|one(?![a-z])|once|ouija)", re.I)
# Consonant letter but vowel sound: "an hour", "an honest".
_AN_SOUND = re.compile(r"^(hour|honest|honou?r|heir|herb)", re.I)
# un- prefixes (unusual, undone, under) take "an"; "uni-" is handled above.
_UN_PREFIX = re.compile(r"^un(?!i)", re.I)
# Digits read with a vowel sound: 8, 11, 18, 80-89, 800...
_AN_DIGITS = re.compile(r"^(8|11(?!\d)|18(?!\d))")


def article(word: str) -> str:
    """Return 'a' or 'an' for the word that follows."""
    w = re.sub(r"^[^A-Za-z0-9]+", "", (word or "").strip())
    if not w:
        return "a"
    if w[0].isdigit():
        return "an" if _AN_DIGITS.match(w) else "a"
    if _AN_SOUND.match(w) or _UN_PREFIX.match(w):
        return "an"
    if _A_SOUND.match(w):
        return "a"
    return "an" if w[0].lower() in "aeiou" else "a"


def with_article(phrase: str) -> str:
    """'ivory' -> 'an ivory'."""
    p = (phrase or "").strip()
    return f"{article(p)} {p}" if p else p


_ART_RE = re.compile(r"(?<![\w'\-])(an?)(\s+)([A-Za-z0-9][\w'\-]*)", re.I)


def fix_articles(text: str | None) -> str | None:
    """Repair a/an agreement everywhere in a sentence (keeps capitalisation)."""
    if not text:
        return text

    def _sub(m: re.Match[str]) -> str:
        art, sp, word = m.group(1), m.group(2), m.group(3)
        want = article(word)
        if art.lower() == want:
            return m.group(0)
        out = want.capitalize() if art[0].isupper() else want
        return f"{out}{sp}{word}"

    return _ART_RE.sub(_sub, text)


def articles_fixed(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator: apply fix_articles to a prompt generator's string result (None passes through)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        res = fn(*args, **kwargs)
        return fix_articles(res) if isinstance(res, str) else res

    return wrapper