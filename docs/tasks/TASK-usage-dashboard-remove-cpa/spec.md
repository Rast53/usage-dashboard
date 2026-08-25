# TASK-usage-dashboard-remove-cpa — Spec

> S-задача: выпилить мёртвые источники xAI/Codex (CLIProxy + Postgres usage_records) из кода, env и UI usage-dashboard. Wallets (DeepSeek / OpenRouter / Z.AI) продолжают отдавать live-данные. Исторические `snapshots.jsonl` не трогать и не ронять рендер. Деплой не делать.

## Проблема

CLIProxy (auth-files + Postgres `usage_records`) выведен 2026-08-18 (TASK-cliproxy-decommission). Fetch auth-files уже пропущен, `psycopg2` в образ не ставится, compose без этих env — но в `app.py` / UI / README остались коллекторы, карточки «Аккаунты xAI / Codex» и подписи про эти источники.

## Цель

В коде, env и UI не осталось этих источников. Карточки DeepSeek / OpenRouter / Z.AI показывают live-данные. Старые snapshot-строки (с полем `accounts`) по-прежнему читаются для 24h spend.

## Non-goals

- Деплой / смена Dockhand stack env (делает ops после merge).
- Удаление или переписывание `/opt/usage-dashboard/data/snapshots.jsonl`.
- Новые карточки подписок (эпик TASK-usage-dashboard-subscriptions, волна 1).

## Acceptance

1. `grep -i "cpa\|USAGE_PG_DSN\|ORPHAN\|psycopg2" app.py static/index.html README.md docker-compose.yml` → 0 совпадений (кроме, возможно, одной строки-примечания в README об удалении); env-шаблон/compose без `CPA_*`, `USAGE_PG_DSN`, `USAGE_INCLUDE_ORPHAN_USAGE`.
2. В UI нет секции «Аккаунты xAI / Codex» и подписей «по CPA аккаунтам»; карточки DeepSeek/OpenRouter/Z.AI показывают live-данные.
3. После autodeploy (ops, не эта ветка): `GET /api/health` → ok, `/api/summary` отдаёт wallets без errors, страница https://usage.ragpt.ru рендерится, старые snapshots на месте.
4. README описывает только wallets-источники; PR; строка в progress.md о закрытии.
