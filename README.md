# usage-dashboard

Multi-provider AI usage dashboard.

Live: **https://usage.raclaw.ru**

## Now
- CPA multi-account view (xAI/Grok + Codex)
- Live auth status / success / failed / recent sparkline
- Tokens + models from durable Postgres `usage_records` (24h window)

## Not this
- Not SuperGrok native remaining quota
- Not CPA `usage-queue` (ephemeral one-shot queue)

## Architecture
```
Browser → Caddy(usage.raclaw.ru)
       → FastAPI :3210
          ├─ CPA /v0/management/auth-files
          └─ Postgres usage_records (cliproxy-dashboard)
```

## API
- `GET /api/health`
- `GET /api/summary`
- `GET /api/accounts`
- `POST /api/refresh`

## Local run
```bash
export CPA_BASE=http://127.0.0.1:8317
export CPA_MGMT_TOKEN=openclaw
export USAGE_PG_DSN='host=... dbname=cliproxyapi user=... password=...'
export USAGE_PORT=3210
python3 app.py
```

## Deploy
See `DEPLOY.md` in project memory / ops notes.
Host path: `/opt/usage-dashboard` on aeza-helsinki-claw.

## License
MIT

## DeepSeek
- Separate wallet card (not in CPA accounts table)
- Balance: `GET https://api.deepseek.com/user/balance`
- 24h spend: estimated from local `snapshots.jsonl` (baseline − current)
- API has no usage history endpoint
- Endpoint: `GET /api/wallets`

## OpenRouter
- Separate wallet card (not in CPA table)
- Balance: `GET /api/v1/credits` → remaining ≈ total_credits - total_usage
- Key usage: `GET /api/v1/key` (usage_daily/weekly/monthly)
- Optional all keys: management key `GET /api/v1/keys`
- Rolling 24h spend from local snapshots of total_usage (fills in after history exists)

## Z.AI GLM Coding
- Separate wallet card (not CPA table)
- Short 5h + weekly token quotas + monthly MCP tools
- Source: `GET https://api.z.ai/api/monitor/usage/quota/limit`
- Key: `ZAI_API_KEY` in `/opt/usage-dashboard/env`
