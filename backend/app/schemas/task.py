"""Pydantic v2-схемы контракта данных задач диаграммы Гантта.

ВАЖНО (system.md, инвариант 2 — зеркалирование контрактов):
Этот файл строго зеркалит ``frontend/src/schemas/task.ts`` (Zod).
Любое изменение полей задачи должно вноситься ОДНОВРЕМЕННО в оба файла.

Именование: внутри Python — snake_case (duration_days, start_date, end_date),
по проводу API — camelCase через alias_generator=to_camel
(architecture.md, раздел 2.3). Сериализация ответов API выполняется
с by_alias=True (или response_model_by_alias=True в FastAPI).

Каждое поле снабжено description на русском языке с примером в examples —
это критично для корректного LLM Tool Calling (skills/zod-sync.md).
"""

from datetime import date

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class RawTask(BaseModel):
    """Исходная задача БЕЗ дат.

    Поступает из Excel-парсера (openpyxl), seed-данных или мутаций LLM
    (MCP-инструменты). Дат не содержит: start_date/end_date вычисляет
    ТОЛЬКО DAG Scheduler (backend/app/services/scheduler.py) —
    system.md, инвариант 1 (единый источник расчёта дат).
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    id: str = Field(
        min_length=1,
        description='Уникальный идентификатор задачи. Пример: "task-1"',
        examples=["task-1"],
    )
    title: str = Field(
        min_length=1,
        description='Название задачи. Пример: "Проектирование БД"',
        examples=["Проектирование БД"],
    )
    description: str = Field(
        description=(
            "Подробное описание задачи (может быть пустой строкой). "
            'Пример: "Спроектировать схему PostgreSQL"'
        ),
        examples=["Спроектировать схему PostgreSQL"],
    )
    assignee: str = Field(
        description=(
            'Исполнитель задачи (может быть пустой строкой). Пример: "Дмитрий Пан"'
        ),
        examples=["Дмитрий Пан"],
    )
    duration_days: int = Field(
        ge=1,
        description=(
            "Длительность задачи в рабочих днях, целое число не меньше 1. Пример: 5"
        ),
        examples=[5],
    )
    predecessors: list[str] = Field(
        description=(
            "Список id задач-предшественников (может быть пустым списком). "
            'Пример: ["task-1", "task-2"]'
        ),
        examples=[["task-1", "task-2"]],
    )
    preferred_start_date: str | None = Field(
        default=None,
        min_length=10,
        max_length=10,
        description=(
            "Желаемая дата начала задачи в формате YYYY-MM-DD. "
            "Используется ТОЛЬКО если задача не имеет предшественников (predecessors пуст). "
            "Если указана — планировщик ставит задачу строго на эту дату. "
            "Если задача имеет предшественники — поле игнорируется. "
            'Пример: "2026-09-04"'
        ),
        examples=["2026-09-04"],
    )


class GanttTask(RawTask):
    """Задача с рассчитанными датами.

    Расширяет RawTask полями start_date и end_date, которые заполняет
    ТОЛЬКО backend/app/services/scheduler.py. Ни фронтенд, ни LLM-промпты,
    ни MCP-инструменты не вычисляют эти даты самостоятельно.

    Единственный формат данных, отдаваемый API фронтенду для Gantt UI;
    поле date сериализуется Pydantic в ISO-строку YYYY-MM-DD.
    """

    start_date: date = Field(
        description=(
            "Дата начала задачи в формате ISO YYYY-MM-DD, рассчитана DAG Scheduler "
            'на бэкенде. Пример: "2026-08-03"'
        ),
        examples=["2026-08-03"],
    )
    end_date: date = Field(
        description=(
            "Дата окончания задачи в формате ISO YYYY-MM-DD "
            "(start_date + duration_days - 1), рассчитана DAG Scheduler на бэкенде. "
            'Пример: "2026-08-07"'
        ),
        examples=["2026-08-07"],
    )
