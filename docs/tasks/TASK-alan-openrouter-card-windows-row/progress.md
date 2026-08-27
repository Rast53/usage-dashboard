# TASK-alan-openrouter-card-windows-row — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ⏳ | materialize |
| 2026-08-27 | UI | ⏳ | не рендерить пустые окна вчера/7д/30д |
| 2026-08-27 | Tests | ⏳ | |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

<!-- заполняется при закрытии -->

## 2026-08-27 — build notes

<!-- заполняется по ходу -->

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(renderSpendCalendar)` / `code_def(compute_openrouter_calendar_spend)` / `code_callers(renderSpendCalendar)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо). Символы читались напрямую: `static/index.html` `renderSpendCalendar` / `calendarCell`; `app.py` `compute_openrouter_calendar_spend`
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7
- Live `GET https://usage.alan.ragpt.ru/api/summary` — `spend_calendar.yesterday/days_7/days_30.spent=null` (partial), `total.spent` заполнен; `hide_partial_spend_chips=true`
- Чтение: `static/index.html` `renderSpendCalendar` / `renderProviderCard` / `table.cal th { text-transform: uppercase }`; пакет задачи
