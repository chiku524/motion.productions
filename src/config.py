"""
Load and expose app config (YAML). Used by the pipeline to get output dir, video params, etc.
"""
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config from YAML. Path is optional; defaults to config/default.yaml."""
    if config_path is None:
        config_path = _project_root() / "config" / "default.yaml"
    path = Path(config_path)
    if not path.exists():
        return _defaults()
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {**_defaults(), **data}


def _defaults() -> dict[str, Any]:
    return {
        "output": {
            "dir": "output",
            "filename_prefix": "video",
            "width": 512,
            "height": 512,
            "fps": 24,
        },
        "video": {"max_single_clip_seconds": 6},
        "prompt": {"enrich": False},
    }


def get_output_dir(config: dict[str, Any]) -> Path:
    """Resolve output directory (relative to project root if needed)."""
    out = config.get("output", {})
    d = out.get("dir", "output")
    p = Path(d)
    if not p.is_absolute():
        p = _project_root() / p
    return p
