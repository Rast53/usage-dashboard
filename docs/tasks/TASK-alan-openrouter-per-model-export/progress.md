# TASK-alan-openrouter-per-model-export — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ✅ | materialize; ops hash/volume/redeploy — после merge |
| 2026-08-27 | Экспортёр | ✅ | `OPENROUTER_TRACKED_KEY_HASH` + activity?api_key_hash, throttle 300с, атомарный JSON |
| 2026-08-27 | Импортёр + UI | ✅ | key-only overlay; колонки 24ч/7д/30д; stale/missing без ошибок |
| 2026-08-27 | Compose/env | ✅ | volume export rw (stack 7) / :ro (alan); слоты без секретов |
| 2026-08-27 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 101 passed |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

Cursor cloud-agent: per-model экспорт ключа Алана с основного инстанса и импорт на usage.alan.ragpt.ru. Оценка S. Ops (sha256 ключа, mkdir export, редеплой стеков 7/8) — отдельным шагом. Деплой не делался.

## 2026-08-27 — build notes

- Экспортёр (usage.ragpt.ru): пустой `OPENROUTER_TRACKED_KEY_HASH` = no-op. Задан — `GET /api/v1/activity?api_key_hash=` management-ключом через существующий proxy/base URL, не чаще 300с, атомарный JSON без `total_credits`/`remaining`/секретов. Ошибка запроса сохраняет предыдущие models и пишет `last_error` + новый `updated_at`.
- Импортёр только при `OPENROUTER_KEY_ONLY=1` (иначе основной инстанс подменил бы account-wide per-model общим volume). Свежий файл ≤1800с → таблица; нет файла → «нет разбивки от провайдера»; протух → «нет свежих данных экспорта». Activity с алан-контейнера нет.
- UI: `source=openrouter-key-export` — колонки 24ч/7д/30д + «экспорт с аккаунта (key-only)». Основной рендер 7д без изменений.
- Секреты не коммитились. Новые тесты: плейсхолдеры `placeholder-key-N` / `placeholder-hash-alan`.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(probe_openrouter_wallet)` / `code_def(get_openrouter_management_key)` / `code_def(aggregate_openrouter_models)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `code_callers(aggregate_openrouter_models)` / `code_callers(probe_openrouter_wallet)` — 0 callers (тот же пробел индекса)
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7, OpenRouter через London `:8444`
- OpenRouter docs: `GET /api/v1/activity` query `api_key_hash` (SHA-256 hex, management key)
- Чтение: `app.py` `aggregate_openrouter_models` (~L674) / `probe_openrouter_wallet` / `build_openrouter_wallet` / `collect_state`; `static/index.html` `renderModelsSection`; пакет задачи
