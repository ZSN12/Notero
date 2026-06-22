import { ArrowLeft, ChevronDown, Download, Share2, Search, BrainCircuit, ClipboardCheck, Database, RefreshCw, Loader2 } from 'lucide-react';
import ThemeToggle from '@/components/ThemeToggle';
import { getAvatarUrl } from '@/services/auth';
import type { UserProfile } from '@/services/auth';
import { layoutFromNoteParts } from '@/lib/noteLayout';
import type { ContentBlock } from '@/services/api';
import type { StudentNote } from '@/pages/note-detail/types';

import type { useExport } from '@/pages/note-detail/useExport';
import type { useShare } from '@/pages/note-detail/hooks/useShare';
import type { useRAG } from '@/pages/note-detail/hooks/useRAG';
import type { useMindMap } from '@/pages/note-detail/hooks/useMindMap';
import type { useQuiz } from '@/pages/note-detail/hooks/useQuiz';
import type { useVectorIndex } from '@/pages/note-detail/hooks/useVectorIndex';

interface NoteDetailTopNavProps {
  displaySession?: { title?: string } | null;
  displayNotebook?: { title?: string } | null;
  profile: UserProfile | null;
  sessionId?: string;
  onBack: () => void;
  onNavigateProfile: () => void;
  transcriptText: string;
  contentBlocks: ContentBlock[];
  notes: StudentNote[];
  exportTools: ReturnType<typeof useExport>;
  share: ReturnType<typeof useShare>;
  rag: ReturnType<typeof useRAG>;
  mindMap: ReturnType<typeof useMindMap>;
  quiz: ReturnType<typeof useQuiz>;
  vectorIndex: ReturnType<typeof useVectorIndex>;
}

export function NoteDetailTopNav({
  displaySession,
  displayNotebook,
  profile,
  sessionId,
  onBack,
  onNavigateProfile,
  transcriptText,
  contentBlocks,
  notes,
  exportTools,
  share,
  rag,
  mindMap,
  quiz,
  vectorIndex,
}: NoteDetailTopNavProps) {
  const renderVectorIndexBadge = () => {
    const status = vectorIndex.state.vectorStatus?.status;
    if (status === 'indexed') {
      return (
        <>
          <Database className="w-3 h-3 text-green-500" />
          <span className="text-green-600 dark:text-green-400">已索引 {vectorIndex.state.vectorStatus?.chunk_count}条</span>
          <button
            onClick={vectorIndex.actions.handleRebuildIndex}
            disabled={vectorIndex.state.isRebuilding}
            className="ml-1 text-slate-400 hover:text-blue-500"
            title="重建索引"
          >
            <RefreshCw className={`w-3 h-3 ${vectorIndex.state.isRebuilding ? 'animate-spin' : ''}`} />
          </button>
        </>
      );
    }
    if (status === 'stale') {
      return (
        <>
          <Database className="w-3 h-3 text-amber-500" />
          <span className="text-amber-600 dark:text-amber-400">内容已变化</span>
          <button
            onClick={vectorIndex.actions.handleRebuildIndex}
            disabled={vectorIndex.state.isRebuilding}
            className="ml-1 text-amber-500 hover:text-blue-500 font-medium"
            title="重建索引"
          >
            {vectorIndex.state.isRebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : '重建'}
          </button>
        </>
      );
    }
    if (status === 'not_indexed') {
      return (
        <>
          <Database className="w-3 h-3 text-slate-400" />
          <button
            onClick={vectorIndex.actions.handleRebuildIndex}
            disabled={vectorIndex.state.isRebuilding}
            className="text-slate-500 hover:text-blue-500"
            title="建立索引"
          >
            {vectorIndex.state.isRebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : '建立索引'}
          </button>
        </>
      );
    }
    return <span className="text-slate-400">无内容</span>;
  };

  return (
    <nav className="flex-shrink-0 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md border-b border-slate-200/60 dark:border-slate-800/60">
      <div className="px-3 py-2 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onBack}
            className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <ArrowLeft className="w-5 h-5" />
          </button>
          <div className="min-w-0">
            <h1 className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">
              {displaySession?.title || '课次'}
            </h1>
            <p className="text-xs text-slate-400 truncate">{displayNotebook?.title}</p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="relative">
            <button
              onClick={() => exportTools.actions.setShowExportMenu(!exportTools.state.showExportMenu)}
              className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors"
              title="导出"
            >
              <Download className="w-3.5 h-3.5" />
              <ChevronDown className="w-3 h-3" />
            </button>
            {exportTools.state.showExportMenu && (
              <div className="absolute right-0 top-full mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg py-1 z-50 min-w-[140px]">
                <button
                  onClick={() => {
                    const blocks = layoutFromNoteParts(transcriptText, contentBlocks, notes);
                    exportTools.actions.exportMarkdown(transcriptText, notes, blocks);
                  }}
                  className="w-full text-left px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                >
                  📝 导出 Markdown
                </button>
                <button
                  onClick={() => {
                    const blocks = layoutFromNoteParts(transcriptText, contentBlocks, notes);
                    exportTools.actions.exportPDF(transcriptText, notes, blocks);
                  }}
                  disabled={exportTools.state.isExportingPDF}
                  className="w-full text-left px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
                >
                  {exportTools.state.isExportingPDF ? '⏳ 导出中...' : '📄 导出 PDF'}
                </button>
                <button
                  onClick={() => exportTools.actions.exportNotebookPackage()}
                  disabled={exportTools.state.isExportingPackage}
                  className="w-full text-left px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
                >
                  {exportTools.state.isExportingPackage ? '⏳ 导出中...' : '📦 导出笔记本包'}
                </button>
              </div>
            )}
          </div>
          <button
            onClick={() =>
              share.actions.handleShareSession(sessionId!, share.state.shareExpiresIn, share.state.shareMaxViewsInput)
            }
            className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors"
            title="分享"
          >
            <Share2 className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => {
              const willOpen = !rag.state.showSearch;
              rag.actions.setShowSearch(willOpen);
              if (willOpen) {
                rag.actions.loadMessages(sessionId);
                vectorIndex.actions.ensureIndexed();
              }
            }}
            className={`flex items-center gap-1 px-3 py-2 text-sm rounded-lg transition-colors ${
              rag.state.showSearch
                ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20'
                : 'text-slate-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20'
            }`}
            title="搜索"
          >
            <Search className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => {
              mindMap.actions.setShowMindMap(true);
              vectorIndex.actions.ensureIndexed();
            }}
            className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-900/20 rounded-lg transition-colors"
            title="知识导图"
          >
            <BrainCircuit className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={() => {
              quiz.actions.setShowQuiz(true);
              quiz.actions.setActiveQuiz(null);
              quiz.actions.setQuizSubmitted(false);
              quiz.actions.setQuizAnswers({});
              quiz.actions.setQuizError(null);
              vectorIndex.actions.ensureIndexed();
            }}
            className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 rounded-lg transition-colors"
            title="测验"
          >
            <ClipboardCheck className="w-3.5 h-3.5" />
          </button>
          <div className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
            {renderVectorIndexBadge()}
          </div>
          <ThemeToggle />
          <button onClick={onNavigateProfile} className="cursor-pointer">
            {profile?.avatar_url ? (
              <img src={getAvatarUrl(profile.id)} alt="avatar" className="w-7 h-7 rounded-full object-cover" />
            ) : (
              <div className="w-7 h-7 rounded-full bg-gradient-to-br from-blue-400 to-blue-600 flex items-center justify-center text-white text-xs font-bold">
                {(profile?.username || profile?.email || 'U')[0].toUpperCase()}
              </div>
            )}
          </button>
        </div>
      </div>
    </nav>
  );
}
