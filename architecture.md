# Architecture — AI-Native Gantt Chart (FastAPI + React TS + MCP)

Этот документ — единственный источник истины по архитектуре проекта. Любые изменения кода обязаны соответствовать этому документу и инвариантам из `system.md`. Правила валидации схем описаны в `skills/zod-sync.md`, правила работы с графом зависимостей — в `skills/dag-scheduler.md`.

---

## 1. Структура папок и стек технологий

### 1.1. Полный стек технологий

| Слой | Технология | Назначение |
|---|---|---|
| Frontend UI | **React 18** | Компонентный UI: диаграмма Гантта, чат, загрузка Excel |
| Frontend язык | **TypeScript** (strict mode) | Статическая типизация всего фронтенда |
| Frontend сборка | **Vite** | Dev-сервер, HMR, production-сборка |
| Frontend валидация | **Zod** | Runtime-валидация всех ответов API/LLM (`GanttTaskSchema.array().parse()`) |
| Backend framework | **FastAPI** | REST API, async-эндпоинты, автогенерация OpenAPI |
| Backend валидация | **Pydantic v2** | Схемы данных, aliases для snake_case ↔ camelCase, строгая валидация |
| AI Tool Calling | **FastMCP** | MCP-сервер с инструментами мутации задач для LLM |
| Excel-парсинг | **openpyxl** | Чтение `.xlsx`-файлов с задачами проекта |
| LLM-провайдер | **OpenRouter API** | Доступ к LLM для чата и Tool Calling (ключ через env `OPENROUTER_API_KEY`) |

### 1.2. Структура папок

```
bioteh/
├── architecture.md                  # Этот документ (источник истины по архитектуре)
├── system.md                        # Правила и инварианты для AI-кодинга
├── skills/
│   ├── zod-sync.md                  # Правила зеркалирования Zod <-> Pydantic
│   └── dag-scheduler.md             # Правила DAG-расчёта дат
│
├── frontend/
│   ├── index.html                   # Точка входа Vite
│   ├── package.json                 # Зависимости: react, react-dom, zod
│   ├── tsconfig.json                # strict: true
│   ├── vite.config.ts               # Конфиг Vite + proxy на backend (/api -> :8000)
│   └── src/
│       ├── main.tsx                 # Bootstrap React-приложения
│       ├── App.tsx                  # Корневой layout: GanttChart + ChatPanel
│       ├── schemas/
│       │   └── task.ts              # Zod-схемы: RawTaskSchema, GanttTaskSchema (зеркало Pydantic)
│       ├── api/
│       │   └── client.ts            # HTTP-клиент: fetch + Zod-parse всех ответов, camelCase-маппинг
│       ├── components/
│       │   ├── GanttChart.tsx       # Рендер диаграммы Гантта из GanttTask[]
│       │   ├── GanttRow.tsx         # Строка задачи (bar по startDate/endDate)
│       │   ├── ChatPanel.tsx        # Чат с LLM (история сообщений, ввод)
│       │   ├── FileUpload.tsx       # Загрузка Excel-файла (.xlsx)
│       │   └── Toast.tsx            # Toast-уведомления об ошибках (валидация, сеть, циклы)
│       ├── hooks/
│       │   ├── useTasks.ts          # Состояние GanttTask[]: загрузка, обновление после мутаций
│       │   └── useChat.ts           # Состояние чата: отправка сообщений, приём обновлённых задач
│       └── utils/
│           └── dates.ts             # Только форматирование ISO-дат для отображения (НЕ расчёт!)
│
└── backend/
    ├── pyproject.toml               # Зависимости: fastapi, uvicorn, pydantic>=2, fastmcp, openpyxl, httpx
    ├── .env.example                 # OPENROUTER_API_KEY, OPENROUTER_MODEL
    └── app/
        ├── __init__.py
        ├── main.py                  # FastAPI-приложение: CORS, роутеры, обработчики ошибок
        ├── config.py                # Настройки из env (pydantic-settings)
        ├── schemas/
        │   ├── __init__.py
        │   └── task.py              # Pydantic v2: RawTask, GanttTask (зеркало Zod), ChatRequest/Response
        ├── services/
        │   ├── __init__.py
        │   ├── scheduler.py         # DAG Scheduler — ЕДИНСТВЕННЫЙ источник расчёта дат
        │   ├── excel_parser.py      # openpyxl: .xlsx -> RawTask[]
        │   ├── seed.py              # Демо-набор RawTask[] для старта без Excel
        │   ├── task_store.py        # In-memory хранилище RawTask[] (текущее состояние проекта)
        │   └── llm_client.py        # httpx-клиент OpenRouter: chat completions + tool calling loop
        ├── routers/
        │   ├── __init__.py
        │   ├── tasks.py             # GET /api/tasks, POST /api/tasks/upload (Excel)
        │   └── chat.py              # POST /api/chat (User Chat -> LLM -> MCP tools -> GanttTask[])
        └── mcp_server.py            # FastMCP-сервер: update_task_details, add_new_task, delete_tasks
```

---

## 2. Единый контракт данных (Data Mapping)

### 2.1. RawTask — исходная задача (без дат)

`RawTask` — минимальное описание задачи, поступающее из Excel, seed-данных или мутаций LLM. Дат НЕ содержит: даты вычисляет только DAG Scheduler.

| Frontend (Zod, camelCase) | Backend (Pydantic v2, snake_case) | Тип | Обязательность | Описание | Пример |
|---|---|---|---|---|---|
| `id` | `id` | `string` / `str` | обязательное | Уникальный идентификатор задачи | `"task-1"` |
| `title` | `title` | `string` / `str` | обязательное | Название задачи | `"Проектирование БД"` |
| `description` | `description` | `string` / `str` | обязательное (может быть `""`) | Подробное описание задачи | `"Спроектировать схему PostgreSQL"` |
| `assignee` | `assignee` | `string` / `str` | обязательное (может быть `""`) | Исполнитель задачи | `"Дмитрий Пан"` |
| `durationDays` | `duration_days` | `number` (int ≥ 1) / `int` (`ge=1`) | обязательное | Длительность задачи в рабочих днях | `5` |
| `predecessors` | `predecessors` | `string[]` / `list[str]` | обязательное (может быть `[]`) | Список `id` задач-предшественников | `["task-1", "task-2"]` |
| `preferredStartDate` | `preferred_start_date` | `string` (ISO `YYYY-MM-DD`) / `str \| None` | опциональное (`None`) | Желаемая дата начала (только для задач без предшественников) | `"2026-09-04"` |

### 2.2. GanttTask — задача с рассчитанными датами

`GanttTask` расширяет `RawTask` двумя полями, которые заполняет ТОЛЬКО `backend/app/services/scheduler.py`:

| Frontend (Zod, camelCase) | Backend (Pydantic v2, snake_case) | Тип | Описание | Пример |
|---|---|---|---|---|
| `startDate` | `start_date` | `string` (ISO `YYYY-MM-DD`) / `date` (сериализуется в ISO) | Дата начала, рассчитанная DAG Scheduler | `"2026-08-03"` |
| `endDate` | `end_date` | `string` (ISO `YYYY-MM-DD`) / `date` (сериализуется в ISO) | Дата окончания = startDate + durationDays − 1 | `"2026-08-07"` |

Наследование контрактов:
- Zod: `GanttTaskSchema = RawTaskSchema.extend({ startDate, endDate })`.
- Pydantic: `class GanttTask(RawTask)` с полями `start_date`, `end_date`.

### 2.3. Правила маппинга именования (camelCase ↔ snake_case)

1. **Frontend — всегда camelCase.** Все Zod-схемы, TypeScript-типы, props и состояние используют `durationDays`, `startDate`, `endDate`.
2. **Backend — всегда snake_case.** Вся внутренняя логика Python (`scheduler.py`, `excel_parser.py`, `mcp_server.py`) оперирует `duration_days`, `start_date`, `end_date`.
3. **Граница маппинга — сериализация Pydantic.** Модели Pydantic v2 объявляются так:
   - `model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)`;
   - в JSON-ответах API поля сериализуются с алиасами (`model_dump(by_alias=True)` / `response_model_by_alias=True`) — т.е. по проводу между backend и frontend ходит **camelCase**;
   - входящий JSON от фронтенда принимается в camelCase и парсится в snake_case-поля через алиасы.
4. **Frontend не выполняет ручной конвертации ключей.** HTTP-клиент (`frontend/src/api/client.ts`) получает уже camelCase-JSON и сразу передаёт его в `GanttTaskSchema.array().parse()`.
5. **Зеркалирование обязательно.** Любое изменение полей задачи вносится ОДНОВРЕМЕННО в:
   - `frontend/src/schemas/task.ts` (Zod);
   - `backend/app/schemas/task.py` (Pydantic v2).
6. **Описания полей обязательны (правило `skills/zod-sync.md`).** Каждое поле в обеих схемах снабжается описанием на русском языке с одним примером данных:
   - Zod: `.describe("Длительность задачи в рабочих днях. Пример: 5")`;
   - Pydantic: `Field(description="Длительность задачи в рабочих днях. Пример: 5")`.
   Это критично для корректного Tool Calling: LLM читает JSON Schema инструментов, сгенерированную из этих описаний.

### 2.4. Валидация на границах

- **Frontend:** каждый ответ API/LLM прогоняется через `GanttTaskSchema.array().parse()` в try-catch. При `ZodError` UI не падает: показывается Toast-уведомление с текстом ошибки, состояние задач не изменяется.
- **Backend:** входящие данные валидируются Pydantic; ошибки бизнес-логики (цикл в графе, неизвестный `id`) возвращаются как `HTTPException` с кодами 400/404/422 и человекочитаемым `detail`.

---

## 3. Data Flow (Поток данных)

### 3.1. Поток 1 — загрузка данных (Excel / Seed)

```
Excel (.xlsx) ──> POST /api/tasks/upload ──> excel_parser.py (openpyxl)
                                                    │
Seed-данные ──> GET /api/tasks ──> seed.py ─────────┤
                                                    ▼
                                              RawTask[] ──> task_store.py (сохранение состояния)
                                                    │
                                                    ▼
                                       scheduler.py (DAG Scheduler)
                                        • валидация ссылок predecessors
                                        • проверка циклов -> CyclicDependencyError
                                        • топологическая сортировка (Kahn / DFS)
                                        • расчёт start_date / end_date
                                                    │
                                                    ▼
                                              GanttTask[]
                                                    │
                                                    ▼
                              FastAPI response (Pydantic, by_alias=True -> camelCase JSON)
                                                    │
                                                    ▼
                          frontend/src/api/client.ts: GanttTaskSchema.array().parse()
                                        │ (ZodError -> Toast, UI не падает)
                                                    ▼
                                   useTasks -> GanttChart (Gantt UI render)
```

Шаги:
1. Пользователь загружает `.xlsx` через `FileUpload.tsx`, либо приложение при старте запрашивает seed-данные.
2. `excel_parser.py` читает строки через openpyxl и строит `RawTask[]` (без дат); `seed.py` отдаёт демо-набор `RawTask[]`.
3. `RawTask[]` сохраняется в `task_store.py` как текущее состояние проекта.
4. `scheduler.py` строит DAG по `predecessors`, проверяет циклы (при цикле — `CyclicDependencyError` → `HTTPException 400`), выполняет топологическую сортировку и вычисляет `start_date`/`end_date`: задача без предшественников стартует от базовой даты проекта; задача с предшественниками — со дня, следующего за максимальным `end_date` предшественников; `end_date = start_date + duration_days - 1`.
5. FastAPI сериализует `GanttTask[]` в camelCase JSON.
6. Фронтенд валидирует ответ Zod-схемой и рендерит диаграмму Гантта.

### 3.2. Поток 2 — мутации через чат (LLM Tool Calling / MCP)

```
User Chat (ChatPanel.tsx)
        │  POST /api/chat { message, история }
        ▼
FastAPI routers/chat.py ──> llm_client.py ──> OpenRouter API (LLM)
                                                    │
                                    LLM Tool Call (MCP-инструмент:
                              update_task_details / add_new_task / delete_tasks)
                                                    │
                                                    ▼
                                 mcp_server.py: Task Mutation
                              (мутация RawTask[] из task_store.py)
                                                    │
                                                    ▼
                                    scheduler.py (DAG Scheduler)
                              (полный пересчёт дат, проверка циклов)
                                                    │
                                                    ▼
                                              GanttTask[]
                                                    │
                        ┌───────────────────────────┤
                        ▼                           ▼
        результат tool call -> LLM          camelCase JSON -> frontend
        (LLM формирует текстовый ответ)             │
                                                    ▼
                                  Zod parse -> useTasks -> UI re-render
```

Шаги:
1. Пользователь пишет запрос в чат («увеличь длительность задачи X до 7 дней»).
2. `routers/chat.py` через `llm_client.py` отправляет в OpenRouter сообщение пользователя, историю и JSON Schema MCP-инструментов.
3. LLM возвращает tool call; backend исполняет соответствующий MCP-инструмент.
4. Инструмент мутирует `RawTask[]` (никогда не трогает даты напрямую) и вызывает `scheduler.py` для полного пересчёта.
5. Результат (`GanttTask[]`) возвращается LLM для формирования текстового ответа и — вместе с текстом ответа — фронтенду.
6. Фронтенд валидирует `GanttTask[]` через Zod и перерисовывает диаграмму. Ошибки (цикл, неизвестный id, ZodError) показываются как Toast.

Инварианты потоков (из `system.md`):
- Даты вычисляются ТОЛЬКО в `scheduler.py`; фронтенд и LLM-промпты никогда не считают `startDate`/`endDate`.
- Любая мутация проходит полный цикл: `RawTask[] -> scheduler -> GanttTask[]`.
- Каждая мутация зависимостей/длительности сопровождается проверкой цикличности; при цикле — `CyclicDependencyError`, мутация откатывается, состояние остаётся консистентным.

---

## 4. Спецификация MCP-инструментов (FastMCP)

Общие правила для всех инструментов (`backend/app/mcp_server.py`):
- Инструменты **агностичны к UI**: не знают о React, не форматируют текст для пользователя.
- Каждый инструмент: читает текущее `RawTask[]` из `task_store.py` → применяет мутацию → вызывает `scheduler.py` → возвращает отвалидированный `GanttTask[]` (сериализация через Pydantic).
- Все параметры инструментов описаны через Pydantic `Field(description=...)` на русском языке с примером — эти описания попадают в JSON Schema инструментов для LLM.
- При ошибке (неизвестный `id`, цикл зависимостей, невалидные данные) инструмент возвращает структурированную ошибку `{ "error": "<человекочитаемое описание>" }`, мутация не применяется (состояние `task_store` откатывается к исходному).

### 4.1. `update_task_details`

Назначение: обновить одно или несколько полей существующей задачи.

Сигнатура:

```
update_task_details(
    task_id: str,                      # Обязательный. ID изменяемой задачи. Пример: "task-3"
    title: str | None = None,          # Новое название задачи. Пример: "Разработка API"
    description: str | None = None,    # Новое описание задачи. Пример: "Реализовать REST-эндпоинты"
    assignee: str | None = None,       # Новый исполнитель. Пример: "Дмитрий Пан"
    duration_days: int | None = None,  # Новая длительность в рабочих днях (>= 1). Пример: 7
    predecessors: list[str] | None = None  # Новый ПОЛНЫЙ список ID предшественников (замена, не добавление). Пример: ["task-1"]
) -> list[GanttTask]
```

Поведение:
1. Найти задачу по `task_id`; если не найдена — ошибка `"Задача с id 'task-3' не найдена"`.
2. Применить только переданные (не-`None`) поля; `None` означает «поле не менять».
3. `predecessors` заменяется целиком: LLM обязана передавать полный итоговый список.
4. Проверить, что все `id` в `predecessors` существуют и не ссылаются на саму задачу.
5. Вызвать `scheduler.py`: проверка циклов (`CyclicDependencyError` → ошибка, откат мутации) и полный пересчёт дат.
6. Вернуть полный обновлённый `GanttTask[]` (все задачи проекта, т.к. изменение одной задачи может сдвинуть даты остальных).

Выход: `list[GanttTask]` — полный список задач с пересчитанными `start_date`/`end_date`, либо `{ "error": ... }`.

### 4.2. `add_new_task`

Назначение: добавить новую задачу в проект.

Сигнатура:

```
add_new_task(
    title: str,                        # Обязательный. Название новой задачи. Пример: "Написание тестов"
    description: str = "",             # Описание задачи. Пример: "Покрыть scheduler юнит-тестами"
    assignee: str = "",                # Исполнитель. Пример: "Дмитрий Пан"
    duration_days: int = 1,            # Длительность в рабочих днях (>= 1). Пример: 3
    predecessors: list[str] = []       # Список ID задач-предшественников. Пример: ["task-2", "task-4"]
) -> list[GanttTask]
```

Поведение:
1. Сгенерировать уникальный `id` для новой задачи на бэкенде (LLM `id` не передаёт и не придумывает).
2. Проверить `duration_days >= 1`; иначе — ошибка валидации.
3. Проверить, что все `id` из `predecessors` существуют; если нет — ошибка `"Предшественник с id '...' не найден"`, задача не добавляется.
4. Добавить `RawTask` в `task_store`, вызвать `scheduler.py` (проверка циклов + пересчёт дат).
5. Вернуть полный обновлённый `GanttTask[]`, включающий новую задачу с рассчитанными датами.

Выход: `list[GanttTask]` — полный список задач, либо `{ "error": ... }`.

### 4.3. `delete_tasks`

Назначение: удалить одну или несколько задач.

Сигнатура:

```
delete_tasks(
    task_ids: list[str]                # Обязательный. Список ID удаляемых задач. Пример: ["task-5", "task-6"]
) -> list[GanttTask]
```

Поведение:
1. Проверить, что все `task_ids` существуют; если какой-то не найден — ошибка `"Задача с id '...' не найдена"`, ничего не удаляется (операция атомарна).
2. Удалить задачи из `task_store`.
3. У всех оставшихся задач вычистить удалённые `id` из `predecessors` (осиротевшие ссылки недопустимы).
4. Вызвать `scheduler.py` для полного пересчёта дат оставшихся задач.
5. Вернуть полный обновлённый `GanttTask[]` (может быть пустым списком, если удалены все задачи).

Выход: `list[GanttTask]` — полный список оставшихся задач, либо `{ "error": ... }`.

### 4.4. Сводная таблица инструментов

| Инструмент | Входные параметры | Выход | Ключевые ошибки |
|---|---|---|---|
| `update_task_details` | `task_id` (обяз.), `title?`, `description?`, `assignee?`, `duration_days?`, `predecessors?` | `list[GanttTask]` (все задачи) | задача не найдена; предшественник не найден; ссылка на себя; `CyclicDependencyError`; `duration_days < 1` |
| `add_new_task` | `title` (обяз.), `description?`, `assignee?`, `duration_days?`, `predecessors?` | `list[GanttTask]` (все задачи, включая новую) | предшественник не найден; `CyclicDependencyError`; `duration_days < 1` |
| `delete_tasks` | `task_ids` (обяз., непустой список) | `list[GanttTask]` (оставшиеся задачи) | задача не найдена (атомарный отказ); пустой `task_ids` |
| `set_project_start_date` | `project_start_date` (обяз., ISO `YYYY-MM-DD`) | `list[GanttTask]` (все задачи) | неверный формат даты; `CyclicDependencyError` |

> ⚠️ `set_project_start_date` **строго запрещён** для сдвига отдельных задач. Используйте `duration_days` и `predecessors`. Инструмент вызывается **только** при явном запросе сдвинуть старт *всего проекта*.

---

## 5. Соответствие инвариантам `system.md`

| № | Инвариант | Как закреплён в архитектуре |
|---|---|---|
| 1 | Единый источник расчёта дат | Только `backend/app/services/scheduler.py` вычисляет `start_date`/`end_date`; фронтенд (`utils/dates.ts`) лишь форматирует ISO-даты; MCP-инструменты мутируют только `RawTask`-поля |
| 2 | Зеркалирование контрактов | Раздел 2: таблицы полей + правило одновременного изменения `frontend/src/schemas/task.ts` и `backend/app/schemas/task.py`, alias-маппинг camelCase ↔ snake_case |
| 3 | Строгая валидация и обработка ошибок | Раздел 2.4: `GanttTaskSchema.array().parse()` в try-catch + Toast; Pydantic + `HTTPException` на бэке |
| 4 | MCP-изоляция | Раздел 4: инструменты агностичны к UI, паттерн `RawTask[] + мутация -> scheduler -> GanttTask[]` |
| 5 | Отсутствие заглушек | Документ полный, без TODO и сокращений; это же требование распространяется на весь будущий код |
