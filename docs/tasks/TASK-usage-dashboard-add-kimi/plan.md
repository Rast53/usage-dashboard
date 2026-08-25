# TASK-usage-dashboard-add-kimi — Plan

## Phase 1: materialize + parse

1. `docs/tasks/TASK-usage-dashboard-add-kimi/{spec,plan,progress}.md`.
2. Helpers: `get_kimi_api_key`, optional `get_kimi_proxy` / `get_kimi_code_base_url`, parse `usage` + 5h `limits[]`.

## Phase 2: probe + collect

1. `probe_kimi_usage` → `GET {base}/usages` (Bearer).
2. Missing key → `ok: false`, `status: manual`, без HTTP.
3. API/сеть → `ok: false`, `status: error`; исключение в `collect_state` не роняет остальные wallets.
4. `WALLET_PROBE_KEYS` += `kimi-main`; `build_kimi_wallet`.

## Phase 3: UI + env

1. Карточка в `static/index.html`: 5ч / неделя; badge live/error/manual.
2. `classify` / stats включают kimi.
3. compose + `.env.example` + README: `KIMI_API_KEY`, optional `KIMI_PROXY` / `KIMI_CODE_BASE_URL`. Без секретов.

## Phase 4: tests

1. Missing key → manual, zero HTTP.
2. Mock 200 usages → weekly + 5h; redacted proxy.
3. 401/timeout → error, дашборд-collect без raise.
4. `python3 -m unittest discover -s tests -q` зелёный.

## Guardrails

- Не деплоить. Не коммитить ключи.
- DeepSeek / OpenRouter / Z.AI / Command Code path не менять по смыслу (только список wallets/keys).
