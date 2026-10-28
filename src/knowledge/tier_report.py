"""Coverage by evidence tier for the local registries (observed / verified / declared).

Only observed + verified count as coverage; declared (seeds, spec values, guesses) is reported but never
covers a cell. Local files carry the tier per entry; legacy entries are classified by the rules in evidence.py.

    python -m src.knowledge.tier_report
"""
from __future__ import annotations

import json
from typing import Any

from . import sound_v2
from .dynamic_registry import DYNAMIC_ASPECTS, load_dynamic_registry
from .evidence import TIERS, coverage_by_tier
from .narrative_registry import NARRATIVE_ASPECTS, load_narrative_registry
from .static_registry import load_static_registry


def _entries(data: dict[str, Any]) -> list[dict[str, Any]]:
    es = data.get("entries") if isinstance(data, dict) else None
    if isinstance(es, dict):
        return [e for e in es.values() if isinstance(e, dict)]
    return [e for e in (es or []) if isinstance(e, dict)]


def local_tier_coverage(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """{"categories": {name: {observed, verified, declared, covered}}, "totals": {...}, "sound_v2": {...}}."""
    cats: dict[str, list[dict[str, Any]]] = {}
    for aspect in ("colors", "sound"):
        cats[f"static_{aspect}"] = _entries(load_static_registry(aspect, config))
    for a in DYNAMIC_ASPECTS:
        cats[a["id"]] = _entries(load_dynamic_registry(a["id"], config))
    for a in NARRATIVE_ASPECTS:
        cats[f"narrative_{a['id']}"] = _entries(load_narrative_registry(a["id"], config))
    per = coverage_by_tier(cats)
    totals = {t: sum(c[t] for c in per.values()) for t in TIERS}
    totals["covered"] = totals["observed"] + totals["verified"]
    return {
        "categories": per,
        "totals": totals,
        "sound_v2": sound_v2.coverage_stats(config),
        "policy": "Only observed and verified entries count as coverage; declared (seeded, spec or guessed) never does.",
    }


def main() -> int:
    from src.config import load_config  # local import: keep the module import-light

    print(json.dumps(local_tier_coverage(load_config()), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())