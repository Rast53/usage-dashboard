# TASK-alan-openrouter-card-windows-row — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ✅ | materialize; ops stack 8 — после merge |
| 2026-08-27 | UI | ✅ | `calendarWindowFilled`: пустые вчера/7д/30д не рендерятся |
| 2026-08-27 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 110 passed |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

Cursor cloud-agent: скрытие пустой строки ВЧЕРА/7Д/30Д на карточке OpenRouter Алана. Оценка S. Деплой не делался.

## 2026-08-27 — build notes

- Live usage.alan.ragpt.ru: `spend_calendar` вчера/7д/30д `spent=null` (snapshots короче полных суток МСК); таблица шла с «—» из‑за `text-transform: uppercase` как ВЧЕРА / 7 ДНЕЙ / 30 ДНЕЙ.
- `renderSpendCalendar`: если все три окна пустые (`spent=null` или `partial`) — пустая строка, без таблицы и note. Частично заполненные — только живые колонки + Итого.
- Backend `spend_calendar` без изменений. Чипы сутки/нед/мес UTC и hero ключа на месте. usage.ragpt.ru не зовёт таблицу (`hide_partial_spend_chips=false`).
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(renderSpendCalendar)` / `code_def(compute_openrouter_calendar_spend)` / `code_callers(renderSpendCalendar)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо). Символы читались напрямую: `static/index.html` `renderSpendCalendar` / `calendarCell`; `app.py` `compute_openrouter_calendar_spend`
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7
- Live `GET https://usage.alan.ragpt.ru/api/summary` — `spend_calendar.yesterday/days_7/days_30.spent=null` (partial), `total.spent` заполнен; `hide_partial_spend_chips=true`
- Чтение: `static/index.html` `renderSpendCalendar` / `renderProviderCard` / `table.cal th { text-transform: uppercase }`; пакет задачи
