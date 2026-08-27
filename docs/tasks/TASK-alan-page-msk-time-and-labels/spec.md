# TASK-alan-page-msk-time-and-labels — Spec

> S-задача (код): страница Алана — московское время, честные подписи окон, скрытие частичных чипов. Деплой не делать.

## Проблема

https://usage.alan.ragpt.ru показывает timestamps в UTC и чипы «Расход ~24ч/7д» из короткой истории snapshots (часто `partial` + `~`). Подписи «сегодня / нед / мес» у ключа OpenRouter читаются как локальные окна, хотя API отдаёт **календарные UTC** сутки / неделю (пн–вс) / месяц. Алан в Москве. Основной https://usage.ragpt.ru не трогать.

## Цель

Один образ, разный env:

- `DISPLAY_TZ` — IANA-пояс для UI. Дефолт: `UTC` (usage.ragpt.ru как сейчас). Пустой + `OPENROUTER_KEY_ONLY=1` → `Europe/Moscow` (инстанс Алана без нового обязательного env).
- Timestamps страницы (`обновлено`, сбросы окон) в выбранном поясе; для Москвы подпись **МСК** (UTC+3, без DST).
- Чипы snapshot «24ч / 7д» (в т.ч. с `~`) **не рендерятся** на инстансе Алана (`hide_partial_spend_chips`).
- Карточка OpenRouter key-only: таблица **вчера / 7 дней / 30 дней / Итого** из полных календарных суток МСК (snapshots `key.usage` / `total_usage`) + `key.usage` как Итого. Неполные окна — «—», без тильды. Пометка про МСК.
- Hero и суммы ключа (`usage_daily` / `usage_weekly` / `usage_monthly`) остаются; подписи окон API честные: сутки/неделя/месяц **UTC**, не «сегодня в Москве».
- Дефолт без флагов = текущее поведение usage.ragpt.ru.

Ключи не в git. `/api/summary` не содержит секретов.

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (ops hermes-chuwi **после merge**, stack 8).
- Менять основной инстанс usage.ragpt.ru (не задавать там `DISPLAY_TZ` / `OPENROUTER_KEY_ONLY`).
- Пересчёт окон OpenRouter API из UTC в МСК (на проводе их нет).

## Ops (после merge, не эта ветка)

Редеплой stack 8 (`docker-compose.alan.yml`). `DISPLAY_TZ` по умолчанию `Europe/Moscow` в alan-compose; при уже выставленном `OPENROUTER_KEY_ONLY=1` код сам выбирает МСК. Основной stack 7 не трогать.

## Acceptance

1. PR: тесты зелёные, GitGuardian чистый, merged.
2. После деплоя stack 8: таблица «вчера/7 дней/30 дней» + Итого + пометка про МСК; timestamps страницы в МСК; чипы «Расход ~24ч/7д» отсутствуют; hero и суммы ключа работают как раньше. usage.ragpt.ru — б/и.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
