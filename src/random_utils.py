"""
Crypto-quality random for growth and creation (BACKLOG_AND_ENHANCEMENTS).
Uses secrets module to avoid bias in domain value selection.
"""
import hashlib
import secrets
from typing import Callable, TypeVar

T = TypeVar("T")


def secure_choice(sequence):
    """Cryptographically secure random choice. Use for pick_prompt, creation, prompt_gen."""
    if not sequence:
        return None
    return secrets.choice(list(sequence))


def secure_random():
    """Cryptographically secure random float in [0, 1)."""
    return secrets.SystemRandom().random()


def fresh_seed(*salt) -> int:
    """31-bit seed that is unique to this generation.

    ``salt`` (job id, run count, ...) is mixed in with OS entropy through BLAKE2b, so two
    workers with the same job id or counter still diverge. Never uses Python's salted
    ``hash()`` or an arithmetic function of a counter.
    """
    if not salt:
        return secrets.randbits(31)
    h = hashlib.blake2b(digest_size=8)
    h.update(secrets.token_bytes(16))
    for s in salt:
        h.update(b"\x1f" + str(s).encode("utf-8", "replace"))
    return int.from_bytes(h.digest(), "big") & 0x7FFFFFFF


def weighted_choice(items, weights, rng=None):
    """Pick one item with probability proportional to ``weights`` (non-negative).

    ``rng`` may be any object with ``random()`` (e.g. ``random.Random(1)``) for deterministic
    tests; by default the OS CSPRNG is used. Falls back to a uniform pick if all weights are 0.
    """
    items = list(items)
    if not items:
        return None
    ws = [max(0.0, float(w)) for w in weights]
    total = sum(ws)
    r = (rng.random() if rng is not None else secrets.SystemRandom().random())
    if total <= 0:
        return items[min(int(r * len(items)), len(items) - 1)]
    r *= total
    for item, w in zip(items, ws):
        r -= w
        if r < 0:
            return item
    return items[-1]


def weighted_choice_favor_underused(
    items: list[T],
    get_count: Callable[[T], int],
) -> T | None:
    """
    Pick one item with probability inversely proportional to (1 + count).
    Favors underused entries (lower count = higher chance). Use for registry selection.
    """
    if not items:
        return None
    weights = [1.0 / (1.0 + max(0, get_count(x))) for x in items]
    total = sum(weights)
    if total <= 0:
        return secrets.choice(items)
    r = secrets.SystemRandom().random() * total
    for i, w in enumerate(weights):
        r -= w
        if r <= 0:
            return items[i]
    return items[-1]


def weighted_choice_favor_recent(
    items: list[T],
    get_created_at: Callable[[T], str | None],
) -> T | None:
    """
    Pick one item with probability favoring more recent created_at (ISO datetime string).
    Older entries get lower weight. Use for learned_audio / any list with created_at.
    """
    if not items:
        return None
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    weights = []
    for x in items:
        raw = get_created_at(x)
        if not raw:
            weights.append(1.0)
            continue
        try:
            # Parse ISO-ish datetime; assume UTC if no tz
            dt = datetime.datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=datetime.timezone.utc)
            days_ago = (now - dt).total_seconds() / 86400.0
            # weight = 1 / (1 + days_ago) so recent = higher
            weights.append(1.0 / (1.0 + max(0, days_ago)))
        except Exception:
            weights.append(1.0)
    total = sum(weights)
    if total <= 0:
        return secrets.choice(items)
    r = secrets.SystemRandom().random() * total
    for i, w in enumerate(weights):
        r -= w
        if r <= 0:
            return items[i]
    return items[-1]
