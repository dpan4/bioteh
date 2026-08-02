"""Утилита работы с NDJSON-логами чата.

Структура логов:
    backend/logs/
      YYYY-MM-DD/                   — папка с датой
        chat.log                    — все записи за день (NDJSON)
        HH-MM-SS_<action>.json      — отдельный файл по каждому действию с LLM

Каждый вызов /api/chat создаёт:
  1. Запись в chat.log (сводный файл за день).
  2. Отдельный файл для данного запроса с именем HH-MM-SS_<действие>.json.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Папка для логов — рядом с корнем бэкенда (на уровень выше app/)
LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def _get_day_dir() -> Path:
    """Возвращает (и создаёт) папку логов для текущей даты: logs/YYYY-MM-DD/."""
    date_str = datetime.now().strftime("%Y-%m-%d")
    day_dir = LOGS_DIR / date_str
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir


def _action_name(entry: dict[str, Any]) -> str:
    """Извлекает краткое имя действия из лог-записи для имени файла.

    Имя файла: HH-MM-SS_<action>.json
    Где action — первое имя tool call или 'chat' если инструменты не вызывались.

    Args:
        entry: Словарь лога с ключом "tool_calls".

    Returns:
        Строка-имя действия (латиница, нижний регистр, без спецсимволов).
    """
    tool_calls = entry.get("tool_calls", [])
    if tool_calls and isinstance(tool_calls, list):
        first_tool = tool_calls[0]
        if isinstance(first_tool, dict):
            name = first_tool.get("tool", "chat")
            name = re.sub(r"[^a-zA-Z0-9_-]", "_", str(name))
            return name[:50]
    return "chat"


def write_log(entry: dict[str, Any]) -> None:
    """Записывает лог-запроса: в сводный chat.log + в отдельный файл действия.

    Структура:
      logs/YYYY-MM-DD/chat.log           — все записи за день (NDJSON)
      logs/YYYY-MM-DD/HH-MM-SS_<action>  — отдельный файл по действию

    Ошибки записи логируются в stderr, но не останавливают запрос.

    Args:
        entry: Словарь с данными запроса для записи в лог.
    """
    try:
        day_dir = _get_day_dir()
        now = datetime.now()
        timestamp = now.strftime("%H-%M-%S")

        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"

        # 1. Сvodный файл за день
        summary_path = day_dir / "chat.log"
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(line)

        # 2. Отдельный файл по действию
        action = _action_name(entry)
        action_filename = f"{timestamp}_{action}.json"
        action_path = day_dir / action_filename
        with open(action_path, "w", encoding="utf-8") as f:
            f.write(line)

    except Exception as exc:
        logger.warning("Не удалось записать лог: %s", exc)
