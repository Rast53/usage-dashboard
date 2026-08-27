# TASK-alan-openrouter-card-cleanup — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-openrouter-card-cleanup/{spec,plan,progress}.md`.

## Phase 2: backend

1. `aggregate_openrouter_key_models`: короткое окно = вчерашние UTC-сутки (поле `usage_24h` в schema 1 без смены имени). `aggregate_openrouter_models` (аккаунт, usage.ragpt.ru) не трогать.
2. В экспорт/импорт — `windows` (yesterday / 7d / 30d from–to, tz=UTC) и note с датами. Старый файл без `windows` — даты от `updated_at`.
3. `spend_calendar.note` — те же окна с датами МСК (карточка).
4. Константа «экспорт с аккаунта (key-only)» убирается.

## Phase 3: UI

1. Сводная: при `hide_partial_spend_chips` подпись «rolling 24ч · start – end» через `fmtDateShort` (МСК). Иначе — текущий текст usage.ragpt.ru.
2. Карточка: `renderSpendCalendar` → строка `.win-row`, не `<table class="cal">`.
3. Per-model export: заголовки вчера / 7 дней / 30 дней; сноска = `models.note` с датами; fallback без «экспорт с аккаунта».

## Phase 4: tests / docs

1. Контракт HTML: нет мини-таблицы и «экспорт с аккаунта»; есть win-row, ВЧЕРА/7 ДНЕЙ/30 ДНЕЙ (uppercase CSS), rolling-подпись.
2. Агрегация: gemini yesterday-only в `usage_24h`; windows+note; дефолт UTC-инстанса без изменений.
3. README. Старые тесты зелёные.

## Guardrails

- Не деплоить. Не коммитить ключи.
- usage.ragpt.ru: флаги не заданы = текущее поведение.
