#!/usr/bin/env python3
"""
Interpretation-only worker: no create/render. Polls queue, interprets user prompts,
stores results in D1 via API. Generates diverse prompts (slang, dialect), interprets,
extracts linguistic mappings, and grows the linguistic registry for "anything and everything".

Usage:
  python scripts/interpret_loop.py
  python scripts/interpret_loop.py --api-base https://motion.productions
  python scripts/interpret_loop.py --delay 15
  INTERPRET_DELAY_SECONDS=20 python scripts/interpret_loop.py
"""
import argparse
import logging
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

DEFAULT_DELAY_SECONDS = 10
DEFAULT_QUEUE_LIMIT = 20


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Interpretation-only loop (no create/render).")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("API_BASE", "https://motion.productions"),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds between poll cycles (env INTERPRET_DELAY_SECONDS)",
    )
    parser.add_argument(
        "--queue-limit",
        type=int,
        default=DEFAULT_QUEUE_LIMIT,
        help="Max items to process per cycle",
    )
    parser.add_argument(
        "--no-backfill",
        action="store_true",
        help="Disable backfill of prompts from jobs table",
    )
    parser.add_argument(
        "--no-generate",
        action="store_true",
        help="Disable prompt generation and linguistic growth",
    )
    parser.add_argument("--health-port", type=int, default=None, help="Port for health HTTP server (0=disabled); env HEALTH_PORT")
    args = parser.parse_args()
    delay = args.delay if args.delay is not None else float(os.environ.get("INTERPRET_DELAY_SECONDS", DEFAULT_DELAY_SECONDS))

    from src.api_client import APIError, api_request_with_retry
    from src.interpretation import interpret_user_prompt
    from src.interpretation.prompt_gen import generate_interpretation_prompt_batch
    from src.interpretation.linguistic import extract_linguistic_mappings
    from src.interpretation.linguistic_client import fetch_linguistic_registry, post_linguistic_growth
    from src.workflow_utils import setup_graceful_shutdown, start_health_server, request_shutdown

    setup_graceful_shutdown()
    health_port = args.health_port if args.health_port is not None else int(os.environ.get("HEALTH_PORT", "0"))
    if health_port > 0:
        start_health_server(health_port)

    api_base = args.api_base.rstrip("/")
    print("Interpretation worker started (no create/render)")
    print(f"API: {api_base}")
    print(f"Delay: {delay}s between cycles. Backfill: {'off' if args.no_backfill else 'on'}. Generate: {'off' if args.no_generate else 'on'}\n")

    cycle = 0
    while True:
        if request_shutdown():
            print("Shutdown requested, exiting")
            break
        cycle += 1
        try:
            # 1) Process queue: GET pending → interpret → PATCH result
            try:
                queue_path = f"/api/interpret/queue?limit={args.queue_limit}"
                data = api_request_with_retry(
                    api_base, "GET", queue_path,
                    timeout=15,
                )
            except APIError as e:
                logger.warning("GET /api/interpret/queue failed (status=%s): %s", e.status_code, e)
                time.sleep(delay)
                continue

            items = data.get("items", [])
            linguistic_registry = fetch_linguistic_registry(api_base) if api_base else {}
            for item in items:
                uid = item.get("id")
                prompt = item.get("prompt", "").strip()
                if not uid or not prompt:
                    continue
                try:
                    instruction = interpret_user_prompt(
                        prompt,
                        default_duration=6.0,
                        linguistic_registry=linguistic_registry or None,
                    )
                    payload = instruction.to_api_dict() if hasattr(instruction, "to_api_dict") else instruction.to_dict()
                    api_request_with_retry(
                        api_base, "PATCH", f"/api/interpret/{uid}",
                        data={"instruction": payload},
                        timeout=15,
                    )
                    print(f"[{cycle}] interpreted: {prompt[:50]}…")
                except APIError as e:
                    logger.warning("PATCH /api/interpret/%s failed: %s", uid, e)
                except Exception as e:
                    logger.warning("Interpret failed for %s: %s", prompt[:40], e)

            # 2) Backfill: batch fetch → interpret all → batch POST (reduces round-trips)
            if not args.no_backfill and api_base:
                try:
                    backfill = api_request_with_retry(
                        api_base, "GET", "/api/interpret/backfill-prompts?limit=50",
                        timeout=15,
                    )
                    prompts = [p.strip() for p in backfill.get("prompts", []) if p and isinstance(p, str)]
                    if prompts:
                        linguistic_registry = fetch_linguistic_registry(api_base)
                        batch: list[dict] = []
                        for prompt in prompts:
                            try:
                                instruction = interpret_user_prompt(
                                    prompt,
                                    default_duration=6.0,
                                    linguistic_registry=linguistic_registry or None,
                                )
                                payload = instruction.to_api_dict() if hasattr(instruction, "to_api_dict") else instruction.to_dict()
                                batch.append({"prompt": prompt, "instruction": payload, "source": "backfill"})
                            except Exception as e:
                                logger.warning("Backfill interpret failed for %s: %s", prompt[:40], e)
                        if batch:
                            try:
                                resp = api_request_with_retry(
                                    api_base, "POST", "/api/interpretations/batch",
                                    data={"items": batch},
                                    timeout=30,
                                )
                                n = resp.get("inserted", 0)
                                if n:
                                    print(f"[{cycle}] backfill: {n} interpreted")
                            except APIError as e:
                                logger.warning("POST /api/interpretations/batch failed: %s — falling back to single POSTs", e)
                                for it in batch:
                                    try:
                                        api_request_with_retry(
                                            api_base, "POST", "/api/interpretations",
                                            data=it, timeout=15,
                                        )
                                        print(f"[{cycle}] backfill: {it['prompt'][:50]}…")
                                    except APIError:
                                        pass
                except APIError as e:
                    logger.warning("GET /api/interpret/backfill-prompts failed: %s", e)

            # 3) Generate & learn: generate prompts, interpret, extract, grow linguistic registry
            if not args.no_generate and api_base:
                try:
                    linguistic_registry = fetch_linguistic_registry(api_base)
                    generated = generate_interpretation_prompt_batch(5, avoid=set())
                    all_extracted: list[dict] = []
                    for prompt in generated:
                        try:
                            instruction = interpret_user_prompt(
                                prompt,
                                default_duration=6.0,
                                linguistic_registry=linguistic_registry,
                            )
                            payload = instruction.to_api_dict() if hasattr(instruction, "to_api_dict") else instruction.to_dict()
                            api_request_with_retry(
                                api_base, "POST", "/api/interpretations",
                                data={"prompt": prompt, "instruction": payload, "source": "generate"},
                                timeout=15,
                            )
                            extracted = extract_linguistic_mappings(prompt, instruction)
                            for e in extracted:
                                e["variant_type"] = e.get("variant_type", "synonym")
                            all_extracted.extend(extracted)
                            print(f"[{cycle}] generated: {prompt[:50]}…")
                        except Exception as e:
                            logger.warning("Generate/interpret failed for %s: %s", prompt[:40], e)
                    if all_extracted:
                        result = post_linguistic_growth(api_base, all_extracted)
                        if result.get("inserted", 0) or result.get("updated", 0):
                            print(f"[{cycle}] linguistic growth: +{result.get('inserted', 0)} new, {result.get('updated', 0)} updated")
                except APIError as e:
                    logger.warning("Generate/learn phase failed: %s", e)

        except Exception as e:
            logger.exception("Interpret loop error: %s", e)

        time.sleep(delay)


if __name__ == "__main__":
    run()
