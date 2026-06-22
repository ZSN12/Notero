import { API_BASE, authHeaders } from './core';
import type { RAGCallbacks, RAGMessage, RAGSource } from './types';

export function askRAG(
  query: string,
  sessionId: string | undefined,
  notebookId: string | undefined,
  callbacks: RAGCallbacks,
): { abort: () => void } {
  const controller = new AbortController();

  const run = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/rag/ask`, {
        method: 'POST',
        headers: { ...authHeaders(), 'Content-Type': 'application/json' },
        body: JSON.stringify({ query, session_id: sessionId, notebook_id: notebookId, top_k: 5 }),
        signal: controller.signal,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: '请求失败' }));
        callbacks.onError(err.detail || `HTTP ${res.status}`);
        return;
      }

      const reader = res.body?.getReader();
      if (!reader) {
        callbacks.onError('No response body');
        return;
      }

      const decoder = new TextDecoder();
      let buffer = '';
      let answerText = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const event = JSON.parse(line.slice(6));
              switch (event.type) {
                case 'status':
                  callbacks.onStatus(event.message || '');
                  break;
                case 'chunk':
                  answerText += event.text || '';
                  callbacks.onChunk(answerText);
                  break;
                case 'sources':
                  callbacks.onSources(event.sources || []);
                  break;
                case 'done':
                  callbacks.onDone();
                  break;
                case 'error':
                  callbacks.onError(event.detail || 'Unknown error');
                  break;
              }
            } catch (parseErr) {
              console.warn('[askRAG] SSE parse error:', parseErr);
              callbacks.onError('AI 回答流解析失败');
            }
          }
        }
      }
    } catch (err: unknown) {
      if (err instanceof Error && err.name === 'AbortError') return;
      callbacks.onError(err instanceof Error ? err.message : '请求失败');
    }
  };

  run();
  return { abort: () => controller.abort() };
}

export async function fetchRAGMessages(sessionId: string): Promise<RAGMessage[]> {
  const res = await fetch(
    `${API_BASE}/api/rag/messages?session_id=${encodeURIComponent(sessionId)}&limit=200`,
    {
      headers: authHeaders(),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  const data = (await res.json()) as RAGMessage[];
  return data.map((m) => ({
    ...m,
    sources: m.sources || [],
  }));
}

export async function clearRAGMessages(sessionId: string): Promise<{ deleted: number }> {
  const res = await fetch(
    `${API_BASE}/api/rag/messages?session_id=${encodeURIComponent(sessionId)}`,
    {
      method: 'DELETE',
      headers: authHeaders(),
    },
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: '请求失败' }));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json() as Promise<{ deleted: number }>;
}

export function serializeRAGSources(sources?: RAGSource[]): RAGSource[] {
  return (sources || []).map((s) => ({
    chunk_id: s.chunk_id,
    notebook_id: s.notebook_id,
    notebook_title: s.notebook_title,
    session_id: s.session_id,
    session_title: s.session_title,
    source_type: s.source_type,
    snippet: s.snippet,
    score: s.score,
    page: s.page ?? null,
    block_id: s.block_id ?? null,
    chunk_index: s.chunk_index ?? null,
    metadata: s.metadata || {},
  }));
}
