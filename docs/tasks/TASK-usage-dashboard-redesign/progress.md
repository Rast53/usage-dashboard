# TASK-usage-dashboard-redesign — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | гибрид A+B; контракт `spend_series_7d` |
| 2026-08-25 | spend_series_7d | ✅ | 8 UTC-дней; partial / no-history / window-reset честные |
| 2026-08-25 | UI | ✅ | hero, чипы `~`, sparkline SVG, allotment used%, таблица моделей |
| 2026-08-25 | Tests + shots | ✅ | `python3 -m unittest discover -s tests -q` — 73 passed; desktop-1280 + mobile-390 |
| 2026-08-25 | Закрытие | ✅ | код/тесты/скрины готовы; деплой не делался |

## Actual

Cursor cloud-agent: spec + `spend_series_7d` + гибрид A+B UI + тесты + скриншоты 1280/390 против локального fixture. Оценка M. Деплой не делался.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-redesign`. Деплой не делался. Compose/Dockerfile не трогались.

## 2026-08-25 — build notes

- `spend_series_7d`: 8 UTC-дней; spent=null если нет наблюдения за день (не выдумываем 0); сброс окна → `gap=window-reset`.
- Allotment-бар = used%; warn при used > 50%; подпись «N% осталось (окно) · used/cap».
- Per-model таблица вынесена под сетку; на 390px `table-wrap` scrollWidth 520 / clientWidth 368.
- Sparkline: inline SVG polyline, без JS-библиотек. Inter через Google Fonts.
- Скриншоты: `docs/tasks/TASK-usage-dashboard-redesign/screenshots/{desktop-1280,mobile-390}.png` против `tests/fixtures/summary_ui.json`.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(compute_openrouter_spend_7d)` / `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(spend_series_7d)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо; `code_callers(collect_state)` → empty/`not_built`)
- `whoami` gbrain — transport legacy, без source pin
- `get_page(research/2026-08-25_usage-dashboard-design)` — рекомендация гибрида A+B (hero+чипы+sparkline / allotment+per-model)
- `get_page(projects/usage-dashboard)` — FastAPI + `static/index.html`, usage.ragpt.ru, stack 7
- Чтение: `app.py` `pick_baseline` / `compute_quota_spend` / `build_*_wallet` / `collect_state` / `summary`; `static/index.html`; пакет задачи
