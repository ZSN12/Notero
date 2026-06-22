import { X, BrainCircuit, Copy, Check, RefreshCw, Loader2, AlertCircle, FileText, Trash2 } from 'lucide-react';
import MindMapCanvas from '@/pages/note-detail/MindMapCanvas';
import type { useMindMap } from '@/pages/note-detail/hooks/useMindMap';
import type { usePPT } from '@/pages/note-detail/usePPT';

interface MindMapDrawerProps {
  mindMap: ReturnType<typeof useMindMap>;
  ppt: ReturnType<typeof usePPT>;
  displaySession?: { title?: string } | null;
  displayNotebook?: { title?: string } | null;
  sessionId?: string;
  paragraphContainerRef: React.RefObject<HTMLDivElement>;
}

export function MindMapDrawer({
  mindMap,
  ppt,
  displaySession,
  displayNotebook,
  sessionId,
  paragraphContainerRef,
}: MindMapDrawerProps) {
  if (!mindMap.state.showMindMap) return null;

  return (
    <div className="fixed inset-0 z-50 flex">
      <div
        className="absolute inset-0 bg-black/30 backdrop-blur-sm"
        onClick={() => mindMap.actions.setShowMindMap(false)}
      />
      <div
        className="relative ml-auto w-full max-w-[90vw] h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
          <div className="flex items-center gap-2">
            <BrainCircuit className="w-5 h-5 text-purple-500" />
            <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">知识导图</h2>
            {mindMap.state.mindMapStatus?.mind_map?.title && mindMap.state.mindMapStatus.status === 'ready' && (
              <span className="text-sm text-slate-400 ml-2">
                — {mindMap.state.mindMapStatus.mind_map.title}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2">
            {mindMap.state.mindMapStatus?.mind_map && (
              <button
                onClick={mindMap.actions.handleCopyMindMapOutline}
                className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title="复制大纲"
              >
                {mindMap.state.copyMindMapSuccess ? (
                  <Check className="w-4 h-4 text-green-500" />
                ) : (
                  <Copy className="w-4 h-4" />
                )}
              </button>
            )}
            {mindMap.state.mindMapStatus?.status === 'ready' && (
              <button
                onClick={() => mindMap.actions.handleGenerateMindMap(mindMap.state.mindMapStatus?.status === 'ready')}
                disabled={mindMap.state.isGeneratingMindMap}
                className="px-3 py-1.5 text-xs font-medium text-purple-600 bg-purple-50 dark:bg-purple-900/20 rounded-lg hover:bg-purple-100 dark:hover:bg-purple-900/30 disabled:opacity-50 flex items-center gap-1"
                title="重新生成"
              >
                <RefreshCw className={`w-3.5 h-3.5 ${mindMap.state.isGeneratingMindMap ? 'animate-spin' : ''}`} />
                重新生成
              </button>
            )}
            {mindMap.state.mindMapStatus?.status === 'ready' && (
              <button
                onClick={mindMap.actions.handleDeleteMindMap}
                className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                title="删除导图"
              >
                <Trash2 className="w-4 h-4" />
              </button>
            )}
            <button
              onClick={() => mindMap.actions.setShowMindMap(false)}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-hidden">
          {mindMap.state.mindMapStatus?.status === 'empty' ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-2">
              <FileText className="w-10 h-10 opacity-30" />
              <p className="text-sm">当前课次没有可生成的内容</p>
            </div>
          ) : mindMap.state.mindMapStatus?.status === 'not_generated' ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-4">
              <BrainCircuit className="w-10 h-10 opacity-30" />
              <p className="text-sm">{'尚未生成知识导图'}</p>
              <button
                onClick={() => mindMap.actions.handleGenerateMindMap()}
                disabled={mindMap.state.isGeneratingMindMap}
                className="px-4 py-2 text-sm font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50 flex items-center gap-2"
              >
                {mindMap.state.isGeneratingMindMap ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {'生成导图'}
              </button>
            </div>
          ) : mindMap.state.mindMapStatus?.status === 'error' ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-4">
              <AlertCircle className="w-10 h-10 text-red-400 opacity-50" />
              <p className="text-sm text-red-500">{mindMap.state.mindMapStatus.error || '生成失败'}</p>
              <button
                onClick={() => mindMap.actions.handleGenerateMindMap()}
                disabled={mindMap.state.isGeneratingMindMap}
                className="px-4 py-2 text-sm font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50"
              >
                重试
              </button>
            </div>
          ) : mindMap.state.mindMapStatus?.status === 'queued' ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3">
              <Loader2 className="w-8 h-8 text-purple-400" />
              <p className="text-sm">{mindMap.state.mindMapStatus.message || '导图等待前置任务执行...'}</p>
            </div>
          ) : mindMap.state.isGeneratingMindMap || mindMap.state.mindMapStatus?.status === 'generating' ? (
            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3">
              <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
              <p className="text-sm">AI 正在分析课程内容，生成知识导图...</p>
              {typeof mindMap.state.mindMapStatus?.progress === 'number' && (
                <p className="text-xs text-slate-400">
                  进度 {Math.round(mindMap.state.mindMapStatus.progress * 100)}%
                </p>
              )}
            </div>
          ) : (mindMap.state.mindMapStatus?.status === 'stale' ||
              mindMap.state.mindMapStatus?.status === 'ready') &&
            mindMap.state.mindMapStatus?.mind_map?.nodes?.length ? (
            <div className="flex flex-col h-full">
              {mindMap.state.mindMapStatus?.status === 'stale' && (
                <div className="flex-shrink-0 mx-5 mt-4 p-3 bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-xs text-amber-700 dark:text-amber-400">
                    <AlertCircle className="w-4 h-4 flex-shrink-0" />
                    <span>笔记内容已变化，导图可能与当前内容不符</span>
                  </div>
                  <button
                    onClick={() => mindMap.actions.handleGenerateMindMap(true)}
                    disabled={mindMap.state.isGeneratingMindMap}
                    className="px-2.5 py-1.5 text-xs font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50 flex items-center gap-1"
                  >
                    {mindMap.state.isGeneratingMindMap ? (
                      <Loader2 className="w-3 h-3 animate-spin" />
                    ) : (
                      <RefreshCw className="w-3 h-3" />
                    )}
                    重新生成
                  </button>
                </div>
              )}
              <div className="flex-1 overflow-hidden">
                <MindMapCanvas
                  data={mindMap.state.mindMapStatus.mind_map!}
                  rootTitle={displaySession?.title || displayNotebook?.title || '当前课次'}
                  sessionId={sessionId || ''}
                  onSelect={mindMap.actions.setSelectedMindMapNode}
                  selectedNode={mindMap.state.selectedMindMapNode}
                  onSourceClick={(source: { source_type: string; page?: number | null; block_id?: string; snippet?: string }) => {
                    if (source.source_type === 'ppt' && source.page != null) {
                      ppt.actions.setActiveSlideIndex(source.page - 1);
                      return;
                    }
                    if (
                      (source.source_type === 'transcript' || source.source_type === 'note') &&
                      source.snippet
                    ) {
                      mindMap.actions.setShowMindMap(false);
                      setTimeout(() => {
                        const container = paragraphContainerRef.current;
                        if (!container) return;
                        const walker = document.createTreeWalker(container, NodeFilter.SHOW_TEXT);
                        const lowerSnippet = source.snippet!.toLowerCase();
                        let node;
                        while ((node = walker.nextNode() as Text | null)) {
                          if (node.textContent?.toLowerCase().includes(lowerSnippet)) {
                            const el = node.parentElement;
                            if (el) {
                              el.scrollIntoView({ behavior: 'smooth', block: 'center' });
                              el.classList.add('bg-yellow-100', 'dark:bg-yellow-900/30', 'transition-colors');
                              setTimeout(() => {
                                el.classList.remove('bg-yellow-100', 'dark:bg-yellow-900/30', 'transition-colors');
                              }, 3000);
                            }
                            break;
                          }
                        }
                      }, 300);
                    }
                  }}
                />
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-4">
              <BrainCircuit className="w-10 h-10 opacity-30" />
              <p className="text-sm">导图数据为空，请尝试重新生成</p>
              <button
                onClick={() => mindMap.actions.handleGenerateMindMap(true)}
                disabled={mindMap.state.isGeneratingMindMap}
                className="px-4 py-2 text-sm font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50 flex items-center gap-2"
              >
                {mindMap.state.isGeneratingMindMap ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                重新生成
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
