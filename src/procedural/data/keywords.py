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
}

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
