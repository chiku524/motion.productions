#!/usr/bin/env python3
"""
Registry export analysis — growth velocity, loop progress, schema gaps, data quality.

Run against exported registry JSON (e.g. from Export JSON on the registries page).
Aligns with Motion.Productions_Registry_Comparison_&_Optimization_Report and
enhancement_and_optimization_report: validates tone leakage, depth coverage,
exploit/explore ratio, and schema shape.

Usage:
  python scripts/registry_export_analysis.py
      # uses latest 3 files from "json registry exports/motion-registries-*.json"
  python scripts/registry_export_analysis.py path/to/export1.json path/to/export2.json
  python scripts/registry_export_analysis.py --single path/to/export.json
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


def safe_get(d: dict, *keys: str):
    """Navigate nested dict; return [] or value. For list counts."""
    obj = d
    for k in keys:
        if isinstance(obj, dict):
            obj = obj.get(k, [])
        else:
            return [] if "list" in str(type(obj)).lower() else None
    return obj if isinstance(obj, list) else (obj if isinstance(obj, dict) else [])


def load_snapshots(paths: list[Path]) -> dict[str, dict]:
    """Load JSON exports; key by stem date or label."""
    snapshots = {}
    for i, p in enumerate(paths):
        if not p.exists():
            raise FileNotFoundError(p)
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        # Label from filename (e.g. motion-registries-2026-02-24 -> Feb 24)
        stem = p.stem
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", stem)
        if m:
            label = f"{m.group(2)}-{m.group(3)}"
        else:
            label = f"Export_{i+1}"
        snapshots[label] = data
    return snapshots


def run_analysis(snapshots: dict[str, dict]) -> None:
    if not snapshots:
        print("No snapshots loaded.")
        return

    labels = sorted(snapshots.keys())
    # Registries may nest interpretation/linguistic under registries (export shape from app.js)
    def interp(d: dict) -> list:
        r = d.get("registries") or {}
        return r.get("interpretation") if isinstance(r.get("interpretation"), list) else d.get("interpretation") or []

    def ling(d: dict) -> list:
        r = d.get("registries") or {}
        return r.get("linguistic") if isinstance(r.get("linguistic"), list) else d.get("linguistic") or []

    def sem(d: dict, key: str) -> int:
        r = d.get("registries") or {}
        sn = r.get("semantic_narrative") or {}
        arr = sn.get(key) if isinstance(sn, dict) else []
        return len(arr) if isinstance(arr, list) else 0

    categories = {
        "pure_colors": lambda d: len(safe_get(d, "registries", "pure_static", "discoveries", "colors")),
        "pure_sound": lambda d: len(safe_get(d, "registries", "pure_static", "discoveries", "sound")),
        "blended_motion": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "motion")),
        "blended_lighting": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "lighting")),
        "blended_composition": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "composition")),
        "blended_graphics": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "graphics")),
        "blended_temporal": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "temporal")),
        "blended_blends": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "blends")),
        "blended_cfb": lambda d: len(safe_get(d, "registries", "blended_dynamic", "discoveries", "colors_from_blends")),
        "semantic_genre": lambda d: sem(d, "genre"),
        "semantic_mood": lambda d: sem(d, "mood"),
        "semantic_themes": lambda d: sem(d, "themes"),
        "semantic_settings": lambda d: sem(d, "settings"),
        "semantic_plots": lambda d: sem(d, "plots"),
        "semantic_style": lambda d: sem(d, "style"),
        "semantic_scene_type": lambda d: sem(d, "scene_type"),
        "interpretation": lambda d: len(interp(d)),
        "linguistic": lambda d: len(ling(d)),
    }

    # ---- 1. GROWTH VELOCITY ----
    print("=== GROWTH VELOCITY: ENTRIES PER CATEGORY ===")
    n = len(labels)
    header = "{:<30}".format("Category") + "".join("{:>8}".format(l) for l in labels)
    if n >= 2:
        header += "  {:>8}  {:>8}".format(labels[0] + "->" + labels[1][:3], labels[-2][:3] + "->" + labels[-1][:3] if n > 2 else "delta")
    print(header)
    print("-" * (30 + 8 * n + (20 if n >= 2 else 0)))
    for cat, fn in categories.items():
        vals = [fn(snapshots[l]) for l in labels]
        row = "{:<30}".format(cat) + "".join("{:>8}".format(v) for v in vals)
        if n >= 2:
            d1 = vals[1] - vals[0]
            d2 = (vals[-1] - vals[-2]) if n > 2 else d1
            row += "  {:>+8}  {:>+8}".format(d1, d2)
        print(row)

    # ---- 2. LOOP PROGRESS: exploit/explore ----
    print()
    print("=== LOOP PROGRESS: EXPLOIT/EXPLORE RATIO ===")
    for label in labels:
        data = snapshots[label]
        lp = data.get("loop_progress") or {}
        exploit = lp.get("exploit_count", 0)
        explore = lp.get("explore_count", 0)
        total = exploit + explore
        discovery_rate = lp.get("discovery_rate_pct", 0)
        repetition = lp.get("repetition_score", 0)
        precision = lp.get("precision_pct", 0)
        ratio = (exploit / total * 100) if total else 0
        print("  {}: exploit={}, explore={}, ratio={:.0f}% exploit, discovery_rate={}%, repetition={}, precision={}%".format(
            label, exploit, explore, ratio, discovery_rate, repetition, precision))

    # ---- 3. SCHEMA GAPS ----
    print()
    print("=== SCHEMA GAPS: TOP-LEVEL KEYS ===")
    first = snapshots[labels[0]]
    last = snapshots[labels[-1]]
    print("Top-level keys (first):", sorted(first.keys()))
    print("Top-level keys (last):", sorted(last.keys()))
    r_first = first.get("registries") or {}
    r_last = last.get("registries") or {}
    print("registries keys (first):", sorted(r_first.keys()))
    print("registries keys (last):", sorted(r_last.keys()))
    cs_first = first.get("coverage_snapshot") or {}
    cs_last = last.get("coverage_snapshot") or {}
    print("coverage_snapshot keys (first):", list(cs_first.keys()))
    print("coverage_snapshot keys (last):", list(cs_last.keys()))

    # ---- 4. SOUND TONE LEAKAGE (Pure sound: primitive tones only) ----
    print()
    print("=== PURE SOUND: TONE LEAKAGE (non-primitive tones) ===")
    s_data = last.get("registries") or {}
    pure = s_data.get("pure_static") or {}
    discoveries = pure.get("discoveries") if isinstance(pure, dict) else {}
    sounds = discoveries.get("sound", []) if isinstance(discoveries, dict) else []
    expected_tones = {"low", "mid", "high", "silent", "neutral", "silence"}
    leakage_count = 0
    for s in sounds:
        key = s.get("key", "")
        parts = key.split("_")
        if len(parts) >= 2:
            tone = parts[1].lower()
            if tone not in expected_tones:
                leakage_count += 1
                print("  Non-primitive tone: key={}, name={}, strength={}".format(
                    key, s.get("name"), s.get("strength_pct")))
    if leakage_count == 0:
        print("  No tone leakage detected (all keys use primitive tones).")
    print("Total leakage entries:", leakage_count)

    # ---- 5. BLENDED MOTION: sample fields (depth_breakdown) ----
    print()
    print("=== BLENDED MOTION: SAMPLE ENTRY FIELDS ===")
    dyn = r_last.get("blended_dynamic") or {}
    motion = (dyn.get("discoveries") or {}).get("motion", []) if isinstance(dyn, dict) else []
    if motion:
        sample = motion[0]
        print("Sample motion entry keys:", list(sample.keys()))
        print("Has depth_breakdown:", bool(sample.get("depth_breakdown")))
    else:
        print("No motion entries.")

    # ---- 6. BLENDED LIGHTING: depth coverage ----
    print()
    print("=== BLENDED LIGHTING: DEPTH COVERAGE ===")
    lighting = (dyn.get("discoveries") or {}).get("lighting", []) if isinstance(dyn, dict) else []
    with_depth = [x for x in lighting if x.get("depth_breakdown")]
    without_depth = [x for x in lighting if not x.get("depth_breakdown")]
    print("Lighting with depth_breakdown: {} / {}".format(len(with_depth), len(lighting)))
    if with_depth:
        s = with_depth[0]
        print("Sample with depth: name={}, depth_breakdown={}".format(s.get("name"), s.get("depth_breakdown")))
    if without_depth:
        s = without_depth[0]
        print("Sample without depth: name={}, keys={}".format(s.get("name"), list(s.keys())))


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze registry export JSON(s) for growth, loop progress, and data quality.")
    ap.add_argument("paths", nargs="*", help="Paths to export JSON files (order = chronological).")
    ap.add_argument("--single", action="store_true", help="Treat paths as a single export (no growth delta).")
    args = ap.parse_args()

    root = Path(__file__).resolve().parent.parent
    export_dir = root / "json registry exports"

    if args.paths:
        paths = [Path(p).resolve() for p in args.paths]
    else:
        # Default: latest 3 motion-registries-*.json by modification time
        candidates = sorted(export_dir.glob("motion-registries-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        paths = candidates[:3]
        if not paths:
            print("No motion-registries-*.json found in", export_dir)
            return

    snapshots = load_snapshots(paths)
    run_analysis(snapshots)


if __name__ == "__main__":
    main()
