import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useEditorHistory } from '../useEditorHistory';

describe('useEditorHistory', () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });

  afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
  });

  it('records and undoes changes', () => {
    const { result } = renderHook(() => useEditorHistory());

    act(() => {
      result.current.record('a', true);
    });
    act(() => {
      result.current.record('b', true);
    });

    expect(result.current.canUndo).toBe(true);

    let snapshot: string | null = '';
    act(() => {
      snapshot = result.current.undo();
    });

    expect(snapshot).toBe('a');
    expect(result.current.canUndo).toBe(true);

    act(() => {
      snapshot = result.current.undo();
    });

    expect(snapshot).toBe('');
    expect(result.current.canUndo).toBe(false);
  });

  it('redoes previously undone changes', () => {
    const { result } = renderHook(() => useEditorHistory());

    act(() => {
      result.current.record('first', true);
    });
    act(() => {
      result.current.record('second', true);
    });

    act(() => {
      result.current.undo();
    });

    let snapshot: string | null = '';
    act(() => {
      snapshot = result.current.redo();
    });

    expect(snapshot).toBe('second');
    expect(result.current.canRedo).toBe(false);
  });

  it('debounces rapid records', () => {
    const { result } = renderHook(() => useEditorHistory());

    act(() => {
      result.current.record('a', true);
    });

    act(() => {
      result.current.record('b');
      result.current.record('c');
      result.current.record('d');
    });

    // Only the last debounced value should be committed.
    act(() => {
      vi.advanceTimersByTime(600);
    });

    expect(result.current.canUndo).toBe(true);

    let snapshot: string | null = '';
    act(() => {
      snapshot = result.current.undo();
    });

    expect(snapshot).toBe('a');
  });

  it('clears redo stack on new record', () => {
    const { result } = renderHook(() => useEditorHistory());

    act(() => {
      result.current.record('a', true);
    });
    act(() => {
      result.current.record('b', true);
    });

    act(() => {
      result.current.undo();
    });

    expect(result.current.canRedo).toBe(true);

    act(() => {
      result.current.record('c', true);
    });

    expect(result.current.canRedo).toBe(false);

    let snapshot: string | null = '';
    act(() => {
      snapshot = result.current.redo();
    });

    expect(snapshot).toBeNull();
  });

  it('respects the max stack size', () => {
    const { result } = renderHook(() => useEditorHistory(3));

    for (let i = 0; i < 5; i++) {
      act(() => {
        result.current.record(String(i + 1), true);
      });
    }

    // With capacity 3, past stack drops oldest records.
    act(() => {
      result.current.undo();
    });
    act(() => {
      result.current.undo();
    });

    let snapshot: string | null = '';
    act(() => {
      snapshot = result.current.undo();
    });

    expect(snapshot).toBe('2');
  });
});
