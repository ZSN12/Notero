import RagChatPanel from '@/pages/note-detail/components/RagChatPanel';
import type { useRAG } from '@/pages/note-detail/hooks/useRAG';
import type { useVectorIndex } from '@/pages/note-detail/hooks/useVectorIndex';
import type { RAGSource } from '@/services/api';

interface RagSearchModalProps {
  rag: ReturnType<typeof useRAG>;
  vectorIndex: ReturnType<typeof useVectorIndex>;
  sessionId?: string;
  displayNotebook?: { id?: string } | null;
  onRagSourceClick: (source: RAGSource, closePanel?: () => void) => void;
  getRagSourceTypeLabel: (source: RAGSource) => string;
}

export function RagSearchModal({
  rag,
  vectorIndex,
  sessionId,
  displayNotebook,
  onRagSourceClick,
  getRagSourceTypeLabel,
}: RagSearchModalProps) {
  if (!rag.state.showSearch) return null;

  const close = () => rag.actions.setShowSearch(false);

  const ask = () => {
    rag.actions.handleRAGAsk(sessionId, displayNotebook?.id, vectorIndex.actions.ensureIndexed);
  };

  const clear = () => {
    rag.actions.clearMessages(sessionId);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-16 sm:pt-20 px-4 bg-black/30 backdrop-blur-sm"
      onClick={close}
    >
      <div
        className="w-full max-w-2xl h-[80vh] bg-white dark:bg-slate-800 rounded-2xl shadow-xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <RagChatPanel
          messages={rag.state.messages}
          searchQuery={rag.state.searchQuery}
          onSearchQueryChange={rag.actions.setSearchQuery}
          onSubmit={ask}
          isAskingRAG={rag.state.isAskingRAG}
          searchScope={rag.state.searchScope}
          onSearchScopeChange={rag.actions.setSearchScope}
          ragError={rag.state.ragError}
          ragStatus={rag.state.ragStatus}
          streamingAnswer={rag.state.ragAnswer}
          streamingSources={rag.state.ragSources}
          onSourceClick={onRagSourceClick}
          getSourceTypeLabel={getRagSourceTypeLabel}
          onClose={close}
          onClear={clear}
        />
      </div>
    </div>
  );
}
