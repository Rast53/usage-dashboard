# TASK-usage-dashboard-add-opencode-go — Spec

> S-задача: карточка **OpenCode Go** на usage-dashboard с остатком месячного лимита и датой reset: live-квота или явный error/manual. Деплой не делать.

## Проблема

Инвентарь [[services/ai-subscriptions]] уже держит **OpenCode Go** (Hermes provider `opencode-go`, `https://opencode.ai/zen/go/v1`; 2026-08-18 hit `GoUsageLimitError` 429, monthly reset ~17d). На https://usage.ragpt.ru карточки DeepSeek / OpenRouter / Z.AI / Command Code / Kimi. Live remaining% в CRM/gbrain не копировать — дашборд = телеметрия.

## Цель

После merge (и последующего redeploy ops) на https://usage.ragpt.ru есть карточка **OpenCode Go**: остаток месячного лимита + дата reset (и окна 5ч / неделя, если API их отдал) без падения дашборда, либо явный **error** / **manual**, если API/ключ недоступны. Ключ не в git.

## Разведка endpoint'а (2026-08-25)

Пробы **без секрета** с этой cloud-сессии (`GET`, `Accept: application/json`, UA `usage-dashboard/1.0`). Origin `https://opencode.ai` с агента **доступен** (не timeout). **tw-msk docker-egress из этой сессии не зондировался** (нет SSH в stack 7) — тот же класс риска, что `api.z.ai` / `api.kimi.com`; если контейнер не достучится, карточка `error`, остальные провайдеры живы; ops может выставить `OPENCODE_GO_PROXY`.

| URL | Auth contract | Без ключа | Что читается |
|---|---|---|---|
| `GET https://opencode.ai/zen/go/v1/usage` | `Authorization: Bearer <OpenCode Go API key>` | **401** JSON `{type:error, error:{type:AuthError, message:"Missing API key."}}`. Мусорный Bearer — **401** `Unauthorized` | Live окна: `usage.rolling` / `weekly` / `monthly` → `{status: "ok"\|"rate-limited", percent, resetsAt}` где `percent` = **used** %, `resetsAt` = ISO reset |
| `GET https://opencode.ai/zen/go/v1/models` | нет | **200** `{object:list, data:[{id,...}]}` | Каталог моделей. **Квоты нет** |
| `GET https://opencode.ai/zen/v1/usage` | — | **404** SPA HTML | Не квота |
| `GET https://opencode.ai/zen/go/v1/balance` | — | **404** SPA HTML | Zen wallet. **Не этот REST** (issue #44189) |
| `GET https://opencode.ai/zen/go/v1` | — | **404** SPA HTML | Не квота |

**Не читается (нет публичного контракта / не для этой карточки):**

- Cookie-сессия console / `workspace/{id}/go` scrape (`OPENCODE_GO_WORKSPACE_ID` + `auth` cookie) — desktop-workaround (opencode-quota / старый pi-go-bars). Истекает, не Dockhand secret.
- Zen pay-as-you-go balance (`BillingTable.balance`) — только browser session; #44189 open.
- Chat/completions 429 `GoUsageLimitError` — побочный сигнал, не read-only probe (жжёт квоту).

**Источники разведки:**

- Live HTTP 2026-08-25 (эта сессия): статусы/тела выше.
- Official: [Go docs](https://opencode.ai/docs/go/) — $10/мес; окна **$12 / 5ч**, **$30 / неделя**, **$60 / месяц**; usage в console.
- [opencode#16513](https://github.com/anomalyco/opencode/pull/16513) merged 2026-08-11: `GET /zen/go/v1/usage` Bearer. Текущий `usage.ts` на `dev` оборачивает `analyze*Usage` в `{status, percent, resetsAt}` (не сырой `usagePercent`/`resetInSec`).
- [opencode#44189](https://github.com/anomalyco/opencode/issues/44189) (2026-08-22): live shape `usage.{rolling,weekly,monthly}.{status,percent,resetsAt}`; balance **нет**.
- [pi-go-bars 0.4.0](https://github.com/donrami/pi-go-bars) (2026-08-23): primary `GET /zen/go/v1/usage` + `parseUsageApi`; cookie scrape только fallback.
- gbrain `services/ai-subscriptions`: 2026-08-18 `GoUsageLimitError` 429 monthly; Hermes `opencode-go` → `https://opencode.ai/zen/go/v1`.
- gbrain `projects/usage-dashboard`: волна 1 эпика TASK-usage-dashboard-subscriptions — карточка opencode-go.

**Вывод:** live-карточка = Bearer `OPENCODE_GO_API_KEY` → `GET {OPENCODE_GO_BASE_URL}/usage`. Нет ключа → **manual** (без HTTP). 401/403/сеть → **error** на карточке, дашборд не падает. Cookie / Zen balance не используем. `percent` на проводе = used; remaining% = 100 − used. USD-остаток — оценка от опубликованных cap'ов ($12 / $30 / $60), не с провода.

## Решение

- `OPENCODE_GO_API_KEY` (alias `OPENCODE_API_KEY`) — тот же ключ, что `/zen/go/v1`. Dockhand stack env, `is_secret`. Не коммитить.
- Optional `OPENCODE_GO_PROXY` — HTTP CONNECT / SOCKS5(h), только OpenCode Go (как `ZAI_PROXY` / `KIMI_PROXY`), если tw-msk docker-egress не дойдёт. Пустой default.
- Optional `OPENCODE_GO_BASE_URL` — default `https://opencode.ai/zen/go/v1`.
- Probe: `GET …/usage`. Окна rolling→5ч, weekly, monthly. Reset из `resetsAt` (legacy `resetInSec` тоже парсим).
- UI: карточка рядом с Command Code / Kimi; три окна; badge Go / `error` / `manual`; дата reset видна.
- Существующие DeepSeek / OpenRouter / Z.AI / Command Code / Kimi probes не ломать.

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (ops после merge).
- Cookie-сессия / dashboard scrape / Zen balance.
- Карточка cursor (другой ребёнок эпика).
- Копирование remaining% в CRM/gbrain.

## Acceptance

1. На https://usage.ragpt.ru карточка OpenCode Go показывает остаток/reset без error (после ops: ключ в stack env + autodeploy), **или** явный error/manual при недоступности API; дашборд не падает.
2. Разведка endpoint'а зафиксирована в этом spec (таблица, источники, дата 2026-08-25).
3. Ключ не в git; env-слот в compose / `.env.example`; redeploy через autodeploy (ops); prod-smoke после деплоя — не эта ветка.

## Contracts

```json
{"status": "ready", "type": null, "repo": "Rast53/usage-dashboard"}
```
