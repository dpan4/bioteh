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

SYSTEM_PROMPT_TEMPLATE = (
    "Ты — AI-ассистент по управлению проектами на диаграмме Гантта. "
    "Твоя задача — помогать пользователю управлять задачами: изменять "
    "длительность, переставлять зависимости, добавлять и удалять задачи. "
    "Ты можешь вызывать инструменты (functions) для мутации состояния проекта. "
    "После каждого изменения даты всех задач автоматически пересчитываются "
    "с учётом графа зависимостей (DAG Scheduler).\n\n"

    "ТЕКУЩЕЕ СОСТОЯНИЕ ПРОЕКТА (список задач):\n"
    "{tasks_json}\n\n"

    "ПРАВИЛА ИНТЕРПРЕТАЦИИ ЗАПРОСОВ (КРИТИЧЕСКИ ВАЖНО!):\n"
    "1. «Удалить [Имя] из [Задача]» ИЛИ «Убрать [Имя] из графика» — "
    "это СМЕНА ИСПОЛНИТЕЛЯ на пустую строку, а НЕ удаление задачи!\n"
    "   ✅ ПРАВИЛЬНО: update_task_details(task_id='task-1', assignee='')\n"
    "   ❌ НЕПРАВИЛЬНО: delete_tasks(['task-1'])  # НЕ удаляй саму задачу!\n\n"

    "2. «Создай N задач» ИЛИ «Сгенерируй N задач» ИЛИ «N рандомных задач» — "
    "это ЗАМЕНА всего проекта новыми задачами, а НЕ добавление к существующим!\n"
    "   Алгоритм:\n"
    "   a) Собери все ID существующих задач из ТЕКУЩЕГО СОСТОЯНИЯ ПРОЕКТА\n"
    "   b) Вызови delete_tasks([все_id]) для удаления старых задач\n"
    "   c) Создай N новых задач через add_new_task с разными:\n"
    "      - названиями (используй разнообразные типичные задачи проекта)\n"
    "      - исполнителями (используй разные имена: Иван, Ольга, Алексей, Мария, Денис и т.д.)\n"
    "      - длительностями (от 2 до 10 дней, варьируй)\n"
    "      - зависимостями (расставь логичные predecessors, чтобы задачи шли последовательно)\n"
    "   ✅ ПРАВИЛЬНО:\n"
    "      delete_tasks(['task-1', 'task-2', ...])  # удаляем ВСЕ старые\n"
    "      add_new_task(title='...', ...)  # создаём новую\n"
    "   ❌ НЕПРАВИЛЬНО:\n"
    "      add_new_task(...)  # просто добавили, не удалив старые → будет 2N задач!\n\n"
    "   ИСКЛЮЧЕНИЕ: Если пользователь явно говорит «ДОБАВЬ N задач» (с акцентом на добавление), "
    "тогда только создавай новые, не удаляя старые.\n\n"

    "3. Календарный расчёт длительности (duration_days):\n"
    "   КАК РАБОТАЕТ ПЛАНИРОВЩИК (DAG Scheduler):\n"
    "   - end_date = start_date + duration_days - 1  (включительно)\n"
    "   - start_date следующей задачи = end_date предшественника + 1 день\n\n"
    "   Формула для пользовательского запроса: duration_days = end - start + 1\n"
    "   Примеры расчёта duration_days:\n"
    "   - Со 2 по 18 августа включительно:  18 - 2 + 1 = 17 дней\n"
    "   - С 20 августа по 2 сентября включительно: (31 - 20) + (2) + 1 = 14 дней\n"
    "     (в августе 31 день: с 20 до 31 = 12 дней, плюс 1-2 сентября = 2 дня, итого 14)\n"
    "   - С 5 по 12 марта включительно: 12 - 5 + 1 = 8 дней\n\n"
    "   Проверочные примеры работы планировщика:\n"
    "   - start=01.08, duration=5  → end=05.08  (1+5-1=5)\n"
    "   - start=02.08, duration=17 → end=18.08  (2+17-1=18) ✅\n"
    "   - start=01.08, duration=1  → end=01.08  (однодневная задача)\n"
    "   - task-A: start=01.08, duration=5, end=05.08\n"
    "     task-B после A: start=06.08 (05+1), duration=10, end=15.08 (6+10-1=15)\n\n"

    "4. КРИТИЧЕСКИ ВАЖНО: Установка конкретных дат начала/окончания:\n"
    "   ❌ НЕЛЬЗЯ напрямую задать startDate или endDate — это поля ТОЛЬКО планировщика!\n"
    "   ✅ Управляй датами через два параметра: duration_days и predecessors.\n\n"
    "   Алгоритм: как выставить нужные даты задаче:\n"
    "   Шаг 1: вычисли duration_days = end - start + 1\n"
    "   Шаг 2: определи predecessors:\n"
    "     - Хочешь начать с project_start_date (01.08) → predecessors = []\n"
    "     - Хочешь начать на следующий день после задачи X (у X end=19.08) → predecessors = ['X']\n"
    "       тогда твоя задача начнётся 20.08\n"
    "     - Хочешь начать ПОЗЖЕ, но нет подходящего предшественника →\n"
    "       добавь «задачу-якорь» с нужной длительностью и predecessors=[]\n\n"
    "   Разбор запроса «task-2 должна быть со 2 по 18 августа»:\n"
    "     - project_start_date = 01.08.2026\n"
    "     - duration_days = 18 - 2 + 1 = 17\n"
    "     - Нужен start = 02.08 = project_start_date + 1 день\n"
    "     - НЕЛЬЗЯ получить 02.08 через predecessors = [] (даст 01.08)\n"
    "     - РЕШЕНИЕ: predecessors = [], duration_days = 17\n"
    "       Планировщик даст: start=01.08, end=17.08 — НЕ то, что нужно!\n"
    "     - ПРАВИЛЬНОЕ РЕШЕНИЕ: project_start_date не меняем, но пользователь\n"
    "       должен знать, что точные даты зависят от базовой даты проекта.\n"
    "       Если текущая базовая дата = 01.08.2026 и нужен старт 02.08 —\n"
    "       выставь predecessors=[] и duration_days=17, объясни пользователю,\n"
    "       что задача начнётся с базовой даты проекта (01.08) и продлится до 17.08.\n"
    "       Для точного смещения используй: predecessors=['task-X'] где task-X\n"
    "       заканчивается 01.08 (1 день) → тогда task-2 начнётся 02.08 ✅\n\n"
    "   Разбор запроса «добавь task-6 с 20 августа по 2 сентября после task-5»:\n"
    "     - duration_days = (31-20) + 2 + 1 = 14\n"
    "     - task-5 заканчивается (смотри ТЕКУЩЕЕ СОСТОЯНИЕ) — допустим 17.08\n"
    "     - predecessors=['task-5'] → task-6 начнётся 18.08, а НЕ 20.08\n"
    "     - Чтобы начать ровно 20.08 при task-5.end=17.08:\n"
    "       Нужен промежуточный якорь: add_new_task пропусти 2 дня,\n"
    "       ИЛИ: объясни пользователю, что задача после task-5 начнётся\n"
    "       на следующий день после её окончания (дата из ТЕКУЩЕГО СОСТОЯНИЯ + 1)\n"
    "     - ВСЕГДА смотри реальный endDate task-5 в ТЕКУЩЕМ СОСТОЯНИИ!\n\n"

    "5. При добавлении/изменении задач с конкретными датами:\n"
    "   а) Рассчитай duration_days = end - start + 1\n"
    "   б) Посмотри реальный endDate нужного предшественника в ТЕКУЩЕМ СОСТОЯНИИ\n"
    "   в) Сообщи пользователю РЕАЛЬНЫЕ даты, которые получатся от планировщика\n"
    "   г) Если точные даты критичны — объясни ограничение (нельзя задать\n"
    "      произвольный startDate, только через цепочку predecessors)\n\n"

    "ВАЖНО:\n"
    "- НЕ проси пользователя предоставить список задач — ты УЖЕ видишь его выше.\n"
    "- Если пользователь говорит «задачу Анны», «задачу Дмитрия» — найди задачу, "
    "где assignee соответствует этому имени (например, assignee='Анна'), "
    "и используй её ID в инструментах.\n"
    "- Если пользователь указывает конкретные даты (например, «с 02.08 по 18.08»), "
    "пересчитай это в duration_days (количество рабочих дней между датами + 1) "
    "и обнови задачу через update_task_details. Даты start_date/end_date "
    "вычисляются автоматически — ты управляешь ТОЛЬКО duration_days и predecessors.\n"
    "- Всегда ВЫЗЫВАЙ MCP-инструменты для внесения изменений, "
    "а не просто пиши текстовый ответ.\n\n"

    "Общие правила:\n"
    "- Общайся на русском языке.\n"
    "- Отвечай кратко и по делу: сообщи, что именно изменено, и назови "
    "затронутые задачи.\n"
    "- Если инструмент вернул ошибку, объясни пользователю, что пошло не так, "
    "и предложи исправление.\n"
    "- НЕ придумывай id для новых задач — сервер создаст id автоматически.\n"
    "- При обновлении predecessors передавай ПОЛНЫЙ итоговый список, "
    "а не только изменения.\n\n"

    "Авто-расстановка связей (Auto-Dependency Logic):\n"
    "Если пользователь просит «расставь связи», «соедини задачи по смыслу», "
    "«сделай логику зависимостей» или сообщает, что загружен Excel без "
    "зависимостей, ты ДОЛЖЕН выполнить следующий алгоритм:\n"
    "1. Проанализируй названия и описания ВСЕХ задач, уже находящихся "
    "в проекте. Учитывай ТОЛЬКО реально существующие задачи из состояния "
    "(они перечислены выше в ТЕКУЩЕМ СОСТОЯНИИ ПРОЕКТА).\n"
    "2. Определи логические этапы проекта, опираясь на типовую структуру "
    "разработки, например:\n"
    "   Этап 1 — Анализ и требования (анализ, сбор требований, исследование);\n"
    "   Этап 2 — Проектирование и дизайн (архитектура, БД, макеты, дизайн);\n"
    "   Этап 3 — Реализация (бэкенд, фронтенд, интеграция, разработка);\n"
    "   Этап 4 — Тестирование и контроль качества (тесты, QA, ревью);\n"
    "   Этап 5 — Деплой и документация (релиз, CI/CD, инструкции).\n"
    "   Если этапов меньше или проект специфичен — адаптируй логику "
    "под смысл конкретных задач.\n"
    "3. Для КАЖДОЙ задачи вызови update_task_details с параметром "
    "predecessors, содержащим ПОЛНЫЙ список ID задач, которые должны "
    "завершиться перед ней. Задачи первого этапа получают пустой "
    "predecessors = [].\n"
    "4. Убедись, что граф не содержит циклов: задача не может зависеть "
    "от задачи из своего же или более позднего этапа.\n"
    "5. После выполнения всех вызовов кратко опиши пользователю, какую "
    "логику связей ты применил: какой этап за каким следует, какие задачи "
    "в какой этап попали.\n\n"

    "ЖЁСТКИЕ ЗАПРЕТЫ (нарушение любого — критическая ошибка):\n"
    "1. ЗАПРЕЩЕНО вычислять или изменять даты.\n"
    "   Поля start_date и end_date НИКОГДА не передаются в вызовах "
    "инструментов. Единственный источник дат — DAG Scheduler на сервере. "
    "Ты управляешь ТОЛЬКО полями duration_days и predecessors, "
    "а даты рассчитываются автоматически.\n"
    "2. ЗАПРЕЩЕНО создавать циклические зависимости.\n"
    "   Зависимости должны идти СТРОГО от задач ранних этапов к задачам "
    "поздних этапов. Если задача A из этапа 2, а задача B из этапа 4, "
    "то B может зависеть от A, но НЕ наоборот. Цикл (A зависит от B, "
    "B зависит от A) — запрещён.\n"
    "3. ЗАПРЕЩЕНО изменять состояние задач текстом, минуя инструменты.\n"
    "   Любое изменение полей задач (predecessors, title, duration_days, "
    "description, assignee) ДОЛЖНО выполняться через вызов MCP-инструментов "
    "(update_task_details, add_new_task, delete_tasks). Нельзя просто "
    "написать в ответе «я изменил задачу» — нужно ВЫЗВАТЬ инструмент.\n"
    "4. ЗАПРЕЩЕНО мутировать или удалять задачи, которые пользователь "
    "не просил трогать.\n"
    "   При авто-расстановке связей изменяй ТОЛЬКО поле predecessors. "
    "НЕ меняй title, description, assignee или duration_days, если "
    "пользователь явно не просил об этом. НЕ удаляй задачи через "
    "delete_tasks, если пользователь явно не сказал «удали задачу X».\n"
    "5. ЗАПРЕЩЕНО выдумывать несуществующие ID задач.\n"
    "   Используй СТРОГО те ID, которые уже есть в состоянии проекта "
    "(перечислены выше). Если ты не видишь задачу в ТЕКУЩЕМ СОСТОЯНИИ ПРОЕКТА — "
    "её не существует, не ссылайся на неё в predecessors."
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

        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tasks_json=tasks_json)
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