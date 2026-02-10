"""
Shot types: wide, medium, close-up, POV.
Affects effective zoom/framing in the renderer.
"""
from typing import Tuple


def get_shot_params(shot_type: str) -> Tuple[float, float, float]:
    """
    Return (zoom_factor, pan_range, handheld_shake) for shot type.
    zoom_factor: >1 = tighter (close), <1 = wider
    pan_range: 0-1, how much camera can pan
    handheld_shake: 0-1, subtle movement for handheld
    """
    if shot_type == "wide":
        return 0.85, 0.15, 0.0
    if shot_type == "medium":
        return 1.0, 0.1, 0.0
    if shot_type == "close":
        return 1.25, 0.05, 0.0
    if shot_type == "close_up":
        return 1.25, 0.05, 0.0
    if shot_type == "pov":
        return 1.1, 0.2, 0.02
    if shot_type == "handheld":
        return 1.0, 0.1, 0.03
    return 1.0, 0.1, 0.0
