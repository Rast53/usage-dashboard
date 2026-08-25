# TASK-alan-usage-page — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize; ops alan.ragpt.ru — после merge |
| 2026-08-25 | PROVIDERS / SITE_TITLE | ✅ | allowlist + заголовок; пустой env = все 6 |
| 2026-08-25 | UI hero collapse | ✅ | «из 1 провайдера» / 1/1 OpenCode Go; без хардкода 6 имён |
| 2026-08-25 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 73 passed |
| 2026-08-25 | Screenshots | ✅ | desktop+mobile, одна карточка OpenCode Go |
| 2026-08-25 | Ops E2E | ⏳ | hermes-chuwi после merge; деплой не эта ветка |

## Actual

Cursor cloud-agent: env-конфиг инстанса (`PROVIDERS`, `SITE_TITLE`). Оценка S. Ops (второй контейнер, traefik alan.ragpt.ru без basicauth, secret ключа Алана) — отдельным шагом.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(WALLET_PROBE_KEYS)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7, traefik + tasks-basicauth@file
- Чтение: `app.py` `collect_state` / `WALLET_PROBE_KEYS` / `summary` / `index`; `static/index.html` `renderStats`; пакет задачи
