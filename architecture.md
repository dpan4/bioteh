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
| AI Tool Calling | **FastMCP** (бывший) → **собственный MCP-сервер** (`mcp_server.py`) | MCP-инструменты мутации задач для LLM, инструменты агностичны к UI |
| Excel-парсинг | **openpyxl** | Чтение `.xlsx`-файлов с задачами проекта |
| LLM-провайдер | **Мультипровайдерный** (`llm_client.py`): Google Gemini (SDK `google-genai`) + OpenAI-совместимые API (`AsyncOpenAI`) | OpenRouter, OpenAI, DeepSeek, Groq, Ollama, Gemini; ключи через `LLM_API_KEY` / `GEMINI_API_KEY` |

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
│   ├── package.json                 # Зависимости: react, react-dom, zod, vite
│   ├── package-lock.json
│   ├── tsconfig.json                # strict: true
│   ├── vite.config.ts               # Конфиг Vite + proxy на backend (/api -> :8000)
│   └── src/
│       ├── main.tsx                 # Bootstrap React-приложения
│       ├── App.tsx                  # Корневой layout: GanttChart + ChatPanel + UndoRedoControls
│       ├── schemas/
│       │   └── task.ts              # Zod-схемы: RawTaskSchema, GanttTaskSchema (зеркало Pydantic)
│       ├── api/
│       │   └── client.ts            # HTTP-клиент: fetch + Zod-parse всех ответов
│       ├── components/
│       │   ├── GanttChart.tsx       # Рендер диаграммы Гантта из GanttTask[]
│       │   ├── ChatPanel.tsx        # Чат с LLM (история сообщений, ввод)
│       │   ├── FileUpload.tsx       # Загрузка Excel-файла (.xlsx)
│       │   ├── TaskDetailModal.tsx  # Модалка деталей задачи (даты, исполнитель, зависимости)
│       │   ├── Toast.tsx            # Toast-уведомления об ошибках (валидация, сеть, циклы)
│       │   └── UndoRedoControls.tsx # Кнопки Undo/Redo с горячими клавишами Ctrl+Z/Y
│       └── hooks/
│           └── useTasks.ts          # Состояние GanttTask[]: загрузка, обновление, undo/redo
│
└── backend/
    ├── requirements.txt             # Зависимости Python
    ├── Dockerfile                   # Docker-конфиг для бэкенда
    ├── data/                        # Персистентное хранилище tasks.json
    ├── logs/                        # Логи чата (NDJSON, по папкам YYYY-MM-DD/)
    ├── tests/                       # pytest + snapshot-тесты
    └── app/
        ├── __init__.py
        ├── main.py                  # FastAPI-приложение: CORS, роутеры, обработчики ошибок
        ├── logger.py                # Цветной ANSI-логгер с тегами
        ├── mcp_server.py            # MCP-сервер: TOOL_DEFINITIONS + execute_tool_call диспетчер
        ├── prompts/
        │   └── system.md            # Системный промпт для LLM с подстановкой задач
        ├── schemas/
        │   ├── __init__.py
        │   └── task.py              # Pydantic v2: RawTask, GanttTask (зеркало Zod), ChatRequest/Response
        ├── services/
        │   ├── __init__.py
        │   ├── scheduler.py         # DAG Scheduler — ЕДИНСТВЕННЫЙ источник расчёта дат
        │   ├── excel_parser.py      # openpyxl: .xlsx -> RawTask[] + генерация шаблонов
        │   ├── task_store.py        # In-memory хранилище RawTask[] + персистентность в JSON
        │   ├── llm_client.py        # Мультипровайдерный клиент: Google Gemini + AsyncOpenAI
        │   ├── agent_loop.py        # Цикл Tool Calling с защитой от зацикливания и валидацией
        │   ├── grounding.py         # Post-Tool и Post-Reply проверки дат (конфликты, заземление)
        │   ├── request_parser.py    # Парсинг запросов: извлечение tool calls из естественного языка
        │   └── utils/
        │       ├── __init__.py
        │       ├── logger.py        # Утилита NDJSON-логов чата (logs/YYYY-MM-DD/)
        │       └── parsers.py       # Утилиты: извлечение дат, нормализация tool calls, языковой guard
        ├── routers/
        │   ├── __init__.py
        │   ├── tasks.py             # GET /api/tasks, POST /upload, PUT /sync, GET /export, GET /template
        │   └── chat.py              # POST /api/chat (Tool Calling Loop + grounding)
        └── utils/
            ├── __init__.py
            ├── logger.py            # Утилитарный логгер
            └── parsers.py           # Утилитарные парсеры (даты, месяцы)
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
2. `excel_parser.py` читает строки через openpyxl и строит `RawTask[]` (без дат); при пустом хранилище `task_store.py` автоматически подгружает seed-данные (5 задач с логичными зависимостями).
3. `RawTask[]` сохраняется в `task_store.py` как текущее состояние проекта.
4. `scheduler.py` строит DAG по `predecessors`, проверяет циклы (при цикле — `CyclicDependencyError` → `HTTPException 400`), выполняет топологическую сортировку и вычисляет `start_date`/`end_date`: задача без предшественников стартует от базовой даты проекта; задача с предшественниками — со дня, следующего за максимальным `end_date` предшественников; `end_date = start_date + duration_days - 1`.
5. FastAPI сериализует `GanttTask[]` в camelCase JSON.
6. Фронтенд валидирует ответ Zod-схемой и рендерит диаграмму Гантта.

### 3.2. Поток 2 — мутации через чат (LLM Tool Calling / MCP)

```
User Chat (ChatPanel.tsx)
        │  POST /api/chat { message, история }
        ▼
FastAPI routers/chat.py ──> request_parser.py (анализ запроса, шаблоны tool_calls)
        │
        ▼
llm_client.py ──> OpenRouter API / Google Gemini / AsyncOpenAI
        │
        ▼
LLM Tool Call (MCP-инструмент:
  update_task_details / add_new_task / delete_tasks /
  set_project_start_date / clear_all_tasks / get_excel_template)
        │
        ▼
mcp_server.py: execute_tool_call() — диспетчер с валидацией аргументов
(камелCase → snake_case, приведение типов, Pydantic-валидация)
        │
        ▼
agent_loop.py: run_tool_calling_loop()
(многораундовый цикл, защита от зацикливания, Post-Tool grounding)
        │
        ▼
mcp_server.py: инструмент мутирует RawTask[] из task_store.py
        │
        ▼
scheduler.py (DAG Scheduler)
(полный пересчёт дат, проверка циклов)
        │
        ▼
GanttTask[]
        │
        ▼
grounding.py: grounding_check() — Post-Reply проверка дат в ответе LLM
        │
        ▼
camelCase JSON -> frontend
        │
        ▼
Zod parse -> useTasks -> UI re-render
```

Шаги:
1. Пользователь пишет запрос в чат («увеличь длительность задачи X до 7 дней»).
2. `routers/chat.py` через `request_parser.py` предварительно анализирует запрос и генерирует шаблоны tool calls для помощи LLM.
3. `routers/chat.py` через `llm_client.py` отправляет в LLM сообщение пользователя, историю и JSON Schema MCP-инструментов.
4. LLM возвращает tool call (или текст с XML/JSON — перехватывается валидационным слоем `agent_loop.py`); `mcp_server.py` диспетчеризует вызов через `execute_tool_call()`.
5. Инструмент мутирует `RawTask[]` (никогда не трогает даты напрямую) и вызывает `scheduler.py` для полного пересчёта.
6. `agent_loop.py` выполняет Post-Tool grounding: сравнивает запрошенные пользователем даты с фактическими датами задач и при конфликте инъецирует пояснение в контекст LLM.
7. Результат (`GanttTask[]`) возвращается LLM для формирования текстового ответа и — вместе с текстом ответа — фронтенду.
8. `grounding_check()` выполняет Post-Reply grounding: сверяет даты в текстовом ответе LLM с актуальными датами задач; при обнаружении галлюцинированных дат добавляет поправку в ответ.
9. Фронтенд валидирует `GanttTask[]` через Zod и перерисовывает диаграмму. Ошибки (цикл, неизвестный id, ZodError) показываются как Toast.

Инварианты потоков (из `system.md`):
- Даты вычисляются ТОЛЬКО в `scheduler.py`; фронтенд и LLM-промпты никогда не считают `startDate`/`endDate`.
- Любая мутация проходит полный цикл: `RawTask[] -> scheduler -> GanttTask[]`.
- Каждая мутация зависимостей/длительности сопровождается проверкой цикличности; при цикле — `CyclicDependencyError`, мутация откатывается, состояние остаётся консистентным.
- Защита от зацикливания: `agent_loop.py` отслеживает уникальные сигнатуры вызовов инструментов и прерывает цикл при обнаружении повтора (максимум 5 раундов).

---

## 4. Спецификация MCP-инструментов (mcp_server.py)

Общие правила для всех инструментов (`backend/app/mcp_server.py`):
- Инструменты **агностичны к UI**: не знают о React, не форматируют текст для пользователя.
- Каждый инструмент: читает текущее `RawTask[]` из `task_store.py` → применяет мутацию → вызывает `scheduler.py` → возвращает отвалидированный `GanttTask[]` (сериализация через Pydantic).
- Все параметры инструментов описаны через Pydantic `Field(description=...)` на русском языке с примером — эти описания попадают в JSON Schema инструментов для LLM.
- При ошибке (неизвестный `id`, цикл зависимостей, невалидные данные) инструмент возвращает структурированную ошибку `{ "error": "<человекочитаемое описание>" }`, мутация не применяется (состояние `task_store` откатывается к исходному).
- Диспетчер `execute_tool_call()` выполняет маппинг camelCase → snake_case, приведение типов и Pydantic-валидацию перед вызовом реализации.

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
    preferred_start_date: str | None = None  # Желаемая дата начала (YYYY-MM-DD). Пример: "2026-09-04"
) -> list[GanttTask] | { "error": str }
```

Поведение:
1. Найти задачу по `task_id`; если не найдена — ошибка `"Задача с id 'task-3' не найдена"`.
2. Применить только переданные (не-`None`) поля; `None` означает «поле не менять».
3. `predecessors` заменяется целиком: LLM обязана передавать полный итоговый список.
4. Проверить, что все `id` в `predecessors` существуют и не ссылаются на саму задачу.
5. `preferred_start_date` сохраняется даже при наличии предшественников — планировщик учитывает его как ограничение снизу (max constraint).
6. Вызвать `scheduler.py`: проверка циклов (`CyclicDependencyError` → ошибка, откат мутации) и полный пересчёт дат.
7. Вернуть полный обновлённый `GanttTask[]` (все задачи проекта, т.к. изменение одной задачи может сдвинуть даты остальных).

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
    predecessors: list[str] = [],      # Список ID задач-предшественников. Пример: ["task-2", "task-4"]
    preferred_start_date: str | None = None  # Желаемая дата начала (YYYY-MM-DD). Пример: "2026-09-04"
) -> list[GanttTask] | { "error": str }
```

Поведение:
1. Сгенерировать уникальный `id` для новой задачи на бэкенде (LLM `id` не передаёт и не придумывает).
2. Проверить `duration_days >= 1`; иначе — ошибка валидации.
3. Проверить, что все `id` из `predecessors` существуют; если нет — ошибка `"Предшественник с id '...' не найден"`, задача не добавляется.
4. `preferred_start_date` сохраняется даже при наличии предшественников — планировщик учитывает его как ограничение снизу.
5. Добавить `RawTask` в `task_store`, вызвать `scheduler.py` (проверка циклов + пересчёт дат).
6. Вернуть полный обновлённый `GanttTask[]`, включающий новую задачу с рассчитанными датами.

Выход: `list[GanttTask]` — полный список задач, либо `{ "error": ... }`.

### 4.3. `delete_tasks`

Назначение: удалить одну или несколько задач.

Сигнатура:

```
delete_tasks(
    task_ids: list[str]                # Обязательный. Список ID удаляемых задач. Пример: ["task-5", "task-6"]
) -> list[GanttTask] | { "error": str }
```

Поведение:
1. Если ни один из `task_ids` не найден в проекте — возвращается актуальный граф без ошибки (идемпотентность).
2. Если часть `task_ids` не найдена — удаляются только существующие задачи, не существующие игнорируются.
3. Удалить задачи из `task_store`.
4. У всех оставшихся задач вычистить удалённые `id` из `predecessors` (осиротевшие ссылки недопустимы).
5. Вызвать `scheduler.py` для полного пересчёта дат оставшихся задач.
6. Вернуть полный обновлённый `GanttTask[]` (может быть пустым списком, если удалены все задачи).

Выход: `list[GanttTask]` — полный список оставшихся задач, либо `{ "error": ... }`.

### 4.4. `set_project_start_date`

Назначение: сдвинуть базовую дату старта всего проекта и пересчитать все задачи.

Сигнатура:

```
set_project_start_date(
    project_start_date: str            # Обязательный. ISO YYYY-MM-DD. Пример: "2026-08-01"
) -> list[GanttTask] | { "error": str }
```

Поведение:
1. Валидировать формат даты (YYYY-MM-DD); при невалидном формате — ошибка.
2. Обновить `project_start_date` в `TaskStore`.
3. Вызвать `scheduler.py` для полного пересчёта дат всех задач.
4. Вернуть полный обновлённый `GanttTask[]`.

> ⚠️ Этот инструмент **строго запрещён** для сдвига отдельных задач. Используйте `duration_days` и `predecessors`. Инструмент вызывается **только** при явном запросе сдвинуть старт *всего проекта*.

### 4.5. `clear_all_tasks`

Назначение: полностью очистить таблицу задач.

Сигнатура:

```
clear_all_tasks() -> list[GanttTask] | { "error": str }
```

Поведение:
1. Очистить `task_store` (удалить все задачи).
2. Вернуть пустой список `[]`.

### 4.6. `get_excel_template`

Назначение: получить эталонный Excel-шаблон для заполнения проекта (5 колонок).

Сигнатура:

```
get_excel_template() -> { "template": str (base64), "filename": str, "mime_type": str } | { "error": str }
```

Поведение:
1. Сформировать `.xlsx` файл с 5 колонками: Задача, Описание, Исполнитель, Длительность (дни), Предшественники.
2. БЕЗ колонок ID, Дата начала, Дата окончания (даты рассчитает бэкенд при импорте).
3. 5 демо-строк с наглядными примерами заполнения. Предшественники указываются как номера строк (1, 2, 3, 4), НЕ task-N.
4. Вернуть base64-кодированное содержимое файла.

### 4.7. Сводная таблица инструментов

| Инструмент | Входные параметры | Выход | Ключевые ошибки |
|---|---|---|---|
| `update_task_details` | `task_id` (обяз.), `title?`, `description?`, `assignee?`, `duration_days?`, `predecessors?`, `preferred_start_date?` | `list[GanttTask]` (все задачи) | задача не найдена; предшественник не найден; ссылка на себя; `CyclicDependencyError`; `duration_days < 1` |
| `add_new_task` | `title` (обяз.), `description?`, `assignee?`, `duration_days?`, `predecessors?`, `preferred_start_date?` | `list[GanttTask]` (все задачи, включая новую) | предшественник не найден; `CyclicDependencyError`; `duration_days < 1` |
| `delete_tasks` | `task_ids` (обяз., непустой список) | `list[GanttTask]` (оставшиеся задачи) | задача не найдена (идемпотентный пропуск); пустой `task_ids` |
| `set_project_start_date` | `project_start_date` (обяз., ISO `YYYY-MM-DD`) | `list[GanttTask]` (все задачи) | неверный формат даты; `CyclicDependencyError` |
| `clear_all_tasks` | (нет параметров) | `list[GanttTask]` (пустой `[]`) | — |
| `get_excel_template` | (нет параметров) | `{ template: base64, filename, mime_type }` | ошибка генерации шаблона |

---

## 5. Соответствие инвариантам `system.md`

| № | Инвариант | Как закреплён в архитектуре |
|---|---|---|
| 1 | Единый источник расчёта дат | Только `backend/app/services/scheduler.py` вычисляет `start_date`/`end_date`; MCP-инструменты мутируют только `RawTask`-поля; `preferred_start_date` учитывается как ограничение снизу |
| 2 | Зеркалирование контрактов | Раздел 2: таблицы полей + правило одновременного изменения `frontend/src/schemas/task.ts` и `backend/app/schemas/task.py`, alias-маппинг camelCase ↔ snake_case |
| 3 | Строгая валидация и обработка ошибок | Раздел 2.4: `GanttTaskSchema.array().parse()` в try-catch + Toast; Pydantic + `HTTPException` на бэке; диспетчер `mcp_server.py` валидирует аргументы через Pydantic |
| 4 | MCP-изоляция | Раздел 4: инструменты агностичны к UI, паттерн `RawTask[] + мутация -> scheduler -> GanttTask[]` |
| 5 | Отсутствие заглушек | Документ полный, без TODO и сокращений; это же требование распространяется на весь будущий код |
| 6 | Мультипровайдерность LLM | `llm_client.py` поддерживает Gemini (через `google-genai` SDK) и OpenAI-совместимые API (через `AsyncOpenAI`); автоопределение по имени модели |
| 7 | Защита от зацикливания | `agent_loop.py` отслеживает уникальные сигнатуры вызовов инструментов; при обнаружении повтора — прерывание цикла (максимум 5 раундов) |
| 8 | Grounding проверок | `grounding.py` выполняет Post-Tool проверку (конфликты дат) и Post-Reply grounding (галлюцинации дат в ответе LLM) |

---

## 6. Тестирование

### 6.1. Snapshot-тесты (pytest)

Проект использует **data-driven snapshot-тестирование** на базе `pytest`. Тесты воспроизводят реальные диалоги с AI-ассистентом из логов `backend/logs/` и проверяют корректность результатов (генерация ответа и обновление табличного состояния).

**Структура тестов:**

```
backend/
└── tests/
    ├── test_agent_evals.py       # Основной файл тестов
    ├── eval_cases/               # Снэпшоты реальных диалогов (JSON)
    │   ├── 11-36-07_update_task_details.json
    │   ├── 11-38-08_add_new_task.json
    │   └── ...
    └── result/
        ├── test.md               # Отчёт о результатах тестов
        └── test2.md
```

**Как работает тест:**
1. Тест загружает все `.json`-файлы из `backend/tests/eval_cases/`.
2. Для каждого файла восстанавливает состояние `TaskStore` из `tasks_before`.
3. Вызывает `execute_tool_call()` для каждого `tool_call` из лога.
4. Сравнивает итоговое состояние `TaskStore` с `tasks_after` (количество задач, ID, поля) и подсвечивает расхождения.

**Запуск:**
```bash
cd backend
python -m pytest tests/test_agent_evals.py -v
```

**Как добавить новый Eval-кейс:**
1. Открой папку логов за нужную дату: `backend/logs/YYYY-MM-DD/`.
2. Найди JSON-файл нужного вызова (например, `12-20-51_update_task_details.json`).
3. Скопируй его в `backend/tests/eval_cases/`:
   ```bash
   # Windows
   Copy-Item backend\logs\2026-08-03\12-20-51_update_task_details.json backend\tests\eval_cases\
   # Linux / macOS
   cp backend/logs/2026-08-03/12-20-51_update_task_details.json backend/tests/eval_cases/
   ```
4. Запусти `pytest` — тесты автоматически пройдутся по всем `.json` в папке и подсветят расхождения в генерации или обновлении табличного состояния.

### 6.2. Валидация на границах (runtime)

Помимо snapshot-тестов, валидация выполняется в рантайме:
- **Фронтенд:** каждый ответ API/LLM прогоняется через `GanttTaskSchema.array().parse()` в try-catch. При `ZodError` UI не падает — показывается Toast.
- **Бэкенд:** входящие данные валидируются Pydantic; ошибки бизнес-логики (цикл в графе, неизвестный `id`) возвращаются как `HTTPException` с кодами 400/404/422.
- **MCP-диспетчер:** аргументы инструментов валидируются через Pydantic-схемы (`_normalize_arguments`) перед выполнением.

### 6.3. Тестирование фронтенда

На данный момент фронтенд не имеет unit-тестов. UI-валидация выполняется вручную через dev-сервер (`npm run dev`) и через интеграцию с бэкендом.
