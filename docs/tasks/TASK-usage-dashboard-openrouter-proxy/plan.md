# TASK-usage-dashboard-openrouter-proxy — Plan

## Phase 1: materialize + helpers

1. `docs/tasks/TASK-usage-dashboard-openrouter-proxy/{spec,plan,progress}.md` из пакета.
2. Pure helpers: `get_openrouter_base_url`, `get_openrouter_proxy`, `openrouter_api_url`, `redact_proxy_url`, `_proxy_handlers`.
3. `http_request` / `http_json`: SOCKS5(h) через PySocks + `ssl_verify` для Tailscale reverse-proxy.

## Phase 2: probe + compose

1. `probe_openrouter_wallet` — все три вызова (`/credits`, `/key`, `/keys`) через base URL + proxy.
2. `docker-compose.yml`: `OPENROUTER_BASE_URL` (default London `:8444`), `OPENROUTER_PROXY`, `OPENROUTER_SSL_NO_VERIFY`; `extra_hosts` для host socks-relay.
3. Dockerfile: PySocks. README: env, без секретов.

## Phase 3: tests

1. Base URL join; proxy redact (userinfo stripped).
2. Probe передаёт proxy + rewritten URL в `http_json` (mock).
3. Без env — `https://openrouter.ai`, proxy None.
4. `python -m unittest discover -s tests -q` зелёный.

## Guardrails

- Только OpenRouter path; DeepSeek/Z.AI не трогать.
- Не деплоить. Не коммитить ключи/реальные proxy-credentials.
