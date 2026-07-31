"""Мультипровайдерный LLM-клиент на базе официального SDK openai.

Работает с любым OpenAI-совместимым API:
  OpenRouter, OpenAI, DeepSeek Direct, Ollama, LM Studio, Groq.

Логика провайдера задаётся через переменные окружения (через python-dotenv в main.py).

Интерфейс клиента:
  - build_system_message() -> dict  — системный промпт ассистента Гантта.
  - async chat(messages, tools) -> {"reply": str, "tool_calls": list[dict]}
    Формат ответа строго совместим с циклом Tool Calling в routers/chat.py.

Конфигурация из переменных окружения:
  LLM_BASE_URL    — base_url для AsyncOpenAI (default: "https://openrouter.ai/api/v1").
  LLM_API_KEY     — ключ API (обязателен).
  LLM_MODEL       — идентификатор модели (default: "deepseek/deepseek-chat").
  LLM_MAX_TOKENS  — лимит токенов ответа (default: 4096).

Для обратной совместимости также читаются OPENROUTER_API_KEY, OPENROUTER_MODEL,
OPENROUTER_MAX_TOKENS, OPENROUTER_BASE_URL — они используются как fallback,
если LLM_* переменные не заданы.
"""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_MODEL = "deepseek/deepseek-chat"
DEFAULT_MAX_TOKENS = 4096

SYSTEM_PROMPT = (
    "Ты — AI-ассистент по управлению проектами на диаграмме Гантта. "
    "Твоя задача — помогать пользователю управлять задачами: изменять "
    "длительность, переставлять зависимости, добавлять и удалять задачи. "
    "Ты можешь вызывать инструменты (functions) для мутации состояния проекта. "
    "После каждого изменения даты всех задач автоматически пересчитываются "
    "с учётом графа зависимостей (DAG Scheduler).\n\n"
    "Правила:\n"
    "- Общайся на русском языке.\n"
    "- Отвечай кратко и по делу: сообщи, что именно изменено, и назови "
    "затронутые задачи.\n"
    "- Если инструмент вернул ошибку, объясни пользователю, что пошло не так, "
    "и предложи исправление.\n"
    "- НЕ придумывай id для новых задач — сервер создаст id автоматически.\n"
    "- При обновлении predecessors передавай ПОЛНЫЙ итоговый список, "
    "а не только изменения."
)


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
    """Извлекает модель (LLM_MODEL с fallback на OPENROUTER_MODEL)."""
    return _env("LLM_MODEL") or _env("OPENROUTER_MODEL") or DEFAULT_MODEL


def _resolve_max_tokens() -> int:
    """Извлекает max_tokens (LLM_MAX_TOKENS с fallback на OPENROUTER_MAX_TOKENS)."""
    raw = _env("LLM_MAX_TOKENS") or _env("OPENROUTER_MAX_TOKENS")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return DEFAULT_MAX_TOKENS


class LLMClient:
    """Мультипровайдерный LLM-клиент на базе openai.AsyncOpenAI.

    Инициализируется с base_url и api_key, благодаря чему работает с любым
    OpenAI-совместимым API.

    Attributes:
        model: Идентификатор LLM-модели (из LLM_MODEL).
        max_tokens: Лимит токенов ответа.
        _client: openai.AsyncOpenAI — асинхронный HTTP-клиент.
    """

    def __init__(self) -> None:
        base_url = _resolve_base_url()
        api_key = _resolve_api_key()
        self.model = _resolve_model()
        self.max_tokens = _resolve_max_tokens()
        self._client = AsyncOpenAI(base_url=base_url, api_key=api_key)

    def build_system_message(self) -> dict[str, str]:
        """Формирует системный промпт для LLM."""
        return {"role": "system", "content": SYSTEM_PROMPT}

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


def get_client() -> LLMClient:
    """Возвращает (и лениво создаёт) глобальный экземпляр LLMClient."""
    global _client_instance
    if _client_instance is None:
        _client_instance = LLMClient()
    return _client_instance