from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

import app


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


NOW = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)


class PaceNormDeltaTest(unittest.TestCase):
    def test_used_vs_reset_yields_norm_delta_and_pace(self) -> None:
        reset = NOW + timedelta(minutes=150)
        norm = app.compute_pace_norm_percent(reset, 300, NOW)
        self.assertEqual(norm, 50.0)
        delta = 40.0 - norm
        self.assertEqual(delta, -10.0)
        self.assertEqual(app.classify_pace(delta), "ok")
        self.assertEqual(app.compute_pace_cooldown_minutes(delta, 300), 0.0)

        over = 60.0 - norm
        self.assertEqual(over, 10.0)
        self.assertEqual(app.classify_pace(over), "warn")
        self.assertEqual(app.compute_pace_cooldown_minutes(over, 300), 30.0)

        weekly_reset = NOW + timedelta(minutes=5040)
        weekly_norm = app.compute_pace_norm_percent(weekly_reset, 10080, NOW)
        self.assertEqual(weekly_norm, 50.0)

    def test_norm_clamped_to_0_and_100(self) -> None:
        future = NOW + timedelta(minutes=400)
        self.assertEqual(app.compute_pace_norm_percent(future, 300, NOW), 0.0)
        past = NOW - timedelta(minutes=1)
        self.assertEqual(app.compute_pace_norm_percent(past, 300, NOW), 100.0)

    def test_boundary_exactly_5pp_is_ok_with_zero_cooldown(self) -> None:
        self.assertEqual(app.classify_pace(5.0), "ok")
        self.assertEqual(app.compute_pace_cooldown_minutes(5.0, 300), 0.0)
        self.assertEqual(app.classify_pace(5.0001), "warn")
        self.assertGreater(app.compute_pace_cooldown_minutes(5.0001, 300), 0.0)

    def test_boundary_exactly_20pp_is_warn(self) -> None:
        self.assertEqual(app.classify_pace(20.0), "warn")
        self.assertEqual(app.compute_pace_cooldown_minutes(20.0, 300), 60.0)
        self.assertEqual(app.classify_pace(20.0001), "danger")


class PaceLaneSkipTest(unittest.TestCase):
    def test_missing_next_reset_at_skips_lane_and_lands_in_no_window(self) -> None:
        payload = app.build_pace_payload(
            {
                "accounts": {
                    "zai-main": {
                        "probed_at": _iso(NOW),
                        "session": {"used_percent": 40.0},
                        "weekly": {"used_percent": 10.0, "next_reset_at": None},
                    }
                }
            },
            now=NOW,
        )
        self.assertEqual(payload["accounts"], [])
        self.assertEqual(payload["no_window"], ["zai-main"])

    def test_missing_used_percent_skips_lane_and_lands_in_no_window(self) -> None:
        reset = _iso(NOW + timedelta(minutes=150))
        payload = app.build_pace_payload(
            {
                "accounts": {
                    "kimi-main": {
                        "probed_at": _iso(NOW),
                        "session": {"used_percent": None, "next_reset_at": reset},
                        "weekly": {"next_reset_at": reset},
                    }
                }
            },
            now=NOW,
        )
        self.assertEqual(payload["accounts"], [])
        self.assertEqual(payload["no_window"], ["kimi-main"])

    def test_partial_window_keeps_provider_out_of_no_window(self) -> None:
        reset = _iso(NOW + timedelta(minutes=150))
        payload = app.build_pace_payload(
            {
                "accounts": {
                    "commandcode-main": {
                        "probed_at": _iso(NOW),
                        "session": {"used_percent": 40.0, "next_reset_at": reset},
                        "weekly": {"used_percent": 12.0},
                    }
                }
            },
            now=NOW,
        )
        self.assertEqual(len(payload["accounts"]), 1)
        self.assertEqual(payload["accounts"][0]["provider"], "commandcode-main")
        self.assertEqual([lane["window"] for lane in payload["accounts"][0]["lanes"]], ["5h"])
        self.assertEqual(payload["no_window"], [])

    def test_balance_only_providers_are_no_window(self) -> None:
        payload = app.build_pace_payload(
            {
                "accounts": {
                    "deepseek-main": {"probed_at": _iso(NOW), "balance": []},
                    "openrouter-main": {"probed_at": _iso(NOW), "remaining": 8.0},
                    "zai-main": {
                        "probed_at": _iso(NOW),
                        "session": {
                            "used_percent": 40.0,
                            "next_reset_at": _iso(NOW + timedelta(minutes=150)),
                        },
                    },
                }
            },
            now=NOW,
        )
        providers = [row["provider"] for row in payload["accounts"]]
        self.assertEqual(providers, ["zai-main"])
        self.assertEqual(payload["no_window"], ["deepseek-main", "openrouter-main"])
        self.assertEqual(payload["server_now"], _iso(NOW))


class PaceStaleAgeTest(unittest.TestCase):
    def test_stale_probed_at_reflected_in_data_age_seconds(self) -> None:
        probed = NOW - timedelta(seconds=900)
        reset = NOW + timedelta(minutes=150)
        lane = app.compute_pace_lane(
            "5h",
            300,
            {"used_percent": 40.0, "next_reset_at": _iso(reset)},
            NOW,
            _iso(probed),
        )
        self.assertIsNotNone(lane)
        assert lane is not None
        self.assertEqual(lane["data_age_seconds"], 900)
        self.assertEqual(lane["used_percent"], 40.0)
        self.assertEqual(lane["norm_percent"], 50.0)
        self.assertEqual(lane["delta_pp"], -10.0)
        self.assertEqual(lane["pace"], "ok")
        self.assertEqual(lane["cooldown_minutes"], 0.0)
        self.assertEqual(lane["reset_at"], _iso(reset))
        self.assertEqual(lane["window_minutes"], 300)

        payload = app.build_pace_payload(
            {
                "accounts": {
                    "opencode-go-main": {
                        "probed_at": _iso(probed),
                        "weekly": {
                            "used_percent": 70.0,
                            "next_reset_at": _iso(NOW + timedelta(minutes=5040)),
                        },
                    }
                }
            },
            now=NOW,
        )
        lane = payload["accounts"][0]["lanes"][0]
        self.assertEqual(lane["data_age_seconds"], 900)
        self.assertEqual(lane["window"], "weekly")
        self.assertEqual(lane["pace"], "warn")
        self.assertEqual(lane["cooldown_minutes"], 20.0 * 10080 / 100)


if __name__ == "__main__":
    unittest.main()
