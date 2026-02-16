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
import logging
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.random_utils import secure_choice, secure_random

logger = logging.getLogger(__name__)

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


from src.api_client import APIError, api_request, api_request_with_retry


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
    """Exploit (good prompts) vs explore (new) based on exploit_ratio. Uses knowledge for dynamic exploration.
    When exploring, may pick from interpretation_prompts (user-prompt registry) so creation has more prompts."""
    from src.automation import generate_procedural_prompt

    good = state.get("good_prompts", [])
    recent = set(state.get("recent_prompts", [])[-150:])  # Wider window for variety when exploiting
    interpretation_prompts = (knowledge or {}).get("interpretation_prompts", [])

    if secure_random() < exploit_ratio and good:
        # Exclude recently used for variety even when exploiting
        candidates = [p for p in good if p not in recent]
        return secure_choice(candidates) if candidates else secure_choice(good)
    # When exploring: sometimes use a pre-interpreted user prompt from the interpretation registry
    if interpretation_prompts and secure_random() < 0.35:
        candidates = [p for p in interpretation_prompts if isinstance(p, dict) and p.get("prompt") and p["prompt"] not in recent]
        if candidates:
            return secure_choice(candidates)["prompt"]
    return (
        generate_procedural_prompt(avoid=recent, knowledge=knowledge)
        or (secure_choice(good) if good else generate_procedural_prompt(knowledge=knowledge))
    )


def _load_state(api_base: str) -> dict:
    """Load state from API (KV); falls back to baseline if unavailable. Retries on 5xx/connection."""
    try:
        data = api_request_with_retry(api_base, "GET", "/api/loop/state", timeout=15)
        s = data.get("state", {})
        return {
            "run_count": int(s.get("run_count", 0)),
            "good_prompts": list(s.get("good_prompts", []))[-200:],
            "recent_prompts": list(s.get("recent_prompts", []))[-200:],
            "duration_base": float(s.get("duration_base", 6.0)),
        }
    except APIError as e:
        logger.warning("GET /api/loop/state failed (status=%s, path=%s): %s — using baseline state", e.status_code, e.path, e)
        return baseline_state()


# KV allows 1 write/sec per key. Save only every N runs to stay under the limit.
STATE_SAVE_EVERY_N_RUNS = 5


def _save_state(api_base: str, state: dict, run_count: int) -> None:
    """Persist state to API (KV). Saves only every N runs. Retries on 429 with backoff."""
    if run_count % STATE_SAVE_EVERY_N_RUNS != 0:
        return
    try:
        # KV 1 write/sec — use extra retries for 429
        api_request(
            api_base, "POST", "/api/loop/state",
            data={"state": state},
            timeout=15,
            max_retries=5,
            backoff_seconds=2.0,
        )
    except APIError as e:
        detail = f" {e.body}" if getattr(e, "body", None) else ""
        logger.warning("POST /api/loop/state failed (status=%s, path=%s): %s%s — state not persisted", e.status_code, e.path, e, detail)


def _load_progress(api_base: str) -> dict:
    """Load loop progress (discovery rate, precision) for adaptive exploit ratio."""
    try:
        return api_request_with_retry(api_base, "GET", "/api/loop/progress?last=20", timeout=10)
    except APIError:
        return {}


def _get_discovery_adjusted_exploit_ratio(
    base_ratio: float,
    progress: dict,
    override_active: bool,
) -> float:
    """When discovery_rate_pct is low or repetition_score high, reduce exploit to boost exploration.
    Exploiter (override=1): soft cap when discovery < 20% so we inject exploration.
    Balanced: cap at 0.4 when discovery < 10%."""
    rate = progress.get("discovery_rate_pct")
    total_runs = progress.get("total_runs", 0)
    repetition = progress.get("repetition_score")  # 0–1; high = few entries dominate count

    # High repetition (e.g. top 20 entries hold >35% of total count) → reduce exploit
    if repetition is not None and repetition > 0.35 and total_runs >= 5:
        cap = 0.7 if override_active else 0.5
        return min(base_ratio, cap)

    if total_runs < 5:
        return base_ratio

    if override_active:
        # Exploiter: soft cap when discovery rate is low (inject 10–20% exploration)
        if rate is not None and rate < 10:
            return min(base_ratio, 0.80)
        if rate is not None and rate < 20:
            return min(base_ratio, 0.90)
        return base_ratio

    # Balanced: stronger cap when discovery is very low
    if rate is not None and rate < 10:
        return min(base_ratio, 0.4)
    return base_ratio


def _load_loop_config(api_base: str) -> dict:
    """Load user-controlled loop config from API (controls Railway loop). Retries on 5xx/connection; logs on failure."""
    try:
        data = api_request_with_retry(api_base, "GET", "/api/loop/config", timeout=15)
        return {
            "enabled": data.get("enabled", True),
            "delay_seconds": int(data.get("delay_seconds", DEFAULT_DELAY_SECONDS)),
            "exploit_ratio": float(data.get("exploit_ratio", DEFAULT_EXPLOIT_RATIO)),
            "duration_seconds": data.get("duration_seconds"),
        }
    except APIError as e:
        logger.warning("GET /api/loop/config failed (status=%s, path=%s): %s — using defaults", e.status_code, e.path, e)
        return {"enabled": True, "delay_seconds": DEFAULT_DELAY_SECONDS, "exploit_ratio": DEFAULT_EXPLOIT_RATIO, "duration_seconds": None}


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

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Self-feeding learning loop.")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("API_BASE", "https://motion.productions"),
    )
    parser.add_argument("--duration", type=float, default=6, help="Base duration (s). Use 1 for learning-optimized (more videos, one window each).")
    parser.add_argument("--delay", type=float, default=None, help="Seconds to wait between runs (e.g. 30 to view results); env LOOP_DELAY_SECONDS")
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--health-port", type=int, default=None, help="Port for health HTTP server (0=disabled); env HEALTH_PORT")
    args = parser.parse_args()

    from src.workflow_utils import setup_graceful_shutdown, start_health_server, request_shutdown, log_structured
    setup_graceful_shutdown()
    health_port = args.health_port if args.health_port is not None else int(os.environ.get("HEALTH_PORT", "0"))
    if health_port > 0:
        start_health_server(health_port)
        log_structured("info", msg="Health server started", port=health_port)
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
        if request_shutdown():
            log_structured("info", msg="Shutdown requested, exiting")
            break

        loop_config = _load_loop_config(args.api_base)
        if not loop_config.get("enabled", True):
            print("Loop paused (disabled in webapp). Rechecking in 30s...")
            time.sleep(30)
            continue

        delay_seconds = loop_config.get("delay_seconds") or (args.delay if args.delay is not None else float(os.environ.get("LOOP_DELAY_SECONDS", "0")) or 0)
        override = os.environ.get("LOOP_EXPLOIT_RATIO_OVERRIDE")
        override_active = override is not None and override != ""
        exploit_ratio = float(override) if override_active else loop_config.get("exploit_ratio", DEFAULT_EXPLOIT_RATIO)
        exploit_ratio = max(0.0, min(1.0, exploit_ratio))
        progress = _load_progress(args.api_base)
        exploit_ratio = _get_discovery_adjusted_exploit_ratio(exploit_ratio, progress, override_active)
        # workflow_type for site: explorer | exploiter | main (prompt choice)
        workflow_type = os.environ.get("LOOP_WORKFLOW_TYPE") or ("explorer" if override == "0" else "exploiter" if override == "1" else "main")
        # extraction_focus: frame (per-frame / pure static only) | window (per-window blends only) | unset = all
        extraction_focus = (os.environ.get("LOOP_EXTRACTION_FOCUS") or "").strip().lower() or "all"
        if extraction_focus not in ("frame", "window", "all"):
            extraction_focus = "all"

        knowledge = {}
        try:
            knowledge = get_knowledge_for_creation(config)
        except APIError as e:
            logger.warning("Knowledge fetch failed (path=%s, status=%s): %s — using empty knowledge", e.path, e.status_code, e)
        except Exception as e:
            logger.warning("Knowledge fetch failed (non-API): %s — using empty knowledge", e)

        prompt = pick_prompt(state, exploit_ratio=exploit_ratio, knowledge=knowledge)
        if not prompt:
            state["recent_prompts"] = []
            continue

        # Duration: API loop config (from UI) overrides local config and CLI
        api_duration = loop_config.get("duration_seconds")
        if api_duration is not None and api_duration > 0:
            duration = float(api_duration)
        else:
            learning_duration = (config.get("learning") or {}).get("duration_seconds")
            if learning_duration is not None and learning_duration > 0:
                duration = float(learning_duration)
            else:
                duration = duration_for_run(state["run_count"], args.duration)

        try:
            job = api_request_with_retry(
                args.api_base, "POST", "/api/jobs",
                data={"prompt": prompt, "duration_seconds": duration, "workflow_type": workflow_type},
                timeout=30,
            )
        except APIError as e:
            logger.warning("POST /api/jobs failed (status=%s, path=%s): %s", e.status_code, e.path, e)
            print(f"API error: {e}")
            continue

        job_id = job.get("id")
        if not job_id:
            logger.warning("POST /api/jobs returned no id: %s — skipping run", job)
            print("API error: job created but no id returned")
            continue

        out_path = out_dir / f"loop_{job_id}.mp4"
        log_structured("info", phase="run", run=state["run_count"] + 1, job_id=job_id, prompt_preview=prompt[:50], duration=duration)
        print(f"[{state['run_count'] + 1}] {prompt[:50]}... ({duration}s) ", end="", flush=True)

        run_succeeded = False
        try:
            run_seed = (state["run_count"] + 1) * 7919 + (hash(job_id) % 1_000_000)
            path = generate_full_video(
                prompt,
                duration,
                generator=generator,
                output_path=out_path,
                seed=run_seed,
                config=config,
            )

            with open(path, "rb") as f:
                body = f.read()
            api_request_with_retry(
                args.api_base, "POST", f"/api/jobs/{job_id}/upload",
                raw_body=body, content_type="video/mp4",
                timeout=120,
            )
            run_succeeded = True

            instruction = interpret_user_prompt(prompt, default_duration=duration)
            from src.knowledge import get_knowledge_for_creation
            spec = build_spec_from_instruction(instruction, knowledge=get_knowledge_for_creation(config))
            from src.knowledge import extract_from_video
            ext = extract_from_video(path)
            analysis_dict = ext.to_dict()

            # Growth + sync: gated by extraction_focus (frame | window | all)
            try:
                from src.knowledge.growth_per_instance import grow_all_from_video
                from src.knowledge.narrative_registry import grow_narrative_from_spec
                from src.knowledge.remote_sync import (
                    grow_and_sync_to_api,
                    post_all_discoveries,
                    post_static_discoveries,
                    post_dynamic_discoveries,
                    post_narrative_discoveries,
                    growth_metrics,
                )
                added, novel_for_sync = grow_all_from_video(
                    path,
                    prompt=prompt,
                    config=config,
                    max_frames=None,
                    sample_every=2,
                    window_seconds=1.0,
                    collect_novel_for_sync=bool(args.api_base),
                    spec=spec,
                    extraction_focus=extraction_focus,
                )
                if any(added.values()):
                    metrics = growth_metrics(added)
                    logger.info("Growth [%s]: total=%s static=%s dynamic=%s aspects=%s", extraction_focus, metrics["total_added"], metrics["static_added"], metrics["dynamic_added"], metrics["by_aspect"])
                narrative_novel = {}
                if extraction_focus in ("window", "all"):
                    narrative_added, narrative_novel = grow_narrative_from_spec(
                        spec, prompt=prompt, config=config, instruction=instruction, collect_novel_for_sync=True
                    )
                if args.api_base:
                    if extraction_focus == "frame":
                        post_static_discoveries(
                            args.api_base,
                            novel_for_sync.get("static_colors", []),
                            novel_for_sync.get("static_sound") or [],
                            job_id=job_id,
                        )
                    elif extraction_focus == "window":
                        post_dynamic_discoveries(args.api_base, novel_for_sync, job_id=job_id)
                        if narrative_novel and any(narrative_novel.values()):
                            post_narrative_discoveries(args.api_base, narrative_novel, job_id=job_id)
                    else:
                        post_all_discoveries(
                            args.api_base,
                            novel_for_sync.get("static_colors", []),
                            novel_for_sync.get("static_sound") or [],
                            novel_for_sync,
                            narrative_novel,
                            job_id=job_id,
                        )
            except APIError as e:
                logger.warning("Per-instance or narrative sync failed (status=%s): %s", e.status_code, e)
            except Exception as e:
                logger.warning("Per-instance or narrative growth/sync: %s", e)

            # Whole-video blends (learned_colors, learned_motion, learned_blends): only for window or all
            if extraction_focus in ("window", "all"):
                try:
                    from src.knowledge.remote_sync import grow_and_sync_to_api
                    grow_and_sync_to_api(analysis_dict, prompt=prompt, api_base=args.api_base, spec=spec, job_id=job_id)
                except APIError as e:
                    logger.warning("POST /api/knowledge/discoveries failed (status=%s): %s", e.status_code, e)
                    print(f"  (discoveries sync: {e})")
                except Exception as e:
                    print(f"  (discoveries sync: {e})")

            # Guaranteed discovery run recording — ensures diagnostics show ✓ disc even when
            # post_all_discoveries or grow_and_sync failed or threw before recording
            try:
                from src.knowledge.remote_sync import post_discoveries
                post_discoveries(args.api_base, {"job_id": job_id})
            except Exception:
                pass

            try:
                api_request_with_retry(args.api_base, "POST", "/api/learning", data={
                    "job_id": job_id,
                    "prompt": prompt,
                    "spec": {
                        "palette_name": spec.palette_name,
                        "motion_type": spec.motion_type,
                        "intensity": spec.intensity,
                    },
                    "analysis": analysis_dict,
                }, timeout=45)
            except APIError as e:
                logger.warning("POST /api/learning failed (status=%s, path=%s): %s — run still counts as success", e.status_code, e.path, e)
                print(f"  (learning log: {e})")

            if is_good_outcome(analysis_dict):
                state["good_prompts"] = (state.get("good_prompts", []) + [prompt])[-200:]
                print("✓ good")
            else:
                print("✓")

            if delay_seconds > 0:
                print(f"  (waiting {delay_seconds:.0f}s before next run — check the library at motion.productions)")
                time.sleep(delay_seconds)

        except APIError as e:
            logger.warning("API call failed (status=%s, path=%s): %s", e.status_code, e.path, e)
            print(f"✗ {e}")
        except Exception as e:
            print(f"✗ {e}")
            if os.environ.get("DEBUG") == "1":
                import traceback
                traceback.print_exc()

        if run_succeeded:
            state["run_count"] += 1
            state["recent_prompts"] = (state.get("recent_prompts", []) + [prompt])[-200:]
            state["last_run_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
            state["last_prompt"] = (prompt or "")[:80] + ("…" if len(prompt or "") > 80 else "")
            state["last_job_id"] = job_id
            _save_state(args.api_base, state, state["run_count"])

    print("Loop stopped.")


if __name__ == "__main__":
    run()
