import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { toast } from 'sonner';
import {
  ArrowLeft, Play, Pause, ChevronUp, ChevronDown, Edit3, Loader2, AlertCircle, ImagePlus,
  X, FileText, Square, Download, Bold, List, Share2, Trash2, Mic, MicOff, Search,
  ChevronDown as ChevronDownIcon, Database, RefreshCw, BrainCircuit, Copy, Check,
  ClipboardCheck, CircleDot, Sparkles
} from 'lucide-react';
import { useStore } from '@/store/useStore';
import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { getProfile, getAvatarUrl } from '@/services/auth';
import type { UserProfile } from '@/services/auth';
import ContentBlocksView from '@/pages/note-detail/components/ContentBlocksView';
import RagSourceCards from '@/pages/note-detail/components/RagSourceCards';

import ThemeToggle from '@/components/ThemeToggle';
import RichTextEditor from '@/components/RichTextEditor';
import { AuthenticatedImage } from '@/components/AuthenticatedImage';
import { preloadAuthenticatedImage } from '@/lib/imageCache';
import { API_BASE, deleteAudio, uploadPPT, insertPPTIntoTranscript, uploadAudio, getMediaUrl, fetchNotebookDetail, fetchSessionById, enableShare, disableShare, getShareStatus, rebuildSessionVectorIndex, getSessionMindMap, generateSessionMindMap, deleteSessionMindMap, MindMapStatus, MindMapNode, MindMapData, getSessionQuizzes, generateSessionQuiz, getQuizDetail, submitQuizAnswers, deleteQuiz, getQuizBankStatus, rebuildQuizBank, QuizListItem, QuizDetail, QuizQuestion, QuizBankStatus, runAllAgents, fetchNote, type Slide } from '@/services/api';
import { sanitizeHTML, escapeHtml } from '@/lib/sanitize';
import { layoutFromNoteParts } from '@/lib/noteLayout';
import type { Notebook, Session } from '@/types';

import { useRecording } from './useRecording';
import { useTranscript, StudentNote } from './useTranscript';
import { usePPT } from './usePPT';
import { useNotes } from './useNotes';
import { useExport } from './useExport';
import { useShare } from './hooks/useShare';
import { useVectorIndex } from './hooks/useVectorIndex';
import { useRAG } from './hooks/useRAG';
import { useMindMap } from './hooks/useMindMap';
import { useQuiz } from './hooks/useQuiz';
import { useAudioUpload } from './hooks/useAudioUpload';
import { useAutoGenerate } from './hooks/useAutoGenerate';
import { useRestructure } from './hooks/useRestructure';
import { useProcessingStatus } from './hooks/useProcessingStatus';
import MindMapCanvas, { computeDefaultExpanded } from './MindMapCanvas';
import type { ContentBlock, RAGSource } from '@/services/api';

interface EditableParagraphCardsProps {
  transcriptText: string;
  containerRef?: React.RefObject<HTMLDivElement>;
  onUpdateDraft: (value: string) => void;
  onCommitDraft: () => void;
  onMarkUserEdited: () => void;
  onSetActiveTextEl: (el: HTMLDivElement | null) => void;
  onClearSentences: () => void;
}

function EditableParagraphCards({
  transcriptText,
  containerRef: externalContainerRef,
  onUpdateDraft,
  onCommitDraft,
  onMarkUserEdited,
  onSetActiveTextEl,
  onClearSentences,
}: EditableParagraphCardsProps) {
  const internalContainerRef = useRef<HTMLDivElement | null>(null);
  const containerRef = externalContainerRef || internalContainerRef;
  const activeIndexRef = useRef<number | null>(null);
  const isComposingRef = useRef(false);
  const blockRefs = useRef<Map<number, HTMLDivElement>>(new Map());

  const setBlockRef = (index: number) => (el: HTMLDivElement | null) => {
    if (el) blockRefs.current.set(index, el);
    else blockRefs.current.delete(index);
  };

  // Recompute paragraphs only when the external transcriptText changes (commit/load/AI),
  // never while the user is typing.
  const paragraphs = useMemo(() => {
    const rawParagraphs = transcriptText
      .split('\n\n')
      .map(p => p.trim())
      .filter(p => p);
    const CARD_MAX_CHARS = 320;
    const splitLongParagraph = (text: string): string[] => {
      if (text.length <= CARD_MAX_CHARS) return [text];
      const sentences = text.split(/(?<=[。！？.!?])/);
      const chunks: string[] = [];
      let current = '';
      for (const s of sentences) {
        if (current && (current + s).replace(/\s/g, '').length > CARD_MAX_CHARS) {
          chunks.push(current.trim());
          current = s;
        } else {
          current += s;
        }
      }
      if (current.trim()) chunks.push(current.trim());
      return chunks.length ? chunks : [text];
    };
    const result: string[] = [];
    for (const p of rawParagraphs) {
      result.push(...splitLongParagraph(p));
    }
    return result;
  }, [transcriptText]);

  // Sync non-active blocks when paragraphs change from outside.
  useEffect(() => {
    paragraphs.forEach((para, index) => {
      if (index === activeIndexRef.current) return;
      const el = blockRefs.current.get(index);
      if (!el) return;
      const next = sanitizeHTML(para.trim()) as unknown as string;
      if (el.innerHTML !== next) {
        el.innerHTML = next;
      }
    });
  }, [paragraphs]);

  const readDraftFromDom = () => {
    if (!containerRef.current) return transcriptText;
    const parts: string[] = [];
    for (const child of containerRef.current.children) {
      const html = sanitizeHTML((child as HTMLElement).innerHTML) as unknown as string;
      if (html && html !== '<br>' && html !== '<br />') {
        parts.push(html);
      }
    }
    return parts.join('\n\n');
  };

  const handleInput = () => {
    onMarkUserEdited();
    if (isComposingRef.current) return;
    onUpdateDraft(readDraftFromDom());
    onClearSentences();
  };

  const handleCompositionStart = () => {
    isComposingRef.current = true;
    onMarkUserEdited();
  };

  const handleCompositionEnd = () => {
    isComposingRef.current = false;
    handleInput();
  };

  const handleBlur = () => {
    activeIndexRef.current = null;
    onSetActiveTextEl(null);
    onUpdateDraft(readDraftFromDom());
    onCommitDraft();
  };

  return (
    <div ref={containerRef} className="space-y-3">
      {paragraphs.map((para, i) => (
        <div
          key={`para-${i}`}
          ref={setBlockRef(i)}
          contentEditable
          suppressContentEditableWarning
          dangerouslySetInnerHTML={{ __html: sanitizeHTML(para.trim()) as unknown as string }}
          onPaste={(e) => {
            e.preventDefault();
            const text = e.clipboardData?.getData('text/plain') || '';
            document.execCommand('insertText', false, text);
          }}
          onInput={handleInput}
          onCompositionStart={handleCompositionStart}
          onCompositionEnd={handleCompositionEnd}
          onBlur={handleBlur}
          onFocus={(e) => {
            activeIndexRef.current = i;
            onMarkUserEdited();
            onSetActiveTextEl(e.currentTarget);
          }}
          onPointerDown={(e) => { e.currentTarget.focus(); }}
          className="w-full rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 px-4 py-3 text-sm text-slate-600 dark:text-slate-300 leading-7 whitespace-pre-wrap break-words shadow-sm outline-none transition-colors hover:border-slate-300 dark:hover:border-slate-600 focus:border-blue-300 dark:focus:border-blue-600 focus:ring-2 focus:ring-blue-100 dark:focus:ring-blue-900/30 select-text cursor-text"
        />
      ))}
    </div>
  );
}

export { EditableParagraphCards };

const TEXT_COLORS = [
  { name: '红色', value: '#ef4444' },
  { name: '黄色', value: '#eab308' },
  { name: '蓝色', value: '#3b82f6' },
  { name: '黑色', value: '#1e293b' },
];

export default function NoteDetail() {
  const { id, sessionId } = useParams<{ id: string; sessionId: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const notebooks = useStore((s) => s.notebooks);
  const sessions = useStore((s) => s.sessions);

  const notebook = notebooks.find((n) => n.id === id);
  const session = sessions.find((s) => s.id === sessionId);
  const [fallbackNotebook, setFallbackNotebook] = useState<Notebook | null>(null);
  const [fallbackSession, setFallbackSession] = useState<Session | null>(null);
  const displayNotebook = notebook || fallbackNotebook;
  const displaySession = session || fallbackSession;
  const [profile, setProfile] = useState<UserProfile | null>(null);

  useEffect(() => { getProfile().then(setProfile).catch(() => {}); }, []);

  useEffect(() => {
    if (!id || notebook) return;
    fetchNotebookDetail(id).then((data) => {
      if (!data) return;
      setFallbackNotebook({
        id: data.id,
        title: data.title,
        description: data.description || '',
        icon: data.icon || 'BookOpen',
        color: data.color || 'from-blue-500 to-blue-600',
        sessionCount: data.session_count,
        updatedAt: data.created_at.split('T')[0],
        createdAt: data.created_at.split('T')[0],
      });
    }).catch(() => {});
  }, [id, notebook]);

  useEffect(() => {
    if (!sessionId || session) return;
    fetchSessionById(sessionId).then(setFallbackSession).catch(() => {});
  }, [sessionId, session]);

  // ---- Hooks ----
  const ppt = usePPT(sessionId);
  const notesHook = useNotes();
  const exportTools = useExport(displaySession, displayNotebook);
  const processing = useProcessingStatus(sessionId);
  const recording = useRecording(sessionId, { onFinalize: processing.refresh });
  const transcript = useTranscript(sessionId, recording.state.isRecording, ppt.state.slides);

  const share = useShare();
  const vectorIndex = useVectorIndex(sessionId, processing.processingStatus);
  const rag = useRAG();
  const mindMap = useMindMap(sessionId, processing.processingStatus);
  const quiz = useQuiz(sessionId, processing.processingStatus);
  const audioUpload = useAudioUpload(sessionId, { onFinalize: processing.refresh });
  const autoGen = useAutoGenerate(sessionId, processing.processingStatus);
  const restructure = useRestructure();

  const [isLoading, setIsLoading] = useState(true);
  const [showLeftPanel, setShowLeftPanel] = useState(false); // tablet sidebar
  const [aiCorrectionStatus, setAiCorrectionStatus] = useState<{ type: 'idle' | 'processing' | 'corrected' | 'local' | 'error'; message?: string }>({ type: 'idle' });

  const isPendingCorrectionMessage = (message?: string | null) => {
    if (!message) return false;
    return message.includes('等待统一 AI 整理') || message.includes('正在统一 AI 整理');
  };
  const fileInputRef = useRef<HTMLInputElement>(null);
  const transcriptEditRef = useRef<HTMLDivElement>(null);
  const noteEditRef = useRef<HTMLDivElement>(null);
  const activeTextElRef = useRef<HTMLDivElement | null>(null);
  const lastSentenceIdxRef = useRef(0);
  const paragraphContainerRef = useRef<HTMLDivElement>(null);

  // Drag-to-insert PPT state
  const [dragState, setDragState] = useState<{
    slide: Slide | null;
    pointer: { x: number; y: number } | null;
    targetIndex: number | null;
    targetPosition: 'before' | 'after' | null;
  }>({ slide: null, pointer: null, targetIndex: null, targetPosition: null });
  const longPressTimerRef = useRef<number | null>(null);
  const dragStartPosRef = useRef<{ x: number; y: number } | null>(null);
  const isDraggingRef = useRef(false);

  const getRagSourceTypeLabel = useCallback((source: RAGSource) => {
    const rawType = source.source_type === 'layout'
      ? String(source.metadata?.block_type || source.source_type)
      : source.source_type;
    if (rawType === 'ppt') return 'PPT';
    if (rawType === 'transcript') return '转写';
    if (rawType === 'note') return '笔记';
    return '资料';
  }, []);

  const highlightTranscriptSnippet = useCallback((snippet?: string | null) => {
    const container = paragraphContainerRef.current;
    if (!container || !snippet) return false;
    const normalize = (value: string) => value.replace(/\s+/g, '').toLowerCase();
    const target = normalize(snippet).slice(0, 80);
    if (!target) return false;

    const candidates = Array.from(container.children) as HTMLElement[];
    const targetEl = candidates.find((el) => normalize(el.textContent || '').includes(target));
    if (!targetEl) return false;

    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    targetEl.classList.add('ring-2', 'ring-violet-300', 'bg-violet-50', 'dark:bg-violet-900/20');
    window.setTimeout(() => {
      targetEl.classList.remove('ring-2', 'ring-violet-300', 'bg-violet-50', 'dark:bg-violet-900/20');
    }, 3000);
    return true;
  }, []);

  const handleRagSourceClick = useCallback((source: RAGSource, closePanel?: () => void) => {
    closePanel?.();
    if (source.session_id && source.session_id !== sessionId) {
      navigate(`/subject/${source.notebook_id}/session/${source.session_id}`, { state: { ragSource: source } });
      return;
    }

    const pageNumber = source.page == null ? null : Number(source.page);
    const typeLabel = getRagSourceTypeLabel(source);
    if (typeLabel === 'PPT' && Number.isFinite(pageNumber) && pageNumber! > 0) {
      ppt.actions.setActiveSlideIndex(pageNumber! - 1);
      return;
    }

    window.setTimeout(() => {
      const located = highlightTranscriptSnippet(source.snippet);
      if (!located) toast.info('已找到来源，但当前页面没有可精确定位的文本块');
    }, 200);
  }, [getRagSourceTypeLabel, highlightTranscriptSnippet, navigate, ppt.actions, sessionId]);



  useEffect(() => {
    const source = (location.state as { ragSource?: RAGSource } | null)?.ragSource;
    if (!source || source.session_id !== sessionId) return;
    const timer = window.setTimeout(() => {
      handleRagSourceClick(source);
      navigate(location.pathname, { replace: true, state: null });
    }, 800);
    return () => window.clearTimeout(timer);
  }, [handleRagSourceClick, location.pathname, location.state, navigate, sessionId]);

  // ---- Load history ----
  // Notes & PPT are restored reactively when the transcript hook finishes its
  // single fetchNote, avoiding a duplicate network call.
  useEffect(() => {
    if (!sessionId) { setIsLoading(false); return; }
    // useTranscript.loadHistory fires independently and sets loadedNote.
    // We wait for it rather than calling fetchNote ourselves.
  }, [sessionId]);

  // Provide the latest notes draft getter to useTranscript so debounced saves
  // always use the most recent notes content, not a stale closure.
  useEffect(() => {
    transcript.actions.setGetCurrentNotes(() => notesHook.refs.notesDraftRef.current);
  }, [transcript.actions.setGetCurrentNotes, notesHook.refs.notesDraftRef]);

  // React to loadedNote from useTranscript (single source of truth for history load)
  const loadedNote = transcript.state.loadedNote;
  useEffect(() => {
    if (!sessionId || !transcript.state.isLoaded) return;
    if (!loadedNote) {
      setIsLoading(false);
      return;
    }
    // Restore notes
    if (loadedNote.content) {
      const hasTranscript = loadedNote.transcript && Array.isArray(loadedNote.transcript) && loadedNote.transcript.length > 0;
      const parsed = notesHook.actions.parseNotesFromContent(loadedNote.content, hasTranscript);
      if (parsed.length > 0) {
        notesHook.actions.setNotes(parsed);
        notesHook.actions.resetDrafts(parsed);
      }
    }
    // Set AI correction status from loaded note
    if (loadedNote?.transcript && Array.isArray(loadedNote.transcript) && loadedNote.transcript.length > 0) {
      const sorted = [...loadedNote.transcript].sort((a: {chunk_index?: number}, b: {chunk_index?: number}) => (a.chunk_index || 0) - (b.chunk_index || 0));
      const lastEntry = sorted[sorted.length - 1];
      if (lastEntry?.is_ai_corrected) {
        setAiCorrectionStatus({ type: 'corrected' });
      } else if (lastEntry?.correction_error && !isPendingCorrectionMessage(lastEntry.correction_error)) {
        setAiCorrectionStatus({ type: 'error', message: lastEntry.correction_error });
      } else if (lastEntry?.correction_error && isPendingCorrectionMessage(lastEntry.correction_error)) {
        setAiCorrectionStatus({ type: 'local' });
      } else if (lastEntry?.is_corrected === false) {
        setAiCorrectionStatus({ type: 'local' });
      }
    }
    if (loadedNote.ppt_images && loadedNote.ppt_images.length > 0) {
      const lastPpt = loadedNote.ppt_images[loadedNote.ppt_images.length - 1];
      if (lastPpt.slides) ppt.actions.setSlides(lastPpt.slides);
      // Only auto-insert PPT if we don't have saved layout_blocks
      const hasLayoutBlocks = loadedNote.layout_blocks && Array.isArray(loadedNote.layout_blocks) && loadedNote.layout_blocks.length > 0;
      if (!hasLayoutBlocks) {
        setTimeout(async () => {
          try {
            const blocks = await insertPPTIntoTranscript(sessionId);
            if (blocks.blocks?.some((b: ContentBlock) => b.type === 'image')) {
              transcript.actions.updateContentBlocks(blocks.blocks, false, false);
            }
          } catch { /* ignore */ }
        }, 500);
      }
    }
    setIsLoading(false);
  }, [loadedNote, sessionId, transcript.state.isLoaded]);

  useEffect(() => {
    const stage = processing.processingStatus?.stages?.transcript_finalize;
    if (!stage) return;
    if (stage.status === 'running') {
      setAiCorrectionStatus({ type: 'processing', message: stage.message || '正在统一 AI 整理...' });
    } else if (stage.status === 'ready') {
      setAiCorrectionStatus({ type: 'corrected' });
    } else if (stage.status === 'fallback') {
      setAiCorrectionStatus({ type: 'local', message: stage.message || stage.error_message || undefined });
    } else if (stage.status === 'error') {
      setAiCorrectionStatus({ type: 'error', message: stage.error_message || 'AI 整理失败' });
    }
  }, [
    processing.processingStatus?.stages?.transcript_finalize?.status,
    processing.processingStatus?.stages?.transcript_finalize?.message,
    processing.processingStatus?.stages?.transcript_finalize?.error_message,
  ]);

  // ---- Auto-save ----
  // Debounced silent save: triggered by any dirty draft, but waits for the user
  // to stop typing before hitting the database. No prominent "saving" UI.
  useEffect(() => {
    if (!sessionId || !transcript.state.isLoaded || !transcript.state.hasLocalChanges || audioUpload.state.isUploadingAudio) return;
    transcript.actions.scheduleSave(() => notesHook.refs.notesDraftRef.current, 300);
    return () => {};
  }, [
    sessionId,
    transcript.state.isLoaded,
    transcript.state.hasLocalChanges,
    notesHook.refs.notesDraftRef,
    transcript.actions.scheduleSave,
    audioUpload.state.isUploadingAudio,
  ]);

  const workflowStatus = useMemo(() => {
    const stages = processing.processingStatus?.stages;
    if (ppt.state.isUploadingPPT) return { tone: 'blue', text: '正在上传并解析 PPT' };
    if (recording.state.isProcessing) return { tone: 'blue', text: '正在初始化录音设备' };

    // Real-time recording: keep the timer visible, but overlay PPT matching when active.
    if (recording.state.isRecording) {
      if (recording.state.isPaused) return { tone: 'amber', text: '录音已暂停' };
      if (transcript.state.isPptMatching) {
        return { tone: 'blue', text: `录音中 ${recording.state.currentTime} · 正在匹配 PPT 页面` };
      }
      return { tone: 'red', text: `录音中 ${recording.state.currentTime}` };
    }

    // Audio file upload + transcribe (upload + recognition shown as one stage).
    if (audioUpload.state.isUploadingAudio || stages?.upload_transcribe?.status === 'running') {
      if (audioUpload.state.uploadPhase === 'finalizing') {
        return { tone: 'violet', text: '正在整理转写稿' };
      }
      return { tone: 'blue', text: '正在处理录音文件', progress: audioUpload.state.audioQueueProgress };
    }

    // Recording wrap-up (concatenating audio chunks).
    if (stages?.recording_finalize?.status === 'running') return { tone: 'blue', text: '正在保存录音...' };
    if (stages?.recording_finalize?.status === 'error') return { tone: 'red', text: '录音保存失败' };
    if (stages?.recording_finalize?.status === 'ready' && stages?.transcript_finalize?.status === 'idle') {
      return { tone: 'amber', text: '录音已保存，点击 AI 整理生成学习资料' };
    }

    // Transcript AI finalization.
    if (stages?.transcript_finalize?.status === 'running') {
      return { tone: 'violet', text: '正在整理转写稿' };
    }
    if (stages?.transcript_finalize?.status === 'error') return { tone: 'red', text: stages.transcript_finalize.error_message || '整理转写稿失败' };
    if (stages?.upload_transcribe?.status === 'error') return { tone: 'red', text: '上传转写失败' };

    // Vector index (powers RAG Q&A).
    if (stages?.vector_index?.status === 'running') return { tone: 'violet', text: '正在建立知识索引' };
    if (stages?.vector_index?.status === 'error') return { tone: 'red', text: '知识索引建立失败' };

    // Learning-material agents (mindmap / quiz). Summary is disabled.
    const agentStages = [stages?.mindmap, stages?.quiz_bank];
    const anyAgentRunning = agentStages.some(s => s?.status === 'running');
    // A processing-status error is only shown as a failure when the drawer
    // doesn't already have usable generated data (ready or stale).
    const mindMapHasData = !!mindMap.state.mindMapStatus?.mind_map?.nodes?.length;
    const quizHasData = (quiz.state.bankStatus?.question_count || 0) > 0;
    const agentErrors: string[] = [];
    const retryAgents: string[] = [];
    if (stages?.mindmap?.status === 'error' && !mindMapHasData) {
      agentErrors.push('导图');
      retryAgents.push('mindmap');
    }
    if (stages?.quiz_bank?.status === 'error' && !quizHasData) {
      agentErrors.push('题库');
      retryAgents.push('quiz');
    }
    const allAgentsReady =
      (!stages?.mindmap || ['ready', 'stale', 'fallback', 'idle'].includes(stages.mindmap.status)) &&
      (!stages?.quiz_bank || ['ready', 'stale', 'fallback', 'idle'].includes(stages.quiz_bank.status));
    const transcriptFinalized =
      stages?.transcript_finalize?.status === 'ready' ||
      stages?.transcript_finalize?.status === 'fallback';
    const hasAgents = agentStages.some(s => s?.status !== 'idle');

    if (anyAgentRunning) {
      return { tone: 'blue', text: '正在生成导图和题库...' };
    }
    if (agentErrors.length > 0) {
      return { tone: 'red', text: `${agentErrors.join('、')}整理失败，可手动重试`, retryAgents };
    }
    if (
      hasAgents &&
      allAgentsReady &&
      transcriptFinalized &&
      stages?.vector_index?.status === 'ready'
    ) {
      return { tone: 'green', text: '整理成功' };
    }

    if (stages?.transcript_finalize?.status === 'fallback') return { tone: 'amber', text: '已使用本地整理稿' };

    if (transcript.state.isPptMatching) return { tone: 'blue', text: '正在匹配 PPT 页面' };
    if (transcript.state.saveStatus === 'error') return { tone: 'red', text: transcript.state.saveError || '保存失败', canRetrySave: true };
    if (ppt.state.uploadMessage) return { tone: 'green', text: ppt.state.uploadMessage };
    if (transcript.state.pptMatchMessage) return { tone: 'slate', text: transcript.state.pptMatchMessage };
    if (transcript.state.lastSaveTime) {
      const time = new Date(transcript.state.lastSaveTime).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      return { tone: 'green', text: `已保存 ${time}` };
    }
    return { tone: 'slate', text: '准备记录' };
  }, [
    processing.processingStatus?.stages,
    audioUpload.state.isUploadingAudio,
    audioUpload.state.audioQueueProgress,
    audioUpload.state.uploadPhase,
    ppt.state.isUploadingPPT,
    ppt.state.uploadMessage,
    recording.state.currentTime,
    recording.state.isPaused,
    recording.state.isProcessing,
    recording.state.isRecording,
    transcript.state.isPptMatching,
    transcript.state.lastSaveTime,
    transcript.state.pptMatchMessage,
    transcript.state.saveError,
    transcript.state.saveStatus,
    mindMap.state.mindMapStatus?.mind_map?.nodes?.length,
    quiz.state.bankStatus?.question_count,
  ]);

  const statusClass = {
    blue: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800',
    green: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800',
    amber: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800',
    red: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800',
    violet: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-900/20 dark:text-violet-300 dark:border-violet-800',
    slate: 'bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-800/60 dark:text-slate-300 dark:border-slate-700',
  }[workflowStatus.tone];

  const isLiveTranscriptMode = recording.state.isRecording || recording.state.isProcessing || audioUpload.state.isUploadingAudio;

  // Live transcript displayed in the main editor: confirmed finals + current
  // partial interim result, so the user sees the continuous stream in one place.
  const liveTranscriptHtml = useMemo(() => {
    const confirmed = transcript.state.transcriptText || '';
    const partial = transcript.state.partialText?.trim() || '';
    if (!partial) return confirmed;
    const partialHtml = `<p>${escapeHtml(partial)}</p>`;
    return confirmed ? `${confirmed}${partialHtml}` : partialHtml;
  }, [transcript.state.transcriptText, transcript.state.partialText]);

  // Has PPT blocks with image: show them even during recording
  const hasPptImageBlocks = transcript.state.contentBlocks.some(b => b.type === 'image');

  // ---- Format helpers ----
  const applyFormat = (formatType: string, value?: string) => {
    const el = activeTextElRef.current;
    if (!el) return;
    el.focus();
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0) return;
    const range = sel.getRangeAt(0);
    if (range.collapsed) return;
    const selectedText = range.toString();
    if (!selectedText) return;

    // Find the closest ancestor matching tag/predicate, stopping at the editor root.
    const findAncestor = (node: Node, tag: string, predicate?: (e: HTMLElement) => boolean): HTMLElement | null => {
      let cur: Node | null = node;
      while (cur && cur !== el) {
        if (cur.nodeType === Node.ELEMENT_NODE) {
          const elem = cur as HTMLElement;
          if (elem.tagName.toLowerCase() === tag && (!predicate || predicate(elem))) {
            return elem;
          }
        }
        cur = cur.parentNode;
      }
      return null;
    };

    // Replace a wrapper element with its children.
    const unwrap = (wrapper: HTMLElement) => {
      const parent = wrapper.parentNode;
      if (!parent) return;
      while (wrapper.firstChild) {
        parent.insertBefore(wrapper.firstChild, wrapper);
      }
      parent.removeChild(wrapper);
    };

    switch (formatType) {
      case 'bold': {
        const strong = findAncestor(range.startContainer, 'strong');
        if (strong && strong.contains(range.endContainer)) {
          unwrap(strong);
        } else {
          const wrapper = document.createElement('strong');
          try {
            range.surroundContents(wrapper);
          } catch {
            const fragment = range.extractContents();
            wrapper.appendChild(fragment);
            range.insertNode(wrapper);
          }
        }
        break;
      }
      case 'insertUnorderedList': {
        const ul = document.createElement('ul');
        const li = document.createElement('li'); li.textContent = selectedText;
        ul.appendChild(li); range.deleteContents(); range.insertNode(ul);
        break;
      }
      case 'foreColor': {
        if (value) {
          const sameColorSpan = findAncestor(range.startContainer, 'span', (s) => s.style.color === value);
          if (sameColorSpan && sameColorSpan.contains(range.endContainer)) {
            unwrap(sameColorSpan);
          } else {
            const span = document.createElement('span'); span.style.color = value;
            try {
              range.surroundContents(span);
            } catch {
              const fragment = range.extractContents();
              span.appendChild(fragment);
              range.insertNode(span);
            }
          }
        }
        break;
      }
    }
    sel.removeAllRanges();
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };

  const normalizeTranscriptBlockForDisplay = (content?: string) => {
    return (content || '').trim().replace(/^#{1,6}\s*/, '');
  };

  // ---- Drag-to-insert PPT ----
  const clearDrag = useCallback(() => {
    if (longPressTimerRef.current) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    dragStartPosRef.current = null;
    isDraggingRef.current = false;
    setDragState({ slide: null, pointer: null, targetIndex: null, targetPosition: null });
  }, []);

  const detectDropTarget = useCallback((clientX: number, clientY: number): { index: number | null; position: 'before' | 'after' | null } => {
    const el = document.elementFromPoint(clientX, clientY);
    const blockEl = el?.closest('[data-block-index]') as HTMLElement | null;
    if (!blockEl) return { index: null, position: null };
    const index = Number(blockEl.getAttribute('data-block-index'));
    if (Number.isNaN(index)) return { index: null, position: null };
    const rect = blockEl.getBoundingClientRect();
    const position: 'before' | 'after' = clientY < rect.top + rect.height / 2 ? 'before' : 'after';
    return { index, position };
  }, []);

  const insertSlideBlock = useCallback((slide: Slide, targetIndex: number, position: 'before' | 'after') => {
    const blocks = transcript.state.contentBlocks;
    const imageBlock: ContentBlock = {
      type: 'image',
      src: slide.image_path
        ? `/api/media/slides/${sessionId}/${slide.image_path}`
        : slide.image_base64 || '',
      page: slide.page,
      title: slide.title,
    };

    let insertIndex = position === 'before' ? targetIndex : targetIndex + 1;
    if (position === 'after') {
      // Place the image before the next text block so it groups correctly
      while (insertIndex < blocks.length && blocks[insertIndex]?.type !== 'text') {
        insertIndex++;
      }
    }

    const newBlocks = [...blocks];
    newBlocks.splice(insertIndex, 0, imageBlock);
    transcript.actions.updateContentBlocks(newBlocks, true);
  }, [sessionId, transcript.actions, transcript.state.contentBlocks]);

  const updateDrag = useCallback((clientX: number, clientY: number) => {
    const target = detectDropTarget(clientX, clientY);
    setDragState((prev) => ({
      ...prev,
      pointer: { x: clientX, y: clientY },
      targetIndex: target.index,
      targetPosition: target.position,
    }));
  }, [detectDropTarget]);

  const endDrag = useCallback(() => {
    setDragState((prev) => {
      if (prev.slide && prev.targetIndex !== null && prev.targetPosition) {
        insertSlideBlock(prev.slide, prev.targetIndex, prev.targetPosition);
      }
      return prev;
    });
    clearDrag();
  }, [clearDrag, insertSlideBlock]);

  const startDrag = useCallback((slide: Slide, clientX: number, clientY: number) => {
    isDraggingRef.current = true;
    setDragState({
      slide,
      pointer: { x: clientX, y: clientY },
      targetIndex: null,
      targetPosition: null,
    });
  }, []);

  const handleSlideMouseDown = useCallback((slide: Slide) => (e: React.MouseEvent) => {
    if (e.button !== 0) return;
    e.preventDefault();
    startDrag(slide, e.clientX, e.clientY);
  }, [startDrag]);

  const handleSlideTouchStart = useCallback((slide: Slide) => (e: React.TouchEvent) => {
    const touch = e.touches[0];
    dragStartPosRef.current = { x: touch.clientX, y: touch.clientY };
    if (longPressTimerRef.current) window.clearTimeout(longPressTimerRef.current);
    longPressTimerRef.current = window.setTimeout(() => {
      longPressTimerRef.current = null;
      startDrag(slide, touch.clientX, touch.clientY);
    }, 400);
  }, [startDrag]);

  const handleSlideTouchMove = useCallback((e: React.TouchEvent) => {
    if (!longPressTimerRef.current || !dragStartPosRef.current) return;
    const touch = e.touches[0];
    const dx = touch.clientX - dragStartPosRef.current.x;
    const dy = touch.clientY - dragStartPosRef.current.y;
    if (Math.sqrt(dx * dx + dy * dy) > 10) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
      dragStartPosRef.current = null;
    }
  }, []);

  const handleSlideTouchEnd = useCallback(() => {
    if (longPressTimerRef.current) {
      window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = null;
    }
    dragStartPosRef.current = null;
  }, []);

  // Global move/up listeners while dragging
  useEffect(() => {
    if (!dragState.slide) return;
    const handleMouseMove = (e: MouseEvent) => updateDrag(e.clientX, e.clientY);
    const handleTouchMove = (e: TouchEvent) => {
      e.preventDefault();
      updateDrag(e.touches[0].clientX, e.touches[0].clientY);
    };
    const handleEnd = () => endDrag();

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleEnd);
    window.addEventListener('touchmove', handleTouchMove, { passive: false });
    window.addEventListener('touchend', handleEnd);
    window.addEventListener('touchcancel', handleEnd);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleEnd);
      window.removeEventListener('touchmove', handleTouchMove);
      window.removeEventListener('touchend', handleEnd);
      window.removeEventListener('touchcancel', handleEnd);
    };
  }, [dragState.slide, updateDrag, endDrag]);

  // ---- Share ----


  // Preload adjacent PPT slides so switching slides feels instant.
  useEffect(() => {
    if (!sessionId || ppt.state.slides.length === 0) return;
    const nextIndex = ppt.state.activeSlideIndex + 1;
    const prevIndex = ppt.state.activeSlideIndex - 1;
    [nextIndex, prevIndex].forEach((idx) => {
      if (idx < 0 || idx >= ppt.state.slides.length) return;
      const slide = ppt.state.slides[idx];
      const src = slide.image_path
        ? getMediaUrl(`/api/media/slides/${sessionId}/${slide.image_path}`)
        : slide.image_base64 || '';
      if (src) preloadAuthenticatedImage(src);
    });
  }, [ppt.state.activeSlideIndex, ppt.state.slides, sessionId]);


  // ---- Vector Index ----

  useEffect(() => {
    if (!transcript.state.hasLocalChanges) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = '';
    };
    window.addEventListener('beforeunload', handleBeforeUnload);
    return () => window.removeEventListener('beforeunload', handleBeforeUnload);
  }, [transcript.state.hasLocalChanges]);















  // ---- Navigation ----
  const handleBack = useCallback(async () => {
    if (sessionId && transcript.state.hasLocalChanges) {
      await transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
    }
    navigate(`/subject/${id}`);
  }, [sessionId, transcript.state.hasLocalChanges, transcript.actions.saveContent, notesHook.refs.notesDraftRef, navigate, id]);

  // ---- PPT ----
  const handlePPTClick = () => fileInputRef.current?.click();

  const handlePPTSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await ppt.actions.handlePPTUpload(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };






  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex items-center gap-2 text-slate-400"><Loader2 className="w-5 h-5 animate-spin" /> 加载中...</div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* ---- Top Nav ---- */}
      <nav className="flex-shrink-0 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md border-b border-slate-200/60 dark:border-slate-800/60">
        <div className="px-3 py-2 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <button onClick={handleBack} className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors">
              <ArrowLeft className="w-5 h-5" />
            </button>
            <div className="min-w-0">
              <h1 className="text-sm font-semibold text-slate-800 dark:text-slate-200 truncate">{displaySession?.title || '课次'}</h1>
              <p className="text-xs text-slate-400 truncate">{displayNotebook?.title}</p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <button onClick={() => exportTools.actions.setShowExportMenu(!exportTools.state.showExportMenu)}
                className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors" title="导出">
                <Download className="w-3.5 h-3.5" />
                <ChevronDownIcon className="w-3 h-3" />
              </button>
              {exportTools.state.showExportMenu && (
                <div className="absolute right-0 top-full mt-1 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg py-1 z-50 min-w-[140px]">
                  <button onClick={() => {
                    const blocks = layoutFromNoteParts(transcript.state.transcriptText, transcript.state.contentBlocks, notesHook.state.notes);
                    exportTools.actions.exportMarkdown(transcript.state.transcriptText, notesHook.state.notes, blocks);
                  }}
                    className="w-full text-left px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
                    📝 导出 Markdown
                  </button>
                  <button onClick={() => {
                    const blocks = layoutFromNoteParts(transcript.state.transcriptText, transcript.state.contentBlocks, notesHook.state.notes);
                    exportTools.actions.exportPDF(transcript.state.transcriptText, notesHook.state.notes, blocks);
                  }} disabled={exportTools.state.isExportingPDF}
                    className="w-full text-left px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50">
                    {exportTools.state.isExportingPDF ? '⏳ 导出中...' : '📄 导出 PDF'}
                  </button>
                  <button onClick={() => exportTools.actions.exportNotebookPackage()} disabled={exportTools.state.isExportingPackage}
                    className="w-full text-left px-3 py-2 text-xs text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors disabled:opacity-50">
                    {exportTools.state.isExportingPackage ? '⏳ 导出中...' : '📦 导出笔记本包'}
                  </button>
                </div>
              )}
            </div>
            <button onClick={() => share.actions.handleShareSession(sessionId!, share.state.shareExpiresIn, share.state.shareMaxViewsInput)} className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded-lg transition-colors" title="分享">
              <Share2 className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => { const willOpen = !rag.state.showSearch; rag.actions.setShowSearch(willOpen); if (willOpen) vectorIndex.actions.ensureIndexed(); }} className={`flex items-center gap-1 px-3 py-2 text-sm rounded-lg transition-colors ${rag.state.showSearch ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-slate-500 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20'}`} title="搜索">
              <Search className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => { mindMap.actions.setShowMindMap(true); vectorIndex.actions.ensureIndexed(); }} className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-900/20 rounded-lg transition-colors" title="知识导图">
              <BrainCircuit className="w-3.5 h-3.5" />
            </button>
            <button onClick={() => { quiz.actions.setShowQuiz(true); quiz.actions.setActiveQuiz(null); quiz.actions.setQuizSubmitted(false); quiz.actions.setQuizAnswers({}); quiz.actions.setQuizError(null); vectorIndex.actions.ensureIndexed(); }} className="flex items-center gap-1 px-3 py-2 text-sm text-slate-500 hover:text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 rounded-lg transition-colors" title="测验">
              <ClipboardCheck className="w-3.5 h-3.5" />
            </button>
            <div className="flex items-center gap-1 px-2 py-1 text-xs rounded-lg bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700">
              {vectorIndex.state.vectorStatus?.status === 'indexed' ? (
                <>
                  <Database className="w-3 h-3 text-green-500" />
                  <span className="text-green-600 dark:text-green-400">已索引 {vectorIndex.state.vectorStatus.chunk_count}条</span>
                  <button onClick={vectorIndex.actions.handleRebuildIndex} disabled={vectorIndex.state.isRebuilding} className="ml-1 text-slate-400 hover:text-blue-500" title="重建索引">
                    <RefreshCw className={`w-3 h-3 ${vectorIndex.state.isRebuilding ? 'animate-spin' : ''}`} />
                  </button>
                </>
              ) : vectorIndex.state.vectorStatus?.status === 'stale' ? (
                <>
                  <Database className="w-3 h-3 text-amber-500" />
                  <span className="text-amber-600 dark:text-amber-400">内容已变化</span>
                  <button onClick={vectorIndex.actions.handleRebuildIndex} disabled={vectorIndex.state.isRebuilding} className="ml-1 text-amber-500 hover:text-blue-500 font-medium" title="重建索引">
                    {vectorIndex.state.isRebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : '重建'}
                  </button>
                </>
              ) : vectorIndex.state.vectorStatus?.status === 'not_indexed' ? (
                <>
                  <Database className="w-3 h-3 text-slate-400" />
                  <button onClick={vectorIndex.actions.handleRebuildIndex} disabled={vectorIndex.state.isRebuilding} className="text-slate-500 hover:text-blue-500" title="建立索引">
                    {vectorIndex.state.isRebuilding ? <Loader2 className="w-3 h-3 animate-spin" /> : '建立索引'}
                  </button>
                </>
              ) : (
                <span className="text-slate-400">无内容</span>
              )}
            </div>
            <ThemeToggle />
            <button onClick={() => navigate('/profile')} className="cursor-pointer">
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

      {/* ---- Toolbar ---- */}
      <div className="flex-shrink-0 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border-b border-slate-200/60 dark:border-slate-700/60">
        <div className="px-3 py-2 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <input ref={fileInputRef} type="file" accept=".ppt,.pptx,.pdf" onChange={handlePPTSelect} className="hidden" />
            <button onClick={handlePPTClick} disabled={ppt.state.isUploadingPPT}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg hover:border-blue-300 hover:text-blue-600 transition-all disabled:opacity-50">
              {ppt.state.isUploadingPPT ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <ImagePlus className="w-3.5 h-3.5" />}
              {ppt.state.isUploadingPPT ? '上传中...' : '上传PPT'}
            </button>
            {ppt.state.slides.length > 0 && <span className="text-xs text-slate-400">{ppt.state.slides.length} 页</span>}

            <input ref={audioUpload.refs.audioInputRef} type="file" multiple accept=".wav,.mp3,.webm,.m4a,.ogg,.flac" onChange={(e) => {
                  const files = e.target.files;
                  if (!files || files.length === 0) return;
                  audioUpload.actions.handleAudioUpload(Array.from(files), {
                    clearDerivedTranscriptViews: transcript.actions.clearDerivedTranscriptViews,
                    clearStreamingTranscriptChunks: transcript.actions.clearStreamingTranscriptChunks,
                    updateTranscriptText: transcript.actions.updateTranscriptText,
                    appendTranscriptText: transcript.actions.appendTranscriptText,
                    receiveAiText: transcript.actions.receiveAiText,
                    clearStreamingTranscriptChunksFinal: transcript.actions.clearStreamingTranscriptChunks,
                    clearContentBlocks: transcript.actions.clearContentBlocks,
                    scrollToBottom: () => {
                      if (paragraphContainerRef.current) {
                        paragraphContainerRef.current.scrollTop = paragraphContainerRef.current.scrollHeight;
                      }
                    },
                  }, setAiCorrectionStatus);
                }} className="hidden" />
            <button onClick={() => { if (audioUpload.refs.audioInputRef.current) audioUpload.refs.audioInputRef.current.value = ''; audioUpload.refs.audioInputRef.current?.click(); }} disabled={audioUpload.state.isUploadingAudio}
              className="flex items-center gap-1 px-2.5 py-1.5 text-xs text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg hover:border-green-300 hover:text-green-600 transition-all disabled:opacity-50">
              {audioUpload.state.isUploadingAudio ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Mic className="w-3.5 h-3.5" />}
              {audioUpload.state.isUploadingAudio
                ? (audioUpload.state.audioQueueProgress
                  ? `处理中 ${audioUpload.state.audioQueueProgress.current}/${audioUpload.state.audioQueueProgress.total}`
                  : '处理中...')
                : '上传录音'}
            </button>
          </div>

          <div className="flex items-center gap-3">
            <div className="relative">
              {recording.state.isProcessing ? (
                <button disabled className="w-9 h-9 rounded-full bg-gradient-to-br from-blue-500 to-blue-600 text-white flex items-center justify-center shadow-lg cursor-wait">
                  <Loader2 className="w-4 h-4 animate-spin" />
                </button>
              ) : recording.state.isError ? (
                <button onClick={() => {
                  if (recording.state.isRecording) {
                    recording.actions.stopRecording(transcript.actions.receiveAiText);
                  }
                }}
                  className="w-9 h-9 rounded-full bg-gradient-to-br from-red-500 to-red-600 text-white flex items-center justify-center shadow-lg hover:shadow-xl transition-all hover:scale-105 active:scale-95">
                  <AlertCircle className="w-4 h-4" />
                </button>
              ) : (
                <button onClick={() => {
                  if (recording.state.isPaused) recording.actions.resumeRecording();
                  else if (recording.state.isRecording) recording.actions.pauseRecording();
                  else {
                    transcript.actions.clearDerivedTranscriptViews();
                    transcript.actions.clearStreamingState();
                    recording.actions.startRecording(
                      transcript.actions.receivePartial,
                      transcript.actions.receiveFinal,
                    );
                  }
                }}
                  className={`w-11 h-11 rounded-full text-white flex items-center justify-center shadow-lg hover:shadow-xl transition-all hover:scale-105 active:scale-95 ${
                    recording.state.isRecording ? 'bg-gradient-to-br from-amber-500 to-amber-600 shadow-amber-200' : 'bg-gradient-to-br from-blue-500 to-blue-600 shadow-blue-200'
                  }`}>
                  {recording.state.isRecording ? <Pause className="w-4 h-4" /> : <Play className="w-4 h-4 ml-0.5" />}
                </button>
              )}
            </div>

            <div className="flex items-center gap-0.5 h-7 hidden sm:flex">
              {recording.state.waveHeights.map((height, i) => (
                <div key={i} className="w-1 rounded-full transition-all duration-75"
                  style={{ height: `${height}px`, backgroundColor: recording.state.isRecording ? 'rgba(59, 130, 246, 0.5)' : 'rgba(148, 163, 184, 0.3)' }}
                />
              ))}
            </div>

            <span className="text-sm font-mono font-medium text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-700 px-2.5 py-0.5 rounded-md tabular-nums">
              {recording.state.currentTime}
            </span>

            {recording.state.isRecording && (
              <button onClick={() => {
                if (recording.state.isPaused) recording.actions.resumeRecording();
                else recording.actions.pauseRecording();
              }}
                className="flex items-center gap-1 px-3 py-2 text-sm font-medium rounded-md bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-400 hover:bg-amber-200 transition-colors min-h-[44px]">
                {recording.state.isPaused ? <Play className="w-3 h-3" /> : <Square className="w-3 h-3" />}
                {recording.state.isPaused ? '继续' : '暂停'}
              </button>
            )}

            {recording.state.isRecording && (
              <button onClick={() => {
                recording.actions.stopRecording(transcript.actions.receiveAiText).then((result) => {
                  if (result?.status === 'finished') {
                    processing.refresh();
                    toast.info('录音已保存。请稍等片刻，然后点击「AI 整理」生成学习材料。');
                    return;
                  }
                  if (result?.status === 'no_audio' || result?.status === 'no_chunks') {
                    toast.warning('未检测到录音内容');
                    return;
                  }
                  if (result?.status === 'error') {
                    toast.error('录音保存失败，请稍后重试');
                    return;
                  }
                  processing.refresh();
                });
              }}
                className="flex items-center gap-1 px-3 py-2 text-sm font-medium rounded-md bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 hover:bg-red-200 dark:hover:bg-red-900/50 transition-colors min-h-[44px]">
                <MicOff className="w-3.5 h-3.5" />
                停止
              </button>
            )}
          </div>

          <div className="flex items-center gap-1.5">
            <button onMouseDown={(e) => e.preventDefault()} onClick={() => applyFormat('bold')}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors" title="加粗">
              <Bold className="w-5 h-5" />
            </button>
            <button onMouseDown={(e) => e.preventDefault()} onClick={() => applyFormat('insertUnorderedList')}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors" title="列表">
              <List className="w-5 h-5" />
            </button>
            <div className="w-px h-5 bg-slate-200 dark:bg-slate-600 mx-1" />
            <div className="flex items-center gap-1.5">
              {TEXT_COLORS.map((color) => (
                <button key={color.value} onMouseDown={(e) => e.preventDefault()} onClick={() => applyFormat('foreColor', color.value)}
                  className="w-7 h-7 rounded-full border-2 border-slate-300 dark:border-slate-500 hover:scale-125 hover:border-slate-400 transition-all"
                  style={{ backgroundColor: color.value }} title={color.name} />
              ))}
            </div>
          </div>
        </div>
      </div>

      {autoGen.state.autoGenerateToast && !autoGen.state.autoGenerateToast.startsWith('正在') && !autoGen.state.autoGenerateToast.includes('失败') && (
        <div className="flex-shrink-0 mx-4 mt-3 px-3 py-2 border rounded-xl flex items-center gap-2 text-xs bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800">
          <AlertCircle className="w-3.5 h-3.5 flex-shrink-0" />
          <span className="flex-1">{autoGen.state.autoGenerateToast}</span>
        </div>
      )}

      <div className={`flex-shrink-0 mx-4 mt-3 px-3 py-2 border rounded-xl flex items-center gap-2 text-xs ${statusClass}`}>
        {(ppt.state.isUploadingPPT || audioUpload.state.isUploadingAudio || recording.state.isProcessing || transcript.state.isPptMatching || processing.processingStatus?.overall_status === 'running') && (
          <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0" />
        )}
        <span className="flex-1">{workflowStatus.text}</span>
        {(workflowStatus as any).progress && (workflowStatus as any).progress.total > 1 && (
          <div className="flex items-center gap-2 w-28 sm:w-36">
            <div className="flex-1 h-1.5 bg-current opacity-20 rounded-full overflow-hidden">
              <div
                className="h-full bg-current rounded-full transition-all duration-300"
                style={{ width: `${(((workflowStatus as any).progress.current / (workflowStatus as any).progress.total) * 100).toFixed(1)}%` }}
              />
            </div>
            <span className="text-xs tabular-nums opacity-90">{(workflowStatus as any).progress.current}/{(workflowStatus as any).progress.total}</span>
          </div>
        )}
        {(workflowStatus as any).retryAgents && (workflowStatus as any).retryAgents.length > 0 && (
          <button
            onClick={() => autoGen.actions.handleTriggerAgents(sessionId, (workflowStatus as any).retryAgents)}
            className="px-2 py-1 rounded-md bg-white/70 dark:bg-slate-900/60 hover:bg-white text-xs font-medium"
          >
            {(workflowStatus as any).retryAgents.length === 1
              ? ((workflowStatus as any).retryAgents[0] === 'mindmap'
                  ? '重新生成导图'
                  : (workflowStatus as any).retryAgents[0] === 'quiz'
                    ? '重新生成题库'
                    : `重新生成${(workflowStatus as any).retryAgents[0]}`)
              : '重新生成'}
          </button>
        )}
        {transcript.state.saveStatus === 'error' && (
          <button
            onClick={() => {
              notesHook.actions.commitNotesDraft();
              transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, true);
            }}
            className="px-2 py-1 rounded-md bg-white/70 dark:bg-slate-900/60 hover:bg-white text-xs font-medium"
          >
            重试保存
          </button>
        )}
      </div>

      {recording.state.isError && recording.state.errorMessage && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1"><p className="text-xs text-red-600 dark:text-red-400">{recording.state.errorMessage}</p></div>
          <button onClick={() => { recording.actions.setIsError(false); recording.actions.setErrorMessage(''); }}
            className="p-0.5 text-red-400 hover:text-red-600"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {ppt.state.uploadError && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1"><p className="text-xs text-red-600 dark:text-red-400">{ppt.state.uploadError}</p></div>
          <button onClick={() => ppt.actions.setUploadError(null)} className="text-red-400 hover:text-red-600"><X className="w-4 h-4" /></button>
        </div>
      )}

      {audioUpload.state.audioUploadError && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1"><p className="text-xs text-red-600 dark:text-red-400">{audioUpload.state.audioUploadError}</p></div>
          <button onClick={() => audioUpload.actions.setAudioUploadError(null)}
            className="p-0.5 text-red-400 hover:text-red-600"><X className="w-3.5 h-3.5" /></button>
        </div>
      )}

      {transcript.state.isAiRestructuring && recording.state.isRecording && ppt.state.slides.length > 0 && (
        <div className="flex-shrink-0 mx-4 mt-2 flex items-center gap-2 px-3 py-2 bg-blue-50 dark:bg-blue-900/20 border border-blue-100 dark:border-blue-800 rounded-lg text-xs text-blue-600 dark:text-blue-400">
          <Loader2 className="w-3 h-3 animate-spin" />
          正在匹配 PPT 页面...
        </div>
      )}

      {transcript.state.pendingAiText && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-violet-50 dark:bg-violet-900/20 border border-violet-200 dark:border-violet-800 rounded-xl flex items-start gap-2">
          <FileText className="w-4 h-4 text-violet-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-xs text-violet-700 dark:text-violet-300">有 AI 整理版本可应用，当前编辑内容不会被自动覆盖。</p>
          </div>
          <button onClick={transcript.actions.applyPendingAiText} className="px-2 py-1 rounded-md bg-violet-500 text-white text-xs font-medium hover:bg-violet-600">应用</button>
          <button onClick={transcript.actions.dismissPendingAiText} className="text-violet-400 hover:text-violet-600"><X className="w-4 h-4" /></button>
        </div>
      )}

      {/* ---- Three-column layout (sidebars overlay on tablet) ---- */}
      <div className="flex-1 flex overflow-hidden">
        {!showLeftPanel && (
          <button
            onClick={() => setShowLeftPanel(true)}
            className="lg:hidden fixed bottom-20 right-6 z-40 w-11 h-11 rounded-full bg-blue-500 text-white shadow-lg flex items-center justify-center hover:bg-blue-600 transition-colors"
            title="PPT 与笔记"
          >
            <FileText className="w-5 h-5" />
          </button>
        )}

        {/* ---- Left (1/3): PPT on top, Notes on bottom ---- */}
        {showLeftPanel && <div onClick={() => setShowLeftPanel(false)} className="lg:hidden fixed inset-0 z-40 bg-black/50 backdrop-blur-sm" />}
        <aside className={`${showLeftPanel ? 'fixed inset-y-0 left-0 z-50 w-80' : 'hidden'} lg:relative lg:flex lg:w-1/3 flex-shrink-0 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border-r border-slate-200/60 dark:border-slate-700/60 flex flex-col overflow-hidden`}>
          <div className="lg:hidden flex-shrink-0 px-3 py-2 flex items-center justify-between border-b border-slate-200/60 dark:border-slate-700/60">
            <div className="flex items-center gap-1.5">
              <FileText className="w-3.5 h-3.5 text-blue-500" />
              <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">PPT 与笔记</h3>
            </div>
            <button onClick={() => setShowLeftPanel(false)} className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* PPT section (top) */}
          <div className="flex-shrink-0 border-b border-slate-200/60 dark:border-slate-700/60">
            <div className="px-3 py-2 flex items-center justify-between">
              <div className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-blue-500" />
                <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">PPT</h3>
              </div>
              {ppt.state.slides.length > 0 && (
                <div className="flex items-center gap-1">
                  <span className="text-xs text-slate-400 font-mono">{ppt.state.activeSlideIndex + 1}/{ppt.state.slides.length}</span>
                  <button onClick={() => ppt.actions.setActiveSlideIndex(Math.max(0, ppt.state.activeSlideIndex - 1))}
                    disabled={ppt.state.activeSlideIndex === 0}
                    className="min-w-[32px] min-h-[32px] rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-30 transition-colors flex items-center justify-center">
                    <ChevronUp className="w-5 h-5" />
                  </button>
                  <button onClick={() => ppt.actions.setActiveSlideIndex(Math.min(ppt.state.slides.length - 1, ppt.state.activeSlideIndex + 1))}
                    disabled={ppt.state.activeSlideIndex === ppt.state.slides.length - 1}
                    className="min-w-[32px] min-h-[32px] rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-30 transition-colors flex items-center justify-center">
                    <ChevronDown className="w-5 h-5" />
                  </button>
                </div>
              )}
            </div>

            {/* PPT slide image */}
            <div className="px-3 pb-3">
              {ppt.state.slides.length > 0 && ppt.state.slides[ppt.state.activeSlideIndex] ? (
                <div className="space-y-1.5">
                  <div
                    className={`rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 select-none ${dragState.slide ? 'opacity-60' : 'hover:ring-2 hover:ring-blue-200 cursor-grab active:cursor-grabbing'}`}
                    onMouseDown={handleSlideMouseDown(ppt.state.slides[ppt.state.activeSlideIndex])}
                    onTouchStart={handleSlideTouchStart(ppt.state.slides[ppt.state.activeSlideIndex])}
                    onTouchMove={handleSlideTouchMove}
                    onTouchEnd={handleSlideTouchEnd}
                  >
                    {(() => {
                      const s = ppt.state.slides[ppt.state.activeSlideIndex];
                      const src = s.image_path
                        ? getMediaUrl(`/api/media/slides/${sessionId}/${s.image_path}`)
                        : s.image_base64 || '';
                      const fallback = <div className="flex items-center justify-center h-28 text-xs text-slate-400">无预览图</div>;
                      return src ? (
                        <AuthenticatedImage
                          src={src}
                          alt={`Slide ${s.page}`}
                          className="w-full object-cover pointer-events-none"
                          fallback={fallback}
                        />
                      ) : fallback;
                    })()}
                  </div>
                  <p className="text-[10px] text-slate-400 text-center">长按或拖拽到右侧段落插入</p>
                </div>
              ) : (
                <div className="flex items-center justify-center h-28 bg-slate-50 dark:bg-slate-900/50 rounded-lg border border-dashed border-slate-300 dark:border-slate-600">
                  <p className="text-xs text-slate-400">上传PPT后显示</p>
                </div>
              )}
            </div>
          </div>

          {/* Notes section (bottom, flex-1) */}
          <div className="flex-1 flex flex-col min-h-0">
            <div className="flex-shrink-0 px-3 py-2 border-b border-slate-100 dark:border-slate-700/50 flex items-center gap-1.5">
              <Edit3 className="w-3.5 h-3.5 text-amber-500" />
              <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">随堂思考与重难点</h3>
            </div>
            <div className="flex-1 overflow-y-auto p-3">
              <RichTextEditor
                ref={noteEditRef}
                value={notesHook.state.notes.length > 0 ? notesHook.state.notes[0].content : ''}
                onChange={(text) => {
                  transcript.actions.markUserEdited();
                  notesHook.actions.updateNoteDraft(0, text);
                  transcript.actions.scheduleSave(() => notesHook.refs.notesDraftRef.current, 300);
                }}
                onFocus={() => {
                  activeTextElRef.current = noteEditRef.current;
                }}
                onBlur={() => {
                  notesHook.actions.commitNotesDraft();
                  transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
                }}
                placeholder="在此记录随堂思考与重难点..."
                className="rich-text-editor w-full p-2.5 text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-200 leading-relaxed"
              />
            </div>
          </div>
        </aside>

        {/* ---- Right (2/3): Transcript ---- */}
        <main className="flex-1 flex flex-col min-h-0 bg-white/40 dark:bg-slate-900/40 backdrop-blur-sm">
          <div className="flex-shrink-0 px-4 md:px-6 py-4">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-sm font-semibold text-slate-600 dark:text-slate-300 flex items-center gap-2">
                {recording.state.isRecording ? <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" /> : <span className="w-2 h-2 rounded-full bg-slate-400" />}
                语音转文字 {recording.state.isRecording && <span className="text-xs font-normal text-slate-400">录制中</span>}
                {aiCorrectionStatus.type === 'corrected' && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400" title="DeepSeek AI 已纠正同音字、术语和格式">AI 已纠正</span>
                )}
                {aiCorrectionStatus.type === 'processing' && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400 inline-flex items-center gap-1" title={aiCorrectionStatus.message || '正在调用 DeepSeek 整理转写'}>
                    <Loader2 className="w-3 h-3 animate-spin" />
                    AI 整理中
                  </span>
                )}
                {aiCorrectionStatus.type === 'local' && (
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400" title="未配置 DeepSeek API 或 AI 纠正被拦截，使用本地规则整理">本地整理</span>
                )}
                {aiCorrectionStatus.type === 'error' && (
                  <span
                    className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-400 cursor-help"
                    title={aiCorrectionStatus.message || 'AI 整理失败'}
                  >
                    {aiCorrectionStatus.message?.includes('删减')
                      ? 'AI 纠正被拦截：疑似删减'
                      : aiCorrectionStatus.message?.includes('超时')
                        ? 'AI 纠正超时'
                        : aiCorrectionStatus.message?.includes('未配置')
                          ? '本地整理：未配置 API'
                          : 'AI 纠正失败'}
                  </span>
                )}
              </h2>
              <div className="flex items-center gap-2">
                {transcript.state.transcriptText && !recording.state.isRecording && !audioUpload.state.isUploadingAudio && !recording.state.isProcessing && (
                  <button
                    onClick={async () => {
                      const ok = await restructure.actions.handleRestructure(sessionId, transcript.actions.receiveAiText, setAiCorrectionStatus, autoGen.state.autoGenerateStudyMaterials);
                      if (!ok || !sessionId || ppt.state.slides.length === 0) return;
                      // Re-match PPT slides after AI finalization produces clean text.
                      try {
                        const result = await insertPPTIntoTranscript(sessionId);
                        if (result.blocks?.some((b) => b.type === 'image')) {
                          transcript.actions.updateContentBlocks(result.blocks, false, true);
                        }
                      } catch { /* ignore */ }
                    }}
                    disabled={restructure.state.isRestructuring || processing.processingStatus?.overall_status === 'running'}
                    className={`px-2 py-1 text-[10px] font-medium rounded flex items-center gap-1 transition-colors disabled:opacity-50 ${
                      processing.processingStatus?.stages?.transcript_finalize?.status === 'ready' ||
                      processing.processingStatus?.stages?.transcript_finalize?.status === 'fallback'
                        ? 'bg-blue-50 text-blue-600 hover:bg-blue-100 dark:bg-blue-900/20 dark:text-blue-400 dark:hover:bg-blue-900/30'
                        : 'bg-blue-600 text-white hover:bg-blue-700 shadow-sm'
                    }`}
                    title="调用 DeepSeek 整理转写文本并生成学习资料"
                  >
                    {restructure.state.isRestructuring ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    {processing.processingStatus?.stages?.transcript_finalize?.status === 'ready' ||
                    processing.processingStatus?.stages?.transcript_finalize?.status === 'fallback'
                      ? '重新 AI 整理'
                      : 'AI 整理'}
                  </button>
                )}
                {transcript.state.lastSaveTime && <span className="text-xs text-slate-400">已保存 {new Date(transcript.state.lastSaveTime).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}</span>}
              </div>
            </div>

            {recording.state.audioPlaybackUrl && !recording.state.isRecording && (
              <div className="mb-3 p-2.5 bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 rounded-xl flex items-center gap-3">
                <button onClick={() => {
                  if (!recording.refs.audioPlayerRef.current) return;
                  if (recording.state.isPlayingAudio) { recording.refs.audioPlayerRef.current.pause(); recording.actions.setIsPlayingAudio(false); }
                  else { recording.refs.audioPlayerRef.current.play(); recording.actions.setIsPlayingAudio(true); }
                }}
                  className="min-w-[44px] min-h-[44px] rounded-full bg-blue-500 text-white flex items-center justify-center hover:bg-blue-600 transition-colors">
                  {recording.state.isPlayingAudio ? <Pause className="w-3.5 h-3.5" /> : <Play className="w-3.5 h-3.5 ml-0.5" />}
                </button>
                <span className="text-xs text-blue-600 dark:text-blue-400 flex-1">录音回放</span>
                <button onClick={async () => {
                  if (!sessionId || !window.confirm('确定要删除录音文件吗？')) return;
                  await deleteAudio(sessionId);
                }}
                  className="min-w-[44px] min-h-[44px] rounded-lg text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 flex items-center justify-center transition-colors" title="删除录音">
                  <Trash2 className="w-3.5 h-3.5" />
                </button>
                <audio ref={recording.refs.audioPlayerRef} src={recording.state.audioPlaybackUrl}
                  onEnded={() => { recording.actions.setIsPlayingAudio(false); transcript.actions.setActiveSentenceIndex(null); lastSentenceIdxRef.current = 0; }}
                  onPause={() => { recording.actions.setIsPlayingAudio(false); }}
                  onPlay={() => { recording.actions.setIsPlayingAudio(true); lastSentenceIdxRef.current = 0; }}
                  onTimeUpdate={(e) => {
                    const currentTime = (e.target as HTMLAudioElement).currentTime;
                    const sentences = transcript.state.sentencesWithTime;
                    if (sentences.length === 0) return;
                    // Start scanning from last matched index (audio usually goes forward)
                    let idx = lastSentenceIdxRef.current;
                    if (idx >= sentences.length || currentTime < sentences[idx].startTime) {
                      idx = 0; // user seeked backward, restart from beginning
                    }
                    for (let i = idx; i < sentences.length; i++) {
                      if (currentTime >= sentences[i].startTime && currentTime < sentences[i].endTime) {
                        lastSentenceIdxRef.current = i;
                        transcript.actions.setActiveSentenceIndex(i);
                        return;
                      }
                    }
                    if (currentTime >= sentences[sentences.length - 1].startTime) {
                      lastSentenceIdxRef.current = sentences.length - 1;
                      transcript.actions.setActiveSentenceIndex(sentences.length - 1);
                    }
                  }}
                  className="hidden" />
              </div>
            )}
          </div>

          {/* 转写内容滚动区域 */}
          <div className="flex-1 overflow-y-auto px-4 md:px-6 pb-4">

            {isLiveTranscriptMode ? (
              /* 1) Live streaming — always show the editable transcript area first,
                 even when PPT blocks already exist. Otherwise the user can't see
                 or edit the incoming text while recording. */
              <div className="space-y-3">
                {/* Live transcript: confirmed finals + current partial (editable) */}
                <RichTextEditor
                  ref={transcriptEditRef}
                  value={liveTranscriptHtml}
                  onChange={(text) => {
                    transcript.actions.markUserEdited();
                    transcript.actions.updateTranscriptDraft(text);
                    // The user has edited the live stream; clear the interim
                    // partial so the next partial starts fresh after their edit.
                    transcript.actions.clearPartialText();
                  }}
                  onFocus={() => {
                    transcript.actions.setEditorFocused(true);
                    activeTextElRef.current = transcriptEditRef.current;
                  }}
                  onBlur={() => {
                    transcript.actions.setEditorFocused(false);
                    transcript.actions.commitTranscriptDraft();
                    transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
                  }}
                  placeholder={audioUpload.state.isUploadingAudio ? '正在识别上传录音，结果会逐段显示...' : '正在转录中，可直接编辑修改...'}
                  className="rich-text-editor w-full p-4 text-sm text-slate-600 dark:text-slate-300 bg-white dark:bg-slate-800 border border-blue-200 dark:border-blue-700 rounded-xl min-h-[200px] focus:outline-none focus:ring-2 focus:ring-blue-200 leading-relaxed whitespace-pre-wrap break-words"
                />
                {recording.state.isRecording && !recording.state.isPaused && (
                  <div className="flex items-center gap-2 px-3 py-2 text-slate-400 text-sm">
                    <span className="w-1.5 h-1.5 rounded-full bg-blue-400 animate-pulse" />
                    {transcript.state.partialText ? '实时识别中…' : '正在聆听…'}
                  </div>
                )}
                {(recording.state.isProcessing || audioUpload.state.isUploadingAudio) && (
                  <div className="flex items-center gap-2 text-slate-400 text-sm">
                    <Loader2 className="w-4 h-4 animate-spin" />
                    {audioUpload.state.isUploadingAudio ? (audioUpload.state.audioUploadStatus || '正在识别上传录音...') : '正在处理录音...'}
                  </div>
                )}
                {/* During recording, show a compact preview of matched slides so
                    the user can see PPT matching is working without leaving the
                    live editor. */}
                {recording.state.isRecording && transcript.state.contentBlocks.some((b) => b.type === 'image') && (
                  <div className="space-y-2">
                    <p className="text-xs text-slate-500 dark:text-slate-400">已匹配 PPT：</p>
                    <div className="flex flex-wrap gap-2">
                      {transcript.state.contentBlocks
                        .filter((b): b is ContentBlock & { type: 'image'; src: string; page?: number } => b.type === 'image' && !!b.src)
                        .map((block, idx) => (
                          <button
                            key={`live-slide-${block.page ?? idx}-${idx}`}
                            onClick={() => {
                              const slideIndex = ppt.state.slides.findIndex((s) => s.page === block.page);
                              if (slideIndex >= 0) ppt.actions.setActiveSlideIndex(slideIndex);
                            }}
                            className="relative w-20 h-14 rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 hover:ring-2 hover:ring-blue-200 transition-all"
                            title={`PPT 第 ${block.page} 页`}
                          >
                            <AuthenticatedImage
                              src={block.src}
                              alt={`PPT ${block.page}`}
                              className="w-full h-full object-cover"
                              fallback={<div className="w-full h-full bg-slate-100 dark:bg-slate-800" />}
                            />
                            {block.page && (
                              <span className="absolute bottom-0.5 right-0.5 px-1 py-0.5 text-[10px] bg-black/50 text-white rounded">
                                {block.page}
                              </span>
                            )}
                          </button>
                        ))}
                    </div>
                  </div>
                )}
              </div>
            ) : (hasPptImageBlocks || (transcript.state.contentBlocks.length > 0 && transcript.state.contentBlocks.some(b => b.type === 'image'))) ? (
              /* 2) PPT+text layout blocks — only when not currently recording/uploading */
              <ContentBlocksView
                blocks={transcript.state.contentBlocks}
                slides={ppt.state.slides}
                onSetActiveSlideIndex={(idx) => ppt.actions.setActiveSlideIndex(idx)}
                onShowLeftPanel={() => setShowLeftPanel(true)}
                onUpdateContentBlocks={(blocks) => {
                  transcript.actions.updateContentBlocks(blocks);
                  // Structural changes (drag insert) also need to be persisted.
                  transcript.actions.scheduleSave(() => notesHook.refs.notesDraftRef.current, 300);
                }}
                onUpdateBlockDraft={transcript.actions.updateContentBlockDraft}
                onCommitContentBlocks={() => {
                  transcript.actions.commitContentBlockDraft();
                  transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
                }}
                normalizeTranscriptBlockForDisplay={normalizeTranscriptBlockForDisplay}
                activeTextElRef={activeTextElRef}
                dropTargetIndex={dragState.targetIndex}
                dropPosition={dragState.targetPosition}
              />
            ) : transcript.state.transcriptText === '' ? (
              /* 3) Empty state */
              <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500">
                <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
                  {audioUpload.state.isUploadingAudio ? (
                    <Loader2 className="w-6 h-6 text-blue-400 animate-spin" />
                  ) : (
                    <Mic className="w-6 h-6 text-slate-300 dark:text-slate-600" />
                  )}
                </div>
                <p className="text-sm">{audioUpload.state.isUploadingAudio ? '正在等待第一段转写' : '点击录制按钮开始录音'}</p>
                <p className="text-xs mt-1 text-slate-300 dark:text-slate-600">
                  {audioUpload.state.isUploadingAudio ? '识别结果会先显示原文，再由 AI 替换为整理稿' : '录音将实时转写，PPT 自动对齐插入'}
                </p>
              </div>
            ) : transcript.state.transcriptText ? (
              /* 4) Editable paragraph cards — smart split into ~2-4 sentence chunks */
              <EditableParagraphCards
                transcriptText={transcript.state.transcriptText}
                containerRef={paragraphContainerRef}
                onUpdateDraft={transcript.actions.updateTranscriptDraft}
                onCommitDraft={() => {
                  transcript.actions.commitTranscriptDraft();
                  transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
                }}
                onMarkUserEdited={transcript.actions.markUserEdited}
                onSetActiveTextEl={(el) => { activeTextElRef.current = el; }}
                onClearSentences={() => {
                  if (transcript.state.sentencesWithTime.length > 0) {
                    transcript.actions.setSentencesWithTime([]);
                    transcript.actions.setActiveSentenceIndex(null);
                  }
                }}
              />
            ) : transcript.state.sentencesWithTime.length > 0 ? (
              /* 5) Fallback timestamp view when no editable transcript text exists */
              <div className="space-y-1 leading-relaxed whitespace-pre-wrap break-words">
                {transcript.state.sentencesWithTime.map((sentence, idx) => {
                  const hasAudio = !!recording.state.audioPlaybackUrl;
                  return (
                  <span
                    key={idx}
                    onClick={hasAudio ? () => {
                      if (recording.refs.audioPlayerRef.current) {
                        recording.refs.audioPlayerRef.current.currentTime = sentence.startTime;
                        recording.refs.audioPlayerRef.current.play();
                        recording.actions.setIsPlayingAudio(true);
                      }
                    } : undefined}
                    className={`inline px-0.5 py-0.5 rounded transition-colors ${
                      transcript.state.activeSentenceIndex === idx
                        ? 'bg-blue-200 dark:bg-blue-700 text-blue-900 dark:text-blue-100'
                        : hasAudio
                          ? 'cursor-pointer hover:bg-slate-100 dark:hover:bg-slate-700'
                          : ''
                    }`}
                  >
                    {sentence.text}
                  </span>
                  );
                })}
              </div>
            ) : (
              <div className="flex flex-col items-center justify-center py-20 text-slate-400 dark:text-slate-500">
                <div className="w-16 h-16 rounded-full bg-slate-100 dark:bg-slate-800 flex items-center justify-center mb-4">
                  <Mic className="w-6 h-6 text-slate-300 dark:text-slate-600" />
                </div>
                <p className="text-sm">转录内容将显示在这里</p>
              </div>
            )}

          </div>
        </main>
      </div>

      {/* ---- Mind Map Drawer ---- */}
      {mindMap.state.showMindMap && (
        <div className="fixed inset-0 z-50 flex">
          <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={() => mindMap.actions.setShowMindMap(false)} />
          <div className="relative ml-auto w-full max-w-[90vw] h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
              <div className="flex items-center gap-2">
                <BrainCircuit className="w-5 h-5 text-purple-500" />
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">知识导图</h2>
                {mindMap.state.mindMapStatus?.mind_map?.title && mindMap.state.mindMapStatus.status === 'ready' && (
                  <span className="text-sm text-slate-400 ml-2">— {mindMap.state.mindMapStatus.mind_map.title}</span>
                )}
              </div>
              <div className="flex items-center gap-2">
                {mindMap.state.mindMapStatus?.mind_map && (
                  <button onClick={mindMap.actions.handleCopyMindMapOutline} className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors" title="复制大纲">
                    {mindMap.state.copyMindMapSuccess ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
                  </button>
                )}
                {mindMap.state.mindMapStatus?.status === 'ready' && (
                  <button onClick={() => mindMap.actions.handleGenerateMindMap(mindMap.state.mindMapStatus?.status === 'ready')} disabled={mindMap.state.isGeneratingMindMap} className="px-3 py-1.5 text-xs font-medium text-purple-600 bg-purple-50 dark:bg-purple-900/20 rounded-lg hover:bg-purple-100 dark:hover:bg-purple-900/30 disabled:opacity-50 flex items-center gap-1" title="重新生成">
                    <RefreshCw className={`w-3.5 h-3.5 ${mindMap.state.isGeneratingMindMap ? 'animate-spin' : ''}`} />
                    重新生成
                  </button>
                )}
                {mindMap.state.mindMapStatus?.status === 'ready' && (
                  <button onClick={mindMap.actions.handleDeleteMindMap} className="p-2 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors" title="删除导图">
                    <Trash2 className="w-4 h-4" />
                  </button>
                )}
                <button onClick={() => mindMap.actions.setShowMindMap(false)} className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
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
                  <button onClick={() => mindMap.actions.handleGenerateMindMap()} disabled={mindMap.state.isGeneratingMindMap} className="px-4 py-2 text-sm font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50 flex items-center gap-2">
                    {mindMap.state.isGeneratingMindMap ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    {'生成导图'}
                  </button>
                </div>
              ) : mindMap.state.mindMapStatus?.status === 'error' ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-4">
                  <AlertCircle className="w-10 h-10 text-red-400 opacity-50" />
                  <p className="text-sm text-red-500">{mindMap.state.mindMapStatus.error || '生成失败'}</p>
                  <button onClick={() => mindMap.actions.handleGenerateMindMap()} disabled={mindMap.state.isGeneratingMindMap} className="px-4 py-2 text-sm font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50">重试</button>
                </div>
              ) : mindMap.state.isGeneratingMindMap || mindMap.state.mindMapStatus?.status === 'generating' ? (
                <div className="flex flex-col items-center justify-center h-full text-slate-400 gap-3">
                  <Loader2 className="w-8 h-8 animate-spin text-purple-500" />
                  <p className="text-sm">AI 正在分析课程内容，生成知识导图...</p>
                  {typeof mindMap.state.mindMapStatus?.progress === 'number' && (
                    <p className="text-xs text-slate-400">进度 {Math.round(mindMap.state.mindMapStatus.progress * 100)}%</p>
                  )}
                </div>
              ) : mindMap.state.mindMapStatus?.status === 'stale' || mindMap.state.mindMapStatus?.status === 'ready' && mindMap.state.mindMapStatus?.mind_map?.nodes?.length ? (
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
                        {mindMap.state.isGeneratingMindMap ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
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
                      onSourceClick={(source) => {
                      if (source.source_type === 'ppt' && source.page != null) {
                        ppt.actions.setActiveSlideIndex(source.page - 1);
                        return;
                      }
                      if ((source.source_type === 'transcript' || source.source_type === 'note') && source.snippet) {
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
                  <button onClick={() => mindMap.actions.handleGenerateMindMap(true)} disabled={mindMap.state.isGeneratingMindMap} className="px-4 py-2 text-sm font-medium text-white bg-purple-500 rounded-lg hover:bg-purple-600 disabled:opacity-50 flex items-center gap-2">
                    {mindMap.state.isGeneratingMindMap ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                    重新生成
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ---- Quiz Drawer ---- */}
      {quiz.state.showQuiz && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={() => { quiz.actions.setShowQuiz(false); quiz.actions.setShowQuizQA(false); }} />

          {/* ---- Left QA Panel ---- */}
          {quiz.state.showQuizQA && (
            <div className="relative z-10 w-full max-w-lg h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col border-r border-slate-200 dark:border-slate-700">
              {/* Header */}
              <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
                <div className="flex items-center gap-2">
                  <Sparkles className="w-5 h-5 text-violet-500" />
                  <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">AI 答疑</h2>
                </div>
                <button onClick={() => quiz.actions.setShowQuizQA(false)} className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>

              {/* Search input */}
              <div className="p-4 border-b border-slate-200 dark:border-slate-700 space-y-3">
                <div className="flex items-center gap-2">
                  <input
                    value={rag.state.searchQuery}
                    onChange={(e) => rag.actions.setSearchQuery(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') rag.actions.handleRAGAsk(sessionId, displayNotebook?.id, vectorIndex.actions.ensureIndexed);
                    }}
                    placeholder="输入问题，AI 将基于课堂资料回答..."
                    className="flex-1 text-sm bg-transparent outline-none text-slate-700 dark:text-slate-200 placeholder:text-slate-400"
                    autoFocus
                  />
                  <button onClick={() => rag.actions.handleRAGAsk(sessionId, displayNotebook?.id, vectorIndex.actions.ensureIndexed)} disabled={rag.state.isAskingRAG} className="px-3 py-1.5 text-xs font-medium text-white bg-violet-500 rounded-lg hover:bg-violet-600 disabled:opacity-50">
                    {rag.state.isAskingRAG ? '...' : '提问'}
                  </button>
                </div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden">
                    <button onClick={() => rag.actions.setSearchScope('session')} className={`px-2 py-1 text-[10px] font-medium transition-colors ${rag.state.searchScope === 'session' ? 'bg-blue-500 text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>本课次</button>
                    <button onClick={() => rag.actions.setSearchScope('notebook')} className={`px-2 py-1 text-[10px] font-medium transition-colors ${rag.state.searchScope === 'notebook' ? 'bg-blue-500 text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>本课程</button>
                  </div>
                  <span className="text-[10px] text-slate-400">基于测验和课次内容答疑</span>
                </div>
                {rag.state.ragError && (
                  <div className="text-xs text-red-500">{rag.state.ragError}</div>
                )}
                {rag.state.ragStatus && (
                  <div className="text-xs text-violet-500 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    {rag.state.ragStatus}
                  </div>
                )}
              </div>

              {/* Answer area */}
              <div className="flex-1 overflow-y-auto p-4">
                {rag.state.ragAnswer || rag.state.ragSources.length > 0 ? (
                  <div className="space-y-3">
                    {rag.state.ragAnswer ? (
                      <div className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">{rag.state.ragAnswer}</div>
                    ) : (
                      <div className="text-xs text-slate-400">AI 暂时没有生成回答，但已检索到相关课堂来源。</div>
                    )}
                    {rag.state.ragSources.length > 0 && (
                      <div className="pt-3 border-t border-slate-100 dark:border-slate-700">
                        <p className="text-[10px] text-slate-400 mb-2">参考来源</p>
                        <RagSourceCards
                          sources={rag.state.ragSources}
                          onSourceClick={handleRagSourceClick}
                          getSourceTypeLabel={getRagSourceTypeLabel}
                          onClose={() => quiz.actions.setShowQuizQA(false)}
                        />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-3">
                    <Sparkles className="w-10 h-10 opacity-30" />
                    <p className="text-sm">{rag.state.isAskingRAG ? '正在思考中...' : '输入问题，AI 将基于课堂资料回答'}</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ---- Right Quiz Panel ---- */}
          <div className="relative w-full max-w-2xl h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col" onClick={(e) => e.stopPropagation()}>
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
              <div className="flex items-center gap-2">
                <ClipboardCheck className="w-5 h-5 text-emerald-500" />
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">课次测验</h2>
              </div>
              <div className="flex items-center gap-2">
                {quiz.state.activeQuiz && (
                  <>
                    <button onClick={() => { quiz.actions.setActiveQuiz(null); quiz.actions.setQuizSubmitted(false); quiz.actions.setQuizAnswers({}); quiz.actions.setShowQuizQA(false); }} className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors" title="返回列表">
                      <ChevronDown className="w-4 h-4 rotate-90" />
                    </button>
                    <button onClick={() => quiz.actions.setShowQuizQA(!quiz.state.showQuizQA)} className={`p-2 rounded-lg transition-colors ${quiz.state.showQuizQA ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-slate-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20'}`} title="测验答疑">
                      <Search className="w-4 h-4" />
                    </button>
                  </>
                )}
                <button onClick={() => { quiz.actions.setShowQuiz(false); quiz.actions.setShowQuizQA(false); }} className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors">
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto">
              {quiz.state.quizError && (
                <div className="mx-5 mt-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-sm text-red-600 dark:text-red-400 flex items-center gap-2">
                  <AlertCircle className="w-4 h-4 flex-shrink-0" />
                  {quiz.state.quizError}
                  <button onClick={() => quiz.actions.setQuizError(null)} className="ml-auto text-red-400 hover:text-red-600"><X className="w-3 h-3" /></button>
                </div>
              )}

              {quiz.state.activeQuiz ? (
                /* ---- Active Quiz View ---- */
                <div className="p-5">
                  <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100 mb-4">{quiz.state.activeQuiz.title}</h3>

                  {quiz.state.quizSubmitted && quiz.state.activeQuiz.submission ? (
                    /* ---- Results View ---- */
                    <div>
                      <div className="flex items-center gap-4 mb-6 p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
                        <div className="text-center">
                          <div className={`text-3xl font-bold ${quiz.state.activeQuiz.submission.percentage >= 60 ? 'text-emerald-500' : 'text-red-500'}`}>
                            {quiz.state.activeQuiz.submission.percentage}%
                          </div>
                          <div className="text-xs text-slate-400 mt-1">正确率</div>
                        </div>
                        <div className="text-center">
                          <div className="text-2xl font-bold text-slate-700 dark:text-slate-200">
                            {quiz.state.activeQuiz?.submission?.score}/{quiz.state.activeQuiz?.submission?.total}
                          </div>
                          <div className="text-xs text-slate-400 mt-1">答对题数</div>
                        </div>
                      </div>

                      <div className="space-y-4">
                        {quiz.state.activeQuiz?.questions.map((q, idx) => {
                          const result = quiz.state.activeQuiz?.submission?.results.find(r => r.question_id === q.id);
                          const isCorrect = result?.correct;
                          return (
                            <div key={q.id} className={`p-4 rounded-xl border ${isCorrect ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/10' : 'border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-900/10'}`}>
                              <div className="flex items-start gap-2 mb-2">
                                <span className={`text-xs font-bold mt-0.5 ${isCorrect ? 'text-emerald-500' : 'text-red-500'}`}>
                                  {isCorrect ? '✓' : '✗'}
                                </span>
                                <span className="text-sm font-medium text-slate-700 dark:text-slate-200">{idx + 1}. {q.question}</span>
                              </div>
                              <div className="space-y-1.5 ml-5">
                                {q.options.map(opt => {
                                  const isSelected = result?.selected === opt.id;
                                  const isAnswer = q.answer === opt.id;
                                  return (
                                    <div key={opt.id} className={`text-xs px-2.5 py-1.5 rounded-lg ${isAnswer ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 font-medium' : isSelected ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 line-through' : 'text-slate-500 dark:text-slate-400'}`}>
                                      <span className="font-medium mr-1">{opt.id}.</span> {opt.text}
                                      {opt.explanation && <span className="ml-1 opacity-70">— {opt.explanation}</span>}
                                    </div>
                                  );
                                })}
                              </div>
                              {q.explanation && (
                                <div className="mt-2 ml-5 text-xs text-slate-500 dark:text-slate-400">
                                  <span className="font-medium">解析：</span>{q.explanation}
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ) : (
                    /* ---- Taking Quiz View ---- */
                    <div>
                      <div className="space-y-5">
                        {quiz.state.activeQuiz?.questions.map((q, idx) => (
                          <div key={q.id} className="p-4 rounded-xl border border-slate-200 dark:border-slate-600">
                            <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3">
                              <span className="text-emerald-500 mr-1">{idx + 1}.</span>
                              {q.question}
                            </p>
                            <div className="space-y-2">
                              {q.options.map(opt => (
                                <button
                                  key={opt.id}
                                  onClick={() => quiz.actions.setQuizAnswers(prev => ({ ...prev, [q.id]: opt.id }))}
                                  className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors flex items-center gap-2 ${
                                    quiz.state.quizAnswers[q.id] === opt.id
                                      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700'
                                      : 'bg-slate-50 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border border-transparent hover:bg-slate-100 dark:hover:bg-slate-600'
                                  }`}
                                >
                                  <CircleDot className={`w-4 h-4 flex-shrink-0 ${quiz.state.quizAnswers[q.id] === opt.id ? 'text-emerald-500' : 'text-slate-300 dark:text-slate-500'}`} />
                                  <span className="font-medium mr-1">{opt.id}.</span>
                                  {opt.text}
                                </button>
                              ))}
                            </div>
                          </div>
                        ))}
                      </div>
                      <div className="mt-6 flex items-center justify-between">
                        <span className="text-xs text-slate-400">已答 {Object.keys(quiz.state.quizAnswers).length}/{quiz.state.activeQuiz.questions.length} 题</span>
                        <button
                          onClick={quiz.actions.handleSubmitQuiz}
                          disabled={Object.keys(quiz.state.quizAnswers).length < quiz.state.activeQuiz.questions.length}
                          className="px-5 py-2.5 text-sm font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                        >
                          提交答案
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              ) : (
                /* ---- Quiz List View ---- */
                <div className="p-5">
                  {/* Bank Status Banner */}
                  {quiz.state.bankStatus && quiz.state.bankStatus.status !== 'ready' && (
                    <div className={`mb-4 p-3 rounded-lg text-sm flex items-center gap-2 ${
                      quiz.state.bankStatus.status === 'generating' ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400' :
                      quiz.state.bankStatus.status === 'error' ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400' :
                      quiz.state.bankStatus.status === 'empty' ? 'bg-slate-50 dark:bg-slate-700 text-slate-500' :
                      'bg-slate-50 dark:bg-slate-700 text-slate-500'
                    }`}>
                      {quiz.state.bankStatus.status === 'generating' && <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />}
                      {quiz.state.bankStatus.status === 'error' && <AlertCircle className="w-4 h-4 flex-shrink-0" />}
                      <span>
                        {quiz.state.bankStatus.status === 'generating' && '题库生成中，请稍候...'}
                        {quiz.state.bankStatus.status === 'error' && `题库生成失败: ${quiz.state.bankStatus.error || '未知错误'}`}
                        {quiz.state.bankStatus.status === 'empty' && '当前课次没有可生成的内容'}
                        {quiz.state.bankStatus.status === 'not_generated' && '尚未生成题库'}
                      </span>
                      {(quiz.state.bankStatus.status === 'error' || quiz.state.bankStatus.status === 'not_generated') && (
                        <button
                          onClick={quiz.actions.handleRebuildBank}
                          disabled={quiz.state.isRebuildingBank}
                          className="ml-auto px-2.5 py-1 text-xs font-medium text-white bg-blue-500 rounded hover:bg-blue-600 disabled:opacity-50 flex items-center gap-1"
                        >
                          {quiz.state.isRebuildingBank && <Loader2 className="w-3 h-3 animate-spin" />}
                          生成题库
                        </button>
                      )}
                    </div>
                  )}

                  {/* Rebuild Bank Button (when bank is ready) */}
                  {quiz.state.bankStatus && quiz.state.bankStatus.status === 'ready' && (
                    <div className="mb-4 flex items-center justify-between p-3 rounded-lg bg-emerald-50 dark:bg-emerald-900/10 text-sm">
                      <span className="text-emerald-600 dark:text-emerald-400">
                        题库已就绪 ({quiz.state.bankStatus.question_count} 题)
                      </span>
                      <button
                        onClick={quiz.actions.handleRebuildBank}
                        disabled={quiz.state.isRebuildingBank}
                        className="px-2.5 py-1 text-xs font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded hover:bg-amber-100 dark:hover:bg-amber-900/40 disabled:opacity-50 flex items-center gap-1"
                        title="重新生成题库会调用 AI"
                      >
                        {quiz.state.isRebuildingBank ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                        重新生成题库
                      </button>
                    </div>
                  )}

                  {quiz.state.isGeneratingQuiz ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-3">
                      <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
                      <p className="text-sm">正在从题库抽取题目...</p>
                    </div>
                  ) : quiz.state.quizList.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-4">
                      <ClipboardCheck className="w-10 h-10 opacity-30" />
                      <p className="text-sm">尚未开始测验</p>
                      <button
                        onClick={quiz.actions.handleGenerateQuiz}
                        disabled={!quiz.state.bankStatus || quiz.state.bankStatus.status !== 'ready'}
                        className="px-4 py-2 text-sm font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
                      >
                        开始测验
                      </button>
                    </div>
                  ) : (
                    <div>
                      <div className="flex items-center justify-between mb-4">
                        <span className="text-sm text-slate-500">历史测验</span>
                        <button
                          onClick={quiz.actions.handleGenerateQuiz}
                          disabled={quiz.state.isGeneratingQuiz || !quiz.state.bankStatus || quiz.state.bankStatus.status !== 'ready'}
                          className="px-3 py-1.5 text-xs font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600 disabled:opacity-50 flex items-center gap-1"
                        >
                          {quiz.state.isGeneratingQuiz ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                          开始新测验
                        </button>
                      </div>
                      <div className="space-y-2">
                        {quiz.state.quizList.map(q => (
                          <div key={q.quiz_id} className="flex items-center justify-between p-3 rounded-xl border border-slate-200 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors">
                            <button
                              onClick={() => quiz.actions.handleOpenQuiz(q.quiz_id, q.submitted)}
                              className="flex-1 text-left"
                            >
                              <div className="text-sm font-medium text-slate-700 dark:text-slate-200">{q.title}</div>
                              <div className="text-xs text-slate-400 mt-0.5">
                                {q.question_count} 题 · {q.submitted ? '已完成' : '未完成'}
                                {q.score && ` · ${q.score.percentage}%`}
                                {q.generated_at && ` · ${new Date(q.generated_at).toLocaleDateString()}`}
                              </div>
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); quiz.actions.handleDeleteQuiz(q.quiz_id); }}
                              className="p-1.5 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                              title="删除"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {rag.state.showSearch && (
        <div className="fixed inset-0 z-50 flex items-start justify-center pt-20 bg-black/30 backdrop-blur-sm" onClick={() => rag.actions.setShowSearch(false)}>
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl w-full max-w-lg mx-4 overflow-hidden" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center gap-2 p-4 border-b border-slate-200 dark:border-slate-700">
              <Sparkles className="w-4 h-4 text-violet-400" />
              <input
                value={rag.state.searchQuery}
                onChange={(e) => rag.actions.setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') rag.actions.handleRAGAsk(sessionId, displayNotebook?.id, vectorIndex.actions.ensureIndexed);
                }}
                placeholder="输入问题，AI 将基于课堂资料回答..."
                className="flex-1 text-sm bg-transparent outline-none text-slate-700 dark:text-slate-200 placeholder:text-slate-400"
                autoFocus
              />
              <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden">
                <button onClick={() => rag.actions.setSearchScope('session')} className={`px-2 py-1 text-[10px] font-medium transition-colors ${rag.state.searchScope === 'session' ? 'bg-blue-500 text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>本课次</button>
                <button onClick={() => rag.actions.setSearchScope('notebook')} className={`px-2 py-1 text-[10px] font-medium transition-colors ${rag.state.searchScope === 'notebook' ? 'bg-blue-500 text-white' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'}`}>本课程</button>
              </div>
              <button onClick={() => rag.actions.handleRAGAsk(sessionId, displayNotebook?.id, vectorIndex.actions.ensureIndexed)} disabled={rag.state.isAskingRAG} className="px-3 py-1.5 text-xs font-medium text-white bg-violet-500 rounded-lg hover:bg-violet-600 disabled:opacity-50">
                {rag.state.isAskingRAG ? '...' : '提问'}
              </button>
            </div>
            <div className="max-h-96 overflow-y-auto">
              <div className="p-4">
                {rag.state.ragError && (
                  <div className="mb-3 text-xs text-red-500">{rag.state.ragError}</div>
                )}
                {rag.state.ragStatus && (
                  <div className="mb-3 text-xs text-violet-500 flex items-center gap-1">
                    <Loader2 className="w-3 h-3 animate-spin" />
                    {rag.state.ragStatus}
                  </div>
                )}
                {rag.state.ragAnswer || rag.state.ragSources.length > 0 ? (
                  <div className="space-y-3">
                    {rag.state.ragAnswer ? (
                      <div className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">{rag.state.ragAnswer}</div>
                    ) : (
                      <div className="text-xs text-slate-400">AI 暂时没有生成回答，但已检索到相关课堂来源。</div>
                    )}
                    {rag.state.ragSources.length > 0 && (
                      <div className="pt-3 border-t border-slate-100 dark:border-slate-700">
                        <p className="text-[10px] text-slate-400 mb-2">参考来源</p>
                        <RagSourceCards
                          sources={rag.state.ragSources}
                          onSourceClick={handleRagSourceClick}
                          getSourceTypeLabel={getRagSourceTypeLabel}
                          onClose={() => rag.actions.setShowSearch(false)}
                        />
                      </div>
                    )}
                  </div>
                ) : (
                  <div className="py-8 text-center text-xs text-slate-400">
                    {rag.state.isAskingRAG ? '正在思考中...' : '输入问题，AI 将基于课堂资料回答'}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

{share.state.showShareModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={() => share.actions.setShowShareModal(false)}>
          <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-xl p-6 w-full max-w-md mx-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-base font-semibold text-slate-800 dark:text-slate-200">分享课次</h3>
              <button onClick={() => share.actions.setShowShareModal(false)} className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"><X className="w-4 h-4" /></button>
            </div>
            {share.state.shareLoading ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
              </div>
            ) : share.state.shareEnabled && share.state.shareLink ? (
              <>
                <div className="flex items-center gap-2 mb-3">
                  <span className="w-2 h-2 rounded-full bg-green-400" />
                  <span className="text-xs text-green-600 dark:text-green-400">分享已开启</span>
                  {share.state.shareExpiresAt && (
                    <span className="text-xs text-amber-600 dark:text-amber-400 ml-2">
                      有效期至 {new Date(share.state.shareExpiresAt).toLocaleString()}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mb-4">
                  <input readOnly value={share.state.shareLink} className="flex-1 px-3 py-2 text-sm border border-slate-200 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-900 text-slate-600 dark:text-slate-300" />
                  <button onClick={() => { navigator.clipboard.writeText(share.state.shareLink); share.actions.setCopySuccess(true); setTimeout(() => share.actions.setCopySuccess(false), 3000); }}
                    className="px-3 py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-colors">{share.state.copySuccess ? '已复制' : '复制'}</button>
                </div>
                {share.state.shareMaxViews !== null && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mb-3">
                    已访问 {share.state.shareViewCount} / {share.state.shareMaxViews} 次
                  </p>
                )}
                <button onClick={() => share.actions.handleDisableShare(sessionId!)} className="w-full py-2 text-sm text-red-500 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg transition-colors">
                  关闭分享
                </button>
              </>
            ) : (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">有效期（小时）</label>
                    <input
                      type="number"
                      min={1}
                      placeholder="不限"
                      value={share.state.shareExpiresIn}
                      onChange={(e) => share.actions.setShareExpiresIn(e.target.value === '' ? '' : Number(e.target.value))}
                      className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-300"
                    />
                  </div>
                  <div>
                    <label className="block text-xs text-slate-500 dark:text-slate-400 mb-1">最大访问次数</label>
                    <input
                      type="number"
                      min={1}
                      placeholder="不限"
                      value={share.state.shareMaxViewsInput}
                      onChange={(e) => share.actions.setShareMaxViewsInput(e.target.value === '' ? '' : Number(e.target.value))}
                      className="w-full px-3 py-2 text-sm border border-slate-200 dark:border-slate-600 rounded-lg bg-slate-50 dark:bg-slate-700 text-slate-800 dark:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-300"
                    />
                  </div>
                </div>
                <button onClick={() => share.actions.handleShareSession(sessionId!, share.state.shareExpiresIn, share.state.shareMaxViewsInput)} className="w-full py-2 text-sm font-medium text-white bg-blue-500 rounded-lg hover:bg-blue-600 transition-colors">
                  开启分享
                </button>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ---- Drag preview overlay ---- */}
      {dragState.slide && dragState.pointer && (
        <div
          className="fixed z-[100] pointer-events-none"
          style={{
            left: dragState.pointer.x + 12,
            top: dragState.pointer.y + 12,
            width: 160,
          }}
        >
          <div className="rounded-lg overflow-hidden border-2 border-blue-400 shadow-xl bg-white dark:bg-slate-900">
            <AuthenticatedImage
              src={dragState.slide.image_path
                ? getMediaUrl(`/api/media/slides/${sessionId}/${dragState.slide.image_path}`)
                : dragState.slide.image_base64 || ''}
              alt={`Slide ${dragState.slide.page}`}
              className="w-full object-cover"
              fallback={<div className="flex items-center justify-center h-20 text-xs text-slate-400">无预览图</div>}
            />
          </div>
          <div className="mt-1 px-2 py-1 bg-blue-500 text-white text-[10px] rounded-md shadow-md inline-block">
            插入到第 {dragState.slide.page} 页
          </div>
        </div>
      )}
    </div>
  );
}
