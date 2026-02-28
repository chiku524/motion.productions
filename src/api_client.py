"""
HTTP client for API calls. Uses requests + browser-like headers so Cloudflare
WAF/Bot Fight Mode does not block server-side automation.
Step 1 (ENHANCEMENTS): explicit success/failure, retries, and error context.
"""
import json
import logging
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

# Retry config: only retry on transient failures
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_SECONDS = 2.0
# D1 CPU limit errors need longer recovery before retry
D1_BACKOFF_BASE_SECONDS = 10.0
D1_BACKOFF_INCREMENT = 5.0
# Jitter window for D1-heavy endpoints (spread concurrent workers)
D1_JITTER_MAX_SECONDS = 8.0


class APIError(Exception):
    """API call failed with status or invalid response."""
    def __init__(self, message: str, status_code: int | None = None, path: str = "", body: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.path = path
        self.body = body


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
    headers = dict(_API_HEADERS)
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
        try:
            resp = requests.request(method, url, data=body, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return _parse_json_response(resp)
        except requests.exceptions.HTTPError as e:
            last_exc = e
            status = e.response.status_code if e.response is not None else None
            err_body = e.response.text[:500] if e.response and e.response.text else None
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
                    if e.response and "Retry-After" in e.response.headers:
                        try:
                            delay = float(e.response.headers["Retry-After"])
                        except (ValueError, TypeError):
                            pass
                    # Exponential backoff for 429: 3s, 5s, 8s, 12s...
                    else:
                        delay = backoff_seconds + attempt * 2.0
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
            if attempt < max_retries:
                logger.warning("API %s %s connection/timeout (attempt %s), retrying in %.1fs", method, path, attempt + 1, backoff_seconds)
                time.sleep(backoff_seconds)
                continue
            raise APIError(f"API {method} {path} failed: {e}", path=path) from e
    if last_exc:
        raise last_exc
    raise APIError(f"API {method} {path} failed", path=path)


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
    headers = dict(_API_HEADERS)
    headers["Content-Type"] = content_type
    try:
        resp = requests.post(url, data=body, headers=headers, timeout=timeout)
        resp.raise_for_status()
        # Some endpoints return empty body; avoid .json() on empty
        if resp.content:
            _parse_json_response(resp)
    except requests.exceptions.HTTPError as e:
        status = e.response.status_code if e.response is not None else None
        err_body = e.response.text[:500] if e.response and e.response.text else None
        raise APIError(f"API POST {path} failed: {e}", status_code=status, path=path, body=err_body) from e
