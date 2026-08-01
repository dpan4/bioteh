"""API-роутер для работы с задачами диаграммы Гантта.

Эндпоинты:
  GET  /api/tasks          — список задач с датами (seed при пустом хранилище).
  POST /api/tasks/upload    — загрузка Excel-файла, замена состояния.
  GET  /api/tasks/export    — скачать заполненный .xlsx с расписанием (8 колонок).
  GET  /api/tasks/template  — скачать эталонный шаблон для заполнения (5 колонок).

Все ответы используют camelCase через Pydantic alias_generator=to_camel
(architecture.md, раздел 2.3). Ошибки валидации и бизнес-логики оборачиваются
в HTTPException (инвариант 3).
"""

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response

from app.services.excel_parser import (
    generate_excel,
    generate_template_excel,
    parse_excel,
)
from app.services.scheduler import CyclicDependencyError
from app.services.task_store import store

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("")
def get_tasks() -> list[dict[str, object]]:
    """Возвращает все задачи проекта с датами, рассчитанными DAG Scheduler.

    Если хранилище пустое — автоматически инициализируется seed-данными
    (5 реалистичных задач с логичными зависимостями).

    Returns:
        Список задач в camelCase JSON: id, title, description, assignee,
        durationDays, predecessors, startDate, endDate.

        Модель ответа соответствует GanttTaskSchema (frontend/src/schemas/task.ts).
    """
    try:
        tasks = store.get_gantt_tasks()
    except CyclicDependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [task.model_dump(by_alias=True, mode='json') for task in tasks]


@router.post("/upload")
async def upload_tasks(file: UploadFile = File(...)) -> list[dict[str, object]]:
    """Загружает Excel-файл (.xlsx) и заменяет весь проект новыми задачами.

    Принимает файл с шапкой: Задача/Title, Описание/Description,
    Исполнитель/Assignee, Длительность/Duration_days,
    Предшественники/Predecessors (опционально ID/Id).

    Парсинг: openpyxl (backend/app/services/excel_parser.py).
    Расчёт дат: DAG Scheduler (backend/app/services/scheduler.py).

    Args:
        file: Файл Excel (.xlsx), multipart/form-data, поле "file".

    Returns:
        Обновлённый список задач с пересчитанными датами в camelCase JSON.
    """
    content_length = (
        file.size if file.size is not None else 0
    )
    if content_length == 0:
        raise HTTPException(status_code=400, detail="Загружен пустой файл.")
    if content_length > 10 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Размер файла превышает 10 МБ. Загрузите файл меньшего размера.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Загружен пустой файл.")

    try:
        raw_tasks = parse_excel(file_bytes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        gantt_tasks = store.set_raw_tasks(raw_tasks)
    except (CyclicDependencyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return [task.model_dump(by_alias=True, mode='json') for task in gantt_tasks]


@router.get("/export")
def export_tasks() -> Response:
    """Формирует Excel-файл (.xlsx) с текущим расписанием проекта (8 колонок).

    Содержимое: столбцы ID, Задача, Описание, Исполнитель, Длительность (дни),
    Дата начала, Дата окончания, Предшественники (с датами и формулами).

    Returns:
        Response с медиатипом xlsx и заголовком Content-Disposition,
        предлагающим браузеру скачать файл как gantt_plan.xlsx.
    """
    try:
        gantt_tasks = store.get_gantt_tasks()
    except CyclicDependencyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        excel_bytes = generate_excel(gantt_tasks)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось сформировать Excel-файл: {exc}",
        ) from exc

    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=gantt_plan.xlsx"
        },
    )


@router.get("/template")
def get_template() -> Response:
    """Формирует эталонный Excel-шаблон для заполнения проекта (5 колонок).

    Содержимое: Задача, Описание, Исполнитель, Длительность (дни), Предшественники.
    БЕЗ колонок ID, Дата начала, Дата окончания (даты рассчитает бэкенд при импорте).

    Шаблон содержит 5 демо-строк с наглядными примерами заполнения:
    - Предшественники указываются как номера строк (1, 2, 3, 4), а не task-N.
    - Пользователь может очистить демо-строки и заполнить свои задачи.

    Returns:
        Response с медиатипом xlsx и заголовком Content-Disposition,
        предлагающим браузеру скачать файл как gantt_template.xlsx.
    """
    try:
        template_bytes = generate_template_excel()
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Не удалось сформировать шаблон Excel: {exc}",
        ) from exc

    return Response(
        content=template_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": "attachment; filename=gantt_template.xlsx"
        },
    )