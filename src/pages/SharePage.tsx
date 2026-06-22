import { useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, Loader2, FileText, Edit3, ImagePlus, BookOpen, Clock, Tag, ShieldAlert, Link2Off, ImageOff } from 'lucide-react';
import { useState, useEffect, useCallback } from 'react';
import ThemeToggle from '@/components/ThemeToggle';
import { getShareMediaUrl } from '@/services/api';
import { sanitizeHTML } from '@/lib/sanitize';
import type { NoteLayoutBlock } from '@/lib/noteLayout';
import { API_BASE } from '@/config';

interface TranscriptChunk {
  chunk_index?: number;
  text?: string;
}

interface SharedData {
  session: {
    id: string;
    notebook_id: string;
    title: string;
    summary: string | null;
    keywords: string[];
    duration: string | null;
    status: string;
  };
  notebook: {
    id: string;
    title: string;
  };
  note: {
    content: string | null;
    transcript: TranscriptChunk[] | null;
    ppt_images: unknown[] | null;
    layout_blocks: NoteLayoutBlock[] | null;
  } | null;
}

function fallbackLayoutFromNote(note: SharedData['note']): NoteLayoutBlock[] {
  if (!note) return [];
  let transcriptText = '';
  if (note.transcript && Array.isArray(note.transcript) && note.transcript.length > 0) {
    transcriptText = note.transcript
      .sort((a, b) => (a.chunk_index || 0) - (b.chunk_index || 0))
      .map((chunk) => chunk.text || '')
      .join(' ')
      .trim();
  }
  if (!transcriptText && note.content) {
    const match = note.content.match(/^## 语音转文字\n\n([\s\S]*?)(?:\n\n---\n\n[\s\S]*)?$/);
    if (match?.[1]?.trim()) transcriptText = match[1].trim();
  }
  const blocks: NoteLayoutBlock[] = [];
  if (transcriptText) {
    transcriptText.split(/\n{2,}/).filter(Boolean).forEach((para, i) => {
      blocks.push({ id: `transcript-${i + 1}`, type: 'transcript', content: para.trim() });
    });
  }
  if (note.content) {
    const match = note.content.match(/^## 语音转文字\n\n([\s\S]*?)\n\n---\n\n([\s\S]*)$/);
    if (match?.[2]?.trim()) {
      blocks.push({ id: `note-1`, type: 'note', content: match[2].trim() });
    }
  }
  return blocks;
}

export default function SharePage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const [searchParams] = useSearchParams();
  const shareToken = searchParams.get('token') || '';
  const navigate = useNavigate();

  const [data, setData] = useState<SharedData | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<{ title: string; message: string } | null>(null);

  useEffect(() => {
    const loadSharedSession = async () => {
      if (!sessionId) return;
      setIsLoading(true);
      setError(null);
      try {
        if (!shareToken) {
          setError({ title: '缺少分享令牌', message: '分享链接不完整，请检查链接是否包含 token 参数' });
          return;
        }
        const res = await fetch(`${API_BASE}/api/public/share/${sessionId}?token=${encodeURIComponent(shareToken)}`);
        if (!res.ok) {
          if (res.status === 403) {
            setError({ title: '分享已关闭或链接无效', message: '该课次可能已取消分享，或分享链接已过期' });
          } else if (res.status === 404) {
            setError({ title: '课次不存在', message: '该课次可能已被删除' });
          } else {
            setError({ title: '加载失败', message: '请稍后重试' });
          }
          return;
        }
        const result = await res.json();
        setData(result);
      } catch {
        setError({ title: '网络错误', message: '请检查网络后重试' });
      } finally {
        setIsLoading(false);
      }
    };
    loadSharedSession();
  }, [sessionId, shareToken]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
          <span className="text-sm text-slate-400">加载中...</span>
        </div>
      </div>
    );
  }

  if (error || !data) {
    const ErrorIcon = error?.title === '分享已关闭或链接无效' ? Link2Off : ShieldAlert;
    return (
      <div className="min-h-screen flex flex-col items-center justify-center bg-slate-50 dark:bg-slate-950 gap-4 px-4">
        {error && (
          <div className="w-14 h-14 rounded-full bg-red-50 dark:bg-red-900/20 flex items-center justify-center mb-2">
            <ErrorIcon className="w-7 h-7 text-red-400" />
          </div>
        )}
        <h2 className="text-lg font-semibold text-slate-700 dark:text-slate-300">{error?.title || '课次不存在'}</h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 text-center max-w-sm">{error?.message || '该课次可能已被删除或分享链接无效'}</p>
        <button onClick={() => navigate('/')} className="mt-2 px-4 py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-colors">返回首页</button>
      </div>
    );
  }

  const { session, notebook, note } = data;
  const blocks = note?.layout_blocks?.length ? note.layout_blocks : fallbackLayoutFromNote(note);

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* ---- Top Nav ---- */}
      <nav className="flex-shrink-0 sticky top-0 z-40 backdrop-blur-xl bg-white/70 dark:bg-slate-900/70 border-b border-slate-200/60 dark:border-slate-800/60">
        <div className="px-4 md:px-6 py-2 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => navigate('/')}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div className="min-w-0">
              <h1 className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">
                {session.title}
              </h1>
              <p className="text-xs text-slate-400 truncate">{notebook.title}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
          </div>
        </div>
      </nav>

      {/* ---- Main Content ---- */}
      <div className="flex-1">
        <div className="max-w-3xl mx-auto px-4 md:px-6 py-8">
          {/* Cover-style header */}
          <div className="mb-10">
            <div className="flex items-center gap-2 mb-3">
              <BookOpen className="w-4 h-4 text-blue-500" />
              <span className="text-xs font-medium text-blue-600 dark:text-blue-400 uppercase tracking-wide">{notebook.title}</span>
            </div>
            <h1 className="text-2xl md:text-3xl font-bold text-slate-800 dark:text-slate-100 mb-4 leading-tight">
              {session.title}
            </h1>
            <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500 dark:text-slate-400">
              {session.duration && (
                <span className="flex items-center gap-1.5">
                  <Clock className="w-3.5 h-3.5" />
                  {session.duration}
                </span>
              )}
              <span className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5" />
                由 Notero 智能课堂笔记生成
              </span>
            </div>
            {session.keywords && session.keywords.length > 0 && (
              <div className="flex flex-wrap gap-1.5 mt-4">
                {session.keywords.map((kw, i) => (
                  <span key={i} className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-full bg-blue-50 dark:bg-blue-900/30 text-blue-600 dark:text-blue-400 border border-blue-100 dark:border-blue-800/50">
                    <Tag className="w-3 h-3" />
                    {kw}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Summary */}
          {session.summary && (
            <div className="mb-10 p-5 bg-gradient-to-br from-blue-50 to-indigo-50 dark:from-blue-900/20 dark:to-indigo-900/20 border border-blue-100 dark:border-blue-800 rounded-2xl">
              <h2 className="text-xs font-semibold text-blue-600 dark:text-blue-400 mb-3 uppercase tracking-wider flex items-center gap-2">
                <span className="w-1 h-4 bg-blue-500 rounded-full" />
                课程摘要
              </h2>
              <p className="text-sm text-slate-600 dark:text-slate-300 leading-relaxed">{session.summary}</p>
            </div>
          )}

          {/* Layout Blocks */}
          {blocks.length > 0 ? (
            <div className="space-y-6">
              {blocks.map((block) => (
                <LayoutBlockRenderer key={block.id} block={block} shareToken={shareToken} />
              ))}
            </div>
          ) : (
            <div className="text-center py-16 text-slate-400 dark:text-slate-500">
              <FileText className="w-12 h-12 mx-auto mb-3 opacity-30" />
              <p className="text-sm">暂无内容</p>
            </div>
          )}

          {/* Footer */}
          <div className="text-center text-xs text-slate-400 dark:text-slate-500 mt-12 pt-6 border-t border-slate-200 dark:border-slate-700">
            由 Notero 智能课堂笔记生成
          </div>
        </div>
      </div>
    </div>
  );
}

// ---- Shared PPT Image Component ----
function SharedPptImage({ src, page, title, shareToken }: {
  src: string | undefined;
  page: number | string;
  title?: string;
  shareToken: string;
}) {
  const [imgError, setImgError] = useState(false);

  const handleError = useCallback(() => {
    setImgError(true);
  }, []);

  if (!src || imgError) {
    return (
      <div className="flex items-center justify-center h-32 text-xs text-slate-400 gap-2">
        <ImageOff className="w-4 h-4" />
        该页 PPT 图片缺失
      </div>
    );
  }

  const imgSrc = src.startsWith('data:') ? src : getShareMediaUrl(src, shareToken);

  return (
    <img
      src={imgSrc}
      alt={`PPT 第 ${page} 页${title ? ' · ' + title : ''}`}
      className="w-full object-contain bg-slate-50 dark:bg-slate-900 max-h-[500px]"
      onError={handleError}
    />
  );
}


// ---- Layout Block Renderer ----
function LayoutBlockRenderer({
  block,
  shareToken,
}: {
  block: NoteLayoutBlock;
  shareToken: string;
}) {
  switch (block.type) {
    case 'transcript':
      return (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 p-5">
          <div className="flex items-center gap-2 mb-3">
            <span className="w-2 h-2 rounded-full bg-blue-400" />
            <h3 className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide">语音转文字</h3>
          </div>
          <div
            className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed whitespace-pre-line"
            dangerouslySetInnerHTML={{ __html: sanitizeHTML(block.content || '') }}
          />
        </div>
      );

    case 'ppt':
      return (
        <div className="bg-white dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700 overflow-hidden">
          <div className="flex items-center gap-2 px-4 py-3 bg-slate-50/50 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-700/50">
            <ImagePlus className="w-3.5 h-3.5 text-blue-500" />
            <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">
              PPT 第 {block.page} 页{block.title ? ` · ${block.title}` : ''}
            </span>
          </div>
          <SharedPptImage src={block.src} page={block.page ?? '?'} title={block.title} shareToken={shareToken} />
        </div>
      );

    case 'note':
      return (
        <div className="bg-amber-50/50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-5">
          <div className="flex items-center gap-2 mb-3">
            <Edit3 className="w-3.5 h-3.5 text-amber-500" />
            <h3 className="text-xs font-semibold text-amber-700 dark:text-amber-400 uppercase tracking-wide">随堂笔记</h3>
          </div>
          <div
            className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed"
            dangerouslySetInnerHTML={{ __html: sanitizeHTML(block.content || '') }}
          />
        </div>
      );

    default:
      return null;
  }
}
