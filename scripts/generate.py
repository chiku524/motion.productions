#!/usr/bin/env python3
"""
CLI: Generate one full video from one prompt. No scenes — one output file.
Usage:
  python scripts/generate.py "Your prompt here"
  python scripts/generate.py "Your prompt" --duration 30
  python scripts/generate.py "Your prompt" --duration 10 --output my_video.mp4
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import argparse

from src.config import load_config
from src.pipeline import generate_full_video
from src.procedural import ProceduralVideoGenerator


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate one full video from a single prompt (local, no external APIs)."
    )
    parser.add_argument(
        "prompt",
        type=str,
        help="Text prompt describing the video you want.",
    )
    parser.add_argument(
        "--duration",
        "-d",
        type=float,
        default=6.0,
        help="Target duration in seconds (default: 6).",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output video path (default: output/video_<timestamp>.mp4).",
    )
    parser.add_argument(
        "--style",
        type=str,
        default=None,
        help="Optional style (e.g. cinematic, anime).",
    )
    parser.add_argument(
        "--tone",
        type=str,
        default=None,
        help="Optional tone (e.g. dreamy, dark).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Optional random seed for reproducibility.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config YAML (default: config/default.yaml).",
    )
    parser.add_argument(
        "--learn",
        action="store_true",
        help="After generating, interpret the output and log it for training/learning.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    out_cfg = config.get("output", {})
    generator = ProceduralVideoGenerator(
        width=out_cfg.get("width", 512),
        height=out_cfg.get("height", 512),
        fps=out_cfg.get("fps", 24),
    )

    print(f"Prompt: {args.prompt[:60]}{'...' if len(args.prompt) > 60 else ''}")
    print(f"Duration: {args.duration}s")
    print("Generating... (procedural engine — no external model)")

    path = generate_full_video(
        args.prompt,
        args.duration,
        generator=generator,
        output_path=args.output,
        style=args.style,
        tone=args.tone,
        seed=args.seed,
        config=config,
    )
    print(f"Done. Video: {path}")

    if args.learn:
        from src.analysis import analyze_video
        from src.learning import log_run
        from src.interpretation import interpret_user_prompt
        from src.creation import build_spec_from_instruction
        from src.knowledge import grow_from_analysis
        instruction = interpret_user_prompt(args.prompt, default_duration=args.duration)
        spec = build_spec_from_instruction(instruction, knowledge=None)
        analysis = analyze_video(path)
        log_path = log_run(
            args.prompt,
            {"palette_name": spec.palette_name, "motion_type": spec.motion_type, "intensity": spec.intensity},
            analysis.to_dict(),
            video_path=str(path),
            config=config,
        )
        # Growth: add novel colors/motion to learned registry (the loop)
        grown = grow_from_analysis(analysis.to_dict(), prompt=args.prompt, config=config)
        print(f"Logged for learning: {log_path} (grown: {grown})")


if __name__ == "__main__":
    main()
