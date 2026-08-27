# TASK-alan-openrouter-per-model-export — Spec

> S-задача (код): per-model расход ключа Алана через экспорт с основного инстанса (management activity `api_key_hash`) и импорт на usage.alan.ragpt.ru. Деплой не делать.

## Проблема

На https://usage.alan.ragpt.ru карточка OpenRouter в key-only режиме не показывает разбивку по моделям: `GET /api/v1/activity` требует management key, а алан-контейнер его не имеет и не должен звать activity. Нужна таблица моделей ключа Алана (gemini/veo/kling/kokoro и др.) за день / 7д / 30д без утечки баланса аккаунта Ивана и без секретов.

## Цель

Один образ, разный env:

### Экспортёр (основной инстанс, usage.ragpt.ru)

- `OPENROUTER_TRACKED_KEY_HASH` — пусто = фича выключена, дефолт-поведение не меняется.
- `OPENROUTER_EXPORT_PATH` — дефолт `/app/export/openrouter_key_models.json`.
- Если хэш задан: в цикле поллинга (троттлинг ≤ 1 раз / 300 сек) `GET /api/v1/activity?api_key_hash=<hash>` management-ключом (существующие `get_openrouter_management_key` / proxy / base URL).
- Агрегация по моделям в стиле существующей per-model: UTC-дни, today+yesterday как «24ч», 7 календарных дней, 30 дней.
- Атомарная запись JSON:

```json
{
  "schema": 1,
  "updated_at": "…Z",
  "key_label_hash_suffix": "…",
  "models": [
    {
      "model": "google/gemini-…",
      "usage_24h": 0,
      "usage_7d": 0,
      "usage_30d": 0,
      "requests_24h": 0,
      "requests_7d": 0
    }
  ],
  "totals": {"usage_24h": 0, "usage_7d": 0, "usage_30d": 0}
}
```

- В файле **запрещены**: `total_credits` / `remaining` аккаунта, данные других ключей, любые секреты, полный hash ключа.
- При ошибке запроса — сохранить предыдущий файл, обновить только `updated_at` попытки и поле `last_error`.
- compose `docker-compose.yml`: volume `- /opt/usage-dashboard/export:/app/export`.

### Импортёр (алан-инстанс)

- `OPENROUTER_IMPORT_PATH` — дефолт `/app/export/openrouter_key_models.json`.
- Если файл свежий (`updated_at` не старше 1800 сек): models-секция кошелька OpenRouter строится из него (существующий рендер таблицы), пометка источника «экспорт с аккаунта (key-only)».
- Если файл отсутствует — «нет разбивки от провайдера»; если протух — «нет свежих данных экспорта». Ошибок на странице нет.
- Прямых вызовов activity из алан-контейнера нет (`OPENROUTER_KEY_ONLY=1` без изменений).
- Импорт только в key-only режиме, чтобы основной инстанс не подменил account-wide per-model файлом ключа Алана (общий volume).
- compose `docker-compose.alan.yml`: volume `- /opt/usage-dashboard/export:/app/export:ro`.

## Non-goals

- Деплой / Dockhand upsert `OPENROUTER_TRACKED_KEY_HASH` / `mkdir /opt/usage-dashboard/export` / редеплой стеков 7 и 8 (ops hermes-chuwi **после merge**).
- Менять основной usage.ragpt.ru при пустом `OPENROUTER_TRACKED_KEY_HASH`.
- `POST /api/v1/analytics/query`.
- Печать значения ключа Алана / полный sha256 в git / `/api/wallets` / экспорт-файле.

## Ops (после merge, не эта ветка)

На hermes-chuwi:

1. Посчитать sha256 ключа Алана (источник: openclaw.json контейнера alanclaw-openclaw, **без печати значения**), вставить в stack 7 `OPENROUTER_TRACKED_KEY_HASH` (plain env, dockhand upsert).
2. `mkdir /opt/usage-dashboard/export` на хосте.
3. Редеплой обоих стеков (7 — после вставки env; 8 — подписанный webhook), приёмка.

## Acceptance

1. PR: тесты зелёные (старые + новые), GitGuardian чистый, merged. Плейсхолдеры вида `placeholder-key-N` / `placeholder-hash-N`; без `sk-or-…` и hex ≥ 40 символов в новых тестах.
2. После деплоя: на usage.alan.ragpt.ru в карточке OpenRouter видна per-model таблица ключа Алана с суммами за день/неделю/30д; при удалении/протухании файла секция честно деградирует без ошибок.
3. Основной usage.ragpt.ru: поведение не изменилось; файл экспорта появляется и содержит ТОЛЬКО данные ключа Алана (суммы = фильтрованному запросу, нет `total_credits`).
4. Секреты в `/api/wallets` и экспорт-файле отсутствуют.

## Contracts

```json
{"status": "ready", "type": "code", "repo": "Rast53/usage-dashboard"}
```
