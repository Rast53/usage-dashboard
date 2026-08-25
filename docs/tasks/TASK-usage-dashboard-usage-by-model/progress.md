# TASK-usage-dashboard-usage-by-model — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize + verdict OpenRouter activity + partial-паттерн |
| 2026-08-25 | Snapshot 24h/7d | ✅ | DeepSeek/OpenRouter + Z.AI/Command Code/Kimi/OpenCode Go |
| 2026-08-25 | Per-model | ✅ | `GET /api/v1/activity` management key; остальные — пометка |
| 2026-08-25 | UI | ✅ | расход 24ч/7д на каждой карточке; блок «По моделям» |
| 2026-08-25 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 66 passed |
| 2026-08-25 | Закрытие | ✅ | код/тесты готовы; деплой не делался |
| 2026-08-25 | Ops E2E | ⏳ | autodeploy после merge; prod-smoke на usage.ragpt.ru |

## Actual

Cursor cloud-agent: spec/recon + snapshot deltas 24h/7d + OpenRouter activity per-model + UI + tests. Оценка M. Ops E2E (карточки 24ч/7д и per-model на usage.ragpt.ru) — после merge/redeploy.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-usage-by-model`. Деплой не делался. Файл snapshots.jsonl на volume не трогался.

## 2026-08-25 — build notes

- Spend: snapshots-дельты. DeepSeek balance↓, OpenRouter total_usage↑, Z.AI weekly.currentValue↑, Command Code monthly remaining↓, Kimi weekly.used↑, OpenCode Go monthly.used_usd↑.
- Partial-паттерн: точка до окна → полная дельта; только in-window → `partial`; нет метрики → «недостаточно истории»; сброс квоты → `gap=window-reset`, spent null.
- OpenRouter per-model: `GET {OPENROUTER_BASE_URL}/api/v1/activity` с `OPENROUTER_MANAGEMENT_KEY` (тот же proxy). UTC-дни, не rolling-час (`models.partial`).
- Остальные: `models.reason = «нет разбивки от провайдера»`. CPA/accounts xAI не читаются как spend.
- Fixture `tests/fixtures/snapshots_2026-07-10.jsonl` — схема `save_state` коммитов 10.07 (volume недоступен из cloud-agent).
- Live usage.ragpt.ru за basic auth (401) — prod-smoke нового UI после ops autodeploy.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(compute_deepseek_spend_24h)` / `code_blast(compute_deepseek_spend_24h)` / `code_blast(build_openrouter_wallet)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо; `code_callers(collect_state)` → `not_built`)
- `get_page(projects/usage-dashboard)` — волна 2 эпика: расход по подпискам и моделям без CPA; volume snapshots с 10.07.2026
- `whoami` gbrain — transport legacy, без source pin
- Live recon 2026-08-25: `GET https://openrouter.ai/api/v1/activity` без ключа 401 `No cookie auth credentials found`; мусорный Bearer 401 `User not found.`
- Docs: OpenRouter Get user activity (management key, 30 completed UTC days, fields model/usage/requests/tokens)
- Чтение: `app.py` `save_state` / `compute_*_spend_24h` / `probe_openrouter_wallet` / `collect_state`; `static/index.html`; пакет задачи
