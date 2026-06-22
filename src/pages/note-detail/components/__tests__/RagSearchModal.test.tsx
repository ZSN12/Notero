import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { RagSearchModal } from '../RagSearchModal';
import type { RAGMessage, RAGSource } from '@/services/api';

const createRag = (overrides: Record<string, unknown> = {}) => ({
  state: {
    showSearch: true,
    searchQuery: '',
    searchScope: 'session' as const,
    messages: [] as RAGMessage[],
    ragAnswer: '',
    ragSources: [] as RAGSource[],
    isAskingRAG: false,
    ragError: null as string | null,
    ragStatus: null as string | null,
    ...overrides,
  },
  actions: {
    setShowSearch: vi.fn(),
    setSearchQuery: vi.fn(),
    setSearchScope: vi.fn(),
    handleRAGAsk: vi.fn(),
    clearMessages: vi.fn(),
    loadMessages: vi.fn(),
  },
});

const vectorIndex = {
  state: {},
  actions: {
    ensureIndexed: vi.fn().mockResolvedValue(undefined),
  },
};

const onRagSourceClick = vi.fn();
const getRagSourceTypeLabel = (source: RAGSource) => source.source_type;

describe('RagSearchModal', () => {
  it('renders nothing when showSearch is false', () => {
    const rag = createRag({ showSearch: false });
    const { container } = render(
      <RagSearchModal
        rag={rag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it('displays historical messages', () => {
    const messages: RAGMessage[] = [
      { id: 'u1', session_id: 's1', notebook_id: 'n1', role: 'user', content: 'Hello', created_at: '2026-01-01T00:00:00Z' },
      { id: 'a1', session_id: 's1', notebook_id: 'n1', role: 'assistant', content: 'Hi there', sources: [], created_at: '2026-01-01T00:00:01Z' },
    ];
    const rag = createRag({ messages });

    render(
      <RagSearchModal
        rag={rag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );

    expect(screen.getByText('Hello')).toBeInTheDocument();
    expect(screen.getByText('Hi there')).toBeInTheDocument();
  });

  it('shows streaming answer while asking', () => {
    const rag = createRag({
      isAskingRAG: true,
      ragAnswer: 'Streaming answer',
      ragStatus: 'thinking...',
    });

    render(
      <RagSearchModal
        rag={rag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );

    expect(screen.getByText('Streaming answer')).toBeInTheDocument();
    expect(screen.getByText('thinking...')).toBeInTheDocument();
  });

  it('keeps answer visible after onDone switches to assistant message', () => {
    const messages: RAGMessage[] = [
      { id: 'u1', session_id: 's1', notebook_id: 'n1', role: 'user', content: 'Q', created_at: '2026-01-01T00:00:00Z' },
      { id: 'a1', session_id: 's1', notebook_id: 'n1', role: 'assistant', content: 'Final answer', sources: [], created_at: '2026-01-01T00:00:01Z' },
    ];
    const rag = createRag({
      messages,
      isAskingRAG: false,
      ragAnswer: '',
      ragStatus: null,
    });

    render(
      <RagSearchModal
        rag={rag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );

    expect(screen.getByText('Final answer')).toBeInTheDocument();
    expect(screen.queryByText('thinking...')).not.toBeInTheDocument();
  });

  it('persists messages after close and reopen', () => {
    const messages: RAGMessage[] = [
      { id: 'a1', session_id: 's1', notebook_id: 'n1', role: 'assistant', content: 'Persistent answer', sources: [], created_at: '2026-01-01T00:00:00Z' },
    ];
    const rag = createRag({ messages });

    const { rerender, container } = render(
      <RagSearchModal
        rag={rag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );

    fireEvent.click(screen.getByTitle('关闭'));
    expect(rag.actions.setShowSearch).toHaveBeenCalledWith(false);

    const reopenedRag = createRag({ messages });
    rerender(
      <RagSearchModal
        rag={reopenedRag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );

    expect(container.querySelector('.rounded-2xl')).toBeInTheDocument();
    expect(screen.getByText('Persistent answer')).toBeInTheDocument();
  });

  it('renders source cards and triggers click handler', () => {
    const sources: RAGSource[] = [
      {
        chunk_id: 'c1',
        notebook_id: 'n1',
        notebook_title: 'Notebook',
        session_id: 's1',
        session_title: 'Session',
        source_type: 'ppt',
        snippet: 'Source snippet',
        score: 0.95,
        page: 2,
      },
    ];
    const messages: RAGMessage[] = [
      { id: 'a1', session_id: 's1', notebook_id: 'n1', role: 'assistant', content: 'Answer with sources', sources, created_at: '2026-01-01T00:00:00Z' },
    ];
    const rag = createRag({ messages });

    render(
      <RagSearchModal
        rag={rag as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useRAG').useRAG>}
        vectorIndex={vectorIndex as unknown as ReturnType<typeof import('@/pages/note-detail/hooks/useVectorIndex').useVectorIndex>}
        sessionId="s1"
        displayNotebook={{ id: 'n1' }}
        onRagSourceClick={onRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />,
    );

    expect(screen.getByText('Source snippet')).toBeInTheDocument();
    fireEvent.click(screen.getByText('Source snippet'));
    expect(onRagSourceClick).toHaveBeenCalledWith(sources[0], expect.any(Function));
  });
});
