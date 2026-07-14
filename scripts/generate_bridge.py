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
import argparse
import os
import time
from pathlib import Path

from src.api_client import api_get, api_post, api_post_binary, api_request_with_retry
from src.config import load_config
from src.pipeline import generate_full_video
from src.procedural import ProceduralVideoGenerator


def fetch_pending_jobs(api_base: str) -> list[dict]:
    out = api_get(api_base, "/api/jobs?status=pending&limit=5")
    return out.get("jobs", [])


def _learning_spec_payload(spec) -> dict:
    """Registry-relevant fields from the rendered SceneSpec (not a re-built copy)."""
    return {
        "palette_name": getattr(spec, "palette_name", ""),
        "motion_type": getattr(spec, "motion_type", ""),
        "intensity": getattr(spec, "intensity", 1.0),
        "gradient_type": getattr(spec, "gradient_type", None),
        "camera_motion": getattr(spec, "camera_motion", None),
        "audio_tempo": getattr(spec, "audio_tempo", None),
        "audio_mood": getattr(spec, "audio_mood", None),
        "audio_presence": getattr(spec, "audio_presence", None),
        "genre": getattr(spec, "genre", None),
        "mood": getattr(spec, "mood", None),
        "style": getattr(spec, "style", None),
    }


def log_to_api(
    api_base: str, job_id: str, prompt: str, spec, analysis: dict
) -> None:
    api_post(
        api_base,
        "/api/learning",
        {"job_id": job_id, "prompt": prompt, "spec": _learning_spec_payload(spec), "analysis": analysis},
    )


def upload_video(api_base: str, job_id: str, video_path: Path) -> None:
    with open(video_path, "rb") as f:
        body = f.read()
    api_post_binary(api_base, f"/api/jobs/{job_id}/upload", body, content_type="video/mp4", timeout=120)


def process_job(job: dict, api_base: str, config: dict, learn: bool) -> bool:
    job_id = job["id"]
    prompt = job["prompt"]
    duration = float(job.get("duration_seconds") or 6)
    print(f"Processing job {job_id}: {prompt[:50]}... ({duration}s)")

    config = {**config, "api_base": api_base}
    generator = ProceduralVideoGenerator(config=config)
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
            from src.knowledge import get_knowledge_for_creation
            from src.knowledge.remote_sync import (
                grow_and_sync_to_api,
                post_all_discoveries,
                post_static_discoveries,
                post_dynamic_discoveries,
                post_narrative_discoveries,
                post_discoveries,
                growth_metrics,
            )
            from src.knowledge.growth_per_instance import grow_all_from_video
            from src.knowledge.narrative_registry import grow_narrative_from_spec

            # Prefer the spec/instruction that actually drove the render
            instruction = getattr(generator, "_last_instruction", None)
            spec = getattr(generator, "_last_spec", None)
            if instruction is None or spec is None:
                linguistic_registry = None
                try:
                    from src.interpretation.linguistic_client import fetch_linguistic_registry
                    linguistic_registry = fetch_linguistic_registry(api_base.rstrip("/"))
                except Exception:
                    linguistic_registry = None
                if instruction is None:
                    instruction = interpret_user_prompt(
                        prompt,
                        default_duration=duration,
                        linguistic_registry=linguistic_registry,
                    )
                if spec is None:
                    knowledge = get_knowledge_for_creation(config, api_base=api_base)
                    spec = build_spec_from_instruction(instruction, knowledge=knowledge)

            # Interpretation + linguistics registries (same as automate_loop)
            try:
                payload = (
                    instruction.to_api_dict()
                    if hasattr(instruction, "to_api_dict")
                    else instruction.to_dict()
                )
                print("  [interpretation] posting...", flush=True)
                api_request_with_retry(
                    api_base,
                    "POST",
                    "/api/interpretations",
                    data={"prompt": prompt, "instruction": payload, "source": "bridge"},
                    timeout=30,
                    max_retries=5,
                    backoff_seconds=2.0,
                )
                print("  [interpretation] recorded", flush=True)
            except Exception as e:
                print(f"  [interpretation] failed: {e}", flush=True)
            try:
                from src.interpretation.linguistic import extract_linguistic_mappings
                from src.interpretation.linguistic_client import post_linguistic_growth
                mappings = extract_linguistic_mappings(prompt, instruction)
                if mappings:
                    post_linguistic_growth(api_base, mappings)
            except Exception as e:
                print(f"  [linguistic] growth skipped: {e}")

            analysis = analyze_video(path)
            analysis_dict = analysis.to_dict()
            log_to_api(api_base, job_id, prompt, spec, analysis_dict)

            extraction_focus = (os.environ.get("LOOP_EXTRACTION_FOCUS") or "all").strip().lower()
            if extraction_focus not in ("frame", "window", "all"):
                extraction_focus = "all"

            try:
                learning_cfg = config.get("learning") or {}
                max_frames = learning_cfg.get("max_frames")
                sample_every = learning_cfg.get("sample_every", 2)
                if duration < 15 and sample_every > 1:
                    sample_every = 1
                added, novel_for_sync = grow_all_from_video(
                    path,
                    prompt=prompt,
                    config=config,
                    max_frames=max_frames,
                    sample_every=sample_every,
                    window_seconds=1.0,
                    collect_novel_for_sync=True,
                    spec=spec,
                    extraction_focus=extraction_focus,
                )
                if any(added.values()):
                    metrics = growth_metrics(added)
                    print(
                        f"  Growth [{extraction_focus}]: total={metrics['total_added']} "
                        f"static={metrics['static_added']} dynamic={metrics['dynamic_added']}"
                    )

                narrative_novel = {}
                if extraction_focus in ("window", "all"):
                    narrative_added, narrative_novel = grow_narrative_from_spec(
                        spec,
                        prompt=prompt,
                        config=config,
                        instruction=instruction,
                        collect_novel_for_sync=True,
                    )
                    if any(narrative_added.values()):
                        print(f"  Narrative registry: {sum(narrative_added.values())} new — {narrative_added}")

                if extraction_focus == "frame":
                    post_static_discoveries(
                        api_base,
                        novel_for_sync.get("static_colors", []),
                        novel_for_sync.get("static_sound") or [],
                        job_id=job_id,
                    )
                elif extraction_focus == "window":
                    post_dynamic_discoveries(api_base, novel_for_sync, job_id=job_id)
                    if narrative_novel and any(narrative_novel.values()):
                        post_narrative_discoveries(api_base, narrative_novel, job_id=job_id)
                    if novel_for_sync.get("static_colors"):
                        post_static_discoveries(
                            api_base,
                            novel_for_sync.get("static_colors", []),
                            novel_for_sync.get("static_sound") or [],
                            job_id=job_id,
                        )
                else:
                    post_all_discoveries(
                        api_base,
                        novel_for_sync.get("static_colors", []),
                        novel_for_sync.get("static_sound") or [],
                        novel_for_sync,
                        narrative_novel,
                        job_id=job_id,
                    )
                print("  Discoveries synced to D1")
            except Exception as e:
                print(f"  Per-instance growth failed: {e}")

            if extraction_focus in ("window", "all"):
                try:
                    sync_resp = grow_and_sync_to_api(
                        analysis_dict, prompt=prompt, api_base=api_base, spec=spec, job_id=job_id
                    )
                    print("  Logged for learning (D1 + KV)")
                    if sync_resp.get("results"):
                        print(f"  Discoveries recorded: {sync_resp.get('results')}")
                except Exception as e:
                    print(f"  Learning run logged; discoveries sync failed: {e}")

            try:
                post_discoveries(api_base, {"job_id": job_id})
            except Exception:
                pass
        return True
    except Exception as e:
        print(f"  Error: {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Process pending Motion jobs and upload videos.")
    parser.add_argument("--api-base", default=os.environ.get("API_BASE", "https://motion.productions"), help="API base URL")
    parser.add_argument("--once", action="store_true", help="Process one job and exit")
    parser.add_argument("--learn", action="store_true", help="Log runs for learning")
    parser.add_argument("--interval", type=int, default=int(os.environ.get("BRIDGE_INTERVAL_SECONDS", "30")), help="Poll interval (seconds)")
    parser.add_argument("--config", type=Path, default=None, help="Config YAML path")
    parser.add_argument("--health-port", type=int, default=None, help="Health HTTP port; env HEALTH_PORT")
    args = parser.parse_args()

    from src.workflow_utils import setup_graceful_shutdown, start_health_server, request_shutdown

    setup_graceful_shutdown()
    health_port = args.health_port if args.health_port is not None else int(os.environ.get("HEALTH_PORT", "0"))
    if health_port:
        start_health_server(health_port)

    config = load_config(args.config)

    while True:
        if request_shutdown():
            print("Shutdown requested. Exiting.")
            return
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
