"""
Precise parsing of user instructions.
Interprets what the user is instructing from text/script/prompt.
"""
import re
from typing import Any

from .schema import InterpretedInstruction
from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    DEFAULT_PALETTE,
    DEFAULT_MOTION,
    DEFAULT_INTENSITY,
    DEFAULT_GRADIENT,
    DEFAULT_CAMERA,
    DEFAULT_SHAPE,
)

# Duration extraction: "5 seconds", "10s", "15 sec", "2 minutes", "1 min"
_DURATION_PATTERN = re.compile(
    r"(?:^|[^\w])"
    r"(\d+(?:\.\d+)?)\s*"
    r"(?:seconds?|secs?|s|minutes?|mins?|m)"
    r"(?:$|[^\w])",
    re.IGNORECASE,
)

# Style keywords (optional)
_STYLE_KEYWORDS: set[str] = {"cinematic", "anime", "abstract", "minimal", "realistic"}

# Tone keywords (optional)
_TONE_KEYWORDS: set[str] = {"dreamy", "dark", "bright", "calm", "energetic", "moody"}

# Negation: "not X", "no X", "avoid X"
_NEGATION_PATTERN = re.compile(
    r"\b(?:not|no|avoid|without)\s+([a-z]+)",
    re.IGNORECASE,
)


def _extract_words(prompt: str) -> list[str]:
    """Extract lowercase alphabetic words, preserving order."""
    return re.findall(r"[a-z]+", (prompt or "").lower())


def _extract_duration(prompt: str) -> float | None:
    """Extract duration in seconds from prompt. Returns None if not found."""
    match = _DURATION_PATTERN.search(prompt)
    if not match:
        return None
    val = float(match.group(1))
    text = match.group(0).lower()
    if "min" in text or text.strip().endswith("m"):
        val *= 60.0
    return val


def _extract_negations(prompt: str) -> tuple[list[str], list[str]]:
    """
    Extract negated terms. Returns (avoid_motion, avoid_palette).
    Maps keywords to their resolved values: "not calm" → avoid motion "slow".
    """
    avoid_motion: list[str] = []
    avoid_palette: list[str] = []
    for m in _NEGATION_PATTERN.finditer(prompt):
        term = m.group(1).lower()
        if term in KEYWORD_TO_MOTION:
            val = KEYWORD_TO_MOTION[term]
            if val not in avoid_motion:
                avoid_motion.append(val)
        if term in KEYWORD_TO_PALETTE:
            val = KEYWORD_TO_PALETTE[term]
            if val not in avoid_palette:
                avoid_palette.append(val)
    return avoid_motion, avoid_palette


def _resolve_palette(
    words: list[str],
    avoid_palette: list[str],
) -> str:
    """
    Resolve palette from keywords with precision.
    First match wins; excludes avoided palettes.
    """
    avoid_set = set(avoid_palette)
    for w in words:
        if w in KEYWORD_TO_PALETTE:
            p = KEYWORD_TO_PALETTE[w]
            if p not in avoid_set:
                return p
    return DEFAULT_PALETTE


def _resolve_motion(
    words: list[str],
    avoid_motion: list[str],
) -> str:
    """
    Resolve motion type from keywords with precision.
    First match wins; excludes avoided motions.
    """
    avoid_set = set(avoid_motion)
    for w in words:
        if w in KEYWORD_TO_MOTION:
            m = KEYWORD_TO_MOTION[w]
            if m not in avoid_set:
                return m
    return DEFAULT_MOTION


def _resolve_intensity(
    words: list[str],
) -> float:
    """
    Resolve intensity from keywords with precision.
    First match wins. Clamped to 0–1.
    """
    for w in words:
        if w in KEYWORD_TO_INTENSITY:
            return max(0.1, min(1.0, float(KEYWORD_TO_INTENSITY[w])))
    return DEFAULT_INTENSITY


def _resolve_gradient(words: list[str]) -> str:
    """Resolve gradient type from keywords."""
    for w in words:
        if w in KEYWORD_TO_GRADIENT:
            return KEYWORD_TO_GRADIENT[w]
    return DEFAULT_GRADIENT


def _resolve_camera(words: list[str]) -> str:
    """Resolve camera motion from keywords."""
    for w in words:
        if w in KEYWORD_TO_CAMERA:
            return KEYWORD_TO_CAMERA[w]
    return DEFAULT_CAMERA


def _resolve_shape(words: list[str]) -> str:
    """Resolve shape overlay from keywords."""
    for w in words:
        if w in KEYWORD_TO_SHAPE:
            return KEYWORD_TO_SHAPE[w]
    return DEFAULT_SHAPE


def _resolve_style(words: list[str]) -> str | None:
    """Extract style hint if present."""
    for w in words:
        if w in _STYLE_KEYWORDS:
            return w
    return None


def _resolve_tone(words: list[str]) -> str | None:
    """Extract tone hint if present."""
    for w in words:
        if w in _TONE_KEYWORDS:
            return w
    return None


def interpret_user_prompt(
    prompt: str,
    *,
    default_duration: float | None = None,
    seed: int | None = None,
) -> InterpretedInstruction:
    """
    Precisely interpret what the user is instructing.

    Parses: palette, motion, intensity, duration, style, tone, negations.
    Returns an InterpretedInstruction with resolved values.
    """
    prompt = (prompt or "").strip()
    raw_lower = prompt.lower()

    words = _extract_words(prompt)
    avoid_motion, avoid_palette = _extract_negations(prompt)
    duration = _extract_duration(prompt) or default_duration
    style = _resolve_style(words)
    tone = _resolve_tone(words)
    palette = _resolve_palette(words, avoid_palette)
    motion = _resolve_motion(words, avoid_motion)
    intensity = _resolve_intensity(words)
    gradient = _resolve_gradient(words)
    camera = _resolve_camera(words)
    shape = _resolve_shape(words)

    # Keywords that contributed (for learning and logging)
    contributing: list[str] = []
    for w in words:
        if w in KEYWORD_TO_PALETTE or w in KEYWORD_TO_MOTION or w in KEYWORD_TO_INTENSITY or w in KEYWORD_TO_GRADIENT or w in KEYWORD_TO_CAMERA or w in KEYWORD_TO_SHAPE:
            contributing.append(w)
    if not contributing:
        contributing = words[:10]  # fallback: first 10 words

    return InterpretedInstruction(
        palette_name=palette,
        motion_type=motion,
        intensity=intensity,
        gradient_type=gradient,
        camera_motion=camera,
        shape_overlay=shape,
        duration_seconds=duration,
        style=style,
        tone=tone,
        keywords=contributing,
        avoid_motion=avoid_motion,
        avoid_palette=avoid_palette,
        raw_prompt=raw_lower,
    )
