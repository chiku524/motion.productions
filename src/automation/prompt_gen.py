"""
Procedural prompt generator. Uses keyword data + learned discoveries for dynamic exploration.
Produces diverse prompts for automated knowledge-building.
"""
import random
from typing import Any, Iterator

from ..random_utils import secure_choice, secure_random

from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    KEYWORD_TO_LIGHTING,
    KEYWORD_TO_GENRE,
    KEYWORD_TO_STYLE,
    KEYWORD_TO_SHOT,
    KEYWORD_TO_TRANSITION,
    KEYWORD_TO_PACING,
    KEYWORD_TO_COMPOSITION_BALANCE,
    KEYWORD_TO_COMPOSITION_SYMMETRY,
    KEYWORD_TO_TENSION,
    KEYWORD_TO_AUDIO_TEMPO,
    KEYWORD_TO_AUDIO_MOOD,
    KEYWORD_TO_AUDIO_PRESENCE,
)

# Base subjects (palette-suggesting keywords)
SUBJECTS_BASE = sorted(set(KEYWORD_TO_PALETTE.keys()))

# All modifier categories — every domain from INTENDED_LOOP represented
_MODS_MOTION = [k for k in KEYWORD_TO_MOTION.keys() if k not in SUBJECTS_BASE]
_MODS_INTENSITY = [k for k in KEYWORD_TO_INTENSITY.keys() if k not in SUBJECTS_BASE]
_MODS_GRADIENT = [k for k in KEYWORD_TO_GRADIENT.keys() if k not in SUBJECTS_BASE]
_MODS_CAMERA = [k for k in KEYWORD_TO_CAMERA.keys() if k not in SUBJECTS_BASE]
_MODS_SHAPE = [k for k in KEYWORD_TO_SHAPE.keys() if k not in SUBJECTS_BASE]
_MODS_LIGHTING = list(KEYWORD_TO_LIGHTING.keys())
_MODS_GENRE = list(KEYWORD_TO_GENRE.keys())
_MODS_STYLE = list(KEYWORD_TO_STYLE.keys())
_MODS_SHOT = list(KEYWORD_TO_SHOT.keys())
_MODS_TRANSITION = list(KEYWORD_TO_TRANSITION.keys())
# Temporal: pacing
_MODS_PACING = list(KEYWORD_TO_PACING.keys())
# Composition: balance, symmetry
_MODS_COMPOSITION = list(KEYWORD_TO_COMPOSITION_BALANCE.keys()) + [k for k in KEYWORD_TO_COMPOSITION_SYMMETRY.keys() if k not in KEYWORD_TO_COMPOSITION_BALANCE]
# Narrative: tension curve
_MODS_TENSION = list(KEYWORD_TO_TENSION.keys())
# Audio: tempo, mood, presence
_MODS_AUDIO = list(KEYWORD_TO_AUDIO_TEMPO.keys()) + list(KEYWORD_TO_AUDIO_MOOD.keys()) + list(KEYWORD_TO_AUDIO_PRESENCE.keys())
_MODS_AUDIO = list(dict.fromkeys(m for m in _MODS_AUDIO if m not in SUBJECTS_BASE))

MODIFIERS_BASE = (
    _MODS_MOTION + _MODS_INTENSITY + _MODS_GRADIENT + _MODS_CAMERA + _MODS_SHAPE
    + _MODS_LIGHTING + _MODS_GENRE + _MODS_STYLE + _MODS_SHOT + _MODS_TRANSITION
    + _MODS_PACING + _MODS_COMPOSITION + _MODS_TENSION + _MODS_AUDIO
)
MODIFIERS_BASE = [m for m in MODIFIERS_BASE if m not in SUBJECTS_BASE]
MODIFIERS_BASE = list(dict.fromkeys(MODIFIERS_BASE))  # dedupe preserve order

# Templates: single, double, and triple modifier for maximum variety (interpretation workflow)
TEMPLATES_SINGLE = [
    "{subject}",
    "{subject}, {modifier}",
    "{subject} {modifier}",
    "{modifier} {subject}",
    "{subject} with {modifier}",
    "{modifier} atmosphere {subject}",
]
TEMPLATES_DOUBLE = [
    "{subject}, {mod1} and {mod2}",
    "{subject} {mod1} {mod2}",
    "{mod1} {subject} {mod2}",
    "{subject} with {mod1} and {mod2}",
    "{mod1}, {mod2} {subject}",
    "{subject} in {mod1} {mod2} style",
]
TEMPLATES_TRIPLE = [
    "{subject} with {mod1}, {mod2} and {mod3}",
    "{mod1} {mod2} {subject} {mod3}",
    "{subject} — {mod1}, {mod2}, {mod3}",
]
TEMPLATES_ALL = TEMPLATES_SINGLE + TEMPLATES_DOUBLE + TEMPLATES_TRIPLE

# Instructive templates: read as user instructions (create/show/make) so the loop tests interpretation → video.
# Same vocabulary (subject/modifier) so the parser resolves palette, motion, lighting, etc.
INSTRUCTIVE_SINGLE = [
    "Create a {subject} scene with {modifier}",
    "Show me a {subject} with {modifier}",
    "Make something {subject} that feels {modifier}",
    "I want a {subject} vibe with {modifier}",
    "Give me a {subject} with {modifier} feel",
    "Render a {subject} look with {modifier}",
]
INSTRUCTIVE_DOUBLE = [
    "Create a {subject} scene with {mod1} and {mod2}",
    "Show me something {subject} with {mod1} and {mod2}",
    "Make a {subject} that feels {mod1} and {mod2}",
    "I want a {subject} with {mod1}, {mod2}",
    "Give me a {subject} with {mod1} and {mod2} motion",
    "Render a {subject} in {mod1} {mod2} style",
]
INSTRUCTIVE_TRIPLE = [
    "Create a {subject} with {mod1}, {mod2} and {mod3}",
    "Show me a {subject} that has {mod1}, {mod2} and {mod3}",
    "Make something {subject} with {mod1}, {mod2} and {mod3}",
]
INSTRUCTIVE_ALL = INSTRUCTIVE_SINGLE + INSTRUCTIVE_DOUBLE + INSTRUCTIVE_TRIPLE

# Slot-based instructive templates: each slot filled from pure/blend pools so each use gets different values.
# Slots: color (palette/learned colors), motion, lighting, gradient, camera, mood.
INSTRUCTIVE_SLOT_SINGLE = [
    "Create a {color} scene with {motion}",
    "Show me {color} with {lighting}",
    "Make something {motion} with {color} tones",
    "I want a {color} vibe, {mood}",
    "Give me {motion} and {lighting}",
]
INSTRUCTIVE_SLOT_DOUBLE = [
    "Create a {color} scene with {motion} and {lighting}",
    "Show me {color} with {motion}, {mood}",
    "Make a {color} that feels {motion} and {lighting}",
    "I want {color} with {gradient} and {camera}",
    "Give me {motion} with {color} and {lighting}",
    "Render a {color} look with {motion} and {mood}",
]
INSTRUCTIVE_SLOT_TRIPLE = [
    "Create a {color} with {motion}, {lighting} and {mood}",
    "Show me {color} with {motion}, {lighting} and {gradient}",
    "Make something {color} with {motion}, {lighting} and {camera}",
]
INSTRUCTIVE_SLOT_ALL = INSTRUCTIVE_SLOT_SINGLE + INSTRUCTIVE_SLOT_DOUBLE + INSTRUCTIVE_SLOT_TRIPLE


def _build_slot_pools(knowledge: dict[str, Any] | None) -> dict[str, list[str]]:
    """
    Build per-slot pools from pure elements and blends (registry-first, then origin/keywords).
    Each template use picks different values from these pools so prompts stay dynamic.
    """
    from ..knowledge.blend_names import is_semantic_name

    # Color: palette keywords + learned color names (parser resolves via keywords or linguistic registry)
    color = list(dict.fromkeys(SUBJECTS_BASE))
    motion = list(dict.fromkeys(k for k in KEYWORD_TO_MOTION.keys()))
    lighting = list(KEYWORD_TO_LIGHTING.keys())
    gradient = list(KEYWORD_TO_GRADIENT.keys())
    camera = list(KEYWORD_TO_CAMERA.keys())
    mood = list(KEYWORD_TO_AUDIO_MOOD.keys()) + list(KEYWORD_TO_GENRE.keys())[:8]
    mood = list(dict.fromkeys(mood))

    if knowledge:
        # Learned colors: names as display (e.g. "Slate", "Ocean"); parser may resolve via hints or linguistic
        for _key, data in (knowledge.get("learned_colors") or {}).items():
            if isinstance(data, dict):
                name = (data.get("name") or "").strip()
                if name and len(name) >= 2 and is_semantic_name(name):
                    color.append(name)
        # Learned motion: names and trend phrases
        for m in (knowledge.get("learned_motion") or [])[:40]:
            if isinstance(m, dict):
                name = (m.get("name") or "").strip()
                if name and len(name) >= 2 and is_semantic_name(name):
                    motion.append(f"{name} motion")
                trend = (m.get("motion_trend") or "").strip()
                if trend and trend != "steady":
                    motion.append(f"{trend} drift")
        # Gradient/camera from API (learned + origin)
        for item in (knowledge.get("learned_gradient") or [])[:15]:
            v = item.get("gradient_type") if isinstance(item, dict) else (item if isinstance(item, str) else None)
            if v and str(v).strip() and v not in gradient:
                gradient.append(str(v).strip())
        for item in (knowledge.get("origin_gradient") or [])[:8]:
            v = item if isinstance(item, str) else (item.get("gradient_type") if isinstance(item, dict) else None)
            if v and str(v).strip() and v not in gradient:
                gradient.append(str(v).strip())
        for item in (knowledge.get("learned_camera") or [])[:15]:
            v = (item.get("camera_motion") or item.get("motion_type")) if isinstance(item, dict) else (item if isinstance(item, str) else None)
            if v and str(v).strip() and v not in camera:
                camera.append(str(v).strip())
        for item in (knowledge.get("origin_camera") or [])[:8]:
            v = item if isinstance(item, str) else (item.get("camera_motion") or item.get("motion_type"))
            if v and str(v).strip() and v not in camera:
                camera.append(str(v).strip())
        # Pure sound mesh: discovered per-instant sounds — use tone/name for mood slot (drives combination exploration)
        for s in (knowledge.get("static_sound") or [])[:30]:
            if isinstance(s, dict):
                name = (s.get("name") or "").strip()
                tone = (s.get("tone") or "").strip().lower()
                if name and len(name) >= 2 and is_semantic_name(name):
                    mood.append(name)
                if tone and tone not in ("silent", "silence") and tone not in mood:
                    mood.append(tone)

    return {
        "color": [c for c in color if c],
        "motion": [m for m in motion if m],
        "lighting": [l for l in lighting if l],
        "gradient": [g for g in gradient if g],
        "camera": [c for c in camera if c],
        "mood": [m for m in mood if m],
    }


def _expand_from_knowledge(knowledge: dict[str, Any] | None) -> tuple[list[str], list[str]]:
    """
    Extract additional subjects and modifiers from learned knowledge.
    Returns (extra_subjects, extra_modifiers).
    """
    if not knowledge:
        return [], []

    extra_subjects: list[str] = []
    extra_modifiers: list[str] = []

    from ..knowledge.blend_names import is_semantic_name

    # Learned color names — use only semantic names (skip gibberish like "liworazagura")
    learned_colors = knowledge.get("learned_colors") or {}
    for color_key, data in learned_colors.items():
        if isinstance(data, dict):
            name = data.get("name") or color_key
            if name and isinstance(name, str) and len(name) >= 3 and is_semantic_name(name):
                extra_modifiers.append(f"{name} tones")
                extra_modifiers.append(f"{name} palette")

    # Learned motion profiles — use only semantic names (skip gibberish)
    learned_motion = knowledge.get("learned_motion") or []
    for m in learned_motion:
        if isinstance(m, dict):
            name = m.get("name")
            trend = m.get("motion_trend", "")
            level = m.get("motion_level", 0)
            if name and isinstance(name, str) and len(name) >= 3 and is_semantic_name(name):
                extra_modifiers.append(f"{name} motion")
            # Phrase from motion characteristics
            if trend and trend != "steady":
                extra_modifiers.append(f"{trend} drift")
            if level and float(level) > 5:
                extra_modifiers.append("dynamic movement")

    # Learned audio (blended): mood/tempo/presence phrases for richer prompts
    for a in (knowledge.get("learned_audio") or [])[:20]:
        if isinstance(a, dict):
            m = (a.get("mood") or "").strip()
            t = (a.get("tempo") or "").strip()
            if m and m not in extra_modifiers:
                extra_modifiers.append(f"{m} mood")
            if t and t != "medium" and f"{t} tempo" not in extra_modifiers:
                extra_modifiers.append(f"{t} tempo")

    # Pure sound mesh: discovered sound names/tone as modifiers
    for s in (knowledge.get("static_sound") or [])[:15]:
        if isinstance(s, dict):
            name = (s.get("name") or "").strip()
            if name and len(name) >= 2 and is_semantic_name(name):
                extra_modifiers.append(f"{name} sound")
                extra_modifiers.append(f"{name} tones")

    # Proven keywords from learning stats — only semantic (skip gibberish)
    by_keyword = knowledge.get("by_keyword") or {}
    for kw, stats in list(by_keyword.items())[:50]:
        if isinstance(stats, dict) and stats.get("count", 0) >= 2:
            if kw and isinstance(kw, str) and kw not in SUBJECTS_BASE and is_semantic_name(kw):
                extra_subjects.append(kw)

    # Proven palettes — only semantic names
    by_palette = knowledge.get("by_palette") or {}
    for pal, stats in list(by_palette.items())[:30]:
        if isinstance(stats, dict) and stats.get("count", 0) >= 1:
            if pal and isinstance(pal, str) and is_semantic_name(pal):
                extra_modifiers.append(f"{pal} style")

    # Interpretation registry: reuse short natural-language phrases (linguistic growth)
    for item in (knowledge.get("interpretation_prompts") or [])[:25]:
        if not isinstance(item, dict):
            continue
        prompt = (item.get("prompt") or "").strip()
        if not prompt or len(prompt) < 10 or len(prompt) > 45:
            continue
        words = prompt.split()
        if len(words) < 2 or len(words) > 6:
            continue
        # Skip imperative starts (full-sentence prompts); keep phrase-like fragments
        low = prompt.lower()
        if low.startswith(("create ", "show ", "make ", "give ", "render ", "i want ")):
            continue
        if any(len(w) > 12 and not is_semantic_name(w) for w in words if w.isalpha()):
            continue
        extra_modifiers.append(prompt)

    # Dedupe
    extra_subjects = list(dict.fromkeys(s for s in extra_subjects if s))
    extra_modifiers = list(dict.fromkeys(m for m in extra_modifiers if m))
    return extra_subjects, extra_modifiers


def _word_overlap_ratio(a: str, b: str) -> float:
    """Fraction of words in a that also appear in b (0–1). Used for near-duplicate detection."""
    words_a = set(w.lower() for w in a.split() if len(w) > 1)
    words_b = set(w.lower() for w in b.split() if len(w) > 1)
    if not words_a:
        return 0.0
    return len(words_a & words_b) / len(words_a)


def _is_near_duplicate(prompt: str, avoid: set[str], threshold: float = 0.8) -> bool:
    """True if prompt shares >threshold fraction of words with any avoid item."""
    for other in avoid:
        if _word_overlap_ratio(prompt, other) >= threshold:
            return True
    return False


def generate_procedural_prompt(
    *,
    subjects: list[str] | None = None,
    modifiers: list[str] | None = None,
    knowledge: dict[str, Any] | None = None,
    seed: int | None = None,
    avoid: set[str] | None = None,
    instructive_ratio: float = 0.0,
) -> str | None:
    """
    Generate one prompt by combining subject + modifier(s) from keyword data and learned discoveries.
    When knowledge is provided, uses learned colors, motion profiles, and proven keywords.
    When instructive_ratio > 0, that fraction of attempts use instructive templates (e.g. "Create a
    calm ocean scene with gentle waves") so the loop tests interpretation → video.
    Returns None if no new combination found (avoid set exhausted).
    """
    if seed is not None:
        random.seed(seed)

    avoid = avoid or set()

    # Build subject and modifier pools (static + dynamic from knowledge)
    if subjects is not None and modifiers is not None:
        sub_pool = list(subjects)
        mod_pool = list(modifiers)
    else:
        sub_pool = list(SUBJECTS_BASE)
        mod_pool = list(MODIFIERS_BASE)
        extra_subs, extra_mods = _expand_from_knowledge(knowledge)
        sub_pool = list(dict.fromkeys(sub_pool + extra_subs))
        mod_pool = list(dict.fromkeys(mod_pool + extra_mods))

    if not sub_pool or not mod_pool:
        return None

    # Prefer modifiers that map to different palettes/motion (wider interpretation spread)
    def _pick_diverse_mods(n: int, bias_audio: bool = False) -> list[str]:
        chosen: list[str] = []
        pool = list(mod_pool)
        if bias_audio and _MODS_AUDIO:
            first = secure_choice(_MODS_AUDIO)
            if first not in chosen:
                chosen.append(first)
        for _ in range(n - len(chosen)):
            if not pool:
                break
            candidates = [m for m in pool if m not in chosen] or pool
            m = secure_choice(candidates)
            chosen.append(m)
        return chosen

    def _format_instructive(sub: str, m1: str, m2: str, m3: str) -> str:
        r = secure_random()
        if r < 0.25 and m1 != m2 and m2 != m3 and m1 != m3:
            tmpl = secure_choice(INSTRUCTIVE_TRIPLE)
            try:
                return tmpl.format(subject=sub, mod1=m1, mod2=m2, mod3=m3)
            except (KeyError, ValueError):
                return f"Create a {sub} with {m1}, {m2} and {m3}"
        if r < 0.6 and m1 != m2:
            tmpl = secure_choice(INSTRUCTIVE_DOUBLE)
            try:
                return tmpl.format(subject=sub, mod1=m1, mod2=m2)
            except (KeyError, ValueError):
                return f"Create a {sub} scene with {m1} and {m2}"
        tmpl = secure_choice(INSTRUCTIVE_SINGLE)
        try:
            return tmpl.format(subject=sub, modifier=m1)
        except (KeyError, ValueError):
            return f"Create a {sub} scene with {m1}"

    def _format_slot_instructive(slots: dict[str, list[str]]) -> str | None:
        """Format a slot-based instructive template with random values from each pool."""
        required = {"color", "motion", "lighting"}
        if not all(slots.get(k) for k in required):
            return None
        filled = {k: secure_choice(pool) for k, pool in slots.items() if pool}
        # Templates may use gradient, camera, mood; fallback to motion/lighting if a slot is missing
        for k in ("gradient", "camera", "mood"):
            if k not in filled and slots.get("motion"):
                filled[k] = secure_choice(slots["motion"])
        tmpl = secure_choice(INSTRUCTIVE_SLOT_ALL)
        try:
            return tmpl.format(**{k: filled.get(k, "") for k in ("color", "motion", "lighting", "gradient", "camera", "mood")})
        except (KeyError, ValueError):
            return None

    max_attempts = 200
    bias_audio = secure_random() < 0.18  # 18% of runs: ensure at least one audio modifier
    use_instructive = instructive_ratio > 0 and secure_random() < instructive_ratio
    slot_pools = _build_slot_pools(knowledge) if use_instructive else None
    use_slot_based = (
        use_instructive
        and slot_pools
        and all(slot_pools.get(k) for k in ("color", "motion", "lighting"))
        and secure_random() < 0.7
    )

    for _ in range(max_attempts):
        sub = secure_choice(sub_pool)
        mods = _pick_diverse_mods(3, bias_audio=bias_audio)
        mod1 = mods[0] if mods else secure_choice(mod_pool)
        mod2 = mods[1] if len(mods) > 1 else mod1
        mod3 = mods[2] if len(mods) > 2 else mod2

        if use_slot_based and slot_pools:
            prompt = _format_slot_instructive(slot_pools)
        elif use_instructive:
            prompt = _format_instructive(sub, mod1, mod2, mod3)
        else:
            # Pick template: 40% double, 25% triple (when we have 3 distinct), 35% single — more variety
            r = secure_random()
            if r < 0.25 and len(mod_pool) >= 3 and mod1 != mod2 and mod2 != mod3 and mod1 != mod3:
                templates = TEMPLATES_TRIPLE
                tmpl = secure_choice(templates)
                try:
                    prompt = tmpl.format(subject=sub, mod1=mod1, mod2=mod2, mod3=mod3)
                except (KeyError, ValueError):
                    prompt = f"{sub}, {mod1}, {mod2} and {mod3}"
            elif r < 0.65 and mod1 != mod2:
                templates = TEMPLATES_DOUBLE
                tmpl = secure_choice(templates)
                try:
                    prompt = tmpl.format(subject=sub, mod1=mod1, mod2=mod2)
                except (KeyError, ValueError):
                    prompt = f"{sub}, {mod1} and {mod2}"
            else:
                templates = TEMPLATES_SINGLE
                tmpl = secure_choice(templates)
                try:
                    if "mod2" in tmpl:
                        prompt = tmpl.format(subject=sub, mod1=mod1, mod2=mod2)
                    elif "modifier" in tmpl:
                        prompt = tmpl.format(subject=sub, modifier=mod1)
                    else:
                        prompt = tmpl.format(subject=sub)
                except (KeyError, ValueError):
                    prompt = f"{sub}, {mod1}"

        if prompt and prompt not in avoid and not _is_near_duplicate(prompt, avoid):
            return prompt

    return None


def generate_prompt_batch(
    n: int,
    *,
    avoid: set[str] | None = None,
    knowledge: dict[str, Any] | None = None,
    seed: int | None = None,
) -> Iterator[str]:
    """
    Generate n distinct prompts. Yields prompts one at a time.
    """
    if seed is not None:
        random.seed(seed)
    avoid = set(avoid) if avoid else set()
    for _ in range(n):
        p = generate_procedural_prompt(avoid=avoid, knowledge=knowledge)
        if p is None:
            break
        avoid.add(p)
        yield p
