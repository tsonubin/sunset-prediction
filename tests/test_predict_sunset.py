"""Targeted regression tests for the prediction engine (stdlib unittest, zero deps).

Each test owns one fixed contract from docs/AUDIT-2026-10-19.md at its
owning boundary: run_prediction (date handling), compute_sunset_quality
(sunrise sampling, zero values), resolve_location (input validation).
"""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

import app as app_mod

mod = app_mod._load_predict_module()

HOURLY_KEYS = (
    "cloud_cover_low",
    "cloud_cover_mid",
    "cloud_cover_high",
    "cloud_cover",
    "visibility",
    "relative_humidity_2m",
    "precipitation_probability",
)


def _meteo(dates, sunset_times, sunrise_times, hour_profile):
    """Build an Open-Meteo-shaped payload for the given local dates."""
    hourly = {"time": []}
    for k in HOURLY_KEYS:
        hourly[k] = []
    for d in dates:
        for h in range(24):
            hourly["time"].append(f"{d}T{h:02d}:00")
            vals = hour_profile(h)
            for k in HOURLY_KEYS:
                hourly[k].append(vals[k])
    daily = {
        "time": list(dates),
        "sunrise": [f"{d}T{t}" for d, t in zip(dates, sunrise_times)],
        "sunset": [f"{d}T{t}" for d, t in zip(dates, sunset_times)],
        "precipitation_probability_mean": [10] * len(dates),
    }
    return {"daily": daily, "hourly": hourly}


def _flat(**vals):
    return lambda h: dict(vals)


def _no_network():
    return mock.Mock(side_effect=AssertionError("engine must not be called"))


class DateWindowTest(unittest.TestCase):
    """F1: the requested date must select that date's forecast slice."""

    def setUp(self):
        self.today = datetime.now(mod.TZ_CST).date()
        self.dates = [
            (self.today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)
        ]

    def test_requested_date_uses_that_days_data(self):
        meteo = _meteo(
            self.dates,
            sunset_times=["17:30", "17:29", "17:28"],
            sunrise_times=["06:30", "06:31", "06:32"],
            hour_profile=_flat(
                cloud_cover_low=10,
                cloud_cover_mid=20,
                cloud_cover_high=50,
                cloud_cover=30,
                visibility=15000,
                relative_humidity_2m=55,
                precipitation_probability=10,
            ),
        )
        with mock.patch.object(mod, "predict_sunsethue", return_value=None), \
                mock.patch.object(mod, "fetch_openmeteo", return_value=meteo):
            result = mod.run_prediction(location="杭州", date_str=self.dates[2])

        self.assertEqual(result["date"], self.dates[2])
        self.assertIn("日落：17:28", result["discord_message"])
        self.assertNotIn("日落：17:29", result["discord_message"])

    def test_invalid_dates_rejected_before_any_engine_call(self):
        cases = [
            "not-a-date",
            (self.today - timedelta(days=1)).strftime("%Y-%m-%d"),
            (self.today + timedelta(days=3)).strftime("%Y-%m-%d"),
        ]
        for date_str in cases:
            with self.subTest(date=date_str), \
                    mock.patch.object(mod, "predict_sunsethue", _no_network()), \
                    mock.patch.object(mod, "fetch_openmeteo", _no_network()):
                with self.assertRaises(ValueError):
                    mod.run_prediction(location="杭州", date_str=date_str)


class SunriseSamplingTest(unittest.TestCase):
    """F2: sunrise quality must come from morning hours, not the sunset window."""

    def test_sunrise_scores_morning_data(self):
        def profile(h):
            if h <= 8:  # overcast morning
                return dict(cloud_cover_low=90, cloud_cover_mid=20,
                            cloud_cover_high=10, cloud_cover=90,
                            visibility=5000, relative_humidity_2m=80,
                            precipitation_probability=10)
            return dict(cloud_cover_low=5, cloud_cover_mid=5,
                        cloud_cover_high=5, cloud_cover=5,
                        visibility=20000, relative_humidity_2m=50,
                        precipitation_probability=10)

        today = datetime.now(mod.TZ_CST).date()
        dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
        meteo = _meteo(dates, ["17:30"] * 3, ["05:30"] * 3, profile)

        result = mod.compute_sunset_quality(meteo, day_index=0, event_type="sunrise")
        self.assertEqual(result["factors"]["cloud_type"], "overcast")


class ZeroValueTest(unittest.TestCase):
    """F3: a real 0 (clear-sky cloud cover) must survive into the output."""

    def test_zero_cloud_cover_is_not_dropped(self):
        today = datetime.now(mod.TZ_CST).date()
        dates = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(3)]
        meteo = _meteo(
            dates,
            ["17:30"] * 3,
            ["06:30"] * 3,
            _flat(
                cloud_cover_low=0,
                cloud_cover_mid=0,
                cloud_cover_high=0,
                cloud_cover=0,
                visibility=15000,
                relative_humidity_2m=60,
                precipitation_probability=0,
            ),
        )
        result = mod.compute_sunset_quality(meteo, day_index=0, event_type="sunset")
        self.assertEqual(result["cloud_cover_low"], 0)
        self.assertEqual(result["cloud_cover_mid"], 0)
        self.assertEqual(result["cloud_cover_high"], 0)
        self.assertEqual(result["total_cloud_cover"], 0)


class ResolveLocationTest(unittest.TestCase):
    """F6: explicit bad input fails loudly; the no-input default is unchanged."""

    def test_bad_inputs_rejected(self):
        cases = [
            (("Atlantis", None, None), "unknown location"),
            (("杭州", 30.27, None), "together"),
            ((None, 30.27, None), "together"),
            (("杭州", 91.0, 120.0), "out of range"),
            (("杭州", 30.27, 200.0), "out of range"),
        ]
        for args, msg in cases:
            with self.subTest(args=args):
                with self.assertRaises(ValueError) as ctx:
                    mod.resolve_location(*args)
                self.assertIn(msg, str(ctx.exception))

    def test_unknown_env_location_rejected(self):
        with mock.patch.dict(os.environ, {"SUNSET_LOCATION": "Nowhere"}):
            with self.assertRaises(ValueError):
                mod.resolve_location()

    def test_defaults_and_mapped_cities_unchanged(self):
        with mock.patch.dict(os.environ):
            os.environ.pop("SUNSET_LOCATION", None)
            self.assertEqual(mod.resolve_location(), (30.2741, 120.1551, "杭州"))
            self.assertEqual(mod.resolve_location("北京"), (39.9042, 116.4074, "北京"))
            self.assertEqual(
                mod.resolve_location(None, 22.5, 114.0), (22.5, 114.0, "(22.5,114.0)")
            )


if __name__ == "__main__":
    unittest.main()
