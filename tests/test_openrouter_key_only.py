from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]
SECRET = "placeholder-key-1"
MGMT = "placeholder-key-2"


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_without(*names: str) -> dict[str, str]:
    return {k: v for k, v in app.os.environ.items() if k not in names}


def _key_payload() -> dict:
    return {
        "label": "alan-bot",
        "usage": 42.5,
        "usage_daily": 1.25,
        "usage_weekly": 6.5,
        "usage_monthly": 18.0,
        "limit": 50.0,
        "limit_remaining": 7.5,
        "is_free_tier": False,
    }


class OpenrouterKeyOnlyFlagTest(unittest.TestCase):
    def test_unset_and_blank_are_false(self) -> None:
        with patch.dict("os.environ", _env_without("OPENROUTER_KEY_ONLY"), clear=True):
            self.assertFalse(app.openrouter_key_only())
        with patch.dict("os.environ", {"OPENROUTER_KEY_ONLY": ""}, clear=False):
            self.assertFalse(app.openrouter_key_only())
        with patch.dict("os.environ", {"OPENROUTER_KEY_ONLY": "0"}, clear=False):
            self.assertFalse(app.openrouter_key_only())

    def test_truthy_values(self) -> None:
        for raw in ("1", "true", "YES", "on"):
            with patch.dict("os.environ", {"OPENROUTER_KEY_ONLY": raw}, clear=False):
                self.assertTrue(app.openrouter_key_only(), raw)


class ProbeOpenrouterKeyOnlyTest(unittest.TestCase):
    def test_key_only_calls_only_key_endpoint(self) -> None:
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            if url.endswith("/key"):
                return 200, {}, {"data": _key_payload()}, None
            raise AssertionError(f"unexpected url {url}")

        def boom_mgmt():
            raise AssertionError("management key must not be read in key-only mode")

        env = _env_without("OPENROUTER_KEY_ONLY", "OPENROUTER_MANAGEMENT_KEY")
        env.update({"OPENROUTER_KEY_ONLY": "1", "OPENROUTER_API_KEY": SECRET})
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "get_openrouter_api_key", return_value=SECRET):
                with patch.object(app, "get_openrouter_management_key", side_effect=boom_mgmt):
                    with patch.object(app, "http_json", side_effect=fake_http_json):
                        result = app.probe_openrouter_wallet()

        self.assertTrue(result["ok"])
        self.assertIsNone(result.get("error"))
        self.assertEqual(result["kind"], "openrouter-key")
        self.assertIsNone(result["total_credits"])
        self.assertIsNone(result["total_usage"])
        self.assertIsNone(result["remaining"])
        self.assertEqual(result["keys"], [])
        self.assertFalse(result["models"]["available"])
        self.assertEqual(result["key"]["label"], "alan-bot")
        self.assertEqual(result["key"]["usage"], 42.5)
        self.assertEqual(result["key"]["usage_daily"], 1.25)
        self.assertEqual(result["key"]["usage_weekly"], 6.5)
        self.assertEqual(result["key"]["usage_monthly"], 18.0)
        self.assertEqual(result["key"]["limit"], 50.0)
        self.assertEqual(result["key"]["limit_remaining"], 7.5)
        self.assertIn("−$1.25 сутки UTC", result["remaining_summary"])
        self.assertIn("−$6.50 неделя UTC (пн–вс)", result["remaining_summary"])
        self.assertIn("−$18.00 месяц UTC", result["remaining_summary"])
        self.assertNotIn("today (UTC, key)", result["remaining_summary"])
        self.assertNotIn("left", result["remaining_summary"])
        self.assertEqual(calls, [app.openrouter_api_url("/api/v1/key")])
        self.assertFalse(any("/credits" in u or "/keys" in u or "/activity" in u for u in calls))

    def test_key_only_error_does_not_fall_back_to_credits(self) -> None:
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            return None, {}, None, "<urlopen error timed out>"

        with patch.dict("os.environ", {"OPENROUTER_KEY_ONLY": "1"}, clear=False):
            with patch.object(app, "get_openrouter_api_key", return_value=SECRET):
                with patch.object(app, "http_json", side_effect=fake_http_json):
                    result = app.probe_openrouter_wallet()

        self.assertFalse(result["ok"])
        self.assertIn("key API", result["error"] or "")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/api/v1/key"))


class BuildOpenrouterKeyOnlyTest(unittest.TestCase):
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

    def test_builder_uses_key_usage_and_omits_account_fields(self) -> None:
        now = datetime.now(timezone.utc)
        baseline = now - timedelta(hours=25)
        self.snap.write_text(
            json.dumps({"ts": _iso(baseline), "wallets": {"openrouter": {"total_usage": 40.0}}})
            + "\n",
            encoding="utf-8",
        )
        app.invalidate_snapshot_cache()
        probe = {
            "provider": "openrouter",
            "email": "openrouter-main",
            "ok": True,
            "kind": "openrouter-key",
            "total_credits": 999.0,
            "total_usage": 888.0,
            "remaining": 111.0,
            "remaining_summary": "$111.00 left · used $888.00 / $999.00",
            "key": _key_payload(),
            "keys": [{"usage_daily": 9.9, "label": "should-ignore"}],
            "error": None,
            "probed_at": "2026-08-27T00:00:00Z",
            "models": app.models_unavailable("GET /api/v1/activity требует management key"),
        }
        with patch.dict("os.environ", {"OPENROUTER_KEY_ONLY": "1"}, clear=False):
            wallet = app.build_openrouter_wallet(probe)
        assert wallet is not None
        self.assertTrue(wallet["ok"])
        self.assertIsNone(wallet["total_credits"])
        self.assertIsNone(wallet["remaining"])
        self.assertEqual(wallet["total_usage"], 42.5)
        self.assertEqual(wallet["usage_daily"], 1.25)
        self.assertEqual(wallet["keys"], [])
        self.assertIsNone(wallet["usage_daily_all_keys"])
        self.assertEqual(wallet["spend_24h"]["spent"], 2.5)
        self.assertIn("−$1.25 сутки UTC", wallet["remaining_summary"])
        self.assertIn("−$6.50 неделя UTC (пн–вс)", wallet["remaining_summary"])
        self.assertIn("−$18.00 месяц UTC", wallet["remaining_summary"])
        self.assertNotIn("today (UTC, key)", wallet["remaining_summary"])
        self.assertNotIn("left", wallet["remaining_summary"])
        self.assertNotIn("999", wallet["remaining_summary"])
        self.assertNotIn("888", wallet["remaining_summary"])
        self.assertNotIn("111", wallet["remaining_summary"])
        self.assertEqual(wallet["source"], "openrouter-key-api+local-snapshots")
        self.assertFalse(wallet["models"]["available"])
        cal = wallet["spend_calendar"]
        self.assertEqual(cal["tz"], "Europe/Moscow")
        self.assertEqual(cal["total"]["spent"], 42.5)
        self.assertTrue(cal["yesterday"]["partial"] or cal["yesterday"]["spent"] is None)

    def test_default_builder_keeps_account_remaining(self) -> None:
        probe = {
            "ok": True,
            "total_credits": 10.0,
            "total_usage": 2.0,
            "remaining": 8.0,
            "remaining_summary": "$8.00 left · used $2.00 / $10.00",
            "key": {"usage": 1.0, "usage_daily": 0.4},
            "keys": [],
            "probed_at": "t",
        }
        env = _env_without("OPENROUTER_KEY_ONLY")
        with patch.dict("os.environ", env, clear=True):
            wallet = app.build_openrouter_wallet(probe)
        assert wallet is not None
        self.assertEqual(wallet["total_credits"], 10.0)
        self.assertEqual(wallet["total_usage"], 2.0)
        self.assertEqual(wallet["remaining"], 8.0)
        self.assertEqual(wallet["remaining_summary"], "$8.00 left · used $2.00 / $10.00")
        self.assertEqual(wallet["source"], "openrouter-credits-api+local-snapshots")


class SummaryKeyOnlySecretsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.patches = [
            patch.object(app, "DATA_DIR", self.dir),
            patch.object(app, "SNAPSHOT_PATH", self.dir / "snapshots.jsonl"),
            patch.object(app, "STATE_PATH", self.dir / "state.json"),
            patch.object(app, "QUOTA_CACHE_PATH", self.dir / "quota_cache.json"),
            patch.object(app, "STATIC_DIR", ROOT / "static"),
        ]
        for p in self.patches:
            p.start()
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
        self.tmp.cleanup()

    def test_summary_has_key_spend_no_account_balance_no_secrets(self) -> None:
        og = {
            "provider": "opencode-go",
            "email": "opencode-go-main",
            "ok": True,
            "kind": "opencode-go-quota",
            "status": "active",
            "plan_label": "Go",
            "session": {"remaining_percent": 80},
            "weekly": {"remaining_percent": 70},
            "monthly": {"used_usd": 4.0, "remaining_percent": 75.0, "remaining_usd": 45.0},
            "remaining_summary": "Go · 75% left (month)",
            "error": None,
            "probed_at": "2026-08-27T00:00:00Z",
        }
        or_probe = {
            "provider": "openrouter",
            "email": "openrouter-main",
            "ok": True,
            "kind": "openrouter-key",
            "total_credits": None,
            "total_usage": None,
            "remaining": None,
            "key": _key_payload(),
            "keys": [],
            "error": None,
            "probed_at": "2026-08-27T00:00:00Z",
            "models": app.models_unavailable("GET /api/v1/activity требует management key"),
            "remaining_summary": "−$1.25 сутки UTC · −$6.50 неделя UTC (пн–вс) · −$18.00 месяц UTC",
        }
        env = _env_without("PROVIDERS", "SITE_TITLE", "OPENROUTER_KEY_ONLY")
        env.update({
            "PROVIDERS": "opencode-go,openrouter",
            "SITE_TITLE": "Подписки — Алан",
            "OPENROUTER_KEY_ONLY": "1",
            "OPENROUTER_API_KEY": SECRET,
            "OPENROUTER_MANAGEMENT_KEY": MGMT,
            "OPENCODE_GO_API_KEY": "placeholder-key-3",
        })
        with patch.object(app, "probe_deepseek_balance", side_effect=AssertionError("deepseek")):
            with patch.object(app, "probe_zai_quota", side_effect=AssertionError("zai")):
                with patch.object(app, "probe_commandcode_credits", side_effect=AssertionError("cc")):
                    with patch.object(app, "probe_kimi_usage", side_effect=AssertionError("kimi")):
                        with patch.object(app, "probe_opencode_go_usage", return_value=og):
                            with patch.object(app, "probe_openrouter_wallet", return_value=or_probe):
                                with patch.dict("os.environ", env, clear=True):
                                    state = app.collect_state(force_quota=True)
                                    app._state = state
                                    payload = app.summary()
                                    html = app.index().body.decode("utf-8")

        self.assertEqual(payload["enabled_providers"], ["opencode-go", "openrouter"])
        self.assertEqual(set(payload["wallets"]), {"opencode-go", "openrouter"})
        wallet = payload["wallets"]["openrouter"]
        self.assertTrue(wallet["ok"])
        self.assertIsNone(wallet["total_credits"])
        self.assertIsNone(wallet["remaining"])
        self.assertEqual(wallet["total_usage"], 42.5)
        self.assertEqual(wallet["usage_daily"], 1.25)
        self.assertIn("сутки UTC", wallet["remaining_summary"])
        self.assertEqual(payload["display_tz"], "Europe/Moscow")
        self.assertEqual(payload["display_tz_label"], "МСК")
        self.assertTrue(payload["hide_partial_spend_chips"])
        self.assertTrue(payload["openrouter_key_only"])
        cal = wallet["spend_calendar"]
        self.assertEqual(cal["tz_label"], "МСК")
        self.assertEqual(cal["total"]["spent"], 42.5)
        self.assertIn("МСК", cal["note"])
        blob = json.dumps(payload)
        self.assertNotIn(SECRET, blob)
        self.assertNotIn(MGMT, blob)
        self.assertNotRegex(blob, r"sk-[a-zA-Z0-9]{8,}")
        self.assertIn("Подписки — Алан", html)
        self.assertNotIn(SECRET, html)


if __name__ == "__main__":
    unittest.main()
