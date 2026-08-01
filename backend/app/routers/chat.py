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

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.mcp_server import TOOL_DEFINITIONS, execute_tool_call
from app.services.llm_client import get_client
from app.services.task_store import store

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["chat"])

_MAX_TOOL_CALL_ROUNDS = 5

# Папка для логов — рядом с корнем бэкенда (на уровень выше app/)
_LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def _get_log_path() -> Path:
    """Возвращает путь к файлу лога для текущей даты."""
    _LOGS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return _LOGS_DIR / f"chat_{date_str}.log"


def _write_log(entry: dict[str, Any]) -> None:
    """Записывает одну запись лога в файл как JSON-строку (NDJSON).

    Каждый вызов /api/chat пишет одну JSON-строку в файл лога.
    Ошибки записи логируются в stderr, но не останавливают запрос.

    Args:
        entry: Словарь с данными запроса для записи в лог.
    """
    try:
        log_path = _get_log_path()
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        logger.warning(f"Не удалось записать лог: {exc}")


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


def _format_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    """Форматирует результат вызова инструмента для отправки обратно LLM.

    Args:
        tool_name: Имя вызванного инструмента.
        result: Результат от mcp_server.execute_tool_call().

    Returns:
        JSON-строка с результатом или ошибкой на русском языке.
    """
    if "error" in result:
        return json.dumps({"error": result["error"]}, ensure_ascii=False)
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


def _get_current_tasks() -> list[dict[str, object]]:
    """Безопасно получает текущий список задач из хранилища.

    Использует mode='json' для корректной сериализации date-объектов в ISO-строки.
    """
    try:
        gantt = store.get_gantt_tasks()
        serialized = [task.model_dump(by_alias=True, mode="json") for task in gantt]
        logger.debug(f"Получено {len(serialized)} задач из TaskStore (GanttTask)")
        return serialized
    except Exception as exc:
        logger.warning(
            f"Не удалось получить GanttTask, используем RawTask: {exc}",
            exc_info=True,
        )
        raw = store.get_raw_tasks()
        serialized = [task.model_dump(by_alias=True, mode="json") for task in raw]
        logger.debug(f"Получено {len(serialized)} задач из TaskStore (RawTask)")
        return serialized


async def _run_tool_calling_loop(
    messages: list[dict[str, Any]],
    log_entry: dict[str, Any],
) -> tuple[str, list[dict[str, object]]]:
    """Выполняет цикл Tool Calling: отправка в LLM → инструменты → ответ.

    Args:
        messages: История сообщений (начинается с system + user).
        log_entry: Словарь лога текущего запроса — tool calls пишутся сюда.

    Returns:
        Кортеж (текстовый ответ AI, актуальный список задач).
    """
    client = get_client()
    log_entry["tool_calls"] = []
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

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": reply or None,
        }
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
            logger.debug(
                f"Выполнение инструмента: {tc['name']} с аргументами: {tc['arguments']}"
            )
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

            # Записываем в лог: аргументы, результат и итоговые задачи с датами
            tc_log: dict[str, Any] = {
                "round": round_num + 1,
                "tool": tc["name"],
                "arguments": tc["arguments"],
            }
            if "error" in result:
                tc_log["error"] = result["error"]
            else:
                tc_log["result_tasks"] = [
                    {
                        "id": t["id"],
                        "title": t["title"],
                        "assignee": t.get("assignee", ""),
                        "durationDays": t.get("durationDays"),
                        "predecessors": t.get("predecessors", []),
                        "startDate": t["startDate"],
                        "endDate": t["endDate"],
                    }
                    for t in result.get("tasks", [])
                ]
            log_entry["tool_calls"].append(tc_log)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": _format_tool_result(tc["name"], result),
                }
            )

    logger.warning(
        f"Tool Calling Loop: достигнут лимит {_MAX_TOOL_CALL_ROUNDS} итераций"
    )
    tasks = _get_current_tasks()
    return (
        "Достигнут лимит итераций обработки. Пожалуйста, уточните запрос.",
        tasks,
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
    # Инициализируем запись лога для этого запроса
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
        # === ИНИЦИАЛИЗАЦИЯ LLM-КЛИЕНТА ===
        try:
            client = get_client()
        except ValueError as exc:
            logger.error(f"LLM-сервис недоступен: {exc}", exc_info=True)
            log_entry["error"] = f"LLM-сервис недоступен: {exc}"
            _write_log(log_entry)
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
            log_entry["error"] = f"Не удалось получить задачи: {exc}"
            _write_log(log_entry)
            raise HTTPException(
                status_code=500,
                detail=f"Не удалось получить текущий список задач: {exc}",
            ) from exc

        # Записываем состояние задач ДО изменений
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
        # Записываем компактное представление задач, которое видит LLM
        log_entry["system_prompt_tasks"] = log_entry["tasks_before"]

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
            log_entry["error"] = f"Ошибка системного промпта: {exc}"
            _write_log(log_entry)
            raise HTTPException(
                status_code=500,
                detail=f"Ошибка при формировании системного промпта: {exc}",
            ) from exc

        # === ВЫПОЛНЕНИЕ TOOL CALLING LOOP ===
        try:
            reply, tasks = await _run_tool_calling_loop(messages, log_entry)
        except Exception as exc:
            logger.error(
                f"Ошибка при обращении к LLM или выполнении Tool Calling Loop: {exc}",
                exc_info=True,
            )
            log_entry["error"] = f"Ошибка Tool Calling Loop: {exc}"
            _write_log(log_entry)
            raise HTTPException(
                status_code=502,
                detail=f"Ошибка при обращении к LLM: {exc}",
            ) from exc

        # === ФИНАЛЬНЫЙ ЛОГ — СОСТОЯНИЕ ПОСЛЕ ИЗМЕНЕНИЙ ===
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
        _write_log(log_entry)

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
        _write_log(log_entry)
        raise HTTPException(
            status_code=500,
            detail=f"Критическая ошибка при обработке чата: {str(exc)}",
        ) from exc
