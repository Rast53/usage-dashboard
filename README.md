# usage-dashboard

Multi-provider AI usage dashboard — отслеживание подписок и лимитов.

Live: **https://usage.ragpt.ru**

## Что показывает

Карточный дашборд (не таблица), человеческий язык, мобильная версия.

- **Общая статистика сверху** — расход 24ч, активных, требует внимания, живые источники
- **Карточки провайдеров** — Z.AI (оба лимита: короткий 5ч + недельный), DeepSeek (баланс), OpenRouter (кредиты). Цветовая подсветка: 🔴 критично / 🟡 внимание / 🟢 нормально
- **Детали по клику** — точные квоты, ключи OpenRouter, балансы DeepSeek. Жаргон — только в разворачиваемом блоке
- **Автообновление** каждые 30с (с сохранением раскрытых карточек)

Карточки xAI/Codex сняты: тот источник выведен из эксплуатации 2026-08-18.

## Architecture
```
Browser → Traefik (usage.ragpt.ru)
       → FastAPI :3210
          ├─ DeepSeek API (balance)
          ├─ OpenRouter API (credits) via London reverse-proxy / OPENROUTER_PROXY
          └─ Z.AI API (quota/limit)
```

## API
- `GET /api/health` — статус
- `GET /api/summary` — основной endpoint: wallets + errors
- `GET /api/providers` — метаданные источников
- `GET /api/wallets` — DeepSeek + OpenRouter + Z.AI
- `GET /api/quota` — кеш последних wallet-проб
- `POST /api/refresh` — принудительное обновление проб

## Local run
```bash
export DEEPSEEK_API_KEY=...
export OPENROUTER_API_KEY=...
export ZAI_API_KEY=...
export USAGE_PORT=3210
export USAGE_STATIC_DIR=/path/to/static
python3 app.py
```

## Deploy

Live: Dockhand **stack 7** on `tw-msk-server`, `https://usage.ragpt.ru`.
Push to `main` → git webhook → build/recreate. Container `usage-dashboard-usage-dashboard-1`.

Secrets/env: Dockhand `stack_environment_variables` (DEEPSEEK / OPENROUTER×2 / ZAI + `OPENROUTER_BASE_URL` / `OPENROUTER_PROXY` / `OPENROUTER_SSL_NO_VERIFY`). Do not commit keys.

Data volume: `/opt/usage-dashboard/data` → `/app/data`. Historical `snapshots.jsonl` stays on the volume (24h spend); do not truncate it.

## License
MIT

## Data sources

### DeepSeek
- Balance: `GET https://api.deepseek.com/user/balance`
- 24h spend: из локальных `snapshots.jsonl` (baseline − current). API не отдаёт историю.
- `spend_24h.spent` — объект `{CNY, USD}`, не число

### OpenRouter
- Credits: `GET /api/v1/credits` → remaining ≈ total_credits − total_usage
- Key usage: `GET /api/v1/key` (usage_daily/weekly/monthly)
- Optional all keys: management key `GET /api/v1/keys`
- 24h spend: rolling snapshots of total_usage
- tw-msk egress: `openrouter.ai` is DPI-blocked. Probe uses `OPENROUTER_BASE_URL` (compose default: London nginx `:8444` over Tailscale `100.69.177.71`) and/or `OPENROUTER_PROXY` (HTTP CONNECT or SOCKS5/SOCKS5h, OpenRouter-only). `OPENROUTER_SSL_NO_VERIFY=1` for HTTPS to the Tailscale IP. Values live in Dockhand stack env — do not commit secrets.

### Z.AI GLM Coding
- Quotas: `GET https://api.z.ai/api/monitor/usage/quota/limit`
- Три лимита: короткий (5ч), недельный, MCP инструменты (месячный)
- Карточка показывает оба процентных лимита сразу; MCP в разворачиваемых деталях
- Key: `ZAI_API_KEY` in Dockhand stack env
