# TASK-usage-dashboard-remove-cpa — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize docs/tasks/… |
| 2026-08-25 | Collect wallets only | ✅ | `collect_state`; удалены xAI/Codex/Postgres probes |
| 2026-08-25 | UI | ✅ | нет секции «Аккаунты xAI / Codex»; нет «по CPA аккаунтам» |
| 2026-08-25 | README/compose | ✅ | только DeepSeek / OpenRouter / Z.AI |
| 2026-08-25 | Tests | ✅ | `python -m unittest discover -s tests -q` — 18 passed |
| 2026-08-25 | Закрытие | ✅ | grep acceptance #1 = 0; деплой не делался |

## Actual

Cursor cloud-agent: spec + collector cut + UI + tests. Оценка S. Ops E2E (health/summary/страница на usage.ragpt.ru) — после merge/redeploy.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-remove-cpa`. Деплой не делался. Файл snapshots.jsonl на volume не трогался.

## 2026-08-25 — build notes

- `collect_cpa` → `collect_state`: только wallet-пробы; `accounts` в payload всегда `[]`.
- Исторические JSONL-строки с полем `accounts` по-прежнему читаются `_extract_deepseek_balance_from_snapshot` / OpenRouter `wallets.openrouter.total_usage`.
- Квота-кеш без трёх wallet-ключей считается stale (старые xAI-записи не блокируют пробы).
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_cpa)` / `code_callers(collect_cpa)` / `code_def(probe_xai_account)` / `code_callers(fetch_usage_from_pg)` / `code_def(probe_deepseek_balance)` / `code_callers(probe_openrouter_wallet)` / `code_def(build_zai_wallet)` / `code_callers(save_state)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — источники с 2026-08-18: wallets; CLIProxy decommissioned; выпиливание из кода = эта задача
- Пакет задачи + чтение: `app.py` (`collect_cpa`, wallet probes), `static/index.html`, `README.md`, `docker-compose.yml`
