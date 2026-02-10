"""
Transitions: cut, fade, dissolve, wipe.
Apply to frame sequences at shot boundaries.
"""
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import numpy as np


def apply_transition(
    frame: "np.ndarray",
    t: float,
    duration: float,
    transition_type: str,
    *,
    is_in: bool = True,
) -> "np.ndarray":
    """
    Apply transition to a frame. t = time within transition, duration = transition length.
    is_in: True = fading in, False = fading out.
    Returns frame with alpha/opacity applied for fade/dissolve; for cut, returns frame unchanged.
    """
    import numpy as np

    if transition_type == "cut" or duration <= 0:
        return frame

    progress = min(1.0, max(0.0, t / duration))
    if not is_in:
        progress = 1.0 - progress

    if transition_type == "fade":
        alpha = progress
        frame = frame.astype(np.float64) * alpha
        return np.clip(frame, 0, 255).astype(np.uint8)

    if transition_type == "dissolve":
        alpha = progress
        frame = frame.astype(np.float64) * alpha
        return np.clip(frame, 0, 255).astype(np.uint8)

    if transition_type == "wipe":
        h, w = frame.shape[:2]
        wipe_pos = int(w * progress) if is_in else int(w * (1 - progress))
        mask = np.ones((h, w), dtype=np.float64)
        if is_in:
            mask[:, :wipe_pos] = 0
        else:
            mask[:, wipe_pos:] = 0
        mask = mask[:, :, np.newaxis]
        frame = (frame.astype(np.float64) * mask).astype(np.uint8)
        return frame

    return frame
