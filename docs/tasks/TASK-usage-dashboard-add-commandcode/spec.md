# TASK-usage-dashboard-add-commandcode — Spec

> S-задача: карточка Command Code GOAT на usage-dashboard с live-остатком кредитов и rolling-окнами (5ч / неделя / месяц) или явным error/manual. Деплой не делать.

## Проблема

Инвентарь [[services/ai-subscriptions]] уже держит **Command Code GOAT** (CRM Id 17, $10/мес = $70 usage, окна $14/5ч и $35/нед). На https://usage.ragpt.ru карточки только DeepSeek / OpenRouter / Z.AI. Live remaining% в CRM/gbrain не копировать — дашборд = телеметрия.

## Цель

После merge (и последующего redeploy ops) на https://usage.ragpt.ru есть карточка **Command Code**: остаток кредитов + окна 5ч / неделя / месяц без error, либо явный error/manual, если API/ключ недоступны. Дашборд не падает. Ключ не в git.

## Разведка endpoint'а (2026-08-25)

Пробы **без секрета** с этой cloud-сессии (`GET`, `Accept: application/json`). Origin `https://api.commandcode.ai` с агента **доступен** (не 403/timeout).

| URL | Auth contract | Без ключа | Что читается |
|---|---|---|---|
| `GET /alpha/billing/credits` | `Authorization: Bearer <Provider API key>` | **401** `Invalid 'Authorization' header or token.` | Live: `credits.monthlyCredits` (остаток месячного гранта, **не** total), `credits.purchasedCredits`, `windowLimits.fiveHour` / `weekly` (`used`, `cap`, `exceeded`, `resetAt` ms; `resetAt: 0` = окна ещё не открывалось) |
| `GET /alpha/billing/subscriptions` | тот же Bearer | **401** тот же текст | Optional: `planId` (`individual-goat` и т.п.), период биллинга |
| `GET /internal/billing/credits` | web-session cookie (`__Secure-commandcode_prod_.session_token`) | **401** `You're logged out. Please refresh and login.` | Тот же JSON-shape, но **cookie-only** — в дашборде **не используем** |
| `GET /internal/billing/subscriptions` | cookie | **401** logged out | Не используем |
| `GET /provider/v1/models` | нет | **200** list | Каталог моделей. **Usage/квоты нет** |

**Не читается (нет публичного контракта / не для этой карточки):**

- Studio Usage (per-request history) — UI, не API для probe.
- CLI `/usage` — тот же billing, но не HTTP-контракт для сервера.
- Cookie-сессия Studio — не кладём в Dockhand; истекает, не тот секрет.

**Источники разведки:**

- Live HTTP 2026-08-25 (эта сессия): статусы/тела ошибок выше.
- [pi-sub](https://github.com/bacnh85/pi-extensions) `fetchCommandCodeUsage`: `https://api.commandcode.ai/alpha/billing/credits` + тот же Provider API key, что `/provider/v1` (без cookie). Shape: `credits.monthlyCredits`, `windowLimits.fiveHour|weekly.{used,cap,resetAt}`.
- [token-monitor #421](https://github.com/Javis603/token-monitor/pull/421): cookie-path `/internal/billing/*`; каталог планов (GOAT: 70 / 14 / 35); `monthlyCredits` = remaining grant, знаменатель месяца с `planId` + сверка cap'ов.
- Docs: [Usage Limits](https://commandcode.ai/docs/resources/usage-limits), [GOAT](https://commandcode.ai/docs/plans/goat) — $70 / $14 / $35.
- gbrain `services/ai-subscriptions`: Hermes `commandcode`, `api.commandcode.ai/provider/v1`, ключ `credentials/commandcode.env`.

**Вывод:** live-карточка = Bearer `COMMANDCODE_API_KEY` → `/alpha/billing/credits` (+ optional `/alpha/billing/subscriptions`). Нет ключа или 401/сеть → карточка **error/manual**, остальные провайдеры без изменений.

## Решение

- `COMMANDCODE_API_KEY` — Provider API key (Studio). Dockhand stack env, `is_secret`. Не коммитить.
- Optional `COMMANDCODE_PROXY` — HTTP CONNECT / SOCKS5(h), только Command Code (как `ZAI_PROXY`), если tw-msk docker-egress не дойдёт. Пустой default.
- Probe: `GET https://api.commandcode.ai/alpha/billing/credits`; подписка optional.
- Месячный %: remaining с провода; total из каталога плана, если `planId` и/или 5ч+нед cap совпали с опубликованными (GOAT 14/35 → $70). Иначе money-only, без выдуманного знаменателя.
- UI: карточка рядом с Z.AI; три окна; badge plan / `error` / `manual`.
- Существующие DeepSeek / OpenRouter / Z.AI probes не ломать.

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (ops после merge).
- Cookie-сессия Studio / `/internal/billing/*`.
- Карточки opencode-go / kimi / cursor (другие дети эпика).
- Копирование remaining% в CRM/gbrain.

## Acceptance

1. На https://usage.ragpt.ru карточка Command Code показывает остаток/окна без error (после ops: ключ в stack env + autodeploy), **или** явный error/manual при недоступности API, дашборд не падает.
2. Разведка endpoint'а зафиксирована в этом spec (таблица, источники, дата 2026-08-25).
3. Ключ не в git; env-слот в compose / `.env.example`; redeploy через autodeploy (ops); prod-smoke после деплоя — не эта ветка.

## Contracts

```json
{"status": "ready", "type": null, "repo": "Rast53/usage-dashboard"}
```
