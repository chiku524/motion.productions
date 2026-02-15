"""
Linguistic registry: extraction and growth from prompts.

Extracts (span, canonical, domain) from prompt + instruction pairs.
Enables interpretation workflow to learn synonyms, slang, dialect.
"""
from typing import Any

from .schema import InterpretedInstruction
from .parser import _merge_linguistic
from .language_standard import infer_variant_type as _infer_variant_type
from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    KEYWORD_TO_LIGHTING,
    KEYWORD_TO_GENRE,
    KEYWORD_TO_PACING,
    KEYWORD_TO_COMPOSITION_BALANCE,
    KEYWORD_TO_COMPOSITION_SYMMETRY,
    KEYWORD_TO_TENSION,
    KEYWORD_TO_AUDIO_TEMPO,
    KEYWORD_TO_AUDIO_MOOD,
    KEYWORD_TO_AUDIO_PRESENCE,
)

# Domain -> (keyword_dict, instruction_field)
_DOMAIN_MAPPINGS: list[tuple[str, dict[str, str], str]] = [
    ("palette", KEYWORD_TO_PALETTE, "palette_name"),
    ("motion", KEYWORD_TO_MOTION, "motion_type"),
    ("lighting", KEYWORD_TO_LIGHTING, "lighting_preset"),
    ("gradient", KEYWORD_TO_GRADIENT, "gradient_type"),
    ("camera", KEYWORD_TO_CAMERA, "camera_motion"),
    ("shape", KEYWORD_TO_SHAPE, "shape_overlay"),
    ("genre", KEYWORD_TO_GENRE, "genre"),
    ("pacing", KEYWORD_TO_PACING, "pacing_factor"),
    ("composition_balance", KEYWORD_TO_COMPOSITION_BALANCE, "composition_balance"),
    ("composition_symmetry", KEYWORD_TO_COMPOSITION_SYMMETRY, "composition_symmetry"),
    ("tension", KEYWORD_TO_TENSION, "tension_curve"),
    ("audio_tempo", KEYWORD_TO_AUDIO_TEMPO, "audio_tempo"),
    ("audio_mood", KEYWORD_TO_AUDIO_MOOD, "audio_mood"),
    ("audio_presence", KEYWORD_TO_AUDIO_PRESENCE, "audio_presence"),
]


def extract_linguistic_mappings(
    prompt: str,
    instruction: InterpretedInstruction,
) -> list[dict[str, Any]]:
    """
    Extract (span, canonical, domain) from a prompt and its interpretation.
    Returns list of dicts with span, canonical, domain, variant_type.
    """
    words = [w.lower() for w in (prompt or "").split() if len(w) >= 2]
    if not words:
        return []

    instr_dict = instruction.__dict__ if hasattr(instruction, "__dict__") else {}
    if hasattr(instruction, "__dataclass_fields__"):
        instr_dict = {k: getattr(instruction, k) for k in instruction.__dataclass_fields__}

    seen: set[tuple[str, str]] = set()
    out: list[dict[str, Any]] = []

    for domain, kw_dict, field_name in _DOMAIN_MAPPINGS:
        resolved = instr_dict.get(field_name)
        if resolved is None:
            continue
        canonical = str(resolved)
        # Use merged lookup (base + builtin + fetched) so we capture slang/dialect
        lookup = _merge_linguistic(domain, kw_dict, None)
        for w in words:
            if w in lookup:
                val = lookup[w]
                if (w, domain) not in seen:
                    seen.add((w, domain))
                    out.append({
                        "span": w,
                        "canonical": val,
                        "domain": domain,
                        "variant_type": _infer_variant_type(w, val),
                    })

    # Tone/style fallback: if instruction has tone and prompt has mood word
    tone = instr_dict.get("tone") or ""
    style = instr_dict.get("style") or ""
    if tone:
        for w in words:
            if w in ("dreamy", "dark", "bright", "calm", "energetic", "moody"):
                if (w, "tone") not in seen:
                    seen.add((w, "tone"))
                    out.append({
                        "span": w,
                        "canonical": tone,
                        "domain": "tone",
                        "variant_type": "synonym",
                    })
    if style:
        for w in words:
            if w in ("cinematic", "abstract", "minimal", "realistic", "anime"):
                if (w, "style") not in seen:
                    seen.add((w, "style"))
                    out.append({
                        "span": w,
                        "canonical": style,
                        "domain": "style",
                        "variant_type": "synonym",
                    })

    return out


def infer_variant_type(span: str, canonical: str) -> str:
    """Infer variant_type from span vs canonical (language standard)."""
    return _infer_variant_type(span, canonical)
