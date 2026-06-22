import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, act, waitFor } from '@testing-library/react';
import { useRAG } from '../useRAG';

const askRAGMock = vi.fn();
const fetchRAGMessagesMock = vi.fn();
const clearRAGMessagesMock = vi.fn();

vi.mock('@/services/api', async (importOriginal) => {
  const actual = (await importOriginal()) as Record<string, unknown>;
  return {
    ...actual,
    askRAG: (...args: unknown[]) => askRAGMock(...args),
    fetchRAGMessages: (sessionId: string) => fetchRAGMessagesMock(sessionId),
    clearRAGMessages: (sessionId: string) => clearRAGMessagesMock(sessionId),
  };
});

describe('useRAG', () => {
  beforeEach(() => {
    askRAGMock.mockReset();
    fetchRAGMessagesMock.mockReset();
    clearRAGMessagesMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('loads messages on demand', async () => {
    fetchRAGMessagesMock.mockResolvedValue([
      {
        id: 'm1',
        session_id: 's1',
        notebook_id: 'n1',
        role: 'user',
        content: 'Hello',
        sources: [],
        created_at: '2026-01-01T00:00:00Z',
      },
    ]);

    const { result } = renderHook(() => useRAG());

    await act(async () => {
      await result.current.actions.loadMessages('s1');
    });

    expect(result.current.state.messages).toHaveLength(1);
    expect(result.current.state.messages[0].content).toBe('Hello');
  });

  it('appends user and assistant messages after a successful ask', async () => {
    fetchRAGMessagesMock.mockResolvedValue([]);
    let capturedCallbacks: Record<string, (arg?: unknown) => void> = {};

    askRAGMock.mockImplementation((_query, _sessionId, _notebookId, callbacks) => {
      capturedCallbacks = callbacks;
      return { abort: vi.fn() };
    });

    const { result } = renderHook(() => useRAG());

    act(() => {
      result.current.actions.setSearchQuery('What is singleton?');
    });

    await act(async () => {
      await result.current.actions.handleRAGAsk('s1', 'n1');
    });

    expect(result.current.state.isAskingRAG).toBe(true);
    expect(result.current.state.messages).toHaveLength(1);
    expect(result.current.state.messages[0].role).toBe('user');

    act(() => {
      capturedCallbacks.onChunk('Singleton is a design pattern.');
      capturedCallbacks.onSources([]);
      capturedCallbacks.onDone();
    });

    await waitFor(() => {
      expect(result.current.state.messages).toHaveLength(2);
    });

    expect(result.current.state.messages[1].role).toBe('assistant');
    expect(result.current.state.messages[1].content).toBe('Singleton is a design pattern.');
    expect(result.current.state.isAskingRAG).toBe(false);
  });

  it('clears messages', async () => {
    fetchRAGMessagesMock.mockResolvedValue([
      {
        id: 'm1',
        session_id: 's1',
        notebook_id: 'n1',
        role: 'user',
        content: 'Hello',
        sources: [],
        created_at: '2026-01-01T00:00:00Z',
      },
    ]);
    clearRAGMessagesMock.mockResolvedValue({ deleted: 1 });

    const { result } = renderHook(() => useRAG());

    await act(async () => {
      await result.current.actions.loadMessages('s1');
    });

    expect(result.current.state.messages).toHaveLength(1);

    await act(async () => {
      await result.current.actions.clearMessages('s1');
    });

    expect(result.current.state.messages).toHaveLength(0);
  });

  it('removes optimistic user message on error', async () => {
    fetchRAGMessagesMock.mockResolvedValue([]);
    let capturedCallbacks: Record<string, (arg?: unknown) => void> = {};

    askRAGMock.mockImplementation((_query, _sessionId, _notebookId, callbacks) => {
      capturedCallbacks = callbacks;
      return { abort: vi.fn() };
    });

    const { result } = renderHook(() => useRAG());

    act(() => {
      result.current.actions.setSearchQuery('What is singleton?');
    });

    await act(async () => {
      await result.current.actions.handleRAGAsk('s1', 'n1');
    });

    expect(result.current.state.messages).toHaveLength(1);

    act(() => {
      capturedCallbacks.onError('AI service unavailable');
    });

    await waitFor(() => {
      expect(result.current.state.messages).toHaveLength(0);
    });

    expect(result.current.state.ragError).toBe('AI service unavailable');
    expect(result.current.state.isAskingRAG).toBe(false);
  });
});
