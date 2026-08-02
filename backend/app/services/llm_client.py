"""Мультипровайдерный LLM-клиент на базе официального SDK openai.

Работает с любым OpenAI-совместимым API:
  OpenRouter, OpenAI, DeepSeek Direct, Ollama, LM Studio, Groq.

Логика провайдера задаётся через переменные окружения (через python-dotenv в main.py).

Интерфейс клиента:
  - build_system_message() -> dict  — системный промпт ассистента Гантта.
  - async chat(messages, tools) -> {"reply": str, "tool_calls": list[dict]}
    Формат ответа строго совместим с циклом Tool Calling в routers/chat.py.

Конфигурация из переменных окружения (.env):
  LLM_API_KEY     — ключ API (обязательный).
  LLM_MODEL       — идентификатор модели (обязательный).
  LLM_BASE_URL    — base_url для AsyncOpenAI (default: "https://openrouter.ai/api/v1").
  LLM_MAX_TOKENS  — лимит токенов ответа (default: 4096).
  LLM_TEMPERATURE — температура генерации (default: 0.1).

Для обратной совместимости также читаются OPENROUTER_API_KEY, OPENROUTER_MODEL,
OPENROUTER_MAX_TOKENS, OPENROUTER_BASE_URL — они используются как fallback,
если LLM_* переменные не заданы.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.1

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system.md"


def load_system_prompt(tasks_json: str) -> str:
    """Загружает системный промпт из Markdown-файла и подставляет актуальные задачи."""
    if not SYSTEM_PROMPT_PATH.exists():
        raise FileNotFoundError(f"Файл системного промпта не найден: {SYSTEM_PROMPT_PATH}")

    template = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8")
    return template.replace("{{tasks_json}}", tasks_json)

def _env(key: str, fallback: str = "") -> str:
    """Читает переменную окружения, очищая пробелы.

    Args:
        key: Имя переменной окружения.
        fallback: Значение по умолчанию, если переменная не задана.

    Returns:
        Строковое значение переменной окружения.
    """
    return os.getenv(key, fallback).strip()


def _resolve_api_key() -> str:
    """Извлекает ключ API из env (LLM_API_KEY с fallback на OPENROUTER_API_KEY).

    Returns:
        Ключ API.

    Raises:
        ValueError: Если ни одна переменная не задана.
    """
    key = _env("LLM_API_KEY") or _env("OPENROUTER_API_KEY")
    if not key:
        raise ValueError(
            "Не задан LLM_API_KEY. Укажите ключ в переменных окружения "
            "или создайте файл .env с переменной LLM_API_KEY."
        )
    return key


def _resolve_base_url() -> str:
    """Извлекает base_url (LLM_BASE_URL с fallback на OPENROUTER_BASE_URL)."""
    return _env("LLM_BASE_URL") or _env("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL


def _resolve_model() -> str:
    """Извлекает модель (LLM_MODEL с fallback на OPENROUTER_MODEL).

    Raises:
        ValueError: Если ни LLM_MODEL, ни OPENROUTER_MODEL не заданы в .env.
    """
    model = _env("LLM_MODEL") or _env("OPENROUTER_MODEL")
    if not model:
        raise ValueError(
            "Переменная LLM_MODEL не задана в .env. "
            "Укажите модель в формате: LLM_MODEL=deepseek/deepseek-chat"
        )
    return model


def _resolve_max_tokens() -> int:
    """Извлекает max_tokens (LLM_MAX_TOKENS с fallback на OPENROUTER_MAX_TOKENS)."""
    raw = _env("LLM_MAX_TOKENS") or _env("OPENROUTER_MAX_TOKENS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_MAX_TOKENS


def _resolve_temperature() -> float:
    """Извлекает temperature (LLM_TEMPERATURE).

    Диапазон: 0.0 (детерминированный) — 2.0 (максимально креативный).
    По умолчанию 0.1 — баланс между точностью и разнообразием.

    Returns:
        Значение temperature от 0.0 до 2.0.
    """
    raw = _env("LLM_TEMPERATURE")
    if raw:
        try:
            temp = float(raw)
            return max(0.0, min(2.0, temp))
        except ValueError:
            pass
    return DEFAULT_TEMPERATURE


class LLMClient:
    """Мультипровайдерный LLM-клиент на базе openai.AsyncOpenAI.

    Инициализируется с base_url и api_key, благодаря чему работает с любым
    OpenAI-совместимым API.

    Attributes:
        model: Идентификатор LLM-модели (из LLM_MODEL, обязательный).
        max_tokens: Лимит токенов ответа.
        temperature: Степень креативности (0.0–2.0).
        _client: openai.AsyncOpenAI — асинхронный HTTP-клиент.
    """

    def __init__(self) -> None:
        base_url = _resolve_base_url()
        api_key = _resolve_api_key()
        self.model = _resolve_model()
        self.max_tokens = _resolve_max_tokens()
        self.temperature = _resolve_temperature()
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)
        logger.info(
            "[LLMClient] Model='%s', BaseURL='%s', Temp=%.2f, MaxTokens=%d",
            self.model, base_url, self.temperature, self.max_tokens,
        )

    def build_system_message(
        self, current_tasks: list[dict[str, Any]] | None = None
    ) -> dict[str, str]:
        """Формирует системный промпт для LLM с актуальным списком задач.

        Args:
            current_tasks: Список текущих задач проекта в формате dict
                (обычно GanttTask сериализованные через model_dump(by_alias=True)).
                Если None — система сообщит, что задач нет.

        Returns:
            Словарь с ключами "role" и "content" (системное сообщение).
        """
        if current_tasks is None or len(current_tasks) == 0:
            tasks_json = "[]  # Проект пуст. Пользователь может загрузить Excel или попросить создать задачи."
        else:
            tasks_compact = [
                {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "assignee": task.get("assignee", ""),
                    "durationDays": task.get("durationDays"),
                    "predecessors": task.get("predecessors", []),
                    "startDate": task.get("startDate"),
                    "endDate": task.get("endDate"),
                }
                for task in current_tasks
            ]
            tasks_json = json.dumps(
                tasks_compact, ensure_ascii=False, indent=2
            )

        system_prompt = load_system_prompt(tasks_json)
        return {"role": "system", "content": system_prompt}

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Отправляет сообщения в LLM-провайдер и возвращает распарсенный ответ.

        Сигнатура и формат ответа строго совместимы с циклом Tool Calling
        в backend/app/routers/chat.py.

        Args:
            messages: История сообщений [{"role": ..., "content": ...}].
                Роли: system, user, assistant, tool.
            tools: Список дефиниций инструментов в формате function calling.
                Если None — LLM не будет вызывать инструменты.

        Returns:
            Словарь с ключами:
            - "reply": str — текстовый ответ ассистента (может быть пустым, если
              ассистент только вызвал инструменты без текста).
            - "tool_calls": list[dict] — список вызовов инструментов. Каждый вызов:
              {"id": str, "name": str, "arguments": dict}.

        Raises:
            openai.APIError: Если провайдер вернул ошибку HTTP.
            ValueError: Если ответ не удалось распарсить.
        """
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=messages,  # type: ignore[arg-type]
            tools=tools if tools else [],  # type: ignore[arg-type]
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )

        if not response.choices:
            raise ValueError(
                "LLM-провайдер вернул ответ без choices. "
                f"Ответ: {response.model_dump_json()[:500]}"
            )

        choice = response.choices[0]
        message = choice.message

        reply = message.content or ""

        tool_calls: list[dict[str, Any]] = []
        for tc in message.tool_calls or []:
            args_str = tc.function.arguments or "{}"
            try:
                arguments = json.loads(args_str)
            except json.JSONDecodeError:
                arguments = {}
            tool_calls.append({
                "id": tc.id or "",
                "name": tc.function.name or "",
                "arguments": arguments,
            })

        return {"reply": reply, "tool_calls": tool_calls}

    async def close(self) -> None:
        """Закрывает HTTP-клиент."""
        await self._client.close()


_client_instance: LLMClient | None = None


def get_client(force_reload: bool = False) -> LLMClient:
    """Возвращает (и лениво создаёт) глобальный экземпляр LLMClient.

    Args:
        force_reload: Если True — принудительно пересоздаёт клиент
            (полезно при смене .env без перезапуска сервера).
    """
    global _client_instance
    if force_reload or _client_instance is None:
        _client_instance = LLMClient()
    return _client_instance