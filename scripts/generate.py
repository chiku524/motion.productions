#!/usr/bin/env python3
"""
CLI: Generate one full video from one prompt. No scenes — one output file.
Usage:
  python scripts/generate.py "Your prompt here"
  python scripts/generate.py "Your prompt" --duration 30
  python scripts/generate.py "Your prompt" --duration 10 --output my_video.mp4
"""
import argparse
from pathlib import Path

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
        from src.learning import log_run
        from src.knowledge.growth_per_instance import grow_all_from_video
        from src.knowledge.narrative_registry import grow_narrative_from_spec
        from src.knowledge import extract_from_video

        instruction = getattr(generator, "_last_instruction", None)
        spec = getattr(generator, "_last_spec", None)
        if instruction is None or spec is None:
            from src.interpretation import interpret_user_prompt
            from src.creation import build_spec_from_instruction
            from src.knowledge import get_knowledge_for_creation
            if instruction is None:
                instruction = interpret_user_prompt(args.prompt, default_duration=args.duration)
            if spec is None:
                spec = build_spec_from_instruction(
                    instruction, knowledge=get_knowledge_for_creation(config)
                )

        analysis_dict = extract_from_video(path).to_dict()
        log_path = log_run(
            args.prompt,
            {
                "palette_name": getattr(spec, "palette_name", ""),
                "motion_type": getattr(spec, "motion_type", ""),
                "intensity": getattr(spec, "intensity", 1.0),
                "gradient_type": getattr(spec, "gradient_type", None),
                "camera_motion": getattr(spec, "camera_motion", None),
            },
            analysis_dict,
            video_path=str(path),
            config=config,
        )
        try:
            added, _ = grow_all_from_video(
                path,
                prompt=args.prompt,
                config=config,
                max_frames=None,
                sample_every=2,
                window_seconds=1.0,
                collect_novel_for_sync=False,
                spec=spec,
                extraction_focus="all",
            )
            narrative_added, _ = grow_narrative_from_spec(
                spec,
                prompt=args.prompt,
                config=config,
                instruction=instruction,
                collect_novel_for_sync=False,
            )
            total = sum(added.values()) + sum(narrative_added.values())
            print(
                f"Registry growth: static+dynamic={sum(added.values())}, "
                f"narrative={sum(narrative_added.values())} (total {total})"
            )
        except Exception as e:
            print(f"Registry growth failed: {e}")
        print(f"Logged for learning: {log_path}")


if __name__ == "__main__":
    main()
