from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


GOAT_CREDITS = {
    "credits": {
        "belowThreshold": False,
        "monthlyCredits": 62.1,
        "purchasedCredits": 1.5,
        "premiumMonthlyCredits": 0,
        "opensourceMonthlyCredits": 62.1,
    },
    "windowLimits": {
        "limited": True,
        "exceeded": None,
        "fiveHour": {"used": 2.0, "cap": 14, "exceeded": False, "resetAt": 1787700000000},
        "weekly": {"used": 7.9, "cap": 35, "exceeded": False, "resetAt": 1788000000000},
    },
}

GOAT_SUB = {
    "success": True,
    "data": {
        "id": "sub_test",
        "status": "active",
        "planId": "individual-goat",
        "currentPeriodEnd": "2026-09-18T00:00:00.000Z",
    },
}


class CommandCodeHelpersTest(unittest.TestCase):
    def test_default_proxy_and_key_are_none(self) -> None:
        drop = {"COMMANDCODE_PROXY", "COMMANDCODE_API_KEY", "COMMAND_CODE_API_KEY"}
        env = {k: v for k, v in app.os.environ.items() if k not in drop}
        with patch.dict("os.environ", env, clear=True):
            self.assertIsNone(app.get_commandcode_proxy())
            self.assertIsNone(app.get_commandcode_api_key())

    def test_key_aliases_and_proxy(self) -> None:
        with patch.dict(
            "os.environ",
            {"COMMAND_CODE_API_KEY": "sk-commandcode-testkey", "COMMANDCODE_PROXY": "  "},
            clear=False,
        ):
            self.assertEqual(app.get_commandcode_api_key(), "sk-commandcode-testkey")
            self.assertIsNone(app.get_commandcode_proxy())
        with patch.dict(
            "os.environ",
            {
                "COMMANDCODE_API_KEY": "sk-cc-primary-keyxx",
                "COMMANDCODE_PROXY": "http://user:s3cret@10.0.0.1:3128",
            },
            clear=False,
        ):
            self.assertEqual(app.get_commandcode_api_key(), "sk-cc-primary-keyxx")
            self.assertEqual(
                app.get_commandcode_proxy(), "http://user:s3cret@10.0.0.1:3128"
            )


class ProbeCommandCodeCreditsTest(unittest.TestCase):
    def test_missing_key_is_manual_without_http(self) -> None:
        calls: list[str] = []

        def boom(*_a, **_k):
            calls.append("http")
            raise AssertionError("must not call API without a key")

        env = {
            k: v
            for k, v in app.os.environ.items()
            if k not in {"COMMANDCODE_API_KEY", "COMMAND_CODE_API_KEY"}
        }
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "http_json", side_effect=boom):
                result = app.probe_commandcode_credits()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["error"], "COMMANDCODE_API_KEY not set")
        self.assertEqual(calls, [])
        wallet = app.build_commandcode_wallet(result)
        self.assertEqual(wallet["status"], "manual")
        self.assertFalse(wallet["ok"])

    def test_live_goat_windows_and_redacted_proxy(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append({"url": url, "token": token, "proxy": proxy, "timeout": timeout})
            if url.endswith("/alpha/billing/credits"):
                return 200, {}, GOAT_CREDITS, None
            if url.endswith("/alpha/billing/subscriptions"):
                return 200, {}, GOAT_SUB, None
            return 404, {}, None, "unexpected"

        with patch.dict(
            "os.environ",
            {
                "COMMANDCODE_API_KEY": "sk-cc-testkey-xxxxxxxxxx",
                "COMMANDCODE_PROXY": "http://user:s3cret@10.0.0.1:3128",
            },
            clear=False,
        ):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_commandcode_credits()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["plan_id"], "individual-goat")
        self.assertEqual(result["plan_label"], "GOAT")
        self.assertEqual(result["monthly_allowance"], 70.0)
        self.assertAlmostEqual(result["monthly_credits"], 62.1)
        self.assertEqual(result["session"]["cap"], 14.0)
        self.assertAlmostEqual(result["session"]["remaining_percent"], 85.71, places=1)
        self.assertEqual(result["weekly"]["cap"], 35.0)
        self.assertIsNotNone(result["monthly"]["remaining_percent"])
        self.assertEqual(result["via"]["proxy"], "http://10.0.0.1:3128")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["url"], "https://api.commandcode.ai/alpha/billing/credits")
        self.assertEqual(calls[1]["url"], "https://api.commandcode.ai/alpha/billing/subscriptions")
        self.assertEqual(calls[0]["proxy"], "http://user:s3cret@10.0.0.1:3128")
        wallet = app.build_commandcode_wallet(result)
        self.assertTrue(wallet["ok"])
        self.assertEqual(wallet["plan_label"], "GOAT")
        self.assertNotIn("s3cret", str(wallet.get("via")))

    def test_credits_error_does_not_call_subscription(self) -> None:
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            return 401, {}, {
                "success": False,
                "error": {"code": "UNAUTHORIZED", "message": "Invalid 'Authorization' header or token."},
            }, None

        with patch.object(app, "get_commandcode_api_key", return_value="sk-cc-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_commandcode_credits()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid 'Authorization' header or token.", result["error"] or "")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/alpha/billing/credits"))

    def test_unknown_caps_are_money_only_monthly(self) -> None:
        payload = {
            "credits": {"monthlyCredits": 12.0, "purchasedCredits": 0},
            "windowLimits": {
                "fiveHour": {"used": 1, "cap": 99, "resetAt": 0},
                "weekly": {"used": 2, "cap": 199, "resetAt": 0},
            },
        }

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            if url.endswith("/credits"):
                return 200, {}, payload, None
            return 200, {}, {"success": True, "data": {"planId": "brand-new-tier"}}, None

        with patch.object(app, "get_commandcode_api_key", return_value="sk-cc-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_commandcode_credits()

        self.assertTrue(result["ok"])
        self.assertIsNone(result["monthly_allowance"])
        self.assertEqual(result["monthly"]["remaining_usd"], 12.0)
        self.assertIsNone(result["monthly"]["remaining_percent"])
        self.assertIsNone(result["session"]["next_reset_at"])

    def test_nested_and_snake_case_windows(self) -> None:
        payload = {
            "success": True,
            "data": {
                "credits": {
                    "monthly_credits": 9.0,
                    "purchased_credits": 0,
                    "window_limits": {
                        "five_hour": {"cap": "3", "used": "0.75", "reset_at": "1780200000"},
                        "weekly": {"cap": 6, "used": 1.5, "resetAt": 1_780_300_000_000},
                    },
                }
            },
        }

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            if url.endswith("/credits"):
                return 200, {}, payload, None
            return 200, {}, {"success": True, "data": {"planId": "individual-go"}}, None

        with patch.object(app, "get_commandcode_api_key", return_value="sk-cc-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_commandcode_credits()

        self.assertTrue(result["ok"])
        self.assertEqual(result["plan_label"], "Go")
        self.assertEqual(result["session"]["used_percent"], 25.0)
        self.assertEqual(result["weekly"]["used_percent"], 25.0)

    def test_probe_exception_does_not_drop_other_wallets(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)
        patches = [
            patch.object(app, "DATA_DIR", d),
            patch.object(app, "SNAPSHOT_PATH", d / "snapshots.jsonl"),
            patch.object(app, "STATE_PATH", d / "state.json"),
            patch.object(app, "QUOTA_CACHE_PATH", d / "quota_cache.json"),
        ]
        try:
            for p in patches:
                p.start()
            app._quota_cache = {"updated_at": None, "accounts": {}}
            with patch.object(
                app,
                "probe_deepseek_balance",
                return_value={
                    "ok": True,
                    "provider": "deepseek",
                    "balance": [],
                    "email": "deepseek-main",
                    "kind": "deepseek-balance",
                    "is_available": True,
                    "error": None,
                    "probed_at": "t",
                    "remaining_summary": "",
                },
            ):
                with patch.object(
                    app,
                    "probe_openrouter_wallet",
                    return_value={
                        "ok": True,
                        "provider": "openrouter",
                        "email": "openrouter-main",
                        "kind": "openrouter-credits",
                        "total_credits": 1,
                        "total_usage": 0,
                        "remaining": 1,
                        "remaining_summary": "",
                        "key": {},
                        "keys": [],
                        "error": None,
                        "probed_at": "t",
                    },
                ):
                    with patch.object(
                        app,
                        "probe_zai_quota",
                        return_value={
                            "ok": True,
                            "provider": "zai",
                            "email": "zai-main",
                            "kind": "zai-coding-quota",
                            "level": "pro",
                            "session": {},
                            "weekly": {},
                            "mcp": {},
                            "limits": [],
                            "error": None,
                            "probed_at": "t",
                            "remaining_summary": "",
                        },
                    ):
                        with patch.object(app, "probe_commandcode_credits", side_effect=RuntimeError("boom")):
                            state = app.collect_state(force_quota=True)
            self.assertIn("commandcode-credits-probe: boom", state["errors"])
            self.assertTrue(state["wallets"]["deepseek"]["ok"])
            self.assertTrue(state["wallets"]["openrouter"]["ok"])
            self.assertTrue(state["wallets"]["zai"]["ok"])
            self.assertNotIn("commandcode", state["wallets"])
        finally:
            for p in reversed(patches):
                p.stop()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
