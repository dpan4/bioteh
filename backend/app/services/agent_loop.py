"""Ядро LLM-агента: цикл Tool Calling (отправка → инструменты → ответ).

Выполняет многораундовый цикл взаимодействия с LLM:
  1. Отправка сообщений в LLM с дефинициями MCP-инструментов.
  2. Если LLM вызывает инструменты — выполняет их над TaskStore.
  3. Результат возвращается LLM для формирования текстового ответа.
  4. Повторяется, пока LLM не перестанет вызывать инструменты.

Включает защиту от зацикливания (проверка уникальности сигнатур вызовов)
и валидационный слой для перехвата XML/JSON из текста ответа.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

from app.mcp_server import TOOL_DEFINITIONS, execute_tool_call
from app.services.grounding import detect_date_conflicts
from app.services.llm_client import get_client
from app.services.task_store import store
from app.utils.parsers import (
    clean_and_sort_tools,
    ensure_russian_language,
    extract_tools_from_xml_or_text,
)

logger = logging.getLogger(__name__)

MAX_TOOL_CALL_ROUNDS = 5


def format_tool_result(tool_name: str, result: dict[str, Any]) -> str:
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


def get_current_tasks() -> list[dict[str, object]]:
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


async def run_tool_calling_loop(
    messages: list[dict[str, Any]],
    log_entry: dict[str, Any],
    tasks_before: list[dict[str, object]],
    parsed_calls: list[dict[str, Any]] | None = None,
    get_current_tasks: Callable[[], list[dict[str, object]]] | None = None,
    format_tool_result: Callable[[str, dict[str, Any]], str] | None = None,
) -> tuple[str, list[dict[str, object]]]:
    """Выполняет цикл Tool Calling: отправка в LLM → инструменты → ответ.

    Args:
        messages: История сообщений (начинается с system + user).
        log_entry: Словарь лога текущего запроса — tool calls пишутся сюда.
        tasks_before: Список задач ДО выполнения tool calls (для Post-Tool Check).
        parsed_calls: Предварительно разобранные tool_calls из _parse_tool_calls.
            Если LLM не справляется (неверные или отсутствующие вызовы),
            используются parsed_calls вместо LLM-вызовов.
        get_current_tasks: Callable для получения текущих задач из TaskStore.
        format_tool_result: Callable для форматирования результата tool call.

    Returns:
        Кортеж (текстовый ответ AI, актуальный список задач).
    """
    if get_current_tasks is None or format_tool_result is None:
        raise ValueError(
            "get_current_tasks и format_tool_result обязательны "
            "для работы run_tool_calling_loop"
        )

    client = get_client()
    log_entry["tool_calls"] = []

    seen_signatures: set[tuple[tuple[str, str], ...]] = set()
    last_tool_result_tasks: list[dict[str, object]] | None = None  # Результат последнего tool call

    for round_num in range(MAX_TOOL_CALL_ROUNDS):
        response = await client.chat(messages, TOOL_DEFINITIONS)
        reply = response["reply"] or ""
        tool_calls = response["tool_calls"] or []

        # 1. Если LLM выдала XML/JSON текстом в reply вместо tool_calls
        if not tool_calls and ("<tool_call>" in reply or "```json" in reply):
            logger.info("Validation Layer: перехват XML/JSON из текста reply")
            tool_calls = extract_tools_from_xml_or_text(reply)
            reply = ""  # очищаем reply, так как там лежал код вызова

        # 2. Если LLM ничего не вызвала, но у нас есть fallback из _parse_tool_calls
        if not tool_calls and parsed_calls and round_num == 0:
            logger.info("Validation Layer: применен Regex Fallback из _parse_tool_calls")
            tool_calls = parsed_calls

        # 3. Нормализация, очистка и строгое упорядочивание (Delete -> Add -> Update)
        tool_calls = clean_and_sort_tools(tool_calls)

        if not tool_calls:
            # Если инструменты не вызывались — используем последний известный результат
            # Пустой массив [] — валидное состояние (например, после clear_all_tasks)
            tasks = last_tool_result_tasks if last_tool_result_tasks is not None else get_current_tasks()
            reply = ensure_russian_language(reply)
            return reply, tasks

        # --- 🛑 ЗАЩИТА ОТ ЗАЦИКЛИВАНИЯ И ДУБЛИРОВАНИЯ LLM ---
        # Создаем уникальный слепок всех вызовов текущего раунда
        current_signature = tuple(
            (tc["name"], json.dumps(tc["arguments"], sort_keys=True, ensure_ascii=False))
            for tc in tool_calls
        )

        if current_signature in seen_signatures:
            logger.warning(
                f"Round {round_num + 1}: Зафиксирован повторный вызов тех же инструментов! "
                "Прерываем цикл для предотвращения дублирования данных."
            )
            # 🔥 КРИТИЧНО: Используем результат последнего tool call, а не перечитываем store
            # Пустой массив [] — валидное состояние после clear_all_tasks
            tasks = last_tool_result_tasks if last_tool_result_tasks is not None else get_current_tasks()
            # Если у модели был текст — отдаем его, иначе стандартную заглушку
            final_reply = reply or "Изменения успешно внесены в расписание."
            return ensure_russian_language(final_reply), tasks

        seen_signatures.add(current_signature)
        # ----------------------------------------------------

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
                
                # 🔥 КРИТИЧНО: Сохраняем результат последнего успешного tool call
                # Пустой массив [] — это ВАЛИДНЫЙ результат (например, clear_all_tasks)
                if "tasks" in result:
                    last_tool_result_tasks = result["tasks"]
                    
            except Exception as exc:
                logger.error(
                    f"Ошибка при выполнении инструмента {tc['name']}: {exc}",
                    exc_info=True,
                )
                result = {
                    "error": f"Внутренняя ошибка при выполнении инструмента: {exc}"
                }

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
                    "content": format_tool_result(tc["name"], result),
                }
            )

        # === POST-TOOL CHECK: сравнение дат с запросом пользователя ===
        user_message = next(
            (m.get("content", "") for m in messages if m.get("role") == "user"),
            "",
        )
        tasks_after = get_current_tasks()
        conflict_note = detect_date_conflicts(
            user_message, list(tasks_before), tasks_after
        )
        if conflict_note:
            logger.info(
                "Post-Tool Check: обнаружен конфликт дат "
                "— инъекция уведомления в контекст LLM"
            )
            messages.append(
                {"role": "system", "content": conflict_note}
            )

    logger.warning(
        f"Tool Calling Loop: достигнут лимит {MAX_TOOL_CALL_ROUNDS} итераций"
    )
    # 🔥 КРИТИЧНО: Используем результат последнего tool call вместо перечитывания store
    # Пустой массив [] — валидное состояние после clear_all_tasks
    tasks = last_tool_result_tasks if last_tool_result_tasks is not None else get_current_tasks()
    return (
        "Достигнут лимит итераций обработки. Пожалуйста, уточните запрос.",
        tasks,
    )
