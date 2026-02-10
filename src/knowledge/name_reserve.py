"""
Name reserve: mass amounts of unique names on reserve for new discoveries.
Pre-generates a large pool; consumes on demand; refills when low.
Uses the same English-like name generator as blend_names for consistency.
"""
import json
from pathlib import Path
from typing import Any

_MIN_POOL_SIZE = 1000
_DEFAULT_RESERVE_SIZE = 50000


def _generate_batch(count: int, exclude: set[str], start_seed: int = 0) -> list[str]:
    """Generate a batch of unique English-like names (same algorithm as blend_names._invent_word)."""
    from .blend_names import _invent_word

    names: list[str] = []
    seen: set[str] = set(exclude)
    seed = start_seed
    attempts = 0
    max_attempts = count * 20
    while len(names) < count and attempts < max_attempts:
        candidate = _invent_word(seed)
        if len(candidate) >= 4 and candidate not in seen:
            names.append(candidate)
            seen.add(candidate)
        seed += 1237
        attempts += 1
    return names


def _reserve_path(config: dict[str, Any] | None = None) -> Path:
    """Path to name reserve file."""
    from .registry import get_registry_dir
    return get_registry_dir(config) / "name_reserve.json"


def _load_reserve(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Load the name reserve from disk."""
    path = _reserve_path(config)
    if not path.exists():
        return {"pool": [], "used": [], "total_generated": 0}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"pool": [], "used": [], "total_generated": 0}


def _save_reserve(data: dict[str, Any], config: dict[str, Any] | None = None) -> Path:
    """Save the name reserve to disk."""
    from .registry import get_registry_dir
    get_registry_dir(config).mkdir(parents=True, exist_ok=True)
    path = _reserve_path(config)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    return path


def refill(
    target_size: int = _DEFAULT_RESERVE_SIZE,
    *,
    config: dict[str, Any] | None = None,
) -> int:
    """
    Refill the name reserve to target_size. Returns number of names added.
    """
    data = _load_reserve(config)
    pool = data.get("pool", [])
    used = set(data.get("used", []))
    needed = max(0, target_size - len(pool))
    if needed == 0:
        return 0
    existing = set(pool) | used
    start_seed = data.get("total_generated", 0) * 999
    batch = _generate_batch(needed, existing, start_seed=start_seed)
    pool.extend(batch)
    data["pool"] = pool
    data["total_generated"] = data.get("total_generated", 0) + len(batch)
    _save_reserve(data, config)
    return len(batch)


def take(
    *,
    config: dict[str, Any] | None = None,
    ensure_min_pool: int = _MIN_POOL_SIZE,
    refill_target: int = _DEFAULT_RESERVE_SIZE,
) -> str:
    """
    Take the next name from the reserve. If pool is low, refills first.
    Returns a unique name.
    """
    data = _load_reserve(config)
    pool = data.get("pool", [])
    used = data.get("used", [])

    if len(pool) < ensure_min_pool:
        refill(refill_target, config=config)
        data = _load_reserve(config)
        pool = data.get("pool", [])
        used = data.get("used", [])

    if not pool:
        # Fallback: generate one on the fly
        from .blend_names import generate_blend_name
        return generate_blend_name("discovery", "", existing_names=set(used))

    name = pool.pop(0)
    used.append(name)
    data["pool"] = pool
    data["used"] = used[-50000:]  # Keep last 50k used to avoid reuse
    _save_reserve(data, config)
    return name


def reserve_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return current reserve status: pool_size, used_count, total_generated."""
    data = _load_reserve(config)
    return {
        "pool_size": len(data.get("pool", [])),
        "used_count": len(data.get("used", [])),
        "total_generated": data.get("total_generated", 0),
    }


def ensure_reserve(
    min_pool: int = _DEFAULT_RESERVE_SIZE,
    *,
    config: dict[str, Any] | None = None,
) -> int:
    """
    Ensure at least min_pool names are in reserve. Call at startup or periodically.
    Returns number of names in pool after refill.
    """
    data = _load_reserve(config)
    pool = data.get("pool", [])
    if len(pool) >= min_pool:
        return len(pool)
    refill(min_pool, config=config)
    data = _load_reserve(config)
    return len(data.get("pool", []))
