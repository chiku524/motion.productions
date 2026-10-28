"""Gated, back-off poller for GET /api/interpret/queue (D1 free tier: see docs/D1_FREE_TIER.md, "interpret queue").

The interpret loop used to ask for the queue on every cycle (compose: every 90 s = 960 calls/day), and the Worker answered
each call with a read of every pending interpretation. The Worker now serves a bounded rowid-cursor window from cache; this
client does its half:

* ``due()`` gates the call: an empty answer waits >= ``min_seconds`` (default 120 s), doubling to ``max_seconds`` (600 s)
  with jitter, and never less than the server's ``poll_after_sec`` / ``Retry-After``.
* Errors (429/503/free-tier cooldown) use ``PollBackoff.error_delay``.
* ``after=<cursor>`` asks only for rows past the highest rowid already handled, so a prompt that failed to interpret (it
  stays ``pending``) is not re-served on every poll. An empty window wraps the cursor to 0 after the idle wait, so failed
  rows are retried at most once per idle interval; retries alone never reset the back-off.
* Finding NEW work resets the back-off and the next cycle polls again straight away.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from .poll_backoff import PollBackoff, queue_hint

logger = logging.getLogger(__name__)

DEFAULT_IDLE_MIN_SECONDS = 120.0
DEFAULT_IDLE_MAX_SECONDS = 600.0


class InterpretQueuePoller:
    def __init__(
        self,
        fetch: Callable[[str], dict],
        limit: int = 20,
        backoff: Optional[PollBackoff] = None,
        clock: Callable[[], float] = time.monotonic,
        cooldown_remaining: Callable[[], float] = lambda: 0.0,
        error_types: tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        self._fetch = fetch
        self.limit = max(1, int(limit))
        self.backoff = backoff or PollBackoff(
            min_seconds=DEFAULT_IDLE_MIN_SECONDS, max_seconds=DEFAULT_IDLE_MAX_SECONDS
        )
        # The idle floor is part of the contract: never poll an empty queue more often than every 120 s.
        if self.backoff.min_seconds < DEFAULT_IDLE_MIN_SECONDS:
            self.backoff.min_seconds = DEFAULT_IDLE_MIN_SECONDS
            self.backoff.max_seconds = max(self.backoff.max_seconds, DEFAULT_IDLE_MIN_SECONDS)
        self._clock = clock
        self._cooldown = cooldown_remaining
        self._error_types = error_types
        self.cursor = 0
        self.high_water = 0
        self.next_at = 0.0

    def due(self) -> bool:
        return self._clock() >= self.next_at

    def seconds_until_due(self) -> float:
        return max(0.0, self.next_at - self._clock())

    def path(self) -> str:
        p = f"/api/interpret/queue?limit={self.limit}"
        return f"{p}&after={self.cursor}" if self.cursor > 0 else p

    def poll(self) -> list[dict[str, Any]]:
        """Fetch one window. Returns the items to process ([] when idle, gated or failed); schedules the next poll."""
        if not self.due():
            return []
        try:
            data = self._fetch(self.path())
        except self._error_types as exc:
            delay = self.backoff.error_delay(exc, self._cooldown())
            self.next_at = self._clock() + delay
            logger.warning("GET /api/interpret/queue failed (%s); next poll in %.0fs", exc, delay)
            return []
        if not isinstance(data, dict):
            data = {}
        items = [i for i in (data.get("items") or []) if isinstance(i, dict)]
        hint = queue_hint(data)
        if not items:
            # Empty window: wrap to the start so earlier failed rows are retried once per idle interval.
            self.cursor = 0
            self.next_at = self._clock() + self.backoff.next_delay(hint)
            return []
        nc = data.get("next_cursor")
        if isinstance(nc, int) and not isinstance(nc, bool) and nc > self.cursor:
            self.cursor = nc
        rids = [i["rid"] for i in items if isinstance(i.get("rid"), int)]
        has_new = (not rids) or any(r > self.high_water for r in rids) or len(rids) < len(items)
        if rids:
            self.high_water = max(self.high_water, max(rids))
        if has_new:
            self.backoff.reset()
            self.next_at = self._clock()  # more may be waiting: poll again next cycle
        else:
            # only rows we already attempted (still pending): process them, but treat the poll as idle
            self.next_at = self._clock() + self.backoff.next_delay(hint)
        return items