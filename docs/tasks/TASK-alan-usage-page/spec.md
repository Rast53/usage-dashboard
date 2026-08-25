# TASK-alan-usage-page — Spec

> S-задача (код): env-конфиг инстанса usage-dashboard (`PROVIDERS`, `SITE_TITLE`) для выделенной страницы Алана. Деплой не делать.

## Проблема

Нужен второй инстанс того же образа на tw-msk: https://alan.ragpt.ru — только карточка **OpenCode Go** с ключом Алана, без basicauth (решение Ивана). Основной https://usage.ragpt.ru не трогать. Сейчас дашборд всегда пробит и рендерит все 6 провайдеров; hero пишет «из 6 провайдеров» / список всех источников даже если жив один ключ.

## Цель

Один образ, разный env:

- `PROVIDERS` — allowlist через запятую. Дефолт (нет/пустое) = все 6, как сейчас. `PROVIDERS=opencode-go` → проба и рендер только этой карточки.
- `SITE_TITLE` — заголовок страницы. Дефолт: «Мои подписки».
- Hero-сводка и per-model (карточка OpenRouter / «По моделям») схлопываются под фактический allowlist: нет «5 из 6 активных» на инстансе Алана.
- Тесты: фильтрация (проба + `/api/summary` + рендер-контракт); дефолт без env = текущее поведение.
- Ключи не в git. `/api/summary` не содержит секретов.

## Non-goals

- Деплой второго контейнера / Traefik `alan.ragpt.ru` / Dockhand secret (ops hermes-chuwi **после merge**, отдельным шагом).
- Менять основной инстанс usage.ragpt.ru (не задавать там `PROVIDERS`/`SITE_TITLE`).
- Basicauth на alan.ragpt.ru (явно без него).

## Ops (после merge, не эта ветка)

Второй контейнер из того же образа на tw-msk:

- env: `PROVIDERS=opencode-go`, `SITE_TITLE=OpenCode Go — Алан`, `OPENCODE_GO_API_KEY` = ключ Алана (Dockhand secret, не git)
- traefik: `alan.ragpt.ru` → этот контейнер, **без** `tasks-basicauth@file`
- volume отдельный (не `/opt/usage-dashboard/data` основного стека)
- основной usage.ragpt.ru не трогать

## Acceptance

1. PR: `PROVIDERS`/`SITE_TITLE` работают; тесты зелёные (старые + новые); скриншоты страницы с одной карточкой (desktop+mobile).
2. После merge и deploy: https://alan.ragpt.ru открывается без логина, только OpenCode Go с данными ключа Алана; `/api/summary` без ключей; usage.ragpt.ru не изменился.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
