from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SpendSeries7dTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = Path(self.tmp.name) / "snapshots.jsonl"
        self.snap_patch = patch.object(app, "SNAPSHOT_PATH", self.snap)
        self.snap_patch.start()
        app.invalidate_snapshot_cache()

    def tearDown(self) -> None:
        self.snap_patch.stop()
        app.invalidate_snapshot_cache()
        self.tmp.cleanup()

    def _write(self, rows: list[dict]) -> None:
        self.snap.write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8",
        )
        app.invalidate_snapshot_cache()

    def test_daily_increase_series_skips_first_day_without_baseline(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        rows = []
        usage = 10.0
        for i in range(8):
            day = now.replace(hour=12, minute=0, second=0) - timedelta(days=7 - i)
            rows.append({"ts": _iso(day), "wallets": {"openrouter": {"total_usage": usage}}})
            usage += 1.0
        self._write(rows)
        series = app.compute_openrouter_spend_series_7d(17.0, now=now)
        self.assertEqual(series["days"], 8)
        self.assertIsNone(series["gap"])
        dates = [p["date"] for p in series["points"]]
        self.assertEqual(dates[0], "2026-08-18")
        self.assertEqual(dates[-1], "2026-08-25")
        self.assertIsNone(series["points"][0]["spent"])
        self.assertTrue(series["points"][0]["partial"])
        for point in series["points"][1:-1]:
            self.assertEqual(point["spent"], 1.0)
            self.assertFalse(point["partial"])
        self.assertEqual(series["points"][-1]["spent"], 1.0)
        self.assertTrue(series["partial"])

    def test_no_history_gap_when_snapshots_missing(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        series = app.compute_openrouter_spend_series_7d(4.0, now=now)
        self.assertEqual(series["gap"], "no-history")
        self.assertTrue(series["partial"])
        self.assertEqual(series["points"], [])

    def test_missing_day_stays_null_not_zero(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(days=3, hours=6)),
                    "wallets": {"openrouter": {"total_usage": 2.0}},
                },
                {
                    "ts": _iso(now - timedelta(hours=6)),
                    "wallets": {"openrouter": {"total_usage": 5.0}},
                },
            ]
        )
        series = app.compute_openrouter_spend_series_7d(5.5, now=now)
        by_date = {p["date"]: p for p in series["points"]}
        self.assertIsNone(by_date["2026-08-23"]["spent"])
        self.assertTrue(by_date["2026-08-23"]["partial"])
        self.assertEqual(by_date["2026-08-25"]["spent"], 3.5)
        self.assertFalse(by_date["2026-08-25"]["partial"])

    def test_window_reset_nulls_spent(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(days=1, hours=6)),
                    "wallets": {"commandcode": {"monthly": {"remaining_usd": 20.0}}},
                }
            ]
        )
        series = app.compute_commandcode_spend_series_7d(
            {"monthly": {"remaining_usd": 70.0}},
            now=now,
        )
        today = next(p for p in series["points"] if p["date"] == "2026-08-25")
        self.assertIsNone(today["spent"])
        self.assertEqual(today["gap"], "window-reset")
        self.assertTrue(today["partial"])

    def test_deepseek_uses_cny_scalar(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(days=1, hours=6)),
                    "wallets": {
                        "deepseek": {
                            "balance": [{"currency": "CNY", "total_balance": "30.0"}]
                        }
                    },
                }
            ]
        )
        series = app.compute_deepseek_spend_series_7d(
            [{"currency": "CNY", "total_balance": "25.0"}],
            now=now,
        )
        self.assertEqual(series["unit"], "¥")
        today = next(p for p in series["points"] if p["date"] == "2026-08-25")
        self.assertEqual(today["spent"], 5.0)

    def test_partial_in_day_delta_without_pre_baseline(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now.replace(hour=8, minute=0, second=0)),
                    "wallets": {"kimi": {"weekly": {"used": 10}}},
                },
                {
                    "ts": _iso(now.replace(hour=12, minute=0, second=0)),
                    "wallets": {"kimi": {"weekly": {"used": 14}}},
                },
            ]
        )
        series = app.compute_kimi_spend_series_7d({"weekly": {"used": 16}}, now=now)
        today = next(p for p in series["points"] if p["date"] == "2026-08-25")
        self.assertEqual(today["spent"], 6.0)
        self.assertTrue(today["partial"])
        self.assertTrue(series["partial"])


class SpendSeriesOnWalletsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            patch.object(app, "DATA_DIR", self.dir),
            patch.object(app, "SNAPSHOT_PATH", self.dir / "snapshots.jsonl"),
            patch.object(app, "STATE_PATH", self.dir / "state.json"),
            patch.object(app, "QUOTA_CACHE_PATH", self.dir / "quota_cache.json"),
        ]
        for p in self.patches:
            p.start()
        app.invalidate_snapshot_cache()
        app._quota_cache = {"updated_at": None, "accounts": {}}
        app._state = {
            "updated_at": None,
            "providers": {},
            "accounts": [],
            "wallets": {},
            "errors": [],
        }

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        app.invalidate_snapshot_cache()
        self.tmp.cleanup()

    def test_collect_state_exposes_spend_series_on_all_wallets(self) -> None:
        probes = {
            "ds": {
                "provider": "deepseek",
                "email": "deepseek-main",
                "ok": True,
                "kind": "deepseek-balance",
                "balance": [{"currency": "CNY", "total_balance": "12.5"}],
                "is_available": True,
                "error": None,
                "probed_at": "2026-08-25T00:00:00Z",
                "remaining_summary": "CNY 12.5",
            },
            "or": {
                "provider": "openrouter",
                "email": "openrouter-main",
                "ok": True,
                "kind": "openrouter-credits",
                "total_credits": 10.0,
                "total_usage": 2.0,
                "remaining": 8.0,
                "remaining_summary": "$8.00 left",
                "key": {},
                "keys": [],
                "error": None,
                "probed_at": "2026-08-25T00:00:00Z",
                "models": {"available": False, "reason": app.NO_MODEL_BREAKDOWN, "items": []},
            },
            "zai": {
                "provider": "zai",
                "email": "zai-main",
                "ok": True,
                "kind": "zai-coding-quota",
                "level": "pro",
                "session": {"remaining_percent": 80},
                "weekly": {"remaining_percent": 90, "currentValue": 10},
                "mcp": {},
                "limits": [],
                "error": None,
                "probed_at": "2026-08-25T00:00:00Z",
                "remaining_summary": "plan pro",
            },
            "cc": {
                "provider": "commandcode",
                "email": "commandcode-main",
                "ok": True,
                "kind": "commandcode-credits",
                "status": "active",
                "plan_label": "GOAT",
                "monthly_credits": 62.1,
                "monthly": {"remaining_usd": 62.1, "cap": 70},
                "session": {},
                "weekly": {},
                "error": None,
                "probed_at": "2026-08-25T00:00:00Z",
                "remaining_summary": "GOAT",
            },
            "kimi": {
                "provider": "kimi",
                "email": "kimi-main",
                "ok": True,
                "kind": "kimi-coding-quota",
                "status": "active",
                "plan_label": "Moderato",
                "session": {},
                "weekly": {"used": 10, "cap": 2048},
                "error": None,
                "probed_at": "2026-08-25T00:00:00Z",
                "remaining_summary": "Moderato",
            },
            "og": {
                "provider": "opencode-go",
                "email": "opencode-go-main",
                "ok": True,
                "kind": "opencode-go-quota",
                "status": "active",
                "plan_label": "Go",
                "session": {},
                "weekly": {},
                "monthly": {"used_usd": 4.0, "remaining_percent": 75.0},
                "error": None,
                "probed_at": "2026-08-25T00:00:00Z",
                "remaining_summary": "Go",
            },
        }
        with patch.object(app, "probe_deepseek_balance", return_value=probes["ds"]):
            with patch.object(app, "probe_openrouter_wallet", return_value=probes["or"]):
                with patch.object(app, "probe_zai_quota", return_value=probes["zai"]):
                    with patch.object(app, "probe_commandcode_credits", return_value=probes["cc"]):
                        with patch.object(app, "probe_kimi_usage", return_value=probes["kimi"]):
                            with patch.object(app, "probe_opencode_go_usage", return_value=probes["og"]):
                                state = app.collect_state(force_quota=True)
        wallets = state["wallets"]
        for key in ("deepseek", "openrouter", "zai", "commandcode", "kimi", "opencode-go"):
            self.assertIn("spend_series_7d", wallets[key], key)
            series = wallets[key]["spend_series_7d"]
            self.assertIn("partial", series)
            self.assertIn("points", series)
            self.assertIn("gap", series)


if __name__ == "__main__":
    unittest.main()
