import { type FC, useState } from "react";
import type { GanttTask } from "../schemas/task";
import { TaskDetailModal } from "./TaskDetailModal";

interface GanttChartProps {
  tasks: GanttTask[];
  loading: boolean;
}

const DAY_WIDTH = 36;
const ROW_HEIGHT = 48;
const SIDEBAR_WIDTH = 320;
const TIMELINE_PADDING = 16;

const COLORS = [
  "#5b6ef5",
  "#38b2ac",
  "#e070a0",
  "#f0a040",
  "#8b5cf6",
  "#06b6d4",
  "#ef4444",
  "#84cc16",
];

const textStyles = {
  sidebarCell: {
    fontSize: 12,
    color: "#c0c0d0",
    overflow: "hidden" as const,
    textOverflow: "ellipsis" as const,
    whiteSpace: "nowrap" as const,
  },
  sidebarTitle: {
    fontSize: 13,
    color: "#f0f0f8",
    fontWeight: 600,
    overflow: "hidden" as const,
    textOverflow: "ellipsis" as const,
    whiteSpace: "nowrap" as const,
  },
};

function parseDate(iso: string): Date {
  const d = new Date(iso);
  if (isNaN(d.getTime())) {
    return new Date();
  }
  return d;
}

function daysBetween(a: Date, b: Date): number {
  const ms = b.getTime() - a.getTime();
  return Math.round(ms / (1000 * 60 * 60 * 24));
}

function formatDateISO(iso: string): string {
  const d = parseDate(iso);
  const day = String(d.getDate()).padStart(2, "0");
  const month = String(d.getMonth() + 1).padStart(2, "0");
  return `${day}.${month}`;
}

function formatDateFull(iso: string): string {
  return iso;
}

export const GanttChart: FC<GanttChartProps> = ({ tasks, loading }) => {
  const [selectedTask, setSelectedTask] = useState<GanttTask | null>(null);

  console.log("[GanttChart] Рендер с", tasks.length, "задачами, loading:", loading);

  if (loading) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 300, color: "#8a8aaa", fontSize: 15 }}>
        <span style={{ marginRight: 8 }}>Загрузка расписания</span>
        <span className="dots" />
        <style>{`.dots::after { content: ''; animation: dotPulse 1.4s infinite; } @keyframes dotPulse { 0% { content: '.'; } 33% { content: '..'; } 66% { content: '...'; } 100% { content: '.'; } }`}</style>
      </div>
    );
  }

  if (tasks.length === 0) {
    return (
      <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", alignItems: "center", height: 300, color: "#6a6a8a", gap: 12 }}>
        <span style={{ fontSize: 40, opacity: 0.4 }}>&#9783;</span>
        <span style={{ fontSize: 16, fontWeight: 600 }}>Нет задач</span>
        <span style={{ fontSize: 13 }}>
          Загрузите Excel-файл или начните новый проект через чат с AI
        </span>
      </div>
    );
  }

  const startDates = tasks.map((t) => parseDate(t.startDate));
  const endDates = tasks.map((t) => parseDate(t.endDate));
  const timelineStart = new Date(Math.min(...startDates.map((d) => d.getTime())));
  const timelineEnd = new Date(Math.max(...endDates.map((d) => d.getTime())));
  const totalDays = daysBetween(timelineStart, timelineEnd);

  if (totalDays <= 0) {
    return (
      <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 200, color: "#8a8aaa", fontSize: 14 }}>
        Некорректный диапазон дат: все задачи имеют одинаковые даты начала и окончания.
      </div>
    );
  }

  const timelineWidth = totalDays * DAY_WIDTH;
  const timelineDates: Date[] = [];
  for (let i = 0; i <= totalDays; i++) {
    const d = new Date(timelineStart);
    d.setDate(d.getDate() + i);
    timelineDates.push(d);
  }

  const todayOffset = daysBetween(timelineStart, new Date());

  return (
    <div style={{ display: "flex", flexDirection: "column", border: "1px solid #333", borderRadius: 8, background: "#1a1a28" }}>
      {/* Скроллируемая область */}
      <div style={{ overflow: "auto", maxHeight: "calc(100vh - 300px)" }}>
        <div style={{ minWidth: SIDEBAR_WIDTH + TIMELINE_PADDING + (totalDays + 1) * DAY_WIDTH }}>
        {/* Заголовок колонок — sticky top */}
        <div style={{ display: "flex", background: "#232336", fontSize: 12, fontWeight: 600, color: "#a0a0c0", position: "sticky", top: 0, zIndex: 10, borderBottom: "1px solid #333" }}>
          <div style={{ width: SIDEBAR_WIDTH, flexShrink: 0, padding: "8px 12px", borderRight: "1px solid #333", display: "flex", alignItems: "center", gap: 8, position: "sticky", left: 0, zIndex: 11, background: "#232336" }}>
            <span style={{ fontSize: 16 }}>&#9776;</span>
            <span>Задача</span>
          </div>
          <div style={{ flex: 1, position: "relative" }}>
            <div style={{ display: "flex", height: 40, alignItems: "center", paddingLeft: TIMELINE_PADDING }}>
              <div style={{ display: "flex", marginLeft: -DAY_WIDTH / 4 }}>
                {timelineDates.map((d, i) => (
                  <div
                    key={i}
                    style={{
                      width: DAY_WIDTH,
                      textAlign: "center",
                      flexShrink: 0,
                      fontSize: 10,
                      color: i % 7 < 5 ? "#808090" : "#555",
                    }}
                  >
                    {String(d.getDate()).padStart(2, "0")}.{String(d.getMonth() + 1).padStart(2, "0")}
                  </div>
                ))}
              </div>
            </div>
            {/* Линия сегодня */}
            {todayOffset >= 0 && todayOffset <= totalDays && (
              <div
                style={{
                  position: "absolute",
                  top: 0,
                  bottom: 0,
                  left: todayOffset * DAY_WIDTH + DAY_WIDTH / 2 + TIMELINE_PADDING,
                  width: 2,
                  background: "#ef4444",
                  opacity: 0.6,
                  zIndex: 2,
                }}
              />
            )}
          </div>
        </div>

        {/* Строки задач */}
        {tasks.map((task, taskIndex) => {
          const taskStart = parseDate(task.startDate);
          const taskEnd = parseDate(task.endDate);
          const offset = daysBetween(timelineStart, taskStart);
          const width = Math.max(daysBetween(taskStart, taskEnd), 1);
          const color = COLORS[taskIndex % COLORS.length];

          return (
            <div
              key={task.id}
              style={{
                display: "flex",
                borderBottom: "1px solid #272738",
                background: taskIndex % 2 === 0 ? "#1e1e30" : "#1a1a28",
                minHeight: ROW_HEIGHT,
              }}
            >
              {/* Боковая панель задачи — sticky left */}
              <div
                style={{
                  width: SIDEBAR_WIDTH,
                  flexShrink: 0,
                  padding: "6px 12px",
                  borderRight: "1px solid #333",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "center",
                  gap: 2,
                  cursor: "pointer",
                  transition: "background 0.15s",
                  position: "sticky",
                  left: 0,
                  zIndex: 5,
                  background: taskIndex % 2 === 0 ? "#1e1e30" : "#1a1a28",
                }}
                onClick={() => setSelectedTask(task)}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = "#252540";
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = taskIndex % 2 === 0 ? "#1e1e30" : "#1a1a28";
                }}
                title="Нажмите, чтобы открыть детали задачи"
              >
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <span style={{ fontSize: 10, color: color, fontWeight: 700 }}>{task.id}</span>
                  <span style={textStyles.sidebarTitle}>{task.title}</span>
                </div>
                {task.assignee && (
                  <span style={textStyles.sidebarCell}>
                    {task.assignee} &middot; {task.durationDays} дн.
                  </span>
                )}
                {!task.assignee && (
                  <span style={textStyles.sidebarCell}>{task.durationDays} дн.</span>
                )}
              </div>

              {/* Таймлайн */}
              <div style={{ flex: 1, position: "relative", paddingLeft: TIMELINE_PADDING }}>
                {/* Линии сетки */}
                {timelineDates.map((_, i) => (
                  <div
                    key={i}
                    style={{
                      position: "absolute",
                      top: 0,
                      bottom: 0,
                      left: i * DAY_WIDTH + TIMELINE_PADDING,
                      width: 1,
                      background: i % 7 < 5 ? "#1f1f30" : "#252538",
                    }}
                  />
                ))}
                {/* Полоса задачи */}
                <div
                  style={{
                    position: "absolute",
                    top: 8,
                    left: offset * DAY_WIDTH + TIMELINE_PADDING,
                    width: width * DAY_WIDTH - 4,
                    height: ROW_HEIGHT - 16,
                    borderRadius: 4,
                    background: `linear-gradient(135deg, ${color}dd, ${color}99)`,
                    display: "flex",
                    alignItems: "center",
                    paddingLeft: 8,
                    fontSize: 11,
                    color: "#fff",
                    fontWeight: 600,
                    overflow: "hidden",
                    whiteSpace: "nowrap",
                    textOverflow: "ellipsis",
                    cursor: "pointer",
                    minWidth: 2,
                    zIndex: 1,
                    transition: "filter 0.15s",
                  }}
                  onClick={() => setSelectedTask(task)}
                  onMouseEnter={(e) => {
                    e.currentTarget.style.filter = "brightness(1.2)";
                  }}
                  onMouseLeave={(e) => {
                    e.currentTarget.style.filter = "brightness(1)";
                  }}
                  title={`${task.title}: ${formatDateFull(task.startDate)} → ${formatDateFull(task.endDate)} (${task.durationDays} дн.) | Нажмите для деталей`}
                >
                  {width * DAY_WIDTH > 80 ? (
                    <>
                      {formatDateISO(task.startDate)} – {formatDateISO(task.endDate)}
                    </>
                  ) : width * DAY_WIDTH > 40 ? (
                    task.id
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
        </div>
      </div>

      {/* Легенда */}
      <div style={{ display: "flex", gap: 16, padding: "8px 12px", borderTop: "1px solid #333", background: "#232336", fontSize: 11, color: "#808090", flexWrap: "wrap" }}>
        {tasks.map((task, i) => (
          <span key={task.id} style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <span style={{ width: 10, height: 10, borderRadius: 2, background: COLORS[i % COLORS.length] }} />
            {task.id}
          </span>
        ))}
        <span style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 4 }}>
          <span style={{ width: 2, height: 12, background: "#ef4444", borderRadius: 1 }} />
          Сегодня
        </span>
      </div>

      {/* Модалка деталей задачи */}
      <TaskDetailModal task={selectedTask} onClose={() => setSelectedTask(null)} />
    </div>
  );
};