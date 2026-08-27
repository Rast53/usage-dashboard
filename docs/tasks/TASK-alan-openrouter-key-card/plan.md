# TASK-alan-openrouter-key-card — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-openrouter-key-card/{spec,plan,progress}.md`.

## Phase 2: probe + builder

1. `_env_flag("OPENROUTER_KEY_ONLY")` — дефолт false.
2. `probe_openrouter_wallet()`: при флаге только `GET /api/v1/key`; не звать credits / keys / activity и не читать management key.
3. `build_openrouter_wallet()`: при флаге `total_usage = key.usage`; `total_credits`/`remaining` = None; `remaining_summary` из дневных/недельных/месячных сумм ключа.
4. Дефолтная ветка probe/builder без поведенческих правок.

## Phase 3: UI

1. Карточка OpenRouter без `remaining`/`total_credits`: hero и детали по ключу (день/неделя/месяц, лимит если задан). Не рендерить баланс аккаунта.
2. Дефолт (есть remaining) — текущий credits-hero / credits-bar / details.

## Phase 4: env / compose / tests

1. `docker-compose.alan.yml`: PROVIDERS + OpenRouter key-only слоты без секретов. Основной `docker-compose.yml` не получает `OPENROUTER_KEY_ONLY=1`.
2. `.env.example` / README: слот флага, без новых имён ключа.
3. Тесты: контракт probe+builder (нет полей аккаунта, есть дневные суммы); management не дергается; старые тесты зелёные.

## Guardrails

- Не деплоить. Не коммитить ключи.
- Основной инстанс: флаг не задан = текущее поведение.
