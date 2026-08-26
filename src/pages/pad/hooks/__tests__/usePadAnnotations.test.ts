import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { usePadAnnotations } from '../usePadAnnotations';
import type { BackendNote, FreeNoteInsert, FreeNotePage, SessionAnnotations, StrokeAnnotation } from '@/services/api/types';

const updateNoteMock = vi.fn();
const fetchNoteMock = vi.fn();

vi.mock('@/services/api/note', () => ({
  fetchNote: (...args: unknown[]) => fetchNoteMock(...args),
  updateNote: (...args: unknown[]) => updateNoteMock(...args),
}));

function makeNote(annotations?: BackendNote['annotations'], content = 'content'): BackendNote {
  return {
    id: 'n1',
    session_id: 's1',
    content,
    transcript: [],
    ppt_images: [],
    vocabulary: [],
    layout_blocks: null,
    annotations,
    created_at: '2026-01-01T00:00:00Z',
  };
}

const stroke = {
  type: 'stroke' as const,
  color: '#3b82f6',
  width: 4,
  points: [{ x: 0.1, y: 0.1 }],
};

function freePageStrokes(annotations: SessionAnnotations, page: number): StrokeAnnotation[] {
  const entry = annotations.free_notes?.pages[String(page)];
  return Array.isArray(entry) ? entry : entry?.strokes ?? [];
}

function freePageEntry(annotations: SessionAnnotations, page: number): FreeNotePage {
  const entry = annotations.free_notes?.pages[String(page)];
  return Array.isArray(entry) ? { strokes: entry } : entry ?? {};
}

const insert: FreeNoteInsert = {
  id: 'insert-1',
  type: 'slide_snapshot',
  slideIndex: 1,
  dataUrl: 'data:image/png;base64,c2xpZGU=',
  createdAt: '2026-01-01T00:00:00Z',
};
const insertWithLayout = { ...insert, x: 0, y: 0, width: 1, height: 1 };

describe('usePadAnnotations', () => {
  let resolveUpdate: (value?: unknown) => void;
  let rejectUpdate: (reason?: unknown) => void;

  beforeEach(() => {
    vi.useFakeTimers();
    updateNoteMock.mockReset();
    fetchNoteMock.mockReset();
    fetchNoteMock.mockResolvedValue(makeNote({ slides: {} }));
    updateNoteMock.mockImplementation(
      () =>
        new Promise((resolve, reject) => {
          resolveUpdate = resolve;
          rejectUpdate = reject;
        })
    );
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('loads strokes for the initial page', () => {
    const note = makeNote({ slides: { '1': [stroke] } });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    expect(result.current.strokes).toHaveLength(1);
    expect(result.current.strokes[0].color).toBe('#3b82f6');
    expect(result.current.page).toBe(1);
  });

  it('initializes after the note loads instead of marking the session ready early', () => {
    const { result, rerender } = renderHook(
      ({ n }) => usePadAnnotations({ sessionId: 's1', note: n, initialPage: 1 }),
      { initialProps: { n: null as BackendNote | null } }
    );

    expect(result.current.strokes).toHaveLength(0);

    const loadedNote = makeNote({ slides: { '1': [stroke] } });
    rerender({ n: loadedNote });

    expect(result.current.strokes).toHaveLength(1);
    expect(result.current.strokes[0].points).toEqual([{ x: 0.1, y: 0.1 }]);
  });

  it('undo preserves persisted strokes as the base of history', () => {
    const note = makeNote({ slides: { '1': [stroke] } });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    expect(result.current.strokes).toHaveLength(1);

    act(() => result.current.actions.addStroke({ ...stroke, color: '#000000' }));
    expect(result.current.strokes).toHaveLength(2);

    act(() => result.current.actions.undo());
    expect(result.current.strokes).toHaveLength(1);
    expect(result.current.strokes[0].color).toBe('#3b82f6');
  });

  it('does not reinitialize when note refreshes in the background', () => {
    const note = makeNote({ slides: { '1': [stroke] } });
    const { result, rerender } = renderHook(
      ({ n }) => usePadAnnotations({ sessionId: 's1', note: n, initialPage: 1 }),
      { initialProps: { n: note } }
    );

    act(() => result.current.actions.addStroke({ ...stroke, color: '#000000' }));

    const refreshedNote = makeNote({ slides: { '1': [stroke] } });
    rerender({ n: refreshedNote });

    // Local dirty stroke must survive the background refresh.
    expect(result.current.strokes).toHaveLength(2);
    expect(result.current.isDirty).toBe(true);
  });

  it('keeps current-page strokes when switching pages within the debounce window', async () => {
    const note = makeNote({ slides: {} });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    act(() => result.current.actions.addStroke(stroke));

    // Switch page before debounce fires.
    act(() => result.current.actions.setPage(2));

    expect(result.current.page).toBe(2);
    expect(result.current.annotations.slides['1']).toHaveLength(1);
    expect(result.current.annotations.slides['1'][0].points).toEqual([{ x: 0.1, y: 0.1 }]);
    expect(result.current.strokes).toHaveLength(0);

    // Go back; the stroke must still be there.
    act(() => result.current.actions.setPage(1));
    expect(result.current.strokes).toHaveLength(1);
    expect(result.current.strokes[0].points).toEqual([{ x: 0.1, y: 0.1 }]);
  });

  it('flushes pending annotations on unmount so they can be recovered', async () => {
    const note = makeNote({ slides: {} });
    const { result, unmount } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    act(() => result.current.actions.addStroke(stroke));
    unmount();

    // The flush should fire updateNote synchronously without waiting for debounce.
    expect(updateNoteMock).toHaveBeenCalledTimes(1);
    const [, , , savedAnnotations] = updateNoteMock.mock.calls[0];
    expect(savedAnnotations.slides['1']).toHaveLength(1);
  });

  it('saves revisions serially and eventually persists edits made during a save', async () => {
    const note = makeNote({ slides: {} });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    act(() => result.current.actions.addStroke(stroke));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });
    expect(result.current.isSaving).toBe(true);

    // Draw a second stroke while the first request is in flight.
    act(() => result.current.actions.addStroke({ ...stroke, color: '#ef4444' }));

    // Finish the first request.
    await act(async () => {
      resolveUpdate();
      await Promise.resolve();
    });

    // Because the revision advanced, another save should be scheduled.
    await act(async () => {
      vi.advanceTimersByTime(0);
    });

    expect(updateNoteMock).toHaveBeenCalledTimes(2);
    const [, , , finalAnnotations] = updateNoteMock.mock.calls[1];
    expect(finalAnnotations.slides['1']).toHaveLength(2);

    await act(async () => {
      resolveUpdate();
      await Promise.resolve();
    });

    expect(result.current.isDirty).toBe(false);
  });

  it('does not mark new edits as saved when an older save response returns', async () => {
    const note = makeNote({ slides: {} });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    act(() => result.current.actions.addStroke(stroke));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    // Add another stroke before the first save completes.
    act(() => result.current.actions.addStroke({ ...stroke, color: '#22c55e' }));

    await act(async () => {
      resolveUpdate();
      await Promise.resolve();
    });

    // The newer edit must still be dirty.
    expect(result.current.isDirty).toBe(true);
    expect(result.current.strokes).toHaveLength(2);
  });

  it('keeps dirty state and exposes saveError on failure; retrySave can recover', async () => {
    const note = makeNote({ slides: {} });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    act(() => result.current.actions.addStroke(stroke));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    await act(async () => {
      rejectUpdate(new Error('network error'));
      await Promise.resolve();
    });

    expect(result.current.isDirty).toBe(true);
    expect(result.current.saveError).toBe('network error');

    // Retry immediately.
    act(() => result.current.actions.retrySave());
    await act(async () => {
      vi.advanceTimersByTime(0);
    });

    await act(async () => {
      resolveUpdate();
      await Promise.resolve();
    });

    expect(result.current.isDirty).toBe(false);
    expect(result.current.saveError).toBeNull();
  });

  it('does not let an old session save response pollute a new session', async () => {
    const noteS1 = makeNote({ slides: {} }, 's1 content');
    const { result, rerender } = renderHook(
      ({ sid, n }) => usePadAnnotations({ sessionId: sid, note: n, initialPage: 1 }),
      { initialProps: { sid: 's1', n: noteS1 } }
    );

    act(() => result.current.actions.addStroke(stroke));
    await act(async () => {
      vi.advanceTimersByTime(1000);
    });

    // Switch session while save is in flight.
    const noteS2 = makeNote({ slides: { '1': [{ ...stroke, color: '#22c55e' }] } }, 's2 content');
    rerender({ sid: 's2', n: noteS2 });

    // Old session response arrives.
    await act(async () => {
      resolveUpdate();
      await Promise.resolve();
    });

    // New session must not be marked clean by the stale response.
    // The new session has no local edits yet.
    expect(result.current.isDirty).toBe(false);
    expect(result.current.saveError).toBeNull();

    // updateNote must be called for the new session only after initialization,
    // not as a side effect of the old session.
    const savedSessions = updateNoteMock.mock.calls.map((call) => call[0]);
    expect(savedSessions).not.toContain('s2');
  });

  it('supports undo, redo and clear per page', () => {
    const note = makeNote({ slides: {} });
    const { result } = renderHook(() => usePadAnnotations({ sessionId: 's1', note, initialPage: 1 }));

    act(() => result.current.actions.addStroke(stroke));
    expect(result.current.strokes).toHaveLength(1);

    act(() => result.current.actions.undo());
    expect(result.current.strokes).toHaveLength(0);

    act(() => result.current.actions.redo());
    expect(result.current.strokes).toHaveLength(1);

    act(() => result.current.actions.clear());
    expect(result.current.strokes).toHaveLength(0);
    expect(result.current.canUndo).toBe(true);
  });

  it('stores free notebook strokes under free_notes.pages without overwriting slide strokes', async () => {
    const note = makeNote({ slides: { '1': [stroke] } });
    fetchNoteMock.mockResolvedValue(note);
    updateNoteMock.mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.addStroke({ ...stroke, color: '#ef4444' }));
    await act(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    const [, , , savedAnnotations] = updateNoteMock.mock.calls[0];
    expect(savedAnnotations.slides['1']).toHaveLength(1);
    expect(freePageStrokes(savedAnnotations, 1)).toHaveLength(1);
    expect(freePageStrokes(savedAnnotations, 1)[0].color).toBe('#ef4444');
  });

  it('loads legacy free note pages stored directly as stroke arrays', () => {
    const note = makeNote({ slides: {}, free_notes: { pages: { '1': [stroke] } } });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    expect(result.current.strokes).toHaveLength(1);
    expect(result.current.pageBackground).toBe('grid');
    expect(result.current.pageTitle).toBe('自由笔记 1');
    expect(result.current.pageInserts).toEqual([]);
    expect(result.current.pageSummaries[0].isBlank).toBe(false);
  });

  it('adds, switches and deletes free note pages without touching slide annotations', async () => {
    const note = makeNote({ slides: { '1': [stroke] }, free_notes: { pages: { '1': [] } } });
    fetchNoteMock.mockResolvedValue(note);
    updateNoteMock.mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.addPage('lined'));
    expect(result.current.page).toBe(2);
    expect(result.current.pageBackground).toBe('lined');
    expect(result.current.pageSummaries.map((item) => item.page)).toEqual([1, 2]);

    act(() => result.current.actions.setPage(1));
    expect(result.current.page).toBe(1);

    act(() => result.current.actions.deletePage(1, 'grid'));
    expect(result.current.page).toBe(2);
    expect(result.current.pageSummaries.map((item) => item.page)).toEqual([2]);

    await act(async () => {
      vi.advanceTimersByTime(0);
      await Promise.resolve();
    });
    const [, , , savedAnnotations] = updateNoteMock.mock.calls.at(-1)!;
    expect(savedAnnotations.slides['1']).toHaveLength(1);
    expect(savedAnnotations.free_notes.pages['1']).toBeUndefined();
  });

  it('changes page background without clearing existing strokes', () => {
    const note = makeNote({ slides: {}, free_notes: { pages: { '1': [stroke] } } });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.setBackground('blank'));
    const entry = result.current.annotations.free_notes?.pages['1'];
    expect(Array.isArray(entry)).toBe(false);
    expect(entry && !Array.isArray(entry) ? entry.background : null).toBe('blank');
    expect(result.current.strokes).toHaveLength(1);
    expect(freePageStrokes(result.current.annotations, 1)).toHaveLength(1);
  });

  it('merges free note saves with latest slide annotations during concurrent updates', async () => {
    const note = makeNote({ slides: {}, free_notes: { pages: { '1': [] } } });
    fetchNoteMock.mockResolvedValue(makeNote({
      slides: { '3': [{ ...stroke, color: '#22c55e' }] },
      free_notes: { pages: { '1': [] } },
    }));
    updateNoteMock.mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.addStroke({ ...stroke, color: '#ef4444' }));
    await act(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
    });

    const [, , , savedAnnotations] = updateNoteMock.mock.calls[0];
    expect(savedAnnotations.slides['3'][0].color).toBe('#22c55e');
    expect(freePageStrokes(savedAnnotations, 1)[0].color).toBe('#ef4444');
  });

  it('inserts a slide snapshot into the current free note page and saves metadata', async () => {
    const note = makeNote({ slides: { '2': [stroke] }, free_notes: { pages: { '1': [] } } });
    fetchNoteMock.mockResolvedValue(note);
    updateNoteMock.mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.addInsert(insert));
    act(() => result.current.actions.addStroke({ ...stroke, color: '#ef4444' }));

    const pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.inserts).toEqual([insertWithLayout]);
    expect(pageOne.dataUrl).toBe(insert.dataUrl);
    expect(pageOne.strokes?.[0].color).toBe('#ef4444');
    expect(pageOne.metadata).toMatchObject({
      page: 1,
      background: 'grid',
      has_strokes: true,
      has_slide_snapshot: true,
      slide_indexes: [1],
    });

    await act(async () => {
      vi.advanceTimersByTime(1000);
      await Promise.resolve();
    });
    const [, , , savedAnnotations] = updateNoteMock.mock.calls.at(-1)!;
    expect(savedAnnotations.slides['2']).toHaveLength(1);
    expect(freePageEntry(savedAnnotations, 1).inserts).toEqual([insertWithLayout]);
  });

  it('adds a new free note page with a slide snapshot without overwriting old pages', () => {
    const note = makeNote({
      slides: { '1': [stroke] },
      free_notes: { pages: { '1': { background: 'lined', strokes: [stroke], inserts: [] } } },
    });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.addPageWithInsert(insert, 'blank'));

    expect(result.current.page).toBe(2);
    expect(result.current.pageBackground).toBe('blank');
    expect(freePageEntry(result.current.annotations, 1).strokes).toHaveLength(1);
    expect(freePageEntry(result.current.annotations, 2).inserts).toEqual([insertWithLayout]);
    expect(freePageEntry(result.current.annotations, 2).metadata?.slide_indexes).toEqual([1]);
  });

  it('updates a free note page title without clearing template, strokes or inserts', () => {
    const note = makeNote({
      slides: {},
      free_notes: { pages: { '1': { background: 'lined', strokes: [stroke], inserts: [insert], title: '旧标题' } } },
    });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.setTitle('课堂重点'));

    const pageOne = freePageEntry(result.current.annotations, 1);
    expect(result.current.pageTitle).toBe('课堂重点');
    expect(pageOne.title).toBe('课堂重点');
    expect(pageOne.background).toBe('lined');
    expect(pageOne.strokes).toHaveLength(1);
    expect(pageOne.inserts).toEqual([insertWithLayout]);
  });

  it('loads legacy inserts without layout and saves default layout fields', () => {
    const note = makeNote({
      slides: {},
      free_notes: { pages: { '1': { background: 'grid', strokes: [], inserts: [insert] } } },
    });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    expect(result.current.pageInserts).toEqual([insertWithLayout]);
    expect(result.current.pageSummaries[0].inserts).toEqual([insertWithLayout]);
  });

  it('updates insert layout without clearing strokes, background or title', async () => {
    const note = makeNote({
      slides: { '1': [stroke] },
      free_notes: { pages: { '1': { background: 'lined', title: '公式推导', strokes: [stroke], inserts: [insert] } } },
    });
    fetchNoteMock.mockResolvedValue(note);
    updateNoteMock.mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.updateInsert('insert-1', { x: 0.1, y: 0.5, width: 0.45, height: 0.34 }));

    const pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.background).toBe('lined');
    expect(pageOne.title).toBe('公式推导');
    expect(pageOne.strokes).toHaveLength(1);
    expect(pageOne.inserts?.[0]).toMatchObject({ x: 0.1, y: 0.5, width: 0.45, height: 0.34 });

    await act(async () => {
      vi.advanceTimersByTime(0);
      await Promise.resolve();
    });
    const [, , , savedAnnotations] = updateNoteMock.mock.calls.at(-1)!;
    expect(savedAnnotations.slides['1']).toHaveLength(1);
    expect(freePageEntry(savedAnnotations, 1).inserts?.[0]).toMatchObject({ x: 0.1, y: 0.5, width: 0.45, height: 0.34 });
  });

  it('deletes an insert without removing strokes, background or title', () => {
    const note = makeNote({
      slides: {},
      free_notes: { pages: { '1': { background: 'blank', title: '保留页', strokes: [stroke], inserts: [insert] } } },
    });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.deleteInsert('insert-1'));

    const pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.inserts).toEqual([]);
    expect(pageOne.background).toBe('blank');
    expect(pageOne.title).toBe('保留页');
    expect(pageOne.strokes).toHaveLength(1);
    expect(pageOne.metadata?.has_slide_snapshot).toBe(false);
  });

  it('supports text blocks without affecting strokes and inserts', () => {
    const note = makeNote({
      slides: {},
      free_notes: { pages: { '1': { background: 'grid', strokes: [stroke], inserts: [insert] } } },
    });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    let blockId = '';
    act(() => {
      blockId = result.current.actions.addTextBlock({ x: 0.2, y: 0.3 }, '#ef4444', 20);
    });
    act(() => result.current.actions.updateTextBlock(blockId, { text: '课后重点', x: 0.4, y: 0.5 }));

    let pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.textBlocks?.[0]).toMatchObject({ id: blockId, text: '课后重点', x: 0.4, y: 0.5, color: '#ef4444', fontSize: 20 });
    expect(pageOne.strokes).toHaveLength(1);
    expect(pageOne.inserts).toHaveLength(1);
    expect(pageOne.metadata).toMatchObject({ hasTextBlocks: true, textBlockCount: 1 });

    act(() => result.current.actions.deleteTextBlock(blockId));
    pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.textBlocks).toEqual([]);
    expect(pageOne.strokes).toHaveLength(1);
    expect(pageOne.inserts).toHaveLength(1);
  });

  it('saves review status and image metadata without adding slide indexes', () => {
    const imageInsert: FreeNoteInsert = {
      id: 'image-1',
      type: 'image',
      dataUrl: 'data:image/png;base64,aW1hZ2U=',
      createdAt: '2026-01-01T00:00:00Z',
      fileName: 'photo.png',
    };
    const note = makeNote({ slides: { '1': [stroke] }, free_notes: { pages: { '1': { background: 'blank', strokes: [], inserts: [] } } } });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.addInsert(imageInsert));
    act(() => result.current.actions.setReviewStatus('important'));

    const pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.reviewStatus).toBe('important');
    expect(pageOne.inserts?.[0]).toMatchObject({ type: 'image', fileName: 'photo.png', x: 0, y: 0, width: 1, height: 1 });
    expect(pageOne.metadata).toMatchObject({
      hasImages: true,
      imageCount: 1,
      reviewStatus: 'important',
      slide_indexes: [],
      has_slide_snapshot: false,
    });
    expect(result.current.annotations.slides['1']).toHaveLength(1);
  });

  it('saves and deletes AI blocks while preserving page content', () => {
    const note = makeNote({
      slides: {},
      free_notes: { pages: { '1': { background: 'lined', title: 'AI 页', strokes: [stroke], inserts: [insert], textBlocks: [] } } },
    });
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    let blockId = '';
    act(() => {
      blockId = result.current.actions.addAiBlock({
        type: 'summary',
        title: '总结本页',
        content: '这是一条 AI 草稿',
        sourceContext: { page: 1 },
      });
    });
    act(() => result.current.actions.addAiBlock({
      type: 'quiz',
      title: '生成复习题',
      content: 'Q1',
      sourceContext: { page: 1 },
    }));

    let pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.aiBlocks).toHaveLength(2);
    expect(pageOne.metadata).toMatchObject({
      hasAiBlocks: true,
      aiBlockCount: 2,
      aiBlockTypes: ['summary', 'quiz'],
    });
    expect(pageOne.strokes).toHaveLength(1);
    expect(pageOne.inserts).toHaveLength(1);

    act(() => result.current.actions.deleteAiBlock(blockId));
    pageOne = freePageEntry(result.current.annotations, 1);
    expect(pageOne.aiBlocks).toHaveLength(1);
    expect(pageOne.aiBlocks?.[0].type).toBe('quiz');
    expect(pageOne.metadata).toMatchObject({
      aiBlockCount: 1,
      aiBlockTypes: ['quiz'],
    });
    expect(pageOne.background).toBe('lined');
    expect(pageOne.title).toBe('AI 页');
  });

  it('batch updates review status without changing page content or slides', async () => {
    const note = makeNote({
      slides: { '1': [stroke] },
      free_notes: {
        pages: {
          '1': { background: 'grid', title: '公式 A', reviewStatus: 'todo', strokes: [stroke], inserts: [insert] },
          '2': { background: 'lined', title: '公式 B', reviewStatus: 'normal', strokes: [], textBlocks: [{ id: 't1', text: '保留', x: 0.1, y: 0.1, width: 0.2, color: '#111', fontSize: 18, createdAt: 'now', updatedAt: 'now' }] },
          '3': { background: 'blank', title: '其他', reviewStatus: 'todo', strokes: [] },
        },
      },
    });
    fetchNoteMock.mockResolvedValue(note);
    updateNoteMock.mockResolvedValue(undefined);
    const { result } = renderHook(() =>
      usePadAnnotations({ sessionId: 's1', note, initialPage: 1, scope: 'free_notes' })
    );

    act(() => result.current.actions.setPagesReviewStatus([1, 2], 'important'));

    expect(freePageEntry(result.current.annotations, 1).reviewStatus).toBe('important');
    expect(freePageEntry(result.current.annotations, 2).reviewStatus).toBe('important');
    expect(freePageEntry(result.current.annotations, 3).reviewStatus).toBe('todo');
    expect(freePageEntry(result.current.annotations, 1).strokes).toHaveLength(1);
    expect(freePageEntry(result.current.annotations, 2).textBlocks).toHaveLength(1);

    await act(async () => {
      vi.advanceTimersByTime(0);
      await Promise.resolve();
    });
    const [, , , savedAnnotations] = updateNoteMock.mock.calls.at(-1)!;
    expect(savedAnnotations.slides['1']).toHaveLength(1);
  });
});
