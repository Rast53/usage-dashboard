from __future__ import annotations

import unittest
from unittest.mock import patch

import app


class OpenRouterHelpersTest(unittest.TestCase):
    def _without_openrouter_env(self) -> dict[str, str]:
        drop = {
            "OPENROUTER_BASE_URL",
            "OPENROUTER_PROXY",
            "OPENROUTER_SSL_NO_VERIFY",
            "OPENROUTER_API_KEY",
            "OPENROUTER_MANAGEMENT_KEY",
            "OPENROUTER_KEY_ONLY",
        }
        return {k: v for k, v in app.os.environ.items() if k not in drop}

    def test_default_base_url_and_proxy(self) -> None:
        with patch.dict("os.environ", self._without_openrouter_env(), clear=True):
            self.assertEqual(app.get_openrouter_base_url(), "https://openrouter.ai")
            self.assertIsNone(app.get_openrouter_proxy())
            self.assertTrue(app.get_openrouter_ssl_verify())
            self.assertEqual(
                app.openrouter_api_url("/api/v1/credits"),
                "https://openrouter.ai/api/v1/credits",
            )
            self.assertEqual(
                app.openrouter_api_url("api/v1/key"),
                "https://openrouter.ai/api/v1/key",
            )

    def test_base_url_rstrip_and_proxy_from_env(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_BASE_URL": "https://100.69.177.71:8444/",
                "OPENROUTER_PROXY": "socks5h://host.docker.internal:1080",
                "OPENROUTER_SSL_NO_VERIFY": "1",
            },
            clear=False,
        ):
            self.assertEqual(app.get_openrouter_base_url(), "https://100.69.177.71:8444")
            self.assertEqual(
                app.get_openrouter_proxy(), "socks5h://host.docker.internal:1080"
            )
            self.assertFalse(app.get_openrouter_ssl_verify())
            self.assertEqual(
                app.openrouter_api_url("/api/v1/credits"),
                "https://100.69.177.71:8444/api/v1/credits",
            )

    def test_redact_proxy_strips_userinfo(self) -> None:
        self.assertIsNone(app.redact_proxy_url(None))
        self.assertEqual(
            app.redact_proxy_url("http://user:secret@10.1.2.3:3128"),
            "http://10.1.2.3:3128",
        )
        self.assertEqual(
            app.redact_proxy_url("socks5h://host.docker.internal:1080"),
            "socks5h://host.docker.internal:1080",
        )

    def test_http_proxy_handler_scheme(self) -> None:
        handlers = app._proxy_handlers("http://127.0.0.1:3128")
        self.assertEqual(len(handlers), 1)
        self.assertIsInstance(handlers[0], app.urlrequest.ProxyHandler)

    def test_socks_handler_requires_host(self) -> None:
        with self.assertRaises(ValueError):
            app._proxy_handlers("socks5://")

    def test_unsupported_scheme(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            app._proxy_handlers("ftp://127.0.0.1:21")
        self.assertIn("unsupported proxy scheme", str(ctx.exception))

    def test_socks5_handler(self) -> None:
        self.assertIsNotNone(app.socks)
        self.assertIsNotNone(app.SocksiPyHandler)
        handlers = app._proxy_handlers("socks5h://127.0.0.1:1080")
        self.assertEqual(len(handlers), 1)
        self.assertIsInstance(handlers[0], app.SocksiPyHandler)

    def test_socks_without_pysocks(self) -> None:
        with patch.object(app, "socks", None), patch.object(app, "SocksiPyHandler", None):
            with self.assertRaises(RuntimeError) as ctx:
                app._proxy_handlers("socks5://127.0.0.1:1080")
        self.assertIn("PySocks", str(ctx.exception))


class ProbeOpenrouterWalletTest(unittest.TestCase):
    def test_missing_key(self) -> None:
        env = {
            k: v
            for k, v in app.os.environ.items()
            if k not in {"OPENROUTER_API_KEY", "OPENROUTER_MANAGEMENT_KEY"}
        }
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "get_openrouter_api_key", return_value=None):
                result = app.probe_openrouter_wallet()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "OPENROUTER_API_KEY not set")

    def test_probe_passes_proxy_and_rewritten_url(self) -> None:
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
            if url.endswith("/credits"):
                return 200, {}, {"data": {"total_credits": 10.5, "total_usage": 2.25}}, None
            if url.endswith("/key"):
                return 200, {}, {"data": {"label": "main", "usage_daily": 0.5}}, None
            return 404, {}, None, "unexpected"

        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_API_KEY": "sk-or-v1-testkey-xxxxxxxxxx",
                "OPENROUTER_BASE_URL": "https://100.69.177.71:8444",
                "OPENROUTER_PROXY": "http://user:s3cret@10.0.0.1:3128",
                "OPENROUTER_SSL_NO_VERIFY": "yes",
            },
            clear=False,
        ):
            with patch.object(app, "get_openrouter_api_key", return_value="sk-or-v1-testkey-xxxxxxxxxx"):
                with patch.object(app, "get_openrouter_management_key", return_value=None):
                    with patch.object(app, "http_json", side_effect=fake_http_json):
                        result = app.probe_openrouter_wallet()

        self.assertTrue(result["ok"])
        self.assertEqual(result["remaining"], 8.25)
        self.assertIsNone(result.get("error"))
        self.assertEqual(result["via"]["base_url"], "https://100.69.177.71:8444")
        self.assertEqual(result["via"]["proxy"], "http://10.0.0.1:3128")
        self.assertFalse(result["via"]["ssl_verify"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["url"], "https://100.69.177.71:8444/api/v1/credits")
        self.assertEqual(calls[1]["url"], "https://100.69.177.71:8444/api/v1/key")
        self.assertEqual(calls[0]["proxy"], "http://user:s3cret@10.0.0.1:3128")
        self.assertFalse(calls[0]["ssl_verify"])
        self.assertEqual(calls[0]["token"], "sk-or-v1-testkey-xxxxxxxxxx")

    def test_credits_error_does_not_call_key(self) -> None:
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            return None, {}, None, "<urlopen error timed out>"

        with patch.object(app, "get_openrouter_api_key", return_value="sk-or-v1-testkey-xxxxxxxxxx"):
            with patch.object(app, "http_json", side_effect=fake_http_json):
                result = app.probe_openrouter_wallet()

        self.assertFalse(result["ok"])
        self.assertIn("credits API", result["error"] or "")
        self.assertEqual(len(calls), 1)
        self.assertTrue(calls[0].endswith("/api/v1/credits"))


if __name__ == "__main__":
    unittest.main()
