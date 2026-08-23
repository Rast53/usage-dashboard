# TASK-usage-dashboard-openrouter-proxy — Spec

> S-задача: OpenRouter-карточка на usage-dashboard после переезда на tw-msk падает из‑за DPI-блока `openrouter.ai`. Починить через существующий London reverse-proxy / HTTP(S)/SOCKS egress. Деплой не делать.

## Проблема

usage-dashboard живёт на [[servers/tw-msk-server]] (`https://usage.ragpt.ru`). Прямой egress на `openrouter.ai` с tw-msk режется DPI: карточка OpenRouter в error, `probe_openrouter_wallet()` → `"ok": false`.

На [[servers/aeza-london-vpn]] уже есть выделенный reverse-proxy OpenRouter: nginx `:8444` (Tailscale `100.69.177.71`). На tw-msk — `socks-relay.service` (SOCKS5 на London). Код дашборда ходит на `https://openrouter.ai/api/v1/*` напрямую и прокси не использует.

## Цель

После merge (и последующего redeploy ops) карточка OpenRouter показывает credits/remaining без error. `probe_openrouter_wallet()` возвращает `"ok": true`. Пометка DPI-блока в gbrain `projects/usage-dashboard` обновлена.

## Решение

- `OPENROUTER_BASE_URL` — origin для credits/key/keys (default в коде `https://openrouter.ai`; в compose tw-msk — London nginx `:8444` по Tailscale).
- `OPENROUTER_PROXY` — HTTP(S) CONNECT или SOCKS5/SOCKS5h **только** для OpenRouter (не DeepSeek/Z.AI).
- `OPENROUTER_SSL_NO_VERIFY` — для HTTPS к Tailscale-IP reverse-proxy (сертификат не на IP).
- Прокси/base URL читаются из env; секреты не коммитить. Значения — в Dockhand `stack_environment_variables`.

## Non-goals

- Деплой / смена Dockhand stack env на живом хосте (делает ops после merge).
- Прокси для DeepSeek / Z.AI / GitHub.
- Выпиливание CPA-кода (отдельная задача).

## Acceptance

1. После redeploy на https://usage.ragpt.ru карточка OpenRouter показывает credits/remaining без error.
2. `docker exec usage-dashboard-usage-dashboard-1 python -c "…probe_openrouter_wallet…"` → `"ok": true` (или curl `/api/wallets`).
3. В `progress.md` строка о закрытии; в gbrain `projects/usage-dashboard` убрана/обновлена пометка про DPI-блок openrouter.
