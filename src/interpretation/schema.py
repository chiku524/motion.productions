"""
Schema for what the user is instructing.
Precise representation of parsed user input.
"""
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class InterpretedInstruction:
    """
    Precise interpretation of a user's text/script/prompt.
    What the user wants: palette, motion, intensity, duration, style, tone, etc.
    """

    # Core visual (primary resolved values)
    palette_name: str
    motion_type: str
    intensity: float  # 0–1

    # Multi-keyword hints for blending (INTENDED_LOOP: blend primitives, not pick templates)
    palette_hints: list[str] = field(default_factory=list)  # all palette names from matching keywords
    motion_hints: list[str] = field(default_factory=list)   # all motion types from matching keywords
    lighting_hints: list[str] = field(default_factory=list)  # all lighting presets from matching keywords
    composition_balance_hints: list[str] = field(default_factory=list)
    composition_symmetry_hints: list[str] = field(default_factory=list)
    # Primitive values for blending: prompt → actual RGB lists (from PALETTES), not names
    color_primitive_lists: list[list[tuple[int, int, int]]] = field(default_factory=list)
    gradient_type: str = "vertical"   # vertical | radial | angled | horizontal
    camera_motion: str = "static"     # static | zoom | zoom_out | pan | rotate
    shape_overlay: str = "none"       # none | circle | rect
    shot_type: str = "medium"         # wide | medium | close | pov | handheld
    transition_in: str = "cut"        # cut | fade | dissolve | wipe
    transition_out: str = "cut"
    lighting_preset: str = "neutral"  # noir | golden_hour | neon | documentary | moody
    genre: str = "general"            # documentary | thriller | ad | tutorial | educational

    # Composition (Domain: Composition)
    composition_balance: str = "balanced"   # left_heavy | balanced | right_heavy | top_heavy | bottom_heavy
    composition_symmetry: str = "slight"    # asymmetric | slight | bilateral

    # Temporal (Domain: Temporal)
    pacing_factor: float = 1.0              # 0.5–2.0; resolved from KEYWORD_TO_PACING

    # Narrative (Domain: Narrative)
    tension_curve: str = "standard"         # flat | slow_build | standard | immediate

    # Audio (Domain: Audio)
    audio_tempo: str = "medium"             # slow | medium | fast
    audio_mood: str = "neutral"             # neutral | calm | tense | uplifting | dark
    audio_presence: str = "ambient"         # silence | ambient | music | sfx | full

    # Text/graphics overlays (Phase 4)
    text_overlay: str | None = None   # text to display (titles, subtitles)
    text_position: str = "center"     # center | top | bottom
    educational_template: str | None = None  # concept_example_summary | tutorial | explainer
    depth_parallax: bool = False             # Phase 7: 2.5D parallax

    # Duration (seconds; None = use default)
    duration_seconds: float | None = None

    # Style / tone (optional hints)
    style: str | None = None
    tone: str | None = None

    # Keywords extracted (for lookup and learning)
    keywords: list[str] = field(default_factory=list)

    # Negations: things the user explicitly does NOT want
    avoid_motion: list[str] = field(default_factory=list)
    avoid_palette: list[str] = field(default_factory=list)

    # Raw prompt (normalized)
    raw_prompt: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging and API."""
        d: dict[str, Any] = {
            "palette_name": self.palette_name,
            "motion_type": self.motion_type,
            "intensity": self.intensity,
            "keywords": self.keywords,
            "raw_prompt": self.raw_prompt,
        }
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.style:
            d["style"] = self.style
        if self.tone:
            d["tone"] = self.tone
        if self.avoid_motion:
            d["avoid_motion"] = self.avoid_motion
        if self.avoid_palette:
            d["avoid_palette"] = self.avoid_palette
        return d

    def to_api_dict(self) -> dict[str, Any]:
        """Full serialization for API/D1 storage (interpretation registry). JSON-safe."""
        d = asdict(self)
        # Tuples → lists for JSON
        if "color_primitive_lists" in d and d["color_primitive_lists"]:
            d["color_primitive_lists"] = [[list(t) for t in row] for row in d["color_primitive_lists"]]
        return d

    @classmethod
    def from_api_dict(cls, d: dict[str, Any]) -> "InterpretedInstruction":
        """Reconstruct from API/D1 JSON (e.g. for-creation interpretation_prompts)."""
        if "color_primitive_lists" in d and d["color_primitive_lists"]:
            d = {**d, "color_primitive_lists": [tuple(tuple(c) for c in row) for row in d["color_primitive_lists"]]}
        # Only pass keys that InterpretedInstruction expects
        field_names = {f.name for f in cls.__dataclass_fields__}
        kwargs = {k: v for k, v in d.items() if k in field_names}
        return cls(**kwargs)
