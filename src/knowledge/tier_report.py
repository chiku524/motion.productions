"""Coverage by evidence tier for the local registries (observed / verified / declared).

Only observed + verified count as coverage; declared (seeds, spec values, guesses) is reported but never
covers a cell. Local files carry the tier per entry; legacy entries are classified by the rules in evidence.py.

    python -m src.knowledge.tier_report [--remote API_BASE]

The ``exact_color`` section is the exact 8-bit colour registry (16,777,216 cells; docs/COLOR_SURVEY.md), read from
the local bitset store; ``--remote`` adds the Worker's synced coverage counts (one cached GET, no D1 scan).
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


def exact_color_coverage(directory: Any = None, api_base: str = "", get: Any = None) -> dict[str, Any]:
    """Exact-colour coverage from the local bitsets (never creates the store) plus optional Worker counts."""
    from pathlib import Path

    from .color_cells import ColorCellStore, default_store_dir

    path = Path(directory) if directory else default_store_dir()
    out: dict[str, Any] = {"available": False}
    if path.is_dir() and any((path / f"{p}.bits").exists() for p in ("observed", "verified", "declared")):
        store = ColorCellStore(path)
        out = {"available": True, **store.counts()}
    if api_base:
        from .color_sync import fetch_remote_report

        out["remote"] = fetch_remote_report(api_base, get=get)
    return out

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
        "exact_color": exact_color_coverage(),
        "policy": "Only observed and verified entries count as coverage; declared (seeded, spec or guessed) never does.",
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    from src.config import load_config  # local import: keep the module import-light

    ap = argparse.ArgumentParser(description="Coverage by evidence tier")
    ap.add_argument("--remote", default="", help="API base: also include the Worker's synced exact-colour counts")
    args = ap.parse_args(argv)
    report = local_tier_coverage(load_config())
    if args.remote:
        report["exact_color"]["remote"] = exact_color_coverage(api_base=args.remote)["remote"]
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())