# TASK-usage-dashboard-redesign — Spec

> Волна дизайн-имплементации эпика TASK-usage-dashboard-subscriptions: `static/index.html` → гибрид A+B (финтех-портфель + dev-usage админка). Деплой не делать. Compose/Dockerfile не трогать.

## Проблема

На https://usage.ragpt.ru шесть карточек подписок с live-окнами и дельтами 24ч/7д, но визуально это плоский список лимитов. Research 2026-08-25 (`research/2026-08-25_usage-dashboard-design`) рекомендовал **гибрид A+B**; Иван выбрал его. Нет hero-остатка, нет sparkline 7д, allotment-бары не показывают выгорание used%, per-model OpenRouter спрятан в «деталях», нет Inter/mono-цифр.

## Цель

После merge на дашборде:

- карточка = «счёт» (A): крупный остаток, подпись контекста, чипы 24ч/7д, sparkline 7–8 дней, градиент per provider, плашка плана;
- окна квот = allotment-бары выгорания (B): used%, warning при >50% израсходовано, подпись «осталось N% (окно) · used / cap»;
- per-model таблица OpenRouter **под сеткой** карточек (модель → spend / req / tokens за 7д, mono, числа вправо);
- `/api/summary` отдаёт `spend_series_7d` там, где хватает snapshots; partial-флаги честные.

Ключи не в git. Autoupdate 30с, русские подписи, 390px, все 6 провайдеров, состояния ok/error/частичная история.

## Решение

### API — `spend_series_7d`

На каждом wallet в `/api/summary`, рядом с `spend_24h` / `spend_7d`:

```json
{
  "days": 8,
  "partial": true,
  "gap": null,
  "unit": "$",
  "points": [
    {"date": "2026-08-18", "spent": 1.2, "partial": false},
    {"date": "2026-08-19", "spent": null, "partial": true}
  ]
}
```

- 8 UTC-дней включая сегодня. Daily spent = дельта метрики между последней точкой суток и baseline (последняя точка до 00:00 UTC).
- Нет точек за день → `spent: null`, `partial: true` (не выдумываем 0).
- Нет baseline до дня, но есть ≥2 точки внутри → дельта + `partial`.
- Одна точка без baseline → `spent: null` (недостаточно для дневной дельты).
- Отрицательная дельта (сброс окна / refund) → `spent: null`, `gap: "window-reset"` на точке.
- Нет двух точек с метрикой вообще → `points: []`, `gap: "no-history"`.
- DeepSeek: скаляр CNY (иначе USD); unit `¥`/`$`.
- Направление как у window-spend: usage/used ↑ = расход; remaining/balance ↓ = расход.

Контракт `spend_24h` / `spend_7d` не ломаем.

### UI — гибрид A+B

**A (карточка-счёт):**

| Элемент | Поведение |
|---|---|
| Hero | Крупный остаток: OR `$remaining`, DS `¥/ $` баланс, Z.AI weekly remaining%, CC monthly `$`, Kimi weekly remaining%, Go monthly `$` |
| Контекст | «из $470 кредитов» / «недельная квота» / «из ¥top-up» |
| Чипы 24ч / 7д | число дельты; `~` при `partial`; «нет истории» если spent нет / gap |
| Sparkline | inline SVG polyline, без библиотек; только если в серии есть числа |
| Градиент | заливка карточки per provider |
| Плашка | GOAT / pro / Moderato / Go / credits / error / manual |

**B (админка usage):**

- Allotment-бары 5ч / неделя / месяц **где есть**. Ширина = **used%**. Цвет warn при used > 50%, bad при used ≥ 90% или remaining ≤ 0.
- Подпись вида «осталось 60% (месяц) · $41.94 / $70.00».
- Секция «По моделям» под сеткой: таблица OpenRouter 7д. На 390px — горизонтальный скролл. Нет разбивки → явная причина.

Шрифты: Inter (карточки) + mono-стек на цифры/таблицу. Google Fonts link допустим. `<script src=` внешних JS нет.

Карточки в одну колонку при `max-width: 390px` (и текущий 720px breakpoint).

### Сохранить

Автообновление 30с (раскрытые карточки), русский UI, 6 провайдеров, ok/error/partial, live-окна волны 1, без CPA.

## Non-goals

- Деплой / Dockhand env / смена compose/Dockerfile (L3).
- Карточка Cursor.
- Внешние JS-чарты.
- Возврат CPA/Postgres.

## Acceptance

1. `/api/summary` отдаёт `spend_series_7d` там, где хватает данных; partial честные; pytest зелёный (старые + новые).
2. UI = гибрид A+B; 390px одна колонка; per-model таблица читаема.
3. PR: скриншоты desktop 1280 + mobile 390 реальной страницы против локальных данных.
4. Без внешних JS-зависимостей; ключи не трогаем; compose/Dockerfile не меняем.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
