# TASK-alan-openrouter-card-cleanup — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ⏳ | materialize |
| 2026-08-27 | Backend | ⏳ | yesterday-only + windows/note; calendar dates |
| 2026-08-27 | UI | ⏳ | сводная rolling МСК; win-row; per-model даты |
| 2026-08-27 | Tests | ⏳ | |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

<!-- заполняется при закрытии -->

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(build_openrouter_wallet)` / `code_callers(build_openrouter_wallet)` — 0 defs/callers: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7
- Чтение: `app.py` `compute_openrouter_spend_24h` / `compute_openrouter_calendar_spend` / `aggregate_openrouter_key_models`; `static/index.html` `renderStats` / `renderSpendCalendar` / `renderModelsSection`; пакет задачи
