# TASK-alan-openrouter-per-model-export — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-openrouter-per-model-export/{spec,plan,progress}.md`.

## Phase 2: экспортёр (основной инстанс)

1. Env-helpers: `get_openrouter_tracked_key_hash()` (пусто → None), `get_openrouter_export_path()` (дефолт `/app/export/openrouter_key_models.json`).
2. `aggregate_openrouter_key_models()` — UTC-окна как у существующей агрегации (24ч = today+yesterday, 7д, 30д); выход в контракт файла, без top-8 капа.
3. `maybe_export_openrouter_key_models()` в `collect_state` / поллинг: throttle 300с; `GET /api/v1/activity?api_key_hash=` через management key + существующий proxy/base URL.
4. Атомарная запись JSON; при ошибке — прежний payload + `updated_at` + `last_error`. Исключения не роняют дашборд.
5. `docker-compose.yml`: volume export + слоты env без значений-секретов.

## Phase 3: импортёр (алан-инстанс)

1. `get_openrouter_import_path()`, `load_openrouter_key_models_import()`.
2. `build_openrouter_wallet()` при `OPENROUTER_KEY_ONLY`: свежий файл → models из экспорта; stale/missing → текущие reason-строки; activity не вызывается.
3. Без key-only — импорт не применяется (основной инстанс не подменяет account activity).
4. UI: существующая таблица; для `source=openrouter-key-export` колонки день/7д/30д + подпись «экспорт с аккаунта (key-only)».
5. `docker-compose.alan.yml`: ro-volume + `OPENROUTER_IMPORT_PATH`.

## Phase 4: тесты / docs

1. Агрегация + писатель (мок HTTP), контракт файла (нет account-полей), throttle.
2. Импортёр: свежий / протухший / отсутствующий; key-only не зовёт activity.
3. Дефолты без env не изменились; старые тесты зелёные.
4. README / `.env.example`. Без литералов `sk-or-…` и hex ≥ 40 в новых тестах.

## Guardrails

- Не деплоить. Не коммитить ключи / полный sha256.
- Основной инстанс без `OPENROUTER_TRACKED_KEY_HASH` = текущее поведение.
