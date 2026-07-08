#!/usr/bin/env python3
"""
Registry cleanup — audit, fix, and export registries for human readability.

Aligns with REGISTRY_FOUNDATION.md: every entry should have accurate data,
semantic/readable names, and complete depth breakdowns where applicable.

Steps:
  audit   — fetch live data and report readability/accuracy issues
  names   — backfill gibberish names across all D1 tables
  depths  — recalculate depth_breakdown for colors/motion/lighting
  sanitize — canonicalize Pure sound keys (fix mood leakage)
  export  — save a human-readable JSON snapshot
  all     — run audit → names → depths → export (audit repeated at end)

Usage:
  python scripts/registry_cleanup.py audit
  python scripts/registry_cleanup.py names --dry-run
  python scripts/registry_cleanup.py depths --table static_colors
  python scripts/registry_cleanup.py export
  python scripts/registry_cleanup.py all --api-base https://motion.productions
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api_client import api_request_with_retry
from src.knowledge.blend_names import is_semantic_name, narrative_display_name

EXPORT_DIR = ROOT / "json registry exports"

NARRATIVE_ASPECTS = ("genre", "mood", "themes", "plots", "settings", "style", "scene_type")
NAME_TABLES = [
    "static_colors", "learned_colors", "learned_motion", "learned_blends",
    "learned_gradient", "learned_camera", "learned_lighting", "learned_composition",
    "learned_graphics", "learned_temporal", "learned_technical", "learned_audio_semantic",
    "learned_time", "learned_transition", "learned_depth", "static_sound", "narrative_entries",
]
DEPTH_TABLES = ["static_colors", "learned_colors", "learned_motion", "learned_lighting"]

_ASPECT_PREFIX = re.compile(r"^(theme|plot|setting|scene|genre|mood|style)_", re.I)
_DIGITS = re.compile(r"\d{2,}")


def _is_gibberish(name: str | None) -> bool:
    if not name or not str(name).strip():
        return True
    n = str(name).strip()
    # Disambiguated color names are readable: "Cyan (100,125,175)"
    if re.match(r"^.+\(\d+,\d+,\d+\)$", n):
        return False
    if n.lower().startswith("dsc_"):
        return True
    if re.match(r"^novel\d+$", n, re.I):
        return True
    if _ASPECT_PREFIX.match(n):
        return True
    if _DIGITS.search(n):
        return True
    return not is_semantic_name(n)


def _should_fix_narrative_name(name: str | None, entry_key: str, value: str) -> bool:
    readable = narrative_display_name("", entry_key, value)
    if not name or not str(name).strip():
        return True
    n = str(name).strip()
    if n == readable:
        return False
    if _is_gibberish(n):
        return True
    ek = (entry_key or "").lower()
    if len(ek) >= 3 and ek not in n.lower():
        return True
    return False


def _format_key(key: str) -> str:
    if not key:
        return key
    try:
        parsed = json.loads(key)
        if isinstance(parsed, dict) and all(k in parsed for k in ("r", "g", "b")):
            r, g, b = round(float(parsed["r"])), round(float(parsed["g"])), round(float(parsed["b"]))
            return f"rgb({r},{g},{b})"
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return key if len(key) <= 60 else key[:57] + "…"


def fetch_registries(base: str, limit: int = 500) -> dict:
    return api_request_with_retry(base, "GET", f"/api/registries?limit={limit}", timeout=60)


def fetch_coverage(base: str) -> dict:
    return api_request_with_retry(base, "GET", "/api/registries/coverage", timeout=30)


def fetch_health(base: str) -> dict:
    try:
        return api_request_with_retry(base, "GET", "/api/registries/health", timeout=60)
    except Exception:
        return {}


def sanitize_sound_keys(base: str, *, dry_run: bool = False) -> dict:
    path = "/api/registries/sanitize-sound-keys"
    if dry_run:
        path += "?dry_run=1"
    return api_request_with_retry(base, "POST", path, timeout=120)


def audit_registries(base: str, *, limit: int = 500, verbose: bool = True) -> dict:
    """Audit live registry data for readability and accuracy issues."""
    data = fetch_registries(base, limit=limit)
    coverage = fetch_coverage(base)
    health = fetch_health(base)
    issues: list[dict] = []
    summary: dict[str, int] = {
        "gibberish_names": 0,
        "missing_depth": 0,
        "unreadable_keys": 0,
        "narrative_mismatches": 0,
        "pure_sound_semantic_keys": 0,
    }
    if health.get("issues"):
        hi = health["issues"]
        summary["pure_sound_semantic_keys"] = int(hi.get("pure_sound_semantic_keys") or 0)

    static = data.get("static") or {}
    for c in static.get("colors") or []:
        if _is_gibberish(c.get("name")):
            summary["gibberish_names"] += 1
            issues.append({"registry": "pure", "aspect": "color", "key": c.get("key"), "name": c.get("name"), "issue": "gibberish_name"})
        if not c.get("depth_breakdown"):
            summary["missing_depth"] += 1
            issues.append({"registry": "pure", "aspect": "color", "key": c.get("key"), "name": c.get("name"), "issue": "missing_depth"})

    for s in static.get("sound") or []:
        if s.get("key_leak"):
            summary["pure_sound_semantic_keys"] += 1
            issues.append({"registry": "pure", "aspect": "sound", "key": s.get("key"), "canonical": s.get("canonical_key"), "issue": "semantic_key_leak"})
        if _is_gibberish(s.get("name")):
            summary["gibberish_names"] += 1
            issues.append({"registry": "pure", "aspect": "sound", "key": s.get("key"), "name": s.get("name"), "issue": "gibberish_name"})

    dynamic = data.get("dynamic") or {}
    for aspect in ("colors", "motion", "gradient", "camera", "sound", "lighting",
                   "composition", "graphics", "temporal", "technical", "colors_from_blends", "blends"):
        for entry in dynamic.get(aspect) or []:
            name = entry.get("name")
            key = str(entry.get("key") or "")
            if _is_gibberish(name):
                summary["gibberish_names"] += 1
                issues.append({"registry": "blended", "aspect": aspect, "key": key[:60], "name": name, "issue": "gibberish_name"})
            if aspect not in ("blends",) and not entry.get("depth_breakdown") and not (aspect == "motion" and entry.get("depth_pct")):
                summary["missing_depth"] += 1
                issues.append({"registry": "blended", "aspect": aspect, "key": key[:60], "name": name, "issue": "missing_depth"})
            if key.startswith("{") and '"r"' in key:
                summary["unreadable_keys"] += 1
                issues.append({"registry": "blended", "aspect": aspect, "key": key[:60], "name": name, "issue": "unreadable_key"})

    narrative = data.get("narrative") or {}
    for aspect in NARRATIVE_ASPECTS:
        for entry in narrative.get(aspect) or []:
            ek = entry.get("entry_key") or ""
            val = entry.get("value") or ek
            name = entry.get("name")
            if _should_fix_narrative_name(name, ek, val):
                summary["narrative_mismatches"] += 1
                readable = narrative_display_name(aspect, ek, val)
                issues.append({
                    "registry": "semantic",
                    "aspect": aspect,
                    "entry_key": ek,
                    "name": name,
                    "readable": readable,
                    "issue": "narrative_name_mismatch",
                })

    report = {
        "audited_at": datetime.now(timezone.utc).isoformat(),
        "api_base": base,
        "coverage": coverage,
        "health": health,
        "summary": summary,
        "total_issues": sum(summary.values()),
        "issues": issues[:200],
        "issues_truncated": len(issues) > 200,
    }

    if verbose:
        print("=== REGISTRY CLEANUP AUDIT ===")
        print(f"API: {base}")
        print(f"Coverage: static colors {coverage.get('static_colors_count', 0)} "
              f"({coverage.get('static_colors_coverage_pct', 0)}% of ~28k cells), "
              f"sound {coverage.get('static_sound_count', 0)}, "
              f"learned colors {coverage.get('learned_colors_count', 0)}")
        narr = coverage.get("narrative") or {}
        if narr:
            print(f"Narrative min coverage: {coverage.get('narrative_min_coverage_pct', 0)}%")
        if health.get("issues"):
            hi = health["issues"]
            print()
            print("Health API:")
            print(f"  pure_sound_semantic_keys: {hi.get('pure_sound_semantic_keys', 0)}")
            print(f"  blended_motion_missing_depth: {hi.get('blended_motion_missing_depth', 0)}")
            for rec in health.get("recommendations") or []:
                print(f"  -> {rec}")
        print()
        print("Issues found:")
        for k, v in summary.items():
            print(f"  {k}: {v}")
        print(f"  total: {report['total_issues']}")
        if issues:
            print()
            print("Sample issues (up to 15):")
            for item in issues[:15]:
                detail = item.get("readable") or item.get("key") or item.get("entry_key") or ""
                print(f"  [{item['registry']}/{item['aspect']}] {item['issue']}: "
                      f"name={item.get('name')!r} {detail}")

    return report


def run_name_backfill(base: str, *, dry_run: bool = False, limit: int = 100, table: str | None = None, timeout: int = 300) -> int:
    tables = [table] if table else NAME_TABLES
    if table and table not in NAME_TABLES:
        print(f"Unknown table: {table}. Valid: {', '.join(NAME_TABLES)}")
        sys.exit(1)
    grand_total = 0
    for tbl in tables:
        total = 0
        while True:
            qs = [f"limit={min(limit, 500)}", f"table={tbl}"]
            if dry_run:
                qs.append("dry_run=1")
            path = "/api/registries/backfill-names?" + "&".join(qs)
            tbl_timeout = max(timeout, 360) if tbl == "learned_blends" else timeout
            r = api_request_with_retry(base, "POST", path, data={}, timeout=tbl_timeout)
            updated = r.get("updated", 0)
            total += updated
            grand_total += updated
            if updated > 0:
                print(f"  {tbl}: {updated} {'would be ' if dry_run else ''}updated")
            if updated == 0 or dry_run:
                break
        if total > 0 and not dry_run:
            print(f"  {tbl}: {total} total")
    print(f"Names: {grand_total} {'would be ' if dry_run else ''}updated")
    return grand_total


def run_depth_backfill(base: str, *, dry_run: bool = False, limit: int = 50, table: str | None = None) -> int:
    from src.knowledge.blend_depth import compute_color_depth, compute_motion_depth, compute_lighting_depth

    tables = [table] if table else DEPTH_TABLES
    if table and table not in DEPTH_TABLES:
        print(f"Unknown table: {table}. Valid: {', '.join(DEPTH_TABLES)}")
        sys.exit(1)

    def to_pct(d: dict[str, float]) -> dict[str, float]:
        return {k: round(v * 100) if v <= 1 else round(v) for k, v in d.items()}

    grand_total = 0
    for tbl in tables:
        try:
            r = api_request_with_retry(
                base, "GET", f"/api/registries/backfill-rows?table={tbl}&limit={limit}", timeout=30
            )
            rows = r.get("rows") or []
        except Exception as e:
            print(f"  {tbl}: fetch failed — {e}")
            continue
        updates = []
        for row in rows:
            rid = row.get("id")
            if not rid:
                continue
            depth: dict[str, float] = {}
            if tbl in ("static_colors", "learned_colors"):
                depth = compute_color_depth(float(row.get("r", 0)), float(row.get("g", 0)), float(row.get("b", 0)))
            elif tbl == "learned_motion":
                depth = compute_motion_depth(float(row.get("motion_level", 0)), str(row.get("motion_trend", "steady")))
            elif tbl == "learned_lighting":
                depth = compute_lighting_depth(
                    float(row.get("brightness", 128)),
                    float(row.get("contrast", 50)),
                    float(row.get("saturation", 1.0)),
                )
            if depth:
                updates.append({"table": tbl, "id": rid, "depth_breakdown": to_pct(depth)})
        if not updates:
            continue
        qs = "dry_run=1" if dry_run else ""
        path = "/api/registries/backfill-depths" + ("?" + qs if qs else "")
        resp = api_request_with_retry(base, "POST", path, data={"updates": updates}, timeout=60)
        count = resp.get("updated", 0)
        grand_total += count
        print(f"  {tbl}: {count} depth_breakdown {'would be ' if dry_run else ''}updated")
    print(f"Depths: {grand_total} {'would be ' if dry_run else ''}updated")
    return grand_total


def export_readable_snapshot(base: str, *, limit: int = 500) -> Path:
    """Export a human-readable registry snapshot to json registry exports/."""
    data = fetch_registries(base, limit=limit)
    coverage = fetch_coverage(base)

    static = data.get("static") or {}
    dynamic = data.get("dynamic") or {}
    narrative = data.get("narrative") or {}

    for entry in dynamic.get("colors_from_blends") or []:
        key = entry.get("key")
        if key:
            entry["key_display"] = _format_key(str(key))

    for aspect in NARRATIVE_ASPECTS:
        for entry in narrative.get(aspect) or []:
            ek = entry.get("entry_key") or ""
            val = entry.get("value") or ek
            entry["name_display"] = narrative_display_name(aspect, ek, val)

    snapshot = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "exported_schema_version": 2,
        "exported_by": "registry_cleanup.py",
        "api_base": base,
        "registries": {
            "pure_static": {
                "primitives": data.get("static_primitives") or {},
                "discoveries": {
                    "colors": static.get("colors") or [],
                    "sound": static.get("sound") or [],
                },
            },
            "blended_dynamic": {
                "canonical": data.get("dynamic_canonical") or {},
                "discoveries": dynamic,
            },
            "semantic_narrative": narrative,
            "interpretation": data.get("interpretation") or [],
            "linguistic": data.get("linguistic") or [],
        },
        "coverage_snapshot": coverage,
    }

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out_path = EXPORT_DIR / f"motion-registries-{stamp}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(snapshot, f, indent=2, ensure_ascii=False)
    print(f"Exported readable snapshot: {out_path}")
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description="Audit, clean, and export registries for human readability")
    p.add_argument("command", choices=["audit", "names", "depths", "sanitize", "export", "all"],
                    help="audit=report; names=backfill names; depths=recalc depths; sanitize=fix sound keys; export=snapshot; all=full cleanup")
    p.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"))
    p.add_argument("--dry-run", action="store_true", help="Preview names/depths without writing")
    p.add_argument("--limit", type=int, default=100, help="Batch size per table (default 100)")
    p.add_argument("--timeout", type=int, default=300, help="Request timeout seconds for backfill-names (default 300)")
    p.add_argument("--table", help="Process only this table (names or depths)")
    p.add_argument("--quiet", action="store_true", help="Suppress detailed audit output")
    args = p.parse_args()
    base = args.api_base.rstrip("/")

    if args.command == "audit":
        audit_registries(base, verbose=not args.quiet)
    elif args.command == "names":
        run_name_backfill(base, dry_run=args.dry_run, limit=args.limit, table=args.table, timeout=args.timeout)
    elif args.command == "depths":
        run_depth_backfill(base, dry_run=args.dry_run, limit=args.limit, table=args.table)
    elif args.command == "sanitize":
        r = sanitize_sound_keys(base, dry_run=args.dry_run)
        print(f"Sound keys: {r.get('updated', 0)} updated, {r.get('merged', 0)} merged"
              + (" (dry-run)" if args.dry_run else ""))
    elif args.command == "export":
        export_readable_snapshot(base, limit=max(args.limit, 500))
    elif args.command == "all":
        print("Step 1/4: Audit (before)")
        audit_registries(base, verbose=not args.quiet)
        print("\nStep 2/4: Name backfill")
        run_name_backfill(base, dry_run=args.dry_run, limit=args.limit, table=args.table, timeout=args.timeout)
        if not args.dry_run:
            print("\nStep 3/4: Depth backfill")
            run_depth_backfill(base, dry_run=False, limit=args.limit, table=args.table)
            print("\nStep 4/4: Export + audit (after)")
            export_readable_snapshot(base, limit=max(args.limit, 500))
            audit_registries(base, verbose=not args.quiet)
        else:
            print("\n(dry-run: skipping depths, export, and post-audit)")


if __name__ == "__main__":
    main()
