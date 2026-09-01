# TASK-alan-commandcode-card — Spec

> S-задача (код): карточка Command Code GOAT на инстансе Алана (usage.alan.ragpt.ru). Деплой не делать.

## Проблема

https://usage.alan.ragpt.ru сейчас OpenCode Go + OpenRouter (key-only). С 01.09 у Алана подписка **Command Code GOAT** — нужна третья карточка с live-остатком/окнами, без карточек Ивана (DeepSeek / Z.AI / Kimi) и без общего баланса OpenRouter. Основной https://usage.ragpt.ru не трогать: Command Code там уже есть (TASK-usage-dashboard-add-commandcode).

## Цель

Один образ, разный env:

- `PROVIDERS` дефолт алан-стека: `opencode-go,openrouter,commandcode`.
- `COMMANDCODE_API_KEY` и optional `COMMANDCODE_PROXY` — passthrough в `docker-compose.alan.yml` (как `OPENCODE_GO_*` / `OPENROUTER_*`). Значения только в Dockhand stack env (`is_secret` для ключа). Не коммитить.
- Probe/UI карточки уже в образе: `probe_commandcode_credits` → `/alpha/billing/credits` (+ optional subscriptions). Нет ключа → `manual`; 401/сеть → `error`; дашборд не падает.
- Основной `docker-compose.yml` / usage.ragpt.ru не менять (там слоты уже есть).

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (ops hermes-chuwi **после merge**).
- Менять основной инстанс usage.ragpt.ru.
- Новая probe-логика / cookie `/internal/billing/*`.
- Копирование remaining% в CRM/gbrain.

## Ops (после merge, не эта ветка)

Алан-стек (`dockhand stacks/tw-msk-server/usage-dashboard-alan/docker-compose.alan.yml`):

- `PROVIDERS=opencode-go,openrouter,commandcode` (compose default)
- `COMMANDCODE_API_KEY` — ключ подписки Алана GOAT (Dockhand `is_secret=1`), **не** печатать в логах/чате
- optional `COMMANDCODE_PROXY` если `api.commandcode.ai` недоступен из контейнера
- Редеплой, приёмка на https://usage.alan.ragpt.ru

## Acceptance

1. PR: `docker-compose.alan.yml` содержит passthrough `COMMANDCODE_API_KEY` и `COMMANDCODE_PROXY`; allowlist включает `commandcode`; тесты зелёные (`python -m unittest`); GitGuardian зелёный (никаких key-shaped литералов); merged.
2. После merge и deploy: https://usage.alan.ragpt.ru → три карточки (OpenCode Go, OpenRouter key-only, Command Code GOAT); `/api/summary` без секретов; usage.ragpt.ru б/и.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
