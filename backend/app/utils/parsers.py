"""Утилитарные функции: работа с датами, нормализация tool calls, языковой guard."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

# =====================================================================
# КОНСТАНТЫ: русские месяцы
# =====================================================================

RUSSIAN_MONTHS = {
    "января": 1, "февраля": 2, "марта": 3, "апреля": 4,
    "мая": 5, "июня": 6, "июля": 7, "августа": 8,
    "сентября": 9, "октября": 10, "ноября": 11, "декабря": 12,
}

RUSSIAN_MONTH_NAMES = {v: k for k, v in RUSSIAN_MONTHS.items()}

MONTHS_REGEX = (
    r"(?:января|февраля|марта|апреля|мая|июня|июля|августа|"
    r"сентября|октября|ноября|декабря)"
)

# =====================================================================
# КОНСТАНТЫ: маппинг алиасов инструментов
# =====================================================================

TOOL_MAPPING = {
    "create_task": "add_new_task",
    "insert_task": "add_new_task",
    "edit_task": "update_task_details",
    "change_task": "update_task_details",
    "modify_task": "update_task_details",
    "remove_task": "delete_tasks",
    "delete_task": "delete_tasks",
}


# =====================================================================
# ФУНКЦИИ: работа с датами
# =====================================================================


def parse_iso(date_str: str) -> date | None:
    """Парсит ISO-дату YYYY-MM-DD в объект date."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def format_date_ru(d: date | None) -> str:
    """Форматирует дату в русском формате: '20 августа'."""
    if d is None:
        return "неизвестно"
    month_name = RUSSIAN_MONTH_NAMES.get(d.month, str(d.month))
    return f"{d.day} {month_name}"


def extract_mentioned_dates(text: str) -> list[date]:
    """Извлекает упомянутые в тексте даты (русский формат + ISO + DD.MM).

    Поддерживаемые форматы:
      - «20 августа», «2 сентября» (день + месяц в родительном падеже)
      - «со 2 по 18 августа» (диапазон через слово «по»)
      - «02.08», «2/8» (числовой DD.MM или DD/MM)
      - «2026-08-20» (ISO)
    """
    year = date.today().year
    dates: list[date] = []

    # 1. Диапазоны «N по M месяц» (например: «со 2 по 18 августа»)
    range_pattern = (
        r"(\d{1,2})\s+по\s+(\d{1,2})\s+"
        r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)"
    )
    for m in re.finditer(range_pattern, text.lower()):
        start_day, end_day, month_word = int(m.group(1)), int(m.group(2)), m.group(3)
        month = RUSSIAN_MONTHS.get(month_word)
        if month:
            for day in (start_day, end_day):
                try:
                    dates.append(date(year, month, day))
                except ValueError:
                    pass

    # 2. Сто́ячие даты «N месяц» (например: «20 августа»)
    standalone_pattern = (
        r"(\d{1,2})\s+"
        r"(января|февраля|марта|апреля|мая|июня|июля|августа|"
        r"сентября|октября|ноября|декабря)"
    )
    for m in re.finditer(standalone_pattern, text.lower()):
        day, month_word = int(m.group(1)), m.group(2)
        month = RUSSIAN_MONTHS.get(month_word)
        if month:
            try:
                dates.append(date(year, month, day))
            except ValueError:
                pass

    # 3. Числовой формат DD.MM или DD/MM
    numeric_pattern = r"\b(\d{1,2})[./](\d{1,2})\b"
    for m in re.finditer(numeric_pattern, text):
        day, month = int(m.group(1)), int(m.group(2))
        try:
            dates.append(date(year, month, day))
        except ValueError:
            pass

    # 4. ISO-формат YYYY-MM-DD
    iso_pattern = r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)"
    for m in re.finditer(iso_pattern, text):
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            dates.append(date(y, mo, d))
        except ValueError:
            pass

    # Убираем дубликаты, сохраняем порядок появления
    seen: set[date] = set()
    unique: list[date] = []
    for d in dates:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def extract_dates_for_task(text: str, task_id: str) -> list[date]:
    """Извлекает даты, упомянутые в том предложении, где упомянут task_id.

    Делит текст на предложения (по '.', '!', '?'), находит предложение с task_id
    и возвращает даты только из этого предложения.
    """
    sentences = re.split(r"[.!?]+", text)
    for sent in sentences:
        if task_id.lower() in sent.lower():
            return extract_mentioned_dates(sent)
    return []


# =====================================================================
# ФУНКЦИИ: нормализация и сортировка tool calls
# =====================================================================


def normalize_task_ids_in_args(args: dict[str, Any]) -> dict[str, Any]:
    """Исправляет опечатки вида 'tasl-5', 'task_5', 'таск-5' в 'task-5'."""
    id_pattern = re.compile(r'(?:task|tasl|task_|таск)[-_]?(\d+)', re.IGNORECASE)
    new_args = args.copy() if args else {}

    for key in ("task_id", "task_ids", "predecessors"):
        if key not in new_args:
            continue
        val = new_args[key]
        if isinstance(val, str):
            match = id_pattern.search(val)
            if match:
                new_args[key] = f"task-{match.group(1)}"
        elif isinstance(val, list):
            normalized = []
            for item in val:
                if isinstance(item, str):
                    m = id_pattern.search(item)
                    normalized.append(f"task-{m.group(1)}" if m else item)
                else:
                    normalized.append(item)
            new_args[key] = normalized

    return new_args


def extract_tools_from_xml_or_text(text: str) -> list[dict[str, Any]]:
    """Извлекает вызовы инструментов, если OpenRouter выплюнул их текстом в reply.

    Обрабатывает форматы:
    1. <tool_call>name\n<arg_key>k</arg_key><arg_value>v</arg_value></tool_call>
    2. ```json {"tool": "name", "arguments": {...}} ```
    """
    if not text:
        return []

    extracted: list[dict[str, Any]] = []

    # 1. Парсинг XML тегов <tool_call>
    xml_blocks = re.findall(r'<tool_call>(.*?)</tool_call>', text, re.DOTALL)
    for idx, block in enumerate(xml_blocks):
        lines = [line.strip() for line in block.strip().split('\n') if line.strip()]
        if not lines:
            continue

        tool_name = lines[0]
        keys = re.findall(r'<arg_key>(.*?)</arg_key>', block)
        vals = re.findall(r'<arg_value>(.*?)</arg_value>', block)

        args: dict[str, Any] = {}
        for k, v in zip(keys, vals):
            v_clean = v.strip()
            if v_clean.isdigit():
                args[k.strip()] = int(v_clean)
            else:
                args[k.strip()] = v_clean

        extracted.append({
            "id": f"call_xml_{idx}",
            "name": tool_name,
            "arguments": args,
        })

    # 2. Если XML не найден, ищем JSON-блоки в markdown
    if not extracted:
        json_blocks = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
        for idx, j_str in enumerate(json_blocks):
            try:
                data = json.loads(j_str)
                tool_name = data.get("tool") or data.get("name") or data.get("function")
                args = data.get("arguments") or data.get("args") or {}
                if tool_name:
                    extracted.append({
                        "id": f"call_json_{idx}",
                        "name": tool_name,
                        "arguments": args,
                    })
            except Exception:
                pass

    return extracted


def clean_and_sort_tools(raw_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Нормализует имена, исправляет опечатки ID и сортирует вызовы (Delete -> Add -> Update)."""
    cleaned: list[dict[str, Any]] = []

    for call in raw_calls:
        name = call.get("name") or call.get("tool") or ""
        args = call.get("arguments", {})
        cid = call.get("id", "call_gen")

        # Алиасы
        if name in TOOL_MAPPING:
            name = TOOL_MAPPING[name]

        # Контекстуальная коррекция перепутанных инструментов
        if name == "update_task_details" and "task_id" not in args and "title" in args:
            name = "add_new_task"
        elif name == "add_new_task" and "task_id" in args:
            name = "update_task_details"

        # Нормализация ID задач
        args = normalize_task_ids_in_args(args)

        if name:
            cleaned.append({"id": cid, "name": name, "arguments": args})

    # Сортировка: Delete (1) -> Add (2) -> Update (3)
    order = {"delete_tasks": 1, "add_new_task": 2, "update_task_details": 3}
    return sorted(cleaned, key=lambda x: order.get(x["name"], 4))


def ensure_russian_language(text: str) -> str:
    """Защита от переключения бесплатной модели на английский язык."""
    if not text:
        return text

    cyrillic_chars = len(re.findall(r'[а-яА-ЯёЁ]', text))
    total_chars = len(text)

    # Если в отчете длиннее 30 символов кириллицы меньше 15% — считаем, что модель ушла в английский
    if total_chars > 30 and (cyrillic_chars / total_chars) < 0.15:
        return (
            "Запрос обработан и расписание обновлено. "
            "Обратите внимание: детализация задач приведена в таблице ниже."
        )
    return text
