# TASK-usage-dashboard-add-opencode-go — Plan

## Phase 1: materialize + parse

1. `docs/tasks/TASK-usage-dashboard-add-opencode-go/{spec,plan,progress}.md`.
2. Helpers: `get_opencode_go_api_key`, optional `get_opencode_go_proxy` / `get_opencode_go_base_url`, parse `usage.{rolling,weekly,monthly}`.

## Phase 2: probe + collect

1. `probe_opencode_go_usage` → `GET {base}/usage` (Bearer).
2. Missing key → `ok: false`, `status: manual`, без HTTP.
3. API/сеть → `ok: false`, `status: error`; исключение в `collect_state` не роняет остальные wallets.
4. `WALLET_PROBE_KEYS` += `opencode-go-main`; `build_opencode_go_wallet`.

## Phase 3: UI + env

1. Карточка в `static/index.html`: 5ч / неделя / месяц; дата reset; badge live/error/manual.
2. `classify` / stats включают opencode-go.
3. compose + `.env.example` + README: `OPENCODE_GO_API_KEY`, optional `OPENCODE_GO_PROXY` / `OPENCODE_GO_BASE_URL`. Без секретов.

## Phase 4: tests

1. Missing key → manual, zero HTTP.
2. Mock 200 usage (current `{usage.{rolling,weekly,monthly}.{percent,resetsAt}}`) → remaining% + reset; redacted proxy.
3. 401/403/timeout → error, дашборд-collect без raise.
4. `python3 -m unittest discover -s tests -q` зелёный.

## Guardrails

- Не деплоить. Не коммитить ключи.
- DeepSeek / OpenRouter / Z.AI / Command Code / Kimi path не менять по смыслу (только список wallets/keys).
- Cookie scrape не добавлять.
