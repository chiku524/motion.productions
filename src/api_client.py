"""
HTTP client for API calls. Uses requests + browser-like headers so Cloudflare
WAF/Bot Fight Mode does not block server-side automation.
"""
import json

import requests

_API_HEADERS = {
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": "Mozilla/5.0 (compatible; Motion-Productions/1.0; +https://motion.productions)",
    "Origin": "https://motion.productions",
    "Referer": "https://motion.productions/",
}


def api_request(
    api_base: str,
    method: str,
    path: str,
    data: dict | None = None,
    raw_body: bytes | None = None,
    content_type: str | None = None,
    timeout: int = 60,
) -> dict:
    url = f"{api_base.rstrip('/')}{path}"
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

    resp = requests.request(method, url, data=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def api_get(api_base: str, path: str, timeout: int = 60) -> dict:
    return api_request(api_base, "GET", path, timeout=timeout)


def api_post(api_base: str, path: str, data: dict | None = None, raw_body: bytes | None = None, content_type: str | None = None, timeout: int = 60) -> dict:
    return api_request(api_base, "POST", path, data=data, raw_body=raw_body, content_type=content_type, timeout=timeout)


def api_post_binary(api_base: str, path: str, body: bytes, content_type: str = "application/octet-stream", timeout: int = 120) -> None:
    """POST raw bytes (e.g. video upload). Returns None; raises on error."""
    url = f"{api_base.rstrip('/')}{path}"
    headers = dict(_API_HEADERS)
    headers["Content-Type"] = content_type
    resp = requests.post(url, data=body, headers=headers, timeout=timeout)
    resp.raise_for_status()
