"""WSGI boundary tests for app.py (F4 in docs/AUDIT-2026-10-19.md)."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import app as app_mod


def _get(path, query, **environ_extra):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
    }
    environ.update(environ_extra)
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    body = b"".join(app_mod.app(environ, start_response))
    return captured["status"], json.loads(body)


class QueryInputTest(unittest.TestCase):
    def test_non_numeric_lat_is_a_400_not_a_crash(self):
        status, payload = _get("/api/predict", "lat=abc&lng=120.0")
        self.assertEqual(status, "400 Bad Request")
        self.assertFalse(payload["ok"])
        self.assertIn("lat", payload["error"])


class PushAuthTest(unittest.TestCase):
    """Push requires CRON_SECRET; no secret means no push, period."""

    def test_push_without_secret_is_401(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("CRON_SECRET", None)
            status, payload = _get("/api/predict", "location=杭州&push=1")
        self.assertEqual(status, "401 Unauthorized")
        self.assertIn("CRON_SECRET", payload["error"])

    def test_valid_bearer_passes_auth_gate(self):
        with mock.patch.dict(os.environ, {"CRON_SECRET": "s3cret"}):
            status, payload = _get(
                "/api/predict",
                "location=Atlantis&push=1",
                HTTP_AUTHORIZATION="Bearer s3cret",
            )
        # authorized → rejected later by input validation, not by auth
        self.assertEqual(status, "400 Bad Request")
        self.assertIn("unknown location", payload["error"])


if __name__ == "__main__":
    unittest.main()
