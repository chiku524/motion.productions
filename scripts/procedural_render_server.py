#!/usr/bin/env python3
"""
HTTP render service for Video AI engine=procedural.

POST /render  JSON { prompt, duration_seconds?, width?, height?, fps?, seed? }
  → video/mp4 bytes

GET /health → {"ok":true,"service":"procedural-render"}

Auth: when MOTION_API_SECRET / API_SECRET is set, require
  Authorization: Bearer <secret> or X-Motion-Api-Key: <secret>.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from src.config import load_config
from src.pipeline import generate_full_video
from src.procedural import ProceduralVideoGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def _secret() -> str:
    return (os.environ.get("MOTION_API_SECRET") or os.environ.get("API_SECRET") or "").strip()


def _authorized(handler: BaseHTTPRequestHandler) -> bool:
    secret = _secret()
    if not secret:
        return True
    auth = handler.headers.get("Authorization") or ""
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    key = (handler.headers.get("X-Motion-Api-Key") or "").strip()
    return bearer == secret or key == secret


class ProceduralRenderHandler(BaseHTTPRequestHandler):
    server_version = "MotionProceduralRender/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        logger.info("%s - %s", self.address_string(), fmt % args)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/health"):
            self._send_json(200, {"ok": True, "service": "procedural-render"})
            return
        self._send_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/render":
            self._send_json(404, {"error": "Not found"})
            return
        if not _authorized(self):
            self._send_json(401, {"error": "Unauthorized"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"error": "Invalid JSON"})
            return
        if not isinstance(body, dict):
            self._send_json(400, {"error": "Expected JSON object"})
            return

        prompt = str(body.get("prompt") or "").strip()
        if not prompt:
            # Allow nested recipe.meta.prompt for Worker proxy convenience
            recipe = body.get("recipe") if isinstance(body.get("recipe"), dict) else None
            meta = recipe.get("meta") if recipe and isinstance(recipe.get("meta"), dict) else {}
            prompt = str(meta.get("prompt") or body.get("title") or "").strip()
        if not prompt:
            self._send_json(400, {"error": "Missing prompt"})
            return

        duration = float(body.get("duration_seconds") or body.get("durationSec") or 6)
        duration = max(0.5, min(duration, 60.0))
        seed = body.get("seed")
        try:
            seed_i = int(seed) if seed is not None else None
        except (TypeError, ValueError):
            seed_i = None

        config = load_config(None)
        if body.get("width"):
            config.setdefault("output", {})["width"] = int(body["width"])
        if body.get("height"):
            config.setdefault("output", {})["height"] = int(body["height"])
        if body.get("fps"):
            config.setdefault("output", {})["fps"] = int(body["fps"])

        generator = ProceduralVideoGenerator(config=config)
        try:
            with tempfile.TemporaryDirectory(prefix="motion-proc-") as tmp:
                out_path = Path(tmp) / "out.mp4"
                path_out = generate_full_video(
                    prompt,
                    duration,
                    generator=generator,
                    output_path=out_path,
                    config=config,
                    seed=seed_i,
                )
                data = Path(path_out).read_bytes()
        except Exception as e:
            logger.exception("render failed")
            self._send_json(500, {"error": str(e)[:500]})
            return

        self.send_response(200)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    port = int(os.environ.get("PORT") or os.environ.get("HEALTH_PORT") or "8080")
    server = ThreadingHTTPServer(("0.0.0.0", port), ProceduralRenderHandler)
    logger.info("procedural render listening on 0.0.0.0:%s", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
