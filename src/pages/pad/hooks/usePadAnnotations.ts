import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { fetchNote, updateNote } from '@/services/api/note';
import type {
  BackendNote,
  FreeNoteAiBlock,
  FreeNoteBackground,
  FreeNoteInsert,
  FreeNotePage,
  FreeNotePageMetadata,
  FreeNoteReviewStatus,
  FreeNoteTextBlock,
  SessionAnnotations,
  StrokeAnnotation,
} from '@/services/api/types';

export interface PadStroke extends StrokeAnnotation {
  id: string;
}

export interface FreeNotePageSummary {
  page: number;
  background: FreeNoteBackground;
  title: string;
  strokes: StrokeAnnotation[];
  inserts: FreeNoteInsert[];
  textBlocks: FreeNoteTextBlock[];
  aiBlocks: FreeNoteAiBlock[];
  reviewStatus: FreeNoteReviewStatus;
  metadata?: FreeNotePageMetadata;
  isBlank: boolean;
}

export interface UsePadAnnotationsOptions {
  sessionId?: string;
  note?: BackendNote | null;
  initialPage?: number;
  scope?: 'slides' | 'free_notes';
}

export const DEFAULT_FREE_NOTE_BACKGROUND: FreeNoteBackground = 'grid';
export const DEFAULT_INSERT_LAYOUT = { x: 0, y: 0, width: 1, height: 1 };
export const DEFAULT_REVIEW_STATUS: FreeNoteReviewStatus = 'normal';

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

function toLocalStrokes(strokes: StrokeAnnotation[] | undefined): PadStroke[] {
  return (strokes ?? []).map((s) => ({ ...s, id: generateId() }));
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

function isFreeNotePage(value: StrokeAnnotation[] | FreeNotePage | undefined): value is FreeNotePage {
  return Boolean(value && !Array.isArray(value) && typeof value === 'object');
}

function withDefaultInsertLayout(insert: FreeNoteInsert): FreeNoteInsert {
  return {
    ...insert,
    x: typeof insert.x === 'number' ? insert.x : DEFAULT_INSERT_LAYOUT.x,
    y: typeof insert.y === 'number' ? insert.y : DEFAULT_INSERT_LAYOUT.y,
    width: typeof insert.width === 'number' ? insert.width : DEFAULT_INSERT_LAYOUT.width,
    height: typeof insert.height === 'number' ? insert.height : DEFAULT_INSERT_LAYOUT.height,
  };
}

function withDefaultTextBlock(block: Partial<FreeNoteTextBlock> & { id: string; text?: string }): FreeNoteTextBlock {
  const now = new Date().toISOString();
  return {
    id: block.id,
    text: block.text ?? '',
    x: typeof block.x === 'number' ? block.x : 0.12,
    y: typeof block.y === 'number' ? block.y : 0.12,
    width: typeof block.width === 'number' ? block.width : 0.32,
    height: typeof block.height === 'number' ? block.height : 0.12,
    color: block.color ?? '#1e293b',
    fontSize: typeof block.fontSize === 'number' ? block.fontSize : 18,
    createdAt: block.createdAt ?? now,
    updatedAt: block.updatedAt ?? now,
  };
}

function withDefaultAiBlock(block: Partial<FreeNoteAiBlock> & { id: string }): FreeNoteAiBlock {
  const now = new Date().toISOString();
  return {
    id: block.id,
    type: block.type ?? 'summary',
    title: block.title ?? 'AI 草稿',
    content: block.content ?? '',
    sourceContext: block.sourceContext ?? {},
    createdAt: block.createdAt ?? now,
    updatedAt: block.updatedAt ?? now,
  };
}

export function normalizeAnnotations(raw?: SessionAnnotations | null): SessionAnnotations {
  return {
    ...(raw ?? {}),
    slides: { ...(raw?.slides ?? {}) },
    free_notes: {
      ...(raw?.free_notes ?? {}),
      pages: { ...(raw?.free_notes?.pages ?? {}) },
      default_background: raw?.free_notes?.default_background ?? DEFAULT_FREE_NOTE_BACKGROUND,
    },
  };
}

export function getFreeNotePageStrokes(
  annotations: SessionAnnotations,
  pageKey: string,
): StrokeAnnotation[] {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (Array.isArray(entry)) return entry;
  if (isFreeNotePage(entry)) return entry.strokes ?? [];
  return [];
}

export function getFreeNotePageInserts(
  annotations: SessionAnnotations,
  pageKey: string,
): FreeNoteInsert[] {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (isFreeNotePage(entry)) return (entry.inserts ?? []).map(withDefaultInsertLayout);
  return [];
}

export function getFreeNotePageTextBlocks(
  annotations: SessionAnnotations,
  pageKey: string,
): FreeNoteTextBlock[] {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (isFreeNotePage(entry)) return (entry.textBlocks ?? []).map((block) => withDefaultTextBlock(block));
  return [];
}

export function getFreeNotePageAiBlocks(
  annotations: SessionAnnotations,
  pageKey: string,
): FreeNoteAiBlock[] {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (isFreeNotePage(entry)) return (entry.aiBlocks ?? []).map((block) => withDefaultAiBlock(block));
  return [];
}

export function getFreeNotePageReviewStatus(
  annotations: SessionAnnotations,
  pageKey: string,
): FreeNoteReviewStatus {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (isFreeNotePage(entry) && entry.reviewStatus) return entry.reviewStatus;
  return DEFAULT_REVIEW_STATUS;
}

export function getFreeNotePageTitle(
  annotations: SessionAnnotations,
  pageKey: string,
): string {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (isFreeNotePage(entry) && typeof entry.title === 'string' && entry.title.trim()) {
    return entry.title;
  }
  const pageNumber = Number(pageKey);
  return Number.isFinite(pageNumber) && pageNumber > 0 ? `自由笔记 ${pageNumber}` : '自由笔记';
}

export function getFreeNotePageBackground(
  annotations: SessionAnnotations,
  pageKey: string,
): FreeNoteBackground {
  const entry = annotations.free_notes?.pages?.[pageKey];
  if (isFreeNotePage(entry) && entry.background) return entry.background;
  return annotations.free_notes?.default_background ?? DEFAULT_FREE_NOTE_BACKGROUND;
}

function buildFreeNoteMetadata(
  pageKey: string,
  background: FreeNoteBackground,
  strokes: StrokeAnnotation[],
  inserts: FreeNoteInsert[],
  textBlocks: FreeNoteTextBlock[],
  aiBlocks: FreeNoteAiBlock[],
  reviewStatus: FreeNoteReviewStatus,
  updatedAt: string,
): FreeNotePageMetadata {
  const slideIndexes = Array.from(new Set(
    inserts
      .filter((insert) => insert.type === 'slide_snapshot')
      .map((insert) => insert.slideIndex)
      .filter((value): value is number => Number.isFinite(value) && value != null && value >= 0),
  )).sort((a, b) => a - b);
  const imageCount = inserts.filter((insert) => insert.type === 'image').length;
  const aiBlockTypes = Array.from(new Set(aiBlocks.map((block) => block.type)));
  return {
    page: Number(pageKey),
    background,
    has_strokes: strokes.length > 0,
    has_slide_snapshot: inserts.some((insert) => insert.type === 'slide_snapshot'),
    slide_indexes: slideIndexes,
    hasTextBlocks: textBlocks.some((block) => block.text.trim().length > 0),
    textBlockCount: textBlocks.length,
    hasImages: imageCount > 0,
    imageCount,
    reviewStatus,
    hasAiBlocks: aiBlocks.length > 0,
    aiBlockCount: aiBlocks.length,
    aiBlockTypes,
    updated_at: updatedAt,
  };
}

export function getFreeNotePageNumbers(annotations: SessionAnnotations): number[] {
  const pages = annotations.free_notes?.pages ?? {};
  const numbers = Object.keys(pages)
    .map((key) => Number(key))
    .filter((value) => Number.isFinite(value) && value > 0)
    .sort((a, b) => a - b);
  return numbers.length > 0 ? numbers : [1];
}

export function getFreeNotePageSummaries(annotations: SessionAnnotations): FreeNotePageSummary[] {
  return getFreeNotePageNumbers(annotations).map((page) => {
    const pageKey = String(page);
    const strokes = getFreeNotePageStrokes(annotations, pageKey);
    const inserts = getFreeNotePageInserts(annotations, pageKey);
    const textBlocks = getFreeNotePageTextBlocks(annotations, pageKey);
    const aiBlocks = getFreeNotePageAiBlocks(annotations, pageKey);
    const entry = annotations.free_notes?.pages?.[pageKey];
    return {
      page,
      background: getFreeNotePageBackground(annotations, pageKey),
      title: getFreeNotePageTitle(annotations, pageKey),
      strokes,
      inserts,
      textBlocks,
      aiBlocks,
      reviewStatus: getFreeNotePageReviewStatus(annotations, pageKey),
      metadata: isFreeNotePage(entry) ? entry.metadata : undefined,
      isBlank: strokes.length === 0 && inserts.length === 0 && textBlocks.length === 0 && aiBlocks.length === 0,
    };
  });
}

function withFreeNotePage(
  annotations: SessionAnnotations,
  pageKey: string,
  strokes: PadStroke[],
  background: FreeNoteBackground,
  patch: Partial<FreeNotePage> = {},
): SessionAnnotations {
  const existing = annotations.free_notes?.pages?.[pageKey];
  const existingPage = isFreeNotePage(existing) ? existing : {};
  const updatedAt = new Date().toISOString();
  const savedStrokes = toSavedStrokes(strokes);
  const inserts = (patch.inserts ?? existingPage.inserts ?? []).map(withDefaultInsertLayout);
  const textBlocks = (patch.textBlocks ?? existingPage.textBlocks ?? []).map((block) => withDefaultTextBlock(block));
  const aiBlocks = (patch.aiBlocks ?? existingPage.aiBlocks ?? []).map((block) => withDefaultAiBlock(block));
  const nextBackground = patch.background ?? background;
  const reviewStatus = patch.reviewStatus ?? existingPage.reviewStatus ?? DEFAULT_REVIEW_STATUS;
  return {
    ...annotations,
    slides: { ...(annotations.slides ?? {}) },
    free_notes: {
      ...(annotations.free_notes ?? {}),
      default_background: annotations.free_notes?.default_background ?? DEFAULT_FREE_NOTE_BACKGROUND,
      updated_at: new Date().toISOString(),
      pages: {
        ...(annotations.free_notes?.pages ?? {}),
        [pageKey]: {
          ...existingPage,
          ...patch,
          background: nextBackground,
          inserts,
          textBlocks,
          aiBlocks,
          reviewStatus,
          strokes: savedStrokes,
          metadata: buildFreeNoteMetadata(pageKey, nextBackground, savedStrokes, inserts, textBlocks, aiBlocks, reviewStatus, updatedAt),
          updated_at: updatedAt,
        },
      },
    },
  };
}

const SAVE_DEBOUNCE_MS = 1000;
const SAVE_RETRY_DELAY_MS = 3000;

export function usePadAnnotations({ sessionId, note, initialPage = 1, scope = 'slides' }: UsePadAnnotationsOptions) {
  const [page, setPage] = useState<number>(initialPage);
  const [annotations, setAnnotations] = useState<SessionAnnotations>({ slides: {} });
  const [strokes, setStrokes] = useState<PadStroke[]>([]);
  const [pageBackground, setPageBackgroundState] = useState<FreeNoteBackground>(DEFAULT_FREE_NOTE_BACKGROUND);
  const [pageInserts, setPageInserts] = useState<FreeNoteInsert[]>([]);
  const [pageTextBlocks, setPageTextBlocks] = useState<FreeNoteTextBlock[]>([]);
  const [pageAiBlocks, setPageAiBlocks] = useState<FreeNoteAiBlock[]>([]);
  const [pageReviewStatus, setPageReviewStatus] = useState<FreeNoteReviewStatus>(DEFAULT_REVIEW_STATUS);
  const [pageTitle, setPageTitleState] = useState('自由笔记 1');
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null);
  const [historyMap, setHistoryMap] = useState<Record<string, { history: PadStroke[][]; index: number }>>({});
  const [isDirty, setIsDirty] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const revisionRef = useRef(0);
  const isSavingRef = useRef(false);
  const noteRef = useRef(note);
  const sessionIdRef = useRef(sessionId);
  const annotationsRef = useRef(annotations);
  const isDirtyRef = useRef(isDirty);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);
  const lastInitializedKeyRef = useRef<string | undefined>(undefined);
  const pageBackgroundRef = useRef(pageBackground);
  const pageInsertsRef = useRef(pageInserts);
  const pageTextBlocksRef = useRef(pageTextBlocks);
  const pageAiBlocksRef = useRef(pageAiBlocks);
  const pageReviewStatusRef = useRef(pageReviewStatus);
  const pageTitleRef = useRef(pageTitle);

  const getScopedStrokes = useCallback((localAnnotations: SessionAnnotations, pageKey: string) => {
    if (scope === 'free_notes') return getFreeNotePageStrokes(localAnnotations, pageKey);
    return localAnnotations.slides?.[pageKey] ?? [];
  }, [scope]);

  const getScopedBackground = useCallback((localAnnotations: SessionAnnotations, pageKey: string) => {
    if (scope === 'free_notes') return getFreeNotePageBackground(localAnnotations, pageKey);
    return DEFAULT_FREE_NOTE_BACKGROUND;
  }, [scope]);

  const withScopedPage = useCallback((
    localAnnotations: SessionAnnotations,
    pageKey: string,
    nextStrokes: PadStroke[],
    background = pageBackgroundRef.current,
    patch: Partial<FreeNotePage> = {},
  ): SessionAnnotations => {
    if (scope === 'free_notes') {
      return withFreeNotePage(localAnnotations, pageKey, nextStrokes, background, patch);
    }
    return {
      ...localAnnotations,
      slides: {
        ...(localAnnotations.slides ?? {}),
        [pageKey]: toSavedStrokes(nextStrokes),
      },
      free_notes: localAnnotations.free_notes,
    };
  }, [scope]);

  const mergeCurrentScope = useCallback((base: SessionAnnotations): SessionAnnotations => {
    const current = normalizeAnnotations(annotationsRef.current);
    if (scope === 'free_notes') {
      return {
        ...base,
        slides: { ...(base.slides ?? {}) },
        free_notes: current.free_notes,
      };
    }
    return {
      ...base,
      slides: current.slides,
      free_notes: base.free_notes,
    };
  }, [scope]);

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

  useEffect(() => {
    pageBackgroundRef.current = pageBackground;
  }, [pageBackground]);

  useEffect(() => {
    pageInsertsRef.current = pageInserts;
  }, [pageInserts]);

  useEffect(() => {
    pageTextBlocksRef.current = pageTextBlocks;
  }, [pageTextBlocks]);

  useEffect(() => {
    pageAiBlocksRef.current = pageAiBlocks;
  }, [pageAiBlocks]);

  useEffect(() => {
    pageReviewStatusRef.current = pageReviewStatus;
  }, [pageReviewStatus]);

  useEffect(() => {
    pageTitleRef.current = pageTitle;
  }, [pageTitle]);

  const loadPage = useCallback((targetPage: number, localAnnotations: SessionAnnotations) => {
    const pageKey = String(targetPage);
    const localStrokes = toLocalStrokes(getScopedStrokes(localAnnotations, pageKey));
    const background = getScopedBackground(localAnnotations, pageKey);
    const inserts = scope === 'free_notes' ? getFreeNotePageInserts(localAnnotations, pageKey) : [];
    const textBlocks = scope === 'free_notes' ? getFreeNotePageTextBlocks(localAnnotations, pageKey) : [];
    const aiBlocks = scope === 'free_notes' ? getFreeNotePageAiBlocks(localAnnotations, pageKey) : [];
    const reviewStatus = scope === 'free_notes' ? getFreeNotePageReviewStatus(localAnnotations, pageKey) : DEFAULT_REVIEW_STATUS;
    const title = scope === 'free_notes' ? getFreeNotePageTitle(localAnnotations, pageKey) : `第 ${targetPage} 页`;
    setPage(targetPage);
    setStrokes(localStrokes);
    setPageBackgroundState(background);
    setPageInserts(inserts);
    setPageTextBlocks(textBlocks);
    setPageAiBlocks(aiBlocks);
    setPageReviewStatus(reviewStatus);
    setPageTitleState(title);
    pageBackgroundRef.current = background;
    pageInsertsRef.current = inserts;
    pageTextBlocksRef.current = textBlocks;
    pageAiBlocksRef.current = aiBlocks;
    pageReviewStatusRef.current = reviewStatus;
    pageTitleRef.current = title;
    setHistoryMap((prev) => {
      if (!prev[pageKey]) {
        return { ...prev, [pageKey]: { history: [localStrokes], index: 0 } };
      }
      return prev;
    });
  }, [getScopedBackground, getScopedStrokes, scope]);

  useEffect(() => {
    if (!sessionId) return;
    if (!note) return;
    const initKey = `${sessionId}:${scope}`;
    if (lastInitializedKeyRef.current === initKey) return;

    const nextAnnotations = normalizeAnnotations(note.annotations);
    setAnnotations(nextAnnotations);
    annotationsRef.current = nextAnnotations;
    loadPage(initialPage, nextAnnotations);

    revisionRef.current = 0;
    setIsDirty(false);
    setSaveError(null);
    lastInitializedKeyRef.current = initKey;
  }, [sessionId, note, initialPage, scope, loadPage]);

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
    isSavingRef.current = true;
    if (mountedRef.current) setIsSaving(true);

    try {
      const latestNote = (await fetchNote(currentSession).catch(() => currentNote)) ?? currentNote;
      const latestAnnotations = normalizeAnnotations(latestNote.annotations);
      const mergedAnnotations = mergeCurrentScope(latestAnnotations);
      annotationsRef.current = mergedAnnotations;

      await updateNote(
        currentSession,
        latestNote.content ?? currentNote.content ?? '',
        latestNote.layout_blocks ?? currentNote.layout_blocks ?? undefined,
        mergedAnnotations
      );

      if (!mountedRef.current) return;
      if (sessionIdRef.current !== currentSession) return;

      if (revisionRef.current !== rev) {
        if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
        saveTimerRef.current = setTimeout(() => {
          saveTimerRef.current = null;
          if (mountedRef.current) performSave();
        }, 0);
        return;
      }

      setIsDirty(false);
      setSaveError(null);
      setLastSavedAt(Date.now());
    } catch (err) {
      if (!mountedRef.current) return;
      if (sessionIdRef.current !== currentSession) return;
      setSaveError(err instanceof Error ? err.message : '标注保存失败，可重试');
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
  }, [mergeCurrentScope]);

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
          updateNote(
            currentSession,
            currentNote.content ?? '',
            currentNote.layout_blocks ?? undefined,
            annotationsRef.current
          ).catch(() => {});
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

  const commitPage = useCallback((
    pageKey: string,
    nextStrokes: PadStroke[],
    background = pageBackgroundRef.current,
    patch: Partial<FreeNotePage> = {},
  ) => {
    const nextAnnotations = withScopedPage(annotationsRef.current, pageKey, nextStrokes, background, patch);
    setStrokes(nextStrokes);
    setAnnotations(nextAnnotations);
    annotationsRef.current = nextAnnotations;
    if (scope === 'free_notes') {
      const nextEntry = nextAnnotations.free_notes?.pages?.[pageKey];
      const nextPage = isFreeNotePage(nextEntry) ? nextEntry : undefined;
      const nextBackground = nextPage?.background ?? background;
      const nextInserts = nextPage?.inserts ?? [];
      const nextTextBlocks = nextPage?.textBlocks ?? [];
      const nextAiBlocks = nextPage?.aiBlocks ?? [];
      const nextReviewStatus = nextPage?.reviewStatus ?? DEFAULT_REVIEW_STATUS;
      const nextTitle = getFreeNotePageTitle(nextAnnotations, pageKey);
      setPageBackgroundState(nextBackground);
      setPageInserts(nextInserts);
      setPageTextBlocks(nextTextBlocks);
      setPageAiBlocks(nextAiBlocks);
      setPageReviewStatus(nextReviewStatus);
      setPageTitleState(nextTitle);
      pageBackgroundRef.current = nextBackground;
      pageInsertsRef.current = nextInserts;
      pageTextBlocksRef.current = nextTextBlocks;
      pageAiBlocksRef.current = nextAiBlocks;
      pageReviewStatusRef.current = nextReviewStatus;
      pageTitleRef.current = nextTitle;
    }
    revisionRef.current += 1;
    setIsDirty(true);
  }, [scope, withScopedPage]);

  const addStroke = useCallback(
    (stroke: StrokeAnnotation) => {
      const pageKey = String(page);
      const newStroke: PadStroke = { ...stroke, id: generateId() };
      const nextStrokes = [...strokes, newStroke];
      commitPage(pageKey, nextStrokes);
      pushHistory(pageKey, nextStrokes);
      scheduleSave();
    },
    [page, strokes, commitPage, pushHistory, scheduleSave]
  );

  const erase = useCallback(
    (point: { x: number; y: number }, radius: number) => {
      const pageKey = String(page);
      const nextStrokes = eraseStrokes(strokes, point, radius);
      if (nextStrokes.length !== strokes.length) {
        commitPage(pageKey, nextStrokes);
        pushHistory(pageKey, nextStrokes);
        scheduleSave();
      }
    },
    [page, strokes, commitPage, pushHistory, scheduleSave]
  );

  const undo = useCallback(() => {
    const pageKey = String(page);
    const current = historyMap[pageKey];
    if (!current || current.index <= 0) return;
    const nextIndex = current.index - 1;
    const nextStrokes = cloneStrokes(current.history[nextIndex]);
    setHistoryMap((prev) => ({ ...prev, [pageKey]: { ...current, index: nextIndex } }));
    commitPage(pageKey, nextStrokes);
    scheduleSave();
  }, [page, historyMap, commitPage, scheduleSave]);

  const redo = useCallback(() => {
    const pageKey = String(page);
    const current = historyMap[pageKey];
    if (!current || current.index >= current.history.length - 1) return;
    const nextIndex = current.index + 1;
    const nextStrokes = cloneStrokes(current.history[nextIndex]);
    setHistoryMap((prev) => ({ ...prev, [pageKey]: { ...current, index: nextIndex } }));
    commitPage(pageKey, nextStrokes);
    scheduleSave();
  }, [page, historyMap, commitPage, scheduleSave]);

  const clear = useCallback(() => {
    const pageKey = String(page);
    const nextStrokes: PadStroke[] = [];
    commitPage(pageKey, nextStrokes);
    pushHistory(pageKey, nextStrokes);
    scheduleSave();
  }, [page, commitPage, pushHistory, scheduleSave]);

  const changePage = useCallback(
    (nextPage: number) => {
      if (nextPage === page) return;
      flushSave();
      loadPage(nextPage, annotationsRef.current);
    },
    [page, flushSave, loadPage]
  );

  const setBackground = useCallback((background: FreeNoteBackground) => {
    const pageKey = String(page);
    commitPage(pageKey, strokes, background);
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const setTitle = useCallback((title: string) => {
    const pageKey = String(page);
    commitPage(pageKey, strokes, pageBackgroundRef.current, { title });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const addInsert = useCallback((insert: FreeNoteInsert) => {
    const pageKey = String(page);
    const nextInserts = [...pageInsertsRef.current, withDefaultInsertLayout(insert)];
    commitPage(pageKey, strokes, pageBackgroundRef.current, {
      inserts: nextInserts,
      dataUrl: insert.dataUrl,
    });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const updateInsert = useCallback((insertId: string, patch: Partial<FreeNoteInsert>) => {
    const pageKey = String(page);
    const nextInserts = pageInsertsRef.current.map((insert) =>
      insert.id === insertId ? withDefaultInsertLayout({ ...insert, ...patch }) : insert,
    );
    commitPage(pageKey, strokes, pageBackgroundRef.current, { inserts: nextInserts });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const deleteInsert = useCallback((insertId: string) => {
    const pageKey = String(page);
    const nextInserts = pageInsertsRef.current.filter((insert) => insert.id !== insertId);
    commitPage(pageKey, strokes, pageBackgroundRef.current, {
      inserts: nextInserts,
      dataUrl: nextInserts.at(-1)?.dataUrl,
    });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const addTextBlock = useCallback((point: { x: number; y: number }, color = '#1e293b', fontSize = 18) => {
    const now = new Date().toISOString();
    const pageKey = String(page);
    const block = withDefaultTextBlock({
      id: generateId(),
      text: '',
      x: point.x,
      y: point.y,
      width: 0.34,
      height: 0.12,
      color,
      fontSize,
      createdAt: now,
      updatedAt: now,
    });
    const nextTextBlocks = [...pageTextBlocksRef.current, block];
    commitPage(pageKey, strokes, pageBackgroundRef.current, { textBlocks: nextTextBlocks });
    scheduleSave(0);
    return block.id;
  }, [page, strokes, commitPage, scheduleSave]);

  const updateTextBlock = useCallback((blockId: string, patch: Partial<FreeNoteTextBlock>) => {
    const pageKey = String(page);
    const nextTextBlocks = pageTextBlocksRef.current.map((block) =>
      block.id === blockId ? withDefaultTextBlock({ ...block, ...patch, updatedAt: new Date().toISOString() }) : block,
    );
    commitPage(pageKey, strokes, pageBackgroundRef.current, { textBlocks: nextTextBlocks });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const deleteTextBlock = useCallback((blockId: string) => {
    const pageKey = String(page);
    const nextTextBlocks = pageTextBlocksRef.current.filter((block) => block.id !== blockId);
    commitPage(pageKey, strokes, pageBackgroundRef.current, { textBlocks: nextTextBlocks });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const setReviewStatus = useCallback((reviewStatus: FreeNoteReviewStatus) => {
    const pageKey = String(page);
    commitPage(pageKey, strokes, pageBackgroundRef.current, { reviewStatus });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const addAiBlock = useCallback((block: Omit<FreeNoteAiBlock, 'id' | 'createdAt' | 'updatedAt'> & { id?: string }) => {
    const now = new Date().toISOString();
    const pageKey = String(page);
    const nextBlock = withDefaultAiBlock({
      ...block,
      id: block.id ?? generateId(),
      createdAt: now,
      updatedAt: now,
    });
    const nextAiBlocks = [...pageAiBlocksRef.current, nextBlock];
    commitPage(pageKey, strokes, pageBackgroundRef.current, { aiBlocks: nextAiBlocks });
    scheduleSave(0);
    return nextBlock.id;
  }, [page, strokes, commitPage, scheduleSave]);

  const deleteAiBlock = useCallback((blockId: string) => {
    const pageKey = String(page);
    const nextAiBlocks = pageAiBlocksRef.current.filter((block) => block.id !== blockId);
    commitPage(pageKey, strokes, pageBackgroundRef.current, { aiBlocks: nextAiBlocks });
    scheduleSave(0);
  }, [page, strokes, commitPage, scheduleSave]);

  const setPagesReviewStatus = useCallback((pagesToUpdate: number[], reviewStatus: FreeNoteReviewStatus) => {
    const current = normalizeAnnotations(annotationsRef.current);
    let nextAnnotations = current;
    const uniquePages = Array.from(new Set(pagesToUpdate)).filter((value) => Number.isFinite(value) && value > 0);
    uniquePages.forEach((targetPage) => {
      const pageKey = String(targetPage);
      const pageStrokes = toLocalStrokes(getFreeNotePageStrokes(nextAnnotations, pageKey));
      nextAnnotations = withFreeNotePage(
        nextAnnotations,
        pageKey,
        pageStrokes,
        getFreeNotePageBackground(nextAnnotations, pageKey),
        { reviewStatus },
      );
    });
    annotationsRef.current = nextAnnotations;
    setAnnotations(nextAnnotations);
    loadPage(page, nextAnnotations);
    revisionRef.current += 1;
    setIsDirty(true);
    scheduleSave(0);
  }, [page, loadPage, scheduleSave]);

  const addPage = useCallback((background: FreeNoteBackground = DEFAULT_FREE_NOTE_BACKGROUND) => {
    const current = annotationsRef.current;
    const pages = getFreeNotePageNumbers(current);
    const nextPage = Math.max(...pages, 0) + 1;
    const nextAnnotations = withFreeNotePage(current, String(nextPage), [], background);
    annotationsRef.current = nextAnnotations;
    setAnnotations(nextAnnotations);
    loadPage(nextPage, nextAnnotations);
    revisionRef.current += 1;
    setIsDirty(true);
    scheduleSave(0);
    return nextPage;
  }, [loadPage, scheduleSave]);

  const addPageWithInsert = useCallback((insert: FreeNoteInsert, background: FreeNoteBackground = DEFAULT_FREE_NOTE_BACKGROUND) => {
    const current = annotationsRef.current;
    const pages = getFreeNotePageNumbers(current);
    const nextPage = Math.max(...pages, 0) + 1;
    const nextAnnotations = withFreeNotePage(current, String(nextPage), [], background, {
      inserts: [insert],
      dataUrl: insert.dataUrl,
    });
    annotationsRef.current = nextAnnotations;
    setAnnotations(nextAnnotations);
    loadPage(nextPage, nextAnnotations);
    revisionRef.current += 1;
    setIsDirty(true);
    scheduleSave(0);
    return nextPage;
  }, [loadPage, scheduleSave]);

  const deletePage = useCallback((targetPage: number, fallbackBackground: FreeNoteBackground = DEFAULT_FREE_NOTE_BACKGROUND) => {
    const current = normalizeAnnotations(annotationsRef.current);
    const pages = { ...(current.free_notes?.pages ?? {}) };
    delete pages[String(targetPage)];
    let pageNumbers = Object.keys(pages)
      .map((key) => Number(key))
      .filter((value) => Number.isFinite(value) && value > 0)
      .sort((a, b) => a - b);

    if (pageNumbers.length === 0) {
      const updatedAt = new Date().toISOString();
      pages['1'] = {
        background: fallbackBackground,
        strokes: [],
        inserts: [],
        textBlocks: [],
        aiBlocks: [],
        reviewStatus: DEFAULT_REVIEW_STATUS,
        metadata: buildFreeNoteMetadata('1', fallbackBackground, [], [], [], [], DEFAULT_REVIEW_STATUS, updatedAt),
        updated_at: updatedAt,
      };
      pageNumbers = [1];
    }

    const lower = pageNumbers.filter((value) => value < targetPage).pop();
    const higher = pageNumbers.find((value) => value > targetPage);
    const nextPage = targetPage === page ? (lower ?? higher ?? pageNumbers[0]) : page;
    const nextAnnotations: SessionAnnotations = {
      ...current,
      free_notes: {
        ...(current.free_notes ?? {}),
        pages,
        updated_at: new Date().toISOString(),
      },
    };

    annotationsRef.current = nextAnnotations;
    setAnnotations(nextAnnotations);
    loadPage(nextPage, nextAnnotations);
    revisionRef.current += 1;
    setIsDirty(true);
    scheduleSave(0);
    return nextPage;
  }, [page, loadPage, scheduleSave]);

  const setDefaultBackground = useCallback((background: FreeNoteBackground) => {
    const current = normalizeAnnotations(annotationsRef.current);
    const nextAnnotations: SessionAnnotations = {
      ...current,
      free_notes: {
        ...(current.free_notes ?? {}),
        pages: { ...(current.free_notes?.pages ?? {}) },
        default_background: background,
        updated_at: new Date().toISOString(),
      },
    };
    annotationsRef.current = nextAnnotations;
    setAnnotations(nextAnnotations);
    revisionRef.current += 1;
    setIsDirty(true);
    scheduleSave(0);
  }, [scheduleSave]);

  const pageHistory = historyMap[String(page)];
  const pageSummaries = useMemo(() => getFreeNotePageSummaries(annotations), [annotations]);

  return {
    page,
    strokes,
    annotations,
    pageBackground,
    pageInserts,
    pageTextBlocks,
    pageAiBlocks,
    pageReviewStatus,
    pageTitle,
    pageSummaries,
    lastSavedAt,
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
      setBackground,
      setTitle,
      addInsert,
      updateInsert,
      deleteInsert,
      addTextBlock,
      updateTextBlock,
      deleteTextBlock,
      setReviewStatus,
      setPagesReviewStatus,
      addAiBlock,
      deleteAiBlock,
      addPage,
      addPageWithInsert,
      deletePage,
      setDefaultBackground,
    },
  };
}
