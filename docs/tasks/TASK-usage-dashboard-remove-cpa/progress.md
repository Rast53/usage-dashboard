# TASK-usage-dashboard-remove-cpa — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize docs/tasks/… |

## Actual

<!-- заполняется при закрытии -->

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_cpa)` / `code_callers(collect_cpa)` / `code_def(probe_xai_account)` / `code_callers(fetch_usage_from_pg)` / `code_def(probe_deepseek_balance)` / `code_callers(probe_openrouter_wallet)` / `code_def(build_zai_wallet)` / `code_callers(save_state)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — источники с 2026-08-18: wallets; CLIProxy decommissioned; выпиливание из кода = эта задача
- Пакет задачи + чтение: `app.py` (`collect_cpa`, wallet probes), `static/index.html`, `README.md`, `docker-compose.yml`
