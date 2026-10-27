"""Free-tier client behaviour: limit cooldown (no retry storms), loop uploads off by default, fewer/larger chunks."""
from __future__ import annotations

import json
import unittest
from unittest import mock

import requests

from src import api_client
from src.api_client import APIError


def _resp(status: int, body: dict | str) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = (body if isinstance(body, str) else json.dumps(body)).encode()
    r.headers["Content-Type"] = "application/json"
    r.url = "http://test.invalid/api"
    return r


class TestFreeTierCooldown(unittest.TestCase):
    def setUp(self):
        api_client.reset_free_tier_cooldown()

    def tearDown(self):
        api_client.reset_free_tier_cooldown()

    def test_limit_body_detection(self):
        self.assertTrue(api_client.is_free_tier_limit_body('{"error":"free_tier_limit"}'))
        self.assertTrue(api_client.is_free_tier_limit_body("D1 DB exceeded its daily limit"))
        self.assertFalse(api_client.is_free_tier_limit_body("D1 exceeded CPU time limit (daily?)"))
        self.assertFalse(api_client.is_free_tier_limit_body("internal error"))
        self.assertFalse(api_client.is_free_tier_limit_body(None))

    def test_503_limit_is_not_retried_and_starts_cooldown(self):
        calls = []

        def fake(method, url, **kw):
            calls.append((method, url))
            return _resp(503, {"degraded": True, "error": "free_tier_limit", "retry_after_ms": 900000})

        with mock.patch("src.api_client.requests.request", side_effect=fake), mock.patch("src.api_client.time.sleep") as sleep:
            with self.assertRaises(APIError) as cm:
                api_client.api_request_with_retry("http://test.invalid", "POST", "/api/knowledge/discoveries", data={"a": 1}, max_retries=5)
        self.assertEqual(len(calls), 1, "a limit response must not be retried")
        self.assertEqual(cm.exception.status_code, 503)
        self.assertLessEqual(sleep.call_count, 1, 'only the pre-request jitter may sleep; no retry backoff')
        self.assertGreater(api_client.free_tier_cooldown_remaining(), 800)

    def test_writes_are_skipped_during_cooldown_reads_are_not(self):
        api_client.start_free_tier_cooldown(600)
        with mock.patch("src.api_client.requests.request") as req:
            with self.assertRaises(APIError) as cm:
                api_client.api_request("http://test.invalid", "POST", "/api/loop/state", data={})
            req.assert_not_called()
            self.assertIn("free_tier_limit", cm.exception.body or "")
            req.return_value = _resp(200, {"ok": True, "degraded": True})
            out = api_client.api_request("http://test.invalid", "GET", "/api/loop/status")
            req.assert_called_once()
            self.assertTrue(out["ok"])


class TestLoopUploadDefaultOff(unittest.TestCase):
    def setUp(self):
        api_client.reset_free_tier_cooldown()

    def test_default_calls_complete_without_reading_the_clip(self):
        with mock.patch.dict("os.environ", {}, clear=False) as env:
            env.pop("LOOP_UPLOAD_VIDEOS", None)
            with mock.patch("src.api_client.api_request_with_retry", return_value={"stored": False}) as call:
                out = api_client.finish_loop_job("http://x", "job1", "does-not-exist.mp4")
        self.assertFalse(out["stored"])
        self.assertEqual(call.call_args.args[2], "/api/jobs/job1/complete")
        self.assertNotIn("raw_body", call.call_args.kwargs)

    def test_opt_in_uploads_the_clip(self):
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"abc")
        with mock.patch.dict("os.environ", {"LOOP_UPLOAD_VIDEOS": "1"}):
            with mock.patch("src.api_client.api_request_with_retry", return_value={}) as call:
                api_client.finish_loop_job("http://x", "job2", f.name)
        self.assertEqual(call.call_args.args[2], "/api/jobs/job2/upload")
        self.assertEqual(call.call_args.kwargs["raw_body"], b"abc")


class TestChunking(unittest.TestCase):
    def test_a_typical_clip_is_one_or_two_posts(self):
        from src.knowledge.remote_sync import DISCOVERIES_MAX_ITEMS, _chunk_discoveries

        self.assertGreaterEqual(DISCOVERIES_MAX_ITEMS, 30)
        self.assertLessEqual(DISCOVERIES_MAX_ITEMS, 80)  # Worker hard cap
        payload = {
            "static_colors": [{"key": f"{i},0,0,1", "r": i, "g": 0, "b": 0} for i in range(20)],
            "learned_blends": [{"name": f"b{i}", "domain": "color", "inputs": {}, "output": {}} for i in range(10)],
            "motion": [{"key": f"m{i}", "motion_level": 0.1} for i in range(5)],
        }
        chunks = _chunk_discoveries(payload)
        self.assertLessEqual(len(chunks), 2)


if __name__ == "__main__":
    unittest.main()