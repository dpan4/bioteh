import { useEffect, useState, type FC } from "react";

interface ToastProps {
  message: string;
  onClose: () => void;
}

const TOAST_DURATION = 5000;

const styles = {
  wrapper: {
    position: "fixed" as const,
    top: 16,
    right: 16,
    maxWidth: 420,
    zIndex: 9999,
    display: "flex",
    alignItems: "flex-start",
    gap: 12,
    padding: "14px 16px",
    borderRadius: 8,
    background: "#1e1e2e",
    boxShadow: "0 4px 20px rgba(0,0,0,0.35)",
    color: "#f8f8f8",
    fontSize: 14,
    lineHeight: "1.5",
  },
  icon: {
    flexShrink: 0,
    fontSize: 18,
    marginTop: 1,
  },
  message: {
    flex: 1,
    minWidth: 0,
    wordBreak: "break-word" as const,
  },
  closeBtn: {
    flexShrink: 0,
    padding: 0,
    border: "none",
    background: "none",
    color: "#a0a0b8",
    fontSize: 18,
    cursor: "pointer",
    lineHeight: 1,
  },
};

export const Toast: FC<ToastProps> = ({ message, onClose }) => {
  const [visible, setVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setVisible(false);
      onClose();
    }, TOAST_DURATION);
    return () => clearTimeout(timer);
  }, [onClose]);

  if (!visible) {
    return null;
  }

  return (
    <div style={styles.wrapper} role="alert">
      <span style={styles.icon}>&#9888;</span>
      <span style={styles.message}>{message}</span>
      <button
        style={styles.closeBtn}
        onClick={() => {
          setVisible(false);
          onClose();
        }}
        aria-label="Закрыть уведомление"
        type="button"
      >
        &times;
      </button>
    </div>
  );
};