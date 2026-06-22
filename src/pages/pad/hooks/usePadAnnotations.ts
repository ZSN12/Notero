import { useCallback, useEffect, useRef, useState } from 'react';
import { updateNote } from '@/services/api/note';
import type { BackendNote, SessionAnnotations, StrokeAnnotation } from '@/services/api/types';

export interface PadStroke extends StrokeAnnotation {
  id: string;
}

export interface UsePadAnnotationsOptions {
  sessionId?: string;
  note?: BackendNote | null;
  initialPage?: number;
}

function generateId() {
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function cloneStrokes(strokes: PadStroke[]): PadStroke[] {
  return strokes.map((s) => ({
    ...s,
    points: s.points.map((p) => ({ ...p })),
  }));
}

function toSavedStrokes(strokes: PadStroke[]): StrokeAnnotation[] {
  return strokes.map(({ type, color, width, points }) => ({
    type,
    color,
    width,
    points,
  }));
}

function emptyPageHistory(): { history: PadStroke[][]; index: number } {
  return { history: [[]], index: 0 };
}

function distanceToSegment(
  px: number,
  py: number,
  x1: number,
  y1: number,
  x2: number,
  y2: number
): number {
  const dx = x2 - x1;
  const dy = y2 - y1;
  if (dx === 0 && dy === 0) {
    return Math.hypot(px - x1, py - y1);
  }
  let t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy);
  t = Math.max(0, Math.min(1, t));
  return Math.hypot(px - (x1 + t * dx), py - (y1 + t * dy));
}

function eraseStrokes(
  strokes: PadStroke[],
  point: { x: number; y: number },
  radius: number
): PadStroke[] {
  return strokes.filter((stroke) => {
    for (let i = 0; i < stroke.points.length - 1; i++) {
      const a = stroke.points[i];
      const b = stroke.points[i + 1];
      if (distanceToSegment(point.x, point.y, a.x, a.y, b.x, b.y) <= radius) {
        return false;
      }
    }
    return true;
  });
}

const SAVE_DEBOUNCE_MS = 1000;
const SAVE_RETRY_DELAY_MS = 3000;

export function usePadAnnotations({ sessionId, note, initialPage = 1 }: UsePadAnnotationsOptions) {
  const [page, setPage] = useState<number>(initialPage);
  const [annotations, setAnnotations] = useState<SessionAnnotations>({ slides: {} });
  const [strokes, setStrokes] = useState<PadStroke[]>([]);
  const [historyMap, setHistoryMap] = useState<Record<string, { history: PadStroke[][]; index: number }>>({});
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const revisionRef = useRef(0);
  const savingRevisionRef = useRef<number | null>(null);
  const isSavingRef = useRef(false);
  const noteRef = useRef(note);
  const sessionIdRef = useRef(sessionId);
  const annotationsRef = useRef(annotations);
  const isDirtyRef = useRef(isDirty);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const lastInitializedSessionRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    noteRef.current = note;
  }, [note]);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    annotationsRef.current = annotations;
  }, [annotations]);

  useEffect(() => {
    isDirtyRef.current = isDirty;
  }, [isDirty]);

  // Initialize local annotations once per sessionId after the note is loaded.
  // Background refreshes of `note` must not overwrite dirty local data.
  useEffect(() => {
    if (!sessionId) return;
    if (!note) return;
    if (lastInitializedSessionRef.current === sessionId) return;

    const nextAnnotations = note.annotations?.slides
      ? { slides: { ...note.annotations.slides } }
      : { slides: {} };
    setAnnotations(nextAnnotations);
    annotationsRef.current = nextAnnotations;

    const pageKey = String(initialPage);
    const pageStrokes = nextAnnotations.slides[pageKey] ?? [];
    const localStrokes = pageStrokes.map((s) => ({ ...s, id: generateId() }));
    setStrokes(localStrokes);
    // Use the loaded strokes as the base of the undo history so that undo
    // after the first new stroke returns to the persisted state.
    setHistoryMap({ [pageKey]: { history: [localStrokes], index: 0 } });

    revisionRef.current = 0;
    savingRevisionRef.current = null;
    setIsDirty(false);
    setSaveError(null);
    lastInitializedSessionRef.current = sessionId;
  }, [sessionId, note, initialPage]);

  const loadPageStrokes = useCallback((targetPage: number, localAnnotations: SessionAnnotations) => {
    const pageKey = String(targetPage);
    const pageStrokes = localAnnotations.slides[pageKey] ?? [];
    const localStrokes = pageStrokes.map((s) => ({ ...s, id: generateId() }));
    setStrokes(localStrokes);
    setHistoryMap((prev) => {
      // If the page has never been visited, seed its history with the persisted strokes.
      if (!prev[pageKey]) {
        return { ...prev, [pageKey]: { history: [localStrokes], index: 0 } };
      }
      return prev;
    });
  }, []);

  const performSave = useCallback(async () => {
    const currentSession = sessionIdRef.current;
    const currentNote = noteRef.current;
    if (!currentSession || !currentNote) return;
    if (isSavingRef.current) {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        saveTimerRef.current = null;
        if (isDirtyRef.current) performSave();
      }, 100);
      return;
    }

    const rev = revisionRef.current;
    savingRevisionRef.current = rev;
    isSavingRef.current = true;
    if (mountedRef.current) setIsSaving(true);

    try {
      await updateNote(
        currentSession,
        currentNote.content ?? '',
        currentNote.layout_blocks ?? undefined,
        annotationsRef.current
      );

      if (!mountedRef.current) return;
      // Ignore responses that belong to a different session.
      if (sessionIdRef.current !== currentSession) return;

      if (revisionRef.current !== rev) {
        // Newer edits happened while saving; continue saving the latest version.
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        saveTimerRef.current = setTimeout(() => {
          saveTimerRef.current = null;
          if (mountedRef.current) performSave();
        }, 0);
        return;
      }

      setIsDirty(false);
      setSaveError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      if (sessionIdRef.current !== currentSession) return;
      setSaveError(err instanceof Error ? err.message : '标注保存失败，可重试');
      // Keep dirty=true so the user can retry.
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        saveTimerRef.current = null;
        if (mountedRef.current && sessionIdRef.current === currentSession) performSave();
      }, SAVE_RETRY_DELAY_MS);
    } finally {
      if (mountedRef.current && sessionIdRef.current === currentSession) {
        isSavingRef.current = false;
        setIsSaving(false);
      }
    }
  }, []);

  const scheduleSave = useCallback(
    (delay = SAVE_DEBOUNCE_MS) => {
      if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
      saveTimerRef.current = setTimeout(() => {
        saveTimerRef.current = null;
        performSave();
      }, delay);
    },
    [performSave]
  );

  const flushSave = useCallback(() => {
    if (saveTimerRef.current) {
      clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    if (isDirtyRef.current && !isSavingRef.current) {
      performSave();
    }
  }, [performSave]);

  const retrySave = useCallback(() => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    scheduleSave(0);
  }, [scheduleSave]);

  // Flush pending saves on unmount instead of silently cancelling the timer.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      if (saveTimerRef.current) {
        clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      if (isDirtyRef.current && sessionIdRef.current) {
        const currentSession = sessionIdRef.current;
        const currentNote = noteRef.current;
        if (currentNote) {
          // Fire the request synchronously; we cannot await in a cleanup.
          updateNote(
            currentSession,
            currentNote.content ?? '',
            currentNote.layout_blocks ?? undefined,
            annotationsRef.current
          ).catch(() => {
            // Errors on unmount are intentionally ignored.
          });
        }
      }
    };
  }, []);

  const pushHistory = useCallback((pageKey: string, nextStrokes: PadStroke[]) => {
    setHistoryMap((prev) => {
      const current = prev[pageKey] ?? emptyPageHistory();
      const base = current.history.slice(0, current.index + 1);
      return {
        ...prev,
        [pageKey]: { history: [...base, cloneStrokes(nextStrokes)], index: current.index + 1 },
      };
    });
  }, []);

  const commitStrokes = useCallback((pageKey: string, nextStrokes: PadStroke[]) => {
    const nextAnnotations = {
      slides: {
        ...annotationsRef.current.slides,
        [pageKey]: toSavedStrokes(nextStrokes),
      },
    };
    setStrokes(nextStrokes);
    setAnnotations(nextAnnotations);
    annotationsRef.current = nextAnnotations;
    revisionRef.current += 1;
    setIsDirty(true);
  }, []);

  const addStroke = useCallback(
    (stroke: StrokeAnnotation) => {
      const pageKey = String(page);
      const newStroke: PadStroke = { ...stroke, id: generateId() };
      const nextStrokes = [...strokes, newStroke];
      commitStrokes(pageKey, nextStrokes);
      pushHistory(pageKey, nextStrokes);
      scheduleSave();
    },
    [page, strokes, commitStrokes, pushHistory, scheduleSave]
  );

  const erase = useCallback(
    (point: { x: number; y: number }, radius: number) => {
      const pageKey = String(page);
      const nextStrokes = eraseStrokes(strokes, point, radius);
      if (nextStrokes.length !== strokes.length) {
        commitStrokes(pageKey, nextStrokes);
        pushHistory(pageKey, nextStrokes);
        scheduleSave();
      }
    },
    [page, strokes, commitStrokes, pushHistory, scheduleSave]
  );

  const undo = useCallback(() => {
    const pageKey = String(page);
    const current = historyMap[pageKey];
    if (!current || current.index <= 0) return;
    const nextIndex = current.index - 1;
    const nextStrokes = cloneStrokes(current.history[nextIndex]);
    setHistoryMap((prev) => ({ ...prev, [pageKey]: { ...current, index: nextIndex } }));
    commitStrokes(pageKey, nextStrokes);
    scheduleSave();
  }, [page, historyMap, commitStrokes, scheduleSave]);

  const redo = useCallback(() => {
    const pageKey = String(page);
    const current = historyMap[pageKey];
    if (!current || current.index >= current.history.length - 1) return;
    const nextIndex = current.index + 1;
    const nextStrokes = cloneStrokes(current.history[nextIndex]);
    setHistoryMap((prev) => ({ ...prev, [pageKey]: { ...current, index: nextIndex } }));
    commitStrokes(pageKey, nextStrokes);
    scheduleSave();
  }, [page, historyMap, commitStrokes, scheduleSave]);

  const clear = useCallback(() => {
    const pageKey = String(page);
    const nextStrokes: PadStroke[] = [];
    commitStrokes(pageKey, nextStrokes);
    pushHistory(pageKey, nextStrokes);
    scheduleSave();
  }, [page, commitStrokes, pushHistory, scheduleSave]);

  const changePage = useCallback(
    (nextPage: number) => {
      if (nextPage === page) return;
      // Flush any pending save for the current page before switching.
      flushSave();
      setPage(nextPage);
      loadPageStrokes(nextPage, annotationsRef.current);
    },
    [page, flushSave, loadPageStrokes]
  );

  const pageHistory = historyMap[String(page)];

  return {
    page,
    strokes,
    annotations,
    isDirty,
    isSaving,
    saveError,
    canUndo: (pageHistory?.index ?? 0) > 0,
    canRedo: (pageHistory?.index ?? 0) < (pageHistory?.history.length ?? 1) - 1,
    actions: {
      setPage: changePage,
      addStroke,
      erase,
      undo,
      redo,
      clear,
      retrySave,
      flushSave,
    },
  };
}
