"""
Motion curves and time-based functions. Our algorithms only — no external model.
Used by the renderer to drive movement over time.
"""
import math
from typing import Callable


def ease_in_out(t: float) -> float:
    """Smooth 0→1 over 0→1 (ease in-out)."""
    if t <= 0:
        return 0.0
    if t >= 1:
        return 1.0
    return 3 * t * t - 2 * t * t * t  # smoothstep


def wave(t: float, freq: float = 1.0, phase: float = 0.0) -> float:
    """Sinusoidal wave, output in [-1, 1]."""
    return math.sin(2 * math.pi * freq * t + phase)


def flow(t: float, speed: float = 0.5) -> float:
    """Slow drift (bounded)."""
    return (t * speed) % 1.0


def pulse(t: float, freq: float = 0.5) -> float:
    """Pulsing 0–1."""
    return 0.5 + 0.5 * math.sin(2 * math.pi * freq * t)


def get_motion_func(motion_type: str) -> Callable[[float], float]:
    """Return a time→value function for the given motion type (our data)."""
    if motion_type == "slow":
        return lambda t: ease_in_out((t * 0.2) % 1.0)
    if motion_type == "wave":
        return lambda t: 0.5 + 0.5 * wave(t, 0.3)
    if motion_type == "flow":
        return lambda t: flow(t, 0.3)
    if motion_type == "fast":
        return lambda t: (t * 2.0) % 1.0
    if motion_type == "pulse":
        return lambda t: pulse(t, 0.8)
    return lambda t: flow(t, 0.3)
