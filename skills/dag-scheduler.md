---
description: Правила работы с графом зависимостей и расчётом дат Гантта
globs: backend/app/services/scheduler.py, backend/app/mcp_server.py
---
При любом редактировании зависимостей или длительности задач:
- Всегда проверяй граф на циклические зависимости (A -> B -> A).
- При обнаружении цикла выбрасывай custom exception `CyclicDependencyError`.
- Всегда используй топологическую сортировку (Kahn's algorithm или DFS) для расчета дат.