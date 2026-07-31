"""Excel-парсер и экспортер задач диаграммы Гантта (openpyxl).

Модуль отвечает ТОЛЬКО за преобразование данных:
- parse_excel(): байты .xlsx -> list[RawTask] (БЕЗ дат — даты вычисляет
  исключительно backend/app/services/scheduler.py, system.md, инвариант 1);
- generate_excel(): list[GanttTask] -> байты .xlsx с готовым расписанием.

Ожидаемый формат входного файла: первая строка — шапка с названиями колонок
(регистр и лишние пробелы игнорируются), далее — по одной задаче на строку.

Поддерживаемые названия колонок (русский или английский вариант):
- "задача" или "title"                 -> title (обязательная)
- "описание" или "description"         -> description
- "исполнитель" или "assignee"         -> assignee
- "длительность" или "duration_days"   -> duration_days (обязательная, int >= 1)
- "предшественники" или "predecessors" -> predecessors ("task-1, task-2" -> list)
- "id" или "ид"                        -> id (опциональная; если колонки нет
  или ячейка пуста — id генерируется автоматически: task-1, task-2, ...)
"""

import io
import re
from typing import Any

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import ValidationError

from app.schemas.task import GanttTask, RawTask

# Маппинг нормализованного названия колонки Excel -> внутреннее имя поля.
_COLUMN_ALIASES: dict[str, str] = {
    "задача": "title",
    "title": "title",
    "описание": "description",
    "description": "description",
    "исполнитель": "assignee",
    "assignee": "assignee",
    "длительность": "duration_days",
    "длительность (дни)": "duration_days",
    "duration_days": "duration_days",
    "предшественники": "predecessors",
    "predecessors": "predecessors",
    "id": "id",
    "ид": "id",
}

# Поля, без которых распарсить задачу невозможно.
_REQUIRED_FIELDS: dict[str, str] = {
    "title": '"Задача" / "title"',
    "duration_days": '"Длительность" / "duration_days"',
}

# Колонки выходного Excel-файла: (заголовок, ширина колонки).
_EXPORT_COLUMNS: list[tuple[str, int]] = [
    ("Задача", 30),
    ("Описание", 45),
    ("Исполнитель", 20),
    ("Длительность (дни)", 18),
    ("Дата начала", 14),
    ("Дата окончания", 16),
    ("Предшественники", 25),
]


def _normalize_header(value: Any) -> str:
    """Приводит название колонки к нормализованному виду.

    Args:
        value: Сырое значение ячейки шапки.

    Returns:
        Название колонки в нижнем регистре без лишних пробелов.
    """
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip().lower()


def _cell_to_str(value: Any) -> str:
    """Преобразует значение ячейки в строку.

    Args:
        value: Сырое значение ячейки.

    Returns:
        Строка без обрамляющих пробелов; пустая строка для None.
    """
    if value is None:
        return ""
    return str(value).strip()


def _parse_duration(value: Any, row_number: int) -> int:
    """Преобразует значение ячейки длительности в int >= 1.

    Excel часто хранит целые числа как float (5.0), поэтому такие значения
    принимаются, если дробная часть нулевая.

    Args:
        value: Сырое значение ячейки длительности.
        row_number: Номер строки Excel (для сообщения об ошибке).

    Returns:
        Длительность задачи в рабочих днях.

    Raises:
        ValueError: Если значение пустое, не число, не целое или меньше 1.
    """
    text = _cell_to_str(value)
    if text == "":
        raise ValueError(
            f"Строка {row_number}: не заполнена длительность задачи. "
            "Укажите целое число рабочих дней (не меньше 1)."
        )
    try:
        numeric = float(text.replace(",", "."))
    except (TypeError, ValueError):
        raise ValueError(
            f"Строка {row_number}: длительность '{text}' не является числом. "
            "Укажите целое число рабочих дней (не меньше 1)."
        )
    if not numeric.is_integer():
        raise ValueError(
            f"Строка {row_number}: длительность '{text}' должна быть целым "
            "числом рабочих дней."
        )
    duration = int(numeric)
    if duration < 1:
        raise ValueError(
            f"Строка {row_number}: длительность должна быть не меньше 1 дня, "
            f"получено {duration}."
        )
    return duration


def _parse_predecessors(value: Any) -> list[str]:
    """Разбирает строку с ID предшественников в список.

    Поддерживаются разделители запятая и точка с запятой:
    "task-1, task-2" или "task-1; task-2" -> ["task-1", "task-2"].

    Args:
        value: Сырое значение ячейки предшественников.

    Returns:
        Список ID задач-предшественников (возможно пустой).
    """
    text = _cell_to_str(value)
    if text == "":
        return []
    return [part.strip() for part in re.split(r"[;,]", text) if part.strip()]


def parse_excel(file_bytes: bytes) -> list[RawTask]:
    """Читает .xlsx-файл и возвращает список задач без дат.

    Args:
        file_bytes: Содержимое Excel-файла (.xlsx) в виде байтов.

    Returns:
        Список валидированных RawTask в порядке строк файла. Даты задач
        НЕ вычисляются — это делает только scheduler.py.

    Raises:
        ValueError: Если файл повреждён или не является .xlsx, отсутствуют
            обязательные колонки, встречены невалидные значения
            или дублирующиеся ID задач.
    """
    try:
        workbook = load_workbook(
            io.BytesIO(file_bytes), read_only=True, data_only=True
        )
    except Exception as exc:
        raise ValueError(
            "Не удалось открыть Excel-файл: файл повреждён или имеет "
            f"неподдерживаемый формат (ожидается .xlsx). Детали: {exc}"
        ) from exc

    try:
        worksheet = workbook.active
        if worksheet is None:
            raise ValueError("Excel-файл не содержит ни одного листа.")

        rows = worksheet.iter_rows(values_only=True)
        try:
            header_row = next(rows)
        except StopIteration:
            raise ValueError(
                "Excel-файл пуст: отсутствует строка с названиями колонок."
            )

        # Индекс колонки -> внутреннее имя поля.
        column_map: dict[int, str] = {}
        for index, raw_header in enumerate(header_row):
            field = _COLUMN_ALIASES.get(_normalize_header(raw_header))
            if field is not None and field not in column_map.values():
                column_map[index] = field

        mapped_fields = set(column_map.values())
        missing = [
            label
            for field, label in _REQUIRED_FIELDS.items()
            if field not in mapped_fields
        ]
        if missing:
            raise ValueError(
                "В Excel-файле отсутствуют обязательные колонки: "
                f"{', '.join(missing)}. Проверьте первую строку файла."
            )

        tasks: list[RawTask] = []
        used_ids: set[str] = set()
        auto_id_counter = 0

        for row_number, row in enumerate(rows, start=2):
            values: dict[str, Any] = {
                field: row[index] if index < len(row) else None
                for index, field in column_map.items()
            }

            title = _cell_to_str(values.get("title"))
            other_cells_empty = all(
                _cell_to_str(values.get(field)) == ""
                for field in ("description", "assignee", "duration_days",
                              "predecessors", "id")
            )
            if title == "" and other_cells_empty:
                continue  # Полностью пустая строка — пропускаем.
            if title == "":
                raise ValueError(
                    f"Строка {row_number}: не заполнено название задачи "
                    '(колонка "Задача" / "title").'
                )

            task_id = _cell_to_str(values.get("id"))
            if task_id == "":
                auto_id_counter += 1
                task_id = f"task-{auto_id_counter}"
                while task_id in used_ids:
                    auto_id_counter += 1
                    task_id = f"task-{auto_id_counter}"
            if task_id in used_ids:
                raise ValueError(
                    f"Строка {row_number}: дублирующийся идентификатор задачи "
                    f"'{task_id}'. Каждая задача должна иметь уникальный id."
                )
            used_ids.add(task_id)

            try:
                task = RawTask(
                    id=task_id,
                    title=title,
                    description=_cell_to_str(values.get("description")),
                    assignee=_cell_to_str(values.get("assignee")),
                    duration_days=_parse_duration(
                        values.get("duration_days"), row_number
                    ),
                    predecessors=_parse_predecessors(values.get("predecessors")),
                )
            except ValidationError as exc:
                raise ValueError(
                    f"Строка {row_number}: данные задачи не прошли валидацию. "
                    f"Детали: {exc}"
                ) from exc

            tasks.append(task)

        if not tasks:
            raise ValueError(
                "Excel-файл не содержит ни одной задачи: заполните строки "
                "под шапкой таблицы."
            )

        return tasks
    finally:
        workbook.close()


def generate_excel(tasks: list[GanttTask]) -> bytes:
    """Формирует .xlsx-файл с рассчитанным расписанием проекта.

    Args:
        tasks: Список задач с датами, рассчитанными DAG Scheduler.

    Returns:
        Содержимое Excel-файла в виде байтов (файл формируется в памяти
        через io.BytesIO, на диск ничего не записывается).
    """
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "График проекта"

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(
        start_color="4472C4", end_color="4472C4", fill_type="solid"
    )

    for column_index, (header, width) in enumerate(_EXPORT_COLUMNS, start=1):
        cell = worksheet.cell(row=1, column=column_index, value=header)
        cell.font = header_font
        cell.fill = header_fill
        worksheet.column_dimensions[get_column_letter(column_index)].width = width

    worksheet.freeze_panes = "A2"

    for row_index, task in enumerate(tasks, start=2):
        row_values: list[Any] = [
            task.title,
            task.description,
            task.assignee,
            task.duration_days,
            task.start_date.isoformat(),
            task.end_date.isoformat(),
            ", ".join(task.predecessors),
        ]
        for column_index, value in enumerate(row_values, start=1):
            worksheet.cell(row=row_index, column=column_index, value=value)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
