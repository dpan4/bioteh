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

import base64
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.schemas.task import GanttTask, RawTask
from app.services.excel_parser import generate_template_excel
from app.services.scheduler import CyclicDependencyError, calculate_schedule
from app.services.task_store import store

logger = logging.getLogger(__name__)


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
        description=(
            'Имя исполнителя задачи. '
            'Если нужно СНЯТЬ/УДАЛИТЬ исполнителя с задачи (например, "удалить Анну из task-1") — '
            'передавай ПУСТУЮ СТРОКУ "" (не null, а именно пустую строку)! '
            'Если менять исполнителя не нужно — не передавай этот параметр вообще (оставь null). '
            'Пример назначения: "Дмитрий Пан". '
            'Пример снятия: ""'
        ),
        examples=["Дмитрий Пан", ""],
    )
    duration_days: int | None = Field(
        default=None,
        ge=1,
        description=(
            'Длительность задачи в рабочих днях (не меньше 1). '
            'ФОРМУЛА РАСЧЁТА: duration_days = (Дата окончания - Дата начала + 1 день). '
            'ПРИМЕРЫ РАСЧЁТА: '
            '- Со 2 по 18 августа включительно = 18 - 2 + 1 = 17 дней. '
            '- С 20 августа по 2 сентября = (2 + 31) - 20 + 1 = 14 дней. '
            '- С 5 по 12 марта = 12 - 5 + 1 = 8 дней. '
            'ВНИМАНИЕ: Учитывай количество дней в месяцах при расчёте! '
            'Не передавай этот параметр, если менять длительность не нужно. '
            'Пример: 7'
        ),
        examples=[7, 17, 14],
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
        description=(
            'Список ID задач, которые нужно ПОЛНОСТЬЮ УДАЛИТЬ ИЗ ПРОЕКТА. '
            'ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ ТОЛЬКО если пользователь явно просит УДАЛИТЬ/УБРАТЬ ЗАДАЧУ целиком! '
            'ЗАПРЕЩЕНО использовать для смены или удаления исполнителя — для этого используй update_task_details с assignee=""! '
            'Примеры правильного использования: '
            '- "Удали задачу task-5 из проекта" → delete_tasks(["task-5"]). '
            '- "Убери задачу Дмитрия" → delete_tasks(["task-3"]). '
            'Примеры НЕПРАВИЛЬНОГО использования: '
            '- "Удали Анну из task-1" → НЕ delete_tasks! Используй update_task_details(task_id="task-1", assignee=""). '
            '- "Убери Дмитрия из графика" → НЕ delete_tasks! Используй update_task_details для смены assignee. '
            'Пример: ["task-5", "task-6"]'
        ),
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
                "ПОЛНОСТЬЮ УДАЛИТЬ одну или несколько ЗАДАЧ из проекта. "
                "КРИТИЧЕСКИ ВАЖНО: ИСПОЛЬЗУЙ ЭТОТ ИНСТРУМЕНТ ТОЛЬКО если пользователь явно просит "
                "УДАЛИТЬ/УБРАТЬ ЗАДАЧУ ЦЕЛИКОМ из проекта! "
                "ЗАПРЕЩЕНО использовать для смены или удаления исполнителя — для этого есть "
                "update_task_details с параметром assignee=\"\"! "
                "Удаление атомарно: если хотя бы один ID не найден, ни одна задача не удаляется. "
                "Ссылки на удалённые задачи автоматически очищаются из predecessors оставшихся задач. "
                "Даты пересчитываются. "
                "ПРАВИЛЬНЫЕ примеры использования: "
                "«Удали задачу task-5», «Убери задачу Дмитрия из проекта». "
                "НЕПРАВИЛЬНЫЕ примеры (НЕ используй delete_tasks!): "
                "«Удали Анну из task-1» → используй update_task_details(task_id='task-1', assignee='')."
            ),
            "parameters": DeleteTasksParams.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_excel_template",
            "description": (
                "Получить эталонный Excel-шаблон для заполнения проекта. Шаблон содержит "
                "5 колонок (Задача, Описание, Исполнитель, Длительность, Предшественники) "
                "и 5 демо-строк с примерами заполнения. Предшественники указываются как "
                "номера строк (1, 2, 3, 4). Возвращает base64-кодированное содержимое .xlsx файла."
            ),
            "parameters": {},
        },
    },
]


# ═══════════════════════════════════════════════════════════════════════════════
# Реализация инструментов
# ═══════════════════════════════════════════════════════════════════════════════

def _serialize_tasks(tasks: list[GanttTask]) -> list[dict[str, Any]]:
    """Сериализует список GanttTask в camelCase-словари для JSON.
    
    ВАЖНО: Использует mode='json' для корректной сериализации date-объектов в ISO-строки.
    Без mode='json' Pydantic возвращает Python date-объекты, которые не сериализуются в JSON.
    """
    return [task.model_dump(by_alias=True, mode='json') for task in tasks]


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


def execute_get_excel_template() -> dict[str, Any]:
    """Возвращает эталонный Excel-шаблон для заполнения проекта (5 колонок).

    Шаблон содержит:
    - 5 колонок: Задача, Описание, Исполнитель, Длительность (дни), Предшественники.
    - БЕЗ колонок ID, Дата начала, Дата окончания.
    - 5 демо-строк с наглядными примерами.
    - Предшественники указываются как номера строк (1, 2, 3, 4), НЕ task-N.

    Returns:
        Словарь с ключом "template" (base64-кодированный .xlsx) или "error" (str).
    """
    try:
        template_bytes = generate_template_excel()
        template_b64 = base64.b64encode(template_bytes).decode("utf-8")
        return {
            "template": template_b64,
            "filename": "gantt_template.xlsx",
            "mime_type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    except Exception as exc:
        return {"error": f"Не удалось сформировать шаблон Excel: {exc}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Диспетчер с валидацией и обработкой ошибок
# ═══════════════════════════════════════════════════════════════════════════════

def _normalize_arguments(
    arguments: dict[str, Any], schema_class: type[BaseModel]
) -> dict[str, Any]:
    """Нормализует и валидирует аргументы инструмента.

    Выполняет:
    1. Маппинг camelCase → snake_case для совместимости с LLM
    2. Приведение типов (строка "16" → int 16)
    3. Валидацию через Pydantic-схему

    Args:
        arguments: Сырые аргументы от LLM (могут быть camelCase).
        schema_class: Pydantic-модель параметров инструмента.

    Returns:
        Валидированный и нормализованный словарь аргументов в snake_case.

    Raises:
        ValueError: Если валидация Pydantic не прошла.
    """
    camel_to_snake = {
        "taskId": "task_id",
        "durationDays": "duration_days",
        "taskIds": "task_ids",
    }

    normalized = {}
    for key, value in arguments.items():
        snake_key = camel_to_snake.get(key, key)
        normalized[snake_key] = value

    try:
        validated = schema_class.model_validate(normalized)
        return validated.model_dump(exclude_none=True)
    except ValidationError as exc:
        error_messages = []
        for error in exc.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            error_messages.append(f"{field}: {msg}")
        raise ValueError(
            f"Ошибка валидации параметров: {'; '.join(error_messages)}"
        ) from exc


def execute_tool_call(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Вызывает инструмент мутации по имени и аргументам.

    Выполняет валидацию аргументов, маппинг camelCase → snake_case,
    приведение типов и обработку ошибок. При любой ошибке возвращает
    структурированный ответ {"error": "..."} вместо пробрасывания исключения.

    Args:
        name: Имя инструмента (update_task_details, add_new_task, delete_tasks, get_excel_template).
        arguments: Словарь аргументов, полученный от LLM (может быть camelCase).

    Returns:
        Словарь с ключом "tasks" (list[GanttTask] в camelCase) или "error" (str),
        либо "template" (base64-кодированный .xlsx) для get_excel_template.
    """
    try:
        if name == "update_task_details":
            validated_args = _normalize_arguments(arguments, UpdateTaskParams)
            return execute_update_task_details(**validated_args)

        if name == "add_new_task":
            validated_args = _normalize_arguments(arguments, AddTaskParams)
            return execute_add_new_task(**validated_args)

        if name == "delete_tasks":
            validated_args = _normalize_arguments(arguments, DeleteTasksParams)
            return execute_delete_tasks(**validated_args)

        if name == "get_excel_template":
            return execute_get_excel_template()

        return {"error": f"Неизвестный инструмент: '{name}'."}

    except ValueError as exc:
        logger.error(
            f"Ошибка валидации аргументов инструмента {name}: {exc}",
            exc_info=True,
        )
        return {"error": f"Ошибка валидации параметров: {exc}"}

    except Exception as exc:
        logger.error(
            f"Необработанная ошибка при выполнении инструмента {name}: {exc}",
            exc_info=True,
        )
        return {
            "error": f"Внутренняя ошибка при выполнении инструмента: {exc}"
        }