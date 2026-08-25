# TASK-usage-dashboard-usage-by-model — Spec

> Волна 2 эпика TASK-usage-dashboard-subscriptions: расход по каждой подписке (24ч и 7д) из snapshots-дельт + live-окна волны 1; per-model там, где provider API её отдаёт. Без CPA-кода. Деплой не делать.

## Проблема

После волны 0 (remove-cpa) и волны 1 (карточки Command Code / Kimi / OpenCode Go) на https://usage.ragpt.ru видны **остатки** квот, но **расход за окно** есть только у DeepSeek и OpenRouter (24ч из `snapshots.jsonl`). 7д нет. Per-model разбивки нет. Исторические JSONL-строки с 10.07.2026 (accounts xAI + ранние wallets) не должны ронять рендер.

## Цель

После merge (и последующего redeploy ops) на каждой карточке подписки виден расход **24ч** и **7д** (где хватает истории) из snapshots-дельт; live-окна волны 1 (5ч / неделя / месяц) остаются. OpenRouter показывает per-model, если activity API ответил; остальные карточки явно помечают «нет разбивки от провайдера». Дашборд не падает на старых snapshots. Ключи не в git.

## Разведка OpenRouter per-model (2026-08-25)

Пробы **без секрета** с этой cloud-сессии (`GET`, `Accept: application/json`, UA `usage-dashboard/1.0 recon`). Origin `https://openrouter.ai` с агента доступен.

| URL | Auth contract | Без ключа | Мусорный Bearer | Что отдаёт |
|---|---|---|---|---|
| `GET https://openrouter.ai/api/v1/activity` | Bearer **management key** (docs: [Get user activity](https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity-grouped-by-endpoint)) | **401** `No cookie auth credentials found` | **401** `User not found.` | Last **30 completed UTC days**, rows `{date, model, model_permaslug, usage (USD), requests, prompt_tokens, completion_tokens, reasoning_tokens, endpoint_id, provider_name}`. Опционально `?date=YYYY-MM-DD`. **403** если ключ не management: `Only management keys can perform this operation` |
| `GET /api/v1/credits` | Bearer API или management | **401** тот же cookie-текст | — | `total_credits` / `total_usage`. **Per-model нет** (уже в дашборде) |
| `GET /api/v1/key` | user API key | — | — | `usage_daily/weekly/monthly` на ключ. **Per-model нет** |
| `POST /api/v1/analytics/query` | management key (beta) | не зондировали телом | — | Гибкие dimensions включая `model`. Тяжелее, чем activity; **в этой задаче не используем** |

**Verdict (2026-08-25):** per-model для OpenRouter = `GET {OPENROUTER_BASE_URL}/api/v1/activity` с `OPENROUTER_MANAGEMENT_KEY` (тот же слот, что `/api/v1/keys`). Гранулярность — **календарный UTC-день**, не rolling-час; 24ч-разбивка поэтому `partial`. Live rolling 24ч/7д **суммы** по-прежнему из snapshots `total_usage`. Нет management key / 401/403 → карточка жива, models.available=false, текст «нет разбивки от провайдера».

## Разведка остальных провайдеров (2026-08-25)

| Провайдер | Live usage/quota API | Per-model? |
|---|---|---|
| DeepSeek | `GET /user/balance` only; `/user/usage` без ключа **401** Authentication Fails; history API нет (уже в README) | **нет** — «нет разбивки от провайдера» |
| Z.AI | `GET /api/monitor/usage/quota/limit` — session/weekly/MCP; `usageDetails` без стабильного model-контракта | **нет** (не парсим неизвестный shape) |
| Command Code | `GET /alpha/billing/credits` — окна 5ч/нед/мес, не модели | **нет** |
| Kimi Coding | `GET /coding/v1/usages` — weekly + 5h request quota | **нет** |
| OpenCode Go | `GET /zen/go/v1/usage` — rolling/weekly/monthly percent | **нет** |

CPA / Postgres `usage_records` / xAI accounts — **не источник**. Не возвращать в код.

## Решение

- **Snapshots-дельты** (один проход по `snapshots.jsonl`, forward-compat к строкам с 10.07):
  - DeepSeek: `baseline_balance − current` (¥/$) за 24ч и 7д.
  - OpenRouter: `current_total_usage − baseline` ($) за 24ч и 7д.
  - Z.AI: дельта `weekly.currentValue` / `used_percent` (квота, не $).
  - Command Code: дельта monthly remaining credits.
  - Kimi: дельта `weekly.used` (запросы).
  - OpenCode Go: дельта `monthly.used_usd` / `used_percent`.
- **Live-окна волны 1** на карточках не убираем (5ч / неделя / месяц).
- **Partial-паттерн** — см. ниже; пробелы не выдумываем.
- **Per-model:** только OpenRouter activity; остальные — явная пометка.
- UI: на каждой карточке строки «расход 24ч» / «расход 7д» + блок «По моделям».

## Partial-паттерн (пробелы данных)

| Ситуация | `partial` | `gap` | UI |
|---|---|---|---|
| Есть snapshot ≤ старта окна | false | null | число дельты |
| Нет точки до окна, есть первая внутри | true | null | число + «частичная история» |
| Нет точек с нужной метрикой | true | `no-history` | «недостаточно истории» |
| Usage-метрика упала (сброс окна / refund) | true | `window-reset` | «сброс окна, дельта недоступна» — **не** показываем отрицательный расход как трату |
| 7д короче 7 суток истории (новые карточки волны 1) | true | null или `no-history` | 24ч если есть; 7д пометка |
| OpenRouter activity: день, не час | true на models | null | разбивка есть, подпись «по UTC-дням» |
| Нет management key / 401/403 activity | — | `no-provider-breakdown` | «нет разбивки от провайдера» |
| Историческая строка без wallets / с `accounts` xAI / битый JSON | — | skip row | рендер не падает |

Не подставляем CPA tokens/models из старых `accounts[]` как расход текущих подписок.

## Non-goals

- Деплой / запись Dockhand env (ops после merge).
- Карточка Cursor (другой ребёнок эпика).
- `POST /api/v1/analytics/query`.
- Cookie-сессии провайдеров.
- Копирование remaining% / spend в CRM/gbrain.
- Возврат CPA/Postgres collectors.

## Acceptance

1. На https://usage.ragpt.ru виден расход по каждой подписке за 24ч (и 7д, где есть данные) из snapshots-дельт, без CPA-кода; prod-smoke подтверждает (после ops autodeploy; эта ветка не деплоит).
2. Per-model разбивка для OpenRouter (`GET /api/v1/activity`, management key, дата разведки 2026-08-25); для остальных — «нет разбивки от провайдера».
3. Исторические snapshots не роняют рендер (тест forward-compat на записях схемы 10.07).
4. Стратегия пробелов зафиксирована в этом spec (таблица partial-паттерна).

## Contracts

```json
{"status": "ready", "type": null, "repo": "Rast53/usage-dashboard"}
```
