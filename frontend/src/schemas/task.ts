import { z } from "zod";

/**
 * Zod-схемы контракта данных задач диаграммы Гантта.
 *
 * ВАЖНО (system.md, инвариант 2 — зеркалирование контрактов):
 * Этот файл строго зеркалит `backend/app/schemas/task.py` (Pydantic v2).
 * Любое изменение полей задачи должно вноситься ОДНОВРЕМЕННО в оба файла.
 *
 * Именование: фронтенд — camelCase (durationDays, startDate, endDate),
 * бэкенд — snake_case; по проводу API ходит camelCase (Pydantic aliases).
 *
 * Каждое поле снабжено `.describe()` на русском языке с примером —
 * это критично для корректного LLM Tool Calling (skills/zod-sync.md).
 */

/** Регулярное выражение для ISO-даты формата YYYY-MM-DD (например, "2026-08-03"). */
const ISO_DATE_REGEX = /^\d{4}-\d{2}-\d{2}$/;

/**
 * RawTaskSchema — исходная задача БЕЗ дат.
 *
 * Поступает из Excel-парсера, seed-данных или мутаций LLM (MCP-инструменты).
 * Дат не содержит: startDate/endDate вычисляет ТОЛЬКО DAG Scheduler на бэкенде
 * (system.md, инвариант 1 — единый источник расчёта дат).
 */
export const RawTaskSchema = z.object({
  id: z
    .string()
    .min(1)
    .describe('Уникальный идентификатор задачи. Пример: "task-1"'),
  title: z
    .string()
    .min(1)
    .describe('Название задачи. Пример: "Проектирование БД"'),
  description: z
    .string()
    .describe(
      'Подробное описание или детали задачи. Если пользователь указал детали, контекст или явное описание в запросе — ты ОБЯЗАН передать этот текст сюда. Пример: "Спроектировать схему PostgreSQL"'
    ),
  assignee: z
    .string()
    .describe(
      'Исполнитель задачи (может быть пустой строкой). Пример: "Дмитрий Пан"'
    ),
  durationDays: z
    .number()
    .int()
    .min(1)
    .describe("Длительность задачи в рабочих днях, целое число не меньше 1. Пример: 5"),
  predecessors: z
    .array(z.string())
    .describe(
      'Список id задач-предшественников (может быть пустым массивом). Пример: ["task-1", "task-2"]'
    ),
  preferredStartDate: z
    .string()
    .regex(ISO_DATE_REGEX)
    .nullable()
    .optional()
    .describe(
      'Желаемая дата начала задачи YYYY-MM-DD (только для задач без предшественников). Пример: "2026-09-04"'
    ),
});

/**
 * GanttTaskSchema — задача с рассчитанными датами.
 *
 * Расширяет RawTaskSchema полями startDate и endDate, которые заполняет
 * ТОЛЬКО backend/app/services/scheduler.py. Фронтенд эти даты не вычисляет
 * и не изменяет — только валидирует и отображает.
 *
 * Все ответы API/LLM валидируются через `GanttTaskSchema.array().parse()`
 * в try-catch; при ошибке валидации UI показывает Toast и не падает
 * (system.md, инвариант 3).
 */
export const GanttTaskSchema = RawTaskSchema.extend({
  startDate: z
    .string()
    .regex(ISO_DATE_REGEX)
    .describe(
      'Дата начала задачи в формате ISO YYYY-MM-DD, рассчитана DAG Scheduler на бэкенде. Пример: "2026-08-03"'
    ),
  endDate: z
    .string()
    .regex(ISO_DATE_REGEX)
    .describe(
      'Дата окончания задачи в формате ISO YYYY-MM-DD (startDate + durationDays - 1), рассчитана DAG Scheduler на бэкенде. Пример: "2026-08-07"'
    ),
});

/** Исходная задача без дат (вход парсера, seed-данных и MCP-мутаций). */
export type RawTask = z.infer<typeof RawTaskSchema>;

/** Задача с рассчитанными датами (единственный формат данных для Gantt UI). */
export type GanttTask = z.infer<typeof GanttTaskSchema>;
