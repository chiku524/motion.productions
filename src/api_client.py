"""
HTTP client for API calls. Uses requests + browser-like headers so Cloudflare
WAF/Bot Fight Mode does not block server-side automation.
Step 1 (ENHANCEMENTS): explicit success/failure, retries, and error context.
When MOTION_API_SECRET or API_SECRET is set, sends Authorization: Bearer <secret>.
"""
import json
import logging
import os
import random
import time

import requests

logger = logging.getLogger(__name__)

_API_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (compatible; Motion-Productions/1.0; +https://motion.productions)",
    "Origin": "https://motion.productions",
    "Referer": "https://motion.productions/",
}


def _auth_headers() -> dict[str, str]:
    """Attach API secret when configured (Docker workers / local scripts)."""
    secret = (os.environ.get("MOTION_API_SECRET") or os.environ.get("API_SECRET") or "").strip()
    if not secret:
        return {}
    return {
        "Authorization": f"Bearer {secret}",
        "X-Motion-Api-Key": secret,
    }

# Retry config: only retry on transient failures
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0
# D1 CPU limit errors need longer recovery before retry
D1_BACKOFF_BASE_SECONDS = 10.0
D1_BACKOFF_INCREMENT = 5.0
# Jitter window for D1-heavy endpoints (spread concurrent workers)
D1_JITTER_MAX_SECONDS = 8.0


# Cloudflare Free-tier daily limits (D1 5M reads / 100k writes, KV 1,000 writes per day) reset at 00:00 UTC.
# Retrying a blocked binding only burns more of the budget, so a limit response (Worker body
# {"error": "free_tier_limit"}) is NOT retried and puts all write requests on a cooldown.
LIMIT_COOLDOWN_SECONDS_DEFAULT = 900.0
_limit_cooldown_until = 0.0


def limit_cooldown_seconds() -> float:
    raw = os.environ.get("FREE_TIER_LIMIT_COOLDOWN_SECONDS", "")
    try:
        return max(1.0, float(raw)) if raw.strip() else LIMIT_COOLDOWN_SECONDS_DEFAULT
    except ValueError:
        return LIMIT_COOLDOWN_SECONDS_DEFAULT


def is_free_tier_limit_body(body: str | None) -> bool:
    """True when an error body says a Cloudflare daily free-tier quota is exhausted (not a transient CPU limit)."""
    if not body:
        return False
    low = body.lower()
    if "free_tier_limit" in low or "d1_db_full" in low or "exceeded maximum db size" in low:
        return True
    if "cpu time" in low:
        return False
    return "daily" in low and "limit" in low


LEARNING_ANALYSIS_KEYS = ("motion_level", "mean_brightness", "mean_contrast")


def slim_learning_analysis(analysis: dict | None) -> dict:
    """Only the scalars the Worker's learning stats aggregate (the rest, e.g. motion_per_frame arrays, bloated D1)."""
    out: dict = {}
    for k in LEARNING_ANALYSIS_KEYS:
        v = (analysis or {}).get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = round(float(v), 3)
    return out


def _note_degraded_success(method: str, path: str, result: object, headers: object = None) -> None:
    """The Worker answers HTTP 200 + {"degraded": true, "error": "d1_db_full"|"free_tier_limit"} instead of a 5xx.
    A write that was not recorded must pause writes like a 503 limit does (no hammering a full/blocked D1)."""
    if method == "GET":
        return
    x_degraded = ""
    try:
        x_degraded = str(headers.get("X-Degraded") or "") if headers is not None else ""  # type: ignore[union-attr]
    except Exception:
        x_degraded = ""
    body_degraded = isinstance(result, dict) and result.get("degraded") is True and (
        result.get("recorded") is False or result.get("error") in ("d1_db_full", "free_tier_limit")
    )
    if x_degraded or body_degraded:
        secs = retry_after_seconds(headers, json.dumps(result) if isinstance(result, dict) else None)
        start_free_tier_cooldown(secs, reason=x_degraded or str((result or {}).get("error") or "degraded"))
        logger.warning("API %s %s degraded (%s); writes paused %.0fs", method, path, x_degraded or (result or {}).get("error"), secs)


# Per-process counters of non-GET API call attempts (each is a potential D1 write); read and reset per loop
# iteration by scripts/automate_loop.py for the local metrics log.
_write_stats = {"requests": 0, "failed": 0}


def pop_write_stats() -> dict:
    """Return {requests, failed} non-GET attempts since the last call and reset them."""
    out = dict(_write_stats)
    _write_stats["requests"] = 0
    _write_stats["failed"] = 0
    return out


class APIError(Exception):
    """API call failed with status or invalid response."""
    def __init__(self, message: str, status_code: int | None = None, path: str = "", body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.path = path
        self.body = body


def _budget():
    """The shared write budget (ledger on the mounted volume), or None when the gate is off / unavailable."""
    try:
        from .knowledge.write_budget import budget_gate_enabled, get_budget
        return get_budget() if budget_gate_enabled() else None
    except Exception as e:  # never break a loop over bookkeeping
        logger.debug("write budget unavailable: %s", e)
        return None


def free_tier_cooldown_remaining() -> float:
    """Seconds writes stay paused: this process's cooldown or the back-off another container started (shared ledger)."""
    local = max(0.0, _limit_cooldown_until - time.monotonic())
    b = _budget()
    return max(local, b.backoff_remaining() if b is not None else 0.0)


def start_free_tier_cooldown(seconds: float | None = None, reason: str = "") -> None:
    """Pause writes for ``seconds`` (default 900) in this process AND, via the shared ledger, in every container."""
    global _limit_cooldown_until
    secs = seconds if seconds is not None else limit_cooldown_seconds()
    _limit_cooldown_until = time.monotonic() + secs
    b = _budget()
    if b is not None:
        b.start_backoff(secs, reason)


def reset_free_tier_cooldown() -> None:
    global _limit_cooldown_until
    _limit_cooldown_until = 0.0
    b = _budget()
    if b is not None:
        b.clear_backoff()


class WriteBudgetSkipped(APIError):
    """A write was not sent because this container's share of the daily D1 write budget is used up (or a shared
    back-off is active). Subclass of APIError so existing handlers keep working; budget-aware callers keep the data
    in a local buffer and retry later instead of treating it as a failure."""


def retry_after_seconds(headers: object, body: str | None = None, default: float | None = None) -> float:
    """Back-off the Worker asked for: Retry-After header, else body retry_after_ms, else the 900 s default."""
    for key in ("Retry-After", "retry-after"):
        try:
            v = headers.get(key) if headers is not None else None  # type: ignore[union-attr]
            if v is not None:
                return max(1.0, float(v))
        except (TypeError, ValueError):
            pass
    if body:
        try:
            ms = json.loads(body).get("retry_after_ms")
            if isinstance(ms, (int, float)) and ms > 0:
                return max(1.0, float(ms) / 1000.0)
        except (ValueError, TypeError, AttributeError):
            pass
    return default if default is not None else limit_cooldown_seconds()


def is_d1_limit_body(body: str | None) -> bool:
    """D1 errors that mean a quota (not a transient CPU blip): back off for the full cooldown, do not retry."""
    if not body:
        return False
    low = body.lower()
    if "cpu time" in low:
        return False
    return "d1_error" in low and any(w in low for w in ("quota", "daily", "rows written", "rows_written", "exceeded its"))


def _parse_json_response(resp: requests.Response) -> dict:
    """Parse JSON body; raise APIError with context if invalid."""
    if not resp.content:
        return {}
    try:
        return resp.json()
    except json.JSONDecodeError as e:
        raise APIError(
            f"Invalid JSON response: {e}",
            status_code=resp.status_code,
            path=resp.url or "",
            body=resp.text[:500] if resp.text else None,
        ) from e


def api_request(
    api_base: str,
    method: str,
    path: str,
    data: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 60,
    max_retries: int = 0,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict:
    """
    Execute API request. Raises APIError on failure with context.
    If max_retries > 0, retries on 5xx and connection errors only.
    """
    url = f"{api_base.rstrip('/')}{path}"
    if method != "GET" and free_tier_cooldown_remaining() > 0:
        # Do not hit a blocked Worker: skip writes until the cooldown ends (reads still flow, they are served degraded).
        raise APIError(
            f"API {method} {path} skipped: Cloudflare free-tier limit cooldown ({free_tier_cooldown_remaining():.0f}s left)",
            status_code=503, path=path, body='{"error":"free_tier_limit","skipped":true}',
        )
    reserved = 0
    budget = _budget() if method != "GET" else None
    if budget is not None:
        from .knowledge.write_budget import estimate_rows
        est, prio = estimate_rows(method, path, data)
        if est > 0:
            if not budget.reserve(est, prio):
                raise WriteBudgetSkipped(
                    f"API {method} {path} skipped: {budget.name} is out of its daily D1 write budget "
                    f"({budget.used()}/{budget.allowance()} rows used; resets 00:00 UTC)",
                    status_code=503, path=path, body='{"error":"write_budget","skipped":true}',
                )
            reserved = est
    # Jitter for heavy D1 endpoints: spread concurrent requests from multiple workers
    needs_jitter = (
        (method == "GET" and (
            "/api/knowledge/for-creation" in path
            or "/api/loop/progress" in path
            or "/api/interpret/backfill-prompts" in path
            or "/api/learning/stats" in path
        ))
        or (method == "POST" and "/api/knowledge/discoveries" in path)
    )
    if needs_jitter:
        time.sleep(random.uniform(0, D1_JITTER_MAX_SECONDS))
    headers = {**_API_HEADERS, **_auth_headers()}
    if raw_body is not None:
        body = raw_body
        if content_type:
            headers["Content-Type"] = content_type
    elif isinstance(data, dict):
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"
    else:
        body = None

    last_exc: Exception | None = None
    for attempt in range(max(1, max_retries + 1)):
        if method != "GET":
            _write_stats["requests"] += 1
        try:
            resp = requests.request(method, url, data=body, headers=headers, timeout=timeout)
            resp.raise_for_status()
            parsed = _parse_json_response(resp)
            _note_degraded_success(method, path, parsed, resp.headers)
            if budget is not None and reserved:
                _settle_reservation(budget, reserved, parsed)
            return parsed
        except requests.exceptions.HTTPError as e:
            last_exc = e
            if method != "GET":
                _write_stats["failed"] += 1
            status = e.response.status_code if e.response is not None else None
            # `is not None`: a requests.Response is falsy for 4xx/5xx, so a plain truthiness test dropped every error body
            err_body = e.response.text[:500] if e.response is not None and e.response.text else None
            degraded_hdr = e.response is not None and bool(e.response.headers.get("X-Degraded"))
            if (status in (429, 503) and (is_free_tier_limit_body(err_body) or degraded_hdr)) or is_d1_limit_body(err_body):
                secs = retry_after_seconds(e.response.headers if e.response is not None else None, err_body)
                start_free_tier_cooldown(secs, reason=f"http {status}")
                if budget is not None and reserved:
                    budget.refund(reserved)  # a degraded Worker answer wrote nothing
                    reserved = 0
                logger.warning(
                    "API %s %s hit the Cloudflare free-tier daily limit; no retry, writes paused %.0fs",
                    method, path, secs,
                )
                raise APIError(f"API {method} {path} free_tier_limit: {err_body}", status_code=status, path=path, body=err_body) from e
            # Retry on 5xx and 429 (rate limit, e.g. KV 1 write/sec)
            retryable = status and (500 <= status < 600 or status == 429) and attempt < max_retries
            if retryable:
                delay = backoff_seconds
                is_d1_error = err_body and (
                    "D1_ERROR" in err_body
                    or "D1 DB exceeded" in err_body
                    or "CPU time limit" in err_body
                    or "Network connection lost" in err_body
                )
                if is_d1_error:
                    # D1 needs time to reset; longer backoff avoids retry storm
                    delay = D1_BACKOFF_BASE_SECONDS + attempt * D1_BACKOFF_INCREMENT
                    logger.warning(
                        "API %s %s → D1 error (attempt %s), retrying in %.1fs",
                        method, path, attempt + 1, delay,
                    )
                elif status == 429:
                    delay = backoff_seconds + attempt * 2.0
                    # Prefer lease body retry_after_ms (discoveries write lease)
                    if err_body:
                        try:
                            parsed = json.loads(err_body)
                            ms = parsed.get("retry_after_ms")
                            if isinstance(ms, (int, float)) and ms > 0:
                                # Cap wait so a stuck/long lease does not freeze the loop for minutes
                                delay = max(5.0, min(float(ms) / 1000.0, 25.0))
                        except (json.JSONDecodeError, TypeError, ValueError):
                            pass
                    if e.response is not None and "Retry-After" in e.response.headers:
                        try:
                            header_delay = float(e.response.headers["Retry-After"])
                            delay = max(delay, min(header_delay, 25.0), 5.0)
                        except (ValueError, TypeError):
                            delay = max(delay, 5.0)
                    else:
                        delay = max(delay, 5.0)
                    logger.warning("API %s %s → %s (attempt %s), retrying in %.1fs", method, path, status, attempt + 1, delay)
                else:
                    logger.warning("API %s %s → %s (attempt %s), retrying in %.1fs", method, path, status, attempt + 1, delay)
                time.sleep(delay)
                continue
            msg = f"API {method} {path} failed: {e}"
            if err_body and status and 500 <= status < 600:
                msg += f" — response: {err_body[:300]}"
            raise APIError(msg, status_code=status, path=path, body=err_body) from e
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exc = e
            if method != "GET":
                _write_stats["failed"] += 1
            if attempt < max_retries:
                delay = backoff_seconds
                # Discoveries timeouts usually mean D1/Worker overload — back off like D1 errors
                if method == "POST" and "/api/knowledge/discoveries" in path:
                    delay = D1_BACKOFF_BASE_SECONDS + attempt * D1_BACKOFF_INCREMENT
                logger.warning(
                    "API %s %s connection/timeout (attempt %s), retrying in %.1fs",
                    method, path, attempt + 1, delay,
                )
                time.sleep(delay)
                continue
            raise APIError(f"API {method} {path} failed: {e}", path=path) from e
    if last_exc:
        raise last_exc
    raise APIError(f"API {method} {path} failed", path=path)


def _settle_reservation(budget, reserved: int, parsed: object) -> None:
    """Replace the worst-case charge by the rows the Worker says it wrote (``rows_written``), when it reports them."""
    try:
        actual = parsed.get("rows_written") if isinstance(parsed, dict) else None
        if isinstance(actual, (int, float)) and not isinstance(actual, bool) and actual >= 0:
            budget.settle(reserved, int(actual))
    except Exception as e:
        logger.debug("write budget settle skipped: %s", e)


def api_request_with_retry(
    api_base: str,
    method: str,
    path: str,
    data: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 60,
    max_retries: int = DEFAULT_MAX_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> dict:
    """Same as api_request but with retries on 5xx and connection errors."""
    return api_request(
        api_base, method, path,
        data=data, raw_body=raw_body, content_type=content_type, timeout=timeout,
        max_retries=max_retries, backoff_seconds=backoff_seconds,
    )


def api_get(api_base: str, path: str, timeout: int = 60) -> dict:
    return api_request(api_base, "GET", path, timeout=timeout)


def api_post(api_base: str, path: str, data: dict | None = None, raw_body: bytes | None = None, content_type: str | None = None, timeout: int = 60) -> dict:
    return api_request(api_base, "POST", path, data=data, raw_body=raw_body, content_type=content_type, timeout=timeout)


def api_post_binary(api_base: str, path: str, body: bytes, content_type: str = "application/octet-stream", timeout: int = 120) -> None:
    """POST raw bytes (e.g. video upload). Returns None; raises APIError on error."""
    url = f"{api_base.rstrip('/')}{path}"
    headers = {**_API_HEADERS, **_auth_headers(), "Content-Type": content_type}
    if free_tier_cooldown_remaining() > 0:
        raise WriteBudgetSkipped(
            f"API POST {path} skipped: write back-off ({free_tier_cooldown_remaining():.0f}s left)",
            status_code=503, path=path, body='{"error":"free_tier_limit","skipped":true}',
        )
    budget = _budget()
    if budget is not None:
        from .knowledge.write_budget import estimate_rows
        est, prio = estimate_rows("POST", path)
        if est > 0 and not budget.reserve(est, prio):
            raise WriteBudgetSkipped(
                f"API POST {path} skipped: {budget.name} is out of its daily D1 write budget",
                status_code=503, path=path, body='{"error":"write_budget","skipped":true}',
            )
    try:
        resp = requests.post(url, data=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
        # Some endpoints return empty body; avoid .json() on empty
        if resp.content:
            _note_degraded_success("POST", path, _parse_json_response(resp), resp.headers)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        err_body = e.response.text[:500] if e.response is not None and e.response.text else None
        if e.response is not None and (e.response.headers.get("X-Degraded") or is_free_tier_limit_body(err_body)):
            start_free_tier_cooldown(retry_after_seconds(e.response.headers, err_body), reason=f"http {status}")
        raise APIError(f"API POST {path} failed: {e}", status_code=status, path=path, body=err_body) from e


def loop_upload_videos_enabled() -> bool:
    """Loop clips are NOT stored in R2 by default (free tier: 10 GB). Set LOOP_UPLOAD_VIDEOS=1 to upload them."""
    return (os.environ.get("LOOP_UPLOAD_VIDEOS") or "").strip().lower() in ("1", "true", "yes", "on")


def finish_loop_job(
    api_base: str,
    job_id: str,
    video_path: str | os.PathLike | None = None,
    *,
    timeout: int = 120,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> dict:
    """
    Complete a loop-owned job. Uploads the clip only when LOOP_UPLOAD_VIDEOS is truthy; otherwise marks the job
    completed with POST /api/jobs/{id}/complete (no R2 write). Web-submitted jobs keep using the upload route.
    """
    if loop_upload_videos_enabled() and video_path is not None:
        with open(video_path, "rb") as f:
            body = f.read()
        return api_request_with_retry(
            api_base, "POST", f"/api/jobs/{job_id}/upload",
            raw_body=body, content_type="video/mp4", timeout=timeout, max_retries=max_retries,
        )
    return api_request_with_retry(
        api_base, "POST", f"/api/jobs/{job_id}/complete", data={}, timeout=60, max_retries=max_retries,
    )
