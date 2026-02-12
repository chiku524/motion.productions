#!/usr/bin/env python3
"""
One-time backfill: interpret prompts from jobs and store in interpretation registry.
Use when the interpretation registry is empty and the interpret worker hasn't caught up.

Usage:
  py scripts/backfill_interpretations.py --api-base https://motion.productions
  py scripts/backfill_interpretations.py --limit 100
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill interpretation registry from jobs.")
    parser.add_argument("--api-base", default="https://motion.productions", help="API base URL")
    parser.add_argument("--limit", type=int, default=100, help="Max prompts to interpret")
    args = parser.parse_args()
    api_base = args.api_base.rstrip("/")

    from src.api_client import APIError, api_request_with_retry
    from src.interpretation import interpret_user_prompt

    print("Fetching prompts from jobs without interpretation...")
    try:
        data = api_request_with_retry(
            api_base, "GET", f"/api/interpret/backfill-prompts?limit={args.limit}",
            timeout=30,
        )
    except APIError as e:
        print(f"Failed to fetch backfill prompts: {e}")
        sys.exit(1)

    prompts = [p.strip() for p in data.get("prompts", []) if p and isinstance(p, str)]
    if not prompts:
        print("No prompts to backfill.")
        return

    print(f"Found {len(prompts)} prompts. Interpreting and storing...")
    batch: list[dict] = []
    for i, prompt in enumerate(prompts):
        try:
            instruction = interpret_user_prompt(prompt, default_duration=6.0)
            payload = instruction.to_api_dict() if hasattr(instruction, "to_api_dict") else instruction.to_dict()
            batch.append({"prompt": prompt, "instruction": payload, "source": "backfill"})
        except Exception as e:
            print(f"  [{i+1}] Interpret failed for {prompt[:40]}…: {e}")

    if not batch:
        print("No interpretations produced.")
        return

    try:
        resp = api_request_with_retry(
            api_base, "POST", "/api/interpretations/batch",
            data={"items": batch},
            timeout=60,
        )
        n = resp.get("inserted", 0)
        print(f"Stored {n} interpretations.")
    except APIError as e:
        print(f"Batch POST failed: {e}. Falling back to single POSTs...")
        n = 0
        for it in batch:
            try:
                api_request_with_retry(api_base, "POST", "/api/interpretations", data=it, timeout=15)
                n += 1
                if n % 10 == 0:
                    print(f"  Stored {n}...")
            except APIError:
                pass
        print(f"Stored {n} interpretations (single POSTs).")


if __name__ == "__main__":
    main()
