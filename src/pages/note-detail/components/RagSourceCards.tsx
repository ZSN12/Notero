import { memo } from 'react';
import type { RAGSource } from '@/services/api';

interface RagSourceCardsProps {
  sources: RAGSource[];
  onSourceClick: (source: RAGSource, closePanel?: () => void) => void;
  getSourceTypeLabel: (source: RAGSource) => string;
  onClose?: () => void;
}

function RagSourceCards({ sources, onSourceClick, getSourceTypeLabel, onClose }: RagSourceCardsProps) {
  return (
    <div className="space-y-2">
      {sources.map((source, index) => (
        <button
          key={`${source.chunk_id}-${index}`}
          onClick={() => onSourceClick(source, onClose)}
          className="w-full text-left rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50/80 dark:bg-slate-900/30 px-3 py-2 hover:border-violet-200 hover:bg-violet-50/60 dark:hover:bg-violet-900/20 transition-colors"
        >
          <div className="flex items-center gap-2 mb-1">
            <span className="text-[10px] font-semibold text-violet-600 dark:text-violet-300 bg-violet-100 dark:bg-violet-900/40 rounded-full px-2 py-0.5">
              [{index + 1}] {getSourceTypeLabel(source)}
            </span>
            <span className="text-[10px] text-slate-400 truncate">
              {source.source_type === 'web' && typeof source.metadata?.url === 'string'
                ? source.metadata.url
                : source.session_title}
            </span>
            {source.page != null && <span className="text-[10px] text-slate-400">第 {source.page} 页</span>}
            {source.source_type !== 'web' && (
              <span className="ml-auto text-[10px] text-slate-400">{Math.round(source.score * 100)}%</span>
            )}
          </div>
          <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-2">{source.snippet}</p>
        </button>
      ))}
    </div>
  );
}

export default memo(RagSourceCards);
