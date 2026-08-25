# TASK-usage-dashboard-zai-proxy — Spec

> S-задача: Z.AI-карточка на usage-dashboard после переезда на tw-msk падает: прямой docker-egress на `api.z.ai` не доходит. Починить через `ZAI_PROXY` (HTTP CONNECT / SOCKS5). Деплой не делать.

## Проблема

usage-dashboard живёт на [[servers/tw-msk-server]] (`https://usage.ragpt.ru`). Из контейнера прямой egress на `api.z.ai` не работает: карточка Z.AI в error, `probe_zai_quota()` → `"ok": false`.

OpenRouter уже ходит через `OPENROUTER_BASE_URL` / `OPENROUTER_PROXY`. Z.AI по-прежнему дергает `https://api.z.ai/api/monitor/usage/quota/limit` напрямую, без прокси. `http_request` уже умеет HTTP CONNECT и SOCKS5(h) (в т.ч. с userinfo).

## Цель

После merge (и последующего redeploy ops) карточка Z.AI показывает лимиты (5ч + недельный) без error. `/api/summary` → `wallets.zai.ok: true`. `ZAI_PROXY` живёт в Dockhand `stack_environment_variables` с `is_secret` (пароль/userinfo не в git).

## Решение

- `ZAI_PROXY` — HTTP(S) CONNECT или SOCKS5/SOCKS5h **только** для Z.AI (не DeepSeek/OpenRouter).
- Значение — в Dockhand env (`is_secret`); compose пробрасывает `${ZAI_PROXY:-}` без дефолта с credentials.
- Probe пишет `via.proxy` через `redact_proxy_url` (userinfo срезается).
- Origin остаётся `https://api.z.ai` (отдельного reverse-proxy нет).

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (делает ops после merge).
- Прокси для DeepSeek / OpenRouter.
- Смена URL квоты / UI карточки.

## Acceptance

1. После redeploy на https://usage.ragpt.ru карточка Z.AI показывает лимиты (5ч + недельный) без error; `zai ok:true` в `/api/summary`.
2. Пароль не в git; `ZAI_PROXY` в Dockhand env (`is_secret`); деплой через autodeploy.
3. В `progress.md` строка о закрытии.
