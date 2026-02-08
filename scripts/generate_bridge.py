#!/usr/bin/env python3
"""
Generator bridge: fetches pending jobs from the API, runs the procedural pipeline,
uploads the result. Run this locally or on a server to process jobs created via the web app.

Usage:
  python scripts/generate_bridge.py
  python scripts/generate_bridge.py --api-base https://motion.productions
  python scripts/generate_bridge.py --once   # process one job and exit
  python scripts/generate_bridge.py --learn  # log runs for learning

Requires: the API must be deployed. Jobs stay "pending" until this script (or similar)
processes them and uploads the video.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import argparse
import time

from src.config import load_config
from src.pipeline import generate_full_video
from src.procedural import ProceduralVideoGenerator


from src.api_client import api_get, api_post, api_post_binary


def fetch_pending_jobs(api_base: str) -> list[dict]:
    out = api_get(api_base, "/api/jobs?status=pending")
    return out.get("jobs", [])


def log_to_api(
    api_base: str, job_id: str, prompt: str, spec: dict, analysis: dict
) -> None:
    api_post(api_base, "/api/learning", {"job_id": job_id, "prompt": prompt, "spec": spec, "analysis": analysis})


def upload_video(api_base: str, job_id: str, video_path: Path) -> None:
    with open(video_path, "rb") as f:
        body = f.read()
    api_post_binary(api_base, f"/api/jobs/{job_id}/upload", body, content_type="video/mp4", timeout=120)


def process_job(job: dict, api_base: str, config: dict, learn: bool) -> bool:
    job_id = job["id"]
    prompt = job["prompt"]
    duration = float(job.get("duration_seconds") or 6)
    print(f"Processing job {job_id}: {prompt[:50]}... ({duration}s)")

    out_cfg = config.get("output", {})
    generator = ProceduralVideoGenerator(
        width=out_cfg.get("width", 512),
        height=out_cfg.get("height", 512),
        fps=out_cfg.get("fps", 24),
    )
    out_dir = Path(config.get("output", {}).get("dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"job_{job_id}.mp4"

    try:
        path = generate_full_video(
            prompt,
            duration,
            generator=generator,
            output_path=out_path,
            config=config,
        )
        upload_video(api_base, job_id, path)
        print(f"  Uploaded: {path}")

        if learn:
            from src.analysis import analyze_video
            from src.interpretation import interpret_user_prompt
            from src.creation import build_spec_from_instruction
            from src.knowledge.remote_sync import grow_and_sync_to_api

            instruction = interpret_user_prompt(prompt, default_duration=duration)
            spec = build_spec_from_instruction(instruction)
            analysis = analyze_video(path)
            analysis_dict = analysis.to_dict()
            log_to_api(
                api_base,
                job_id,
                prompt,
                {"palette_name": spec.palette_name, "motion_type": spec.motion_type, "intensity": spec.intensity},
                analysis_dict,
            )
            # Sync discoveries (blends, colors, motion, etc.) to D1/KV
            try:
                sync_resp = grow_and_sync_to_api(analysis_dict, prompt=prompt, api_base=api_base)
                results = sync_resp.get("results", {})
                print(f"  Logged for learning (D1 + KV)")
                if results:
                    print(f"  Discoveries recorded: {results}")
            except Exception as e:
                print(f"  Learning run logged; discoveries sync failed: {e}")
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Process pending Motion jobs and upload videos.")
    parser.add_argument("--api-base", default="https://motion.productions", help="API base URL")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--learn", action="store_true", help="Log runs for learning")
    parser.add_argument("--interval", type=int, default=30, help="Poll interval (seconds)")
    parser.add_argument("--config", type=Path, default=None, help="Config YAML path")
    args = parser.parse_args()

    config = load_config(args.config)

    while True:
        jobs = fetch_pending_jobs(args.api_base)
        if not jobs:
            if args.once:
                print("No pending jobs. Exiting.")
                return
            print(f"No pending jobs. Polling again in {args.interval}s...")
            time.sleep(args.interval)
            continue

        job = jobs[0]
        process_job(job, args.api_base, config, args.learn)

        if args.once:
            return
        time.sleep(1)


if __name__ == "__main__":
    main()
