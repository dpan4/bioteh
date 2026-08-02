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

from __future__ impoimport logging
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
    6. Весь процесс записывается в logs/chat_YYYY-MM-DD.log.

    Args:
        request: Объект ChatRequest с полем message.

    Returns:
        Словарь с ключами reply (str) и tasks (list[dict]).
    """
    log_entry: dict[str, Any] = {
        "timestamp": datetime.now().isoformat(),
        "user_message": request.message,
        "tasks_before": [],
        "system_prompt_tasks": [],
        "tool_calls": [],
        "reply": "",
        "tasks_after": [],
        "error": None,
    }

    try:
        try:
            client = get_client()
        except ValueError as exc:
            logger.error(f"LLM-сервис недоступен: {exc}", exc_info=True)
            log_entry["error"] = f"LLM-сервис недоступен: {exc}"
            write_log(log_entry)
            raise HTTPException(
                status_code=503,
                detail=f"LLM-сервис недоступен: {exc}",
            ) from exc

        try:
            current_tasks = get_current_tasks()
        except Exception as exc:
            logger.error(
                f"Не удалось получить текущий список задач: {exc}",
                exc_info=True,
            )
            log_entry["error"] = f"Не удалось получить задачи: {exc}"
            write_log(log_entry)
            raise HTTPException(
                status_code=500,
                detail=f"Не удалось получить текущий список задач: {exc}",
            ) from exc

        log_entry["tasks_before"] = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "assignee": t.get("assignee", ""),
                "durationDays": t.get("durationDays"),
                "predecessors": t.get("predecessors", []),
                "startDate": t.get("startDate"),
                "endDate": t.get("endDate"),
            }
            for t in current_tasks
        ]
        log_entry["system_prompt_tasks"] = log_entry["tasks_before"]

        try:
            analysis = analyze_request(request.message, current_tasks)
            system_msg = client.build_system_message(current_tasks=current_tasks)

            if analysis:
                system_msg["content"] = analysis + system_msg["content"]

            messages: list[dict[str, Any]] = [system_msg]
            messages.append({"role": "user", "content": request.message})
        except Exception as exc:
            logger.error(
                f"Ошибка при формировании системного промпта: {exc}",
                exc_info=True,
            )
            log_entry["error"] = f"Ошибка системного промпта: {exc}"
            write_log(log_entry)
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при формировании системного промпта: {exc}",
            ) from exc

        parsed_calls = parse_tool_calls(request.message, current_tasks)

        try:
            reply, tasks = await run_tool_calling_loop(
                messages, log_entry, current_tasks, parsed_calls,
                get_current_tasks=get_current_tasks,
                format_tool_result=format_tool_result,
            )
        except Exception as exc:
            logger.error(
                f"Ошибка при обращении к LLM или выполнении Tool Calling Loop: {exc}",
                exc_info=True,
            )
            log_entry["error"] = f"Ошибка Tool Calling Loop: {exc}"
            write_log(log_entry)
            raise HTTPException(
                status_code=502,
                detail=f"Ошибка при обращении к LLM: {exc}",
            ) from exc

        reply = grounding_check(reply, request.message, tasks)

        log_entry["reply"] = reply
        log_entry["tasks_after"] = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "assignee": t.get("assignee", ""),
                "durationDays": t.get("durationDays"),
                "predecessors": t.get("predecessors", []),
                "startDate": t.get("startDate"),
                "endDate": t.get("endDate"),
            }
            for t in tasks
        ]
        write_log(log_entry)

"reply"] = reply
        log_entry["tasks_after"] = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "assignee": t.get("assignee", ""),
                "durationDays": t.get("durationDays"),
                "predecessors": t.get("predecessors", []),
                "startDate": t.get("startDate"),
                "endDate": t.get("endDate"),
            }
            for t in tasks
        ]
        write_log(log_entry)

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
        raise

    except Exception as exc:
        logger.error(
            f"CRITICAL CHAT ERROR — необработанное исключение: {exc}",
            exc_info=True,
        )
        log_entry["error"] = f"CRITICAL: {exc}"
        write_log(log_entry)
        raise HTTPException(
            status_code=500,
            detail=f"Критическая ошибка при обработке чата: {str(exc)}",
        ) from exc