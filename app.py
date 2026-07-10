"""
Vercel Python entrypoint (WSGI).

Vercel looks for app.py / index.py with a top-level `app` (WSGI/ASGI)
or `handler` (BaseHTTPRequestHandler). Multiple files under api/*.py with
custom names are no longer enough on their own.

Routes:
  GET  /              health
  GET  /api/predict   prediction JSON; ?push=1 to Server酱
  GET  /api/cron      daily cron: predict + push
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


# ── load prediction engine ──────────────────────────────────

def _load_predict_module():
    import importlib.util

    name = "predict_sunset_mod"
    if name in sys.modules:
        return sys.modules[name]
    path = SCRIPTS / "predict-sunset.py"
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _parse_query(qs: str) -> dict[str, str]:
    raw = parse_qs(qs, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in raw.items()}


def _auth_header(environ: dict) -> str:
    return environ.get("HTTP_AUTHORIZATION") or environ.get("Authorization") or ""


def _user_agent(environ: dict) -> str:
    return (environ.get("HTTP_USER_AGENT") or "").lower()


def _check_bearer(environ: dict) -> tuple[bool, str | None]:
    secret = os.environ.get("CRON_SECRET", "").strip()
    if not secret:
        return True, None
    if _auth_header(environ) == f"Bearer {secret}":
        return True, None
    return False, "Unauthorized: missing or invalid Authorization Bearer token"


def _run_and_maybe_push(
    *,
    location: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    date_str: str | None = None,
    event_type: str = "sunset",
    push: bool = True,
) -> dict[str, Any]:
    mod = _load_predict_module()
    result = mod.run_prediction(
        location=location or os.environ.get("SUNSET_LOCATION") or None,
        lat=lat,
        lng=lng,
        date_str=date_str,
        event_type=event_type or "sunset",
    )
    if "error" in result:
        return {"ok": False, **result}

    out: dict[str, Any] = {
        "ok": True,
        "quality": result["quality"],
        "source": result["source"],
        "location": result["location"],
        "date": result["date"],
        "event_type": result["event_type"],
        "short_summary": result["short_summary"],
        "message": result["discord_message"],
        "serverchan_title": result["serverchan_title"],
    }

    if push:
        push_result = mod.send_serverchan(
            title=result["serverchan_title"],
            desp=result["serverchan_desp"],
            short=result["short_summary"],
        )
        out["pushed"] = "error" not in push_result
        out["serverchan"] = push_result
        if "error" in push_result:
            out["ok"] = False
            out["error"] = f"prediction ok, push failed: {push_result['error']}"
    else:
        out["pushed"] = False

    return out


def _json(status: int, payload: dict) -> tuple[int, list[tuple[str, str]], bytes]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(body))),
        ("Cache-Control", "no-store"),
    ]
    return status, headers, body


def _handle_health() -> tuple[int, list[tuple[str, str]], bytes]:
    return _json(
        200,
        {
            "ok": True,
            "service": "sunset-prediction",
            "endpoints": ["/api/predict", "/api/cron"],
        },
    )


def _handle_predict(environ: dict) -> tuple[int, list[tuple[str, str]], bytes]:
    q = _parse_query(environ.get("QUERY_STRING", ""))
    location = q.get("location") or os.environ.get("SUNSET_LOCATION") or None
    date_str = q.get("date") or None
    event_type = q.get("type") or "sunset"
    push = str(q.get("push", "0")).lower() in {"1", "true", "yes", "on"}

    lat = q.get("lat")
    lng = q.get("lng")
    lat_f = float(lat) if lat not in (None, "") else None
    lng_f = float(lng) if lng not in (None, "") else None

    if push:
        ok, err = _check_bearer(environ)
        if not ok:
            return _json(401, {"ok": False, "error": err})

    try:
        result = _run_and_maybe_push(
            location=location,
            lat=lat_f,
            lng=lng_f,
            date_str=date_str,
            event_type=event_type,
            push=push,
        )
    except Exception as e:
        return _json(500, {"ok": False, "error": str(e)})

    status = 200 if result.get("ok") else 502
    return _json(status, result)


def _handle_cron(environ: dict) -> tuple[int, list[tuple[str, str]], bytes]:
    secret = os.environ.get("CRON_SECRET", "").strip()
    if secret:
        ok, err = _check_bearer(environ)
        if not ok:
            return _json(401, {"ok": False, "error": err})
    elif "vercel-cron" not in _user_agent(environ):
        return _json(
            401,
            {
                "ok": False,
                "error": (
                    "Set CRON_SECRET and pass Authorization: Bearer <secret>, "
                    "or invoke via Vercel Cron"
                ),
            },
        )

    location = os.environ.get("SUNSET_LOCATION") or "杭州"
    event_type = os.environ.get("SUNSET_EVENT_TYPE") or "sunset"

    try:
        result = _run_and_maybe_push(
            location=location,
            event_type=event_type,
            push=True,
        )
    except Exception as e:
        return _json(500, {"ok": False, "error": str(e)})

    status = 200 if result.get("ok") else 502
    return _json(status, result)


def app(environ: dict, start_response: Callable) -> list[bytes]:
    """WSGI application — Vercel Python entrypoint."""
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "") or "/"

    if method not in {"GET", "POST", "HEAD"}:
        status, headers, body = _json(405, {"ok": False, "error": "Method not allowed"})
        start_response(f"{status} Method Not Allowed", headers)
        return [] if method == "HEAD" else [body]

    if path in {"/", ""}:
        status, headers, body = _handle_health()
    elif path.rstrip("/") == "/api/predict":
        status, headers, body = _handle_predict(environ)
    elif path.rstrip("/") == "/api/cron":
        status, headers, body = _handle_cron(environ)
    else:
        status, headers, body = _json(
            404,
            {
                "ok": False,
                "error": "Not found",
                "path": path,
                "endpoints": ["/", "/api/predict", "/api/cron"],
            },
        )

    reason = {
        200: "OK",
        401: "Unauthorized",
        404: "Not Found",
        405: "Method Not Allowed",
        500: "Internal Server Error",
        502: "Bad Gateway",
    }.get(status, "OK")
    start_response(f"{status} {reason}", headers)
    return [] if method == "HEAD" else [body]
