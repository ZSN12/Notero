import { useState, useCallback, useRef } from 'react';
import { askRAG, fetchRAGMessages, clearRAGMessages } from '@/services/api';
import type { RAGMessage, RAGSource } from '@/services/api';
import { getErrorMessage } from '@/lib/error';

export function useRAG() {
  const [showSearch, setShowSearch] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchScope, setSearchScope] = useState<'session' | 'notebook'>('session');
  const [messages, setMessages] = useState<RAGMessage[]>([]);
  const [ragAnswer, setRagAnswer] = useState('');
  const [ragSources, setRagSources] = useState<RAGSource[]>([]);
  const [isAskingRAG, setIsAskingRAG] = useState(false);
  const [ragError, setRagError] = useState<string | null>(null);
  const [ragStatus, setRagStatus] = useState<string | null>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const loadMessages = useCallback(async (sessionId: string | undefined) => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    try {
      const data = await fetchRAGMessages(sessionId);
      setMessages(data);
    } catch (err: unknown) {
      console.warn('[useRAG] loadMessages failed:', getErrorMessage(err));
      setMessages([]);
    }
  }, []);

  const clearMessages = useCallback(async (sessionId: string | undefined) => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    try {
      await clearRAGMessages(sessionId);
      setMessages([]);
    } catch (err: unknown) {
      setRagError(getErrorMessage(err) || '清空对话失败');
    }
  }, []);

  const handleRAGAsk = useCallback(
    async (
      sessionId: string | undefined,
      notebookId: string | undefined,
      ensureIndexed?: () => Promise<void>,
    ) => {
      if (!searchQuery.trim() || isAskingRAG) return;

      abortRef.current?.();
      const query = searchQuery.trim();
      const userMessage: RAGMessage = {
        id: `optimistic-${Date.now()}`,
        session_id: sessionId || '',
        notebook_id: notebookId || '',
        role: 'user',
        content: query,
        sources: [],
        created_at: new Date().toISOString(),
      };

      setMessages((prev) => [...prev, userMessage]);
      setIsAskingRAG(true);
      setRagAnswer('');
      setRagSources([]);
      setRagError(null);
      setRagStatus('正在检查知识索引...');

      try {
        await ensureIndexed?.();
      } catch (err: unknown) {
        setRagError(getErrorMessage(err) || '知识索引建立失败，请稍后重试');
        setIsAskingRAG(false);
        setRagStatus(null);
        return;
      }

      let finalAnswer = '';
      let finalSources: RAGSource[] = [];

      const { abort } = askRAG(
        query,
        searchScope === 'session' ? sessionId : undefined,
        searchScope === 'notebook' ? notebookId : undefined,
        {
          onStatus: (message: string) => setRagStatus(message || null),
          onChunk: (text: string) => {
            finalAnswer = text;
            setRagAnswer(text);
          },
          onSources: (sources: RAGSource[]) => {
            finalSources = sources;
            setRagSources(sources);
          },
          onDone: () => {
            setIsAskingRAG(false);
            setRagStatus(null);
            setRagAnswer('');
            setRagSources([]);
            setMessages((prev) => {
              // Replace optimistic user message with actual flow by removing it
              // and appending both user + assistant messages.
              const withoutOptimistic = prev.filter((m) => m.id !== userMessage.id);
              return [
                ...withoutOptimistic,
                {
                  ...userMessage,
                  id: `user-${Date.now()}`,
                },
                {
                  id: `assistant-${Date.now()}`,
                  session_id: sessionId || '',
                  notebook_id: notebookId || '',
                  role: 'assistant',
                  content: finalAnswer,
                  sources: finalSources,
                  created_at: new Date().toISOString(),
                },
              ];
            });
            setSearchQuery('');
            abortRef.current = null;
          },
          onError: (err: string) => {
            setRagError(err);
            setIsAskingRAG(false);
            setRagStatus(null);
            setRagAnswer('');
            setRagSources([]);
            // Remove optimistic user message on error
            setMessages((prev) => prev.filter((m) => m.id !== userMessage.id));
            abortRef.current = null;
          },
        },
      );

      abortRef.current = abort;
    },
    [searchQuery, isAskingRAG, searchScope],
  );

  return {
    state: {
      showSearch,
      searchQuery,
      searchScope,
      messages,
      ragAnswer,
      ragSources,
      isAskingRAG,
      ragError,
      ragStatus,
    },
    actions: {
      setShowSearch,
      setSearchQuery,
      setSearchScope,
      loadMessages,
      clearMessages,
      handleRAGAsk,
    },
  };
}
