# TASK-alan-page-msk-time-and-labels — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-page-msk-time-and-labels/{spec,plan,progress}.md`.

## Phase 2: backend

1. `DISPLAY_TZ` / `get_display_tz()`: пустой → UTC; `OPENROUTER_KEY_ONLY=1` без явного пояса → `Europe/Moscow`. Фиксированный UTC+3 (`MSK`), без зависимости от tzdata в slim-образе.
2. `/api/summary`: `display_tz`, `display_tz_label`, `hide_partial_spend_chips`.
3. `compute_spend_series_7d(..., tz=, days=)` — опциональный пояс, дефолт UTC (sparkline основного инстанса без изменений).
4. `compute_openrouter_calendar_spend()`: 31 сутки МСК; вчера / 7 / 30 = только **полные** дни (сегодня не входит); Итого = `key.usage`.
5. Key-only `remaining_summary`: «сутки UTC / неделя UTC (пн–вс) / месяц UTC».

## Phase 3: UI

1. `fmtDateTime` / `fmtDateShort` — UTC-ветка как сейчас; иначе Intl + подпись МСК.
2. `hide_partial_spend_chips` → не звать `spendChip('24ч'|'7д')`.
3. Таблица календарных окон на карточке OpenRouter key-only + note про МСК.
4. Чипы/hero/детали ключа: честные UTC-подписи, числа те же.

## Phase 4: env / tests

1. `docker-compose.alan.yml`: `DISPLAY_TZ=${DISPLAY_TZ:-Europe/Moscow}`. Основной compose без пояса.
2. `.env.example` / README.
3. Тесты: дефолт UTC + чипы 24ч; key-only → МСК, нет чипов 24ч/7д, таблица, Итого; календарь полных суток; старые тесты зелёные.

## Guardrails

- Не деплоить. Не коммитить ключи.
- usage.ragpt.ru: флаги не заданы = текущее поведение.
