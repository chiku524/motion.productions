"""D1 regrowth prevention, client side: slim learning payload and cooldown on degraded 200 writes."""
from __future__ import annotations

import json
import unittest
from unittest import mock

import requests

from src import api_client


def _resp(status: int, body: dict) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = json.dumps(body).encode()
    r.headers["Content-Type"] = "application/json"
    r.url = "http://test.invalid/api"
    return r


class TestSlimLearningAnalysis(unittest.TestCase):
    def test_keeps_only_aggregated_scalars(self):
        big = {"motion_level": 0.123456, "mean_brightness": 0.5, "mean_contrast": 1, "motion_per_frame": [0.1] * 5000, "palette": {"x": "y" * 999}}
        out = api_client.slim_learning_analysis(big)
        self.assertEqual(out, {"motion_level": 0.123, "mean_brightness": 0.5, "mean_contrast": 1.0})
        self.assertLess(len(json.dumps(out)), 100)

    def test_tolerates_missing_and_bad_values(self):
        self.assertEqual(api_client.slim_learning_analysis(None), {})
        self.assertEqual(api_client.slim_learning_analysis({"motion_level": "high", "mean_contrast": True}), {})


class TestDegradedSuccessCooldown(unittest.TestCase):
    def setUp(self):
        api_client.reset_free_tier_cooldown()

    def tearDown(self):
        api_client.reset_free_tier_cooldown()

    def test_db_full_body_is_a_limit_body(self):
        self.assertTrue(api_client.is_free_tier_limit_body('{"error":"d1_db_full"}'))
        self.assertTrue(api_client.is_free_tier_limit_body("D1_ERROR: Exceeded maximum DB size"))

    def test_degraded_200_write_starts_cooldown_and_next_write_is_skipped(self):
        body = {"degraded": True, "error": "d1_db_full", "recorded": False, "retry_after_ms": 900000}
        with mock.patch("src.api_client.requests.request", return_value=_resp(200, body)) as req, mock.patch("src.api_client.time.sleep"):
            out = api_client.api_request("http://test.invalid", "POST", "/api/learning", data={"a": 1})
            self.assertEqual(out["recorded"], False)
            self.assertGreater(api_client.free_tier_cooldown_remaining(), 800)
            with self.assertRaises(api_client.APIError):
                api_client.api_request("http://test.invalid", "POST", "/api/learning", data={"a": 1})
        self.assertEqual(req.call_count, 1, "second write must not reach the Worker")

    def test_degraded_200_read_does_not_pause_writes(self):
        with mock.patch("src.api_client.requests.request", return_value=_resp(200, {"degraded": True, "error": "d1_db_full"})), mock.patch("src.api_client.time.sleep"):
            api_client.api_request("http://test.invalid", "GET", "/api/knowledge/for-creation")
        self.assertEqual(api_client.free_tier_cooldown_remaining(), 0.0)

    def test_normal_200_write_does_not_start_cooldown(self):
        with mock.patch("src.api_client.requests.request", return_value=_resp(201, {"id": "x"})), mock.patch("src.api_client.time.sleep"):
            api_client.api_request("http://test.invalid", "POST", "/api/learning", data={"a": 1})
        self.assertEqual(api_client.free_tier_cooldown_remaining(), 0.0)


if __name__ == "__main__":
    unittest.main()
