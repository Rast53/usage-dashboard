# TASK-alan-usage-page — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-usage-page/{spec,plan,progress}.md`.

## Phase 2: env + collect

1. `get_enabled_providers()` / `get_site_title()`.
2. `collect_state` пробит только allowlist; cache-stale смотрит только их probe-keys.
3. `/api/summary` отдаёт `site_title`, `enabled_providers`, отфильтрованные wallets.
4. `/` подставляет `SITE_TITLE` в `<title>` и `<h1>`.

## Phase 3: UI

1. `applySiteTitle` из `/api/summary`.
2. Hero: счётчики и подписи источников по фактическим wallets (не хардкод 6 имён).
3. Per-model остаётся в деталях OpenRouter; без этого wallet секция не рендерится.
4. Дефолт 6 карточек / «DeepSeek + OpenRouter · 7д на карточках» без изменения.

## Phase 4: tests + docs

1. PROVIDERS=opencode-go: чужие probes не вызываются; summary только `opencode-go`; ключ не в JSON.
2. Без env: 6 wallets, как сейчас.
3. Рендер-контракт: нет литерала «6 имён» в stats; `SITE_TITLE` в HTML.
4. compose / `.env.example` / README: слоты без секретов. Второй сервис в compose **не** добавлять (stack 7 = usage.ragpt.ru).

## Guardrails

- Не деплоить. Не коммитить ключи.
- Основной инстанс: пустые `PROVIDERS`/`SITE_TITLE` = текущее поведение.
