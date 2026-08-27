from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]
SECRET = "sk-alan-opencode-go-secret-key-do-not-leak"
ALAN_TITLE = "OpenCode Go — Алан"
ALL_PROVIDERS = [
    "deepseek",
    "openrouter",
    "zai",
    "commandcode",
    "kimi",
    "opencode-go",
]


def _env_without(*names: str) -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in names}


class GetEnabledProvidersTest(unittest.TestCase):
    def test_unset_and_blank_are_all_six(self) -> None:
        with patch.dict("os.environ", _env_without("PROVIDERS", "SITE_TITLE"), clear=True):
            self.assertEqual(app.get_enabled_providers(), ALL_PROVIDERS)
            self.assertEqual(app.get_site_title(), "Мои подписки")
        with patch.dict("os.environ", {"PROVIDERS": "", "SITE_TITLE": "  "}, clear=False):
            self.assertEqual(app.get_enabled_providers(), ALL_PROVIDERS)
            self.assertEqual(app.get_site_title(), "Мои подписки")

    def test_allowlist_parses_order_dedupes_and_drops_unknown(self) -> None:
        with patch.dict(
            "os.environ",
            {"PROVIDERS": " opencode-go , FOO, kimi, opencode-go,deepseek "},
            clear=False,
        ):
            self.assertEqual(
                app.get_enabled_providers(),
                ["opencode-go", "kimi", "deepseek"],
            )
        with patch.dict("os.environ", {"PROVIDERS": "not-a-provider"}, clear=False):
            self.assertEqual(app.get_enabled_providers(), [])
        with patch.dict("os.environ", {"SITE_TITLE": "  " + ALAN_TITLE + "  "}, clear=False):
            self.assertEqual(app.get_site_title(), ALAN_TITLE)


class InstanceConfigCollectTest(unittest.TestCase):
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

    def _probes(self) -> dict[str, dict]:
        ok = {"ok": True, "error": None, "probed_at": "2026-08-25T00:00:00Z"}
        return {
            "deepseek": {
                **ok,
                "provider": "deepseek",
                "email": "deepseek-main",
                "kind": "deepseek-balance",
                "balance": [{"currency": "CNY", "total_balance": "12.5"}],
                "is_available": True,
                "remaining_summary": "CNY 12.5",
            },
            "openrouter": {
                **ok,
                "provider": "openrouter",
                "email": "openrouter-main",
                "kind": "openrouter-credits",
                "total_credits": 10.0,
                "total_usage": 2.0,
                "remaining": 8.0,
                "remaining_summary": "$8.00 left",
                "key": {},
                "keys": [],
                "models": {
                    "available": True,
                    "endpoint": "/api/v1/activity",
                    "items": [{"model": "openai/gpt-4.1", "usage": 0.2, "requests": 1}],
                    "items_24h": [],
                    "partial": True,
                },
            },
            "zai": {
                **ok,
                "provider": "zai",
                "email": "zai-main",
                "kind": "zai-coding-quota",
                "level": "pro",
                "session": {"remaining_percent": 80},
                "weekly": {"remaining_percent": 90, "currentValue": 10},
                "mcp": {},
                "limits": [],
                "remaining_summary": "plan pro",
            },
            "commandcode": {
                **ok,
                "provider": "commandcode",
                "email": "commandcode-main",
                "kind": "commandcode-credits",
                "status": "active",
                "plan_label": "GOAT",
                "monthly_credits": 62.1,
                "monthly": {"remaining_usd": 62.1, "cap": 70},
                "session": {},
                "weekly": {},
                "remaining_summary": "GOAT",
            },
            "kimi": {
                **ok,
                "provider": "kimi",
                "email": "kimi-main",
                "kind": "kimi-coding-quota",
                "status": "active",
                "plan_label": "Moderato",
                "session": {},
                "weekly": {"used": 10, "cap": 2048},
                "remaining_summary": "Moderato",
            },
            "opencode-go": {
                **ok,
                "provider": "opencode-go",
                "email": "opencode-go-main",
                "kind": "opencode-go-quota",
                "status": "active",
                "plan_label": "Go",
                "session": {"remaining_percent": 80},
                "weekly": {"remaining_percent": 70},
                "monthly": {"used_usd": 4.0, "remaining_percent": 75.0, "remaining_usd": 45.0},
                "remaining_summary": "Go · 75% left (month)",
            },
        }

    def _patch_probes(self, probes: dict[str, dict], calls: list[str]):
        mapping = {
            "probe_deepseek_balance": "deepseek",
            "probe_openrouter_wallet": "openrouter",
            "probe_zai_quota": "zai",
            "probe_commandcode_credits": "commandcode",
            "probe_kimi_usage": "kimi",
            "probe_opencode_go_usage": "opencode-go",
        }

        def make(name: str):
            def _fn(*_a, **_k):
                calls.append(name)
                return probes[name]

            return _fn

        stack = []
        for fn_name, key in mapping.items():
            stack.append(patch.object(app, fn_name, side_effect=make(key)))
        for p in stack:
            p.start()
        return stack

    def test_default_env_probes_all_six_and_summary_matches_legacy(self) -> None:
        probes = self._probes()
        calls: list[str] = []
        stacked = self._patch_probes(probes, calls)
        try:
            with patch.dict("os.environ", _env_without("PROVIDERS", "SITE_TITLE"), clear=True):
                state = app.collect_state(force_quota=True)
                app._state = state
                payload = app.summary()
        finally:
            for p in reversed(stacked):
                p.stop()
        self.assertEqual(calls, ALL_PROVIDERS)
        self.assertEqual(list(state["wallets"].keys()), ALL_PROVIDERS)
        self.assertEqual(payload["enabled_providers"], ALL_PROVIDERS)
        self.assertEqual(payload["site_title"], "Мои подписки")
        self.assertEqual(payload["display_tz"], "UTC")
        self.assertEqual(payload["display_tz_label"], "UTC")
        self.assertFalse(payload["hide_partial_spend_chips"])
        self.assertFalse(payload["openrouter_key_only"])
        self.assertIsNone(payload["wallets"]["openrouter"].get("spend_calendar"))
        self.assertEqual(len(payload["wallets"]), 6)
        self.assertTrue(payload["wallets"]["openrouter"]["models"]["available"])
        html = app.index().body.decode("utf-8")
        self.assertIn("<h1>Мои подписки</h1>", html)
        self.assertIn("<title>Мои подписки · raclaw</title>", html)

    def test_providers_opencode_go_skips_other_probes_and_summary(self) -> None:
        probes = self._probes()
        calls: list[str] = []
        stacked = self._patch_probes(probes, calls)
        env = _env_without("PROVIDERS", "SITE_TITLE")
        env.update({
            "PROVIDERS": "opencode-go",
            "SITE_TITLE": ALAN_TITLE,
            "OPENCODE_GO_API_KEY": SECRET,
        })
        try:
            with patch.dict("os.environ", env, clear=True):
                state = app.collect_state(force_quota=True)
                app._state = state
                payload = app.summary()
                html = app.index().body.decode("utf-8")
        finally:
            for p in reversed(stacked):
                p.stop()
        self.assertEqual(calls, ["opencode-go"])
        self.assertEqual(list(state["wallets"].keys()), ["opencode-go"])
        self.assertEqual(payload["enabled_providers"], ["opencode-go"])
        self.assertEqual(payload["site_title"], ALAN_TITLE)
        self.assertEqual(set(payload["wallets"]), {"opencode-go"})
        self.assertEqual(payload["providers"]["wallets"]["keys"], ["opencode-go"])
        blob = json.dumps(payload)
        self.assertNotIn(SECRET, blob)
        self.assertNotRegex(blob, r"sk-[a-zA-Z0-9]{8,}")
        self.assertNotIn("openrouter", payload["wallets"])
        self.assertIn(ALAN_TITLE, html)
        self.assertNotIn("<h1>Мои подписки</h1>", html)
        self.assertNotIn(SECRET, html)
        notes = " ".join(payload.get("notes") or [])
        self.assertIn("OpenCode Go", notes)
        self.assertNotIn("DeepSeek wallet", notes)
        self.assertNotIn("OpenRouter wallet", notes)

    def test_summary_filters_stale_wallets_from_state(self) -> None:
        app._state = {
            "updated_at": "t",
            "wallets": {
                "deepseek": {"provider": "deepseek", "ok": True},
                "opencode-go": {"provider": "opencode-go", "ok": True},
            },
            "providers": {"wallets": {"keys": ["deepseek", "opencode-go"]}},
            "errors": [],
            "notes": [],
        }
        with patch.dict("os.environ", {"PROVIDERS": "opencode-go"}, clear=False):
            payload = app.summary()
        self.assertEqual(set(payload["wallets"]), {"opencode-go"})
        self.assertEqual(payload["providers"]["wallets"]["keys"], ["opencode-go"])


class RenderContractTest(unittest.TestCase):
    def test_hero_and_title_are_data_driven(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function applySiteTitle", html)
        self.assertIn("function sourceLabels", html)
        self.assertIn("function providersGenitive", html)
        self.assertIn("data.site_title", html)
        self.assertIn("из ' + allItems.length", html)
        self.assertNotIn(
            "DeepSeek · OpenRouter · Z.AI · Command Code · Kimi · OpenCode Go",
            html,
        )
        self.assertNotIn("из 6 провайдеров", html)
        self.assertIn("renderOpenrouterCard", html)
        self.assertIn("renderModelsSection", html)
        self.assertIn("models-label", html)
        self.assertIn("CARD_ORDER", html)
        self.assertIn("opencode-go-card", html)
        self.assertIn("function openrouterIsKeyOnly", html)
        self.assertIn("GET /api/v1/key (key-only)", html)
        self.assertIn("OpenRouter · key", html)
        self.assertIn("hidePartialSpendChips", html)
        self.assertNotIn("<table class=\"cal\">", html)
        self.assertNotIn("<th>Итого</th>", html)
        self.assertIn("<th class=\"num\">вчера</th>", html)
        self.assertIn("<th class=\"num\">7 дней</th>", html)
        self.assertIn("<th class=\"num\">30 дней</th>", html)
        self.assertIn("rolling ", html)
        self.assertIn("сутки (сброс 03:00 МСК)", html)
        self.assertIn("всего $", html)
        self.assertNotIn("win-row", html)
        self.assertNotIn("renderSpendCalendar", html)

        self.assertIn("сутки UTC", html)
        self.assertIn("getUTCHours()", html)
        self.assertIn("spendChip('24ч'", html)
        self.assertIn("spendChip('7д'", html)
        self.assertNotIn("экспорт с аккаунта", html)
        self.assertIn("openrouter-key-export", html)

    def test_compose_and_env_example_expose_slots_without_secrets(self) -> None:
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        alan = (ROOT / "docker-compose.alan.yml").read_text(encoding="utf-8")
        example = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("PROVIDERS=${PROVIDERS:-}", compose)
        self.assertIn("SITE_TITLE=${SITE_TITLE:-}", compose)
        self.assertIn("DISPLAY_TZ=${DISPLAY_TZ:-}", compose)
        self.assertNotIn("OPENROUTER_KEY_ONLY=1", compose)
        self.assertNotIn("OPENROUTER_KEY_ONLY=${OPENROUTER_KEY_ONLY:-1}", compose)
        self.assertIn("PROVIDERS=${PROVIDERS:-opencode-go,openrouter}", alan)
        self.assertIn("OPENROUTER_KEY_ONLY=${OPENROUTER_KEY_ONLY:-1}", alan)
        self.assertIn("DISPLAY_TZ=${DISPLAY_TZ:-Europe/Moscow}", alan)
        self.assertNotIn("DISPLAY_TZ=${DISPLAY_TZ:-Europe/Moscow}", compose)
        self.assertIn("OPENROUTER_API_KEY=${OPENROUTER_API_KEY:-}", alan)
        self.assertIn("OPENROUTER_BASE_URL=${OPENROUTER_BASE_URL:-http://100.69.177.71:8444}", alan)
        self.assertIn("SITE_TITLE=${SITE_TITLE:-Подписки — Алан}", alan)
        self.assertIn("PROVIDERS=", example)
        self.assertIn("SITE_TITLE=", example)
        self.assertIn("OPENROUTER_KEY_ONLY=", example)
        self.assertIn("DISPLAY_TZ=", example)
        self.assertIn("OPENROUTER_TRACKED_KEY_HASH=${OPENROUTER_TRACKED_KEY_HASH:-}", compose)
        self.assertIn("OPENROUTER_EXPORT_PATH=${OPENROUTER_EXPORT_PATH:-/app/export/openrouter_key_models.json}", compose)
        self.assertIn("/opt/usage-dashboard/export:/app/export", compose)
        self.assertNotIn("/opt/usage-dashboard/export:/app/export:ro", compose)
        self.assertIn("/opt/usage-dashboard/export:/app/export:ro", alan)
        self.assertIn("OPENROUTER_IMPORT_PATH=${OPENROUTER_IMPORT_PATH:-/app/export/openrouter_key_models.json}", alan)
        self.assertNotIn("OPENROUTER_TRACKED_KEY_HASH", alan)
        self.assertNotIn("OPENROUTER_EXPORT_PATH", alan)
        self.assertIn("OPENROUTER_TRACKED_KEY_HASH=", example)
        self.assertIn("OPENROUTER_EXPORT_PATH=", example)
        self.assertIn("OPENROUTER_IMPORT_PATH=", example)
        blob = compose + alan + example
        self.assertNotIn(SECRET, blob)
        self.assertNotRegex(blob, r"sk-[a-zA-Z0-9]{8,}")
        self.assertNotIn("sk-or-", blob)


if __name__ == "__main__":
    unittest.main()
