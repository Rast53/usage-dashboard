# TASK-usage-dashboard-usage-by-model — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize + verdict OpenRouter activity + partial-паттерн |
| 2026-08-25 | Snapshot 24h/7d | ⏳ | |
| 2026-08-25 | Per-model | ⏳ | |
| 2026-08-25 | UI | ⏳ | |
| 2026-08-25 | Tests | ⏳ | |
| 2026-08-25 | Закрытие | ⏳ | деплой не делать |

## Actual

<!-- заполняется при закрытии -->

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-usage-by-model`. Деплой не делается.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(compute_deepseek_spend_24h)` / `code_blast(compute_deepseek_spend_24h)` / `code_blast(build_openrouter_wallet)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо; `code_callers(collect_state)` → `not_built`)
- `get_page(projects/usage-dashboard)` — волна 2 эпика: расход по подпискам и моделям без CPA; volume snapshots с 10.07.2026
- `whoami` gbrain — transport legacy, без source pin
- Live recon 2026-08-25: `GET https://openrouter.ai/api/v1/activity` без ключа 401 `No cookie auth credentials found`; мусорный Bearer 401 `User not found.`
- Docs: OpenRouter Get user activity (management key, 30 completed UTC days, fields model/usage/requests/tokens)
- Чтение: `app.py` `save_state` / `compute_*_spend_24h` / `probe_openrouter_wallet` / `collect_state`; `static/index.html`; пакет задачи
