import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { usePadAnnotations } from '../usePadAnnotations';
import type { BackendNote } from '@/services/api/types';

const updateNoteMock = vi.fn();

vi.mock('@/services/api/note', () => ({
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

describe('usePadAnnotations', () => {
  let resolveUpdate: (value?: unknown) => void;
  let rejectUpdate: (reason?: unknown) => void;

  beforeEach(() => {
    vi.useFakeTimers();
    updateNoteMock.mockReset();
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
});
