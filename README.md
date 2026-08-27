# usage-dashboard

Multi-provider AI usage dashboard — отслеживание подписок и лимитов.

Live: **https://usage.ragpt.ru**

## Что показывает

Карточный дашборд (не таблица), человеческий язык, мобильная версия.

- **Общая статистика сверху** — расход 24ч, активных, требует внимания, живые источники
- **Карточки провайдеров (гибрид A+B)** — hero-остаток + чипы расхода 24ч/7д (`~` при частичной истории) + sparkline 7–8 дней; allotment-бары окон 5ч/неделя/месяц (used%, warning при >50% выгорания). Z.AI, Command Code GOAT, Kimi Coding, OpenCode Go, DeepSeek, OpenRouter. Плашка плана (GOAT / pro / credits…). Цветовая подсветка: 🔴 критично / 🟡 внимание / 🟢 нормально
- **По моделям** — таблица OpenRouter (модель → spend / req / tokens за 7д) под сеткой карточек; остальные — «нет разбивки от провайдера»
- **Детали по клику** — точные квоты, ключи OpenRouter, балансы DeepSeek. Жаргон — только в разворачиваемом блоке
- **Автообновление** каждые 30с (с сохранением раскрытых карточек)
- Шрифты Inter + mono-цифры; без внешних JS-библиотек

Карточки xAI/Codex сняты: тот источник выведен из эксплуатации 2026-08-18.

## Architecture
```
Browser → Traefik (usage.ragpt.ru)
       → FastAPI :3210
          ├─ DeepSeek API (balance)
          ├─ OpenRouter API (credits) via London reverse-proxy / OPENROUTER_PROXY
          ├─ Z.AI API (quota/limit) via ZAI_PROXY (docker-egress)
          ├─ Command Code API (/alpha/billing/credits) via COMMANDCODE_API_KEY
          ├─ Kimi Coding API (/coding/v1/usages) via KIMI_API_KEY
          └─ OpenCode Go API (/zen/go/v1/usage) via OPENCODE_GO_API_KEY
```

## API
- `GET /api/health` — статус
- `GET /api/summary` — основной endpoint: wallets + errors
- `GET /api/providers` — метаданные источников
- `GET /api/wallets` — DeepSeek + OpenRouter + Z.AI + Command Code + Kimi + OpenCode Go
- `GET /api/quota` — кеш последних wallet-проб
- `POST /api/refresh` — принудительное обновление проб

`GET /api/summary` также отдаёт `site_title` и `enabled_providers` (из env `SITE_TITLE` / `PROVIDERS`). Пустые значения = текущее поведение: заголовок «Мои подписки» и все 6 провайдеров. `display_tz` / `display_tz_label` / `hide_partial_spend_chips` — пояс UI (дефолт UTC; инстанс Алана: `Europe/Moscow` / МСК, без чипов snapshot 24ч/7д).

## Local run
```bash
export DEEPSEEK_API_KEY=...
export OPENROUTER_API_KEY=...
export ZAI_API_KEY=...
export COMMANDCODE_API_KEY=...
export KIMI_API_KEY=...
export OPENCODE_GO_API_KEY=...
export USAGE_PORT=3210
export USAGE_STATIC_DIR=/path/to/static
python3 app.py
```

## Deploy

Live: Dockhand **stack 7** on `tw-msk-server`, `https://usage.ragpt.ru`.
Push to `main` → git webhook → build/recreate. Container `usage-dashboard-usage-dashboard-1`.

Secrets/env: Dockhand `stack_environment_variables` (DEEPSEEK / OPENROUTER×2 / ZAI / COMMANDCODE / KIMI / OPENCODE_GO + `OPENROUTER_BASE_URL` / `OPENROUTER_PROXY` / `OPENROUTER_SSL_NO_VERIFY` + `ZAI_PROXY` + optional `COMMANDCODE_PROXY` / `KIMI_PROXY` / `KIMI_CODE_BASE_URL` / `OPENCODE_GO_PROXY` / `OPENCODE_GO_BASE_URL` + optional `PROVIDERS` / `SITE_TITLE` / `OPENROUTER_KEY_ONLY` / `DISPLAY_TZ` + optional `OPENROUTER_TRACKED_KEY_HASH` / `OPENROUTER_EXPORT_PATH` on stack 7 and `OPENROUTER_IMPORT_PATH` on alan). Do not commit keys or proxy passwords. `ZAI_PROXY`, `COMMANDCODE_API_KEY`, `KIMI_API_KEY` and `OPENCODE_GO_API_KEY` are `is_secret`.

Второй инстанс (после merge, ops): тот же образ, `PROVIDERS=opencode-go,openrouter`, `OPENROUTER_KEY_ONLY=1`, `DISPLAY_TZ=Europe/Moscow`, `SITE_TITLE=Подписки — Алан`, `OPENROUTER_BASE_URL=http://100.69.177.71:8444`, отдельный volume, Traefik `usage.alan.ragpt.ru` **без** basicauth. Основной `usage.ragpt.ru` не задаёт `PROVIDERS` / `SITE_TITLE` / `OPENROUTER_KEY_ONLY` / `DISPLAY_TZ` (дефолт = все 6, OpenRouter credits+management, timestamps UTC). Ключ Алана (`OPENROUTER_API_KEY`, `OPENCODE_GO_API_KEY`) только в Dockhand secret (`is_secret=1`); значение OpenRouter — из openclaw.json контейнера alanclaw-openclaw, не из git.

Data volume: `/opt/usage-dashboard/data` → `/app/data`. Historical `snapshots.jsonl` stays on the volume (24h spend); do not truncate it.

Shared export volume (after this task): `/opt/usage-dashboard/export` → `/app/export` (rw on stack 7, `:ro` on alan stack 8). Host dir is created by ops. Main writes `openrouter_key_models.json` when `OPENROUTER_TRACKED_KEY_HASH` is set; alan reads it. Do not put secrets in that file.

## License
MIT

## Data sources

### DeepSeek
- Balance: `GET https://api.deepseek.com/user/balance`
- 24h / 7d spend: из локальных `snapshots.jsonl` (baseline − current). API не отдаёт историю и **нет разбивки от провайдера**.
- `spend_24h.spent` / `spend_7d.spent` — объект `{CNY, USD}`, не число
- Пробелы: нет точки до окна → `partial` + «частичная история»; нет метрики → «недостаточно истории»

### OpenRouter
- Credits: `GET /api/v1/credits` → remaining ≈ total_credits − total_usage
- Key usage: `GET /api/v1/key` (usage_daily/weekly/monthly)
- Optional all keys: management key `GET /api/v1/keys`
- `OPENROUTER_KEY_ONLY=1` (инстанс Алана): только `GET /api/v1/key`; `/credits` / `/keys` / `/activity` не вызываются. Карточка — расход ключа, без баланса аккаунта. `total_usage` в snapshots = `key.usage`. Unset на usage.ragpt.ru.
- 24h / 7d spend: rolling snapshots of `total_usage`. On the Alan instance (`hide_partial_spend_chips`) the summary «Расход 24ч» is this rolling sum with the window shown in МСК; card chips 24ч/7д stay hidden.
- Per-model: `GET /api/v1/activity` (management key; last 30 completed UTC days; поля `model`, `usage` USD, `requests`, tokens). Verdict 2026-08-25. Нет ключа / 401/403 → «нет разбивки от провайдера».
- Per-model ключа Алана (экспорт): основной инстанс при `OPENROUTER_TRACKED_KEY_HASH` (sha256 ключа, не сам ключ) раз в ≤300с пишет `/app/export/openrouter_key_models.json` из `GET /api/v1/activity?api_key_hash=`. Короткое окно в файле (`usage_24h`) = вчерашние UTC-сутки. Алан-инстанс при `OPENROUTER_KEY_ONLY` читает тот же файл (`OPENROUTER_IMPORT_PATH`); свежий ≤1800с → таблица моделей «вчера / 7 дней / 30 дней» с датами UTC в сноске; нет файла → «нет разбивки от провайдера»; протух → «нет свежих данных экспорта». Activity с алан-контейнера не вызывается. Unset hash на usage.ragpt.ru = поведение без экспорта.
- tw-msk egress: `openrouter.ai` is DPI-blocked. Probe uses `OPENROUTER_BASE_URL` (compose default: London nginx `:8444` over Tailscale `100.69.177.71`) and/or `OPENROUTER_PROXY` (HTTP CONNECT or SOCKS5/SOCKS5h, OpenRouter-only). `OPENROUTER_SSL_NO_VERIFY=1` for HTTPS to the Tailscale IP. Values live in Dockhand stack env — do not commit secrets.

### Z.AI GLM Coding
- Quotas: `GET https://api.z.ai/api/monitor/usage/quota/limit`
- Три лимита: короткий (5ч), недельный, MCP инструменты (месячный)
- Карточка показывает оба процентных лимита сразу; MCP в разворачиваемых деталях
- 24h / 7d: дельта `weekly.currentValue` из snapshots; **нет разбивки от провайдера**
- Key: `ZAI_API_KEY` in Dockhand stack env
- tw-msk docker-egress: прямой `api.z.ai` из контейнера не доходит. Probe uses `ZAI_PROXY` (HTTP CONNECT or SOCKS5/SOCKS5h, Z.AI-only). Value lives in Dockhand stack env as `is_secret` — do not commit the password/userinfo.

### Command Code GOAT
- Credits + rolling windows: `GET https://api.commandcode.ai/alpha/billing/credits` (Bearer Provider API key)
- Optional plan: `GET https://api.commandcode.ai/alpha/billing/subscriptions`
- Карточка: остаток месяца + окна 5ч / неделя (GOAT published: $70 / $14 / $35). 24h/7d из snapshots monthly remaining. **нет разбивки от провайдера**. Нет ключа или API 401/сеть → badge `manual`/`error`, дашборд не падает.
- Key: `COMMANDCODE_API_KEY` in Dockhand stack env (`is_secret`). Do not commit.
- Cookie `/internal/billing/*` is not used.
- Optional `COMMANDCODE_PROXY` if docker-egress to `api.commandcode.ai` fails.

### Kimi Coding
- Weekly quota + rolling 5h window: `GET https://api.kimi.com/coding/v1/usages` (Bearer Kimi Code API key)
- Карточка: недельный пул + короткое окно 5ч. 24h/7д из snapshots `weekly.used`. **нет разбивки от провайдера**. Нет ключа или API 401/сеть → badge `manual`/`error`, дашборд не падает.
- Key: `KIMI_API_KEY` (alias `KIMI_CODE_API_KEY`) in Dockhand stack env (`is_secret`). Do not commit.
- Cookie `GetUsages` / Moonshot Open Platform `api.moonshot.cn` are not used.
- Optional `KIMI_PROXY` if docker-egress to `api.kimi.com` fails. Optional `KIMI_CODE_BASE_URL` (default `https://api.kimi.com/coding/v1`).

### OpenCode Go
- Monthly remaining + rolling 5h / weekly windows: `GET https://opencode.ai/zen/go/v1/usage` (Bearer Go API key)
- Карточка: остаток месяца (и окна 5ч / неделя) + дата reset. 24h/7д из snapshots `monthly.used_usd`. **нет разбивки от провайдера**. На проводе `percent` = used; remaining% = 100 − used. USD — оценка от опубликованных cap'ов ($12 / $30 / $60). Нет ключа или API 401/403/сеть → badge `manual`/`error`, дашборд не падает.
- Key: `OPENCODE_GO_API_KEY` (alias `OPENCODE_API_KEY`) in Dockhand stack env (`is_secret`). Do not commit.
- Cookie `workspace/{id}/go` scrape / Zen balance are not used.
- Optional `OPENCODE_GO_PROXY` if docker-egress to `opencode.ai` fails. Optional `OPENCODE_GO_BASE_URL` (default `https://opencode.ai/zen/go/v1`).
