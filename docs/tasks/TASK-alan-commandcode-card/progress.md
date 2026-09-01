# TASK-alan-commandcode-card — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-09-01 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-09-01 | Spec + plan | ✅ | materialize; ops usage.alan.ragpt.ru — после merge |
| 2026-09-01 | Alan compose | ✅ | `PROVIDERS` += commandcode; passthrough `COMMANDCODE_API_KEY` / `COMMANDCODE_PROXY` |
| 2026-09-01 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 113 passed |
| 2026-09-01 | Ops E2E | ⏳ | hermes-chuwi после merge: ключ Алана GOAT в stack env + редеплой; деплой не эта ветка |

## Actual

Cursor cloud-agent: карточка Command Code на инстансе Алана через allowlist + compose passthrough. Probe/UI уже в образе (TASK-usage-dashboard-add-commandcode). Оценка S. Деплой не делался.

## 2026-09-01 — build notes

- `docker-compose.alan.yml`: `PROVIDERS=${PROVIDERS:-opencode-go,openrouter,commandcode}`; слоты `COMMANDCODE_API_KEY` / `COMMANDCODE_PROXY` без значений.
- `collect_state` / `probe_commandcode_credits` / карточка UI не менялись. Нет ключа → `manual`; 401/сеть → `error`.
- Основной `docker-compose.yml` / usage.ragpt.ru без правок.
- Тест compose: слоты без секретов; allowlist пробивает commandcode, не DeepSeek/Z.AI/Kimi. Assert `OPENROUTER_BASE_URL` приведён к фактическому дефолту compose (`https://openrouter.ai`, #21).
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(get_enabled_providers)` / `code_def(probe_commandcode_credits)` / `code_callers(get_enabled_providers)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо). Символы читались напрямую: `app.py` `get_enabled_providers` / `probe_commandcode_credits` / `collect_state` / `_PROVIDER_PROBE_SPECS`
- `get_page(projects/usage-dashboard)` — live usage.ragpt.ru, Dockhand stack 7; алан-инстанс stack 8
- `get_page(services/ai-subscriptions)` — Command Code GOAT CRM Id 17; $70 / $14 / $35
- Чтение: `docker-compose.alan.yml`, `docker-compose.yml`, `tests/test_instance_config.py`, `static/index.html` `CARD_ORDER`; пакет задачи
