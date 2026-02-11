#!/usr/bin/env python3
"""
Interpretation-only worker: no create/render. Polls queue, interprets user prompts,
stores results in D1 via API. Main loop uses interpretation_prompts from GET /api/knowledge/for-creation.

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
    args = parser.parse_args()
    delay = args.delay if args.delay is not None else float(os.environ.get("INTERPRET_DELAY_SECONDS", DEFAULT_DELAY_SECONDS))

    from src.api_client import APIError, api_request_with_retry
    from src.interpretation import interpret_user_prompt

    api_base = args.api_base.rstrip("/")
    print("Interpretation worker started (no create/render)")
    print(f"API: {api_base}")
    print(f"Delay: {delay}s between cycles. Backfill: {'off' if args.no_backfill else 'on'}\n")

    cycle = 0
    while True:
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
            for item in items:
                uid = item.get("id")
                prompt = item.get("prompt", "").strip()
                if not uid or not prompt:
                    continue
                try:
                    instruction = interpret_user_prompt(prompt, default_duration=6.0)
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

            # 2) Backfill: interpret prompts from jobs that don't have an interpretation yet
            if not args.no_backfill and api_base:
                try:
                    backfill = api_request_with_retry(
                        api_base, "GET", "/api/interpret/backfill-prompts?limit=15",
                        timeout=15,
                    )
                    prompts = backfill.get("prompts", [])
                    for prompt in prompts:
                        if not (prompt and isinstance(prompt, str)):
                            continue
                        prompt = prompt.strip()
                        try:
                            instruction = interpret_user_prompt(prompt, default_duration=6.0)
                            payload = instruction.to_api_dict() if hasattr(instruction, "to_api_dict") else instruction.to_dict()
                            api_request_with_retry(
                                api_base, "POST", "/api/interpretations",
                                data={"prompt": prompt, "instruction": payload, "source": "backfill"},
                                timeout=15,
                            )
                            print(f"[{cycle}] backfill: {prompt[:50]}…")
                        except APIError as e:
                            logger.warning("POST /api/interpretations (backfill) failed: %s", e)
                        except Exception as e:
                            logger.warning("Backfill interpret failed for %s: %s", prompt[:40], e)
                except APIError as e:
                    logger.warning("GET /api/interpret/backfill-prompts failed: %s", e)

        except Exception as e:
            logger.exception("Interpret loop error: %s", e)

        time.sleep(delay)


if __name__ == "__main__":
    run()
