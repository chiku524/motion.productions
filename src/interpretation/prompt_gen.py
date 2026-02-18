"""
Generate diverse, user-like prompts for the interpretation workflow.
Includes slang, dialect, and informal variants to expand the linguistic registry.
Uses primitives + learned/extracted values from registries (learned colors, motion, etc.).
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

# Instructive templates: read as user instructions so interpretation → video is tested
INSTRUCTIVE_TEMPLATES = [
    "Create a {subject} scene with {mod}",
    "Show me a {subject} with {mod}",
    "Make something {subject} that feels {mod}",
    "I want a {subject} with {mod}",
    "Give me a {subject} with {mod} feel",
    "Render a {subject} with {mod}",
]


def _build_slot_pools_interpretation(knowledge: dict[str, Any] | None) -> dict[str, list[str]]:
    """Build per-slot pools from pure/blends for interpretation prompts (dynamic values each use)."""
    from ..knowledge.blend_names import is_semantic_name

    color = list(dict.fromkeys(KEYWORD_TO_PALETTE.keys()))
    motion = list(KEYWORD_TO_MOTION.keys())
    lighting = list(KEYWORD_TO_LIGHTING.keys())
    gradient = list(KEYWORD_TO_GRADIENT.keys())
    camera = list(KEYWORD_TO_CAMERA.keys())
    mood = list(dict.fromkeys(list(KEYWORD_TO_AUDIO_MOOD.keys()) + list(KEYWORD_TO_GENRE.keys())[:8]))

    if knowledge:
        # Prefer underused: sort by count ascending so lower-count entries get into the pool (mesh as playground).
        lc_items = [
            (d.get("name", "").strip(), d.get("count", 0))
            for _, d in (knowledge.get("learned_colors") or {}).items()
            if isinstance(d, dict) and (d.get("name") or "").strip()
        ]
        for name, _ in sorted(lc_items, key=lambda x: x[1]):  # ascending count
            if len(name) >= 2 and is_semantic_name(name):
                color.append(name)
        motion_list = knowledge.get("learned_motion") or []
        motion_list = sorted(motion_list, key=lambda m: m.get("count", 0) if isinstance(m, dict) else 0)
        for m in motion_list[:40]:
            if isinstance(m, dict):
                name = (m.get("name") or "").strip()
                if name and len(name) >= 2 and is_semantic_name(name):
                    motion.append(f"{name} motion")
                trend = (m.get("motion_trend") or "").strip()
                if trend and trend != "steady":
                    motion.append(f"{trend} drift")
        for item in (knowledge.get("learned_gradient") or [])[:15]:
            v = item.get("gradient_type") if isinstance(item, dict) else (item if isinstance(item, str) else None)
            if v and str(v).strip() and v not in gradient:
                gradient.append(str(v).strip())
        for item in (knowledge.get("learned_camera") or [])[:15]:
            v = (item.get("camera_motion") or item.get("motion_type")) if isinstance(item, dict) else (item if isinstance(item, str) else None)
            if v and str(v).strip() and v not in camera:
                camera.append(str(v).strip())

    return {
        "color": [c for c in color if c],
        "motion": [m for m in motion if m],
        "lighting": [l for l in lighting if l],
        "gradient": [g for g in gradient if g],
        "camera": [c for c in camera if c],
        "mood": [m for m in mood if m],
    }


# Slot-based instructive (same idea as automation): dynamic pure/blend values per template use
INSTRUCTIVE_SLOT = [
    "Create a {color} scene with {motion}",
    "Show me {color} with {lighting}",
    "Make something {motion} with {color} tones",
    "I want a {color} vibe, {mood}",
    "Create a {color} scene with {motion} and {lighting}",
    "Show me {color} with {motion}, {mood}",
    "Give me {motion} with {color} and {lighting}",
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


def _expand_from_knowledge(
    knowledge: dict[str, Any] | None,
    base_subjects: set[str],
) -> tuple[list[str], list[str]]:
    """
    Extract additional subjects and modifiers from learned/extracted registries.
    Returns (extra_subjects, extra_modifiers) for prompt generation.
    """
    if not knowledge:
        return [], []

    from ..knowledge.blend_names import is_semantic_name

    extra_subjects: list[str] = []
    extra_modifiers: list[str] = []

    # Learned colors — semantic names as modifiers (e.g. "Slate tones", "Ember palette")
    learned_colors = knowledge.get("learned_colors") or {}
    for _color_key, data in learned_colors.items():
        if isinstance(data, dict):
            name = data.get("name") or ""
            if name and isinstance(name, str) and len(name) >= 3 and is_semantic_name(name):
                extra_modifiers.append(f"{name} tones")
                extra_modifiers.append(f"{name} palette")

    # Learned motion profiles
    learned_motion = knowledge.get("learned_motion") or []
    for m in learned_motion:
        if isinstance(m, dict):
            name = m.get("name")
            trend = m.get("motion_trend", "")
            level = m.get("motion_level", 0)
            if name and isinstance(name, str) and len(name) >= 3 and is_semantic_name(name):
                extra_modifiers.append(f"{name} motion")
            if trend and trend != "steady":
                extra_modifiers.append(f"{trend} drift")
            if level and float(level) > 5:
                extra_modifiers.append("dynamic movement")

    # Proven keywords from learning stats
    by_keyword = knowledge.get("by_keyword") or {}
    for kw, stats in list(by_keyword.items())[:50]:
        if isinstance(stats, dict) and stats.get("count", 0) >= 2:
            if kw and isinstance(kw, str) and kw not in base_subjects and is_semantic_name(kw):
                extra_subjects.append(kw)

    # Proven palettes
    by_palette = knowledge.get("by_palette") or {}
    for pal, stats in list(by_palette.items())[:30]:
        if isinstance(stats, dict) and stats.get("count", 0) >= 1:
            if pal and isinstance(pal, str) and is_semantic_name(pal):
                extra_modifiers.append(f"{pal} style")

    # Learned gradient/camera (API returns list of strings or list of dicts)
    for learned_list, suffix in [
        (knowledge.get("learned_gradient") or [], "gradient"),
        (knowledge.get("learned_camera") or [], "motion"),
    ]:
        for item in learned_list[:15]:
            val = None
            if isinstance(item, str) and item.strip():
                val = item.strip()
            elif isinstance(item, dict):
                val = (
                    item.get("name")
                    or item.get("gradient_type")
                    or item.get("camera_motion")
                    or item.get("motion_type")
                )
            if val and isinstance(val, str) and is_semantic_name(val):
                extra_modifiers.append(f"{val} {suffix}")

    extra_subjects = list(dict.fromkeys(s for s in extra_subjects if s))
    extra_modifiers = list(dict.fromkeys(m for m in extra_modifiers if m))
    return extra_subjects, extra_modifiers


def _is_near_duplicate(prompt: str, avoid: set[str], threshold: float = 0.8) -> bool:
    """True if prompt shares >threshold fraction of words with any avoid item."""
    words_a = set(w.lower() for w in prompt.split() if len(w) > 1)
    if not words_a:
        return False
    for other in avoid:
        words_b = set(w.lower() for w in other.split() if len(w) > 1)
        if words_b and len(words_a & words_b) / len(words_a) >= threshold:
            return True
    return False


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
    instructive_ratio: float = 0.5,
) -> str | None:
    """
    Generate one user-like prompt for the interpretation workflow.
    Uses primitives + learned/extracted values (colors, motion, etc.) from registries.
    When instructive_ratio > 0, that fraction uses instructive phrasing (Create/Show/Make).
    """
    if seed is not None:
        random.seed(seed)
    avoid = avoid or set()

    domain_kw = _get_domain_keywords()
    base_subjects = domain_kw["palette"] + domain_kw["motion"][:8]
    base_modifiers = (
        domain_kw["motion"] + domain_kw["lighting"] + domain_kw["genre"]
        + domain_kw["gradient"][:4] + domain_kw["pacing"][:4]
    )
    subjects = [s for s in base_subjects if not s.startswith("_")]
    modifiers = [m for m in base_modifiers if not m.startswith("_")]

    # Expand from learned/extracted registries
    extra_subs, extra_mods = _expand_from_knowledge(
        knowledge, base_subjects=set(s.lower() for s in subjects)
    )
    subjects = list(dict.fromkeys(subjects + extra_subs))
    modifiers = list(dict.fromkeys(modifiers + extra_mods))

    if not subjects or not modifiers:
        return None

    variant_mode = "slang" if use_slang and secure_random() < 0.35 else "standard"
    if use_dialect and secure_random() < 0.2:
        variant_mode = "dialect"

    use_instructive = instructive_ratio > 0 and secure_random() < instructive_ratio
    slot_pools = _build_slot_pools_interpretation(knowledge) if use_instructive else None
    use_slot_based = (
        use_instructive
        and slot_pools
        and all(slot_pools.get(k) for k in ("color", "motion", "lighting"))
        and secure_random() < 0.6
    )

    template_list = INSTRUCTIVE_TEMPLATES if use_instructive else TEMPLATES

    max_attempts = 150
    for _ in range(max_attempts):
        if use_slot_based and slot_pools:
            filled = {k: secure_choice(pool) for k, pool in slot_pools.items() if pool}
            for k in ("gradient", "camera", "mood"):
                if k not in filled and slot_pools.get("motion"):
                    filled[k] = secure_choice(slot_pools["motion"])
            if use_slang and secure_random() < 0.3:
                for k in list(filled.keys()):
                    filled[k] = _apply_variant(filled[k], "slang")
            tmpl = secure_choice(INSTRUCTIVE_SLOT)
            try:
                prompt = tmpl.format(**{k: filled.get(k, "") for k in ("color", "motion", "lighting", "gradient", "camera", "mood")})
            except (KeyError, ValueError):
                prompt = None
        else:
            prompt = None

        if not prompt:
            sub = secure_choice(subjects)
            mod = secure_choice(modifiers)
            sub = _apply_variant(sub, variant_mode)
            mod = _apply_variant(mod, variant_mode)
            tmpl = secure_choice(template_list)
            try:
                prompt = tmpl.format(subject=sub, mod=mod)
            except (KeyError, ValueError):
                prompt = f"Create a {sub} with {mod}" if use_instructive else f"{sub} with {mod}"

        if prompt:
            prompt = prompt.strip()
            if prompt and prompt not in avoid and not _is_near_duplicate(prompt, avoid):
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
