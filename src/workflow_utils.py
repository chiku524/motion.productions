"""
Workflow utilities: structured logging, health server, graceful shutdown.
"""
import json
import logging
import signal
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Any

logger = logging.getLogger(__name__)

_shutdown_requested = False


def request_shutdown() -> bool:
    """Check if shutdown was requested (e.g. SIGTERM)."""
    return _shutdown_requested


def _set_shutdown_requested(*_args: Any) -> None:
    global _shutdown_requested
    _shutdown_requested = True


def setup_graceful_shutdown() -> None:
    """Register SIGTERM/SIGINT handlers for graceful exit."""
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _set_shutdown_requested)
        except (AttributeError, ValueError):
            pass  # Windows or unsupported


def log_structured(level: str, **kwargs: Any) -> None:
    """Emit structured (JSON) log for Railway/monitoring."""
    record = {"level": level, **kwargs}
    line = json.dumps(record)
    if level == "error":
        logger.error("%s", line)
    elif level == "warning":
        logger.warning("%s", line)
    else:
        logger.info("%s", line)


def start_health_server(port: int = 8080) -> threading.Thread | None:
    """Start a minimal HTTP server for health checks (Railway). Daemon thread."""
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true,"service":"motion-loop"}')

        def log_message(self, *args: Any) -> None:
            pass

    try:
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return thread
    except OSError as e:
        logger.warning("Health server failed (port %s): %s", port, e)
        return None
