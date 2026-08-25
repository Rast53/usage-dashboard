# TASK-usage-dashboard-redesign — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-usage-dashboard-redesign/{spec,plan,progress}.md`.
2. Sources: пакет задачи + `research/2026-08-25_usage-dashboard-design` (гибрид A+B). AGENTMAP.md в репо нет.

## Phase 2: spend_series_7d

1. Общий `compute_spend_series_7d(points, current, direction, unit)` — 8 UTC-дней, честный partial/reset/no-history.
2. Обёртки DeepSeek / OpenRouter / Z.AI / Command Code / Kimi / OpenCode Go из тех же extractors, что window-spend.
3. Поле на каждом wallet в `build_*_wallet`. Не менять shape `spend_24h`/`spend_7d`.

## Phase 3: UI hybrid A+B

1. `static/index.html`: Inter + mono, градиенты, hero, чипы, sparkline SVG, allotment used%-бары, таблица моделей под сеткой.
2. Общий рендер карточки; детали (MCP, ключи, точные квоты) остаются в toggle.
3. 390px: 1 колонка, таблица `overflow-x: auto`.

## Phase 4: tests + shots

1. Серия: полные дни, partial, no-history, window-reset → spent null, collect_state ключ есть.
2. UI copy: Inter, sparkline, нет `<script src`, нет CPA.
3. pytest зелёный. Скриншоты 1280/390 против локального fixture `/api/summary`.
4. README: описание гибрида.

## Guardrails

- Не деплоить. Не коммитить ключи.
- Не менять Dockerfile / docker-compose.yml.
- Не ломать spend_24h / spend_7d assertions.
