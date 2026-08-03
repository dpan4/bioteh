"""Цветной логгер приложения с ANSI-раскраской по тегам.

Использование:
    from app.logger import logger

    logger.info("[🤖 AI AGENT] Получен промпт от пользователя")
    logger.info("[📊 DAG ENGINE] Запуск расчёта графа...")
    logger.warning("[🔒 GUARD] Повторный вызов инструментов!")
"""

import logging
import sys


class CustomFormatter(logging.Formatter):
    """Форматтер с ANSI-раскраской по ключевым тегам-префиксам."""

    cyan = "\x1b[36m"
    magenta = "\x1b[35m"
    yellow = "\x1b[33m"
    green = "\x1b[32m"
    reset = "\x1b[0m"

    FORMAT = "%(asctime)s - %(message)s"

    def format(self, record: logging.LogRecord) -> str:
        log_message = super().format(record)

        if "[🤖 AI AGENT]" in log_message:
            return f"{self.cyan}{log_message}{self.reset}"
        elif "[📊 DAG ENGINE]" in log_message:
            return f"{self.magenta}{log_message}{self.reset}"
        elif "[🔒 GUARD]" in log_message:
            return f"{self.yellow}{log_message}{self.reset}"
        elif "SUCCESS" in log_message.upper():
            return f"{self.green}{log_message}{self.reset}"

        return log_message


logger = logging.getLogger("app_logger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        CustomFormatter(CustomFormatter.FORMAT, datefmt="%H:%M:%S")
    )
    logger.addHandler(handler)
