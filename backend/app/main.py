"""Точка входа FastAPI-приложения AI-Native Gantt Chart.

Инициализирует приложение, подключает CORS и регистрирует роутеры.

Запуск:
    uvicorn app.main:app --app-dir backend --reload --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Загружаем переменные из .env в os.environ ДО импорта роутеров.
# override=True гарантирует, что .env перебивает системные переменные окружения.
load_dotenv(override=True)

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routers.chat import router as chat_router
from app.routers.tasks import router as tasks_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    yield
    from app.services.llm_client import _client_instance
    if _client_instance is not None:
        await _client_instance.close()


app = FastAPI(
    title="AI-Native Gantt Chart",
    description=(
        "REST API для управления диаграммой Гантта с поддержкой AI Tool Calling "
        "через OpenRouter. Загрузка Excel, расчёт дат (DAG Scheduler), "
        "мутация задач через чат с LLM."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(tasks_router)
app.include_router(chat_router)


@app.get("/api/health")
def health_check() -> dict[str, str]:
    """Проверка доступности API."""
    return {"status": "ok"}