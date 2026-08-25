from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


MODERATO_USAGES = {
    "usage": {
        "limit": "2048",
        "used": "214",
        "remaining": "1834",
        "resetTime": "2026-09-01T15:23:13.716839300Z",
        "name": "Weekly limit",
    },
    "limits": [
        {
            "window": {"duration": 300, "timeUnit": "TIME_UNIT_MINUTE"},
            "detail": {
                "limit": "200",
                "used": "139",
                "remaining": "61",
                "resetTime": "2026-08-25T18:33:02.717479433Z",
            },
        }
    ],
}


class KimiHelpersTest(unittest.TestCase):
    def test_default_proxy_and_key_are_none(self) -> None:
        drop = {"KIMI_PROXY", "KIMI_CODE_PROXY", "KIMI_API_KEY", "KIMI_CODE_API_KEY", "KIMI_CODE_BASE_URL"}
        env = {k: v for k, v in app.os.environ.items() if k not in drop}
        with patch.dict("os.environ", env, clear=True):
            self.assertIsNone(app.get_kimi_proxy())
            self.assertIsNone(app.get_kimi_api_key())
            self.assertEqual(app.get_kimi_code_base_url(), "https://api.kimi.com/coding/v1")
            self.assertEqual(app.kimi_usages_url(), "https://api.kimi.com/coding/v1/usages")

    def test_key_aliases_proxy_and_base_url(self) -> None:
        with patch.dict(
            "os.environ",
            {"KIMI_CODE_API_KEY": "sk-kimi-testkeyxx", "KIMI_PROXY": "  "},
            clear=False,
        ):
            self.assertEqual(app.get_kimi_api_key(), "sk-kimi-testkeyxx")
            self.assertIsNone(app.get_kimi_proxy())
        with patch.dict(
            "os.environ",
            {
                "KIMI_API_KEY": "sk-kimi-primary-key",
                "KIMI_CODE_PROXY": "http://user:s3cret@10.0.0.1:3128",
                "KIMI_CODE_BASE_URL": "https://api.kimi.com/coding/v1/",
            },
            clear=False,
        ):
            self.assertEqual(app.get_kimi_api_key(), "sk-kimi-primary-key")
            self.assertEqual(app.get_kimi_proxy(), "http://user:s3cret@10.0.0.1:3128")
            self.assertEqual(app.kimi_usages_url(), "https://api.kimi.com/coding/v1/usages")


class ProbeKimiUsageTest(unittest.TestCase):
    def test_missing_key_is_manual_without_http(self) -> None:
        calls: list[str] = []

        def boom(*_a, **_k):
            calls.append("http")
            raise AssertionError("must not call API without a key")

        env = {
            k: v
            for k, v in app.os.environ.items()
            if k not in {"KIMI_API_KEY", "KIMI_CODE_API_KEY"}
        }
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "http_json", side_effect=boom):
                result = app.probe_kimi_usage()
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "manual")
        self.assertEqual(result["error"], "KIMI_API_KEY not set")
        self.assertEqual(calls, [])
        wallet = app.build_kimi_wallet(result)
        self.assertEqual(wallet["status"], "manual")
        self.assertFalse(wallet["ok"])

    def test_live_weekly_and_five_hour_and_redacted_proxy(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append({"url": url, "token": token, "proxy": proxy, "timeout": timeout})
            return 200, {}, MODERATO_USAGES, None

        with patch.dict(
            "os.environ",
            {
                "KIMI_API_KEY": "sk-kimi-testkey-xxxxxxxxxx",
                "KIMI_PROXY": "http://user:s3cret@10.0.0.1:3128",
            },
            clear=False,
        ):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_kimi_usage()

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["plan_label"], "Moderato")
        self.assertEqual(result["weekly"]["cap"], 2048.0)
        self.assertAlmostEqual(result["weekly"]["remaining_percent"], 89.55, places=1)
        self.assertEqual(result["session"]["cap"], 200.0)
        self.assertEqual(result["session"]["remaining"], 61.0)
        self.assertEqual(result["via"]["proxy"], "http://10.0.0.1:3128")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["url"], "https://api.kimi.com/coding/v1/usages")
        self.assertEqual(calls[0]["proxy"], "http://user:s3cret@10.0.0.1:3128")
        wallet = app.build_kimi_wallet(result)
        self.assertTrue(wallet["ok"])
        self.assertEqual(wallet["plan_label"], "Moderato")
        self.assertNotIn("s3cret", str(wallet.get("via")))

    def test_auth_error_stays_on_card(self) -> None:
        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 401, {}, {
                "error": {
                    "message": "Invalid Authentication",
                    "type": "invalid_authentication_error",
                }
            }, None

        with patch.object(app, "get_kimi_api_key", return_value="sk-kimi-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_kimi_usage()

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "error")
        self.assertIn("Invalid Authentication", result["error"] or "")
        wallet = app.build_kimi_wallet(result)
        self.assertEqual(wallet["status"], "error")

    def test_fresh_five_hour_window_without_detail(self) -> None:
        payload = {
            "usage": {"limit": 1024, "used": 0, "remaining": 1024, "reset_at": "2026-09-01T00:00:00Z"},
            "limits": [{"window": {"duration": 300, "timeUnit": "MINUTE"}}],
        }

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 200, {}, payload, None

        with patch.object(app, "get_kimi_api_key", return_value="sk-kimi-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_kimi_usage()

        self.assertTrue(result["ok"])
        self.assertEqual(result["plan_label"], "Andante")
        self.assertEqual(result["session"]["remaining_percent"], 100.0)
        self.assertIsNone(result["session"]["cap"])

    def test_unknown_weekly_cap_has_no_plan_label(self) -> None:
        payload = {
            "usage": {"limit": 99, "used": 9, "remaining": 90},
            "limits": [],
        }

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 200, {}, payload, None

        with patch.object(app, "get_kimi_api_key", return_value="sk-kimi-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_kimi_usage()

        self.assertTrue(result["ok"])
        self.assertIsNone(result["plan_label"])
        self.assertEqual(result["weekly"]["remaining_percent"], 90.91)

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
                            with patch.object(app, "probe_kimi_usage", side_effect=RuntimeError("boom")):
                                with patch.object(
                                    app,
                                    "probe_opencode_go_usage",
                                    return_value={
                                        **ok,
                                        "provider": "opencode-go",
                                        "email": "opencode-go-main",
                                        "kind": "opencode-go-quota",
                                        "status": "active",
                                        "session": {},
                                        "weekly": {},
                                        "monthly": {},
                                    },
                                ):
                                    state = app.collect_state(force_quota=True)
            self.assertIn("kimi-usage-probe: boom", state["errors"])
            self.assertTrue(state["wallets"]["deepseek"]["ok"])
            self.assertTrue(state["wallets"]["openrouter"]["ok"])
            self.assertTrue(state["wallets"]["zai"]["ok"])
            self.assertTrue(state["wallets"]["commandcode"]["ok"])
            self.assertTrue(state["wallets"]["opencode-go"]["ok"])
            self.assertNotIn("kimi", state["wallets"])
        finally:
            for p in reversed(patches):
                p.stop()
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
