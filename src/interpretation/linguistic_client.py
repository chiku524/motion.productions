"""
Client for linguistic registry API. Fetch mappings for interpretation; post growth.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def fetch_linguistic_registry(api_base: str, domain: str | None = None) -> dict[str, dict[str, str]]:
    """
    Fetch linguistic registry from API. Returns {domain: {span: canonical}}.
    """
    try:
        from ..api_client import api_request_with_retry
        path = f"/api/linguistic-registry?domain={domain}" if domain else "/api/linguistic-registry"
        data = api_request_with_retry(api_base, "GET", path, timeout=10)
        mappings = data.get("mappings", [])
        out: dict[str, dict[str, str]] = {}
        for m in mappings:
            d = m.get("domain", "")
            span = m.get("span", "").strip().lower()
            canonical = m.get("canonical", "").strip()
            if d and span and canonical:
                out.setdefault(d, {})[span] = canonical
        return out
    except Exception as e:
        logger.debug("Fetch linguistic registry failed: %s", e)
        return {}


def post_linguistic_growth(
    api_base: str,
    items: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Post extracted mappings to linguistic registry. Upserts; increments count if exists.
    items: [{"span": str, "canonical": str, "domain": str, "variant_type"?: str}]
    """
    if not items:
        return {"inserted": 0, "updated": 0}
    try:
        from ..api_client import api_request_with_retry
        data = api_request_with_retry(
            api_base, "POST", "/api/linguistic-registry/batch",
            data={"items": items},
            timeout=15,
        )
        return {"inserted": data.get("inserted", 0), "updated": data.get("updated", 0)}
    except Exception as e:
        logger.warning("Post linguistic growth failed: %s", e)
        return {"inserted": 0, "updated": 0}
