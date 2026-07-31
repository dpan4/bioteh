import { useCallback, useEffect, useState } from "react";
import { getTasks } from "./api/client";
import { ChatPanel } from "./components/ChatPanel";
import { FileUpload } from "./components/FileUpload";
import { GanttChart } from "./components/GanttChart";
import { Toast } from "./components/Toast";
import type { GanttTask } from "./schemas/task";

const styles = {
  app: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100vh",
    background: "#12121a",
    color: "#e0e0f0",
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
    overflow: "hidden",
  },
  header: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    padding: "12px 20px",
    background: "#161622",
    borderBottom: "1px solid #2a2a3a",
    flexShrink: 0,
  },
  logo: {
    fontSize: 20,
    fontWeight: 700,
    color: "#5b6ef5",
    letterSpacing: -0.5,
  },
  subtitle: {
    fontSize: 12,
    color: "#6a6a8a",
    marginLeft: 4,
  },
  main: {
    display: "flex",
    flex: 1,
    minHeight: 0,
    gap: 0,
  },
  leftPanel: {
    flex: "1 1 0",
    display: "flex",
    flexDirection: "column" as const,
    padding: "16px 16px 16px 20px",
    minWidth: 0,
    gap: 12,
  },
  rightPanel: {
    width: 380,
    flexShrink: 0,
    padding: "16px 20px 16px 0",
  },
  taskTitle: {
    fontSize: 15,
    fontWeight: 600,
    color: "#d0d0e0",
    margin: 0,
  },
  taskCount: {
    fontSize: 12,
    color: "#6a6a8a",
  },
};

export default function App() {
  const [tasks, setTasks] = useState<GanttTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [toasts, setToasts] = useState<{ id: number; message: string }[]>([]);
  const [toastId, setToastId] = useState(0);

  const showError = useCallback(
    (msg: string) => {
      const id = toastId;
      setToastId((prev) => prev + 1);
      setToasts((prev) => [...prev, { id, message: msg }]);
    },
    [toastId],
  );

  const removeToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const handleTasksUpdate = useCallback((newTasks: GanttTask[]) => {
    setTasks(newTasks);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    getTasks()
      .then((data) => {
        if (!cancelled) {
          setTasks(data);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          showError(
            err instanceof Error
              ? err.message
              : "Не удалось загрузить расписание",
          );
        }
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [showError]);

  return (
    <div style={styles.app}>
      {/* Шапка */}
      <header style={styles.header}>
        <span style={styles.logo}>GanttChart AI</span>
        <span style={styles.subtitle}>
          {tasks.length > 0
            ? `${tasks.length} задач в проекте`
            : "Управление проектом через AI"}
        </span>
      </header>

      {/* Основная область */}
      <div style={styles.main}>
        {/* Левая панель: диаграмма + загрузка файлов */}
        <div style={styles.leftPanel}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={styles.taskTitle}>Диаграмма Гантта</h2>
            {tasks.length > 0 && (
              <span style={styles.taskCount}>
                {tasks.length} задач &middot;{" "}
                {tasks[0]?.startDate} – {tasks[tasks.length - 1]?.endDate}
              </span>
            )}
          </div>
          <FileUpload onTasksUpdate={handleTasksUpdate} onError={showError} />
          <GanttChart tasks={tasks} loading={loading} />
        </div>

        {/* Правая панель: чат */}
        <div style={styles.rightPanel}>
          <ChatPanel onTaskUpdate={handleTasksUpdate} onError={showError} />
        </div>
      </div>

      {/* Toast-уведомления */}
      {toasts.map((t) => (
        <Toast key={t.id} message={t.message} onClose={() => removeToast(t.id)} />
      ))}
    </div>
  );
}