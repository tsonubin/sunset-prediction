"""Shared helpers for Vercel Python functions."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"

if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))


def load_predict_module():
    """Load scripts/predict-sunset.py (hyphenated filename) as a module."""
    path = SCRIPTS / "predict-sunset.py"
    name = "predict_sunset_mod"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load prediction module from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def parse_query(path_or_qs: str) -> dict[str, str]:
    """Parse query string from a path (?a=1) or raw qs (a=1)."""
    qs = path_or_qs
    if "?" in path_or_qs:
        qs = path_or_qs.split("?", 1)[1]
    raw = parse_qs(qs, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in raw.items()}


def env_bool(name: str, default: bool = False) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


def check_cron_auth(headers) -> tuple[bool, str | None]:
    """
    Validate cron/manual auth.

    - If CRON_SECRET is set, require Authorization: Bearer <secret>
    - Otherwise allow (useful for open predict endpoint); cron.py still prefers secret
    """
    secret = os.environ.get("CRON_SECRET", "").strip()
    if not secret:
        return True, None
    auth = ""
    if headers:
        # BaseHTTPRequestHandler headers are case-insensitive
        auth = headers.get("Authorization") or headers.get("authorization") or ""
    if auth == f"Bearer {secret}":
        return True, None
    return False, "Unauthorized: missing or invalid Authorization Bearer token"


def run_and_maybe_push(
    *,
    location: str | None = None,
    lat: float | None = None,
    lng: float | None = None,
    date_str: str | None = None,
    event_type: str = "sunset",
    push: bool = True,
) -> dict[str, Any]:
    """Run prediction and optionally push via ServerChan."""
    mod = load_predict_module()
    result = mod.run_prediction(
        location=location or os.environ.get("SUNSET_LOCATION") or None,
        lat=lat,
        lng=lng,
        date_str=date_str,
        event_type=event_type or "sunset",
    )
    if "error" in result:
        return result

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
