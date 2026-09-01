# TASK-alan-commandcode-card — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-commandcode-card/{spec,plan,progress}.md`.

## Phase 2: alan compose

1. `docker-compose.alan.yml`: `PROVIDERS` default `opencode-go,openrouter,commandcode`.
2. Passthrough `COMMANDCODE_API_KEY=${COMMANDCODE_API_KEY:-}` и `COMMANDCODE_PROXY=${COMMANDCODE_PROXY:-}`. Без значений-секретов.
3. Основной `docker-compose.yml` не трогать.

## Phase 3: docs + tests

1. `.env.example` / README: алан-allowlist + слоты ключа/прокси (пустые).
2. Тесты compose-слотов и collect при `PROVIDERS=opencode-go,openrouter,commandcode` (probe commandcode вызывается; deepseek/zai/kimi — нет).
3. `python3 -m unittest discover -s tests -q` зелёный.

## Guardrails

- Не деплоить. Не коммитить ключи / key-shaped литералы в compose/docs.
- Не менять `probe_commandcode_credits` / UI карточки на usage.ragpt.ru.
- `test_openrouter_key_only` с allowlist из двух провайдеров оставить: это контракт key-only, не дефолт алан-стека.
