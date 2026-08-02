"""Утилита работы с NDJSON-логами чата.

Лог-файлы хранятся в backend/logs/chat_YYYY-MM-DD.log.
Каждый вызов /api/chat пишет одну JSON-строку (NDJSON).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Папка для логов — рядом с корнем бэкенда (на уровень выше app/)
LOGS_DIR = Path(__file__).resolve().parent.parent.parent / "logs"


def get_log_path() -> Path:
    """Возвращает путь к файлу лога для текущей даты."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    return LOGS_DIR / f"chat_{date_str}.log"


def write_log(entry: dict[str, Any]) -> None:
    """Записывает одну запись лога в файл как JSON-строку (NDJSON).

    Каждый вызов /api/chat пишет одну JSON-строку в файл лога.
    Ошибки записи логируются в stderr, но не останавливают запрос.

    Args:
        entry: Словарь с данными запроса для записи в лог.
    """
    try:
        log_path = get_log_path()
        line = json.dumps(entry, ensure_ascii=False, default=str) + "\n"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        logger.warning(f"Не удалось записать лог: {exc}")
