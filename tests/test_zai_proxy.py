from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class ZaiProxyHelpersTest(unittest.TestCase):
    def _without_zai_env(self) -> dict[str, str]:
        drop = {"ZAI_PROXY", "ZAI_API_KEY"}
        return {k: v for k, v in app.os.environ.items() if k not in drop}

    def test_default_proxy_is_none(self) -> None:
        with patch.dict("os.environ", self._without_zai_env(), clear=True):
            self.assertIsNone(app.get_zai_proxy())

    def test_proxy_from_env(self) -> None:
        with patch.dict(
            "os.environ",
            {"ZAI_PROXY": "http://user:s3cret@10.0.0.1:3128"},
            clear=False,
        ):
            self.assertEqual(app.get_zai_proxy(), "http://user:s3cret@10.0.0.1:3128")

    def test_blank_proxy_is_none(self) -> None:
        with patch.dict("os.environ", {"ZAI_PROXY": "  "}, clear=False):
            self.assertIsNone(app.get_zai_proxy())


class ProbeZaiQuotaTest(unittest.TestCase):
    def test_missing_key(self) -> None:
        env = {k: v for k, v in app.os.environ.items() if k != "ZAI_API_KEY"}
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "get_zai_api_key", return_value=None):
                result = app.probe_zai_quota()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "ZAI_API_KEY not set")

    def test_probe_passes_proxy_and_keeps_zai_origin(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(
                {
                    "url": url,
                    "token": token,
                    "proxy": proxy,
                    "timeout": timeout,
                    "ssl_verify": ssl_verify,
                }
            )
            if url.endswith("/quota/limit"):
                return (
                    200,
                    {},
                    {
                        "code": 200,
                        "success": True,
                        "data": {
                            "level": "pro",
                            "limits": [
                                {
                                    "type": "TOKENS_LIMIT",
                                    "unit": 3,
                                    "number": 5,
                                    "percentage": 20.0,
                                    "nextResetTime": 1770000000000,
                                },
                                {
                                    "type": "TOKENS_LIMIT",
                                    "unit": 6,
                                    "number": 1,
                                    "percentage": 40.0,
                                    "nextResetTime": 1770500000000,
                                },
                            ],
                        },
                    },
                    None,
                )
            if url.endswith("/subscription/list"):
                return 200, {}, {"data": {"plan": "pro"}}, None
            return 404, {}, None, "unexpected"

        with patch.dict(
            "os.environ",
            {
                "ZAI_API_KEY": "sk-zai-testkey-xxxxxxxxxx",
                "ZAI_PROXY": "http://user:s3cret@10.0.0.1:3128",
            },
            clear=False,
        ):
            with patch.object(app, "get_zai_api_key", return_value="sk-zai-testkey-xxxxxxxxxx"):
                with patch.object(app, "http_json", side_effect=fake_http_json):
                    result = app.probe_zai_quota()

        self.assertTrue(result["ok"])
        self.assertIsNone(result.get("error"))
        self.assertEqual(result["level"], "pro")
        self.assertIsNotNone(result.get("session"))
        self.assertIsNotNone(result.get("weekly"))
        self.assertEqual(result["via"]["proxy"], "http://10.0.0.1:3128")
        self.assertEqual(len(calls), 2)
        self.assertEqual(
            calls[0]["url"],
            "https://api.z.ai/api/monitor/usage/quota/limit",
        )
        self.assertEqual(
            calls[1]["url"],
            "https://api.z.ai/api/biz/subscription/list",
        )
        self.assertEqual(calls[0]["proxy"], "http://user:s3cret@10.0.0.1:3128")
        self.assertEqual(calls[1]["proxy"], "http://user:s3cret@10.0.0.1:3128")
        self.assertEqual(calls[0]["token"], "sk-zai-testkey-xxxxxxxxxx")

        wallet = app.build_zai_wallet(result)
        self.assertTrue(wallet["ok"])
        self.assertEqual(wallet["via"]["proxy"], "http://10.0.0.1:3128")
        self.assertNotIn("s3cret", str(wallet["via"]))

    def test_quota_error_does_not_call_subscription(self) -> None:
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            return None, {}, None, "<urlopen error timed out>"

        with patch.object(app, "get_zai_api_key", return_value="sk-zai-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_zai_quota()

        self.assertFalse(result["ok"])
        self.assertIn("quota/limit API", result["error"] or "")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/quota/limit"))

    def test_without_proxy_still_hits_zai_origin(self) -> None:
        calls: list[dict] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append({"url": url, "proxy": proxy})
            return None, {}, None, "blocked"

        env = {k: v for k, v in app.os.environ.items() if k != "ZAI_PROXY"}
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "get_zai_api_key", return_value="sk-zai-testkey-xxxxxxxxxx"):
                with patch.object(app, "http_json", side_effect=fake_http_json):
                    result = app.probe_zai_quota()

        self.assertFalse(result["ok"])
        self.assertIsNone(result["via"]["proxy"])
        self.assertIsNone(calls[0]["proxy"])
        self.assertEqual(
            calls[0]["url"],
            "https://api.z.ai/api/monitor/usage/quota/limit",
        )


if __name__ == "__main__":
    unittest.main()
