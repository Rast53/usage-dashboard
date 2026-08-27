# TASK-alan-openrouter-card-cleanup — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ✅ | materialize; ops stack 8 — после merge |
| 2026-08-27 | Backend | ✅ | yesterday-only `usage_24h`; `windows`+даты в note; calendar note с датами МСК |
| 2026-08-27 | UI | ✅ | сводная rolling 24ч МСК; win-row вместо мини-таблицы; per-model вчера/7/30 |
| 2026-08-27 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 111 passed |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

Cursor cloud-agent: rolling-24ч в сводной Алана, чистка карточки OpenRouter, per-model с явными датами. Оценка S. Деплой не делался.

## 2026-08-27 — build notes

- Сводная «Расход 24ч» при `hide_partial_spend_chips`: rolling `spend_24h` + подпись окна `fmtDateShort(now−24ч) – now` (МСК). usage.ragpt.ru — прежний текст «7д на карточках».
- Карточка OpenRouter: `.win-row` вчера / 7 дней / 30 дней / всего, без `<table class="cal">`. Неполные окна по-прежнему «—».
- Per-model export: `usage_24h` = вчерашние UTC-сутки (schema 1, имя поля то же). Колонки вчера / 7 дней / 30 дней. Сноска с датами UTC. «экспорт с аккаунта» убран. `aggregate_openrouter_models` (аккаунт) не менялся.
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(build_openrouter_wallet)` / `code_callers(build_openrouter_wallet)` — 0 defs/callers: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7
- Чтение: `app.py` `compute_openrouter_spend_24h` / `compute_openrouter_calendar_spend` / `aggregate_openrouter_key_models`; `static/index.html` `renderStats` / `renderSpendCalendar` / `renderModelsSection`; пакет задачи
