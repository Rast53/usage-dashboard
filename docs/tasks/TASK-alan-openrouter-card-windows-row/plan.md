# TASK-alan-openrouter-card-windows-row — Plan

## Phase 1: materialize

1. `docs/tasks/TASK-alan-openrouter-card-windows-row/{spec,plan,progress}.md`.

## Phase 2: UI

1. `calendarWindowFilled(row)` — `spent != null` и не `partial`.
2. `renderSpendCalendar`: ранний `return ''`, если вчера / 7д / 30д все пустые.
3. В таблице только заполненные колонки + Итого + note.

## Phase 3: tests

1. HTML-контракт: guard `calendarWindowFilled`, ранний выход, заголовки колонок в исходнике сохранены.
2. Старые тесты зелёные (`python3 -m unittest discover -s tests -q`).

## Guardrails

- Не деплоить. Не коммитить ключи.
- usage.ragpt.ru: `hide_partial_spend_chips=false` → `renderSpendCalendar` не зовётся.
