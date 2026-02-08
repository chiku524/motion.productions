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

# Words that suggest camera-style motion
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
DEFAULT_GRADIENT = "vertical"
DEFAULT_CAMERA = "static"
DEFAULT_SHAPE = "none"
