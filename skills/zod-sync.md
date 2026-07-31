---
description: Правила валидации Zod и Pydantic
globs: frontend/src/schemas/*.ts, backend/app/schemas/*.py
---
Каждое поле в схемах должно содержать `.describe()` с понятным описанием на русском языке и 1 примером данных.
Это критично для того, чтобы LLM корректно вызывала Tool Calling.