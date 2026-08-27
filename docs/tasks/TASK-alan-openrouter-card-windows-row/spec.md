# TASK-alan-openrouter-card-windows-row — Spec

> S-задача (код): убрать пустую строку вчера/7д/30д с карточки OpenRouter на инстансе Алана. Деплой не делать.

## Проблема

https://usage.alan.ragpt.ru на карточке OpenRouter рисует таблицу календарных окон (CSS `text-transform: uppercase` → **ВЧЕРА / 7 ДНЕЙ / 30 ДНЕЙ**) с «—» во всех ячейках: snapshots инстанса короче полных суток МСК. Чипы ключа (сутки/неделя/месяц UTC) и Итого в деталях уже есть. Пустая строка шумит. Основной https://usage.ragpt.ru не трогать.

## Цель

- `renderSpendCalendar`: не рендерить таблицу, если вчера / 7 дней / 30 дней все `spent=null` или `partial` (как на живом Алане).
- Если часть окон заполнена — показывать только заполненные колонки + Итого; пустые «—» не держать.
- Backend `spend_calendar` / `compute_openrouter_calendar_spend` без смены контракта: данные как были, только UI не показывает пустую строку.
- Дефолт без `hide_partial_spend_chips` = usage.ragpt.ru как сейчас (таблица не вызывается).

Ключи не в git. `/api/summary` не содержит секретов.

## Non-goals

- Деплой / запись Dockhand stack env (ops hermes-chuwi **после merge**).
- Менять основной инстанс usage.ragpt.ru.
- Пересчёт окон из snapshots в UTC или подстановка totals из per-model экспорта на эту строку.
- Убирать чипы «сутки/нед/мес UTC» и hero ключа.

## Ops (после merge, не эта ветка)

Редеплой stack 8 (`docker-compose.alan.yml`). Основной stack 7 не трогать.

## Acceptance

1. PR: тесты зелёные; на карточке OpenRouter нет пустой строки ВЧЕРА/7Д/30Д при неполных snapshots; при полной истории таблица с числами остаётся; usage.ragpt.ru б/и.
2. После деплоя stack 8: https://usage.alan.ragpt.ru — карточка OpenRouter без пустых «—»-окон; чипы ключа UTC на месте.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
