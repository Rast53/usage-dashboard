# TASK-alan-openrouter-key-card — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-27 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-27 | Spec + plan | ✅ | materialize; ops usage.alan.ragpt.ru — после merge |
| 2026-08-27 | Probe + builder | ✅ | `OPENROUTER_KEY_ONLY=1`: только `/api/v1/key`; `total_usage=key.usage` |
| 2026-08-27 | UI key-only | ✅ | нет баланса аккаунта; день/неделя/месяц + лимит ключа |
| 2026-08-27 | Compose/env | ✅ | alan-стек слоты без секретов; основной compose флаг не получает |
| 2026-08-27 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 87 passed |
| 2026-08-27 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

Cursor cloud-agent: key-only режим OpenRouter (`OPENROUTER_KEY_ONLY`). Оценка S. Ops (PROVIDERS, secret ключа Алана из alanclaw-openclaw, редеплой) — отдельным шагом. Деплой не делался.

## 2026-08-27 — build notes

- `OPENROUTER_KEY_ONLY=1`: `probe_openrouter_wallet()` только `GET /api/v1/key`; `/credits`, `/keys`, `/activity` и `get_openrouter_management_key()` не вызываются.
- `build_openrouter_wallet()`: `total_usage = key.usage` для snapshots-дельт; `total_credits`/`remaining` = None и не входят в `remaining_summary`; summary вида `−$X today (UTC, key) · −$Y week · −$Z month`.
- Дефолт (флаг не задан) — credits+management как раньше. `docker-compose.yml` стека 7 флаг не ставит.
- Имя секрета без изменений: `OPENROUTER_API_KEY`. `/api/summary` ключи не отдаёт.
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(probe_openrouter_wallet)` / `code_def(get_openrouter_wallet)` / `code_callers(probe_openrouter_wallet)` / `code_callers(get_openrouter_wallet)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо). Символы читались напрямую: `app.py` `probe_openrouter_wallet` (~L763) / `build_openrouter_wallet` (~L995; в пакете назван get_openrouter_wallet)
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7, OpenRouter через London `:8444`
- Чтение: `app.py` `probe_openrouter_wallet` / `build_openrouter_wallet` / `compute_openrouter_spend_24h`; `static/index.html` `renderOpenrouterCard`; пакет задачи
