import { memo, useEffect, useRef } from 'react';
import { Loader2, Sparkles, Trash2, X, ChevronDown } from 'lucide-react';
import type { RAGMessage, RAGSource } from '@/services/api';
import RagSourceCards from './RagSourceCards';

interface RagChatPanelProps {
  messages: RAGMessage[];
  searchQuery: string;
  onSearchQueryChange: (value: string) => void;
  onSubmit: () => void;
  isAskingRAG: boolean;
  searchScope: 'session' | 'notebook';
  onSearchScopeChange: (scope: 'session' | 'notebook') => void;
  ragError: string | null;
  ragStatus: string | null;
  streamingAnswer: string;
  streamingSources: RAGSource[];
  onSourceClick: (source: RAGSource, closePanel?: () => void) => void;
  getSourceTypeLabel: (source: RAGSource) => string;
  onClose: () => void;
  onClear: () => void;
}

function RagChatPanel({
  messages,
  searchQuery,
  onSearchQueryChange,
  onSubmit,
  isAskingRAG,
  searchScope,
  onSearchScopeChange,
  ragError,
  ragStatus,
  streamingAnswer,
  streamingSources,
  onSourceClick,
  getSourceTypeLabel,
  onClose,
  onClear,
}: RagChatPanelProps) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingAnswer, ragStatus]);

  const hasContent = messages.length > 0 || streamingAnswer || streamingSources.length > 0 || ragError || ragStatus;

  return (
    <div className="flex flex-col h-full max-h-[80vh]">
      {/* Header */}
      <div className="flex items-center justify-between gap-2 px-4 py-3 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-200">
          <Sparkles className="w-4 h-4 text-violet-400" />
          <span>AI 课堂问答</span>
          {messages.length > 0 && (
            <span className="text-[10px] text-slate-400 font-normal">({messages.length} 条消息)</span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {messages.length > 0 && (
            <button
              onClick={onClear}
              title="清空对话"
              className="p-1.5 rounded-md text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
          <button
            onClick={onClose}
            title="关闭"
            aria-label="关闭"
            className="p-1.5 rounded-md text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4 bg-slate-50/50 dark:bg-slate-900/30">
        {!hasContent && (
          <div className="py-12 text-center text-xs text-slate-400">
            <p>输入问题，AI 将基于课堂资料回答</p>
            <p className="mt-1">可以连续追问，例如“再展开讲讲第二点”</p>
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
          >
            <div
              className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap ${
                msg.role === 'user'
                  ? 'bg-violet-500 text-white rounded-br-md'
                  : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 rounded-bl-md shadow-sm'
              }`}
            >
              {msg.content}
              {msg.role === 'assistant' && (msg.sources?.length ?? 0) > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
                  <button
                    onClick={(e) => {
                      const el = e.currentTarget.nextElementSibling as HTMLElement | null;
                      if (el) el.classList.toggle('hidden');
                    }}
                    className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-violet-500 transition-colors"
                  >
                    <ChevronDown className="w-3 h-3" />
                    参考来源 ({msg.sources!.length})
                  </button>
                  <div className="hidden mt-2">
                    <RagSourceCards
                      sources={msg.sources!}
                      onSourceClick={onSourceClick}
                      getSourceTypeLabel={getSourceTypeLabel}
                      onClose={onClose}
                    />
                  </div>
                </div>
              )}
            </div>
          </div>
        ))}

        {streamingAnswer && (
          <div className="flex justify-start">
            <div className="max-w-[85%] rounded-2xl rounded-bl-md px-4 py-2.5 text-sm leading-relaxed whitespace-pre-wrap bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border border-slate-200 dark:border-slate-700 shadow-sm">
              {streamingAnswer}
              {streamingSources.length > 0 && (
                <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-700">
                  <p className="text-[10px] text-slate-400 mb-2">参考来源</p>
                  <RagSourceCards
                    sources={streamingSources}
                    onSourceClick={onSourceClick}
                    getSourceTypeLabel={getSourceTypeLabel}
                    onClose={onClose}
                  />
                </div>
              )}
            </div>
          </div>
        )}

        {ragStatus && (
          <div className="flex justify-center">
            <div className="flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-violet-50 dark:bg-violet-900/20 text-[11px] text-violet-600 dark:text-violet-300">
              <Loader2 className="w-3 h-3 animate-spin" />
              {ragStatus}
            </div>
          </div>
        )}

        {ragError && (
          <div className="flex justify-center">
            <div className="px-3 py-2 rounded-lg bg-red-50 dark:bg-red-900/20 text-xs text-red-600 dark:text-red-300 max-w-[90%]">
              {ragError}
            </div>
          </div>
        )}
      </div>

      {/* Input */}
      <div className="p-3 border-t border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800">
        <div className="flex items-center gap-2">
          <input
            value={searchQuery}
            onChange={(e) => onSearchQueryChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') onSubmit();
            }}
            placeholder="输入问题..."
            className="flex-1 text-sm bg-slate-50 dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg px-3 py-2 outline-none text-slate-700 dark:text-slate-200 placeholder:text-slate-400 focus:ring-2 focus:ring-violet-100 dark:focus:ring-violet-900/30"
            disabled={isAskingRAG}
          />
          <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden flex-shrink-0">
            <button
              onClick={() => onSearchScopeChange('session')}
              className={`px-2 py-2 text-[10px] font-medium transition-colors ${
                searchScope === 'session'
                  ? 'bg-blue-500 text-white'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              本课次
            </button>
            <button
              onClick={() => onSearchScopeChange('notebook')}
              className={`px-2 py-2 text-[10px] font-medium transition-colors ${
                searchScope === 'notebook'
                  ? 'bg-blue-500 text-white'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
              }`}
            >
              本课程
            </button>
          </div>
          <button
            onClick={onSubmit}
            disabled={isAskingRAG || !searchQuery.trim()}
            className="px-4 py-2 text-xs font-medium text-white bg-violet-500 rounded-lg hover:bg-violet-600 disabled:opacity-50 flex-shrink-0"
          >
            {isAskingRAG ? '...' : '提问'}
          </button>
        </div>
      </div>
    </div>
  );
}

export default memo(RagChatPanel);
