import { useCallback, useRef, useState } from 'react';

export interface EditorHistory {
  undo: () => string | null;
  redo: () => string | null;
  record: (value: string, immediate?: boolean) => void;
  canUndo: boolean;
  canRedo: boolean;
}

export function useEditorHistory(maxStackSize = 50): EditorHistory {
  const [canUndo, setCanUndo] = useState(false);
  const [canRedo, setCanRedo] = useState(false);
  const presentRef = useRef<string>('');
  const pastRef = useRef<string[]>([]);
  const futureRef = useRef<string[]>([]);
  const recordTimeoutRef = useRef<number | null>(null);

  const updateFlags = useCallback(() => {
    setCanUndo(pastRef.current.length > 0);
    setCanRedo(futureRef.current.length > 0);
  }, []);

  const record = useCallback(
    (value: string, immediate = false) => {
      if (value === presentRef.current) return;

      if (recordTimeoutRef.current) {
        window.clearTimeout(recordTimeoutRef.current);
        recordTimeoutRef.current = null;
      }

      const commit = () => {
        if (value === presentRef.current) return;
        pastRef.current.push(presentRef.current);
        if (pastRef.current.length > maxStackSize) {
          pastRef.current.shift();
        }
        presentRef.current = value;
        futureRef.current = [];
        updateFlags();
      };

      if (immediate) {
        commit();
        return;
      }

      recordTimeoutRef.current = window.setTimeout(() => {
        recordTimeoutRef.current = null;
        commit();
      }, 500);
    },
    [maxStackSize, updateFlags],
  );

  const undo = useCallback((): string | null => {
    if (pastRef.current.length === 0) return null;
    const previous = pastRef.current.pop()!;
    futureRef.current.push(presentRef.current);
    presentRef.current = previous;
    updateFlags();
    return previous;
  }, [updateFlags]);

  const redo = useCallback((): string | null => {
    if (futureRef.current.length === 0) return null;
    const next = futureRef.current.pop()!;
    pastRef.current.push(presentRef.current);
    presentRef.current = next;
    updateFlags();
    return next;
  }, [updateFlags]);

  return { undo, redo, record, canUndo, canRedo };
}
