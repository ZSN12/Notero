import { API_BASE, authHeaders } from './core';
import type { RAGCallbacks, RAGSource } from './types';

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
