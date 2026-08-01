import { useRef, useState, type ChangeEvent, type FC } from "react";
import { uploadExcel, exportExcel, downloadTemplate } from "../api/client";
import type { GanttTask } from "../schemas/task";

interface FileUploadProps {
  onTasksUpdate: (tasks: GanttTask[]) => void;
  onError: (msg: string) => void;
}

const styles = {
  panel: {
    display: "flex",
    gap: 8,
    padding: "10px 0",
    alignItems: "center",
  },
  btn: {
    padding: "8px 16px",
    border: "1px solid #4a4a5a",
    borderRadius: 6,
    background: "#2a2a3a",
    color: "#e0e0f0",
    fontSize: 13,
    cursor: "pointer",
    transition: "background 0.15s",
    display: "flex",
    alignItems: "center",
    gap: 6,
    whiteSpace: "nowrap" as const,
  },
  btnPrimary: {
    padding: "8px 16px",
    border: "none",
    borderRadius: 6,
    background: "#5b6ef5",
    color: "#fff",
    fontSize: 13,
    cursor: "pointer",
    fontWeight: 600,
    display: "flex",
    alignItems: "center",
    gap: 6,
    whiteSpace: "nowrap" as const,
  },
  hiddenInput: {
    display: "none",
  },
  spinner: {
    display: "inline-block",
    width: 14,
    height: 14,
    border: "2px solid rgba(255,255,255,0.3)",
    borderTopColor: "#fff",
    borderRadius: "50%",
    animation: "spin 0.6s linear infinite",
  },
  infoText: {
    fontSize: 12,
    color: "#8a8aaa",
    marginLeft: 4,
  },
};

export const FileUpload: FC<FileUploadProps> = ({ onTasksUpdate, onError }) => {
  const [uploading, setUploading] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) {
      return;
    }
    if (!file.name.toLowerCase().endsWith(".xlsx")) {
      onError("Выберите файл с расширением .xlsx");
      e.target.value = "";
      return;
    }
    setUploading(true);
    try {
      const tasks = await uploadExcel(file);
      onTasksUpdate(tasks);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Ошибка загрузки файла");
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const handleExport = async () => {
    setExporting(true);
    try {
      await exportExcel();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Ошибка экспорта");
    } finally {
      setExporting(false);
    }
  };

  const handleDownloadTemplate = async () => {
    setDownloadingTemplate(true);
    try {
      await downloadTemplate();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Ошибка скачивания шаблона");
    } finally {
      setDownloadingTemplate(false);
    }
  };

  return (
    <div style={styles.panel}>
      <button
        style={styles.btnPrimary}
        onClick={() => fileInputRef.current?.click()}
        disabled={uploading}
        type="button"
      >
        {uploading ? (
          <>
            <span className="spinner" />
            Загрузка...
          </>
        ) : (
          "Загрузить Excel"
        )}
      </button>
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx"
        onChange={handleFileChange}
        style={styles.hiddenInput}
      />
      <button
        style={styles.btn}
        onClick={handleDownloadTemplate}
        disabled={downloadingTemplate}
        type="button"
        title="Скачать эталонный шаблон (5 колонок БЕЗ дат) для заполнения проекта"
      >
        {downloadingTemplate ? (
          <>
            <span className="spinner" />
            Загрузка...
          </>
        ) : (
          "Скачать шаблон"
        )}
      </button>
      <button
        style={styles.btn}
        onClick={handleExport}
        disabled={exporting}
        type="button"
        title="Скачать текущее расписание (8 колонок с датами и формулами)"
      >
        {exporting ? (
          <>
            <span className="spinner" />
            Экспорт...
          </>
        ) : (
          "Экспорт проекта"
        )}
      </button>
      <span style={styles.infoText}>.xlsx</span>
      <style>{`@keyframes spin { to { transform: rotate(360deg); } } .spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid rgba(255,255,255,0.3); border-top-color: #fff; border-radius: 50%; animation: spin 0.6s linear infinite; }`}</style>
    </div>
  );
};