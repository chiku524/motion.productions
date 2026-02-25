"""
Our data: keyword → palette and motion hints. Used by the parser.
No external model — we define every mapping ourselves.
"""
# Words (lowercase) that suggest a palette name
KEYWORD_TO_PALETTE: dict[str, str] = {
    "sunset": "warm_sunset",
    "sun": "warm_sunset",
    "ocean": "ocean",
    "sea": "ocean",
    "water": "ocean",
    "neon": "neon",
    "city": "neon",
    "night": "night",
    "dark": "night",
    "forest": "forest",
    "dreamy": "dreamy",
    "dream": "dreamy",
    "fire": "fire",
    "flame": "fire",
    "rain": "ocean",
    "tokyo": "neon",
    "cinematic": "mono",
    "black": "night",
    "white": "mono",
    # Expansions for arbitrary prompts (unknown-word resilience)
    "blue": "ocean",
    "azure": "ocean",
    "teal": "ocean",
    "green": "forest",
    "orange": "fire",
    "red": "fire",
    "purple": "dreamy",
    "lavender": "dreamy",
    "pink": "dreamy",
    "urban": "neon",
    "cyber": "neon",
    "retro": "neon",
}

# Words that suggest motion style
KEYWORD_TO_MOTION: dict[str, str] = {
    "calm": "slow",
    "gentle": "slow",
    "wave": "wave",
    "ocean": "wave",
    "sea": "wave",
    "rain": "wave",
    "flow": "flow",
    "drift": "flow",
    "fast": "fast",
    "quick": "fast",
    "pulse": "pulse",
    "neon": "pulse",
    "city": "pulse",
    "dreamy": "slow",
    "dream": "slow",
    # Expansions for arbitrary prompts
    "chaotic": "fast",
    "intense": "fast",
    "peaceful": "slow",
    "serene": "slow",
    "rhythmic": "pulse",
    "fluid": "flow",
    "smooth": "flow",
    "erratic": "pulse",
}

# Words that suggest gradient layout
KEYWORD_TO_GRADIENT: dict[str, str] = {
    "radial": "radial",
    "circle": "radial",
    "sun": "radial",
    "glow": "radial",
    "angled": "angled",
    "diagonal": "angled",
    "sweep": "angled",
    "vertical": "vertical",
    "horizontal": "horizontal",
}

# Words that suggest shape overlay (none | circle | rect)
KEYWORD_TO_SHAPE: dict[str, str] = {
    "circle": "circle",
    "glow": "circle",
    "spot": "circle",
    "spotlight": "circle",
    "vignette": "circle",
    "frame": "rect",
    "box": "rect",
    "letterbox": "rect",
}

# Words that suggest camera-style motion (film taxonomy)
KEYWORD_TO_CAMERA: dict[str, str] = {
    "zoom": "zoom",
    "zoom_in": "zoom",
    "zoom_out": "zoom_out",
    "pan": "pan",
    "sweep": "pan",
    "rotate": "rotate",
    "spin": "rotate",
    "static": "static",
    "still": "static",
    "dolly": "dolly",
    "push": "dolly",
    "crane": "crane",
    "tilt": "tilt",
    "roll": "roll",
    "truck": "truck",
    "pedestal": "pedestal",
    "arc": "arc",
    "tracking": "tracking",
    "track": "tracking",
    "follow": "tracking",
    "birds_eye": "birds_eye",
    "bird_eye": "birds_eye",
    "overhead": "birds_eye",
    "whip_pan": "whip_pan",
    "whip": "whip_pan",
}

# Words that suggest shot type (Phase 2)
KEYWORD_TO_SHOT: dict[str, str] = {
    "wide": "wide",
    "establishing": "wide",
    "medium": "medium",
    "close": "close",
    "closeup": "close",
    "close_up": "close",
    "pov": "pov",
    "handheld": "handheld",
}

# Words that suggest transition (Phase 2)
KEYWORD_TO_TRANSITION: dict[str, str] = {
    "cut": "cut",
    "fade": "fade",
    "dissolve": "dissolve",
    "crossfade": "dissolve",
    "wipe": "wipe",
}

# Words that suggest lighting preset (Phase 3)
KEYWORD_TO_LIGHTING: dict[str, str] = {
    "noir": "noir",
    "dark": "noir",
    "golden": "golden_hour",
    "golden_hour": "golden_hour",
    "sunset": "golden_hour",
    "warm": "golden_hour",
    "neon": "neon",
    "documentary": "documentary",
    "neutral": "documentary",
    "natural": "documentary",
    "moody": "moody",
    "dramatic": "moody",
    "cinematic": "neutral",
    "film": "neutral",
    "dreamy": "golden_hour",
    "bright": "documentary",
    "soft": "golden_hour",
    "harsh": "noir",
    "dim": "noir",
    "nostalgic": "golden_hour",
}

# Words that suggest depth/parallax (Phase 7)
KEYWORD_TO_DEPTH: dict[str, bool] = {
    "parallax": True,
    "depth": True,
    "layered": True,
    "3d": True,
    "realistic": True,
}

# Words that suggest genre (Phase 5)
KEYWORD_TO_GENRE: dict[str, str] = {
    "documentary": "documentary",
    "doc": "documentary",
    "thriller": "thriller",
    "ad": "ad",
    "commercial": "ad",
    "tutorial": "tutorial",
    "educational": "educational",
    "explainer": "explainer",
    "cinematic": "general",
    "film": "general",
    "movie": "general",
    "advert": "ad",
    "promo": "ad",
    "howto": "tutorial",
    # Expand for Semantic registry growth (§2.4)
    "drama": "general",
    "horror": "general",
    "comedy": "general",
    "scifi": "general",
    "sci-fi": "general",
    "fantasy": "general",
    "vlog": "general",
    "music": "general",
    "art": "general",
    "experimental": "general",
    "minimal": "general",
}

# Abstract style phrases → style (for "documentary feel", "cinematic look", etc.)
STYLE_PHRASE_TO_STYLE: dict[str, str] = {
    "documentary": "realistic",
    "cinematic": "cinematic",
    "film": "cinematic",
    "abstract": "abstract",
    "minimal": "minimal",
    "anime": "anime",
    "realistic": "realistic",
}

# Single words → style (NARRATIVE_ORIGINS: cinematic, abstract, minimal, realistic, anime)
KEYWORD_TO_STYLE: dict[str, str] = {
    "cinematic": "cinematic",
    "film": "cinematic",
    "movie": "cinematic",
    "abstract": "abstract",
    "minimal": "minimal",
    "realistic": "realistic",
    "documentary": "realistic",
    "natural": "realistic",
    "anime": "anime",
}
DEFAULT_STYLE = "cinematic"

# Abstract mood words → tone (for "something nostalgic", "melancholic vibe")
MOOD_TO_TONE: dict[str, str] = {
    "nostalgic": "moody",
    "melancholic": "dark",
    "hopeful": "bright",
    "serene": "calm",
    "uplifting": "bright",
    "eerie": "dark",
    "warm": "bright",
    "cool": "calm",
    "mysterious": "dark",
    "epic": "energetic",
}

# Words that suggest pacing (slow/fast per segment)
KEYWORD_TO_PACING: dict[str, float] = {
    "slow": 0.6,
    "slower": 0.5,
    "fast": 1.4,
    "faster": 1.5,
    "quick": 1.3,
    "lively": 1.2,
    "relaxed": 0.7,
}
DEFAULT_PACING = 1.0

# Composition: balance, symmetry, framing (Domain: Composition)
KEYWORD_TO_COMPOSITION_BALANCE: dict[str, str] = {
    "balanced": "balanced",
    "balance": "balanced",
    "centered": "balanced",
    "left": "left_heavy",
    "right": "right_heavy",
    "asymmetric": "asymmetric",
    "asymmetry": "asymmetric",
    "symmetry": "bilateral",
    "symmetric": "bilateral",
    "bilateral": "bilateral",
}
KEYWORD_TO_COMPOSITION_SYMMETRY: dict[str, str] = {
    "asymmetric": "asymmetric",
    "slight": "slight",
    "symmetry": "bilateral",
    "symmetric": "bilateral",
    "bilateral": "bilateral",
    "mirror": "bilateral",
}

# Narrative tension curve (Domain: Narrative)
KEYWORD_TO_TENSION: dict[str, str] = {
    "flat": "flat",
    "steady": "flat",
    "slow_build": "slow_build",
    "gradual": "slow_build",
    "build": "slow_build",
    "standard": "standard",
    "immediate": "immediate",
    "instant": "immediate",
    "tense": "immediate",
    "climax": "immediate",
}

# Audio: tempo, mood, presence (Domain: Audio)
KEYWORD_TO_AUDIO_TEMPO: dict[str, str] = {
    "slow": "slow",
    "calm": "slow",
    "fast": "fast",
    "upbeat": "fast",
    "medium": "medium",
}
KEYWORD_TO_AUDIO_MOOD: dict[str, str] = {
    "neutral": "neutral",
    "calm": "calm",
    "tense": "tense",
    "uplifting": "uplifting",
    "dark": "dark",
    "ambient": "calm",
}
KEYWORD_TO_AUDIO_PRESENCE: dict[str, str] = {
    "silence": "silence",
    "quiet": "silence",
    "ambient": "ambient",
    "music": "music",
    "sfx": "sfx",
    "full": "full",
}

DEFAULT_COMPOSITION_BALANCE = "balanced"
DEFAULT_COMPOSITION_SYMMETRY = "slight"
DEFAULT_TENSION = "standard"
DEFAULT_AUDIO_TEMPO = "medium"
DEFAULT_AUDIO_MOOD = "neutral"
DEFAULT_AUDIO_PRESENCE = "ambient"

# Words that suggest intensity (0–1)
KEYWORD_TO_INTENSITY: dict[str, float] = {
    "calm": 0.2,
    "gentle": 0.3,
    "intense": 0.9,
    "strong": 0.8,
    "subtle": 0.25,
    "vivid": 0.85,
    "soft": 0.3,
}

DEFAULT_PALETTE = "default"
DEFAULT_MOTION = "flow"
DEFAULT_INTENSITY = 0.5
DEFAULT_GRADIENT = "vertical"
DEFAULT_CAMERA = "static"
DEFAULT_SHAPE = "none"
DEFAULT_SHOT = "medium"
DEFAULT_TRANSITION = "cut"
DEFAULT_LIGHTING = "neutral"
DEFAULT_GENRE = "general"
