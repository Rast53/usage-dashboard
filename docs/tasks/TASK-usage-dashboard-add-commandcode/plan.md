# TASK-usage-dashboard-add-commandcode — Plan

## Phase 1: materialize + parse

1. `docs/tasks/TASK-usage-dashboard-add-commandcode/{spec,plan,progress}.md`.
2. Helpers: `get_commandcode_api_key`, optional `get_commandcode_proxy`, parse credits/windows + plan catalog (GOAT/Go/Pro/Max).

## Phase 2: probe + collect

1. `probe_commandcode_credits` → `/alpha/billing/credits` (Bearer), optional `/alpha/billing/subscriptions`.
2. Missing key → `ok: false`, `status: manual`, без HTTP.
3. API/сеть → `ok: false`, `status: error`; исключение в `collect_state` не роняет остальные wallets.
4. `WALLET_PROBE_KEYS` += `commandcode-main`; `build_commandcode_wallet`.

## Phase 3: UI + env

1. Карточка в `static/index.html`: 5ч / неделя / месяц; badge live/error/manual.
2. `classify` / stats включают commandcode.
3. compose + `.env.example` + README: `COMMANDCODE_API_KEY`, optional `COMMANDCODE_PROXY`. Без секретов.

## Phase 4: tests

1. Missing key → manual, zero HTTP.
2. Mock 200 credits (+ optional subscription) → windows + GOAT catalog.
3. 401/timeout → error, дашборд-collect без raise.
4. `python3 -m unittest discover -s tests -q` зелёный.

## Guardrails

- Не деплоить. Не коммитить ключи.
- DeepSeek / OpenRouter / Z.AI path не менять по смыслу (только список wallets/keys).
