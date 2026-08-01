/**
 * Компонент кнопок Undo/Redo для отмены и повтора действий AI.
 *
 * Поддерживает горячие клавиши:
 * - Ctrl+Z: Undo
 * - Ctrl+Shift+Z или Ctrl+Y: Redo
 */

import { useEffect, type FC } from "react";

interface UndoRedoControlsProps {
  canUndo: boolean;
  canRedo: boolean;
  onUndo: () => void;
  onRedo: () => void;
}

const styles = {
  container: {
    display: "flex",
    alignItems: "center",
    gap: 4,
    marginLeft: "auto",
  },
  button: {
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    width: 32,
    height: 32,
    border: "1px solid #3a3a4a",
    borderRadius: 6,
    background: "#1e1e30",
    color: "#a0a0c0",
    fontSize: 16,
    cursor: "pointer",
    transition: "all 0.15s ease",
    padding: 0,
  },
  buttonHover: {
    background: "#2a2a40",
    borderColor: "#5b6ef5",
    color: "#e0e0f0",
  },
  buttonDisabled: {
    opacity: 0.3,
    cursor: "not-allowed",
    pointerEvents: "none" as const,
  },
  tooltip: {
    position: "relative" as const,
  },
};

export const UndoRedoControls: FC<UndoRedoControlsProps> = ({
  canUndo,
  canRedo,
  onUndo,
  onRedo,
}) => {
  // Обработка горячих клавиш
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Ctrl+Z: Undo
      if (e.ctrlKey && e.key === "z" && !e.shiftKey && canUndo) {
        e.preventDefault();
        onUndo();
      }
      
      // Ctrl+Shift+Z или Ctrl+Y: Redo
      if (
        ((e.ctrlKey && e.key === "z" && e.shiftKey) ||
          (e.ctrlKey && e.key === "y")) &&
        canRedo
      ) {
        e.preventDefault();
        onRedo();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [canUndo, canRedo, onUndo, onRedo]);

  return (
    <div style={styles.container}>
      {/* Кнопка Undo */}
      <button
        type="button"
        style={{
          ...styles.button,
          ...(canUndo ? {} : styles.buttonDisabled),
        }}
        onClick={onUndo}
        disabled={!canUndo}
        title="Отменить (Ctrl+Z)"
        aria-label="Отменить последнее действие"
        onMouseEnter={(e) => {
          if (canUndo) {
            Object.assign(e.currentTarget.style, styles.buttonHover);
          }
        }}
        onMouseLeave={(e) => {
          if (canUndo) {
            Object.assign(e.currentTarget.style, {
              background: "#1e1e30",
              borderColor: "#3a3a4a",
              color: "#a0a0c0",
            });
          }
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M3 7v6h6" />
          <path d="M21 17a9 9 0 00-9-9 9 9 0 00-6 2.3L3 13" />
        </svg>
      </button>

      {/* Кнопка Redo */}
      <button
        type="button"
        style={{
          ...styles.button,
          ...(canRedo ? {} : styles.buttonDisabled),
        }}
        onClick={onRedo}
        disabled={!canRedo}
        title="Повторить (Ctrl+Y или Ctrl+Shift+Z)"
        aria-label="Повторить отменённое действие"
        onMouseEnter={(e) => {
          if (canRedo) {
            Object.assign(e.currentTarget.style, styles.buttonHover);
          }
        }}
        onMouseLeave={(e) => {
          if (canRedo) {
            Object.assign(e.currentTarget.style, {
              background: "#1e1e30",
              borderColor: "#3a3a4a",
              color: "#a0a0c0",
            });
          }
        }}
      >
        <svg
          width="18"
          height="18"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 7v6h-6" />
          <path d="M3 17a9 9 0 019-9 9 9 0 016 2.3l3 2.7" />
        </svg>
      </button>
    </div>
  );
};
