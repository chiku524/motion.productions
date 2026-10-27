"""
Evidence tiers for registry cells (docs/EXHAUSTIVE_REGISTRY_PLAN.md).

  observed  (T1) - measured from the decoded clip by the extractor.
  verified  (T2) - observed AND confirmed: a render that aimed at the cell was decoded and the extractor
                   measured that very cell (closed loop), or the cell was re-observed independently.
  declared  (T3) - taken from a spec, a seed grid, a default or a guess. Never counts as coverage.

Only observed + verified cells are coverage. Everything the extractor cannot measure yet stays declared:
camera motion guessed from frame differences, audio semantics guessed from loudness, an empty depth,
a transition whose duration was not measured, and every pre-seeded primitive.
"""
from __future__ import annotations

from typing import Any, Iterable

OBSERVED = "observed"
VERIFIED = "verified"
DECLARED = "declared"
TIERS: tuple[str, ...] = (OBSERVED, VERIFIED, DECLARED)
COVERING_TIERS: frozenset[str] = frozenset({OBSERVED, VERIFIED})

# Source markers written by seeding code (not by clip analysis).
SEED_SOURCES = frozenset({"primitive_seed", "spec_seed", "seed"})

# Categories whose values are measured straight from decoded pixels/audio samples.
MEASURED_CATEGORIES = frozenset(
    {"motion", "time", "gradient", "lighting", "composition", "graphics", "temporal", "technical"}
)
# Categories that stay declared unless the extractor attaches measured evidence to the window.
GUESSED_CATEGORIES = frozenset({"camera", "audio_semantic", "transition", "depth"})


def normalize_tier(value: Any, default: str = DECLARED) -> str:
    v = str(value or "").strip().lower()
    return v if v in TIERS else default


def covers(tier: Any) -> bool:
    """True only for tiers that count as coverage."""
    return normalize_tier(tier) in COVERING_TIERS


def best_tier(a: Any, b: Any) -> str:
    """The stronger of two tiers (verified > observed > declared)."""
    order = {DECLARED: 0, OBSERVED: 1, VERIFIED: 2}
    return a if order[normalize_tier(a)] >= order[normalize_tier(b)] else b  # type: ignore[return-value]


def window_tiers(window: dict[str, Any]) -> dict[str, str]:
    """Tier per dynamic category for one extracted window.

    The extractor sets window["evidence"] for what it really measured. Anything absent falls back to the
    category default: measured categories are observed, guessed categories are declared.
    """
    ev = window.get("evidence") if isinstance(window, dict) else None
    ev = ev if isinstance(ev, dict) else {}
    out: dict[str, str] = {}
    for cat in MEASURED_CATEGORIES:
        out[cat] = normalize_tier(ev.get(cat), OBSERVED)
    for cat in GUESSED_CATEGORIES:
        out[cat] = normalize_tier(ev.get(cat), DECLARED)
    return out


def entry_tier(category: str, entry: dict[str, Any] | None) -> str:
    """Tier of a stored registry entry. An explicit evidence_tier wins; legacy entries are classified by rule."""
    entry = entry or {}
    explicit = entry.get("evidence_tier")
    if explicit:
        return normalize_tier(explicit)
    cat = str(category or "").lower()
    srcs = entry.get("sources")
    if isinstance(srcs, list) and (not srcs or all(str(s) in SEED_SOURCES for s in srcs)):
        return DECLARED  # only ever pre-seeded: a grid of primitives, never measured from a clip
    if cat in MEASURED_CATEGORIES:
        return OBSERVED
    if cat == "transition":
        dur = entry.get("duration_seconds", entry.get("duration", 0))
        try:
            return OBSERVED if float(dur or 0) > 0 else DECLARED  # 0.0 was a constant, not a measurement
        except (TypeError, ValueError):
            return DECLARED
    if cat in GUESSED_CATEGORIES:
        return DECLARED
    if cat in ("static_sound", "sound", "sound_v1"):
        # v1 pure sounds were extracted, but seeded/spec-derived rows are indistinguishable without a tier.
        return DECLARED if str(entry.get("source") or "").lower() in ("seed", "spec") else OBSERVED
    return OBSERVED


def tier_counts(tiers: Iterable[Any]) -> dict[str, int]:
    c = {t: 0 for t in TIERS}
    for t in tiers:
        c[normalize_tier(t)] += 1
    return c


def coverage_by_tier(
    entries: dict[str, list[dict[str, Any]] | dict[str, Any]],
) -> dict[str, dict[str, int]]:
    """{category: {observed, verified, declared, covered}} from {category: entries (dict values or list)}."""
    out: dict[str, dict[str, int]] = {}
    for cat, es in (entries or {}).items():
        rows = list(es.values()) if isinstance(es, dict) else list(es or [])
        counts = tier_counts(entry_tier(cat, e if isinstance(e, dict) else {}) for e in rows)
        counts["covered"] = counts[OBSERVED] + counts[VERIFIED]
        out[cat] = counts
    return out