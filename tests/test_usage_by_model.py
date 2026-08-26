from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "snapshots_2026-07-10.jsonl"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class July10ForwardCompatTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = Path(self.tmp.name) / "snapshots.jsonl"
        self.snap.write_text(FIXTURE.read_text(encoding="utf-8"), encoding="utf-8")
        self.snap_patch = patch.object(app, "SNAPSHOT_PATH", self.snap)
        self.snap_patch.start()
        app.invalidate_snapshot_cache()

    def tearDown(self) -> None:
        self.snap_patch.stop()
        app.invalidate_snapshot_cache()
        self.tmp.cleanup()

    def test_fixture_is_real_july10_schema(self) -> None:
        text = FIXTURE.read_text(encoding="utf-8")
        self.assertIn("2026-07-10T08:12:03Z", text)
        rows = app.load_snapshot_rows()
        self.assertGreaterEqual(len(rows), 3)
        first = rows[0]
        self.assertIn("accounts", first)
        self.assertNotIn("wallets", first)
        self.assertEqual(first["accounts"][0]["provider"], "xai")
        self.assertIn("grok-4", first["accounts"][0]["models"])

    def test_parsers_do_not_raise_on_july10_rows(self) -> None:
        rows = app.load_snapshot_rows()
        for obj in rows:
            app._extract_deepseek_balance_from_snapshot(obj)
            app._extract_openrouter_usage_from_snapshot(obj)
            app._extract_zai_weekly_used(obj)
            app._extract_commandcode_monthly_remaining(obj)
            app._extract_kimi_weekly_used(obj)
            app._extract_opencode_monthly_used(obj)

        ds = app.compute_deepseek_spend_24h(
            [{"currency": "CNY", "total_balance": "110.0"}],
            window_hours=24,
        )
        self.assertIn("spent_summary", ds)
        self.assertEqual(ds["spent"].get("CNY"), 10.0)
        or_spend = app.compute_openrouter_spend_24h(14.0, window_hours=24)
        self.assertEqual(or_spend["spent"], round(14.0 - 13.1, 6))
        zai = app.compute_zai_spend(
            {"weekly": {"currentValue": 90000}},
            window_hours=24,
        )
        self.assertEqual(zai.get("spent"), 2000.0)
        self.assertFalse(zai.get("partial"))

    def test_xai_account_models_are_not_current_spend(self) -> None:
        rows = app.load_snapshot_rows()
        self.assertIsNone(app._extract_kimi_weekly_used(rows[0]))
        self.assertIsNone(app._extract_commandcode_monthly_remaining(rows[0]))
        self.assertIsNone(app._extract_openrouter_usage_from_snapshot(rows[0]))
        # DeepSeek appears only after wallets / quota.balance
        ts, bal = app._extract_deepseek_balance_from_snapshot(rows[0])
        self.assertIsNone(bal)

    def test_july10_wallet_rows_feed_spend_when_window_covers_them(self) -> None:
        spend = app.compute_deepseek_spend_24h(
            [{"currency": "CNY", "total_balance": "100.0"}],
            window_hours=24,
        )
        self.assertFalse(spend["partial"])
        self.assertEqual(spend["spent"].get("CNY"), 20.0)
        or_spend = app.compute_openrouter_spend_7d(20.0)
        self.assertFalse(or_spend["partial"])
        self.assertEqual(or_spend["spent"], round(20.0 - 13.1, 6))
        zai = app.compute_zai_spend({"weekly": {"currentValue": 100000}}, window_hours=24)
        self.assertFalse(zai["partial"])
        self.assertEqual(zai["spent"], 12000.0)
        self.assertEqual(zai["unit"], "tok")


class SpendWindowsTest(unittest.TestCase):
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

    def test_7d_uses_older_baseline_than_24h(self) -> None:
        now = datetime.now(timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(days=8)),
                    "wallets": {"openrouter": {"total_usage": 1.0}},
                },
                {
                    "ts": _iso(now - timedelta(hours=30)),
                    "wallets": {"openrouter": {"total_usage": 4.0}},
                },
            ]
        )
        h24 = app.compute_openrouter_spend_24h(6.0, window_hours=24)
        h7d = app.compute_openrouter_spend_7d(6.0)
        self.assertFalse(h24["partial"])
        self.assertFalse(h7d["partial"])
        self.assertEqual(h24["spent"], 2.0)
        self.assertEqual(h7d["spent"], 5.0)

    def test_partial_when_only_in_window_points(self) -> None:
        now = datetime.now(timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(hours=3)),
                    "wallets": {
                        "kimi": {"weekly": {"used": 10}},
                    },
                }
            ]
        )
        spend = app.compute_kimi_spend({"weekly": {"used": 18}}, window_hours=24)
        self.assertTrue(spend["partial"])
        self.assertEqual(spend["spent"], 8.0)
        self.assertIn("частичная история", spend["spent_summary"])

    def test_window_reset_marks_gap_not_negative_spend(self) -> None:
        now = datetime.now(timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(hours=26)),
                    "wallets": {"commandcode": {"monthly": {"remaining_usd": 20.0}}},
                }
            ]
        )
        spend = app.compute_commandcode_spend(
            {"monthly": {"remaining_usd": 70.0}},
            window_hours=24,
        )
        self.assertEqual(spend["gap"], "window-reset")
        self.assertIsNone(spend["spent"])
        self.assertIn("сброс окна", spend["spent_summary"])

    def test_opencode_go_used_usd_delta(self) -> None:
        now = datetime.now(timezone.utc)
        self._write(
            [
                {
                    "ts": _iso(now - timedelta(hours=30)),
                    "wallets": {"opencode-go": {"monthly": {"used_usd": 5.0}}},
                }
            ]
        )
        spend = app.compute_opencode_go_spend(
            {"monthly": {"used_usd": 8.5}},
            window_hours=24,
        )
        self.assertEqual(spend["spent"], 3.5)
        self.assertEqual(spend["unit"], "$")


class OpenRouterModelsTest(unittest.TestCase):
    def test_aggregate_by_model_for_24h_and_7d(self) -> None:
        now = datetime(2026, 8, 25, 18, 0, tzinfo=timezone.utc)
        items = [
            {
                "date": "2026-08-25",
                "model": "openai/gpt-4.1",
                "usage": 0.4,
                "requests": 2,
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "reasoning_tokens": 0,
            },
            {
                "date": "2026-08-24 00:00:00",  # реальный формат API
                "model": "openai/gpt-4.1",
                "usage": 0.1,
                "requests": 1,
                "prompt_tokens": 3,
                "completion_tokens": 1,
                "reasoning_tokens": 0,
            },
            {
                "date": "2026-08-20",
                "model": "anthropic/claude-sonnet-4",
                "usage": 2.0,
                "requests": 4,
                "prompt_tokens": 50,
                "completion_tokens": 20,
                "reasoning_tokens": 8,
            },
            {
                "date": "2026-07-01",
                "model": "old/model",
                "usage": 99.0,
                "requests": 1,
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "reasoning_tokens": 0,
            },
        ]
        models = app.aggregate_openrouter_models(items, now=now)
        self.assertTrue(models["available"])
        self.assertEqual(models["endpoint"], "/api/v1/activity")
        names_7d = [row["model"] for row in models["items"]]
        self.assertEqual(names_7d[0], "anthropic/claude-sonnet-4")
        self.assertIn("openai/gpt-4.1", names_7d)
        self.assertNotIn("old/model", names_7d)
        gpt = next(row for row in models["items"] if row["model"] == "openai/gpt-4.1")
        self.assertEqual(gpt["usage"], 0.5)
        self.assertEqual(gpt["requests"], 3)
        names_24h = [row["model"] for row in models["items_24h"]]
        self.assertEqual(names_24h, ["openai/gpt-4.1"])
        self.assertTrue(models["partial"])

    def test_probe_without_management_key_marks_no_breakdown(self) -> None:
        with patch.object(app, "get_openrouter_api_key", return_value=None):
            result = app.probe_openrouter_wallet()
        self.assertFalse(result["models"]["available"])
        self.assertEqual(result["models"]["reason"], app.NO_MODEL_BREAKDOWN)

    def test_probe_activity_with_management_key(self) -> None:
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            if url.endswith("/credits"):
                return 200, {}, {"data": {"total_credits": 10, "total_usage": 1}}, None
            if url.endswith("/key"):
                return 200, {}, {"data": {}}, None
            if url.endswith("/keys"):
                return 200, {}, {"data": []}, None
            if url.endswith("/activity"):
                today = datetime.now(timezone.utc).date().isoformat()
                return (
                    200,
                    {},
                    {
                        "data": [
                            {
                                "date": today,
                                "model": "openai/gpt-4.1",
                                "usage": 0.2,
                                "requests": 1,
                                "prompt_tokens": 4,
                                "completion_tokens": 2,
                                "reasoning_tokens": 0,
                            }
                        ]
                    },
                    None,
                )
            return 404, {}, None, "unexpected"

        with patch.object(app, "get_openrouter_api_key", return_value="sk-or-v1-testkey-xxxxxxxxxx"):
            with patch.object(app, "get_openrouter_management_key", return_value="sk-or-v1-mgmt-xxxxxxxxxx"):
                with patch.object(app, "http_json", side_effect=fake_http_json):
                    result = app.probe_openrouter_wallet()
        self.assertTrue(result["ok"])
        self.assertTrue(any(u.endswith("/activity") for u in calls))
        self.assertTrue(result["models"]["available"])
        self.assertEqual(result["models"]["items"][0]["model"], "openai/gpt-4.1")

    def test_activity_error_keeps_credits_ok(self) -> None:
        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            if url.endswith("/credits"):
                return 200, {}, {"data": {"total_credits": 10, "total_usage": 1}}, None
            if url.endswith("/key"):
                return 200, {}, {"data": {}}, None
            if url.endswith("/activity"):
                return 403, {}, {"error": {"message": "Only management keys can perform this operation"}}, None
            return 404, {}, None, "unexpected"

        with patch.object(app, "get_openrouter_api_key", return_value="sk-or-v1-testkey-xxxxxxxxxx"):
            with patch.object(app, "get_openrouter_management_key", return_value="sk-or-v1-mgmt-xxxxxxxxxx"):
                with patch.object(app, "http_json", side_effect=fake_http_json):
                    result = app.probe_openrouter_wallet()
        self.assertTrue(result["ok"])
        self.assertFalse(result["models"]["available"])
        self.assertEqual(result["models"]["reason"], app.NO_MODEL_BREAKDOWN)


class WalletPayloadModelsTest(unittest.TestCase):
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

    def test_collect_state_exposes_spend_windows_and_model_flags(self) -> None:
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
                "models": {
                    "available": True,
                    "endpoint": "/api/v1/activity",
                    "items": [{"model": "openai/gpt-4.1", "usage": 0.2, "requests": 1}],
                    "items_24h": [],
                    "partial": True,
                },
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
            self.assertIn("spend_24h", wallets[key], key)
            self.assertIn("spend_7d", wallets[key], key)
            self.assertIn("spend_series_7d", wallets[key], key)
            self.assertIn("models", wallets[key], key)
        self.assertTrue(wallets["openrouter"]["models"]["available"])
        self.assertEqual(
            wallets["deepseek"]["models"]["reason"], app.NO_MODEL_BREAKDOWN
        )
        self.assertEqual(wallets["zai"]["models"]["reason"], app.NO_MODEL_BREAKDOWN)
        self.assertEqual(wallets["commandcode"]["models"]["reason"], app.NO_MODEL_BREAKDOWN)
        self.assertEqual(wallets["kimi"]["models"]["reason"], app.NO_MODEL_BREAKDOWN)
        self.assertEqual(
            wallets["opencode-go"]["models"]["reason"], app.NO_MODEL_BREAKDOWN
        )
        self.assertNotIn("cpa", json.dumps(state).lower())


class UiCopyTest(unittest.TestCase):
    def test_index_has_gap_copy_and_spend_windows(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("нет разбивки от провайдера", html)
        self.assertIn("нет истории", html)
        self.assertIn("sparklineSvg", html)
        self.assertIn("allotmentBar", html)
        self.assertIn("По моделям", html)
        self.assertIn("fonts.googleapis.com", html)
        self.assertIn("family=Inter", html)
        self.assertNotRegex(html, r"<script[^>]+src=")
        self.assertIn("applySiteTitle", html)
        self.assertIn("sourceLabels", html)
        self.assertNotRegex(html, r"(?i)cpa|USAGE_PG_DSN|psycopg2")


if __name__ == "__main__":
    unittest.main()
