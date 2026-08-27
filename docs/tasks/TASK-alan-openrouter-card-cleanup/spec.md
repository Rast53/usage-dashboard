# TASK-alan-openrouter-card-cleanup — Spec

> S-задача (код): rolling-24ч в сводной Алана, чистка карточки OpenRouter, per-model с явными датами. Деплой не делать.

## Проблема

На https://usage.alan.ragpt.ru после TASK-alan-page-msk-time-and-labels и TASK-alan-openrouter-per-model-export:

- сводная «Расход 24ч» читается как календарные сутки, хотя это rolling-окно snapshots;
- карточка OpenRouter key-only несёт мини-таблицу вчера/7/30/Итого — лишний chrome рядом с чипами UTC ключа;
- per-model колонки подписаны «24ч», хотя activity — календарные UTC-дни (на практике вчера, т.к. API отдаёт completed days);
- пометка «экспорт с аккаунта (key-only)» — внутренний жаргон, не нужна Алану.

Основной https://usage.ragpt.ru не трогать.

## Цель

Один образ, разный env (`OPENROUTER_KEY_ONLY` / `DISPLAY_TZ` / `hide_partial_spend_chips`):

1. **Сводная «24ч»** на инстансе Алана = rolling-сумма `spend_24h` (snapshots `key.usage` / `total_usage`) с явным окном в **МСК** (start = now−24ч, end = `updated_at`). Не календарное «вчера». Чипы 24ч/7д на карточках по-прежнему скрыты.
2. **Карточка OpenRouter key-only:** без мини-`<table>`; одна строка окон (вчера / 7 дней / 30 дней) + всего. Те же `spend_calendar` числа (полные сутки МСК, неполные = «—»).
3. **Per-model (key-export):** колонки **вчера / 7 дней / 30 дней**. Короткое окно агрегации = предыдущие UTC-сутки (не today+yesterday). Сноска с явными датами UTC, без «экспорт с аккаунта».
4. Дефолт без флагов = текущее поведение usage.ragpt.ru (чипы 24ч/7д, таблица моделей spend/req/tokens за 7д, сводная без rolling-подписи МСК).

Ключи не в git. `/api/summary` не содержит секретов.

## Non-goals

- Деплой / редеплой stack 8 (ops hermes-chuwi **после merge**).
- Менять основной инстанс usage.ragpt.ru (не задавать там `OPENROUTER_KEY_ONLY` / `DISPLAY_TZ`).
- Пересчёт activity-дней из UTC в МСК (на проводе только UTC date).
- Новые секреты / вызовы `/activity` с алан-контейнера.

## Ops (после merge, не эта ветка)

Редеплой stack 8 (`docker-compose.alan.yml`). Stack 7 без поведенческих правок UI. Приёмка на usage.alan.ragpt.ru; usage.ragpt.ru — б/и.

## Acceptance

1. PR: тесты зелёные, GitGuardian чистый, merged.
2. После деплоя stack 8: сводная «24ч» = rolling-сумма с окном в МСК; карточка без мини-таблицы, одна строка окон + всего; per-model: ВЧЕРА/7 ДНЕЙ/30 ДНЕЙ + даты в сноске; «экспорт с аккаунта» отсутствует; usage.ragpt.ru б/и.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
