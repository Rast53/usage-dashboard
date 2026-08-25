# TASK-usage-dashboard-add-kimi — Progress

| Дата | Шаг | Статус | Комментарий |
|---|---|---|---|
| 2026-08-25 | Создана | ✅ | Из пакета cloud-agent (spec отсутствовал в репо) |
| 2026-08-25 | Spec + plan | ✅ | materialize + разведка `GET /coding/v1/usages` |
| 2026-08-25 | Probe + wallet | ✅ | `probe_kimi_usage` Bearer; missing key → manual |
| 2026-08-25 | UI | ✅ | карточка 5ч / неделя; error/manual не роняет дашборд |
| 2026-08-25 | Env/compose/docs | ✅ | `KIMI_API_KEY` + optional `KIMI_PROXY` / `KIMI_CODE_BASE_URL`; без секретов |
| 2026-08-25 | Tests | ✅ | `python3 -m unittest discover -s tests -q` — 42 passed |
| 2026-08-25 | Закрытие | ✅ | код/тесты готовы; деплой не делался |
| 2026-08-25 | Ops E2E | ⏳ | Dockhand stack 7: `KIMI_API_KEY` is_secret + autodeploy |

## Actual

Cursor cloud-agent: spec/recon + probe + UI + tests. Оценка S. Ops E2E (live-карточка на usage.ragpt.ru) — после merge/redeploy и записи ключа в Dockhand.

## 2026-08-25 — handoff из пакета

Задача материализована в ветку `cursor/TASK-usage-dashboard-add-kimi`. Деплой не делался.

## 2026-08-25 — build notes

- Live path: `GET https://api.kimi.com/coding/v1/usages`, `Authorization: Bearer` (`KIMI_API_KEY` / `KIMI_CODE_API_KEY`).
- Cookie `GetUsages` и Moonshot Open Platform `api.moonshot.cn` не используем.
- Нет ключа → `status: manual`, HTTP нет; 401/сеть → `error`; исключение probe не дропает DeepSeek/OpenRouter/Z.AI/Command Code.
- Weekly `limit` 1024/2048/7168 → Andante/Moderato/Allegretto. Иначе без plan label.
- Свежее 5h окно без `detail` → 100% remaining, без выдуманного cap.

Sources used:
- AGENTMAP.md — нет в корне Rast53/usage-dashboard (репо не публикует указатель)
- `code_def(collect_state)` / `code_callers(collect_state)` / `code_def(probe_commandcode_credits)` / `code_def(http_json)` / `code_def(probe_kimi_usage)` — 0 defs: usage-dashboard не в gbrain code-графе (нет `.gbrain-source`; sources raclaw-canonical / raclaw-task-mcp не индексируют этот репо; `code_callers(collect_state)` → `not_built`)
- `get_page(projects/usage-dashboard)` — волна 1 эпика: карточка kimi; wallets DeepSeek/OpenRouter/Z.AI (+ Command Code после #7)
- `get_page(services/ai-subscriptions)` — одна подписка Kimi Code; `credentials/kimi.env` → `api.kimi.com/coding`
- Live recon 2026-08-25: `/coding/` 200 welcome; `/coding/v1/usages` 401 Invalid Authentication (мусорный Bearer → `unauthenticated`); cookie GetUsages GET 405 Allow POST; moonshot.cn — другой продукт
- CodexBar `docs/kimi.md` + Kimi Code membership docs: weekly + 5h (300 MINUTE); Base URL `https://api.kimi.com/coding/v1`
- Чтение: `app.py` `collect_state` / `probe_commandcode_credits` / `http_json`; `static/index.html`; пакет задачи
