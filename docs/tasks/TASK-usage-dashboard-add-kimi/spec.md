# TASK-usage-dashboard-add-kimi — Spec

> S-задача: карточка **Kimi Coding** на usage-dashboard с live-квотой (недельный пул + rolling 5ч) или явным error/manual. Деплой не делать.

## Проблема

Инвентарь [[services/ai-subscriptions]] уже держит **Kimi Coding / Kimi Code** как одну подписку (direct `credentials/kimi.env` → `api.kimi.com/coding`; CPA был только транспортом, не вторым планом). На https://usage.ragpt.ru карточки DeepSeek / OpenRouter / Z.AI / Command Code. Live remaining% в CRM/gbrain не копировать — дашборд = телеметрия.

## Цель

После merge (и последующего redeploy ops) на https://usage.ragpt.ru есть карточка **Kimi Coding**: недельная квота + окно 5ч без падения дашборда, либо явный **error** / **manual**, если API/ключ недоступны. Ключ не в git.

## Разведка endpoint'а (2026-08-25)

Пробы **без секрета** с этой cloud-сессии (`GET`, `Accept: application/json`, UA recon). Origin `https://api.kimi.com` с агента **доступен** (не timeout; Cloudflare `cf-ray …-IAD`). **tw-msk docker-egress из этой сессии не зондировался** (нет SSH в stack 7) — тот же класс риска, что `api.z.ai`; если контейнер не достучится, карточка `error`, остальные провайдеры живы; ops может выставить `KIMI_PROXY`.

| URL | Auth contract | Без ключа | Что читается |
|---|---|---|---|
| `GET https://api.kimi.com/coding/` | нет | **200** `{"message":"Welcome to the Kimi For Coding API!"}` | Welcome, не квота |
| `GET https://api.kimi.com/coding/v1/usages` | `Authorization: Bearer <Kimi Code API key>` | **401** `error.message=Invalid Authentication` / `type=invalid_authentication_error`. С мусорным Bearer — **401** `code=unauthenticated` (`REASON_INVALID_AUTH_TOKEN`) | Live weekly + 5h: `usage.{limit,used,remaining,resetTime\|reset_at}` и `limits[].{window,detail}` |
| `GET https://api.kimi.com/coding/v1/models` | Bearer | **401** тот же Invalid Authentication | Каталог моделей. **Квоты нет** |
| `GET …/coding/v1`, `/usage`, `/quota`, `/limits`, `/users/me` | — | **404** `resource_not_found_error` | Не квота |
| `GET https://www.kimi.com/apiv2/kimi.gateway.billing.v1.BillingService/GetUsages` | cookie `kimi-auth` (web) | **405**, `Allow: POST` | Cookie-only billing. **В дашборде не используем** |
| `GET https://api.moonshot.cn/v1/models` | Open Platform key | **401** `Incorrect API key provided` | **Другой продукт** (Moonshot Open Platform), не Kimi Code |

**Не читается (нет публичного контракта / не для этой карточки):**

- Месячный membership pool (web Settings → Subscription) — cookie `kimi-auth` / CLI session, не Dockhand secret.
- Extra Usage / booster wallet — UI Console, не этот REST.
- `https://agent-gw.kimi.com/coding` — OpenClaw model gateway, не usage.
- CPA `cpa.raclaw.ru/v1` — decommissioned transport, не источник квоты.

**Источники разведки:**

- Live HTTP 2026-08-25 (эта сессия): статусы/тела выше.
- Official: [Membership Benefits](https://www.kimi.com/code/docs/en/kimi-code/membership) — weekly reset 7d + rolling 5h; [Error Reference](https://www.kimi.com/code/docs/en/kimi-code/error-reference.html) — Base URL `https://api.kimi.com/coding/v1` (OpenAI) / `https://api.kimi.com/coding/` (Anthropic); 429 5h / weekly / monthly freeze.
- [CodexBar docs/kimi.md](https://github.com/steipete/CodexBar/blob/main/docs/kimi.md): `GET https://api.kimi.com/coding/v1/usages` + Bearer API key; shape `usage` + `limits[0].window.duration=300 MINUTE` (5h). Cookie GetUsages — enrichment only.
- [quotas crate kimi.md](https://docs.rs/crate/quotas/latest/source/docs-usage/kimi.md) / kimi-cli `/usage`: тот же `{platform.base_url}/usages`, default `KIMI_CODE_BASE_URL=https://api.kimi.com/coding/v1`.
- gbrain `services/ai-subscriptions`: одна подписка Kimi Code; direct `credentials/kimi.env` (`api.kimi.com/coding`).
- gbrain `projects/usage-dashboard`: волна 1 эпика TASK-usage-dashboard-subscriptions — карточка kimi.

**Вывод:** live-карточка = Bearer `KIMI_API_KEY` / `KIMI_CODE_API_KEY` → `GET {KIMI_CODE_BASE_URL}/usages`. Нет ключа → **manual** (без HTTP). 401/сеть → **error** на карточке, дашборд не падает. Cookie / moonshot.cn не используем.

## Решение

- `KIMI_API_KEY` (alias `KIMI_CODE_API_KEY`) — Kimi Code Console key. Dockhand stack env, `is_secret`. Не коммитить.
- Optional `KIMI_PROXY` (alias `KIMI_CODE_PROXY`) — HTTP CONNECT / SOCKS5(h), только Kimi (как `ZAI_PROXY`), если tw-msk docker-egress не дойдёт. Пустой default.
- Optional `KIMI_CODE_BASE_URL` — default `https://api.kimi.com/coding/v1`.
- Probe: `GET …/usages`. Weekly из `usage`; 5h из `limits[]` где window ≈ 300 минут. Свежее окно без `detail` → 100% remaining, без выдуманного cap.
- План (Andante/Moderato/Allegretto) — только если weekly `limit` совпал с опубликованным (1024 / 2048 / 7168). Иначе без label.
- UI: карточка рядом с Command Code; два окна (5ч + неделя); badge plan / `error` / `manual`.
- Существующие DeepSeek / OpenRouter / Z.AI / Command Code probes не ломать.

## Non-goals

- Деплой / запись Dockhand stack env на живом хосте (ops после merge).
- Cookie-сессия / `GetUsages` / Moonshot Open Platform `api.moonshot.cn`.
- Карточки opencode-go / cursor (другие дети эпика).
- Копирование remaining% в CRM/gbrain.

## Acceptance

1. На https://usage.ragpt.ru карточка Kimi Coding показывает квоту/лимит без error (после ops: ключ в stack env + autodeploy), **или** явный error/manual при недоступности API; дашборд не падает.
2. Разведка endpoint'а зафиксирована в этом spec (таблица, источники, дата 2026-08-25).
3. Ключ не в git; env-слот в compose / `.env.example`; redeploy через autodeploy (ops); prod-smoke после деплоя — не эта ветка.

## Contracts

```json
{"status": "in-progress", "type": null, "repo": "Rast53/usage-dashboard"}
```
