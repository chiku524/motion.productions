#!/usr/bin/env python3
"""
Sound-only workflow: no video create/render. Pure sound = noise in one frame (one instant).
Origin/primitive sound values (silence, rumble, tone, hiss) live in the mesh (static_sound
registry); the loop records new discoveries as blends of primitives for each instant,
so the mesh holds primitives + discovered values. This script: generates audio to a WAV;
measures per-instant sound; records blends into the mesh; syncs to API for next-run discovery.

Usage:
  python scripts/sound_loop.py
  python scripts/sound_loop.py --api-base https://motion.productions
  SOUND_LOOP_DELAY_SECONDS=20 python scripts/sound_loop.py
"""
import argparse
import logging
import os
import random
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logger = logging.getLogger(__name__)

DEFAULT_DELAY_SECONDS = 15
DEFAULT_DURATION_SECONDS = 2.5
SOUND_LOOP_FPS = 24


def _pick_audio_params(knowledge: dict) -> tuple[str, str, str]:
    """Pick mood, tempo, presence: prefer learned_audio when available, else keyword origins."""
    learned = knowledge.get("learned_audio") or []
    if learned and isinstance(learned, list):
        entry = random.choice(learned)
        if isinstance(entry, dict):
            mood = entry.get("mood") or entry.get("output", {}).get("mood", "neutral")
            tempo = entry.get("tempo") or entry.get("output", {}).get("tempo", "medium")
            presence = entry.get("presence") or entry.get("output", {}).get("presence", "ambient")
            return (str(mood), str(tempo), str(presence))
    from src.procedural.data.keywords import (
        KEYWORD_TO_AUDIO_MOOD,
        KEYWORD_TO_AUDIO_TEMPO,
        KEYWORD_TO_AUDIO_PRESENCE,
    )
    mood = random.choice(list(KEYWORD_TO_AUDIO_MOOD.values()))
    tempo = random.choice(list(KEYWORD_TO_AUDIO_TEMPO.values()))
    presence = random.choice(list(KEYWORD_TO_AUDIO_PRESENCE.values()))
    return (mood, tempo, presence)


def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = argparse.ArgumentParser(description="Sound-only loop (no video; pure sound discovery).")
    parser.add_argument(
        "--api-base",
        default=os.environ.get("API_BASE", "https://motion.productions"),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Seconds between cycles (env SOUND_LOOP_DELAY_SECONDS)",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Audio duration per cycle in seconds (env SOUND_LOOP_DURATION_SECONDS)",
    )
    parser.add_argument("--health-port", type=int, default=None, help="Port for health HTTP server (0=disabled); env HEALTH_PORT")
    args = parser.parse_args()
    delay = (
        args.delay
        if args.delay is not None
        else float(os.environ.get("SOUND_LOOP_DELAY_SECONDS", DEFAULT_DELAY_SECONDS))
    )
    duration = (
        args.duration
        if args.duration is not None
        else float(os.environ.get("SOUND_LOOP_DURATION_SECONDS", DEFAULT_DURATION_SECONDS))
    )

    from src.api_client import APIError, api_request_with_retry
    from src.config import load_config, get_output_dir
    from src.audio import generate_audio_only
    from src.knowledge.extractor_per_instance import read_audio_segments_only
    from src.knowledge.growth_per_instance import grow_static_sound_from_audio_segments
    from src.knowledge.remote_sync import post_static_discoveries
    from src.knowledge.lookup import get_knowledge_for_creation
    from src.workflow_utils import setup_graceful_shutdown, start_health_server, request_shutdown

    setup_graceful_shutdown()
    health_port = args.health_port if args.health_port is not None else int(os.environ.get("HEALTH_PORT", "0"))
    if health_port > 0:
        start_health_server(health_port)

    api_base = args.api_base.rstrip("/") if args.api_base else ""
    config = load_config()
    out_dir = get_output_dir(config)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("Sound-only worker started (no create/render)")
    print(f"API: {api_base or '(none — local only)'}")
    print(f"Delay: {delay}s, duration: {duration}s per cycle\n")

    cycle = 0
    while True:
        if request_shutdown():
            print("Shutdown requested, exiting")
            break
        cycle += 1
        wav_path = out_dir / f"sound_loop_{cycle}.wav"
        try:
            knowledge = {}
            if api_base:
                try:
                    knowledge = get_knowledge_for_creation(config, api_base=api_base)
                except APIError as e:
                    logger.warning("Knowledge fetch failed (status=%s): %s — using empty", e.status_code, e)
                except Exception as e:
                    logger.warning("Knowledge fetch failed: %s — using empty", e)

            mood, tempo, presence = _pick_audio_params(knowledge)
            source_prompt = f"sound_loop:mood={mood},tempo={tempo},presence={presence}"

            generate_audio_only(
                duration,
                wav_path,
                mood=mood,
                tempo=tempo,
                presence=presence,
            )
            segments = read_audio_segments_only(
                wav_path,
                fps=SOUND_LOOP_FPS,
                duration_seconds=duration,
            )
            added, novel_list = grow_static_sound_from_audio_segments(
                segments,
                prompt=source_prompt,
                config=config,
                collect_novel_for_sync=bool(api_base),
            )
            count = added.get("static_sound", 0)
            if api_base and novel_list:
                try:
                    post_static_discoveries(
                        api_base,
                        [],  # no static_colors in sound-only
                        novel_list,
                        job_id=None,
                    )
                except APIError as e:
                    logger.warning("POST discoveries failed (status=%s): %s", e.status_code, e)

            if count:
                print(f"[{cycle}] sound discovery: +{count} (mood={mood}, tempo={tempo}, presence={presence})")
            else:
                print(f"[{cycle}] no new sounds this cycle")

            try:
                wav_path.unlink(missing_ok=True)
            except OSError:
                pass
        except Exception as e:
            logger.exception("Sound loop cycle error: %s", e)
            print(f"[{cycle}] error: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    run()
