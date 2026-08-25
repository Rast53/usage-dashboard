# TASK-usage-dashboard-zai-proxy — Plan

## Phase 1: materialize + helpers

1. `docs/tasks/TASK-usage-dashboard-zai-proxy/{spec,plan,progress}.md` из пакета.
2. Helper `get_zai_proxy` (env `ZAI_PROXY`, пусто → None). Reuse `_proxy_handlers` / `redact_proxy_url`.

## Phase 2: probe + compose

1. `probe_zai_quota` — quota/limit + subscription/list через `proxy=get_zai_proxy()`.
2. `build_zai_wallet` пробрасывает `via`.
3. `docker-compose.yml`: `ZAI_PROXY=${ZAI_PROXY:-}`; `.env.example` / README без секретов.

## Phase 3: tests

1. Без env — proxy None, URL `https://api.z.ai/...`.
2. С `ZAI_PROXY` probe передаёт proxy в `http_json` (mock); `via.proxy` без userinfo.
3. `python -m unittest discover -s tests -q` зелёный.

## Guardrails

- Только Z.AI path; DeepSeek/OpenRouter не трогать.
- Не деплоить. Не коммитить ключи / proxy-credentials.
