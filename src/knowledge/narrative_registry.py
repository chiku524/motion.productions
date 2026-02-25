"""
Narrative registry: fictional/story blends for time-frames within the video.
Plots, scripts, settings, genre, mood, themes, scene_type — the creative layer.
Distinct from static (pure color, sound) and dynamic (blended over duration).
Accuracy of recorded values is paramount. See docs/REGISTRIES.md.
"""
from pathlib import Path
from typing import Any

# Every narrative/film aspect — full coverage for any prompt.
NARRATIVE_ASPECTS = [
    {"id": "themes", "description": "What the video is about (subject, idea, motif).", "sub_aspects": ["subject", "idea", "motif"]},
    {"id": "plots", "description": "Story structure (arc, beat, tension curve).", "sub_aspects": ["arc", "beat", "tension", "rise", "climax", "resolution"]},
    {"id": "settings", "description": "Where/when (place, era, environment).", "sub_aspects": ["place", "era", "environment"]},
    {"id": "genre", "description": "Narrative category (e.g. drama, documentary).", "sub_aspects": ["category"]},
    {"id": "mood", "description": "Emotional tone (e.g. calm, tense).", "sub_aspects": ["tone"]},
    {"id": "style", "description": "Visual/narrative style (e.g. cinematic, abstract, minimal).", "sub_aspects": ["visual_style", "narrative_style"]},
    {"id": "scene_type", "description": "Kind of scene (indoor, outdoor, abstract).", "sub_aspects": ["indoor", "outdoor", "abstract"]},
]

NARRATIVE_REGISTRY_FILES = {
    a["id"]: f"narrative_{a['id']}.json" for a in NARRATIVE_ASPECTS
}


def get_narrative_registry_dir(config: dict[str, Any] | None = None) -> Path:
    """Path to the narrative registry directory (themes, plots, settings)."""
    from .registry import get_registry_dir
    return get_registry_dir(config) / "narrative"


def narrative_registry_path(config: dict[str, Any] | None, aspect: str) -> Path:
    """Path to the JSON file for a narrative aspect."""
    fname = NARRATIVE_REGISTRY_FILES.get(aspect, f"narrative_{aspect}.json")
    return get_narrative_registry_dir(config) / fname


def load_narrative_registry(aspect: str, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load narrative registry for one aspect. Returns structure with _meta and entries."""
    path = narrative_registry_path(config, aspect)
    if not path.exists():
        return _empty_narrative_registry(aspect)
    try:
        with open(path, encoding="utf-8") as f:
            import json
            return json.load(f)
    except (Exception, OSError):
        return _empty_narrative_registry(aspect)


def save_narrative_registry(aspect: str, data: dict[str, Any], config: dict[str, Any] | None = None) -> Path:
    """Save narrative registry with human-readable structure."""
    from .registry import get_registry_dir
    get_registry_dir(config).mkdir(parents=True, exist_ok=True)
    narrative_dir = get_narrative_registry_dir(config)
    narrative_dir.mkdir(parents=True, exist_ok=True)
    path = narrative_registry_path(config, aspect)
    import json
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return path


def _empty_narrative_registry(aspect: str) -> dict[str, Any]:
    """Empty narrative registry structure for readers."""
    info = next((a for a in NARRATIVE_ASPECTS if a["id"] == aspect), {"id": aspect, "description": "", "sub_aspects": []})
    return {
        "_meta": {
            "registry": "narrative",
            "goal": "Record every instance of narrative/film aspects (themes, plots, settings) present in the video.",
            "aspect": aspect,
            "description": info.get("description", ""),
            "sub_aspects": info.get("sub_aspects", []),
        },
        "entries": [],
        "count": 0,
    }


def _entries_keys(data: dict[str, Any]) -> set[str]:
    """Set of entry keys in the registry (normalized for lookup)."""
    return {e.get("key", "").strip().lower() for e in data.get("entries", []) if e.get("key")}


def ensure_narrative_in_registry(
    aspect: str,
    value: str,
    *,
    source_prompt: str = "",
    config: dict[str, Any] | None = None,
    out_novel: dict[str, list[dict[str, Any]]] | None = None,
) -> str | None:
    """
    If this narrative value is not in the registry for the given aspect, add it with a sensible name.
    Same process as static/dynamic: novel → add; unnamed → name-generator.
    Returns the assigned name if added, else None (already present).
    If out_novel is provided and the value was added, appends the API payload to out_novel[aspect].
    """
    if not value or not str(value).strip():
        return None
    key = str(value).strip().lower()
    data = load_narrative_registry(aspect, config)
    existing = _entries_keys(data)
    if key in existing:
        for e in data.get("entries", []):
            if (e.get("key") or "").strip().lower() == key:
                e["count"] = e.get("count", 0) + 1
                if source_prompt and len(e.get("sources", [])) < 5:
                    e.setdefault("sources", []).append(source_prompt[:80])
                break
        save_narrative_registry(aspect, data, config)
        return None
    names = {e.get("name", "") for e in data.get("entries", []) if e.get("name")}
    from .blend_names import generate_sensible_name
    name = generate_sensible_name(aspect, key, existing_names=names)
    # depth_breakdown where applicable: single value = 100% that origin (REGISTRY_FOUNDATION)
    depth_breakdown: dict[str, Any] = {key: 1.0}
    entry: dict[str, Any] = {
        "key": key,
        "value": value.strip(),
        "name": name,
        "count": 1,
        "sources": [source_prompt[:80]] if source_prompt else [],
        "depth_breakdown": depth_breakdown,
    }
    data.setdefault("entries", []).append(entry)
    data["count"] = len(data["entries"])
    save_narrative_registry(aspect, data, config)
    if out_novel is not None:
        out_novel.setdefault(aspect, []).append({
            "key": key,
            "value": value.strip(),
            "source_prompt": source_prompt[:80] if source_prompt else "",
            "name": name,
            "depth_breakdown": depth_breakdown,
        })
    return name


def extract_narrative_from_spec(
    spec: Any,
    *,
    prompt: str = "",
    instruction: Any = None,
) -> dict[str, list[str]]:
    """
    Extract narrative aspects from a creation spec (SceneSpec) or instruction (InterpretedInstruction).
    Returns dict: aspect_id -> list of value strings to record (e.g. genre -> ["documentary"], mood -> ["calm"]).
    If instruction is provided, also pulls style, tone, palette_hints for themes/mood.
    """
    out: dict[str, list[str]] = {
        "genre": [],
        "mood": [],
        "plots": [],
        "settings": [],
        "themes": [],
        "style": [],
        "scene_type": [],
    }
    genre = getattr(spec, "genre", None) or "general"
    if genre:
        out["genre"].append(str(genre).strip())
    tension = getattr(spec, "tension_curve", None) or "standard"
    if tension:
        out["plots"].append(str(tension).strip())
    audio_mood = getattr(spec, "audio_mood", None) or "neutral"
    if audio_mood:
        out["mood"].append(str(audio_mood).strip())
    src = instruction if instruction is not None else spec
    style = getattr(src, "style", None)
    tone = getattr(src, "tone", None)
    if style and str(style).strip():
        out["style"].append(str(style).strip())
    if tone and str(tone).strip() and str(tone).strip().lower() not in {x.strip().lower() for x in out["mood"]}:
        out["mood"].append(str(tone).strip())
    lighting = getattr(spec, "lighting_preset", None) or "neutral"
    if lighting:
        out["settings"].append(str(lighting).strip())
    shot = getattr(spec, "shot_type", None) or "medium"
    if shot:
        out["scene_type"].append(str(shot).strip())
    palette_name = getattr(spec, "palette_name", None)
    if palette_name and str(palette_name).strip():
        out["themes"].append(str(palette_name).strip())
    palette_hints = getattr(src, "palette_hints", []) or []
    for h in palette_hints:
        if h and str(h).strip() and str(h).strip().lower() not in {x.strip().lower() for x in out["themes"]}:
            out["themes"].append(str(h).strip())
    if prompt:
        words = [w.lower() for w in prompt.split() if len(w) >= 2]
        setting_keywords = {"forest", "city", "night", "day", "outdoor", "indoor", "sea", "ocean", "dusk", "dawn", "golden", "abstract", "desert", "mountain", "street", "room", "sky", "water", "snow", "beach", "studio"}
        genre_keywords = {"documentary", "drama", "horror", "comedy", "sci-fi", "fantasy", "abstract", "music", "vlog", "art", "cinematic", "minimal", "experimental"}
        mood_keywords = {"calm", "tense", "peaceful", "chaotic", "moody", "uplifting", "dark", "bright", "melancholic", "energetic", "chill", "dramatic", "soft", "intense", "dreamy", "harsh"}
        theme_keywords = {"nature", "urban", "love", "conflict", "transformation", "journey", "light", "shadow", "motion", "stillness", "color", "minimalism", "geometry"}
        for w in words:
            if w in setting_keywords and w not in [x.lower() for x in out["settings"]]:
                out["settings"].append(w)
            if w in genre_keywords and w not in [x.lower() for x in out["genre"]]:
                out["genre"].append(w)
            if w in mood_keywords and w not in [x.lower() for x in out["mood"]]:
                out["mood"].append(w)
            if w in theme_keywords and w not in [x.lower() for x in out["themes"]]:
                out["themes"].append(w)
    return out


def ensure_narrative_primitives_seeded(config: dict[str, Any] | None = None) -> None:
    """
    Ensure every primitive (origin) narrative value is in the narrative registry.
    Idempotent: only adds entries whose key is missing. Maps NARRATIVE_ORIGINS to aspects.
    """
    from .origins import get_all_origins
    origins = get_all_origins()
    narrative_origins = origins.get("narrative", {})
    aspect_values: list[tuple[str, str]] = []
    for origin_key, values in narrative_origins.items():
        if origin_key == "genre":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("genre", v))
        elif origin_key == "tone":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("mood", v))
        elif origin_key == "style":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("style", v))
        elif origin_key == "tension_curve":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("plots", v))
        elif origin_key == "settings":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("settings", v))
        elif origin_key == "themes":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("themes", v))
        elif origin_key == "scene_type":
            for v in values:
                if isinstance(v, str):
                    aspect_values.append(("scene_type", v))
    for aspect, value in aspect_values:
        data = load_narrative_registry(aspect, config)
        existing = _entries_keys(data)
        key = str(value).strip().lower()
        if key not in existing:
            ensure_narrative_in_registry(aspect, value, config=config)


def grow_narrative_from_spec(
    spec: Any,
    *,
    prompt: str = "",
    config: dict[str, Any] | None = None,
    instruction: Any = None,
    collect_novel_for_sync: bool = False,
) -> tuple[dict[str, int], dict[str, list[dict[str, Any]]]]:
    """
    Extract narrative from spec (and optional instruction) and ensure every value is in the narrative registry.
    Same process as static/dynamic: novel → add; unnamed → name-generator.
    Returns (added counts per aspect, novel_for_sync for API when collect_novel_for_sync=True).
    """
    ensure_narrative_primitives_seeded(config)
    added: dict[str, int] = {a: 0 for a in ("genre", "mood", "plots", "settings", "themes", "style", "scene_type")}
    novel_for_sync: dict[str, list[dict[str, Any]]] = {a: [] for a in added}
    extracted = extract_narrative_from_spec(spec, prompt=prompt, instruction=instruction)
    out_novel = novel_for_sync if collect_novel_for_sync else None
    for aspect, values in extracted.items():
        if aspect not in added:
            added[aspect] = 0
        for value in values:
            if ensure_narrative_in_registry(
                aspect, value, source_prompt=prompt, config=config, out_novel=out_novel
            ):
                added[aspect] += 1
    return added, novel_for_sync
