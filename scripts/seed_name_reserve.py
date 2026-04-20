#!/usr/bin/env python3
"""
Pre-seed the name reserve with a large pool of unique names.
Run periodically or at setup to ensure mass amounts of names on reserve.

Usage:
  python scripts/seed_name_reserve.py
  python scripts/seed_name_reserve.py --size 100000
"""
import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="Pre-seed the name reserve.")
    parser.add_argument(
        "--size",
        type=int,
        default=50000,
        help="Target pool size (default: 50000)",
    )
    args = parser.parse_args()

    from src.knowledge import ensure_reserve, reserve_status

    print(f"Ensuring name reserve has at least {args.size} names...")
    ensure_reserve(args.size)
    status = reserve_status()
    print(f"Done. Pool size: {status['pool_size']}, used: {status['used_count']}, total generated: {status['total_generated']}")


if __name__ == "__main__":
    main()
