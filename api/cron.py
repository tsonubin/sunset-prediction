"""
Vercel Cron endpoint: GET /api/cron

Runs daily sunset prediction for SUNSET_LOCATION and pushes via Server酱.

Security:
  - Prefer setting CRON_SECRET in Vercel env; Vercel Cron sends
    Authorization: Bearer <CRON_SECRET> on paid plans / when configured.
  - Also accepts x-vercel-cron requests without secret if CRON_SECRET is empty
    (not recommended for public deploys).

Schedule is defined in vercel.json (default: 08:00 UTC = 16:00 Asia/Shanghai).
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from pathlib import Path

_API_DIR = Path(__file__).resolve().parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

from _lib import check_cron_auth, run_and_maybe_push  # noqa: E402


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _is_vercel_cron(headers) -> bool:
    ua = (headers.get("User-Agent") or headers.get("user-agent") or "").lower()
    return "vercel-cron" in ua


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        secret = os.environ.get("CRON_SECRET", "").strip()
        if secret:
            ok, err = check_cron_auth(self.headers)
            if not ok:
                _json_response(self, 401, {"ok": False, "error": err})
                return
        elif not _is_vercel_cron(self.headers):
            # No secret configured: only allow Vercel Cron UA to reduce abuse
            # Manual test: set CRON_SECRET or call with User-Agent vercel-cron/1.0
            _json_response(
                self,
                401,
                {
                    "ok": False,
                    "error": (
                        "Set CRON_SECRET and pass Authorization: Bearer <secret>, "
                        "or invoke via Vercel Cron"
                    ),
                },
            )
            return

        location = os.environ.get("SUNSET_LOCATION") or "杭州"
        event_type = os.environ.get("SUNSET_EVENT_TYPE") or "sunset"

        try:
            result = run_and_maybe_push(
                location=location,
                event_type=event_type,
                push=True,
            )
        except Exception as e:
            _json_response(self, 500, {"ok": False, "error": str(e)})
            return

        status = 200 if result.get("ok") else 502
        _json_response(self, status, result)

    def do_POST(self):
        self.do_GET()

    def log_message(self, format, *args):  # noqa: A003
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))
