# TASK-usage-dashboard-add-commandcode — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | 🔄 | materialize docs/tasks/… + разведка endpoint'а |
| 2026-08-25 | Probe + wallet | ⏳ | |
| 2026-08-25 | UI | ⏳ | |
| 2026-08-25 | Env/compose/docs | ⏳ | |
| 2026-08-25 | Tests | ⏳ | |
| 2026-08-25 | Закрытие | ⏳ | деплой не делать |

## Actual

<!-- заполняется при закрытии -->

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-add-commandcode`. Деплой не делается.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(probe_zai_quota)` / `code_def(http_request)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — волна 1 эпика TASK-usage-dashboard-subscriptions: карточка commandcode
- `get_page(services/ai-subscriptions)` — GOAT CRM Id 17; `api.commandcode.ai/provider/v1`; $70 / $14 / $35
- Live recon 2026-08-25: `/alpha/billing/credits` Bearer 401 vs `/internal/billing/credits` cookie 401
- Чтение: `app.py` wallet probes; `static/index.html`; пакет задачи
