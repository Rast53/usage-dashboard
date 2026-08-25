from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


GO_USAGE = {
    "usage": {
        "rolling": {
            "status": "ok",
            "percent": 19.5,
            "resetsAt": "2026-08-25T20:00:00.000Z",
        },
        "weekly": {
            "status": "ok",
            "percent": 29.7,
            "resetsAt": "2026-08-29T12:00:00.000Z",
        },
        "monthly": {
            "status": "ok",
            "percent": 25.0,
            "resetsAt": "2026-09-11T14:30:00.000Z",
        },
    }
}


class OpenCodeGoHelpersTest(unittest.TestCase):
    def test_default_proxy_and_key_are_none(self) -> None:
        drop = {
            "OPENCODE_GO_PROXY",
            "OPENCODE_PROXY",
            "OPENCODE_GO_API_KEY",
            "OPENCODE_API_KEY",
            "OPENCODE_GO_BASE_URL",
        }
        env = {k: v for k, v in app.os.environ.items() if k not in drop}
        with patch.dict("os.environ", env, clear=True):
            self.assertIsNone(app.get_opencode_go_proxy())
            self.assertIsNone(app.get_opencode_go_api_key())
            self.assertEqual(app.get_opencode_go_base_url(), "https://opencode.ai/zen/go/v1")
            self.assertEqual(app.opencode_go_usage_url(), "https://opencode.ai/zen/go/v1/usage")

    def test_key_aliases_proxy_and_base_url(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENCODE_API_KEY": "sk-opencode-testkey", "OPENCODE_GO_PROXY": "  "},
            clear=False,
        ):
            self.assertEqual(app.get_opencode_go_api_key(), "sk-opencode-testkey")
            self.assertIsNone(app.get_opencode_go_proxy())
        with patch.dict(
            "os.environ",
            {
                "OPENCODE_GO_API_KEY": "sk-og-primary-keyxx",
                "OPENCODE_GO_PROXY": "http://user:s3cret@10.0.0.1:3128",
                "OPENCODE_GO_BASE_URL": "https://opencode.ai/zen/go/v1/",
            },
            clear=False,
        ):
            self.assertEqual(app.get_opencode_go_api_key(), "sk-og-primary-keyxx")
            self.assertEqual(app.get_opencode_go_proxy(), "http://user:s3cret@10.0.0.1:3128")
            self.assertEqual(app.opencode_go_usage_url(), "https://opencode.ai/zen/go/v1/usage")


class ProbeOpenCodeGoUsageTest(unittest.TestCase):
    def test_missing_key_is_manual_without_http(self) -> None:
        calls: list[str] = []

        def boom(*_a, **_k):
            calls.append("http")
            raise AssertionError("must not call API without a key")

        env = {
            k: v
            for k, v in app.os.environ.items()
            if k not in {"OPENCODE_GO_API_KEY", "OPENCODE_API_KEY"}
        }
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "http_json", side_effect=boom):
                result = app.probe_opencode_go_usage()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["error"], "OPENCODE_GO_API_KEY not set")
        self.assertEqual(calls, [])
        wallet = app.build_opencode_go_wallet(result)
        self.assertEqual(wallet["status"], "manual")
        self.assertFalse(wallet["ok"])

    def test_live_windows_remaining_is_inverse_of_used_percent(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append({"url": url, "token": token, "proxy": proxy, "timeout": timeout})
            return 200, {}, GO_USAGE, None

        with patch.dict(
            "os.environ",
            {
                "OPENCODE_GO_API_KEY": "sk-og-testkey-xxxxxxxxxx",
                "OPENCODE_GO_PROXY": "http://user:s3cret@10.0.0.1:3128",
            },
            clear=False,
        ):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_opencode_go_usage()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["monthly"]["used_percent"], 25.0)
        self.assertEqual(result["monthly"]["remaining_percent"], 75.0)
        self.assertEqual(result["monthly"]["cap"], 60.0)
        self.assertEqual(result["monthly"]["remaining_usd"], 45.0)
        self.assertEqual(result["monthly"]["next_reset_at"], "2026-09-11T14:30:00Z")
        self.assertEqual(result["session"]["next_reset_at"], "2026-08-25T20:00:00Z")
        self.assertEqual(result["session"]["cap"], 12.0)
        self.assertAlmostEqual(result["session"]["remaining_percent"], 80.5, places=1)
        self.assertEqual(result["weekly"]["cap"], 30.0)
        self.assertEqual(result["via"]["proxy"], "http://10.0.0.1:3128")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], "https://opencode.ai/zen/go/v1/usage")
        self.assertEqual(calls[0]["proxy"], "http://user:s3cret@10.0.0.1:3128")
        wallet = app.build_opencode_go_wallet(result)
        self.assertTrue(wallet["ok"])
        self.assertEqual(wallet["plan_label"], "Go")
        self.assertNotIn("s3cret", str(wallet.get("via")))

    def test_auth_error_stays_on_card(self) -> None:
        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 401, {}, {
                "type": "error",
                "error": {"type": "AuthError", "message": "Unauthorized"},
            }, None

        with patch.object(app, "get_opencode_go_api_key", return_value="sk-og-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_opencode_go_usage()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("Unauthorized", result["error"] or "")
        wallet = app.build_opencode_go_wallet(result)
        self.assertEqual(wallet["status"], "error")

    def test_entitlement_error_is_error_not_manual(self) -> None:
        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 403, {}, {
                "type": "error",
                "error": {"type": "EntitlementError", "message": "OpenCode Go subscription required."},
            }, None

        with patch.object(app, "get_opencode_go_api_key", return_value="sk-og-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_opencode_go_usage()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("OpenCode Go subscription required.", result["error"] or "")

    def test_legacy_analyze_shape_and_rate_limited(self) -> None:
        payload = {
            "rollingUsage": {"status": "ok", "usagePercent": 10, "resetInSec": 7200},
            "weeklyUsage": {"status": "ok", "usage_percent": "40", "reset_in_sec": 86400},
            "monthlyUsage": {"status": "rate-limited", "percent": 100, "resetsAt": "2026-09-11T00:00:00Z"},
        }

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 200, {}, payload, None

        with patch.object(app, "get_opencode_go_api_key", return_value="sk-og-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_opencode_go_usage()

        self.assertTrue(result["ok"])
        self.assertEqual(result["session"]["remaining_percent"], 90.0)
        self.assertIsNotNone(result["session"]["next_reset_at"])
        self.assertEqual(result["weekly"]["remaining_percent"], 60.0)
        self.assertEqual(result["monthly"]["remaining_percent"], 0.0)
        self.assertEqual(result["monthly"]["status"], "rate-limited")
        self.assertEqual(result["monthly"]["next_reset_at"], "2026-09-11T00:00:00Z")

    def test_nested_data_usage_envelope(self) -> None:
        payload = {
            "data": {
                "usage": {
                    "rolling": {"percent": 0, "resetsAt": "2026-08-25T18:00:00Z"},
                    "weekly": {"percent": 0, "resetsAt": "2026-09-01T00:00:00Z"},
                    "monthly": {"percent": 0, "resetsAt": "2026-09-18T00:00:00Z"},
                }
            }
        }

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 200, {}, payload, None

        with patch.object(app, "get_opencode_go_api_key", return_value="sk-og-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_opencode_go_usage()

        self.assertTrue(result["ok"])
        self.assertEqual(result["monthly"]["remaining_percent"], 100.0)
        self.assertEqual(result["monthly"]["remaining_usd"], 60.0)

    def test_html_404_is_error(self) -> None:
        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 404, {}, "<!DOCTYPE html><html></html>", None

        with patch.object(app, "get_opencode_go_api_key", return_value="sk-og-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_opencode_go_usage()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("HTML", result["error"] or "")

    def test_probe_exception_does_not_drop_other_wallets(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        d = Path(tmp.name)
        patches = [
            patch.object(app, "DATA_DIR", d),
            patch.object(app, "SNAPSHOT_PATH", d / "snapshots.jsonl"),
            patch.object(app, "STATE_PATH", d / "state.json"),
            patch.object(app, "QUOTA_CACHE_PATH", d / "quota_cache.json"),
        ]
        ok = {
            "ok": True,
            "error": None,
            "probed_at": "t",
            "remaining_summary": "",
        }
        try:
            for p in patches:
                p.start()
            app._quota_cache = {"updated_at": None, "accounts": {}}
            with patch.object(
                app,
                "probe_deepseek_balance",
                return_value={
                    **ok,
                    "provider": "deepseek",
                    "balance": [],
                    "email": "deepseek-main",
                    "kind": "deepseek-balance",
                    "is_available": True,
                },
            ):
                with patch.object(
                    app,
                    "probe_openrouter_wallet",
                    return_value={
                        **ok,
                        "provider": "openrouter",
                        "email": "openrouter-main",
                        "kind": "openrouter-credits",
                        "total_credits": 1,
                        "total_usage": 0,
                        "remaining": 1,
                        "key": {},
                        "keys": [],
                    },
                ):
                    with patch.object(
                        app,
                        "probe_zai_quota",
                        return_value={
                            **ok,
                            "provider": "zai",
                            "email": "zai-main",
                            "kind": "zai-coding-quota",
                            "level": "pro",
                            "session": {},
                            "weekly": {},
                            "mcp": {},
                            "limits": [],
                        },
                    ):
                        with patch.object(
                            app,
                            "probe_commandcode_credits",
                            return_value={
                                **ok,
                                "provider": "commandcode",
                                "email": "commandcode-main",
                                "kind": "commandcode-credits",
                                "status": "active",
                                "session": {},
                                "weekly": {},
                                "monthly": {},
                            },
                        ):
                            with patch.object(
                                app,
                                "probe_kimi_usage",
                                return_value={
                                    **ok,
                                    "provider": "kimi",
                                    "email": "kimi-main",
                                    "kind": "kimi-coding-quota",
                                    "status": "active",
                                    "session": {},
                                    "weekly": {},
                                },
                            ):
                                with patch.object(app, "probe_opencode_go_usage", side_effect=RuntimeError("boom")):
                                    state = app.collect_state(force_quota=True)
            self.assertIn("opencode-go-usage-probe: boom", state["errors"])
            self.assertTrue(state["wallets"]["deepseek"]["ok"])
            self.assertTrue(state["wallets"]["openrouter"]["ok"])
            self.assertTrue(state["wallets"]["zai"]["ok"])
            self.assertTrue(state["wallets"]["commandcode"]["ok"])
            self.assertTrue(state["wallets"]["kimi"]["ok"])
            self.assertNotIn("opencode-go", state["wallets"])
        finally:
            for p in reversed(patches):
                p.stop()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
