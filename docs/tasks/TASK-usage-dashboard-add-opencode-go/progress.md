# TASK-usage-dashboard-add-opencode-go — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize + разведка `GET /zen/go/v1/usage` |
| 2026-08-25 | Probe + wallet | ⏳ | |
| 2026-08-25 | UI | ⏳ | |
| 2026-08-25 | Env/compose/docs | ⏳ | |
| 2026-08-25 | Tests | ⏳ | |
| 2026-08-25 | Закрытие | ⏳ | деплой не делать |
| 2026-08-25 | Ops E2E | ⏳ | Dockhand stack 7: `OPENCODE_GO_API_KEY` is_secret + autodeploy |

## Actual

Cursor cloud-agent: spec/recon. Оценка S. Ops E2E (live-карточка на usage.ragpt.ru) — после merge/redeploy и записи ключа в Dockhand.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-add-opencode-go`. Деплой не делался.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(probe_kimi_usage)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — волна 1 эпика: карточка opencode-go
- `get_page(services/ai-subscriptions)` — Hermes `opencode-go` → `https://opencode.ai/zen/go/v1`; 2026-08-18 `GoUsageLimitError` 429
- Live recon 2026-08-25: `/zen/go/v1/usage` 401 Missing API key / Unauthorized; `/zen/go/v1/models` 200 без квоты; `/zen/v1/usage` и `/zen/go/v1/balance` SPA 404
- opencode#16513 merged; current `usage.ts` `{usage.{rolling,weekly,monthly}.{status,percent,resetsAt}}`; pi-go-bars 0.4.0 `parseUsageApi`
- Чтение: `app.py` `collect_state` / `probe_kimi_usage` / `http_json`; `static/index.html`; пакет задачи
