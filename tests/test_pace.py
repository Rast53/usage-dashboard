from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

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


class PaceMonthlyWindowTest(unittest.TestCase):
    def test_monthly_norm_from_calendar_month_including_31st_clamp(self) -> None:
        reset = datetime(2026, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
        start = datetime(2026, 2, 28, 12, 0, 0, tzinfo=timezone.utc)
        self.assertEqual(app.subtract_one_calendar_month(reset), start)
        self.assertEqual(
            app.subtract_one_calendar_month(
                datetime(2028, 3, 31, 12, 0, 0, tzinfo=timezone.utc)
            ),
            datetime(2028, 2, 29, 12, 0, 0, tzinfo=timezone.utc),
        )
        window_minutes = 31 * 24 * 60
        self.assertEqual(app.compute_monthly_window_minutes(_iso(reset)), window_minutes)
        now = start + timedelta(minutes=window_minutes / 2)
        self.assertEqual(app.compute_pace_norm_percent(reset, window_minutes, now), 50.0)

        payload = app.build_pace_payload(
            {
                "accounts": {
                    "commandcode-main": {
                        "probed_at": _iso(now),
                        "monthly": {
                            "used_percent": 50.0,
                            "next_reset_at": _iso(reset),
                            "kind": "monthly",
                        },
                    }
                }
            },
            now=now,
        )
        self.assertEqual(payload["no_window"], [])
        self.assertEqual(len(payload["accounts"]), 1)
        lane = payload["accounts"][0]["lanes"][0]
        self.assertEqual(lane["window"], "monthly")
        self.assertEqual(lane["window_minutes"], window_minutes)
        self.assertEqual(lane["norm_percent"], 50.0)
        self.assertEqual(lane["delta_pp"], 0.0)
        self.assertEqual(lane["pace"], "ok")
        self.assertEqual(lane["cooldown_minutes"], 0.0)

    def test_monthly_pace_boundaries_at_5_and_20_pp(self) -> None:
        reset = datetime(2026, 4, 30, 12, 0, 0, tzinfo=timezone.utc)
        window_minutes = app.compute_monthly_window_minutes(reset)
        self.assertIsNotNone(window_minutes)
        assert window_minutes is not None
        start = app.subtract_one_calendar_month(reset)
        now = start + timedelta(minutes=window_minutes / 2)
        self.assertEqual(app.compute_pace_norm_percent(reset, window_minutes, now), 50.0)

        def lane_for(used: float) -> dict:
            result = app.compute_pace_lane(
                "monthly",
                window_minutes,
                {"used_percent": used, "next_reset_at": _iso(reset)},
                now,
            )
            self.assertIsNotNone(result)
            assert result is not None
            return result

        ok = lane_for(55.0)
        self.assertEqual(ok["delta_pp"], 5.0)
        self.assertEqual(ok["pace"], "ok")
        self.assertEqual(ok["cooldown_minutes"], 0.0)

        warn_lo = lane_for(55.0001)
        self.assertEqual(warn_lo["pace"], "warn")
        self.assertGreater(warn_lo["cooldown_minutes"], 0.0)

        warn_hi = lane_for(70.0)
        self.assertEqual(warn_hi["delta_pp"], 20.0)
        self.assertEqual(warn_hi["pace"], "warn")
        self.assertEqual(
            warn_hi["cooldown_minutes"],
            round(20.0 * window_minutes / 100.0, 4),
        )

        danger = lane_for(70.0001)
        self.assertEqual(danger["pace"], "danger")

    def test_missing_monthly_block_absent_from_monthly_not_no_window(self) -> None:
        session_reset = _iso(NOW + timedelta(minutes=150))
        weekly_reset = _iso(NOW + timedelta(minutes=5040))
        payload = app.build_pace_payload(
            {
                "accounts": {
                    "kimi-main": {
                        "probed_at": _iso(NOW),
                        "session": {
                            "used_percent": 40.0,
                            "next_reset_at": session_reset,
                        },
                        "weekly": {
                            "used_percent": 12.0,
                            "next_reset_at": weekly_reset,
                        },
                    },
                    "zai-main": {
                        "probed_at": _iso(NOW),
                        "session": {
                            "used_percent": 40.0,
                            "next_reset_at": session_reset,
                        },
                        "monthly": {"next_reset_at": _iso(NOW + timedelta(days=20))},
                    },
                    "deepseek-main": {"probed_at": _iso(NOW), "balance": []},
                    "openrouter-main": {"probed_at": _iso(NOW), "remaining": 8.0},
                }
            },
            now=NOW,
        )
        providers = [row["provider"] for row in payload["accounts"]]
        self.assertEqual(providers, ["zai-main", "kimi-main"])
        for row in payload["accounts"]:
            windows = [lane["window"] for lane in row["lanes"]]
            self.assertNotIn("monthly", windows)
            self.assertIn("5h", windows)
        self.assertEqual(payload["no_window"], ["deepseek-main", "openrouter-main"])


class PaceMonthlyHtmlTest(unittest.TestCase):
    def test_index_has_monthly_plot_and_wraps_below_desktop(self) -> None:
        html = (Path(__file__).resolve().parents[1] / "static" / "index.html").read_text(
            encoding="utf-8"
        )
        self.assertIn("renderPaceColumn('месяц', 'monthly'", html)
        self.assertIn("renderPaceColumn('5-часовое окно', '5h'", html)
        self.assertIn("renderPaceColumn('неделя', 'weekly'", html)
        self.assertIn("repeat(auto-fit, minmax(240px, 1fr))", html)
        self.assertIn("@media (max-width: 699px)", html)
        self.assertIn(".pace-plots { grid-template-columns: 1fr; }", html)


if __name__ == "__main__":
    unittest.main()
