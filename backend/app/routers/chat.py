"""API-роутер чата с LLM (Tool Calling через OpenRouter).

Эндпоинт:
  POST /api/chat — отправка сообщения пользователя в LLM,
    выполнение MCP-инструментов, возврат ответа и обновлённого расписания.

Поток данных (§3.2 architecture.md):
  User Message -> POST /api/chat -> llm_client -> OpenRouter LLM
    -> Tool Call -> mcp_server -> TaskStore + Scheduler
    -> GanttTask[] -> ответ пользователю.

Логирование: каждый запрос пишется в logs/chat_YYYY-MM-DD.log рядом с main.py.
Лог содержит: входящий запрос, состояние задач (системный промпт), каждый
tool call с аргументами и результатом (задачи с датами), финальный ответ.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.services.agent_loop import (
    format_tool_result,
    get_current_tasks,
    run_tool_calling_loop,
)
from app.services.grounding import grounding_check
from app.services.llm_client import get_client
from app.services.request_parser import analyze_request, parse_tool_calls
from app.services.task_store import store
from app.utils.logger import write_log

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])


class ChatRequest(BaseModel):
    """Входящий запрос чата."""

    message: str = Field(
        min_length=1,
        description='Сообщение пользователя. Пример: "Увеличь длительность задачи task-3 до 10 дней"',
        examples=["Увеличь длительность задачи task-3 до 10 дней"],
    )


class ChatResponse(BaseModel):
    """Ответ чата."""

    reply: str = Field(
        description="Текстовый ответ AI-ассистента.",
    )
    tasks: list[dict[str, object]] = Field(
        description="Актуальный список задач в camelCase.",
    )


def _task_to_log_dict(task: dict[str, object]) -> dict[str, object]:
    """Сериализует задачу в компактный словарь для лога.

    Args:
        task: Задача в формате GanttTask (camelCase dict).

    Returns:
        Словарь с ключевыми полями задачи для записи в лог.
    """
    return {
        "id": task.get("id"),
        "title": task.get("title"),
        "assignee": task.get("assignee", ""),
        "durationDays": task.get("durationDays"),
        "predecessors": task.get("predecessors", []),
        "startDate": task.get("startDate"),
        "endDate": task.get("endDate"),
    }


def _init_log_entry(message: str) -> dict[str, Any]:
    """Создаёт пустой словарь лога для текущего запроса.

    Args:
        message: Текст сообщения пользователя.

    Returns:
        Словарь лога с заполненными метаданными и пустыми списками задач.
    """
    return {
        "timestamp": datetime.now().isoformat(),
        "user_message": message,
        "tasks_before": [],
        "system_prompt_tasks": [],
        "tool_calls": [],
        "reply": "",
        "tasks_after": [],
        "error": None,
    }


def _raise_http(detail: str, status: int, log_entry: dict[str, Any], exc: Exception) -> None:
    """Логирует ошибку, записывает в лог и выбрасывает HTTPException.

    Args:
        detail: Человекочитаемое описание ошибки.
        status: HTTP-код ошибки.
        log_entry: Словарь лога текущего запроса.
        exc: Исключение, которое было поймано.
    """
    logger.error(detail, exc_info=True)
    log_entry["error"] = detail
    write_log(log_entry)
    raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """Обрабатывает сообщение пользователя через LLM с Tool Calling.

    Поток:
    1. Получает текущий список задач из TaskStore и передаёт их в системный промпт.
    2. Формируется история: system-промпт (с текущими задачами) + сообщение пользователя.
    3. Отправляется в LLM с дефинициями MCP-инструментов.
    4. Если LLM вызывает инструменты — они выполняются над TaskStore,
       результат возвращается LLM, цикл повторяется.
    5. Финальный ответ: текст от LLM + актуальный список задач.
    6. Весь процесс записывается в logs/chat_YYYY-MM-DD.log.

    Args:
        request: Объект ChatRequest с полем message.

    Returns:
        Словарь с ключами reply (str) и tasks (list[dict]).
    """
    log_entry = _init_log_entry(request.message)

    # --- 1. Инициализация LLM-клиента ---
    try:
        client = get_client()
    except ValueError as exc:
        _raise_http(
            f"LLM-сервис недоступен: {exc}", 503, log_entry, exc
        )

    # --- 2. Получение текущих задач ---
    try:
        current_tasks = get_current_tasks()
    except Exception as exc:
        _raise_http(
            f"Не удалось получить текущий список задач: {exc}", 500, log_entry, exc
        )

    log_entry["tasks_before"] = [_task_to_log_dict(t) for t in current_tasks]
    log_entry["system_prompt_tasks"] = log_entry["tasks_before"]

    # --- 3. Формирование системного промпта и истории сообщений ---
    try:
        analysis = analyze_request(request.message, current_tasks)
        system_msg = client.build_system_message(current_tasks=current_tasks)

        if analysis:
            system_msg["content"] = analysis + system_msg["content"]

        messages: list[dict[str, Any]] = [system_msg]
        messages.append({"role": "user", "content": request.message})
    except Exception as exc:
        _raise_http(
            f"Ошибка при формировании системного промпта: {exc}",
            500, log_entry, exc,
        )

    # --- 4. Tool Calling Loop: LLM -> инструменты -> ответ ---
    parsed_calls = parse_tool_calls(request.message, current_tasks)

    # Транзакционность: сохраняем состояние ДО цикла для возможности отката
    tasks_snapshot = store.get_raw_tasks()

    try:
        reply, tasks = await run_tool_calling_loop(
            messages, log_entry, current_tasks, parsed_calls,
            get_current_tasks=get_current_tasks,
            format_tool_result=format_tool_result,
        )
        # Цикл завершился успешно — фиксируем изменения инструментов на диске
        store.save_to_file()
    except Exception as exc:
        # Откат: восстанавливаем состояние до вызова инструментов
        store.set_raw_tasks(tasks_snapshot)
        store.save_to_file()
        _raise_http(
            f"Ошибка при обращении к LLM или выполнении Tool Calling Loop: {exc}",
            502, log_entry, exc,
        )

    # --- 5. Post-Tool grounding ---
    reply = grounding_check(reply, request.message, tasks)

    # tasks_after читаем напрямую из store — гарантированно актуальное состояние
    tasks_after = get_current_tasks()

    log_entry["reply"] = reply
    log_entry["tasks_after"] = [_task_to_log_dict(t) for t in tasks_after]
    write_log(log_entry)

    # --- 6. Формирование и возврат ответа ---
    try:
        return ChatResponse(reply=reply, tasks=tasks_after)
    except Exception as exc:
        _raise_http(
            f"Ошибка при формировании ответа: {exc}", 500, log_entry, exc
        )
