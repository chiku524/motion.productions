"""Idle-poll back-off for queue pollers (D1 free tier: every poll that misses the Worker cache costs D1 rows read).

A poller that finds nothing should not ask again every few seconds: wait ``min_seconds`` (default 60 s) after the
first empty answer, double the wait on each further empty/degraded/429 answer up to ``max_seconds`` (default 600 s),
add jitter so several containers do not fire together, and never wait less than the server asked for
(``Retry-After`` header or ``poll_after_sec`` in the body). Finding work resets the sequence.
"""
from __future__ import annotations

import os
import random
from typing import Callable, Optional

DEFAULT_MIN_SECONDS = 60.0
DEFAULT_MAX_SECONDS = 600.0
DEFAULT_FACTOR = 2.0
DEFAULT_JITTER = 0.25  # wait is multiplied by a random factor in [1, 1 + jitter]: jitter never shortens the wait


def _env_float(name: str, default: float) -> float:
    try:
        v = float((os.environ.get(name) or "").strip())
        return v if v > 0 else default
    except ValueError:
        return default


class PollBackoff:
    """Exponential back-off with jitter that honours server hints. Not thread-safe (one per poll loop)."""

    def __init__(
        self,
        min_seconds: float | None = None,
        max_seconds: float | None = None,
        factor: float = DEFAULT_FACTOR,
        jitter: float = DEFAULT_JITTER,
        rng: Optional[Callable[[], float]] = None,
    ) -> None:
        self.min_seconds = float(min_seconds if min_seconds is not None else _env_float("POLL_IDLE_MIN_SECONDS", DEFAULT_MIN_SECONDS))
        self.max_seconds = max(self.min_seconds, float(max_seconds if max_seconds is not None else _env_float("POLL_IDLE_MAX_SECONDS", DEFAULT_MAX_SECONDS)))
        self.factor = max(1.0, factor)
        self.jitter = max(0.0, jitter)
        self._rng = rng or random.random
        self.misses = 0

    def reset(self) -> None:
        """Work was found (or the call succeeded with data): the next idle wait starts at min_seconds again."""
        self.misses = 0

    def next_delay(self, hint: float | None = None) -> float:
        """Seconds to sleep after an empty / degraded / rate-limited answer; escalates the sequence by one step.

        ``hint`` (Retry-After / poll_after_sec) is a floor: the result is never shorter. A hint above ``max_seconds``
        is honoured as-is (the server knows best), but is not escalated further.
        """
        base = min(self.max_seconds, self.min_seconds * (self.factor ** self.misses))
        self.misses += 1
        delay = base * (1.0 + self.jitter * self._rng())
        if hint is not None and hint > 0:
            delay = max(delay, float(hint))
        return delay

    def error_delay(self, exc: BaseException | None = None, cooldown_remaining: float = 0.0) -> float:
        """Delay after a failed poll. Honours ``exc.retry_after`` (APIError), a 429/503 status, and any shared cooldown."""
        hint = getattr(exc, "retry_after", None)
        floor = max(float(hint) if isinstance(hint, (int, float)) else 0.0, float(cooldown_remaining or 0.0))
        return self.next_delay(floor or None)


def queue_hint(payload: object, headers: object = None) -> float | None:
    """Server back-off hint from a queue response: body ``poll_after_sec`` or a ``Retry-After`` header (largest wins)."""
    vals: list[float] = []
    if isinstance(payload, dict):
        v = payload.get("poll_after_sec")
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            vals.append(float(v))
    if headers is not None:
        for key in ("Retry-After", "retry-after"):
            try:
                raw = headers.get(key)  # type: ignore[union-attr]
                if raw is not None:
                    vals.append(max(0.0, float(raw)))
                    break
            except (TypeError, ValueError, AttributeError):
                pass
    vals = [v for v in vals if v > 0]
    return max(vals) if vals else None
