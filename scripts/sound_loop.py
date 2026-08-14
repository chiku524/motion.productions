#!/usr/bin/env python3
"""
Sound-only workflow: no video create/render.

Sounds live on their own spectrum, same idea as color:
  frame  — pair two registry instants and hold them still (static_sound growth)
  window — rematch 3–4 sounds over ~1s (dynamic blends of those instants)

Each cycle picks a new pairing from primitives + discoveries, not a mood catalog.

Usage:
  python scripts/sound_loop.py
  python scripts/sound_loop.py --api-base https://motion.productions
  SOUND_LOOP_DELAY_SECONDS=20 python scripts/sound_loop.py
"""
import argparse
import logging
import os
import random
import time

logger = logging.getLogger(__name__)

DEFAULT_DELAY_SECONDS = 15
DEFAULT_DURATION_SECONDS = 2.5
SOUND_LOOP_FPS = 24


def _pick_audio_params(knowledge: dict) -> tuple[str, str, str]:
    """Pick mood, tempo, presence: prefer learned_audio when available, else full AUDIO_ORIGINS."""
    learned = knowledge.get("learned_audio") or []
    if learned and isinstance(learned, list):
        entry = random.choice(learned)
        if isinstance(entry, dict):
            mood = entry.get("mood") or entry.get("output", {}).get("mood", "neutral")
            tempo = entry.get("tempo") or entry.get("output", {}).get("tempo", "medium")
            presence = entry.get("presence") or entry.get("output", {}).get("presence", "ambient")
            return (str(mood), str(tempo), str(presence))
    try:
        from src.knowledge.origins import AUDIO_ORIGINS
        mood = random.choice(list(AUDIO_ORIGINS.get("mood") or ["neutral"]))
        tempo = random.choice(list(AUDIO_ORIGINS.get("tempo") or ["medium"]))
        presence = random.choice(list(AUDIO_ORIGINS.get("presence") or ["ambient"]))
        return (mood, tempo, presence)
    except Exception:
        from src.procedural.data.keywords import (
            KEYWORD_TO_AUDIO_MOOD,
            KEYWORD_TO_AUDIO_TEMPO,
            KEYWORD_TO_AUDIO_PRESENCE,
        )
        mood = random.choice(list(KEYWORD_TO_AUDIO_MOOD.values()))
        tempo = random.choice(list(KEYWORD_TO_AUDIO_TEMPO.values()))
        presence = random.choice(list(KEYWORD_TO_AUDIO_PRESENCE.values()))
        return (mood, tempo, presence)


def _pick_target_primitive(api_base: str) -> str | None:
    """Prefer missing sound origins from mission, then coverage gaps."""
    from src.knowledge.mission_targets import pick_target_sound_origin

    targeted = pick_target_sound_origin(api_base)
    if targeted:
        return targeted
    from src.knowledge.blend_depth import SOUND_ORIGIN_PRIMITIVES

    missing: list[str] = []
    if api_base:
        try:
            from src.api_client import api_get
            cov = api_get(api_base, "/api/registries/coverage") or {}
            missing = list(cov.get("static_sound_primitives_missing") or [])
        except Exception:
            missing = []
    underused = ["rustle", "click", "whoosh", "drip", "hiss", "hum", "thump"]
    pool = [p for p in underused if p in (missing or underused)]
    if missing:
        pool = [p for p in missing if p != "silence"] or underused
    if not pool:
        pool = [p for p in SOUND_ORIGIN_PRIMITIVES if p != "silence"]
    return random.choice(pool)


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

    from src.api_client import APIError
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
            pairing_kind = "window" if random.random() < 0.4 else "frame"
            pair_count = 4 if pairing_kind == "window" else 2
            clip_duration = duration if pairing_kind == "frame" else max(duration, 4.0)

            from src.audio.pairing import sample_sound_pairing, sound_label
            pairing = sample_sound_pairing(
                knowledge,
                prompt="",
                pair_count=pair_count,
                seed=cycle * 7919 + 13,
            )
            labels = [sound_label(e) for e in pairing if sound_label(e)]
            if pairing_kind == "window":
                source_prompt = (
                    f"dynamic sound pairing of {labels[0]} with {labels[1]}"
                    if len(labels) >= 2
                    else "sound_loop window pairing"
                )
            else:
                source_prompt = (
                    f"static sound pairing of {labels[0]} with {labels[1]}"
                    if len(labels) >= 2
                    else "sound_loop frame pairing"
                )
            target_primitive = labels[0] if labels else _pick_target_primitive(api_base)

            generate_audio_only(
                clip_duration,
                wav_path,
                mood=mood,
                tempo=tempo,
                presence=presence,
                target_primitive=target_primitive,
                pure_sounds=pairing or None,
                pairing_kind=pairing_kind,
            )
            segments = read_audio_segments_only(
                wav_path,
                fps=SOUND_LOOP_FPS,
                duration_seconds=clip_duration,
            )
            added, novel_list = grow_static_sound_from_audio_segments(
                segments,
                prompt=source_prompt,
                config=config,
                collect_novel_for_sync=bool(api_base),
            )
            count = added.get("static_sound", 0)
            # When decoded audio yields no novel keys, still grow from spec (same as video path).
            # Try a few amplitude jitters so we do not stall on a saturated local mesh.
            if count == 0:
                from types import SimpleNamespace
                from src.knowledge.growth_per_instance import (
                    derive_static_sound_from_spec,
                    ensure_static_sound_in_registry,
                )
                prefer: list[str] = [target_primitive] if target_primitive else []
                spec = SimpleNamespace(
                    audio_mood=mood,
                    audio_tempo=tempo,
                    audio_presence=presence,
                )
                out_novel: list = []
                for _ in range(5):
                    spec_sound = derive_static_sound_from_spec(spec, prefer_primitives=prefer or None)
                    if spec_sound and ensure_static_sound_in_registry(
                        spec_sound,
                        source_prompt=source_prompt,
                        config=config,
                        out_novel=out_novel if api_base else None,
                    ):
                        count += 1
                        if len(out_novel) >= 3:
                            break
                if count:
                    added["static_sound"] = count
                    if out_novel:
                        novel_list = list(novel_list or []) + out_novel
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
                print(
                    f"[{cycle}] sound discovery: +{count} "
                    f"(kind={pairing_kind}, pair={'+'.join(labels[:4])}, "
                    f"segments={len(segments)})"
                )
            else:
                print(
                    f"[{cycle}] no new sounds this cycle "
                    f"(segments={len(segments)}, kind={pairing_kind}, pair={'+'.join(labels[:4])})"
                )

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
