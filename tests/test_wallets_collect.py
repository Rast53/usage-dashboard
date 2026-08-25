from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = re.compile(r"cpa|USAGE_PG_DSN|ORPHAN|psycopg2", re.I)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class ResidualSourceStringsTest(unittest.TestCase):
    def test_app_ui_readme_compose_have_no_forbidden_tokens(self) -> None:
        hits: list[str] = []
        for rel in ("app.py", "static/index.html", "README.md", "docker-compose.yml"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for i, line in enumerate(text.splitlines(), 1):
                if FORBIDDEN.search(line):
                    hits.append(f"{rel}:{i}:{line.strip()}")
        self.assertEqual(hits, [])


class HistoricalSnapshotSpendTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.snap = Path(self.tmp.name) / "snapshots.jsonl"
        self.snap_patch = patch.object(app, "SNAPSHOT_PATH", self.snap)
        self.snap_patch.start()

    def tearDown(self) -> None:
        self.snap_patch.stop()
        self.tmp.cleanup()

    def test_legacy_accounts_row_feeds_deepseek_spend(self) -> None:
        now = datetime.now(timezone.utc)
        baseline = now - timedelta(hours=25)
        current_balance = [{"currency": "CNY", "total_balance": "80.0"}]
        legacy = {
            "ts": _iso(baseline),
            "accounts": [
                {
                    "provider": "xai",
                    "email": "old@example.com",
                    "quota": {"credits": {"used_percent": 100}},
                },
                {
                    "provider": "deepseek",
                    "email": "deepseek-main",
                    "quota": {"balance": [{"currency": "CNY", "total_balance": "100.0"}]},
                },
            ],
        }
        self.snap.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
        spend = app.compute_deepseek_spend_24h(current_balance, window_hours=24)
        self.assertFalse(spend["partial"])
        self.assertEqual(spend["spent"].get("CNY"), 20.0)

    def test_wallet_shaped_openrouter_row_still_works(self) -> None:
        now = datetime.now(timezone.utc)
        baseline = now - timedelta(hours=25)
        row = {
            "ts": _iso(baseline),
            "wallets": {"openrouter": {"total_usage": 1.5}},
            "accounts": [{"provider": "xai", "email": "old@example.com"}],
        }
        self.snap.write_text(json.dumps(row) + "\n", encoding="utf-8")
        spend = app.compute_openrouter_spend_24h(3.5, window_hours=24)
        self.assertFalse(spend["partial"])
        self.assertEqual(spend["spent"], 2.0)

    def test_malformed_and_account_only_rows_do_not_raise(self) -> None:
        now = datetime.now(timezone.utc)
        lines = [
            "not-json",
            json.dumps({"ts": _iso(now - timedelta(hours=2)), "accounts": "oops"}),
            json.dumps(
                {
                    "ts": _iso(now - timedelta(hours=26)),
                    "wallets": {
                        "deepseek": {"balance": [{"currency": "CNY", "total_balance": "50"}]}
                    },
                }
            ),
        ]
        self.snap.write_text("\n".join(lines) + "\n", encoding="utf-8")
        spend = app.compute_deepseek_spend_24h(
            [{"currency": "CNY", "total_balance": "40"}],
            window_hours=24,
        )
        self.assertEqual(spend["spent"].get("CNY"), 10.0)


class CollectStateTest(unittest.TestCase):
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
        app._quota_cache = {"updated_at": None, "accounts": {}}
        app._state = {
            "updated_at": None,
            "providers": {},
            "accounts": [{"provider": "xai", "email": "stale"}],
            "wallets": {},
            "errors": ["stale"],
        }

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()

    def _probes(self) -> dict[str, object]:
        ds = {
            "provider": "deepseek",
            "email": "deepseek-main",
            "ok": True,
            "kind": "deepseek-balance",
            "balance": [{"currency": "CNY", "total_balance": "12.5"}],
            "is_available": True,
            "error": None,
            "probed_at": "2026-08-25T00:00:00Z",
            "remaining_summary": "CNY 12.5",
        }
        orp = {
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
        }
        zai = {
            "provider": "zai",
            "email": "zai-main",
            "ok": True,
            "kind": "zai-coding-quota",
            "level": "pro",
            "session": {"remaining_percent": 80},
            "weekly": {"remaining_percent": 90},
            "mcp": {},
            "limits": [],
            "error": None,
            "probed_at": "2026-08-25T00:00:00Z",
            "remaining_summary": "plan pro",
        }
        return {"ds": ds, "or": orp, "zai": zai}

    def test_collect_state_returns_wallets_without_errors(self) -> None:
        probes = self._probes()
        with patch.object(app, "probe_deepseek_balance", return_value=probes["ds"]):
            with patch.object(app, "probe_openrouter_wallet", return_value=probes["or"]):
                with patch.object(app, "probe_zai_quota", return_value=probes["zai"]):
                    state = app.collect_state(force_quota=True)
        self.assertEqual(state["errors"], [])
        self.assertEqual(state["accounts"], [])
        self.assertTrue(state["wallets"]["deepseek"]["ok"])
        self.assertTrue(state["wallets"]["openrouter"]["ok"])
        self.assertTrue(state["wallets"]["zai"]["ok"])
        self.assertEqual(state["providers"]["wallets"]["keys"], ["deepseek", "openrouter", "zai"])
        self.assertNotIn("cpa", json.dumps(state).lower())

    def test_stale_legacy_cache_forces_wallet_probes(self) -> None:
        app._quota_cache = {
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "accounts": {"old@example.com": {"ok": True}},
        }
        calls = {"n": 0}

        def ds():
            calls["n"] += 1
            return self._probes()["ds"]

        with patch.object(app, "probe_deepseek_balance", side_effect=ds):
            with patch.object(app, "probe_openrouter_wallet", return_value=self._probes()["or"]):
                with patch.object(app, "probe_zai_quota", return_value=self._probes()["zai"]):
                    app.collect_state(force_quota=False)
        self.assertEqual(calls["n"], 1)

    def test_refresh_once_health_and_snapshot_schema(self) -> None:
        probes = self._probes()
        with patch.object(app, "probe_deepseek_balance", return_value=probes["ds"]):
            with patch.object(app, "probe_openrouter_wallet", return_value=probes["or"]):
                with patch.object(app, "probe_zai_quota", return_value=probes["zai"]):
                    state = app.refresh_once(force_quota=True)
        health = app.health()
        self.assertTrue(health["ok"])
        self.assertEqual(health["wallets"], 3)
        self.assertEqual(health["errors"], [])
        self.assertIsNotNone(health.get("quota_probe_updated_at"))
        snap_line = (self.dir / "snapshots.jsonl").read_text(encoding="utf-8").strip().splitlines()[-1]
        row = json.loads(snap_line)
        self.assertEqual(row["accounts"], [])
        self.assertIn("deepseek", row["wallets"])
        self.assertEqual(state["wallets"]["openrouter"]["remaining"], 8.0)


if __name__ == "__main__":
    unittest.main()
