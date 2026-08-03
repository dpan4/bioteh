import { useEffect, useRef, useState, type FC, type KeyboardEvent } from "react";
import { sendChatMessage } from "../api/client";
import type { GanttTask } from "../schemas/task";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

interface ChatPanelProps {
  onTaskUpdate: (tasks: GanttTask[]) => void;
  onError: (msg: string) => void;
}

const styles = {
  panel: {
    display: "flex",
    flexDirection: "column" as const,
    height: "100%",
    background: "#1a1a28",
    border: "1px solid #333",
    borderRadius: 8,
    overflow: "hidden",
  },
  header: {
    padding: "10px 14px",
    borderBottom: "1px solid #333",
    background: "#232336",
    fontSize: 14,
    fontWeight: 600,
    color: "#e0e0f0",
  },
  messages: {
    flex: 1,
    overflowY: "auto" as const,
    padding: "12px 8px",
    display: "flex",
    flexDirection: "column" as const,
    gap: 10,
    minHeight: 0,
  },
  empty: {
    display: "flex",
    flexDirection: "column" as const,
    justifyContent: "center",
    alignItems: "center",
    height: "100%",
    color: "#5a5a7a",
    gap: 8,
    fontSize: 13,
    textAlign: "center" as const,
    padding: "0 16px",
  },
  userBubble: {
    alignSelf: "flex-end",
    maxWidth: "85%",
    padding: "8px 12px",
    borderRadius: "12px 12px 0 12px",
    background: "#5b6ef5",
    color: "#fff",
    fontSize: 13,
    lineHeight: "1.5",
    wordBreak: "break-word" as const,
  },
  assistantBubble: {
    alignSelf: "flex-start",
    maxWidth: "85%",
    padding: "8px 12px",
    borderRadius: "12px 12px 12px 0",
    background: "#2a2a3a",
    color: "#e0e0f0",
    fontSize: 13,
    lineHeight: "1.5",
    wordBreak: "break-word" as const,
    whiteSpace: "pre-wrap" as const,
  },
  inputRow: {
    display: "flex",
    gap: 8,
    padding: "10px 12px",
    borderTop: "1px solid #333",
    background: "#161622",
    alignItems: "flex-end",
  },
  input: {
    flex: 1,
    padding: "8px 12px",
    border: "1px solid #444",
    borderRadius: 6,
    background: "#1e1e30",
    color: "#e0e0f0",
    fontSize: 13,
    outline: "none",
    resize: "vertical" as const,
    minHeight: 36,
    maxHeight: 200,
    lineHeight: "1.5",
    overflowY: "auto" as const,
  },
  sendBtn: {
    padding: "8px 14px",
    border: "none",
    borderRadius: 6,
    background: "#5b6ef5",
    color: "#fff",
    fontSize: 13,
    fontWeight: 600,
    cursor: "pointer",
    whiteSpace: "nowrap" as const,
    alignSelf: "flex-end",
  },
  typing: {
    alignSelf: "flex-start",
    display: "flex",
    alignItems: "center",
    gap: 6,
    padding: "8px 12px",
    borderRadius: "12px 12px 12px 0",
    background: "#2a2a3a",
    color: "#8a8aaa",
    fontSize: 12,
    maxWidth: "85%",
  },
};

export const ChatPanel: FC<ChatPanelProps> = ({ onTaskUpdate, onError }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    const textarea = inputRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 200)}px`;
  }, [input]);

  const handleSend = async () => {
    const text = input.trim();
    if (text.length === 0 || loading) {
      return;
    }

    setMessages((prev) => [...prev, { role: "user", content: text }]);
    setInput("");
    setLoading(true);

    try {
      console.log("[ChatPanel] Отправка сообщения:", text);
      const result = await sendChatMessage(text);
      console.log("[ChatPanel] Получен ответ:", {
        reply: result.reply,
        tasksCount: result.tasks.length,
        tasks: result.tasks
      });
      
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: result.reply || "Готово. Расписание обновлено." },
      ]);
      
      // Всегда обновляем задачи, даже если массив пустой (для корректного отображения)
      console.log("[ChatPanel] Вызов onTaskUpdate с", result.tasks.length, "задачами");
      onTaskUpdate(result.tasks);
      console.log("[ChatPanel] onTaskUpdate выполнен");
    } catch (err) {
      console.error("[ChatPanel] Ошибка:", err);
      const errMsg = err instanceof Error ? err.message : "Ошибка при обращении к AI";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: `Ошибка: ${errMsg}` },
      ]);
      onError(errMsg);
    } finally {
      setLoading(false);
      inputRef.current?.focus();
    }
  };

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div style={styles.panel}>
      <div style={styles.header}>AI-ассистент</div>

      <div style={styles.messages}>
        {messages.length === 0 && !loading && (
          <div style={styles.empty}>
            <span style={{ fontSize: 28, opacity: 0.3 }}>&#9998;</span>
            <span>Спросите AI о задачах проекта</span>
            <span style={{ fontSize: 11, color: "#4a4a6a" }}>
              Например: «Увеличь длительность задачи task-3 до 10 дней» или
              «Добавь задачу Код-ревью после Разработки API»
            </span>
          </div>
        )}
        {messages.map((msg, i) => (
          <div
            key={i}
            style={
              msg.role === "user" ? styles.userBubble : styles.assistantBubble
            }
          >
            {msg.content}
          </div>
        ))}
        {loading && (
          <div style={styles.typing}>
            <span>Ассистент пересчитывает граф</span>
            <span className="dots" />
            <style>{`.dots::after { content: ''; animation: dotPulse 1.4s infinite; } @keyframes dotPulse { 0% { content: '.'; } 33% { content: '..'; } 66% { content: '...'; } 100% { content: '.'; } }`}</style>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      <div style={styles.inputRow}>
        <textarea
          ref={inputRef}
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Введите запрос для AI..."
          rows={1}
          disabled={loading}
        />
        <button
          style={styles.sendBtn}
          onClick={handleSend}
          disabled={loading || input.trim().length === 0}
          type="button"
        >
          {loading ? "..." : "Отправить"}
        </button>
      </div>
    </div>
  );
};