# TASK-alan-openrouter-key-card — Spec

> S-задача (код): key-only режим OpenRouter для инстанса Алана. Деплой не делать.

## Проблема

https://usage.alan.ragpt.ru сейчас только OpenCode Go. Нужна вторая карточка **OpenRouter по ключу Алана**: расход день/неделя/месяц (и лимит, если задан), **без** общего баланса аккаунта Ивана. Management-эндпоинты (`/api/v1/credits`, `/api/v1/keys`, `/api/v1/activity`) на этом ключе не вызывать. Основной https://usage.ragpt.ru не трогать.

## Цель

Один образ, разный env:

- `OPENROUTER_KEY_ONLY=1` — `probe_openrouter_wallet()` ходит только в `GET /api/v1/key`; `ok=True`. Нет вызовов `/api/v1/credits`, `/api/v1/keys`, `/api/v1/activity` (management не трогаем вовсе).
- Поля ключа: `label`, `usage`, `usage_daily` / `usage_weekly` / `usage_monthly`, `limit` / `limit_remaining`.
- Билдер (`build_openrouter_wallet`): `total_usage = key.usage` (кумулятив ключа), чтобы `compute_openrouter_spend_24h/7d` и series продолжали работать от snapshots без правок. `total_credits` / `remaining` остаются `None` и **не** попадают в `remaining_summary`. `remaining_summary` — расход ключа (день/неделя/месяц), стиль существующего `−$X today (UTC, key)`.
- Дефолт (флаг не задан) — поведение как сейчас; основной инстанс usage.ragpt.ru не меняется.
- Секреты: имя переменной ключа остаётся `OPENROUTER_API_KEY` (per-container env). Новых имён / сурсинг-путей не добавлять. `/api/summary` ключи не отдаёт.

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (ops hermes-chuwi **после merge**).
- Менять основной инстанс usage.ragpt.ru (не задавать там `OPENROUTER_KEY_ONLY`).
- Новые имена секретов / чтение openclaw.json Алана из кода.

## Ops (после merge, не эта ветка)

Алан-стек (`dockhand stacks/tw-msk-server/usage-dashboard-alan/docker-compose.alan.yml`):

- `PROVIDERS=opencode-go,openrouter`
- `OPENROUTER_KEY_ONLY=1`
- `OPENROUTER_API_KEY` — значение из openclaw.json контейнера alanclaw-openclaw через Dockhand secret (`is_secret=1`), **не** печатать в логах/чате
- `OPENROUTER_BASE_URL=http://100.69.177.71:8444` (лондонский прокси, как у основного инстанса)
- `SITE_TITLE=Подписки — Алан`
- Редеплой, приёмка.

## Acceptance

1. PR: флаг работает, дефолт не изменён, тесты зелёные (старые + новые); merged.
2. После merge и deploy: https://usage.alan.ragpt.ru → 200 без логина; две карточки: OpenCode Go (как было) + OpenRouter со статистикой ключа (расход день/неделя/месяц, лимит если задан); **нет** общего баланса аккаунта; `/api/summary` не содержит секретов; основной usage.ragpt.ru не изменился.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
