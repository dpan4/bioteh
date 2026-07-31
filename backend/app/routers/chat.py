"""API-роутер чата с LLM (Tool Calling через OpenRouter).

Эндпоинт:
  POST /api/chat — отправка сообщения пользователя в LLM,
    выполнение MCP-инструментов, возврат ответа и обновлённого расписания.

Поток данных (§3.2 architecture.md):
  User Message -> POST /api/chat -> llm_client -> OpenRouter LLM
    -> Tool Call -> mcp_server -> TaskStore + Scheduler
    -> GanttTask[] -> ответ пользователю.

Ошибки CyclicDependencyError/ValueError из mcp-инструментов возвращаются
в текстовом ответе LLM, приложение не падает.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.mcp_server import TOOL_DEFINITIONS, execute_tool_call
from app.services.llm_client import get_client
from app.services.task_store import store

router = APIRouter(prefix="/api", tags=["chat"])

_MAX_TOOL_CALL_ROUNDS = 5


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
        description="Актуальный список задач в camelCase (id, title, description, assignee, durationDays, predecessors, startDate, endDate).",
    )


def _format_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    """Форматирует результат вызова инструмента для отправки обратно LLM.

    Args:
        tool_name: Имя вызванного инструмента.
        result: Результат от mcp_server.execute_tool_call().

    Returns:
        JSON-строка с результатом или ошибкой на русском языке.
    """
    if "error" in result:
        return json.dumps(
            {"error": result["error"]}, ensure_ascii=False
        )
    # Для сокращения контекста отправляем только ключевые поля задач.
    tasks_summary = [
        {
            "id": t["id"],
            "title": t["title"],
            "startDate": t["startDate"],
            "endDate": t["endDate"],
            "predecessors": t["predecessors"],
        }
        for t in result["tasks"]
    ]
    return json.dumps({"updated_tasks": tasks_summary}, ensure_ascii=False)


async def _run_tool_calling_loop(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, object]]]:
    """Выполняет цикл Tool Calling: отправка в LLM → инструменты → ответ.

    Args:
        messages: История сообщений (начинается с system + user).

    Returns:
        Кортеж (текстовый ответ AI, актуальный список задач).
    """
    client = get_client()

    for _round in range(_MAX_TOOL_CALL_ROUNDS):
        response = await client.chat(messages, TOOL_DEFINITIONS)
        reply = response["reply"]
        tool_calls = response["tool_calls"]

        if not tool_calls:
            tasks = _get_current_tasks()
            return reply, tasks

        assistant_message: dict[str, Any] = {"role": "assistant", "content": reply or None}
        if tool_calls:
            assistant_message["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {
                        "name": tc["name"],
                        "arguments": json.dumps(tc["arguments"], ensure_ascii=False),
                    },
                }
                for tc in tool_calls
            ]
        messages.append(assistant_message)

        for tc in tool_calls:
            result = execute_tool_call(tc["name"], tc["arguments"])
            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": _format_tool_result(tc["name"], result),
            })

    tasks = _get_current_tasks()
    return (
        "Достигнут лимит итераций обработки. Пожалуйста, уточните запрос.",
        tasks,
    )


def _get_current_tasks() -> list[dict[str, object]]:
    """Безопасно получает текущий список задач из хранилища."""
    try:
        gantt = store.get_gantt_tasks()
        return [task.model_dump(by_alias=True) for task in gantt]
    except Exception:
        raw = store.get_raw_tasks()
        return [task.model_dump(by_alias=True) for task in raw]


@router.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    """Обрабатывает сообщение пользователя через LLM с Tool Calling.

    Поток:
    1. Формируется история: system-промпт + сообщение пользователя.
    2. Отправляется в OpenRouter с дефинициями MCP-инструментов.
    3. Если LLM вызывает инструменты — они выполняются над TaskStore,
       результат возвращается LLM, цикл повторяется.
    4. Финальный ответ: текст от LLM + актуальный список задач.
    5. При ошибках (цикл, невалидные ссылки) LLM получает текст ошибки
       и формирует понятное сообщение пользователю.

    Args:
        request: Объект ChatRequest с полем message.

    Returns:
        Словарь с ключами reply (str) и tasks (list[dict]).
    """
    try:
        client = get_client()
    except ValueError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"LLM-сервис недоступен: {exc}",
        ) from exc

    messages: list[dict[str, Any]] = [client.build_system_message()]
    messages.append({"role": "user", "content": request.message})

    try:
        reply, tasks = await _run_tool_calling_loop(messages)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Ошибка при обращении к LLM: {exc}",
        ) from exc

    return {"reply": reply, "tasks": tasks}