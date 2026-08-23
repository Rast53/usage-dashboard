# TASK-usage-dashboard-openrouter-proxy — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-23 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-23 | Spec + plan | ⏳ | materialize docs/tasks/… |
| 2026-08-23 | Code proxy/base URL | ⏳ | `probe_openrouter_wallet` + `http_request` |
| 2026-08-23 | Env/compose/docs | ⏳ | compose + README; PySocks |
| 2026-08-23 | Tests | ⏳ | unittest, без сети |
| 2026-08-23 | gbrain DPI-пометка | ⏳ | `projects/usage-dashboard` |
| 2026-08-23 | Ops E2E | ⏳ | после мержа — redeploy, не в этой ветке |

## Actual (заполняется при закрытии)

<!-- Пустым при draft. Ops E2E ещё открыт. -->

## 2026-08-23 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-openrouter-proxy`. Build-лог — здесь.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(probe_openrouter_wallet)` / `code_callers(probe_openrouter_wallet)` / `code_def(http_request)` — 0 defs: usage-dashboard не в gbrain code-графе (`.gbrain-source` отсутствует; sources: raclaw-canonical / raclaw-task-mcp / …)
- `get_page(projects/usage-dashboard)` — DPI-блок openrouter.ai с tw-msk egress, wallet в error; Dockhand stack 7
- `get_page(services/openrouter-proxy-london)` — nginx `:8444` на aeza-london-vpn Tailscale `100.69.177.71`
- `get_page(servers/tw-msk-server)` — `socks-relay.service` SOCKS5 на London
- Чтение: `app.py` `http_request` / `probe_openrouter_wallet`; `docker-compose.yml`
