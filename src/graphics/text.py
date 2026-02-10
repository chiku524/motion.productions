"""
Text rendering: titles, subtitles, bullet points.
Phase 4.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def render_text_overlay(
    frame: "np.ndarray",
    text: str,
    *,
    position: str = "center",  # center | top | bottom | top_left | top_right | bottom_left | bottom_right
    font_size: int = 48,
    color: tuple[int, int, int] = (255, 255, 255),
    outline_color: tuple[int, int, int] | None = (0, 0, 0),
    outline_width: int = 2,
    max_width: int | None = None,
) -> "np.ndarray":
    """
    Draw text on a frame. Uses Pillow for rendering.
    Returns frame with text composited.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return frame

    import numpy as np

    if not text or not text.strip():
        return frame

    h, w = frame.shape[:2]
    pil = Image.fromarray(frame)
    draw = ImageDraw.Draw(pil)

    try:
        font = ImageFont.truetype("arial.ttf", font_size)
    except (OSError, IOError):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except (OSError, IOError):
            font = ImageFont.load_default()

    # Word wrap if max_width set
    lines = _wrap_text(text, font, draw, max_width or w - 40)

    # Compute bounding box for all lines
    bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_height = max(b[3] - b[1] for b in bboxes) if bboxes else font_size
    total_height = line_height * len(lines)
    first_bbox = bboxes[0] if bboxes else (0, 0, 0, 0)
    line_w = first_bbox[2] - first_bbox[0]

    # Position
    x_center = w // 2
    y_top = _y_for_position(position, h, total_height)

    for i, line in enumerate(lines):
        bx = bboxes[i]
        lw = bx[2] - bx[0]
        x = x_center - lw // 2
        y = y_top + i * line_height

        if outline_color and outline_width:
            for dx in range(-outline_width, outline_width + 1):
                for dy in range(-outline_width, outline_width + 1):
                    if dx or dy:
                        draw.text((x + dx, y + dy), line, font=font, fill=outline_color)
        draw.text((x, y), line, font=font, fill=color)

    return np.array(pil)


def _wrap_text(text: str, font, draw, max_width: int) -> list[str]:
    """Simple word wrap."""
    words = text.split()
    lines: list[str] = []
    current: list[str] = []
    for word in words:
        test = " ".join(current + [word])
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
    if current:
        lines.append(" ".join(current))
    return lines if lines else [text]


def _y_for_position(position: str, height: int, text_height: int) -> int:
    if position in ("top", "top_left", "top_right"):
        return 20
    if position in ("bottom", "bottom_left", "bottom_right"):
        return height - text_height - 20
    return (height - text_height) // 2
