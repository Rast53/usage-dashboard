# TASK-usage-dashboard-usage-by-model — Plan

## Phase 1: materialize + recon

1. `docs/tasks/TASK-usage-dashboard-usage-by-model/{spec,plan,progress}.md`.
2. Разведка OpenRouter `GET /api/v1/activity` без секрета; verdict в spec.
3. Fixture схемы snapshots 10.07 из `save_state` коммитов 2026-07-10 (volume недоступен из cloud-agent).

## Phase 2: snapshot deltas 24h + 7d

1. Общий проход `snapshots.jsonl` + pick-baseline (до окна / first-in-window / partial / reset).
2. DeepSeek / OpenRouter: сохранить текущий 24h контракт; добавить `spend_7d`.
3. Z.AI / Command Code / Kimi / OpenCode Go: `spend_24h` + `spend_7d` из wallet-полей в snapshots.
4. Старые `accounts[]` (xAI/CPA) не читать как spend текущих подписок — только DeepSeek legacy `quota.balance` / OpenRouter `wallets.total_usage` как сейчас.

## Phase 3: per-model

1. `probe_openrouter_wallet`: `GET /api/v1/activity` management key (тот же proxy/base_url).
2. Агрегат по `model` за ~24ч (сегодня+вчера UTC) и 7д; raw 30d в snapshots не класть.
3. Остальные wallets: `models.available=false`, reason «нет разбивки от провайдера».
4. Ошибка activity не роняет credits-пробу.

## Phase 4: UI

1. Общие `renderSpendBlock` / `renderModelsBlock`.
2. Каждая карточка: расход 24ч и 7д; блок «По моделям».
3. Live-окна волны 1 не убирать.

## Phase 5: tests

1. 7д-дельты; partial; window-reset → spent null.
2. Forward-compat fixture 10.07 — compute + collect не raise.
3. OpenRouter activity mock 200 → items; нет management key → пометка.
4. `python3 -m unittest discover -s tests -q` зелёный.

## Guardrails

- Не деплоить. Не коммитить ключи.
- Не возвращать CPA/Postgres/xAI probes.
- Не ломать существующие spend_24h assertions DeepSeek/OpenRouter.
