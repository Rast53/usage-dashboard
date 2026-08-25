# TASK-usage-dashboard-remove-cpa — Plan

## Подход

1. Заменить `collect_cpa` на `collect_state`: только wallet-пробы (DeepSeek / OpenRouter / Z.AI) + сборка `wallets`.
2. Удалить коллекторы xAI/Codex/Postgres, proto/gRPC grok credits, auth-file loaders, `psycopg2`, связанные env.
3. UI: убрать секцию аккаунтов и CPA-классификацию; статистика только по wallets.
4. `save_state` пишет `wallets` (и пустой `accounts` для стабильности схемы JSONL). Файл snapshots не трогать.
5. `_extract_deepseek_balance_from_snapshot` уже читает исторические `accounts` — оставить fallback.
6. Тесты: collect_state + чтение старых snapshot-строк. Существующий OpenRouter suite зелёный.
