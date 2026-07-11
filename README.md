# usage-dashboard

Multi-provider AI usage dashboard — отслеживание подписок и лимитов.

Live: **https://usage.raclaw.ru**

## Что показывает

Карточный дашборд (не таблица), человеческий язык, мобильная версия.

- **Общая статистика сверху** — расход 24ч, активных, требует внимания, токены 24ч
- **Карточки провайдеров** — Z.AI (оба лимита: короткий 5ч + недельный), DeepSeek (баланс), OpenRouter (кредиты). Цветовая подсветка: 🔴 критично / 🟡 внимание / 🟢 нормально
- **Карточки CPA-аккаунтов** (xAI/Grok + Codex) — статус, остаток %, прогресс-бар, req ok/fail, модели
- **Детали по клику** — токены in/out, разбивка по моделям, спарклайны, точная квота, endpoint'ы. Жаргон — только в разворачиваемом блоке
- **Автообновление** каждые 30с (с сохранением раскрытых карточек)

## Architecture
```
Browser → Caddy(usage.raclaw.ru)
       → FastAPI :3210
          ├─ CPA /v0/management/auth-files
          ├─ Postgres usage_records (cliproxyapi)
          ├─ DeepSeek API (balance)
          ├─ OpenRouter API (credits)
          └─ Z.AI API (quota/limit)
```

## API
- `GET /api/health` — статус
- `GET /api/summary` — основной endpoint: accounts + wallets + errors
- `GET /api/accounts` — CPA аккаунты
- `GET /api/providers` — статистика по провайдерам
- `GET /api/wallets` — DeepSeek + OpenRouter + Z.AI
- `GET /api/quota` — кеш квот (xAI probe)
- `POST /api/refresh` — принудительный probe + обновление

## Local run
```bash
export CPA_BASE=http://127.0.0.1:8317
export CPA_MGMT_TOKEN=openclaw
export USAGE_PG_DSN='host=... dbname=cliproxyapi user=... password=...'
export USAGE_PORT=3210
export USAGE_STATIC_DIR=/path/to/static
python3 app.py
```

## Deploy
Хост: `/opt/usage-dashboard` на `aeza-helsinki-claw` (ssh root@100.72.158.83).

Не git-репо — файлы копируются вручную:
```bash
scp static/index.html root@100.72.158.83:/opt/usage-dashboard/static/index.html
ssh root@100.72.158.83 'systemctl restart usage-dashboard.service'
```

Сервис: `usage-dashboard.service` (systemd), порт 3210, behind Caddy.
Env: `/opt/usage-dashboard/env` (CPA_BASE, CPA_MGMT_TOKEN, USAGE_PG_DSN, ZAI_API_KEY, OPENROUTER_API_KEY, DEEPSEEK_API_KEY).

## License
MIT

## Data sources

### CPA аккаунты (xAI/Grok + Codex)
- Auth status: CPA `/v0/management/auth-files`
- Tokens/models: Postgres `usage_records` (24h window, durable)
- Quota: xAI probe `GetGrokCreditsConfig` (SuperGrok/Build remaining% + reset)
- Secondary: `/v1/me` team_blocked; chat rate-limit headers (RPM/TPM)

### DeepSeek
- Balance: `GET https://api.deepseek.com/user/balance`
- 24h spend: из локальных `snapshots.jsonl` (baseline − current). API не отдаёт историю.
- `spend_24h.spent` — объект `{CNY, USD}`, не число

### OpenRouter
- Credits: `GET /api/v1/credits` → remaining ≈ total_credits − total_usage
- Key usage: `GET /api/v1/key` (usage_daily/weekly/monthly)
- Optional all keys: management key `GET /api/v1/keys`
- 24h spend: rolling snapshots of total_usage

### Z.AI GLM Coding
- Quotas: `GET https://api.z.ai/api/monitor/usage/quota/limit`
- Три лимита: короткий (5ч), недельный, MCP инструменты (месячный)
- Карточка показывает оба процентных лимита сразу; MCP в разворачиваемых деталях
- Key: `ZAI_API_KEY` in `/opt/usage-dashboard/env`
