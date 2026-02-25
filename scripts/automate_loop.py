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
        "exploit_count": 0,
        "explore_count": 0,
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
    coverage: dict | None = None,
) -> tuple[str, bool]:
    """
    Exploit (good prompts) vs explore (new) based on exploit_ratio.
    Returns (prompt, is_exploit) so loop can track exploit_count / explore_count.
    """
    from src.automation import generate_procedural_prompt
    from src.automation.prompt_gen import generate_targeted_narrative_prompt

    good = state.get("good_prompts", [])
    recent = set(state.get("recent_prompts", [])[-150:])
    interpretation_prompts = (knowledge or {}).get("interpretation_prompts", [])

    if secure_random() < exploit_ratio and good:
        candidates = [p for p in good if p not in recent]
        chosen = secure_choice(candidates) if candidates else secure_choice(good)
        if chosen:
            return (chosen, True)
    # When exploring: 20% use targeted narrative prompt to fill missing genre/mood/themes (§2.4)
    if coverage and secure_random() < 0.20:
        targeted = generate_targeted_narrative_prompt(coverage, avoid=recent)
        if targeted:
            logger.info("Targeted narrative prompt (fill gaps): %s", targeted[:60] + ("..." if len(targeted) > 60 else ""))
            return (targeted, False)
    if interpretation_prompts and secure_random() < 0.45:
        candidates = [p for p in interpretation_prompts if isinstance(p, dict) and p.get("prompt") and p["prompt"] not in recent]
        if candidates:
            return (secure_choice(candidates)["prompt"], False)
    fallback = (
        generate_procedural_prompt(avoid=recent, knowledge=knowledge, coverage=coverage, instructive_ratio=0.65)
        or (secure_choice(good) if good else generate_procedural_prompt(knowledge=knowledge, coverage=coverage, instructive_ratio=0.65))
    )
    return (fallback or "", False)


def _load_coverage(api_base: str) -> dict | None:
    """Load registry coverage from API for completion targeting (§2.1). Returns None on failure."""
    try:
        return api_request_with_retry(api_base, "GET", "/api/registries/coverage", timeout=15)
    except Exception as e:
        logger.debug("GET /api/registries/coverage failed: %s — continuing without coverage", e)
        return None


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
            "exploit_count": int(s.get("exploit_count", 0)),
            "explore_count": int(s.get("explore_count", 0)),
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
    coverage: dict | None = None,
) -> float:
    """When discovery_rate_pct is low, repetition high, or registry coverage low, reduce exploit (§2.2)."""
    rate = progress.get("discovery_rate_pct")
    total_runs = progress.get("total_runs", 0)
    repetition = progress.get("repetition_score")

    # Coverage-based caps (§2.2): when registries are far from complete, bias toward exploration
    if coverage and total_runs >= 3:
        static_pct = coverage.get("static_colors_coverage_pct")
        narrative_min = coverage.get("narrative_min_coverage_pct")
        if static_pct is not None and static_pct < 10 and not override_active:
            base_ratio = min(base_ratio, 0.3)
        elif static_pct is not None and static_pct < 5 and override_active:
            base_ratio = min(base_ratio, 0.5)
        if narrative_min is not None and narrative_min < 50 and not override_active:
            base_ratio = min(base_ratio, 0.5)

    # High repetition → reduce exploit
    if repetition is not None and repetition > 0.35 and total_runs >= 5:
        cap = 0.7 if override_active else 0.5
        return min(base_ratio, cap)

    if total_runs < 5:
        return base_ratio

    if override_active:
        if rate is not None and rate < 10:
            return min(base_ratio, 0.80)
        if rate is not None and rate < 20:
            return min(base_ratio, 0.90)
        return base_ratio

    if rate is not None and rate < 10:
        return min(base_ratio, 0.4)
    return base_ratio


def _post_learning_with_retry(
    api_base: str,
    *,
    job_id: str,
    prompt: str,
    spec,
    analysis_dict: dict,
) -> None:
    """POST /api/learning with retries and one extra retry with longer backoff on failure (reduces 15% runs_with_learning gap)."""
    payload = {
        "job_id": job_id,
        "prompt": prompt,
        "spec": {
            "palette_name": getattr(spec, "palette_name", ""),
            "motion_type": getattr(spec, "motion_type", ""),
            "intensity": getattr(spec, "intensity", 1.0),
        },
        "analysis": analysis_dict,
    }
    try:
        api_request_with_retry(
            api_base,
            "POST",
            "/api/learning",
            data=payload,
            timeout=45,
            max_retries=5,
            backoff_seconds=2.0,
        )
    except (APIError, Exception) as e:
        # One extra retry with longer backoff (e.g. Worker cold start / timeout)
        logger.info("Retrying POST /api/learning after %s", e)
        time.sleep(4.0)
        api_request_with_retry(
            api_base,
            "POST",
            "/api/learning",
            data=payload,
            timeout=60,
            max_retries=2,
            backoff_seconds=4.0,
        )


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
        coverage = _load_coverage(args.api_base) if args.api_base else None
        prior_exploit = exploit_ratio
        exploit_ratio = _get_discovery_adjusted_exploit_ratio(exploit_ratio, progress, override_active, coverage=coverage)
        if coverage and exploit_ratio < prior_exploit:
            logger.info(
                "Exploit capped by coverage: %.2f -> %.2f (static_colors %.1f%%, narrative_min %.1f%%)",
                prior_exploit, exploit_ratio,
                coverage.get("static_colors_coverage_pct") or 0,
                coverage.get("narrative_min_coverage_pct") or 0,
            )
        # workflow_type for site: explorer | exploiter | main (prompt choice)
        workflow_type = os.environ.get("LOOP_WORKFLOW_TYPE") or ("explorer" if override == "0" else "exploiter" if override == "1" else "main")
        # extraction_focus: frame (per-frame / pure static only) | window (per-window blends only) | unset = all
        # Use LOOP_EXTRACTION_FOCUS (not LCXP_EXTRACTION_FOCUS). See RAILWAY_CONFIG.md §8 and docs/MISSION_AND_OPERATIONS.md.
        extraction_focus = (os.environ.get("LOOP_EXTRACTION_FOCUS") or "").strip().lower() or "all"
        if extraction_focus not in ("frame", "window", "all"):
            extraction_focus = "all"
        if extraction_focus == "all" and state.get("run_count", 0) == 0:
            logger.info(
                "LOOP_EXTRACTION_FOCUS is unset → Growth [all]. For split workers set LOOP_EXTRACTION_FOCUS=frame or =window (see RAILWAY_CONFIG.md §8)."
            )
        # static_focus: when frame extraction, grow only color | only sound | both (pure colors vs pure sounds workers)
        static_focus = (os.environ.get("LOOP_STATIC_FOCUS") or "").strip().lower() or "both"
        if static_focus not in ("color", "sound", "both"):
            static_focus = "both"

        knowledge = {}
        try:
            knowledge = get_knowledge_for_creation(config, api_base=args.api_base or None)
        except APIError as e:
            logger.warning("Knowledge fetch failed (path=%s, status=%s): %s — using empty knowledge", e.path, e.status_code, e)
        except Exception as e:
            logger.warning("Knowledge fetch failed (non-API): %s — using empty knowledge", e)

        if coverage is None and args.api_base:
            coverage = _load_coverage(args.api_base)
        prompt, is_exploit = pick_prompt(state, exploit_ratio=exploit_ratio, knowledge=knowledge, coverage=coverage)
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
            # Record interpretation first (so it's never skipped by later errors); visible in Railway logs
            if args.api_base:
                try:
                    payload = instruction.to_api_dict() if hasattr(instruction, "to_api_dict") else instruction.to_dict()
                    print("  [interpretation] posting...", flush=True)
                    api_request_with_retry(
                        args.api_base, "POST", "/api/interpretations",
                        data={"prompt": prompt, "instruction": payload, "source": "loop"},
                        timeout=30,
                        max_retries=5,
                        backoff_seconds=2.0,
                    )
                    print("  [interpretation] recorded", flush=True)
                except APIError as e:
                    print(f"  [interpretation] failed status={e.status_code}", flush=True)
                    logger.warning("POST /api/interpretations failed (status=%s): %s", e.status_code, e)
                except Exception as e:
                    print(f"  [interpretation] failed: {e}", flush=True)
                    logger.warning("Interpretation registry record failed: %s", e)
            from src.knowledge import get_knowledge_for_creation
            spec = build_spec_from_instruction(instruction, knowledge=get_knowledge_for_creation(config))
            # Learn from this prompt: extract (span, canonical, domain) so linguistic registry improves (slang, multi-sense)
            if args.api_base:
                try:
                    from src.interpretation.linguistic import extract_linguistic_mappings
                    from src.interpretation.linguistic_client import post_linguistic_growth
                    mappings = extract_linguistic_mappings(prompt, instruction)
                    if mappings:
                        post_linguistic_growth(args.api_base, mappings)
                except Exception as e:
                    logger.warning("Linguistic growth from loop run failed: %s", e)
            from src.knowledge import extract_from_video
            ext = extract_from_video(path)
            analysis_dict = ext.to_dict()

            # Extraction → growth → sync (required order for precision):
            # 1. grow_all_from_video extracts per-frame (static) and per-window (dynamic) from the same video.
            # 2. post_static_discoveries / post_dynamic_discoveries / post_narrative_discoveries send novel values to API.
            # 3. grow_and_sync_to_api posts whole-video aggregates (learned_colors, learned_blends).
            # 4. post_discoveries(api_base, {"job_id": job_id}) records the discovery run for diagnostics.
            # Creation uses get_knowledge_for_creation → build_spec with a merged pool (origin + learned) so gradient/camera/motion selection is randomized across primitives and discoveries.
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
                # §2.3: configurable max_frames; adaptive sample_every (1 for short clips → more discovery)
                learning_cfg = config.get("learning") or {}
                max_frames = learning_cfg.get("max_frames")
                sample_every = learning_cfg.get("sample_every", 2)
                if duration is not None and duration < 15 and sample_every > 1:
                    sample_every = 1  # maximize frames per run for short videos
                added, novel_for_sync = grow_all_from_video(
                    path,
                    prompt=prompt,
                    config=config,
                    max_frames=max_frames,
                    sample_every=sample_every,
                    window_seconds=1.0,
                    collect_novel_for_sync=bool(args.api_base),
                    spec=spec,
                    extraction_focus=extraction_focus,
                    static_focus=static_focus,
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
                        # Temporal blend (window→pure) may have added static colors; sync them
                        if novel_for_sync.get("static_colors"):
                            post_static_discoveries(
                                args.api_base,
                                novel_for_sync.get("static_colors", []),
                                novel_for_sync.get("static_sound") or [],
                                job_id=job_id,
                            )
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
                logger.warning("Missing discovery (job_id=%s): per-instance/narrative sync failed status=%s — %s", job_id, e.status_code, e)
            except Exception as e:
                logger.warning("Missing discovery (job_id=%s): growth/sync — %s", job_id, e)

            # Whole-video blends (learned_colors, learned_motion, learned_blends): only for window or all
            if extraction_focus in ("window", "all"):
                try:
                    from src.knowledge.remote_sync import grow_and_sync_to_api
                    grow_and_sync_to_api(analysis_dict, prompt=prompt, api_base=args.api_base, spec=spec, job_id=job_id)
                except APIError as e:
                    logger.warning("Missing discovery (job_id=%s): grow_and_sync failed status=%s — %s", job_id, e.status_code, e)
                    print(f"  (discoveries sync: {e})")
                except Exception as e:
                    logger.warning("Missing discovery (job_id=%s): %s", job_id, e)
                    print(f"  (discoveries sync: {e})")

            # Guaranteed discovery run recording — ensures diagnostics show ✓ disc even when
            # post_all_discoveries or grow_and_sync failed or threw before recording
            try:
                from src.knowledge.remote_sync import post_discoveries
                post_discoveries(args.api_base, {"job_id": job_id})
            except APIError as e:
                logger.warning("Missing discovery (job_id=%s): post_discoveries failed status=%s — %s", job_id, e.status_code, e)
            except Exception as e:
                logger.warning("Missing discovery (job_id=%s): post_discoveries — %s", job_id, e)

            try:
                # Explicit retries to reduce "missing learning" from transient 5xx/429/connection (audit §1.2)
                _post_learning_with_retry(
                    args.api_base,
                    job_id=job_id,
                    prompt=prompt,
                    spec=spec,
                    analysis_dict=analysis_dict,
                )
            except APIError as e:
                logger.warning("Missing learning (job_id=%s): POST /api/learning failed status=%s — %s", job_id, e.status_code, e)
                print(f"  (learning log: {e})")
            except Exception as e:
                logger.warning("Missing learning (job_id=%s): %s", job_id, e)
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
            if is_exploit:
                state["exploit_count"] = state.get("exploit_count", 0) + 1
            else:
                state["explore_count"] = state.get("explore_count", 0) + 1
            state["last_run_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
            state["last_prompt"] = (prompt or "")[:80] + ("…" if len(prompt or "") > 80 else "")
            state["last_job_id"] = job_id
            _save_state(args.api_base, state, state["run_count"])

    print("Loop stopped.")


if __name__ == "__main__":
    run()
