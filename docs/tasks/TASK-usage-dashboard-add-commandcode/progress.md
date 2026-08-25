# TASK-usage-dashboard-add-commandcode — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize + разведка `/alpha/billing/credits` vs `/internal/billing/*` |
| 2026-08-25 | Probe + wallet | ✅ | `probe_commandcode_credits` Bearer; missing key → manual |
| 2026-08-25 | UI | ✅ | карточка 5ч / неделя / месяц; error/manual не роняет дашборд |
| 2026-08-25 | Env/compose/docs | ✅ | `COMMANDCODE_API_KEY` + optional `COMMANDCODE_PROXY`; без секретов |
| 2026-08-25 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 33 passed |
| 2026-08-25 | Закрытие | ✅ | код/тесты готовы; деплой не делался |
| 2026-08-25 | Ops E2E | ⏳ | Dockhand stack 7: `COMMANDCODE_API_KEY` is_secret + autodeploy |

## Actual

Cursor cloud-agent: spec/recon + probe + UI + tests. Оценка S. Ops E2E (live-карточка на usage.ragpt.ru) — после merge/redeploy и записи ключа в Dockhand.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-add-commandcode`. Деплой не делался.

## 2026-08-25 — build notes

- Live path: `GET https://api.commandcode.ai/alpha/billing/credits` + optional `/alpha/billing/subscriptions`, `Authorization: Bearer` (`COMMANDCODE_API_KEY`).
- Cookie `/internal/billing/*` не используем (401 «logged out» без сессии Studio).
- Нет ключа → `status: manual`, HTTP нет; 401/сеть → `error`; исключение probe не дропает DeepSeek/OpenRouter/Z.AI.
- Месячный % только если 5ч+нед cap совпали с каталогом (GOAT 14/35 → $70). Иначе money-only.
- `resetAt: 0` не показываем как 1970.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(probe_zai_quota)` / `code_def(http_request)` / `code_def(probe_commandcode_credits)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — волна 1 эпика: карточка commandcode; wallets DeepSeek/OpenRouter/Z.AI
- `get_page(services/ai-subscriptions)` — GOAT CRM Id 17; `api.commandcode.ai/provider/v1`; $70 / $14 / $35
- Live recon 2026-08-25: `/alpha/billing/credits` Bearer 401 «Invalid Authorization header or token»; `/internal/billing/credits` cookie 401 «logged out»; `/provider/v1/models` 200 без квоты
- pi-sub `fetchCommandCodeUsage` (`/alpha/billing/credits` + Bearer); token-monitor #421 (shape `credits`/`windowLimits`, catalog)
- Чтение: `app.py` `collect_state` / `probe_zai_quota` / `http_json`; `static/index.html`; пакет задачи
