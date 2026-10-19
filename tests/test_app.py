"""WSGI boundary tests for app.py (F4 in docs/AUDIT-2026-10-19.md)."""

from __future__ import annotations

import json
import unittest

import app as app_mod


def _get(path, query):
    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
    }
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


if __name__ == "__main__":
    unittest.main()
