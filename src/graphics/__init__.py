"""
Graphics: text overlays, arrows, callouts. Phase 4.
"""
from .text import render_text_overlay
from .primitives import draw_arrow, draw_callout, draw_spotlight
from .templates import get_educational_template

__all__ = [
    "render_text_overlay",
    "draw_arrow",
    "draw_callout",
    "draw_spotlight",
    "get_educational_template",
]
