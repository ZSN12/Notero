import { memo } from 'react';
import type { RAGSource } from '@/services/api';
import { getFreeNoteSourcePage } from '@/pages/pad/lib/ragSourceNavigation';

interface RagSourceCardsProps {
  sources: RAGSource[];
  onSourceClick: (source: RAGSource, closePanel?: () => void) => void;
  getSourceTypeLabel: (source: RAGSource) => string;
  onClose?: () => void;
}

function getNumberList(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item))
    .map((item) => item + 1);
}

function getFreeNoteTitle(source: RAGSource) {
  const title = source.metadata?.title;
  if (typeof title === 'string' && title.trim()) return title;
  const page = getFreeNoteSourcePage(source);
  return page ? `自由笔记 ${page}` : '自由笔记';
}

function getAiBlockHints(source: RAGSource) {
  const raw = source.metadata?.aiBlockTypes ?? source.metadata?.ai_block_types;
  if (!Array.isArray(raw)) return [];
  return raw.map((type) => {
    if (type === 'summary') return '含 AI 总结';
    if (type === 'quiz') return '含复习题';
    if (type === 'explanation') return '含课件解释';
    return null;
  }).filter(Boolean) as string[];
}

function RagSourceCards({ sources, onSourceClick, getSourceTypeLabel, onClose }: RagSourceCardsProps) {
  return (
    <div className="space-y-2">
      {sources.map((source, index) => {
        const freeNotePage = getFreeNoteSourcePage(source);
        const slideIndexes = getNumberList(source.metadata?.slideIndexes ?? source.metadata?.slide_indexes);
        const isFreeNote = source.source_type === 'free_note';
        const aiHints = getAiBlockHints(source);
        return (
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
                {isFreeNote
                  ? getFreeNoteTitle(source)
                  : source.source_type === 'web' && typeof source.metadata?.url === 'string'
                    ? source.metadata.url
                    : source.session_title}
              </span>
              {isFreeNote && freeNotePage ? (
                <span className="text-[10px] text-slate-400">自由笔记 · 第 {freeNotePage} 页</span>
              ) : source.page != null ? (
                <span className="text-[10px] text-slate-400">第 {source.page} 页</span>
              ) : null}
              {source.source_type !== 'web' && (
                <span className="ml-auto text-[10px] text-slate-400">{Math.round(source.score * 100)}%</span>
              )}
            </div>
            {isFreeNote && slideIndexes.length > 0 && (
              <p className="mb-1 text-[10px] text-slate-400">关联课件：{slideIndexes.join(', ')}</p>
            )}
            {isFreeNote && aiHints.length > 0 && (
              <p className="mb-1 text-[10px] text-blue-500">{aiHints.join(' · ')}</p>
            )}
            <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed line-clamp-2">{source.snippet}</p>
          </button>
        );
      })}
    </div>
  );
}

export default memo(RagSourceCards);
