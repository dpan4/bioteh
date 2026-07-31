/**
 * API-клиент для взаимодействия с бэкендом AI-Native Gantt Chart.
 *
 * ВСЕ ответы, содержащие задачи, валидируются через z.array(GanttTaskSchema).parse()
 * (system.md, инвариант 3 — строгая валидация). ZodError и HTTP-ошибки конвертируются
 * в читаемый Error — UI ловит их и показывает Toast, НЕ падая белым экраном.
 *
 * Фронтенд не конвертирует ключи (camelCase/snake_case): бэкенд отдаёт camelCase
 * через Pydantic alias_generator=to_camel (architecture.md, раздел 2.3).
 */

import { z } from "zod";
import { GanttTaskSchema, type GanttTask } from "../schemas/task";

/**
 * Базовый URL API.
 *
 * Через Vite dev-сервер проксируются запросы с /api на http://localhost:8000/api.
 * При прямом подключении без прокси можно указать полный URL:
 *   BASE_URL = "http://localhost:8000/api"
 */
const BASE_URL = "/api";

/** Zod-схема для валидации массива GanttTask. */
const GanttTaskArraySchema = z.array(GanttTaskSchema);

/** Zod-схема для валидации ответа чата. */
const ChatResponseSchema = z.object({
  reply: z.string(),
  tasks: GanttTaskArraySchema,
});

/* ═══════════════════════════════════════════════════════════════════════════
 * Внутренние утилиты
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Извлекает человекочитаемое сообщение об ошибке из ответа API.
 *
 * Пробует распарсить JSON и взять поле detail (FastAPI HTTPException),
 * иначе возвращает statusText или общее сообщение.
 */
async function extractApiError(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string" && body.detail.length > 0) {
      return body.detail;
    }
    if (typeof body.detail === "object" && Array.isArray(body.detail)) {
      return body.detail
        .map(
          (e: { msg?: string; loc?: string[] }) =>
            e.msg || JSON.stringify(e)
        )
        .join("; ");
    }
    return JSON.stringify(body);
  } catch {
    return response.statusText || `HTTP ${response.status}`;
  }
}

/**
 * Формирует читаемое сообщение из ZodError.
 */
function formatZodError(error: z.ZodError): string {
  return error.issues
    .map(
      (issue) =>
        `${issue.path.length > 0 ? issue.path.join(".") + ": " : ""}${issue.message}`
    )
    .join("; ");
}

/**
 * Выполняет fetch-запрос, парсит JSON и валидирует его через переданную Zod-схему.
 *
 * При HTTP-ошибке выбрасывает Error с detail из ответа API.
 * При ZodError выбрасывает Error с человекочитаемым списком проблем.
 * При сетевой ошибке выбрасывает Error с понятным сообщением.
 */
async function fetchValidated<T>(
  url: string,
  schema: z.ZodType<T>,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${url}`, init);
  } catch {
    throw new Error(
      "Не удалось подключиться к серверу. Проверьте, что бэкенд запущен на порту 8000.",
    );
  }

  if (!response.ok) {
    const detail = await extractApiError(response);
    throw new Error(detail || `Ошибка сервера (${response.status})`);
  }

  let data: unknown;
  try {
    data = await response.json();
  } catch {
    throw new Error("Сервер вернул некорректный JSON. Попробуйте позже.");
  }

  try {
    return schema.parse(data);
  } catch (error) {
    if (error instanceof z.ZodError) {
      throw new Error(
        `Ошибка валидации данных от сервера: ${formatZodError(error)}`,
      );
    }
    throw error;
  }
}

/* ═══════════════════════════════════════════════════════════════════════════
 * Публичные методы API
 * ═══════════════════════════════════════════════════════════════════════════ */

/**
 * Получает список всех задач с датами, рассчитанными DAG Scheduler.
 *
 * Если бэкенд ещё не инициализирован — автоматически загружает seed-данные
 * (5 задач с реалистичными зависимостями).
 *
 * @returns Массив GanttTask в топологическом порядке.
 * @throws {Error} При ошибке сети, HTTP-ошибке или невалидном ответе (ZodError).
 */
export async function getTasks(): Promise<GanttTask[]> {
  return fetchValidated("/tasks", GanttTaskArraySchema);
}

/**
 * Загружает Excel-файл (.xlsx) и заменяет весь проект новыми задачами.
 *
 * Отправляет multipart/form-data с файлом. Бэкенд парсит Excel через openpyxl,
 * сохраняет задачи в хранилище и пересчитывает расписание.
 *
 * @param file — Файл Excel (.xlsx), выбранный пользователем через <input type="file">.
 * @returns Обновлённый массив GanttTask с пересчитанными датами.
 * @throws {Error} При ошибке парсинга Excel (ValueError), цикле зависимостей
 *                 (CyclicDependencyError), ошибке сети или невалидном ответе.
 */
export async function uploadExcel(file: File): Promise<GanttTask[]> {
  if (file.size === 0) {
    throw new Error("Выбран пустой файл. Загрузите корректный Excel-файл (.xlsx).");
  }
  const maxSize = 10 * 1024 * 1024;
  if (file.size > maxSize) {
    throw new Error(
      `Размер файла (${(file.size / 1024 / 1024).toFixed(1)} МБ) превышает лимит 10 МБ.`,
    );
  }

  const formData = new FormData();
  formData.append("file", file, file.name);

  return fetchValidated("/tasks/upload", GanttTaskArraySchema, {
    method: "POST",
    body: formData,
  });
}

/**
 * Скачивает текущее расписание проекта в виде Excel-файла (.xlsx).
 *
 * Браузер автоматически сохраняет файл как gantt_plan.xlsx через
 * программный клик по временной ссылке.
 *
 * @throws {Error} При ошибке сети или если бэкенд не смог сформировать файл.
 */
export async function exportExcel(): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}/tasks/export`);
  } catch {
    throw new Error(
      "Не удалось подключиться к серверу для скачивания файла.",
    );
  }

  if (!response.ok) {
    const detail = await extractApiError(response);
    throw new Error(detail || "Не удалось сформировать Excel-файл.");
  }

  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = "gantt_plan.xlsx";
  document.body.appendChild(anchor);
  anchor.click();
  document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

/**
 * Отправляет сообщение в чат с AI-ассистентом и получает текстовый ответ
 * вместе с обновлённым списком задач.
 *
 * Бэкенд передаёт сообщение LLM через OpenRouter. Если LLM вызывает инструменты
 * (MCP: update_task_details, add_new_task, delete_tasks), мутации применяются
 * над TaskStore, даты пересчитываются DAG Scheduler.
 *
 * @param message — Текст сообщения пользователя (на русском или английском).
 * @returns Объект с текстовым ответом AI и обновлённым списком задач.
 * @throws {Error} При ошибке сети, HTTP-ошибке (LLM недоступен, цикл
 *                 зависимостей) или невалидном ответе (ZodError).
 */
export async function sendChatMessage(
  message: string,
): Promise<{ reply: string; tasks: GanttTask[] }> {
  if (message.trim().length === 0) {
    throw new Error("Сообщение не может быть пустым.");
  }

  return fetchValidated("/chat", ChatResponseSchema, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message }),
  });
}