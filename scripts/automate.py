#!/usr/bin/env python3
"""
Continuous automation: generates prompts from our keyword data, creates jobs,
runs the procedural pipeline, uploads videos, and logs learning. Runs 24/7 to
build a knowledge base. No external models — 100% our data and algorithms.

Usage:
  python scripts/automate.py
  python scripts/automate.py --api-base https://motion.productions
  python scripts/automate.py --duration 6 --interval 120
  python scripts/automate.py --scale-duration   # gradually increase duration as knowledge grows

Run in background: screen -S motion python scripts/automate.py
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import json
import time

from src.config import load_config
from src.pipeline import generate_full_video
from src.procedural import ProceduralVideoGenerator
from src.automation import generate_procedural_prompt


from src.api_client import api_request


def load_state(state_path: Path, api_base: str | None = None) -> dict:
    state: dict = {"prompts_tried": [], "run_count": 0}
    if state_path.exists():
        with open(state_path, encoding="utf-8") as f:
            state = json.load(f)
    if api_base:
        try:
            data = api_request(api_base, "GET", "/api/knowledge/prompts?limit=500")
            cloud_prompts = set(data.get("prompts", []))
            state["prompts_tried"] = list(set(state.get("prompts_tried", [])) | cloud_prompts)[-500:]
        except Exception:
            pass
    return state


def save_state(state_path: Path, state: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def duration_for_run(run_count: int, base: float, scale: bool) -> float:
    """Increase duration as we accumulate knowledge."""
    if not scale:
        return base
    if run_count < 20:
        return base
    if run_count < 50:
        return min(base + 2, 10)
    if run_count < 100:
        return min(base + 4, 15)
    if run_count < 200:
        return min(base + 6, 20)
    return min(base + 8, 30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Continuous automation: prompt → generate → upload → learn."
    )
    parser.add_argument("--api-base", default="https://motion.productions")
    parser.add_argument("--duration", type=float, default=6, help="Base duration (seconds)")
    parser.add_argument("--interval", type=int, default=60, help="Seconds between runs")
    parser.add_argument("--scale-duration", action="store_true", help="Increase duration as runs accumulate")
    parser.add_argument("--state", type=Path, default=PROJECT_ROOT / "data" / "automation_state.json")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    args = parser.parse_args()

    config = load_config(args.config)
    state = load_state(args.state, args.api_base)
    prompts_tried = set(state.get("prompts_tried", [])[-500:])  # Keep last 500
    run_count = state.get("run_count", 0)

    out_cfg = config.get("output", {})
    generator = ProceduralVideoGenerator(
        width=out_cfg.get("width", 512),
        height=out_cfg.get("height", 512),
        fps=out_cfg.get("fps", 24),
    )
    out_dir = Path(config.get("output", {}).get("dir", "output"))

    while True:
        prompt = generate_procedural_prompt(avoid=prompts_tried)
        if not prompt:
            print("All combinations exhausted. Resetting avoid set.")
            prompts_tried.clear()

        prompt = generate_procedural_prompt(avoid=prompts_tried)
        if not prompt:
            print("No prompt generated.")
            if args.once:
                break
            time.sleep(args.interval)
            continue

        duration = duration_for_run(run_count, args.duration, args.scale_duration)

        try:
            job = api_request(args.api_base, "POST", "/api/jobs", data={
                "prompt": prompt,
                "duration_seconds": duration,
            })
        except Exception as e:
            print(f"API error creating job: {e}")
            if args.once:
                break
            time.sleep(args.interval)
            continue

        job_id = job["id"]
        out_path = out_dir / f"auto_{job_id}.mp4"

        print(f"[{run_count + 1}] {prompt[:50]}... ({duration}s)")

        try:
            path = generate_full_video(
                prompt,
                duration,
                generator=generator,
                output_path=out_path,
                config=config,
            )

            with open(path, "rb") as f:
                body = f.read()
            api_request(
                args.api_base, "POST", f"/api/jobs/{job_id}/upload",
                raw_body=body, content_type="video/mp4",
            )

            from src.analysis import analyze_video
            from src.interpretation import interpret_user_prompt
            from src.creation import build_spec_from_instruction

            instruction = interpret_user_prompt(prompt, default_duration=duration)
            spec = build_spec_from_instruction(instruction)
            analysis = analyze_video(path)
            api_request(args.api_base, "POST", "/api/learning", data={
                "job_id": job_id,
                "prompt": prompt,
                "spec": {
                    "palette_name": spec.palette_name,
                    "motion_type": spec.motion_type,
                    "intensity": spec.intensity,
                },
                "analysis": analysis.to_dict(),
            })

            print(f"  ✓ Uploaded + learned")

        except Exception as e:
            print(f"  ✗ Error: {e}")

        prompts_tried.add(prompt)
        run_count += 1
        state = {
            "prompts_tried": list(prompts_tried)[-500:],
            "run_count": run_count,
        }
        save_state(args.state, state)

        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
