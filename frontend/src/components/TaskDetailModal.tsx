import { type FC, useEffect } from "react";
import type { GanttTask } from "../schemas/task";

interface TaskDetailModalProps {
  task: GanttTask | null;
  onClose: () => void;
}

const styles = {
  overlay: {
    position: "fixed" as const,
    inset: 0,
    background: "rgba(0, 0, 0, 0.7)",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    zIndex: 1000,
    padding: 20,
  },
  modal: {
    background: "#1e1e30",
    borderRadius: 12,
    border: "1px solid #3a3a50",
    maxWidth: 600,
    width: "100%",
    maxHeight: "90vh",
    overflow: "auto",
    boxShadow: "0 10px 40px rgba(0, 0, 0, 0.5)",
  },
  header: {
    display: "flex",
    alignItems: "center",
    justifyContent: "space-between",
    padding: "20px 24px",
    borderBottom: "1px solid #2a2a3a",
  },
  headerTitle: {
    fontSize: 18,
    fontWeight: 700,
    color: "#f0f0f8",
    display: "flex",
    alignItems: "center",
    gap: 8,
  },
  badge: {
    fontSize: 11,
    fontWeight: 600,
    color: "#5b6ef5",
    background: "rgba(91, 110, 245, 0.15)",
    padding: "4px 8px",
    borderRadius: 6,
  },
  closeButton: {
    width: 32,
    height: 32,
    border: "none",
    background: "transparent",
    color: "#8a8aaa",
    fontSize: 20,
    cursor: "pointer",
    borderRadius: 6,
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    transition: "background 0.15s, color 0.15s",
  },
  body: {
    padding: "20px 24px",
    display: "flex",
    flexDirection: "column" as const,
    gap: 20,
  },
  section: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 6,
  },
  label: {
    fontSize: 11,
    fontWeight: 600,
    color: "#8a8aaa",
    textTransform: "uppercase" as const,
    letterSpacing: "0.5px",
  },
  value: {
    fontSize: 14,
    color: "#d0d0e0",
    lineHeight: 1.5,
  },
  valueEmpty: {
    fontSize: 14,
    color: "#6a6a8a",
    fontStyle: "italic" as const,
  },
  dateRange: {
    display: "flex",
    alignItems: "center",
    gap: 12,
    fontSize: 14,
    color: "#d0d0e0",
  },
  dateBox: {
    display: "flex",
    flexDirection: "column" as const,
    gap: 2,
  },
  dateLabel: {
    fontSize: 10,
    color: "#8a8aaa",
    textTransform: "uppercase" as const,
  },
  dateValue: {
    fontSize: 15,
    fontWeight: 600,
    color: "#f0f0f8",
  },
  arrow: {
    color: "#5b6ef5",
    fontSize: 18,
  },
  durationBadge: {
    display: "inline-block",
    fontSize: 13,
    fontWeight: 600,
    color: "#38b2ac",
    background: "rgba(56, 178, 172, 0.15)",
    padding: "6px 12px",
    borderRadius: 6,
  },
  predecessorsList: {
    display: "flex",
    flexWrap: "wrap" as const,
    gap: 8,
  },
  predecessorChip: {
    fontSize: 12,
    fontWeight: 600,
    color: "#f0a040",
    background: "rgba(240, 160, 64, 0.15)",
    padding: "4px 10px",
    borderRadius: 6,
    border: "1px solid rgba(240, 160, 64, 0.3)",
  },
};

function formatDate(isoDate: string): string {
  try {
    const date = new Date(isoDate);
    const day = String(date.getDate()).padStart(2, "0");
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const year = date.getFullYear();
    return `${day}.${month}.${year}`;
  } catch {
    return isoDate;
  }
}

export const TaskDetailModal: FC<TaskDetailModalProps> = ({ task, onClose }) => {
  useEffect(() => {
    if (!task) return;

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
      }
    };

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [task, onClose]);

  if (!task) return null;

  const handleOverlayClick = (e: React.MouseEvent<HTMLDivElement>) => {
    if (e.target === e.currentTarget) {
      onClose();
    }
  };

  return (
    <div style={styles.overlay} onClick={handleOverlayClick}>
      <div style={styles.modal} onClick={(e) => e.stopPropagation()}>
        {/* Шапка */}
        <div style={styles.header}>
          <div style={styles.headerTitle}>
            <span>{task.title}</span>
            <span style={styles.badge}>{task.id}</span>
          </div>
          <button
            type="button"
            style={styles.closeButton}
            onClick={onClose}
            onMouseEnter={(e) => {
              e.currentTarget.style.background = "#2a2a3a";
              e.currentTarget.style.color = "#f0f0f8";
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.background = "transparent";
              e.currentTarget.style.color = "#8a8aaa";
            }}
            aria-label="Закрыть"
          >
            ✕
          </button>
        </div>

        {/* Тело модалки */}
        <div style={styles.body}>
          {/* Даты */}
          <div style={styles.section}>
            <div style={styles.label}>Период выполнения</div>
            <div style={styles.dateRange}>
              <div style={styles.dateBox}>
                <span style={styles.dateLabel}>Начало</span>
                <span style={styles.dateValue}>{formatDate(task.startDate)}</span>
              </div>
              <span style={styles.arrow}>→</span>
              <div style={styles.dateBox}>
                <span style={styles.dateLabel}>Окончание</span>
                <span style={styles.dateValue}>{formatDate(task.endDate)}</span>
              </div>
            </div>
          </div>

          {/* Длительность */}
          <div style={styles.section}>
            <div style={styles.label}>Длительность</div>
            <div>
              <span style={styles.durationBadge}>
                {task.durationDays} {task.durationDays === 1 ? "день" : task.durationDays < 5 ? "дня" : "дней"}
              </span>
            </div>
          </div>

          {/* Исполнитель */}
          <div style={styles.section}>
            <div style={styles.label}>Исполнитель</div>
            {task.assignee ? (
              <div style={styles.value}>{task.assignee}</div>
            ) : (
              <div style={styles.valueEmpty}>Не назначен</div>
            )}
          </div>

          {/* Предшественники */}
          <div style={styles.section}>
            <div style={styles.label}>Зависимости (Предшественники)</div>
            {task.predecessors.length > 0 ? (
              <div style={styles.predecessorsList}>
                {task.predecessors.map((predId) => (
                  <span key={predId} style={styles.predecessorChip}>
                    {predId}
                  </span>
                ))}
              </div>
            ) : (
              <div style={styles.valueEmpty}>Нет зависимостей (корневая задача)</div>
            )}
          </div>

          {/* Описание */}
          <div style={styles.section}>
            <div style={styles.label}>Описание</div>
            {task.description ? (
              <div style={styles.value}>{task.description}</div>
            ) : (
              <div style={styles.valueEmpty}>Описание отсутствует</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
