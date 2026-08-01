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
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.mcp_server import TOOL_DEFINITIONS, execute_tool_call
from app.services.llm_client import get_client
from app.services.task_store import store

logger = logging.getLogger(__name__)
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
    logger.debug(f"Начало Tool Calling Loop с {len(messages)} сообщениями")

    for round_num in range(_MAX_TOOL_CALL_ROUNDS):
        logger.debug(f"Tool Calling Loop: раунд {round_num + 1}/{_MAX_TOOL_CALL_ROUNDS}")
        
        try:
            response = await client.chat(messages, TOOL_DEFINITIONS)
        except Exception as exc:
            logger.error(
                f"Ошибка при вызове LLM на раунде {round_num + 1}: {exc}",
                exc_info=True,
            )
            raise
        
        reply = response["reply"]
        tool_calls = response["tool_calls"]
        logger.debug(f"LLM ответ получен: {len(tool_calls)} вызовов инструментов")

        if not tool_calls:
            logger.debug("Tool Calling Loop завершён: инструментов не вызвано")
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
            logger.debug(f"Выполнение инструмента: {tc['name']} с аргументами: {tc['arguments']}")
            try:
                result = execute_tool_call(tc["name"], tc["arguments"])
                logger.debug(f"Инструмент {tc['name']} выполнен успешно")
            except Exception as exc:
                logger.error(
                    f"Ошибка при выполнении инструмента {tc['name']}: {exc}",
                    exc_info=True,
                )
                result = {
                    "error": f"Внутренняя ошибка при выполнении инструмента: {exc}"
                }

            messages.append({
                "role": "tool",
                "tool_call_id": tc["id"],
                "content": _format_tool_result(tc["name"], result),
            })

    logger.warning(f"Tool Calling Loop: достигнут лимит {_MAX_TOOL_CALL_ROUNDS} итераций")
    tasks = _get_current_tasks()
    return (
        "Достигнут лимит итераций обработки. Пожалуйста, уточните запрос.",
        tasks,
    )


def _get_current_tasks() -> list[dict[str, object]]:
    """Безопасно получает текущий список задач из хранилища.
    
    ВАЖНО: Использует mode='json' для корректной сериализации date-объектов в ISO-строки.
    Без mode='json' Pydantic возвращает Python date-объекты, которые не сериализуются в JSON.
    """
    try:
        gantt = store.get_gantt_tasks()
        serialized = [task.model_dump(by_alias=True, mode='json') for task in gantt]
        logger.debug(f"Получено {len(serialized)} задач из TaskStore (GanttTask)")
        return serialized
    except Exception as exc:
        logger.warning(
            f"Не удалось получить GanttTask, используем RawTask: {exc}",
            exc_info=True,
        )
        raw = store.get_raw_tasks()
        serialized = [task.model_dump(by_alias=True, mode='json') for task in raw]
        logger.debug(f"Получено {len(serialized)} задач из TaskStore (RawTask)")
        return serialized


@router.post("/chat")
async def chat(request: ChatRequest) -> dict[str, Any]:
    """Обрабатывает сообщение пользователя через LLM с Tool Calling.

    Поток:
    1. Получает текущий список задач из TaskStore и передаёт их в системный промпт.
    2. Формируется история: system-промпт (с текущими задачами) + сообщение пользователя.
    3. Отправляется в LLM с дефинициями MCP-инструментов.
    4. Если LLM вызывает инструменты — они выполняются над TaskStore,
       результат возвращается LLM, цикл повторяется.
    5. Финальный ответ: текст от LLM + актуальный список задач.
    6. При ошибках (цикл, невалидные ссылки) LLM получает текст ошибки
       и формирует понятное сообщение пользователю.

    Args:
        request: Объект ChatRequest с полем message.

    Returns:
        Словарь с ключами reply (str) и tasks (list[dict]).
    """
    try:
        # === ИНИЦИАЛИЗАЦИЯ LLM-КЛИЕНТА ===
        try:
            client = get_client()
        except ValueError as exc:
            logger.error(f"LLM-сервис недоступен: {exc}", exc_info=True)
            raise HTTPException(
                status_code=503,
                detail=f"LLM-сервис недоступен: {exc}",
            ) from exc

        # === ПОЛУЧЕНИЕ ТЕКУЩИХ ЗАДАЧ ДЛЯ СИСТЕМНОГО ПРОМПТА ===
        try:
            current_tasks = _get_current_tasks()
        except Exception as exc:
            logger.error(
                f"Не удалось получить текущий список задач: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Не удалось получить текущий список задач: {exc}",
            ) from exc

        # === ФОРМИРОВАНИЕ ИСТОРИИ СООБЩЕНИЙ ===
        try:
            messages: list[dict[str, Any]] = [
                client.build_system_message(current_tasks=current_tasks)
            ]
            messages.append({"role": "user", "content": request.message})
        except Exception as exc:
            logger.error(
                f"Ошибка при формировании системного промпта: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при формировании системного промпта: {exc}",
            ) from exc

        # === ВЫПОЛНЕНИЕ TOOL CALLING LOOP ===
        try:
            reply, tasks = await _run_tool_calling_loop(messages)
        except Exception as exc:
            logger.error(
                f"Ошибка при обращении к LLM или выполнении Tool Calling Loop: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=502,
                detail=f"Ошибка при обращении к LLM: {exc}",
            ) from exc

        # === ФОРМИРОВАНИЕ И ВОЗВРАТ ОТВЕТА ===
        try:
            response = {"reply": reply, "tasks": tasks}
            return response
        except Exception as exc:
            logger.error(
                f"Ошибка при сериализации ответа: {exc}",
                exc_info=True,
            )
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при формировании ответа: {exc}",
            ) from exc

    except HTTPException:
        # Пробрасываем HTTPException как есть (уже залогировано выше)
        raise

    except Exception as exc:
        # Критическая необработанная ошибка
        logger.error(
            f"CRITICAL CHAT ERROR — необработанное исключение: {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Критическая ошибка при обработке чата: {str(exc)}",
        ) from exc