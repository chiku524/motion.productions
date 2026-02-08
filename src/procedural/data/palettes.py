"""
Our data: color palettes (RGB 0–255). Used by the procedural renderer.
No external model — we define every palette ourselves.
"""
# Each palette is a list of (R, G, B) tuples; renderer interpolates or picks by mood
PALETTES: dict[str, list[tuple[int, int, int]]] = {
    "warm_sunset": [
        (255, 120, 80),
        (255, 80, 100),
        (180, 60, 120),
        (100, 40, 100),
    ],
    "ocean": [
        (20, 80, 140),
        (40, 120, 180),
        (80, 160, 220),
        (140, 200, 240),
    ],
    "neon": [
        (255, 0, 128),
        (128, 0, 255),
        (0, 255, 255),
        (255, 255, 0),
    ],
    "forest": [
        (20, 80, 40),
        (40, 120, 60),
        (80, 140, 90),
        (120, 160, 100),
    ],
    "night": [
        (10, 10, 30),
        (30, 20, 60),
        (60, 40, 100),
        (100, 80, 140),
    ],
    "dreamy": [
        (240, 220, 255),
        (220, 200, 255),
        (200, 180, 240),
        (180, 160, 220),
    ],
    "fire": [
        (255, 200, 50),
        (255, 120, 20),
        (200, 60, 10),
        (100, 20, 5),
    ],
    "mono": [
        (240, 240, 240),
        (180, 180, 180),
        (100, 100, 100),
        (40, 40, 40),
    ],
    "default": [
        (60, 60, 80),
        (100, 100, 140),
        (140, 140, 180),
        (200, 200, 220),
    ],
}
