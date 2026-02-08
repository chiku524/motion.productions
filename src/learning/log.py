"""
Log each generation run (prompt, spec, analysis) for learning. Our data only — JSONL.
"""
import json
from pathlib import Path
from typing import Any

from ..config import load_config, get_output_dir


def get_log_path(config: dict[str, Any] | None = None) -> Path:
    """Path to the learning log file (JSONL)."""
    if config is None:
        config = load_config()
    out_dir = get_output_dir(config)
    return out_dir.parent / "learning_log.jsonl"


def log_run(
    prompt: str,
    spec: dict[str, Any],
    analysis: dict[str, Any],
    *,
    video_path: str | None = None,
    config: dict[str, Any] | None = None,
) -> Path:
    """
    Append one run to the learning log: prompt, spec we used, and interpreter analysis.
    Returns the path to the log file.
    """
    log_path = get_log_path(config)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "prompt": prompt,
        "spec": spec,
        "analysis": analysis,
        "video_path": video_path,
    }
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return log_path


def read_log(log_path: Path | None = None) -> list[dict[str, Any]]:
    """Read all entries from the learning log."""
    if log_path is None:
        log_path = get_log_path()
    if not log_path.exists():
        return []
    entries = []
    with open(log_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries
