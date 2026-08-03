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
    Apply single-frame fade/wipe (to/from black). For true A→B dissolves use
    cross_blend() with the outgoing shot frame.
    """
    import numpy as np

    if transition_type == "cut" or duration <= 0:
        return frame

    progress = min(1.0, max(0.0, t / duration))
    if not is_in:
        progress = 1.0 - progress

    if transition_type in ("fade", "dissolve"):
        # Single-buffer path: dissolve without a partner falls back to fade
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


def cross_blend(
    outgoing: "np.ndarray",
    incoming: "np.ndarray",
    progress: float,
    transition_type: str = "dissolve",
) -> "np.ndarray":
    """
    Blend outgoing shot → incoming shot.
    progress 0 = fully outgoing, 1 = fully incoming.
    """
    import numpy as np

    p = float(min(1.0, max(0.0, progress)))
    a = outgoing.astype(np.float32)
    b = incoming.astype(np.float32)
    if a.shape != b.shape:
        # Size mismatch — prefer incoming
        return incoming

    ttype = (transition_type or "dissolve").lower()
    if ttype == "wipe":
        h, w = a.shape[:2]
        wipe_pos = int(w * p)
        mask = np.zeros((h, w), dtype=np.float32)
        mask[:, :wipe_pos] = 1.0
        # Soft edge
        if wipe_pos > 0 and wipe_pos < w:
            edge = min(6, max(1, w // 40))
            for i in range(edge):
                col = wipe_pos - edge + i
                if 0 <= col < w:
                    mask[:, col] = i / edge
        mask3 = mask[..., None]
        out = a * (1.0 - mask3) + b * mask3
        return np.clip(out, 0, 255).astype(np.uint8)

    # dissolve (and default)
    out = a * (1.0 - p) + b * p
    return np.clip(out, 0, 255).astype(np.uint8)
