# TASK-alan-page-msk-time-and-labels — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ✅ | materialize; ops stack 8 — после merge |
| 2026-08-27 | DISPLAY_TZ / summary | ✅ | UTC дефолт; KEY_ONLY без пояса → Europe/Moscow; hide_partial_spend_chips |
| 2026-08-27 | Календарь МСК | ✅ | вчера / 7д / 30д = полные сутки; Итого = key.usage |
| 2026-08-27 | UI | ✅ | timestamps МСК; нет чипов 24ч/7д на Алане; таблица + note; hero/суммы ключа UTC |
| 2026-08-27 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 95 passed |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

Cursor cloud-agent: МСК timestamps, честные UTC-подписи окон ключа, скрытие partial-чипов 24ч/7д, таблица календарных суток. Оценка S. Деплой не делался.

## 2026-08-27 — build notes

- `DISPLAY_TZ` пустой = UTC (usage.ragpt.ru). `OPENROUTER_KEY_ONLY=1` без явного пояса → `Europe/Moscow`. Alan compose: `DISPLAY_TZ=${DISPLAY_TZ:-Europe/Moscow}`. Основной compose слот пустой.
- Timestamps UI: UTC-ветка `getUTC*` без изменений; МСК через `Intl` + подпись «МСК» (фиксированный UTC+3, без tzdata в образе).
- Чипы snapshot 24ч/7д не рендерятся при `hide_partial_spend_chips`. Sparkline и hero сохранены. Суммы ключа `usage_daily/weekly/monthly` на месте, подписи «сутки/неделя/месяц UTC».
- `spend_calendar`: полные календарные сутки МСК из snapshots (сегодня не входит); неполное окно = «—»; Итого = `key.usage`.
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_def(build_openrouter_wallet)` / `code_def(openrouter_key_only)` / `code_callers(probe_openrouter_wallet)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7
- Чтение: `app.py` `probe_openrouter_wallet` / `build_openrouter_wallet` / `_openrouter_key_remaining_summary` / `compute_spend_series_7d`; `static/index.html` `fmtDateTime` / `spendChip` / `openrouterKeyLiveChips` / `heroFor`; пакет задачи
