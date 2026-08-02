"""Post-Tool и Post-Reply проверки дат: конфликты и заземление (Grounding).

Post-Tool Check (detect_date_conflicts):
  Сравнивает запрошенные пользователем даты с фактическими датами задач.
  Если DAG-планировщик сдвинул задачу из-за зависимостей — формирует пояснение.

Post-Reply Grounding Check (grounding_check):
  Сверяет даты в текстовом ответе LLM с result_tasks.
  Если LLM упомянул несуществующие даты — это галлюцинация, добавляет поправку.
"""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from app.utils.parsers import (
    extract_dates_for_task,
    extract_mentioned_dates,
    format_date_ru,
    parse_iso,
)

logger = logging.getLogger(__name__)


def detect_date_conflicts(
    user_message: str,
    tasks_before: list[dict[str, Any]],
    result_tasks: list[dict[str, Any]],
) -> str | None:
    """Сравнивает запрошенные пользователем даты с фактическими датами задач.

    Пост-Tool Check: если пользователь упомянул конкретные даты, а DAG-планировщик
    сдвинул задачу из-за жёстких зависимостей, формирует сообщение с пояснением.

    Возвращает текст конфликта (готовый для инъекции в сообщения LLM) или None.
    """
    # Быстрая проверка: упомянуты ли вообще даты в запросе
    if not extract_mentioned_dates(user_message):
        return None

    after_by_id = {t["id"]: t for t in result_tasks}
    before_by_id = {t["id"]: t for t in tasks_before}

    # Извлекаем ID задач, явно упомянутых в сообщении пользователя
    mentioned_task_ids: set[str] = set(
        re.findall(r"task-\d+", user_message, re.IGNORECASE)
    )

    # Флагаем ТОЛЬКО: новые задачи + задачи, чей ID упомянут в запросе.
    # Сдвинутые как побочный эффект (task-3, task-4, task-5 после delete)
    # проверять не нужно — пользователь о них не просил конкретных дат.
    affected: list[dict[str, Any]] = []
    for tid, after_t in after_by_id.items():
        before_t = before_by_id.get(tid)
        is_new = before_t is None
        is_explicitly_mentioned = tid in mentioned_task_ids
        if not (is_new or is_explicitly_mentioned):
            continue
        if is_new or (
            before_t.get("startDate") != after_t.get("startDate")
            or before_t.get("endDate") != after_t.get("endDate")
        ):
            affected.append(after_t)

    if not affected:
        return None

    conflict_parts: list[str] = []
    for task in affected:
        task_start_str = task.get("startDate")
        if not task_start_str:
            continue
        actual_start = parse_iso(task_start_str)
        if actual_start is None:
            continue

        # Извлекаем даты, упомянутые в том предложении, где есть task_id.
        # Это изолирует даты конкретно для этой задачи (а не чужие даты
        # из других частей составного запроса).
        task_dates = extract_dates_for_task(user_message, task["id"])
        if not task_dates:
            task_dates = extract_mentioned_dates(user_message)

        if not task_dates:
            continue

        # Если фактический старт совпадает с одной из упомянутых дат — конфликта нет
        if actual_start in set(task_dates):
            continue

        preds = task.get("predecessors", [])
        pred_title = None
        pred_end = None

        if preds:
            for pred_id in preds:
                pred_task = after_by_id.get(pred_id)
                if pred_task and pred_task.get("endDate"):
                    pe = parse_iso(pred_task["endDate"])
                    if pe is not None and (pred_end is None or pe > pred_end):
                        pred_end = pe
                        pred_title = pred_task.get("title", "неизвестной задачи")

        # Ищем упомянутую дату, которая раньше фактического старта
        # (т.е. пользователь просил более ранний старт, но планировщик отодвинул)
        earlier_mentioned = [d for d in task_dates if d < actual_start]
        if not earlier_mentioned:
            continue

        # Берём самую позднюю упомянутую дату, которая всё ещё раньше фактического старта.
        # Это ближайшая к фактическому старту "запрошенная" дата.
        requested_start = max(earlier_mentioned)

        # Проверяем: является ли задержка следствелем зависимости от предшественника
        dependency_delayed = (
            bool(preds)
            and pred_end is not None
            and requested_start <= pred_end
        )

        if dependency_delayed:
            pred_end_str = format_date_ru(pred_end)
            conflict_parts.append(
                f'⚠️ Внимание: Задача "{task.get("title", "")}" создана, но из-за '
                f'зависимости от "{pred_title}" (которое заканчивается {pred_end_str}) '
                f'её старт автоматически перенесён с '
                f'{format_date_ru(requested_start)} на {format_date_ru(actual_start)}.'
            )
        else:
            conflict_parts.append(
                f'⚠️ Внимание: Задача "{task.get("title", "")}" — запрошенный старт '
                f'{format_date_ru(requested_start)} не достигнут, '
                f'фактический старт {format_date_ru(actual_start)}.'
            )

    if conflict_parts:
        return (
            "POST-TOOL CHECK — обнаружены конфликты дат, которые модель "
            "ОБЯЗАНА сообщить пользователю в ответе:\n"
            + "\n".join(conflict_parts)
        )
    return None


def grounding_check(
    reply: str,
    user_message: str,
    tasks: list[dict[str, Any]],
) -> str:
    """Post-Reply Grounding Check: сверяет даты в текстовом ответе с result_tasks.

    Если в ответе LLM упомянуты даты, которых нет ни в таблице задач, ни в
    исходном запросе пользователя — это галлюцинация. Добавляет поправку
    в конец ответа с перечнём фактических дат.

    Args:
        reply: Текстовый ответ LLM.
        user_message: Исходное сообщение пользователя.
        tasks: Актуальный список задач (result_tasks от бэкенда).

    Returns:
        Ответ с при необходимости добавленной поправкой о заземлении.
    """
    if not reply:
        return reply

    reply_dates = set(extract_mentioned_dates(reply))
    if not reply_dates:
        return reply

    user_dates = set(extract_mentioned_dates(user_message))

    actual_dates: set[date] = set()
    for t in tasks:
        for key in ("startDate", "endDate"):
            parsed = parse_iso(t.get(key) or "")
            if parsed is not None:
                actual_dates.add(parsed)

    # Даты в ответе, которых нет в задачах и в сообщении пользователя
    hallucinated = reply_dates - actual_dates - user_dates
    if not hallucinated:
        return reply

    harm_str = ", ".join(format_date_ru(d) for d in sorted(hallucinated))
    actual_str = ", ".join(format_date_ru(d) for d in sorted(actual_dates))
    correction = (
        f"\n\n⚠️ [Пост-чек заземления] В ответе упомянуты даты, "
        f"отсутствующие в таблице задач: {harm_str}. "
        f"Фактические даты задач: {actual_str}."
    )
    logger.warning(
        f"Post-Reply Grounding Check: выявлены галлюцинированные даты: {harm_str}"
    )
    return reply + correction
