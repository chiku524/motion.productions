#!/usr/bin/env python3
"""
Self-feeding learning loop: each output triggers the next run.
70% exploit (good outcomes) / 30% explore (new combos). State resets on restart.
Run on Railway or Render as a background worker.

Usage:
  python scripts/automate_loop.py
  python scripts/automate_loop.py --api-base https://motion.productions
"""
import json
import random
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

EXPLOIT_RATIO = 0.70
EXPLORE_RATIO = 0.30

# "Good" outcome thresholds (from analysis)
CONSISTENCY_MAX = 20.0  # brightness_std_over_time lower = more consistent
MOTION_MIN = 1.0
MOTION_MAX = 25.0


def baseline_state() -> dict:
    """Fresh state on each restart."""
    return {
        "run_count": 0,
        "good_prompts": [],
        "recent_prompts": [],
        "duration_base": 6.0,
    }


from src.api_client import api_request


def is_good_outcome(analysis: dict) -> bool:
    """True if output meets quality thresholds."""
    consistency = analysis.get("brightness_std_over_time", 999)
    motion = analysis.get("motion_level", 0)
    return (
        consistency <= CONSISTENCY_MAX
        and MOTION_MIN <= motion <= MOTION_MAX
    )


def pick_prompt(state: dict) -> str:
    """70% exploit (good prompts), 30% explore (new)."""
    from src.automation import generate_procedural_prompt

    good = state.get("good_prompts", [])
    recent = set(state.get("recent_prompts", [])[-100:])

    if random.random() < EXPLOIT_RATIO and good:
        return random.choice(good)
    return generate_procedural_prompt(avoid=recent) or random.choice(good) if good else generate_procedural_prompt()


def duration_for_run(run_count: int, base: float) -> float:
    """Scale duration as session progresses."""
    if run_count < 20:
        return base
    if run_count < 50:
        return min(base + 2, 10)
    if run_count < 100:
        return min(base + 4, 15)
    if run_count < 200:
        return min(base + 6, 20)
    return min(base + 8, 30)


def run() -> None:
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Self-feeding learning loop.")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("API_BASE", "https://motion.productions"),
    )
    parser.add_argument("--duration", type=float, default=6)
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()

    from src.config import load_config
    from src.pipeline import generate_full_video
    from src.procedural import ProceduralVideoGenerator
    from src.analysis import analyze_video
    from src.interpretation import interpret_user_prompt
    from src.creation import build_spec_from_instruction

    config = load_config(args.config)
    out_cfg = config.get("output", {})
    generator = ProceduralVideoGenerator(
        width=out_cfg.get("width", 512),
        height=out_cfg.get("height", 512),
        fps=out_cfg.get("fps", 24),
    )
    out_dir = Path(config.get("output", {}).get("dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    state = baseline_state()
    print("Starting self-feeding loop (70% exploit / 30% explore, baseline state)")
    print("Each output triggers the next run. Restart = reset to baseline.\n")

    while True:
        prompt = pick_prompt(state)
        if not prompt:
            state["recent_prompts"] = []
            continue

        duration = duration_for_run(state["run_count"], args.duration)

        try:
            job = api_request(args.api_base, "POST", "/api/jobs", {
                "prompt": prompt,
                "duration_seconds": duration,
            })
        except Exception as e:
            print(f"API error: {e}")
            continue

        job_id = job["id"]
        out_path = out_dir / f"loop_{job_id}.mp4"

        print(f"[{state['run_count'] + 1}] {prompt[:50]}... ({duration}s) ", end="", flush=True)

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

            instruction = interpret_user_prompt(prompt, default_duration=duration)
            spec = build_spec_from_instruction(instruction)
            analysis = analyze_video(path)
            analysis_dict = analysis.to_dict()

            api_request(args.api_base, "POST", "/api/learning", {
                "job_id": job_id,
                "prompt": prompt,
                "spec": {
                    "palette_name": spec.palette_name,
                    "motion_type": spec.motion_type,
                    "intensity": spec.intensity,
                },
                "analysis": analysis_dict,
            })

            if is_good_outcome(analysis_dict):
                state["good_prompts"] = (state.get("good_prompts", []) + [prompt])[-200:]
                print("✓ good")
            else:
                print("✓")

        except Exception as e:
            print(f"✗ {e}")

        state["run_count"] += 1
        state["recent_prompts"] = (state.get("recent_prompts", []) + [prompt])[-200:]


if __name__ == "__main__":
    run()
