"""DAG Scheduler — ЕДИНСТВЕННЫЙ источник расчёта дат задач (system.md, инвариант 1).

Модуль принимает список RawTask (без дат), строит направленный граф зависимостей
по полю predecessors, проверяет его на циклы и вычисляет start_date / end_date
для каждой задачи. Ни фронтенд, ни LLM-промпты, ни MCP-инструменты не вычисляют
даты самостоятельно — только через calculate_schedule().

Правила (skills/dag-scheduler.md):
- граф всегда проверяется на циклические зависимости (A -> B -> A);
- при обнаружении цикла выбрасывается CyclicDependencyError;
- порядок расчёта — топологическая сортировка (алгоритм Кана).

Используется только стандартная библиотека Python (collections, datetime).
"""

from collections import defaultdict, deque
from datetime import date, timedelta

from app.schemas.task import GanttTask, RawTask
from app.logger import logger as app_logger

ISO_DATE_FMT = "%Y-%m-%d"


class CyclicDependencyError(Exception):
    """Ошибка циклической зависимости в графе задач.

    Выбрасывается, когда задачи образуют цикл (например, task-1 зависит
    от task-2, а task-2 — от task-1), из-за чего рассчитать даты невозможно.

    Attributes:
        cycle_ids: Список ID задач, образующих цикл, в порядке обхода.
    """

    def __init__(self, cycle_ids: list[str]) -> None:
        self.cycle_ids: list[str] = cycle_ids
        cycle_path = " -> ".join(cycle_ids + cycle_ids[:1]) if cycle_ids else ""
        message = (
            "Обнаружена циклическая зависимость между задачами: "
            f"{cycle_path}. Устраните цикл в поле predecessors, "
            "чтобы рассчитать расписание."
        )
        super().__init__(message)


def _validate_tasks(tasks: list[RawTask]) -> None:
    """Проверяет корректность входных данных до построения графа.

    Args:
        tasks: Список исходных задач.

    Raises:
        ValueError: Если встречен дублирующийся ID задачи или задача
            ссылается на несуществующий predecessor_id.
    """
    seen_ids: set[str] = set()
    for task in tasks:
        if task.id in seen_ids:
            raise ValueError(
                f"Дублирующийся идентификатор задачи: '{task.id}'. "
                "Каждая задача должна иметь уникальный id."
            )
        seen_ids.add(task.id)

    for task in tasks:
        for predecessor_id in task.predecessors:
            if predecessor_id not in seen_ids:
                raise ValueError(
                    f"Задача '{task.id}' ссылается на несуществующего "
                    f"предшественника '{predecessor_id}'."
                )


def _find_cycle(
    unprocessed_ids: list[str],
    predecessors_by_id: dict[str, list[str]],
) -> list[str]:
    """Находит один конкретный цикл среди необработанных узлов графа.

    Выполняет DFS по рёбрам "задача -> её предшественник", ограничиваясь
    узлами, которые не удалось обработать алгоритмом Кана (они гарантированно
    содержат хотя бы один цикл).

    Args:
        unprocessed_ids: ID задач, не вошедших в топологический порядок.
        predecessors_by_id: Отображение ID задачи в список ID её предшественников.

    Returns:
        Список ID задач, образующих цикл, в порядке обхода.
    """
    unprocessed: set[str] = set(unprocessed_ids)
    visited: set[str] = set()
    path: list[str] = []
    on_path: set[str] = set()

    def dfs(node_id: str) -> list[str]:
        visited.add(node_id)
        path.append(node_id)
        on_path.add(node_id)
        for predecessor_id in predecessors_by_id[node_id]:
            if predecessor_id not in unprocessed:
                continue
            if predecessor_id in on_path:
                cycle_start = path.index(predecessor_id)
                return path[cycle_start:]
            if predecessor_id not in visited:
                found = dfs(predecessor_id)
                if found:
                    return found
        path.pop()
        on_path.discard(node_id)
        return []

    for start_id in unprocessed_ids:
        if start_id not in visited:
            cycle = dfs(start_id)
            if cycle:
                return cycle

    # Теоретически недостижимо: непустой остаток Кана всегда содержит цикл.
    return unprocessed_ids


def calculate_schedule(
    tasks: list[RawTask],
    project_start_date: date | None = None,
) -> list[GanttTask]:
    """Рассчитывает расписание проекта по графу зависимостей задач.

    Строит DAG по полю predecessors, выполняет топологическую сортировку
    алгоритмом Кана и вычисляет даты:
    - задача без предшественников: start_date = project_start_date;
    - задача с предшественниками: start_date = max(end_date предшественников) + 1 день;
    - end_date = start_date + duration_days - 1 (включительно).

    Формула end_date включает крайний день: задача с началом 02.08 и
    duration_days=17 заканчивается 18.08 (02 + 17 - 1 = 18).
    Следующая задача стартует на следующий день: 19.08.

    Args:
        tasks: Список исходных задач без дат.
        project_start_date: Базовая дата старта проекта. Если не передана,
            используется текущая дата (date.today()).

    Returns:
        Список GanttTask с рассчитанными датами в топологическом порядке:
        предшественники всегда идут раньше зависимых задач.

    Raises:
        CyclicDependencyError: Если граф зависимостей содержит цикл.
        ValueError: Если встречен дублирующийся ID задачи или ссылка
            на несуществующего предшественника.
    """
    if project_start_date is None:
        project_start_date = date.today()

    app_logger.info(
        "[📊 DAG ENGINE] Запущен расчет направленного ациклического графа (DAG) "
        "и критического пути..."
    )

    _validate_tasks(tasks)

    tasks_by_id: dict[str, RawTask] = {task.id: task for task in tasks}
    predecessors_by_id: dict[str, list[str]] = {
        task.id: list(task.predecessors) for task in tasks
    }

    # Рёбра графа: предшественник -> зависимые от него задачи.
    successors_by_id: defaultdict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {task.id: 0 for task in tasks}
    for task in tasks:
        for predecessor_id in task.predecessors:
            successors_by_id[predecessor_id].append(task.id)
            in_degree[task.id] += 1

    # Алгоритм Кана. Начальная очередь — в порядке исходного списка,
    # чтобы топологический порядок был детерминированным и стабильным.
    queue: deque[str] = deque(
        task.id for task in tasks if in_degree[task.id] == 0
    )
    topological_order: list[str] = []
    while queue:
        current_id = queue.popleft()
        topological_order.append(current_id)
        for successor_id in successors_by_id[current_id]:
            in_degree[successor_id] -= 1
            if in_degree[successor_id] == 0:
                queue.append(successor_id)

    if len(topological_order) != len(tasks):
        processed: set[str] = set(topological_order)
        unprocessed_ids: list[str] = [
            task.id for task in tasks if task.id not in processed
        ]
        raise CyclicDependencyError(_find_cycle(unprocessed_ids, predecessors_by_id))

    # Расчёт дат строго в топологическом порядке: к моменту обработки задачи
    # даты всех её предшественников уже вычислены.
    end_dates_by_id: dict[str, date] = {}
    scheduled_tasks: list[GanttTask] = []
    for task_id in topological_order:
        task = tasks_by_id[task_id]
        if task.predecessors:
            app_logger.info(
                "[📊 DAG ENGINE] Обнаружено ветвление графа. "
                "Корректировка дат начала по максимальной дате окончания предков."
            )
            # Начало задачи — день ПОСЛЕ окончания самого позднего предшественника.
            # end_date предшественника — последний день его работы, поэтому +1.
            predecessor_max_end = max(
                end_dates_by_id[predecessor_id]
                for predecessor_id in task.predecessors
            )
            calculated_start = predecessor_max_end + timedelta(days=1)
            
            # 🔥 НОВАЯ ЛОГИКА: Учитываем preferred_start_date даже при наличии предшественников
            # Если пользователь задал желаемую дату — берем максимум между ней и датой после предшественников
            if task.preferred_start_date:
                try:
                    preferred = date.fromisoformat(task.preferred_start_date)
                    start_date = max(calculated_start, preferred)
                except ValueError:
                    start_date = calculated_start
            else:
                start_date = calculated_start
                
        elif task.preferred_start_date:
            # Задача без предшественников, но с указанной желаемой датой начала.
            try:
                preferred = date.fromisoformat(task.preferred_start_date)
                # Берём максимум между желаемой датой и базовой датой проекта,
                # чтобы задача не начиналась раньше старта проекта.
                start_date = max(preferred, project_start_date)
            except ValueError:
                start_date = project_start_date
        else:
            start_date = project_start_date
        # end_date — последний день работы по задаче включительно.
        # Формула: end_date = start_date + duration_days - 1
        # Пример: начало 2 августа, 17 дней → конец 18 августа (2+17-1=18).
        end_date = start_date + timedelta(days=task.duration_days - 1)
        end_dates_by_id[task_id] = end_date
        scheduled_tasks.append(
            GanttTask(
                id=task.id,
                title=task.title,
                description=task.description,
                assignee=task.assignee,
                duration_days=task.duration_days,
                predecessors=list(task.predecessors),
                start_date=start_date,
                end_date=end_date,
            )
        )

    app_logger.info(
        "[📊 DAG ENGINE] SUCCESS: Граф задач успешно валидирован. "
        "Все даты зависимостей пересчитаны."
    )

    return scheduled_tasks
