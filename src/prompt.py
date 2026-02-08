"""
Prompt enrichment: optional step to expand or refine the user prompt (e.g. style, tone).
Returns a single string (and optional metadata) — no "scenes"; one full-video description.
"""
from typing import Any


def enrich_prompt(
    prompt: str,
    *,
    style: str | None = None,
    tone: str | None = None,
    duration_seconds: float | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    """
    Optionally enrich the user prompt (e.g. add style/tone keywords).
    When no LLM is configured, returns the prompt as-is or with a simple suffix from config.
    """
    if not (config or {}).get("prompt", {}).get("enrich", False):
        return _simple_suffix(prompt, config)
    # Future: call local LLM here to expand into one rich description (still one string)
    return _simple_suffix(prompt, config)


def _simple_suffix(prompt: str, config: dict[str, Any] | None) -> str:
    suffix = (config or {}).get("prompt", {}).get("style_suffix")
    if not suffix:
        return prompt
    return f"{prompt}. {suffix}"
