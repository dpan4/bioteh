/**
 * Хук для управления состоянием задач с поддержкой Undo/Redo.
 *
 * Хранит историю состояний GanttTask[] и позволяет откатывать/повторять изменения.
 * Максимум 50 состояний в истории для экономии памяти.
 */

import { useCallback, useState } from "react";
import type { GanttTask } from "../schemas/task";

/** Максимальное количество состояний в истории. */
const MAX_HISTORY_SIZE = 50;

interface UseTasksReturn {
  tasks: GanttTask[];
  canUndo: boolean;
  canRedo: boolean;
  setTasks: (tasks: GanttTask[]) => void;
  undo: () => void;
  redo: () => void;
}

interface HistoryState {
  items: GanttTask[][];
  currentIndex: number;
}

/**
 * Хук для управления задачами с поддержкой истории изменений.
 *
 * @param initialTasks — Начальный массив задач.
 * @returns Объект с текущими задачами, функциями undo/redo и флагами доступности.
 */
export function useTasks(initialTasks: GanttTask[] = []): UseTasksReturn {
  // Объединённое состояние истории и текущего индекса для атомарных обновлений
  const [historyState, setHistoryState] = useState<HistoryState>({
    items: [initialTasks],
    currentIndex: 0,
  });

  // Текущее состояние задач
  const tasks = historyState.items[historyState.currentIndex];

  // Флаги доступности undo/redo
  const canUndo = historyState.currentIndex > 0;
  const canRedo = historyState.currentIndex < historyState.items.length - 1;

  /**
   * Обновляет задачи и добавляет новое состояние в историю.
   * При добавлении нового состояния вся "будущая" история (после текущей позиции) удаляется.
   */
  const setTasks = useCallback((newTasks: GanttTask[]) => {
    console.log("[useTasks] setTasks вызван с", newTasks.length, "задачами");
    setHistoryState((prev) => {
      console.log("[useTasks] Предыдущее состояние:", {
        itemsCount: prev.items.length,
        currentIndex: prev.currentIndex
      });
      
      // Берём историю до текущей позиции включительно
      let newHistory = prev.items.slice(0, prev.currentIndex + 1);
      
      // Добавляем новое состояние
      newHistory.push(newTasks);
      
      // Ограничиваем размер истории
      if (newHistory.length > MAX_HISTORY_SIZE) {
        newHistory = newHistory.slice(newHistory.length - MAX_HISTORY_SIZE);
      }
      
      const newState = {
        items: newHistory,
        currentIndex: newHistory.length - 1,
      };
      
      console.log("[useTasks] Новое состояние:", {
        itemsCount: newState.items.length,
        currentIndex: newState.currentIndex,
        currentTasks: newState.items[newState.currentIndex].length
      });
      
      return newState;
    });
  }, []);

  /**
   * Откатывает последнее изменение (переходит к предыдущему состоянию).
   */
  const undo = useCallback(() => {
    setHistoryState((prev) => {
      if (prev.currentIndex > 0) {
        return {
          ...prev,
          currentIndex: prev.currentIndex - 1,
        };
      }
      return prev;
    });
  }, []);

  /**
   * Повторяет отменённое изменение (переходит к следующему состоянию).
   */
  const redo = useCallback(() => {
    setHistoryState((prev) => {
      if (prev.currentIndex < prev.items.length - 1) {
        return {
          ...prev,
          currentIndex: prev.currentIndex + 1,
        };
      }
      return prev;
    });
  }, []);

  return {
    tasks,
    canUndo,
    canRedo,
    setTasks,
    undo,
    redo,
  };
}
