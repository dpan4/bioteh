"""Парсинг запросов пользователя: извлечение tool calls из естественного языка.

Функции-парсеры анализируют текстовые запросы и формируют структурированные
вызовы MCP-инструментов (delete_tasks, update_task_details, add_new_task).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.utils.parsers import MONTHS_REGEX, RUSSIAN_MONTHS


def resolve_task_id(
    name_first: str, name_last: str, assignee_to_id: dict[str, str]
) -> str:
    """Разрешает task_id по имени исполнителя (из дательного падежа).

    Args:
        name_first: Имя (может быть дательный падеж, напр. «Дмитрию»).
        name_last: Фамилия (уже нормализована в именительный падеж).
        assignee_to_id: Справочник lowercased assignee → task_id.

    Returns:
        task_id или '<ID>' если не найден.
    """
    first = name_first.lower()
    last = name_last.lower()

    # 1. Прямое совпадение (полное имя или только имя)
    full = f"{first} {last}"
    for key, tid in assignee_to_id.items():
        if key == full or key == first:
            return tid

    # 2. Нечёткое совпадение имени: сравниваем все символы,
    #    кроме последнего (обрабатывает падежные окончания:
    #    «дмитрию» ≈ «дмитрий», «семёну» ≈ «семён», «анне» ≈ «анна»)
    for key, tid in assignee_to_id.items():
        key_first = key.split()[0] if " " in key else key
        if len(first) > 3 and len(key_first) > 3:
            if first[:-1] == key_first[:-1]:
                return tid

    return "<ID>"


def parse_tool_calls(
    message: str,
    current_tasks: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Разбирает запрос пользователя и формирует структурированный список tool_calls.

    Эта функция — «cheat sheet» для LLM: если модель не справляется
    с многокомпонентным запросом, бэкенд сам формирует правильные вызовы.

    Args:
        message: Исходное сообщение пользователя.
        current_tasks: Текущий список задач для разрешения ID по assignee.

    Returns:
        Список dict с ключами: name, arguments, id.
    """
    msg_lower = message.lower()

    # Справочник: lowercased assignee → task_id
    assignee_to_id: dict[str, str] = {}
    if current_tasks:
        for t in current_tasks:
            a = t.get("assignee", "")
            if a:
                al = a.lower()
                assignee_to_id[al] = t.get("id", "")
                if " " in al:
                    assignee_to_id[al.split()[0]] = t.get("id", "")

    calls: list[dict[str, Any]] = []

    # --- 1. DELETE: "строчку N" ---
    line_match = re.search(r"строчк[уи]\s+(\d+)", msg_lower)
    if line_match:
        n = line_match.group(1)
        calls.append({
            "id": "call_delete",
            "name": "delete_tasks",
            "arguments": {"task_ids": [f"task-{n}"]},
        })

    # --- 2. UPDATE: "Имя Фам у сделай задачу со/с X по/до Y месяц" ---
    update_match = re.search(
        r"([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)\s+"
        r"(?:сделай|сделать|перенеси|перенести|измени|изменить)\s+задачу\s+"
        r"(?:со|с)\s*(\d{1,2})(?:\s+" + MONTHS_REGEX + r")?\s*"
        r"(?:по|до)\s*(\d{1,2})\s+" + MONTHS_REGEX,
        message,
    )
    if update_match:
        name_first, name_last, start_day, end_day = update_match.groups()[:4]
        name_last_nom = (
            name_last.rstrip("у") if name_last.endswith("у") else name_last
        )
        duration = int(end_day) - int(start_day) + 1
        task_id = resolve_task_id(name_first, name_last_nom, assignee_to_id)
        args: dict[str, Any] = {"task_id": task_id, "duration_days": duration}
        calls.append({
            "id": f"call_update_{task_id}",
            "name": "update_task_details",
            "arguments": args,
        })

    # --- 3. ADD: "добавь task-N ..." ---
    add_match = re.search(r"добавь(?:\s+задачу)?\s+task-(\d+)", msg_lower)
    if add_match:
        task_num = add_match.group(1)
        after_add = message[add_match.end():]
        snippet = after_add[:80]

        # assignee
        assignee = ""
        am = re.search(r"[-—]?\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)", snippet)
        if am:
            assignee = am.group(1).strip().rstrip(",").rstrip()
        # Strip dative endings from assignee for display
        if assignee.endswith("у"):
            assignee = assignee.rstrip("у")

        # title
        tm = re.search(
            r"(?:задача\s+называется|называется)\s+(.+?)(?:\.|,|\Z)",
            message, re.IGNORECASE,
        )
        title = tm.group(1).strip().rstrip(".").rstrip(",") if tm else ""

        # dates → duration_days
        duration = None
        date_match = re.search(
            r"(?:со|с)\s*(\d{1,2})(?:\s+(" + MONTHS_REGEX + r"))?\s*"
            r"(?:по|до)\s*(\d{1,2})\s+(" + MONTHS_REGEX + r")",
            after_add,
        )
        if date_match:
            s_day, s_m, e_day, e_m = date_match.groups()
            y = date.today().year
            sm = RUSSIAN_MONTHS.get(s_m, RUSSIAN_MONTHS.get(e_m, 8)) if s_m else RUSSIAN_MONTHS.get(e_m, 8)
            em = RUSSIAN_MONTHS.get(e_m, 8)
            try:
                sd = date(y, sm, int(s_day))
                ed = date(y, em, int(e_day))
                if ed < sd:
                    ed = date(y + 1, em, int(e_day))
                duration = (ed - sd).days + 1
            except ValueError:
                duration = int(e_day) - int(s_day) + 1
        if duration is None:
            duration = 1

        # predecessors
        pred = ""
        pm = re.search(r"после\s+task-(\d+)|после\s+tasl-(\d+)", message, re.IGNORECASE)
        if pm:
            pred = f"task-{pm.group(1) or pm.group(2)}"

        calls.append({
            "id": f"call_add_{task_num}",
            "name": "add_new_task",
            "arguments": {
                "title": title,
                "assignee": assignee,
                "duration_days": duration,
                "predecessors": [pred] if pred else [],
            },
        })

    return calls


def analyze_request(
    message: str,
    current_tasks: list[dict[str, Any]] | None = None,
) -> str:
    """Предварительный разбор запроса для помощи LLM.

    Генерирует ТОЧНЫЕ шаблоны tool_calls, которые модель ОБЯЗАНА вызвать.
    """
    msg_lower = message.lower()

    assignee_to_id: dict[str, str] = {}
    if current_tasks:
        for t in current_tasks:
            a = t.get("assignee", "")
            if a:
                al = a.lower()
                assignee_to_id[al] = t.get("id", "")
                if " " in al:
                    assignee_to_id[al.split()[0]] = t.get("id", "")

    call_templates: list[str] = []
    step = 0

    # 1. DELETE: "строчку N"
    line_match = re.search(r"строчк[уи]\s+(\d+)", msg_lower)
    if line_match:
        n = line_match.group(1)
        step += 1
        call_templates.append(
            f"ШАГ {step}: delete_tasks(task_ids=['task-{n}'])  // «строчка {n}» = task-{n}"
        )

    # 2. UPDATE: "Имя Фам у сделай задачу со/с X по/до Y месяц"
    update_match = re.search(
        r"([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)\s+"
        r"(?:сделай|сделать|перенеси|перенести|измени|изменить)\s+задачу\s+"
        r"(?:со|с)\s*(\d{1,2})(?:\s+" + MONTHS_REGEX + r")?\s*"
        r"(?:по|до)\s*(\d{1,2})\s+" + MONTHS_REGEX,
        message,
    )
    if update_match:
        name_first, name_last, start_day, end_day = update_match.groups()[:4]
        name_last_nom = name_last.rstrip("у") if name_last.endswith("у") else name_last
        duration = int(end_day) - int(start_day) + 1
        task_id = resolve_task_id(name_first, name_last_nom, assignee_to_id)
        step += 1
        call_templates.append(
            f"ШАГ {step}: update_task_details(task_id='{task_id}', duration_days={duration})  "
            f"// «{name_first} {name_last}» → assignee «{name_first} {name_last_nom}» → {task_id}"
        )

    # 3. ADD: "добавь task-N ..."
    add_match = re.search(r"добавь(?:\s+задачу)?\s+task-(\d+)", msg_lower)
    if add_match:
        task_num = add_match.group(1)
        after_add = message[add_match.end():]
        snippet = after_add[:80]

        assignee = ""
        am = re.search(r"[-—]?\s*([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)", snippet)
        if am:
            assignee = am.group(1).strip().rstrip(",").rstrip()

        tm = re.search(
            r"(?:задача\s+называется|называется)\s+(.+?)(?:\.|,|\Z)",
            message, re.IGNORECASE,
        )
        title = tm.group(1).strip().rstrip(".").rstrip(",") if tm else ""

        duration = None
        s_day_disp = "?"
        month_disp = ""
        date_match = re.search(
            r"(?:со|с)\s*(\d{1,2})(?:\s+(" + MONTHS_REGEX + r"))?\s*"
            r"(?:по|до)\s*(\d{1,2})\s+(" + MONTHS_REGEX + r")",
            after_add,
        )
        if date_match:
            s_day, s_m, e_day, e_m = date_match.groups()
            s_day_disp = s_day
            y = date.today().year
            sm = RUSSIAN_MONTHS.get(s_m, RUSSIAN_MONTHS.get(e_m, 8)) if s_m else RUSSIAN_MONTHS.get(e_m, 8)
            em = RUSSIAN_MONTHS.get(e_m, 8)
            month_disp = f"{s_m} — {e_m}" if s_m and e_m else e_m
            try:
                sd = date(y, sm, int(s_day))
                ed = date(y, em, int(e_day))
                if ed < sd:
                    ed = date(y + 1, em, int(e_day))
                duration = (ed - sd).days + 1
            except ValueError:
                duration = int(e_day) - int(s_day) + 1

        if duration is None:
            duration = 1

        pred = ""
        pm = re.search(r"после\s+task-(\d+)|после\s+tasl-(\d+)", message, re.IGNORECASE)
        if pm:
            pred = f"task-{pm.group(1) or pm.group(2)}"

        pred_arg = f"'{pred}'" if pred else ""
        step += 1
        call_templates.append(
            f"ШАГ {step}: add_new_task(title='{title}', assignee='{assignee}', "
            f"duration_days={duration}, predecessors=[{pred_arg}])  "
            f"// даты: {s_day_disp} {month_disp}"
        )

    if call_templates:
        header = (
            f"ОЖИДАЕМЫЕ ВЫЗОВЫ (ТЫ ОБЯЗАН вызвать ровно {len(call_templates)} "
            "инструмента(ов) в ОДНОМ ответе, без вопросов):\n"
        )
        return header + "\n".join(call_templates) + "\n\n"

    return ""
