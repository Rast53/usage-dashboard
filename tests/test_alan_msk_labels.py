from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import app


ROOT = Path(__file__).resolve().parents[1]


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _env_without(*names: str) -> dict[str, str]:
    return {k: v for k, v in app.os.environ.items() if k not in names}


class DisplayTzTest(unittest.TestCase):
    def test_default_is_utc(self) -> None:
        with patch.dict("os.environ", _env_without("DISPLAY_TZ", "OPENROUTER_KEY_ONLY"), clear=True):
            self.assertEqual(app.get_display_tz(), "UTC")
            self.assertEqual(app.display_tz_label(), "UTC")
            self.assertFalse(app.hide_partial_spend_chips())
            self.assertIs(app.display_tzinfo(), timezone.utc)

    def test_key_only_defaults_to_moscow(self) -> None:
        with patch.dict("os.environ", {"OPENROUTER_KEY_ONLY": "1"}, clear=False):
            env = _env_without("DISPLAY_TZ")
            env["OPENROUTER_KEY_ONLY"] = "1"
            with patch.dict("os.environ", env, clear=True):
                self.assertEqual(app.get_display_tz(), "Europe/Moscow")
                self.assertEqual(app.display_tz_label(), "МСК")
                self.assertTrue(app.hide_partial_spend_chips())
                self.assertEqual(app.display_tzinfo().utcoffset(None), timedelta(hours=3))

    def test_explicit_utc_wins_over_key_only(self) -> None:
        with patch.dict(
            "os.environ",
            {"OPENROUTER_KEY_ONLY": "1", "DISPLAY_TZ": "UTC"},
            clear=False,
        ):
            self.assertEqual(app.get_display_tz(), "UTC")
            self.assertTrue(app.hide_partial_spend_chips())

    def test_explicit_moscow_aliases(self) -> None:
        for raw in ("Europe/Moscow", "MSK", "moscow"):
            with patch.dict("os.environ", {"DISPLAY_TZ": raw}, clear=False):
                self.assertEqual(app.get_display_tz(), "Europe/Moscow", raw)


class OpenrouterCalendarSpendTest(unittest.TestCase):
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

    def test_complete_msk_windows_exclude_today(self) -> None:
        now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        start = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
        usage = 100.0
        rows = []
        for i in range(32):
            day = start + timedelta(days=i)
            rows.append({
                "ts": _iso(day),
                "wallets": {"openrouter": {"total_usage": usage}},
            })
            usage += 1.0
        self._write(rows)
        cal = app.compute_openrouter_calendar_spend(usage, now=now)
        self.assertEqual(cal["tz_label"], "МСК")
        self.assertEqual(cal["yesterday"]["date"], "2026-08-26")
        self.assertEqual(cal["yesterday"]["spent"], 1.0)
        self.assertFalse(cal["yesterday"]["partial"])
        self.assertEqual(cal["days_7"]["spent"], 7.0)
        self.assertFalse(cal["days_7"]["partial"])
        self.assertEqual(cal["days_30"]["spent"], 30.0)
        self.assertFalse(cal["days_30"]["partial"])
        self.assertEqual(cal["total"]["spent"], 132.0)
        self.assertIn("МСК", cal["note"])

    def test_incomplete_windows_are_null_not_tilde(self) -> None:
        now = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
        cal = app.compute_openrouter_calendar_spend(4.0, now=now)
        self.assertIsNone(cal["yesterday"]["spent"])
        self.assertTrue(cal["yesterday"]["partial"])
        self.assertIsNone(cal["days_7"]["spent"])
        self.assertTrue(cal["days_7"]["partial"])
        self.assertIsNone(cal["days_30"]["spent"])
        self.assertEqual(cal["total"]["spent"], 4.0)

    def test_utc_snapshot_after_msk_midnight_lands_on_next_msk_day(self) -> None:
        now = datetime(2026, 8, 27, 15, 0, tzinfo=timezone.utc)
        self._write(
            [
                {
                    "ts": "2026-08-25T20:00:00Z",
                    "wallets": {"openrouter": {"total_usage": 10.0}},
                },
                {
                    "ts": "2026-08-26T22:00:00Z",
                    "wallets": {"openrouter": {"total_usage": 12.0}},
                },
            ]
        )
        series = app.compute_openrouter_spend_series_7d(
            13.0, now=now, tz=app.MSK_TZ, days=3
        )
        by_date = {p["date"]: p for p in series["points"]}
        self.assertIn("2026-08-27", by_date)
        self.assertEqual(by_date["2026-08-27"]["spent"], 3.0)


class UiContractMskTest(unittest.TestCase):
    def test_html_keeps_utc_chip_path_and_adds_msk_table(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("if (!hidePartialSpendChips)", html)
        self.assertIn("spendChip('24ч'", html)
        self.assertIn("spendChip('7д'", html)
        self.assertIn("renderSpendCalendar", html)
        self.assertIn("function calendarWindowFilled", html)
        self.assertIn("<th>вчера</th>", html)
        self.assertIn("<th>7 дней</th>", html)
        self.assertIn("<th>30 дней</th>", html)
        self.assertIn("<th>Итого</th>", html)
        self.assertIn("сутки UTC (ключ)", html)
        self.assertNotIn("сегодня (UTC, key)", html)
        self.assertIn("getUTCFullYear()", html)

    def test_html_hides_empty_openrouter_calendar_windows(self) -> None:
        html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
        self.assertIn("function calendarWindowFilled", html)
        self.assertIn("!calendarWindowFilled(cal.yesterday)", html)
        self.assertIn("!calendarWindowFilled(cal.days_7)", html)
        self.assertIn("!calendarWindowFilled(cal.days_30)", html)
        self.assertIn("if (calendarWindowFilled(cal.yesterday))", html)
        self.assertIn("if (calendarWindowFilled(cal.days_7))", html)
        self.assertIn("if (calendarWindowFilled(cal.days_30))", html)


if __name__ == "__main__":
    unittest.main()
