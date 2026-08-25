# TASK-usage-dashboard-zai-proxy — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize docs/tasks/… |
| 2026-08-25 | Code proxy | ✅ | `get_zai_proxy` + `probe_zai_quota` HTTP/SOCKS + redact via |
| 2026-08-25 | Env/compose/docs | ✅ | compose `ZAI_PROXY`; `.env.example`; README; без пароля в git |
| 2026-08-25 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 25 passed |
| 2026-08-25 | Закрытие | ✅ | код/тесты готовы; деплой не делался |
| 2026-08-25 | Ops E2E | ⏳ | после мержа — Dockhand stack 7 + `ZAI_PROXY` is_secret |

## Actual

Cursor cloud-agent: spec + `ZAI_PROXY` в probe/compose/tests. Оценка S. Ops E2E (карточка на usage.ragpt.ru, `zai ok:true` в `/api/summary`) — после merge/redeploy и записи `ZAI_PROXY` в Dockhand.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-zai-proxy`. Деплой не делался.

## 2026-08-25 — build notes

- `ZAI_PROXY` — только Z.AI (`/quota/limit`, `/subscription/list`). DeepSeek/OpenRouter без изменений.
- Origin остаётся `https://api.z.ai`; отдельного reverse-proxy нет (в отличие от OpenRouter `:8444`).
- Пароль/userinfo — только Dockhand `stack_environment_variables` (`is_secret`). Не коммитились.
- `via.proxy` в probe/wallet — `redact_proxy_url`.
- Закрытие: код и тесты готовы; live-карточка — после autodeploy.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(ZAI_PROXY)` / `code_def(probe_zai_quota)` / `code_callers(probe_zai_quota)` / `code_def(http_request)` / `code_def(probe_zai)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — Z.AI quota/limit без прокси; OpenRouter уже через London/`OPENROUTER_PROXY`
- `get_page(servers/tw-msk-server)` — контейнер `usage-dashboard-usage-dashboard-1`; `socks-relay.service`
- `get_page(services/dockhand-tw)` — stack env: секреты `is_secret=1` AES в БД; compose `${VAR}`
- Чтение: `app.py` `http_request` / `probe_zai_quota`; `docker-compose.yml`; пакет задачи
