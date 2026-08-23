# TASK-usage-dashboard-openrouter-proxy — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-23 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-23 | Spec + plan | ✅ | materialize docs/tasks/… |
| 2026-08-23 | Code proxy/base URL | ✅ | `probe_openrouter_wallet` + `http_request` SOCKS/HTTP + ssl_verify |
| 2026-08-23 | Env/compose/docs | ✅ | compose default London `:8444`; PySocks; `.env.example`; README |
| 2026-08-23 | Tests | ✅ | `python -m unittest discover -s tests -q` — 11 passed |
| 2026-08-23 | gbrain DPI-пометка | ✅ | `projects/usage-dashboard` — блок обходится прокси |
| 2026-08-23 | Ops E2E | ⏳ | после мержа — redeploy Dockhand stack 7 (не в этой ветке) |

## Actual

Cursor cloud-agent: spec + helpers/probe + compose/tests. Оценка S. Ops E2E (карточка на usage.ragpt.ru) — после merge/redeploy.

## 2026-08-23 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-openrouter-proxy`. Деплой не делался.

## 2026-08-23 — build notes

- `OPENROUTER_BASE_URL` / `OPENROUTER_PROXY` / `OPENROUTER_SSL_NO_VERIFY` — только OpenRouter (`/credits`, `/key`, `/keys`). DeepSeek/Z.AI без прокси.
- Compose default origin: `https://100.69.177.71:8444` (London nginx, Tailscale) + `OPENROUTER_SSL_NO_VERIFY=1`.
- Альтернатива: `OPENROUTER_BASE_URL=https://openrouter.ai` + `OPENROUTER_PROXY=socks5h://host.docker.internal:<socks-relay-port>`.
- `via` в probe (base_url + redacted proxy) — для `docker exec … probe_openrouter_wallet()`.
- Секреты не коммитились.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(probe_openrouter_wallet)` / `code_callers(probe_openrouter_wallet)` / `code_def(http_request)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо)
- `get_page(projects/usage-dashboard)` — DPI-блок openrouter.ai с tw-msk egress, wallet в error; Dockhand stack 7
- `get_page(services/openrouter-proxy-london)` — nginx `:8444` на aeza-london-vpn Tailscale `100.69.177.71`
- `get_page(servers/tw-msk-server)` — `socks-relay.service` SOCKS5 на London
- Чтение: `app.py` `http_request` / `probe_openrouter_wallet`; `docker-compose.yml`
