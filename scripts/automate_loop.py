#!/usr/bin/env python3
"""
Self-feeding learning loop: each output triggers the next run.
70% exploit (good outcomes) / 30% explore (new combos).
State is persisted to the API (KV) so it survives restarts.

Usage:
  python scripts/automate_loop.py
  python scripts/automate_loop.py --api-base https://motion.productions
  python scripts/automate_loop.py --delay 30   # wait 30s between runs (view results in library)
  LOOP_DELAY_SECONDS=60 python scripts/automate_loop.py
  DEBUG=1 python scripts/automate_loop.py      # print full tracebacks on errors
"""
import json
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_EXPLOIT_RATIO = 0.70
DEFAULT_DELAY_SECONDS = 30

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


def pick_prompt(
    state: dict,
    exploit_ratio: float = DEFAULT_EXPLOIT_RATIO,
    knowledge: dict | None = None,
) -> str:
    """Exploit (good prompts) vs explore (new) based on exploit_ratio. Uses knowledge for dynamic exploration."""
    from src.automation import generate_procedural_prompt

    good = state.get("good_prompts", [])
    recent = set(state.get("recent_prompts", [])[-100:])

    if random.random() < exploit_ratio and good:
        return random.choice(good)
    return (
        generate_procedural_prompt(avoid=recent, knowledge=knowledge)
        or (random.choice(good) if good else generate_procedural_prompt(knowledge=knowledge))
    )


def _load_state(api_base: str) -> dict:
    """Load state from API (KV); falls back to baseline if unavailable."""
    try:
        data = api_request(api_base, "GET", "/api/loop/state")
        s = data.get("state", {})
        return {
            "run_count": int(s.get("run_count", 0)),
            "good_prompts": list(s.get("good_prompts", []))[-200:],
            "recent_prompts": list(s.get("recent_prompts", []))[-200:],
            "duration_base": float(s.get("duration_base", 6.0)),
        }
    except Exception:
        return baseline_state()


def _save_state(api_base: str, state: dict) -> None:
    """Persist state to API (KV) for cross-restart continuity."""
    try:
        api_request(api_base, "POST", "/api/loop/state", data={"state": state})
    except Exception:
        pass


def _load_loop_config(api_base: str) -> dict:
    """Load user-controlled loop config from API (controls Railway loop)."""
    try:
        data = api_request(api_base, "GET", "/api/loop/config")
        return {
            "enabled": data.get("enabled", True),
            "delay_seconds": int(data.get("delay_seconds", DEFAULT_DELAY_SECONDS)),
            "exploit_ratio": float(data.get("exploit_ratio", DEFAULT_EXPLOIT_RATIO)),
        }
    except Exception:
        return {"enabled": True, "delay_seconds": DEFAULT_DELAY_SECONDS, "exploit_ratio": DEFAULT_EXPLOIT_RATIO}


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
    parser.add_argument("--delay", type=float, default=None, help="Seconds to wait between runs (e.g. 30 to view results); env LOOP_DELAY_SECONDS")
    parser.add_argument("--config", type=Path, default=None)
    args = parser.parse_args()
    delay_seconds = args.delay if args.delay is not None else (float(os.environ.get("LOOP_DELAY_SECONDS", "0")) or 0)

    from src.config import load_config
    from src.pipeline import generate_full_video
    from src.procedural import ProceduralVideoGenerator
    from src.analysis import analyze_video
    from src.interpretation import interpret_user_prompt
    from src.creation import build_spec_from_instruction
    from src.knowledge.lookup import get_knowledge_for_creation

    config = load_config(args.config)
    config = {**config, "api_base": args.api_base}
    out_cfg = config.get("output", {})
    generator = ProceduralVideoGenerator(
        width=out_cfg.get("width", 512),
        height=out_cfg.get("height", 512),
        fps=out_cfg.get("fps", 24),
    )
    out_dir = Path(config.get("output", {}).get("dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    state = _load_state(args.api_base)
    print("Starting self-feeding loop (config from API; respects webapp controls)")
    print(f"State: run_count={state['run_count']}, good_prompts={len(state.get('good_prompts', []))}, recent={len(state.get('recent_prompts', []))}")
    print("Each output triggers the next run. Toggle loop in webapp to pause.\n")

    while True:
        loop_config = _load_loop_config(args.api_base)
        if not loop_config.get("enabled", True):
            print("Loop paused (disabled in webapp). Rechecking in 30s...")
            time.sleep(30)
            continue

        delay_seconds = loop_config.get("delay_seconds") or (args.delay if args.delay is not None else float(os.environ.get("LOOP_DELAY_SECONDS", "0")) or 0)
        override = os.environ.get("LOOP_EXPLOIT_RATIO_OVERRIDE")
        exploit_ratio = float(override) if override is not None and override != "" else loop_config.get("exploit_ratio", DEFAULT_EXPLOIT_RATIO)
        exploit_ratio = max(0.0, min(1.0, exploit_ratio))

        knowledge = {}
        try:
            knowledge = get_knowledge_for_creation(config)
        except Exception:
            pass

        prompt = pick_prompt(state, exploit_ratio=exploit_ratio, knowledge=knowledge)
        if not prompt:
            state["recent_prompts"] = []
            continue

        duration = duration_for_run(state["run_count"], args.duration)

        try:
            job = api_request(args.api_base, "POST", "/api/jobs", data={
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
            from src.knowledge import get_knowledge_for_creation
            spec = build_spec_from_instruction(instruction, knowledge=get_knowledge_for_creation(config))
            from src.knowledge import extract_from_video
            ext = extract_from_video(path)
            analysis_dict = ext.to_dict()

            # Growth: sync discoveries to D1/KV (the intended loop) — full extract + spec-based domains
            try:
                from src.knowledge.remote_sync import grow_and_sync_to_api
                grow_and_sync_to_api(analysis_dict, prompt=prompt, api_base=args.api_base, spec=spec)
            except Exception as e:
                print(f"  (discoveries sync: {e})")

            api_request(args.api_base, "POST", "/api/learning", data={
                "job_id": job_id,
                "prompt": prompt,
                "spec": {
                    "palette_name": spec.palette_name,
                    "motion_type": spec.motion_type,
                    "intensity": spec.intensity,
                },
                "analysis": analysis_dict,
            })

            if is_good_outcome(analysis_dict):  # analysis_dict has brightness_std_over_time, motion_level
                state["good_prompts"] = (state.get("good_prompts", []) + [prompt])[-200:]
                print("✓ good")
            else:
                print("✓")

            if delay_seconds > 0:
                print(f"  (waiting {delay_seconds:.0f}s before next run — check the library at motion.productions)")
                time.sleep(delay_seconds)

        except Exception as e:
            print(f"✗ {e}")
            if os.environ.get("DEBUG") == "1":
                import traceback
                traceback.print_exc()

        state["run_count"] += 1
        state["recent_prompts"] = (state.get("recent_prompts", []) + [prompt])[-200:]
        state["last_run_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
        state["last_prompt"] = (prompt or "")[:80] + ("…" if len(prompt or "") > 80 else "")
        state["last_job_id"] = job_id

        _save_state(args.api_base, state)


if __name__ == "__main__":
    run()
