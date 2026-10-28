"""
Client for linguistic registry API. Fetch mappings for interpretation; post growth.
Batching: Workers Paid allows 1000 queries/request; ~2 per item. Max 100 items/request.
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)

LINGUISTIC_BATCH_MAX = 100


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
    Queue extracted mappings for the linguistic registry and flush what is due.

    Repeated bumps of the same (domain, span) are merged locally with summed ``count`` and sent as ONE batched
    upsert per ``LINGUISTIC_FLUSH_INTERVAL_S`` / ``LINGUISTIC_FLUSH_MAX_ITEMS`` (an INSERT costs 5 D1 rows, a
    bump of an existing span 1). Anything denied by the write budget stays queued locally.
    items: [{"span", "canonical", "domain", "variant_type"?, "count"?}]
    Returns {"inserted", "updated", "queued"}; ``WRITE_BUFFERS=0`` posts directly like before.
    """
    if not items:
        return {"inserted": 0, "updated": 0, "queued": 0}
    from ..knowledge.remote_sync import buffers_enabled

    if buffers_enabled():
        from ..knowledge.write_buffers import get_linguistic_coalescer

        co = get_linguistic_coalescer()
        co.add(items)
        res = co.flush(api_base)
        return {"inserted": res["inserted"], "updated": res["updated"], "queued": res["queued"]}
    return _post_linguistic_direct(api_base, items)


def _post_linguistic_direct(api_base: str, items: list[dict[str, Any]]) -> dict[str, int]:
    total_inserted = 0
    total_updated = 0
    try:
        from ..api_client import api_request_with_retry
        for i in range(0, len(items), LINGUISTIC_BATCH_MAX):
            chunk = items[i : i + LINGUISTIC_BATCH_MAX]
            data = api_request_with_retry(
                api_base, "POST", "/api/linguistic-registry/batch",
                data={"items": chunk},
                timeout=30,
            )
            total_inserted += data.get("inserted", 0)
            total_updated += data.get("updated", 0)
        return {"inserted": total_inserted, "updated": total_updated}
    except Exception as e:
        logger.warning("Post linguistic growth failed: %s", e)
        return {"inserted": total_inserted, "updated": total_updated}
