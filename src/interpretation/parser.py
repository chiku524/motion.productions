"""
Precise parsing of user instructions.
Interprets what the user is instructing from text/script/prompt.
"""
import re

from .schema import InterpretedInstruction
from ..procedural.data.keywords import (
    KEYWORD_TO_PALETTE,
    KEYWORD_TO_MOTION,
    KEYWORD_TO_INTENSITY,
    KEYWORD_TO_GRADIENT,
    KEYWORD_TO_CAMERA,
    KEYWORD_TO_SHAPE,
    KEYWORD_TO_SHOT,
    KEYWORD_TO_TRANSITION,
    KEYWORD_TO_LIGHTING,
    KEYWORD_TO_GENRE,
    KEYWORD_TO_PACING,
    KEYWORD_TO_COMPOSITION_BALANCE,
    KEYWORD_TO_COMPOSITION_SYMMETRY,
    KEYWORD_TO_TENSION,
    KEYWORD_TO_AUDIO_TEMPO,
    KEYWORD_TO_AUDIO_MOOD,
    KEYWORD_TO_AUDIO_PRESENCE,
    KEYWORD_TO_AUDIO_GENRE,
    KEYWORD_TO_MOTION_DIRECTIONALITY,
    KEYWORD_TO_MOTION_SMOOTHNESS,
    KEYWORD_TO_MOTION_RHYTHM,
    KEYWORD_TO_SFX_KIND,
    KEYWORD_TO_ENTITY_KIND,
    KEYWORD_TO_EXPRESSION,
    KEYWORD_TO_PERSONALITY,
    KEYWORD_TO_SETTING,
    SETTING_VISUAL_DEFAULTS,
    STYLE_PHRASE_TO_STYLE,
    KEYWORD_TO_STYLE,
    MOOD_TO_TONE,
    DEFAULT_PALETTE,
    DEFAULT_MOTION,
    DEFAULT_INTENSITY,
    DEFAULT_GRADIENT,
    DEFAULT_CAMERA,
    DEFAULT_SHOT,
    DEFAULT_TRANSITION,
    DEFAULT_LIGHTING,
    DEFAULT_GENRE,
    DEFAULT_PACING,
    DEFAULT_COMPOSITION_BALANCE,
    DEFAULT_COMPOSITION_SYMMETRY,
    DEFAULT_TENSION,
    DEFAULT_AUDIO_TEMPO,
    DEFAULT_AUDIO_MOOD,
    DEFAULT_AUDIO_PRESENCE,
    DEFAULT_AUDIO_GENRE,
    DEFAULT_MOTION_DIRECTIONALITY,
    DEFAULT_MOTION_SMOOTHNESS,
    DEFAULT_MOTION_RHYTHM,
)
from ..procedural.data.palettes import PALETTES
from .language_standard import (
    BUILTIN_LINGUISTIC,
    merge_linguistic_lookup,
    normalize_prompt_for_interpretation,
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


def _merge_linguistic(domain: str, base_dict: dict[str, str], linguistic: dict[str, dict[str, str]] | None) -> dict[str, str]:
    """Merge base keyword dict with built-in + fetched linguistic registry (language standard)."""
    return merge_linguistic_lookup(domain, base_dict, BUILTIN_LINGUISTIC, linguistic)


def _resolve_palette(
    words: list[str],
    avoid_palette: list[str],
    *,
    tone: str | None = None,
    linguistic_registry: dict[str, dict[str, str]] | None = None,
) -> str:
    """
    Resolve palette from keywords. First match wins; excludes avoided palettes.
    For arbitrary prompts: when no keyword matches, infer from tone.
    """
    hints = _resolve_palette_hints(words, avoid_palette, tone=tone, linguistic_registry=linguistic_registry)
    return hints[0] if hints else DEFAULT_PALETTE


def _resolve_palette_hints(
    words: list[str],
    avoid_palette: list[str],
    *,
    tone: str | None = None,
    linguistic_registry: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """
    Resolve ALL palette hints from keywords (for blending primitives).
    INTENDED_LOOP: creation blends these, not a single template.
    """
    lookup = _merge_linguistic("palette", KEYWORD_TO_PALETTE, linguistic_registry)
    avoid_set = set(avoid_palette)
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in lookup:
            p = lookup[w]
            if p not in avoid_set and p not in seen:
                hints.append(p)
                seen.add(p)
    if not hints and tone and tone not in avoid_set:
        tone_to_palette = {"dark": "night", "dreamy": "dreamy", "bright": "warm_sunset", "moody": "night"}
        p = tone_to_palette.get(tone, DEFAULT_PALETTE)
        hints = [p]
    return hints if hints else [DEFAULT_PALETTE]


def _resolve_motion(
    words: list[str],
    avoid_motion: list[str],
    *,
    tone: str | None = None,
    linguistic_registry: dict[str, dict[str, str]] | None = None,
) -> str:
    """
    Resolve motion type from keywords. First match wins; excludes avoided motions.
    """
    hints = _resolve_motion_hints(words, avoid_motion, tone=tone, linguistic_registry=linguistic_registry)
    return hints[0] if hints else DEFAULT_MOTION


def _resolve_motion_hints(
    words: list[str],
    avoid_motion: list[str],
    *,
    tone: str | None = None,
    linguistic_registry: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """
    Resolve ALL motion hints from keywords (for blending primitives).
    INTENDED_LOOP: creation blends these with learned motion.
    """
    lookup = _merge_linguistic("motion", KEYWORD_TO_MOTION, linguistic_registry)
    avoid_set = set(avoid_motion)
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in lookup:
            m = lookup[w]
            if m not in avoid_set and m not in seen:
                hints.append(m)
                seen.add(m)
    if not hints and tone:
        tone_to_motion = {"calm": "slow", "energetic": "fast", "dreamy": "slow", "moody": "flow"}
        m = tone_to_motion.get(tone)
        if m and m not in avoid_set:
            hints = [m]
    return hints if hints else [DEFAULT_MOTION]


def _resolve_intensity(
    words: list[str],
    *,
    tone: str | None = None,
) -> float:
    """
    Resolve intensity from keywords. First match wins. Clamped to 0–1.
    For arbitrary prompts: infer from tone when no keyword matches.
    """
    for w in words:
        if w in KEYWORD_TO_INTENSITY:
            return max(0.1, min(1.0, float(KEYWORD_TO_INTENSITY[w])))
    # Fallback: infer from tone
    if tone:
        tone_to_intensity = {"calm": 0.3, "energetic": 0.8, "dreamy": 0.4, "moody": 0.6, "dark": 0.5}
        if tone in tone_to_intensity:
            return tone_to_intensity[tone]
    return DEFAULT_INTENSITY


def _resolve_gradient(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve gradient type from keywords."""
    lookup = _merge_linguistic("gradient", KEYWORD_TO_GRADIENT, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_GRADIENT


def _resolve_camera(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve camera motion from keywords."""
    lookup = _merge_linguistic("camera", KEYWORD_TO_CAMERA, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_CAMERA


def _resolve_shape(words: list[str]) -> str:
    """Resolve shape overlay from keywords."""
    for w in words:
        if w in KEYWORD_TO_SHAPE:
            return KEYWORD_TO_SHAPE[w]
    return "none"


def _resolve_shot(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve shot type from keywords (supports linguistic registry for synonym expansion)."""
    lookup = _merge_linguistic("shot", KEYWORD_TO_SHOT, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_SHOT


def _resolve_transition(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve transition from keywords (supports linguistic registry for synonym expansion)."""
    lookup = _merge_linguistic("transition", KEYWORD_TO_TRANSITION, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_TRANSITION


def _resolve_lighting(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve lighting preset from keywords."""
    lookup = _merge_linguistic("lighting", KEYWORD_TO_LIGHTING, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_LIGHTING


def _resolve_lighting_hints(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> list[str]:
    """Resolve all lighting preset hints from keywords (for primitive blending)."""
    lookup = _merge_linguistic("lighting", KEYWORD_TO_LIGHTING, linguistic_registry)
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in lookup:
            p = lookup[w]
            if p not in seen:
                hints.append(p)
                seen.add(p)
    return hints if hints else [DEFAULT_LIGHTING]


def _resolve_setting(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str | None:
    """Resolve environment/setting for mini-scene backgrounds + narrative registry."""
    lookup = _merge_linguistic("setting", KEYWORD_TO_SETTING, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return None


def _resolve_theme(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str | None:
    """Resolve narrative theme when present in prompt."""
    from .language_standard import BUILTIN_LINGUISTIC
    base = dict(BUILTIN_LINGUISTIC.get("theme") or {})
    lookup = _merge_linguistic("theme", base, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return None


def _resolve_composition_balance_hints(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> list[str]:
    """Resolve all composition balance hints from keywords (supports linguistic registry)."""
    lookup = _merge_linguistic("composition_balance", KEYWORD_TO_COMPOSITION_BALANCE, linguistic_registry)
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in lookup:
            p = lookup[w]
            if p not in seen:
                hints.append(p)
                seen.add(p)
    return hints if hints else [DEFAULT_COMPOSITION_BALANCE]


def _resolve_composition_symmetry_hints(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> list[str]:
    """Resolve all composition symmetry hints from keywords (supports linguistic registry)."""
    lookup = _merge_linguistic("composition_symmetry", KEYWORD_TO_COMPOSITION_SYMMETRY, linguistic_registry)
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in lookup:
            p = lookup[w]
            if p not in seen:
                hints.append(p)
                seen.add(p)
    return hints if hints else [DEFAULT_COMPOSITION_SYMMETRY]


def _resolve_genre(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve genre from keywords."""
    lookup = _merge_linguistic("genre", KEYWORD_TO_GENRE, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_GENRE


def _resolve_composition_balance(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve composition balance from keywords (supports linguistic registry)."""
    lookup = _merge_linguistic("composition_balance", KEYWORD_TO_COMPOSITION_BALANCE, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_COMPOSITION_BALANCE


def _resolve_composition_symmetry(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve composition symmetry from keywords (supports linguistic registry)."""
    lookup = _merge_linguistic("composition_symmetry", KEYWORD_TO_COMPOSITION_SYMMETRY, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_COMPOSITION_SYMMETRY


def _resolve_pacing_factor(words: list[str]) -> float:
    """Resolve pacing from keywords. Domain: Temporal."""
    for w in words:
        if w in KEYWORD_TO_PACING:
            return max(0.3, min(2.0, float(KEYWORD_TO_PACING[w])))
    return DEFAULT_PACING


def _resolve_tension_curve(words: list[str]) -> str:
    """Resolve tension curve from keywords. Domain: Narrative."""
    for w in words:
        if w in KEYWORD_TO_TENSION:
            return KEYWORD_TO_TENSION[w]
    return DEFAULT_TENSION


def _resolve_audio_tempo(words: list[str]) -> str:
    """Resolve audio tempo from keywords. Domain: Audio."""
    for w in words:
        if w in KEYWORD_TO_AUDIO_TEMPO:
            return KEYWORD_TO_AUDIO_TEMPO[w]
    return DEFAULT_AUDIO_TEMPO


def _resolve_audio_mood(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve audio mood from keywords (supports linguistic registry for synonym expansion)."""
    lookup = _merge_linguistic("audio_mood", KEYWORD_TO_AUDIO_MOOD, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    return DEFAULT_AUDIO_MOOD


def _resolve_audio_presence(words: list[str]) -> str:
    """Resolve audio presence from keywords. Domain: Audio."""
    for w in words:
        if w in KEYWORD_TO_AUDIO_PRESENCE:
            return KEYWORD_TO_AUDIO_PRESENCE[w]
    return DEFAULT_AUDIO_PRESENCE


def _resolve_audio_genre(words: list[str], linguistic_registry: dict[str, dict[str, str]] | None = None) -> str:
    """Resolve music genre for in-house arrangement presets."""
    lookup = _merge_linguistic("audio_genre", KEYWORD_TO_AUDIO_GENRE, linguistic_registry)
    for w in words:
        if w in lookup:
            return lookup[w]
    # Phrase-ish: deep + house already covered by KEYWORD_TO_AUDIO_GENRE["house"]
    return DEFAULT_AUDIO_GENRE


def _resolve_audio_hints(words: list[str]) -> list[str]:
    """Collect audio-related hint tokens for blending / music engine."""
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        for table in (KEYWORD_TO_AUDIO_MOOD, KEYWORD_TO_AUDIO_TEMPO, KEYWORD_TO_AUDIO_PRESENCE, KEYWORD_TO_AUDIO_GENRE):
            if w in table:
                v = table[w]
                if v not in seen:
                    hints.append(v)
                    seen.add(v)
    return hints


def _resolve_motion_directionality(
    words: list[str],
    linguistic_registry: dict[str, dict[str, str]] | None = None,
) -> tuple[str, list[str]]:
    """Resolve primary directionality + all hints."""
    lookup = _merge_linguistic("motion_directionality", KEYWORD_TO_MOTION_DIRECTIONALITY, linguistic_registry)
    hints: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in lookup:
            d = lookup[w]
            if d not in seen:
                hints.append(d)
                seen.add(d)
    primary = hints[0] if hints else DEFAULT_MOTION_DIRECTIONALITY
    return primary, hints if hints else [DEFAULT_MOTION_DIRECTIONALITY]


def _resolve_motion_smoothness(words: list[str]) -> str:
    for w in words:
        if w in KEYWORD_TO_MOTION_SMOOTHNESS:
            return KEYWORD_TO_MOTION_SMOOTHNESS[w]
    return DEFAULT_MOTION_SMOOTHNESS


def _resolve_motion_rhythm(words: list[str]) -> str:
    for w in words:
        if w in KEYWORD_TO_MOTION_RHYTHM:
            return KEYWORD_TO_MOTION_RHYTHM[w]
    return DEFAULT_MOTION_RHYTHM


def _resolve_sfx_kinds(words: list[str]) -> list[str]:
    kinds: list[str] = []
    seen: set[str] = set()
    for w in words:
        if w in KEYWORD_TO_SFX_KIND:
            k = KEYWORD_TO_SFX_KIND[w]
            if k not in seen:
                kinds.append(k)
                seen.add(k)
    return kinds


def _resolve_entities(words: list[str], prompt: str) -> list[dict]:
    """Extract stylized entity hints (ball, block, person, …) for scene graph."""
    entities: list[dict] = []
    seen: set[str] = set()
    direction = "none"
    for w in words:
        if w in KEYWORD_TO_MOTION_DIRECTIONALITY:
            direction = KEYWORD_TO_MOTION_DIRECTIONALITY[w]
            break
    # Prefer left/right/up/down as trajectory labels when present
    traj = "none"
    for label in ("left", "right", "up", "down", "toward", "away"):
        if label in words:
            traj = label
            break
    bounce = any(w in KEYWORD_TO_SFX_KIND and KEYWORD_TO_SFX_KIND[w] == "bounce" for w in words)
    color_hint = None
    for w in words:
        if w in KEYWORD_TO_PALETTE:
            color_hint = KEYWORD_TO_PALETTE[w]
            break
    expression = "neutral"
    expr_lookup = _merge_linguistic("expression", KEYWORD_TO_EXPRESSION, None)
    for w in words:
        if w in expr_lookup:
            expression = expr_lookup[w]
            break
    personality = "neutral"
    pers_lookup = _merge_linguistic("personality", KEYWORD_TO_PERSONALITY, None)
    for w in words:
        if w in pers_lookup:
            personality = pers_lookup[w]
            break
    gag = "none"
    for w in words:
        if w in ("wink", "winks", "winking"):
            gag = "wink"
            break
        if w in ("spin", "spins", "twirl", "flourish"):
            gag = "spin" if w != "flourish" else "flourish"
            break
        if w in ("double",) and "take" in words:
            gag = "double_take"
            break
        if w in ("squash", "squish"):
            gag = "squash"
            break
    for w in words:
        if w in KEYWORD_TO_ENTITY_KIND:
            kind = KEYWORD_TO_ENTITY_KIND[w]
            key = f"{kind}:{w}"
            if key in seen:
                continue
            seen.add(key)
            prop_kinds = ("tree", "fish", "wave", "building", "cloud")
            is_prop = kind in prop_kinds
            ent_bounce = bounce
            ent_traj = traj
            prop_motion = traj if traj != "none" else "none"
            if kind == "fish" and any(x in words for x in ("jump", "jumping", "jumps", "leap", "leaping")):
                ent_bounce = True
                prop_motion = "jump"
                if ent_traj == "none":
                    ent_traj = "right"
            if kind == "tree" and ent_traj == "none":
                prop_motion = "none"
            if kind in ("wave", "cloud") and ent_traj == "none":
                prop_motion = "left"
            entities.append({
                "id": f"e{len(entities)}",
                "kind": kind,
                "label": w,
                "color_hint": color_hint,
                "directionality": direction,
                "trajectory": ent_traj,
                "bounce": ent_bounce,
                "sfx_on": (["bounce"] if ent_bounce and not is_prop else [])
                + (["whoosh"] if kind == "fish" and prop_motion == "jump" else []),
                "expression": expression if kind == "character" else "neutral",
                "personality": personality if kind == "character" else "neutral",
                "gag": gag if gag != "none" else ("squash" if ent_bounce and not is_prop else "none"),
                "is_prop": is_prop,
                "prop_motion": prop_motion,
                "prop_x": 0.25 if kind == "fish" else 0.5,
                "prop_y": 0.7 if kind in ("fish", "wave", "tree", "building") else 0.25,
                "prop_scale": 1.0,
                "z": 0 if is_prop and kind in ("tree", "building", "wave", "cloud") else 2,
            })
    return entities


def _resolve_audio_vocals(words: list[str]) -> bool:
    return any(w in ("vocals", "vocal", "singing", "choir", "voice", "spoken") for w in words)


def _resolve_depth_parallax(words: list[str]) -> bool:
    """Resolve depth/parallax from keywords. Phase 7. Expanded for video/game parallax prompts."""
    depth_keywords = {
        "parallax", "depth", "layered", "realistic",
        "layers", "multilayer", "foreground", "background",
        "2.5d", "scrolling", "dof", "stereo", "field",
    }
    return any(w in depth_keywords for w in words)


def _resolve_text_overlay(prompt: str) -> tuple[str | None, str, str | None]:
    """
    Resolve text overlay from prompt. Phase 4.
    Returns (text_overlay, text_position, educational_template).
    """
    raw = (prompt or "").strip().lower()
    # Patterns: "explain X", "tutorial about Y", "explainer on Z"
    import re
    m = re.search(r"\bexplain\s+(.+?)(?:\s+in\s+\d+\s*(?:sec|s|min|m))?\.?$", raw, re.IGNORECASE)
    if m:
        topic = m.group(1).strip()
        if len(topic) < 80:
            return topic, "center", "explainer"
    m = re.search(r"\btutorial\s+(?:about|on)\s+(.+?)(?:\s+in\s+\d+\s*(?:sec|s|min|m))?\.?$", raw, re.IGNORECASE)
    if m:
        topic = m.group(1).strip()
        if len(topic) < 80:
            return topic, "top", "tutorial"
    m = re.search(r"\bexplainer\s+(?:about|on)\s+(.+?)(?:\s+in\s+\d+\s*(?:sec|s|min|m))?\.?$", raw, re.IGNORECASE)
    if m:
        topic = m.group(1).strip()
        if len(topic) < 80:
            return topic, "center", "explainer"
    return None, "center", None


def _resolve_style(
    words: list[str], prompt: str, linguistic_registry: dict[str, dict[str, str]] | None = None
) -> str | None:
    """Extract style hint from keywords or phrases; uses linguistic merge for synonyms."""
    lookup = _merge_linguistic("style", KEYWORD_TO_STYLE, linguistic_registry)
    raw = (prompt or "").lower()
    for phrase, style in STYLE_PHRASE_TO_STYLE.items():
        if phrase in raw and any(p in raw for p in (f"{phrase} feel", f"{phrase} look", f"{phrase} style", f"{phrase}")):
            return style
    for w in words:
        if w in lookup:
            return lookup[w]
    for w in words:
        if w in STYLE_PHRASE_TO_STYLE:
            return STYLE_PHRASE_TO_STYLE[w]
    return None


def _resolve_tone(
    words: list[str], prompt: str, linguistic_registry: dict[str, dict[str, str]] | None = None
) -> str | None:
    """Extract tone from keywords or phrases; uses linguistic merge for synonyms."""
    lookup = _merge_linguistic("tone", MOOD_TO_TONE, linguistic_registry)
    pl = (prompt or "").lower()
    for mood, tone in lookup.items():
        if mood in pl:
            return tone
    for w in words:
        if w in lookup:
            return lookup[w]
    return None


def _validate_prompt(prompt: str) -> str:
    """Normalize and validate prompt for accuracy and precision."""
    if not isinstance(prompt, str):
        return ""
    s = prompt.strip()
    if len(s) > 2000:
        s = s[:2000].rstrip()
    return s


def interpret_user_prompt(
    prompt: str,
    *,
    default_duration: float | None = None,
    seed: int | None = None,
    linguistic_registry: dict[str, dict[str, str]] | None = None,
) -> InterpretedInstruction:
    """
    Precisely interpret what the user is instructing.

    Parses: palette, motion, intensity, duration, style, tone, negations.
    Returns an InterpretedInstruction with resolved values.
    Validates prompt input for accuracy and precision.
    """
    prompt = normalize_prompt_for_interpretation(_validate_prompt(prompt or ""))
    raw_lower = prompt.lower()

    words = _extract_words(prompt)
    avoid_motion, avoid_palette = _extract_negations(prompt)
    duration = _extract_duration(prompt) or default_duration
    style = _resolve_style(words, prompt, linguistic_registry)
    tone = _resolve_tone(words, prompt, linguistic_registry)
    # Resolve with tone fallback for arbitrary prompts (unknown words)
    palette = _resolve_palette(words, avoid_palette, tone=tone, linguistic_registry=linguistic_registry)
    motion = _resolve_motion(words, avoid_motion, tone=tone, linguistic_registry=linguistic_registry)
    palette_hints = _resolve_palette_hints(words, avoid_palette, tone=tone, linguistic_registry=linguistic_registry)
    motion_hints = _resolve_motion_hints(words, avoid_motion, tone=tone, linguistic_registry=linguistic_registry)
    lighting_hints = _resolve_lighting_hints(words, linguistic_registry)
    composition_balance_hints = _resolve_composition_balance_hints(words, linguistic_registry)
    composition_symmetry_hints = _resolve_composition_symmetry_hints(words, linguistic_registry)
    intensity = _resolve_intensity(words, tone=tone)
    gradient = _resolve_gradient(words, linguistic_registry)
    camera = _resolve_camera(words, linguistic_registry)
    shape = _resolve_shape(words)
    shot = _resolve_shot(words, linguistic_registry)
    transition = _resolve_transition(words, linguistic_registry)
    lighting = _resolve_lighting(words, linguistic_registry)
    setting = _resolve_setting(words, linguistic_registry)
    theme = _resolve_theme(words, linguistic_registry)
    # Setting fills in palette/lighting/gradient when prompt didn't specify them strongly
    if setting and setting in SETTING_VISUAL_DEFAULTS:
        vis = SETTING_VISUAL_DEFAULTS[setting]
        if palette == DEFAULT_PALETTE and vis.get("palette"):
            palette = vis["palette"]
            if vis["palette"] not in palette_hints:
                palette_hints = [vis["palette"]] + [h for h in palette_hints if h != vis["palette"]]
        if lighting == DEFAULT_LIGHTING and vis.get("lighting"):
            lighting = vis["lighting"]
            if lighting not in lighting_hints:
                lighting_hints = [lighting] + [h for h in lighting_hints if h != lighting]
        if gradient == DEFAULT_GRADIENT and vis.get("gradient"):
            gradient = vis["gradient"]
    genre_resolved = _resolve_genre(words, linguistic_registry)
    composition_balance = _resolve_composition_balance(words, linguistic_registry)
    composition_symmetry = _resolve_composition_symmetry(words, linguistic_registry)
    pacing_factor = _resolve_pacing_factor(words)
    tension_curve = _resolve_tension_curve(words)
    audio_tempo = _resolve_audio_tempo(words)
    audio_mood = _resolve_audio_mood(words, linguistic_registry)
    audio_presence = _resolve_audio_presence(words)
    audio_genre = _resolve_audio_genre(words, linguistic_registry)
    audio_hints = _resolve_audio_hints(words)
    audio_vocals = _resolve_audio_vocals(words)
    motion_directionality, motion_directionality_hints = _resolve_motion_directionality(
        words, linguistic_registry
    )
    motion_smoothness = _resolve_motion_smoothness(words)
    motion_rhythm = _resolve_motion_rhythm(words)
    sfx_kinds = _resolve_sfx_kinds(words)
    entities = _resolve_entities(words, prompt)
    # Placeholder sfx_events (t_sec filled by creation when duration known)
    sfx_events: list[dict] = [{"kind": k, "t_sec": None, "strength": 0.8} for k in sfx_kinds]
    # Music genre implies music presence unless silence requested
    if audio_genre != "none" and audio_presence == "ambient":
        audio_presence = "music"
    if audio_vocals and audio_presence in ("ambient", "sfx"):
        audio_presence = "music"
    if sfx_kinds and audio_presence == "ambient":
        audio_presence = "full" if audio_genre != "none" else "sfx"
    # Entity with bounce → ensure circle overlay when no shape set
    if entities and shape == "none":
        shape = entities[0]["kind"] if entities[0]["kind"] in ("circle", "rect") else "circle"
    text_overlay, text_position, educational_template = _resolve_text_overlay(prompt)
    depth_parallax = _resolve_depth_parallax(words)

    # Keywords that contributed (for learning and logging) — all domains
    _all_keyword_sources = (
        KEYWORD_TO_PALETTE, KEYWORD_TO_MOTION, KEYWORD_TO_INTENSITY,
        KEYWORD_TO_GRADIENT, KEYWORD_TO_CAMERA, KEYWORD_TO_SHAPE,
        KEYWORD_TO_SHOT, KEYWORD_TO_TRANSITION, KEYWORD_TO_LIGHTING,
        KEYWORD_TO_GENRE, KEYWORD_TO_PACING,
        KEYWORD_TO_COMPOSITION_BALANCE, KEYWORD_TO_COMPOSITION_SYMMETRY,
        KEYWORD_TO_TENSION, KEYWORD_TO_AUDIO_TEMPO, KEYWORD_TO_AUDIO_MOOD,
        KEYWORD_TO_AUDIO_PRESENCE, KEYWORD_TO_AUDIO_GENRE,
        KEYWORD_TO_MOTION_DIRECTIONALITY, KEYWORD_TO_MOTION_SMOOTHNESS,
        KEYWORD_TO_MOTION_RHYTHM, KEYWORD_TO_SFX_KIND, KEYWORD_TO_ENTITY_KIND,
        KEYWORD_TO_EXPRESSION, KEYWORD_TO_PERSONALITY, KEYWORD_TO_SETTING,
    )
    contributing: list[str] = []
    for w in words:
        if any(w in kw for kw in _all_keyword_sources):
            contributing.append(w)
    # For arbitrary prompts: all meaningful words contribute to learning
    if not contributing:
        contributing = words[:15] if words else ["unknown"]

    # Resolve palette hints to primitive RGB lists (prompt → values, not names)
    default_rgbs = PALETTES.get(DEFAULT_PALETTE, list(PALETTES.values())[0])
    color_primitive_lists = [list(PALETTES.get(h, default_rgbs)) for h in palette_hints]

    return InterpretedInstruction(
        palette_name=palette,
        motion_type=motion,
        palette_hints=palette_hints,
        motion_hints=motion_hints,
        lighting_hints=lighting_hints,
        composition_balance_hints=composition_balance_hints,
        composition_symmetry_hints=composition_symmetry_hints,
        color_primitive_lists=color_primitive_lists,
        intensity=intensity,
        gradient_type=gradient,
        camera_motion=camera,
        shape_overlay=shape,
        shot_type=shot,
        transition_in=transition,
        transition_out=transition,
        lighting_preset=lighting,
        genre=genre_resolved,
        text_overlay=text_overlay,
        text_position=text_position,
        educational_template=educational_template,
        depth_parallax=depth_parallax,
        composition_balance=composition_balance,
        composition_symmetry=composition_symmetry,
        pacing_factor=pacing_factor,
        tension_curve=tension_curve,
        audio_tempo=audio_tempo,
        audio_mood=audio_mood,
        audio_presence=audio_presence,
        audio_genre=audio_genre,
        audio_hints=audio_hints,
        audio_vocals=audio_vocals,
        sfx_events=sfx_events,
        motion_directionality=motion_directionality,
        motion_directionality_hints=motion_directionality_hints,
        motion_smoothness=motion_smoothness,
        motion_rhythm=motion_rhythm,
        entities=entities,
        duration_seconds=duration,
        style=style,
        tone=tone,
        setting=setting,
        theme=theme,
        keywords=contributing,
        avoid_motion=avoid_motion,
        avoid_palette=avoid_palette,
        raw_prompt=raw_lower,
    )
