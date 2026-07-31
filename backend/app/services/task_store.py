"""In-Memory хранилище задач проекта (module-level singleton).

Запоминает текущий набор RawTask[] и базовую дату старта проекта.
Даты вычисляются ТОЛЬКО через scheduler.py (system.md, инвариант 1);
TaskStore — это хранилище состояния, а не логики расчёта.

Содержит seed-данные (5 реалистичных задач с зависимостями) для старта
приложения без загрузки Excel.
"""

from datetime import date

from app.schemas.task import GanttTask, RawTask
from app.services.scheduler import CyclicDependencyError, calculate_schedule


def _build_seed() -> list[RawTask]:
    """Стартовый демо-набор задач с логичными зависимостями.

    Структура (диаграмма зависимостей):
        task-1 (Анализ требований)
            │
        task-2 (Проектирование БД)
            │
            ├── task-3 (Разработка API)
            │        │
            │        ├── task-5 (Тестирование)
            │
            └── task-4 (Верстка UI) ──┘

    task-5 ждёт завершения обоих параллельных путей (3 и 4).
    """
    return [
        RawTask(
            id="task-1",
            title="Анализ требований",
            description="Сбор и документирование функциональных и нефункциональных требований к системе.",
            assignee="Анна",
            duration_days=5,
            predecessors=[],
        ),
        RawTask(
            id="task-2",
            title="Проектирование БД",
            description="Проектирование схемы PostgreSQL: таблицы, индексы, связи, миграции.",
            assignee="Дмитрий Пан",
            duration_days=4,
            predecessors=["task-1"],
        ),
        RawTask(
            id="task-3",
            title="Разработка API",
            description="Реализация REST API на FastAPI: роутеры, валидация, аутентификация.",
            assignee="Сергей",
            duration_days=7,
            predecessors=["task-2"],
        ),
        RawTask(
            id="task-4",
            title="Верстка UI",
            description="Верстка React-компонентов диаграммы Гантта, чата и панели загрузки.",
            assignee="Елена",
            duration_days=6,
            predecessors=["task-2"],
        ),
        RawTask(
            id="task-5",
            title="Тестирование",
            description="Интеграционное и E2E-тестирование API и фронтенда, проверка MCP-инструментов.",
            assignee="Анна",
            duration_days=4,
            predecessors=["task-3", "task-4"],
        ),
    ]


class TaskStore:
    """In-memory хранилище задач с ленивой инициализацией seed-данных.

    Синглтон-экземпляр создаётся на уровне модуля (переменная ``store``),
    поэтому все компоненты приложения разделяют одно состояние.

    Attributes:
        _raw_tasks: Текущий список задач без дат.
        _project_start_date: Базовая дата проекта (по умолчанию — сегодня).
    """

    def __init__(self) -> None:
        self._raw_tasks: list[RawTask] = []
        self._project_start_date: date = date.today()

    def _ensure_seeded(self) -> None:
        """Ленивая инициализация: если задач нет — заполняем seed-данными."""
        if not self._raw_tasks:
            for task in _build_seed():
                self._raw_tasks.append(task)

    def get_gantt_tasks(self) -> list[GanttTask]:
        """Возвращает список задач с датами, рассчитанными DAG Scheduler.

        Если хранилище пустое — автоматически заполняется seed-данными.

        Returns:
            Список GanttTask в топологическом порядке.

        Raises:
            CyclicDependencyError: Если граф содержит цикл (не ожидается
                для seed-данных, но возможно после внешней мутации).
        """
        self._ensure_seeded()
        return calculate_schedule(self._raw_tasks, self._project_start_date)

    def set_raw_tasks(self, tasks: list[RawTask]) -> list[GanttTask]:
        """Заменяет весь набор задач и пересчитывает расписание.

        Args:
            tasks: Новый список задач без дат (например, из Excel-файла).

        Returns:
            Обновлённый список GanttTask с пересчитанными датами.

        Raises:
            CyclicDependencyError: Если в новом наборе задач обнаружен цикл.
            ValueError: Если есть дубли ID или ссылки на несуществующих
                предшественников.
        """
        scheduled = calculate_schedule(tasks, self._project_start_date)
        self._raw_tasks = list(tasks)
        return scheduled

    def get_raw_tasks(self) -> list[RawTask]:
        """Возвращает сырые задачи без дат (текущее состояние проекта)."""
        return list(self._raw_tasks)


# Синглтон-экземпляр: все модули бэкенда импортируют ``store`` из этого файла.
store = TaskStore()