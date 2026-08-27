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
TRACKED = "placeholder-hash-alan"
MGMT = "placeholder-key-2"
SECRET = "placeholder-key-1"
HEX40 = re.compile(r"[0-9a-fA-F]{40,}")
SKOR = re.compile("sk-" + "or-")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_without(*names: str) -> dict[str, str]:
    return {k: v for k, v in app.os.environ.items() if k not in names}


def _activity_rows(now: datetime) -> list[dict]:
    today = now.date()
    return [
        {
            "date": today.isoformat(),
            "model": "google/gemini-flash",
            "usage": 1.0,
            "requests": 2,
        },
        {
            "date": (today - timedelta(days=1)).isoformat() + " 00:00:00",
            "model": "google/gemini-flash",
            "usage": 0.5,
            "requests": 1,
        },
        {
            "date": (today - timedelta(days=5)).isoformat(),
            "model": "kuaishou/kling-v1",
            "usage": 2.0,
            "requests": 4,
        },
        {
            "date": (today - timedelta(days=20)).isoformat(),
            "model": "hexgrad/kokoro",
            "usage": 3.0,
            "requests": 1,
        },
        {
            "date": (today - timedelta(days=40)).isoformat(),
            "model": "old/dropped",
            "usage": 99.0,
            "requests": 9,
        },
    ]


def _assert_no_key_literals(blob: str) -> None:
    assert SECRET not in blob
    assert MGMT not in blob
    assert SKOR.search(blob) is None
    assert HEX40.search(blob) is None


def _assert_export_contract(blob: str) -> None:
    _assert_no_key_literals(blob)
    assert "total_credits" not in blob
    assert "remaining" not in blob
    assert TRACKED not in blob
    for field in ("OPENROUTER_API_KEY", "OPENROUTER_MANAGEMENT_KEY", "api_key"):
        assert field not in blob


class TrackedHashEnvTest(unittest.TestCase):
    def test_unset_blank_and_key_shaped_are_off(self) -> None:
        with patch.dict("os.environ", _env_without("OPENROUTER_TRACKED_KEY_HASH"), clear=True):
            self.assertIsNone(app.get_openrouter_tracked_key_hash())
        with patch.dict("os.environ", {"OPENROUTER_TRACKED_KEY_HASH": ""}, clear=False):
            self.assertIsNone(app.get_openrouter_tracked_key_hash())
        with patch.dict("os.environ", {"OPENROUTER_TRACKED_KEY_HASH": "sk-placeholder-not-a-hash"}, clear=False):
            self.assertIsNone(app.get_openrouter_tracked_key_hash())

    def test_paths_default_and_override(self) -> None:
        env = _env_without("OPENROUTER_EXPORT_PATH", "OPENROUTER_IMPORT_PATH")
        with patch.dict("os.environ", env, clear=True):
            self.assertEqual(
                app.get_openrouter_export_path(),
                Path("/app/export/openrouter_key_models.json"),
            )
            self.assertEqual(
                app.get_openrouter_import_path(),
                Path("/app/export/openrouter_key_models.json"),
            )
        with patch.dict(
            "os.environ",
            {
                "OPENROUTER_EXPORT_PATH": "/tmp/exp.json",
                "OPENROUTER_IMPORT_PATH": "/tmp/imp.json",
            },
            clear=False,
        ):
            self.assertEqual(app.get_openrouter_export_path(), Path("/tmp/exp.json"))
            self.assertEqual(app.get_openrouter_import_path(), Path("/tmp/imp.json"))


class AggregateOpenrouterKeyModelsTest(unittest.TestCase):
    def test_windows_24h_7d_30d(self) -> None:
        now = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)
        rolled = app.aggregate_openrouter_key_models(_activity_rows(now), now=now)
        names = [row["model"] for row in rolled["models"]]
        self.assertEqual(names[0], "kuaishou/kling-v1")
        self.assertIn("google/gemini-flash", names)
        self.assertIn("kuaishou/kling-v1", names)
        self.assertNotIn("old/dropped", names)
        gemini = next(row for row in rolled["models"] if row["model"] == "google/gemini-flash")
        self.assertEqual(gemini["usage_24h"], 0.5)
        self.assertEqual(gemini["requests_24h"], 1)
        self.assertEqual(gemini["usage_7d"], 1.5)
        self.assertEqual(gemini["requests_7d"], 3)
        self.assertEqual(gemini["usage_30d"], 1.5)
        kling = next(row for row in rolled["models"] if row["model"] == "kuaishou/kling-v1")
        self.assertEqual(kling["usage_24h"], 0.0)
        self.assertEqual(kling["requests_24h"], 0)
        self.assertEqual(kling["usage_7d"], 2.0)
        self.assertEqual(kling["requests_7d"], 4)
        self.assertEqual(kling["usage_30d"], 2.0)
        kokoro = next(row for row in rolled["models"] if row["model"] == "hexgrad/kokoro")
        self.assertEqual(kokoro["usage_24h"], 0.0)
        self.assertEqual(kokoro["usage_7d"], 0.0)
        self.assertEqual(kokoro["requests_7d"], 0)
        self.assertEqual(kokoro["usage_30d"], 3.0)
        self.assertEqual(rolled["totals"]["usage_24h"], 0.5)
        self.assertEqual(rolled["totals"]["usage_7d"], 3.5)
        self.assertEqual(rolled["totals"]["usage_30d"], 6.5)
        self.assertEqual(rolled["windows"]["tz"], "UTC")
        self.assertEqual(rolled["windows"]["yesterday"], "2026-08-26")
        self.assertEqual(rolled["windows"]["days_7"]["from"], "2026-08-21")
        self.assertEqual(rolled["windows"]["days_7"]["to"], "2026-08-27")
        self.assertEqual(rolled["windows"]["days_30"]["from"], "2026-07-29")
        self.assertEqual(rolled["windows"]["days_30"]["to"], "2026-08-27")


class ExportWriterTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "openrouter_key_models.json"
        self.env = _env_without(
            "OPENROUTER_TRACKED_KEY_HASH",
            "OPENROUTER_EXPORT_PATH",
            "OPENROUTER_MANAGEMENT_KEY",
        )
        self.env.update(
            {
                "OPENROUTER_TRACKED_KEY_HASH": TRACKED,
                "OPENROUTER_EXPORT_PATH": str(self.path),
            }
        )
        app.reset_openrouter_export_throttle()

    def tearDown(self) -> None:
        app.reset_openrouter_export_throttle()
        self.tmp.cleanup()

    def _fake_activity(self, now: datetime):
        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            self.assertIn("api_key_hash=" + TRACKED, url)
            self.assertIn("/api/v1/activity", url)
            self.assertNotIn("sk-" + "or-", url)
            self.assertEqual(token, MGMT)
            return 200, {}, {"data": _activity_rows(now)}, None

        return fake_http_json

    def test_writer_aggregates_and_omits_account_fields(self) -> None:
        now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        with patch.dict("os.environ", self.env, clear=True):
            with patch.object(app, "get_openrouter_management_key", return_value=MGMT):
                with patch.object(app, "http_json", side_effect=self._fake_activity(now)):
                    with patch.object(app, "now_iso", return_value="2026-08-27T12:00:00Z"):
                        app.maybe_export_openrouter_key_models(now=now, force=True)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema"], 1)
        self.assertEqual(payload["updated_at"], "2026-08-27T12:00:00Z")
        self.assertEqual(payload["key_label_hash_suffix"], TRACKED[-8:])
        self.assertNotIn("last_error", payload)
        names = [row["model"] for row in payload["models"]]
        self.assertIn("google/gemini-flash", names)
        self.assertIn("kuaishou/kling-v1", names)
        self.assertNotIn("old/dropped", names)
        self.assertEqual(payload["totals"]["usage_30d"], 6.5)
        self.assertEqual(payload["windows"]["yesterday"], "2026-08-26")
        blob = json.dumps(payload)
        _assert_export_contract(blob)
        self.assertNotIn("total_credits", blob)
        self.assertNotIn("remaining", blob)
        self.assertNotIn("экспорт с аккаунта", blob)

    def test_error_keeps_previous_models_and_sets_last_error(self) -> None:
        now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        with patch.dict("os.environ", self.env, clear=True):
            with patch.object(app, "get_openrouter_management_key", return_value=MGMT):
                with patch.object(app, "http_json", side_effect=self._fake_activity(now)):
                    with patch.object(app, "now_iso", return_value="2026-08-27T12:00:00Z"):
                        app.maybe_export_openrouter_key_models(now=now, force=True)
        prev = json.loads(self.path.read_text(encoding="utf-8"))

        def boom(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            return 403, {}, {"error": {"message": "nope"}}, None

        app.reset_openrouter_export_throttle()
        with patch.dict("os.environ", self.env, clear=True):
            with patch.object(app, "get_openrouter_management_key", return_value=MGMT):
                with patch.object(app, "http_json", side_effect=boom):
                    with patch.object(app, "now_iso", return_value="2026-08-27T12:05:00Z"):
                        app.maybe_export_openrouter_key_models(now=now, force=True)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["updated_at"], "2026-08-27T12:05:00Z")
        self.assertIn("last_error", payload)
        self.assertIn("403", payload["last_error"])
        self.assertEqual(payload["models"], prev["models"])
        self.assertEqual(payload["totals"], prev["totals"])
        self.assertEqual(payload.get("windows"), prev.get("windows"))
        _assert_export_contract(json.dumps(payload))

    def test_throttle_skips_second_call_within_300s(self) -> None:
        now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            return 200, {}, {"data": _activity_rows(now)}, None

        with patch.dict("os.environ", self.env, clear=True):
            with patch.object(app, "get_openrouter_management_key", return_value=MGMT):
                with patch.object(app, "http_json", side_effect=fake_http_json):
                    app.maybe_export_openrouter_key_models(now=now, force=False)
                    app.maybe_export_openrouter_key_models(now=now, force=False)
        self.assertEqual(len(calls), 1)

    def test_unset_hash_does_not_call_http(self) -> None:
        env = _env_without("OPENROUTER_TRACKED_KEY_HASH", "OPENROUTER_EXPORT_PATH")
        env["OPENROUTER_EXPORT_PATH"] = str(self.path)

        def boom(*args, **kwargs):
            raise AssertionError("http_json must not run when hash unset")

        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "http_json", side_effect=boom):
                with patch.object(app, "get_openrouter_management_key", side_effect=AssertionError("mgmt")):
                    app.maybe_export_openrouter_key_models(force=True)
        self.assertFalse(self.path.exists())


class ImportOverlayTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.export = self.dir / "openrouter_key_models.json"
        self.snap = self.dir / "snapshots.jsonl"
        self.patches = [
            patch.object(app, "DATA_DIR", self.dir),
            patch.object(app, "SNAPSHOT_PATH", self.snap),
            patch.object(app, "STATE_PATH", self.dir / "state.json"),
            patch.object(app, "QUOTA_CACHE_PATH", self.dir / "quota_cache.json"),
        ]
        for p in self.patches:
            p.start()
        app.invalidate_snapshot_cache()
        app.reset_openrouter_export_throttle()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        app.reset_openrouter_export_throttle()
        self.tmp.cleanup()

    def _payload(self, updated_at: str, windows: dict | None = None) -> dict:
        body = {
            "schema": 1,
            "updated_at": updated_at,
            "key_label_hash_suffix": "hash-aln",
            "models": [
                {
                    "model": "google/gemini-flash",
                    "usage_24h": 1.25,
                    "usage_7d": 6.5,
                    "usage_30d": 18.0,
                    "requests_24h": 3,
                    "requests_7d": 11,
                }
            ],
            "totals": {"usage_24h": 1.25, "usage_7d": 6.5, "usage_30d": 18.0},
        }
        if windows is not None:
            body["windows"] = windows
        return body

    def _probe(self) -> dict:
        return {
            "ok": True,
            "kind": "openrouter-key",
            "total_credits": None,
            "total_usage": None,
            "remaining": None,
            "remaining_summary": "−$1.25 today (UTC, key)",
            "key": {
                "label": "alan-bot",
                "usage": 42.5,
                "usage_daily": 1.25,
                "usage_weekly": 6.5,
                "usage_monthly": 18.0,
            },
            "keys": [],
            "error": None,
            "probed_at": "2026-08-27T00:00:00Z",
            "models": app.models_unavailable("GET /api/v1/activity требует management key"),
        }

    def test_fresh_file_builds_models_from_export(self) -> None:
        now = datetime.now(timezone.utc)
        windows = app._openrouter_key_window_meta(
            datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        )
        self.export.write_text(
            json.dumps(self._payload(_iso(now), windows)),
            encoding="utf-8",
        )
        env = _env_without("OPENROUTER_KEY_ONLY", "OPENROUTER_IMPORT_PATH")
        env.update(
            {
                "OPENROUTER_KEY_ONLY": "1",
                "OPENROUTER_IMPORT_PATH": str(self.export),
            }
        )
        with patch.dict("os.environ", env, clear=True):
            wallet = app.build_openrouter_wallet(self._probe())
        assert wallet is not None
        models = wallet["models"]
        self.assertTrue(models["available"])
        self.assertEqual(models["source"], "openrouter-key-export")
        self.assertEqual(models["note"], app.openrouter_key_models_note(windows))
        self.assertIn("вчера 26.08 UTC", models["note"])
        self.assertIn("7 дней 21.08–27.08 UTC", models["note"])
        self.assertIn("30 дней 29.07–27.08 UTC", models["note"])
        self.assertNotIn("экспорт с аккаунта", models["note"])
        self.assertEqual(models["windows"]["yesterday"], "2026-08-26")
        self.assertEqual(models["items"][0]["model"], "google/gemini-flash")
        self.assertEqual(models["items"][0]["usage"], 6.5)
        self.assertEqual(models["items"][0]["usage_24h"], 1.25)
        self.assertEqual(models["items"][0]["usage_30d"], 18.0)
        self.assertIsNone(wallet["total_credits"])
        self.assertIsNone(wallet["remaining"])
        blob = json.dumps(wallet)
        _assert_no_key_literals(blob)
        self.assertIsNone(json.loads(blob).get("total_credits"))

    def test_legacy_file_without_windows_infers_dates(self) -> None:
        now = datetime.now(timezone.utc)
        self.export.write_text(json.dumps(self._payload(_iso(now))), encoding="utf-8")
        env = _env_without("OPENROUTER_KEY_ONLY", "OPENROUTER_IMPORT_PATH")
        env.update({"OPENROUTER_KEY_ONLY": "1", "OPENROUTER_IMPORT_PATH": str(self.export)})
        with patch.dict("os.environ", env, clear=True):
            wallet = app.build_openrouter_wallet(self._probe())
        assert wallet is not None
        expected = app._openrouter_key_window_meta(now)
        self.assertEqual(wallet["models"]["windows"]["yesterday"], expected["yesterday"])
        self.assertEqual(wallet["models"]["note"], app.openrouter_key_models_note(expected))
        self.assertNotIn("экспорт с аккаунта", wallet["models"]["note"])

    def test_stale_file_uses_fresh_export_reason(self) -> None:
        now = datetime.now(timezone.utc)
        stale = now - timedelta(seconds=1801)
        self.export.write_text(json.dumps(self._payload(_iso(stale))), encoding="utf-8")
        env = _env_without("OPENROUTER_KEY_ONLY", "OPENROUTER_IMPORT_PATH")
        env.update({"OPENROUTER_KEY_ONLY": "1", "OPENROUTER_IMPORT_PATH": str(self.export)})
        with patch.dict("os.environ", env, clear=True):
            wallet = app.build_openrouter_wallet(self._probe())
        assert wallet is not None
        self.assertFalse(wallet["models"]["available"])
        self.assertEqual(wallet["models"]["reason"], app.NO_FRESH_EXPORT)
        self.assertTrue(wallet["ok"])
        self.assertNotIn("last_error", wallet)

    def test_missing_file_keeps_no_breakdown(self) -> None:
        missing = self.dir / "no-such.json"
        env = _env_without("OPENROUTER_KEY_ONLY", "OPENROUTER_IMPORT_PATH")
        env.update({"OPENROUTER_KEY_ONLY": "1", "OPENROUTER_IMPORT_PATH": str(missing)})
        with patch.dict("os.environ", env, clear=True):
            wallet = app.build_openrouter_wallet(self._probe())
        assert wallet is not None
        self.assertFalse(wallet["models"]["available"])
        self.assertEqual(wallet["models"]["reason"], app.NO_MODEL_BREAKDOWN)
        self.assertTrue(wallet["ok"])

    def test_without_key_only_import_does_not_override_probe_models(self) -> None:
        now = datetime.now(timezone.utc)
        self.export.write_text(json.dumps(self._payload(_iso(now))), encoding="utf-8")
        probe = self._probe()
        probe["ok"] = True
        probe["total_credits"] = 10.0
        probe["total_usage"] = 2.0
        probe["remaining"] = 8.0
        probe["remaining_summary"] = "$8.00 left · used $2.00 / $10.00"
        probe["models"] = {
            "available": True,
            "source": "openrouter-activity",
            "items": [{"model": "openai/gpt-4.1", "usage": 0.2, "requests": 1}],
        }
        env = _env_without("OPENROUTER_KEY_ONLY", "OPENROUTER_IMPORT_PATH")
        env["OPENROUTER_IMPORT_PATH"] = str(self.export)
        with patch.dict("os.environ", env, clear=True):
            wallet = app.build_openrouter_wallet(probe)
        assert wallet is not None
        self.assertEqual(wallet["models"]["source"], "openrouter-activity")
        self.assertEqual(wallet["models"]["items"][0]["model"], "openai/gpt-4.1")
        self.assertEqual(wallet["total_credits"], 10.0)

    def test_key_only_probe_still_skips_activity_when_import_present(self) -> None:
        now = datetime.now(timezone.utc)
        self.export.write_text(json.dumps(self._payload(_iso(now))), encoding="utf-8")
        calls: list[str] = []

        def fake_http_json(url, token, proxy=None, method="GET", body=None, timeout=20.0, ssl_verify=True):
            calls.append(url)
            if url.endswith("/key"):
                return 200, {}, {"data": {"label": "alan-bot", "usage": 1.0, "usage_daily": 0.2}}, None
            raise AssertionError(f"unexpected url {url}")

        env = _env_without(
            "OPENROUTER_KEY_ONLY",
            "OPENROUTER_IMPORT_PATH",
            "OPENROUTER_TRACKED_KEY_HASH",
            "OPENROUTER_MANAGEMENT_KEY",
        )
        env.update(
            {
                "OPENROUTER_KEY_ONLY": "1",
                "OPENROUTER_API_KEY": SECRET,
                "OPENROUTER_IMPORT_PATH": str(self.export),
            }
        )
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "get_openrouter_api_key", return_value=SECRET):
                with patch.object(app, "get_openrouter_management_key", side_effect=AssertionError("mgmt")):
                    with patch.object(app, "http_json", side_effect=fake_http_json):
                        result = app.probe_openrouter_wallet()
                        wallet = app.build_openrouter_wallet(result)
        self.assertEqual(calls, [app.openrouter_api_url("/api/v1/key")])
        self.assertFalse(any("activity" in u for u in calls))
        assert wallet is not None
        self.assertTrue(wallet["models"]["available"])
        self.assertEqual(wallet["models"]["source"], "openrouter-key-export")


class CollectStateDefaultsExportOffTest(unittest.TestCase):
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
        app.reset_openrouter_export_throttle()

    def tearDown(self) -> None:
        for p in reversed(self.patches):
            p.stop()
        app.reset_openrouter_export_throttle()
        self.tmp.cleanup()

    def test_collect_state_without_hash_does_not_export(self) -> None:
        probe = {
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
            "probed_at": "2026-08-27T00:00:00Z",
            "models": {
                "available": True,
                "source": "openrouter-activity",
                "items": [{"model": "openai/gpt-4.1", "usage": 0.2, "requests": 1}],
            },
        }

        def boom(*args, **kwargs):
            raise AssertionError("export http must not run")

        env = _env_without(
            "OPENROUTER_TRACKED_KEY_HASH",
            "OPENROUTER_KEY_ONLY",
            "PROVIDERS",
            "SITE_TITLE",
        )
        env["PROVIDERS"] = "openrouter"
        with patch.dict("os.environ", env, clear=True):
            with patch.object(app, "probe_deepseek_balance", return_value={"ok": False, "provider": "deepseek"}):
                with patch.object(app, "probe_openrouter_wallet", return_value=probe):
                    with patch.object(app, "probe_zai_quota", return_value={"ok": False, "provider": "zai"}):
                        with patch.object(app, "probe_commandcode_credits", return_value={"ok": False}):
                            with patch.object(app, "probe_kimi_usage", return_value={"ok": False}):
                                with patch.object(app, "probe_opencode_go_usage", return_value={"ok": False}):
                                    with patch.object(app, "http_json", side_effect=boom):
                                        state = app.collect_state(force_quota=True)
        wallet = state["wallets"]["openrouter"]
        self.assertEqual(wallet["total_credits"], 10.0)
        self.assertEqual(wallet["remaining"], 8.0)
        self.assertEqual(wallet["models"]["source"], "openrouter-activity")
        self.assertEqual(state["site_title"], "Мои подписки")
        self.assertEqual(state["enabled_providers"], ["openrouter"])


class WindowNoteHelpersTest(unittest.TestCase):
    def test_fmt_and_note(self) -> None:
        self.assertEqual(app._fmt_iso_day("2026-08-26"), "26.08")
        self.assertEqual(app._fmt_iso_day(None), "—")
        now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        note = app.openrouter_key_models_note(app._openrouter_key_window_meta(now))
        self.assertEqual(
            note,
            "вчера 26.08 UTC · 7 дней 21.08–27.08 UTC · 30 дней 29.07–27.08 UTC",
        )
        self.assertNotIn("экспорт", note)


class NewTestLiteralsGuard(unittest.TestCase):
    def test_this_file_has_no_key_or_long_hex_literals(self) -> None:
        text = Path(__file__).read_text(encoding="utf-8")
        self.assertNotRegex(text, r"sk-" + r"or-")
        self.assertNotRegex(text, r"[0-9a-fA-F]{40,}")
        self.assertIn("placeholder-key-1", text)
        self.assertIn("placeholder-hash-alan", text)


if __name__ == "__main__":
    unittest.main()
