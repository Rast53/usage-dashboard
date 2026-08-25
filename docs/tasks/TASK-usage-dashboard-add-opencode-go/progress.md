# TASK-usage-dashboard-add-opencode-go — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize + разведка `GET /zen/go/v1/usage` |
| 2026-08-25 | Probe + wallet | ✅ | `probe_opencode_go_usage` Bearer; missing key → manual |
| 2026-08-25 | UI | ✅ | карточка 5ч / неделя / месяц + дата reset; error/manual не роняет дашборд |
| 2026-08-25 | Env/compose/docs | ✅ | `OPENCODE_GO_API_KEY` + optional `OPENCODE_GO_PROXY` / `OPENCODE_GO_BASE_URL`; без секретов |
| 2026-08-25 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 52 passed |
| 2026-08-25 | Закрытие | ✅ | код/тесты готовы; деплой не делался |
| 2026-08-25 | Ops E2E | ⏳ | Dockhand stack 7: `OPENCODE_GO_API_KEY` is_secret + autodeploy |

## Actual

Cursor cloud-agent: spec/recon + probe + UI + tests. Оценка S. Ops E2E (live-карточка на usage.ragpt.ru) — после merge/redeploy и записи ключа в Dockhand.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-add-opencode-go`. Деплой не делался.

## 2026-08-25 — build notes

- Live path: `GET https://opencode.ai/zen/go/v1/usage`, `Authorization: Bearer` (`OPENCODE_GO_API_KEY` / `OPENCODE_API_KEY`).
- Cookie `workspace/{id}/go` scrape и Zen balance не используем.
- Нет ключа → `status: manual`, HTTP нет; 401/403/сеть → `error`; исключение probe не дропает DeepSeek/OpenRouter/Z.AI/Command Code/Kimi.
- На проводе `percent` = used; remaining% = 100 − used. USD-остаток — оценка от опубликованных cap'ов ($12 / $30 / $60).
- `resetsAt` ISO; legacy `resetInSec` тоже парсим. `status: rate-limited` → 0% remaining.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(probe_kimi_usage)` / `code_def(probe_opencode_go_usage)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — волна 1 эпика: карточка opencode-go
- `get_page(services/ai-subscriptions)` — Hermes `opencode-go` → `https://opencode.ai/zen/go/v1`; 2026-08-18 `GoUsageLimitError` 429
- Live recon 2026-08-25: `/zen/go/v1/usage` 401 Missing API key / Unauthorized; `/zen/go/v1/models` 200 без квоты; `/zen/v1/usage` и `/zen/go/v1/balance` SPA 404
- opencode#16513 merged; current `usage.ts` `{usage.{rolling,weekly,monthly}.{status,percent,resetsAt}}`; pi-go-bars 0.4.0 `parseUsageApi`
- Чтение: `app.py` `collect_state` / `probe_kimi_usage` / `http_json`; `static/index.html`; пакет задачи
