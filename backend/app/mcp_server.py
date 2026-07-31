"""MCP-инструменты мутации задач диаграммы Гантта (UI-агностичные).

Архитектура (§4):
- Инструменты не знают о React/UI, работают только с RawTask[] и TaskStore.
- Каждый инструмент: читает текущее состояние → мутирует → scheduler → GanttTask[].
- При ошибке (цикл, невалидные ссылки) состояние откатывается.
- Параметры описаны через Pydantic Field(description=...) — генерирует JSON Schema
  для OpenRouter Tool Calling.

Экспортирует:
- TOOL_DEFINITIONS: список дефиниций в формате OpenRouter function calling.
- execute_tool_call(name, args): диспетчер для вызова из chat-роутера.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.task import GanttTask, RawTask
from app.services.scheduler import CyclicDependencyError, calculate_schedule
from app.services.task_store import store


# ═══════════════════════════════════════════════════════════════════════════════
# Pydantic-модели параметров инструментов (генерируют JSON Schema для LLM)
# ═══════════════════════════════════════════════════════════════════════════════

class UpdateTaskParams(BaseModel):
    """Параметры инструмента update_task_details."""

    task_id: str = Field(
        description='ID изменяемой задачи. Пример: "task-3"',
        examples=["task-3"],
    )
    title: str | None = Field(
        default=None,
        description='Новое название задачи. Не передавайте, если менять не нужно. Пример: "Разработка API"',
        examples=["Разработка API"],
    )
    description: str | None = Field(
        default=None,
        description='Новое описание задачи. Не передавайте, если менять не нужно. Пример: "Реализовать REST-эндпоинты"',
        examples=["Реализовать REST-эндпоинты"],
    )
    assignee: str | None = Field(
        default=None,
        description='Новый исполнитель. Не передавайте, если менять не нужно. Пример: "Дмитрий Пан"',
        examples=["Дмитрий Пан"],
    )
    duration_days: int | None = Field(
        default=None,
        ge=1,
        description='Новая длительность в рабочих днях (не меньше 1). Не передавайте, если менять не нужно. Пример: 7',
        examples=[7],
    )
    predecessors: list[str] | None = Field(
        default=None,
        description='ПОЛНЫЙ новый список ID предшественников (замена, не добавление). Не передавайте, если менять не нужно. Пример: ["task-1"]',
        examples=[["task-1"]],
    )


class AddTaskParams(BaseModel):
    """Параметры инструмента add_new_task."""

    title: str = Field(
        min_length=1,
        description='Название новой задачи. Пример: "Написание тестов"',
        examples=["Написание тестов"],
    )
    description: str = Field(
        default="",
        description='Описание задачи. Пример: "Покрыть scheduler юнит-тестами"',
        examples=["Покрыть scheduler юнит-тестами"],
    )
    assignee: str = Field(
        default="",
        description='Исполнитель задачи. Пример: "Дмитрий Пан"',
        examples=["Дмитрий Пан"],
    )
    duration_days: int = Field(
        default=1,
        ge=1,
        description='Длительность в рабочих днях (не меньше 1). Пример: 3',
        examples=[3],
    )
    predecessors: list[str] = Field(
        default_factory=list,
        description='Список ID задач-предшественников (может быть пустым). Пример: ["task-2", "task-4"]',
        examples=[["task-2", "task-4"]],
    )


class DeleteTasksParams(BaseModel):
    """Параметры инструмента delete_tasks."""

    task_ids: list[str] = Field(
        min_length=1,
        description='Список ID удаляемых задач. Пример: ["task-5", "task-6"]',
        examples=[["task-5", "task-6"]],
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Дефиниции инструментов в формате OpenRouter function calling
# ═══════════════════════════════════════════════════════════════════════════════

TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "update_task_details",
            "description": (
                "Изменить одно или несколько полей существующей задачи диаграммы Гантта. "
                "Передавайте ТОЛЬКО те поля, которые нужно изменить; остальные оставляйте "
                "незаполненными (null). Поле predecessors всегда передаётся как ПОЛНЫЙ "
                "список (замена всех предшественников). После вызова даты всех задач "
                "пересчитываются автоматически."
            ),
            "parameters": UpdateTaskParams.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_new_task",
            "description": (
                "Добавить новую задачу в проект. ID генерируется автоматически на сервере — "
                "не пытайтесь придумать или передать id. Укажите название, описание, "
                "исполнителя, длительность и список предшественников (если есть). "
                "После добавления даты всех задач пересчитываются."
            ),
            "parameters": AddTaskParams.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_tasks",
            "description": (
                "Удалить одну или несколько задач по их ID. Удаление атомарно: если хотя бы "
                "один ID не найден, ни одна задача не удаляется. Ссылки на удалённые задачи "
                "автоматически очищаются из predecessors оставшихся задач. Даты "
                "пересчитываются."
            ),
            "parameters": DeleteTasksParams.model_json_schema(),
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Реализация инструментов
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize_tasks(tasks: list[GanttTask]) -> list[dict[str, Any]]:
    """Сериализует список GanttTask в camelCase-словари для JSON."""
    return [task.model_dump(by_alias=True) for task in tasks]


def execute_update_task_details(
    task_id: str,
    title: str | None = None,
    description: str | None = None,
    assignee: str | None = None,
    duration_days: int | None = None,
    predecessors: list[str] | None = None,
) -> dict[str, Any]:
    """Обновляет поля существующей задачи.

    Передаются только изменяемые поля; None = поле не трогать.
    predecessors заменяется целиком переданным списком.

    Архитектура §4.1: сигнатура соответствует контракту update_task_details.
    """
    raw_tasks = store.get_raw_tasks()
    backup = [task.model_copy(deep=True) for task in raw_tasks]

    target = next((t for t in raw_tasks if t.id == task_id), None)
    if target is None:
        return {"error": f"Задача с id '{task_id}' не найдена."}

    all_ids = {t.id for t in raw_tasks}

    if title is not None:
        target.title = title
    if description is not None:
        target.description = description
    if assignee is not None:
        target.assignee = assignee
    if duration_days is not None:
        if duration_days < 1:
            return {"error": f"Длительность должна быть не меньше 1 дня, получено {duration_days}."}
        target.duration_days = duration_days

    if predecessors is not None:
        if task_id in predecessors:
            return {"error": f"Задача не может зависеть от самой себя (id '{task_id}' в predecessors)."}
        for pred_id in predecessors:
            if pred_id not in all_ids:
                return {"error": f"Предшественник с id '{pred_id}' не найден среди задач проекта."}
        target.predecessors = list(predecessors)

    try:
        scheduled = calculate_schedule(raw_tasks, store._project_start_date)
    except (CyclicDependencyError, ValueError) as exc:
        store._raw_tasks = backup
        return {"error": str(exc)}

    store._raw_tasks = raw_tasks
    return {"tasks": _serialize_tasks(scheduled)}


def execute_add_new_task(
    title: str,
    description: str = "",
    assignee: str = "",
    duration_days: int = 1,
    predecessors: list[str] | None = None,
) -> dict[str, Any]:
    """Добавляет новую задачу с автоматической генерацией ID.

    ID генерируется как task-N, где N = max(существующие номера) + 1.
    LLM НЕ передаёт id — он создаётся на бэкенде.

    Архитектура §4.2: сигнатура соответствует контракту add_new_task.
    """
    if predecessors is None:
        predecessors = []

    raw_tasks = store.get_raw_tasks()
    backup = [task.model_copy(deep=True) for task in raw_tasks]

    all_ids = {t.id for t in raw_tasks}
    for pred_id in predecessors:
        if pred_id not in all_ids:
            return {"error": f"Предшественник с id '{pred_id}' не найден среди задач проекта."}

    max_num = 0
    for tid in all_ids:
        if tid.startswith("task-"):
            try:
                num = int(tid.split("-", 1)[1])
                if num > max_num:
                    max_num = num
            except ValueError:
                continue
    new_id = f"task-{max_num + 1}"

    new_task = RawTask(
        id=new_id,
        title=title,
        description=description,
        assignee=assignee,
        duration_days=duration_days,
        predecessors=predecessors,
    )
    raw_tasks.append(new_task)

    try:
        scheduled = calculate_schedule(raw_tasks, store._project_start_date)
    except (CyclicDependencyError, ValueError) as exc:
        store._raw_tasks = backup
        return {"error": str(exc)}

    store._raw_tasks = raw_tasks
    return {"tasks": _serialize_tasks(scheduled)}


def execute_delete_tasks(task_ids: list[str]) -> dict[str, Any]:
    """Удаляет задачи атомарно: все или ничего.

    Осиротевшие ссылки в predecessors оставшихся задач очищаются.
    После удаления даты оставшихся задач пересчитываются.

    Архитектура §4.3: сигнатура соответствует контракту delete_tasks.
    """
    raw_tasks = store.get_raw_tasks()
    backup = [task.model_copy(deep=True) for task in raw_tasks]

    all_ids = {t.id for t in raw_tasks}
    for tid in task_ids:
        if tid not in all_ids:
            return {"error": f"Задача с id '{tid}' не найдена. Операция отменена."}

    remove_set = set(task_ids)
    remaining = [t for t in raw_tasks if t.id not in remove_set]
    for task in remaining:
        task.predecessors = [p for p in task.predecessors if p not in remove_set]

    try:
        scheduled = calculate_schedule(remaining, store._project_start_date)
    except (CyclicDependencyError, ValueError) as exc:
        store._raw_tasks = backup
        return {"error": str(exc)}

    store._raw_tasks = remaining
    return {"tasks": _serialize_tasks(scheduled)}


# ═══════════════════════════════════════════════════════════════════════════════
# Диспетчер
# ═══════════════════════════════════════════════════════════════════════════════

def execute_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Вызывает инструмент мутации по имени и аргументам.

    Args:
        name: Имя инструмента (update_task_details, add_new_task, delete_tasks).
        arguments: Словарь аргументов, полученный от LLM (camelCase).

    Returns:
        Словарь с ключом "tasks" (list[GanttTask] в camelCase) или "error" (str).
    """
    if name == "update_task_details":
        return execute_update_task_details(**arguments)
    if name == "add_new_task":
        return execute_add_new_task(**arguments)
    if name == "delete_tasks":
        return execute_delete_tasks(**arguments)
    return {"error": f"Неизвестный инструмент: '{name}'."}