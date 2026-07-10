"""
Vercel serverless: GET/POST /api/predict

Query params:
  location  — city name (default: SUNSET_LOCATION or 杭州)
  lat, lng  — optional coordinates
  date      — YYYY-MM-DD
  type      — sunset | sunrise
  push      — 1/true to also Server酱 push (default: 0 for ad-hoc; cron uses push)

Auth (optional): if CRON_SECRET is set, require Authorization: Bearer <CRON_SECRET>
when push=1 (prevents strangers burning your SendKey quota).
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# Ensure project root helpers import
_API_DIR = Path(__file__).resolve().parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from _lib import check_cron_auth, env_bool, parse_query, run_and_maybe_push  # noqa: E402


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _handle(handler: BaseHTTPRequestHandler) -> None:
    parsed = urlparse(handler.path)
    q = parse_query(parsed.query)

    location = q.get("location") or os.environ.get("SUNSET_LOCATION") or None
    date_str = q.get("date") or None
    event_type = q.get("type") or "sunset"
    push = env_bool("FORCE_PUSH", False) or str(q.get("push", "0")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }

    lat = q.get("lat")
    lng = q.get("lng")
    lat_f = float(lat) if lat not in (None, "") else None
    lng_f = float(lng) if lng not in (None, "") else None

    if push:
        ok, err = check_cron_auth(handler.headers)
        # Only enforce when CRON_SECRET is configured
        if not ok:
            _json_response(handler, 401, {"ok": False, "error": err})
            return

    try:
        result = run_and_maybe_push(
            location=location,
            lat=lat_f,
            lng=lng_f,
            date_str=date_str,
            event_type=event_type,
            push=push,
        )
    except Exception as e:
        _json_response(handler, 500, {"ok": False, "error": str(e)})
        return

    status = 200 if result.get("ok", "error" not in result) else 502
    if "error" in result and not result.get("quality") and not result.get("ok"):
        status = 502
    _json_response(handler, status, result)


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        _handle(self)

    def do_POST(self):
        _handle(self)

    def log_message(self, format, *args):  # noqa: A003
        # Quieter logs on Vercel
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))
