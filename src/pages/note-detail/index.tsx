import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { toast } from 'sonner';
import { FileText, Loader2, X, Edit3 } from 'lucide-react';
import { useStore } from '@/store/useStore';
import { useState, useRef, useCallback, useEffect } from 'react';
import { getProfile } from '@/services/auth';
import type { UserProfile } from '@/services/auth';

import { type RichTextEditorHandle } from '@/components/RichTextEditor';
import { preloadAuthenticatedImage } from '@/lib/imageCache';
import { getMediaUrl, fetchNotebookDetail, fetchSessionById, insertPPTIntoTranscript, type Slide } from '@/services/api';
import type { Notebook, Session } from '@/types';

import { useRecording } from './useRecording';
import { useTranscript } from './useTranscript';
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
import { useRestructure, type CorrectionStatus } from './hooks/useRestructure';
import { useProcessingStatus } from './hooks/useProcessingStatus';
import { useWorkflowStatus } from './hooks/useWorkflowStatus';
import type { ContentBlock, RAGSource } from '@/services/api';

import { NoteEditableParagraphCards } from './components/NoteEditableParagraphCards';
import { NoteDetailTopNav } from './components/NoteDetailTopNav';
import { NoteDetailToolbar } from './components/NoteDetailToolbar';
import { NoteDetailStatusBanners } from './components/NoteDetailStatusBanners';
import { PPTPanel, type DragState } from './components/PPTPanel';
import { SideNotesPanel } from './components/SideNotesPanel';
import { NotesPanel } from './components/NotesPanel';
import { MindMapDrawer } from './components/MindMapDrawer';
import { QuizDrawer } from './components/QuizDrawer';
import { RagSearchModal } from './components/RagSearchModal';
import { ShareModal } from './components/ShareModal';
import { DragPreviewOverlay } from './components/DragPreviewOverlay';

export { NoteEditableParagraphCards as EditableParagraphCards };

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

  useEffect(() => {
    getProfile().then(setProfile).catch(() => {});
  }, []);

  useEffect(() => {
    if (!id || notebook) return;
    fetchNotebookDetail(id)
      .then((data) => {
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
      })
      .catch(() => {});
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
  const auxiliarySessionId = transcript.state.isLoaded ? sessionId : undefined;

  const share = useShare();
  const vectorIndex = useVectorIndex(auxiliarySessionId, processing.processingStatus);
  const rag = useRAG();
  const mindMap = useMindMap(auxiliarySessionId, processing.processingStatus);
  const quiz = useQuiz(auxiliarySessionId, processing.processingStatus);
  const audioUpload = useAudioUpload(sessionId, { onFinalize: processing.refresh });
  const autoGen = useAutoGenerate(auxiliarySessionId, processing.processingStatus, processing.refresh);
  const restructure = useRestructure();

  const [isLoading, setIsLoading] = useState(true);
  const [showLeftPanel, setShowLeftPanel] = useState(false);
  const [showNotesDrawer, setShowNotesDrawer] = useState(false);
  const [aiCorrectionStatus, setAiCorrectionStatus] = useState<CorrectionStatus>({ type: 'idle' });

  const hasPPT = ppt.state.slides.length > 0;

  const isPendingCorrectionMessage = (message?: string | null) => {
    if (!message) return false;
    return message.includes('等待统一 AI 整理') || message.includes('正在统一 AI 整理');
  };

  const fileInputRef = useRef<HTMLInputElement>(null);
  const transcriptEditRef = useRef<RichTextEditorHandle>(null);
  const noteEditRef = useRef<RichTextEditorHandle>(null);
  const activeTextElRef = useRef<HTMLDivElement | null>(null);
  const lastSentenceIdxRef = useRef(0);
  const paragraphContainerRef = useRef<HTMLDivElement>(null);

  // Drag-to-insert PPT state
  const [dragState, setDragState] = useState<DragState>({
    slide: null,
    pointer: null,
    targetIndex: null,
    targetPosition: null,
  });
  const longPressTimerRef = useRef<number | null>(null);
  const dragStartPosRef = useRef<{ x: number; y: number } | null>(null);
  const isDraggingRef = useRef(false);

  const getRagSourceTypeLabel = useCallback((source: RAGSource) => {
    const rawType =
      source.source_type === 'layout'
        ? String(source.metadata?.block_type || source.source_type)
        : source.source_type;
    if (rawType === 'ppt') return 'PPT';
    if (rawType === 'transcript') return '转写';
    if (rawType === 'note') return '笔记';
    return '资料';
  }, []);

  const highlightElement = useCallback((targetEl: HTMLElement) => {
    targetEl.scrollIntoView({ behavior: 'smooth', block: 'center' });
    targetEl.classList.add('ring-2', 'ring-violet-300', 'bg-violet-50', 'dark:bg-violet-900/20');
    window.setTimeout(() => {
      targetEl.classList.remove('ring-2', 'ring-violet-300', 'bg-violet-50', 'dark:bg-violet-900/20');
    }, 3000);
  }, []);

  const highlightTranscriptAnchor = useCallback(
    (source: RAGSource) => {
      const container = paragraphContainerRef.current;
      if (!container) return false;
      const rawId =
        source.block_id ||
        (typeof source.metadata?.paragraph_id === 'string' ? source.metadata.paragraph_id : null);
      if (!rawId || rawId === 'canonical-transcript' || rawId === 'student-notes') return false;
      const escapeSelector = (value: string) =>
        typeof CSS !== 'undefined' && typeof CSS.escape === 'function'
          ? CSS.escape(value)
          : value.replace(/["\\]/g, '\\$&');
      const targetEl = container.querySelector(
        `[data-paragraph-id="${escapeSelector(rawId)}"], [data-transcript-block][data-block-id="${escapeSelector(rawId)}"]`,
      ) as HTMLElement | null;
      if (!targetEl) return false;
      highlightElement(targetEl);
      return true;
    },
    [highlightElement],
  );

  const highlightTranscriptSnippet = useCallback((snippet?: string | null) => {
    const container = paragraphContainerRef.current;
    if (!container || !snippet) return false;
    const normalize = (value: string) => value.replace(/\s+/g, '').toLowerCase();
    const target = normalize(snippet).slice(0, 80);
    if (!target) return false;

    const candidates = Array.from(container.querySelectorAll('[data-transcript-block]')) as HTMLElement[];
    const targetEl = candidates.find((el) => normalize(el.textContent || '').includes(target));
    if (!targetEl) return false;

    highlightElement(targetEl);
    return true;
  }, [highlightElement]);

  const handleRagSourceClick = useCallback(
    (source: RAGSource, closePanel?: () => void) => {
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
        const located = highlightTranscriptAnchor(source) || highlightTranscriptSnippet(source.snippet);
        if (!located) toast.info('已找到来源，但当前页面没有可精确定位的文本块');
      }, 200);
    },
    [getRagSourceTypeLabel, highlightTranscriptAnchor, highlightTranscriptSnippet, navigate, ppt.actions, sessionId],
  );

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
  useEffect(() => {
    if (!sessionId) {
      setIsLoading(false);
      return;
    }
  }, [sessionId]);

  // Provide the latest notes draft getter to useTranscript so debounced saves
  // always use the most recent notes content, not a stale closure.
  useEffect(() => {
    transcript.actions.setGetCurrentNotes(() => notesHook.refs.notesDraftRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
      const hasTranscript = Boolean(
        loadedNote.transcript && Array.isArray(loadedNote.transcript) && loadedNote.transcript.length > 0,
      );
      const parsed = notesHook.actions.parseNotesFromContent(loadedNote.content, hasTranscript);
      if (parsed.length > 0) {
        notesHook.actions.setNotes(parsed);
        notesHook.actions.resetDrafts(parsed);
      }
    }
    // Set AI correction status from loaded note
    if (loadedNote?.transcript && Array.isArray(loadedNote.transcript) && loadedNote.transcript.length > 0) {
      const sorted = [...loadedNote.transcript].sort(
        (a: { chunk_index?: number }, b: { chunk_index?: number }) =>
          (a.chunk_index || 0) - (b.chunk_index || 0),
      );
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
      const hasLayoutBlocks =
        loadedNote.layout_blocks && Array.isArray(loadedNote.layout_blocks) && loadedNote.layout_blocks.length > 0;
      if (!hasLayoutBlocks) {
        setTimeout(async () => {
          try {
            const blocks = await insertPPTIntoTranscript(sessionId);
            if (blocks.blocks?.some((b: ContentBlock) => b.type === 'image')) {
              transcript.actions.updateContentBlocks(blocks.blocks, false, false);
            }
          } catch (err) {
            console.error('[NoteDetail] Failed to auto-insert PPT after load:', err);
          }
        }, 500);
      }
    }
    setIsLoading(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    processing.processingStatus?.stages?.transcript_finalize?.status,
    processing.processingStatus?.stages?.transcript_finalize?.message,
    processing.processingStatus?.stages?.transcript_finalize?.error_message,
  ]);

  // ---- Auto-save ----
  useEffect(() => {
    if (!sessionId || !transcript.state.isLoaded || !transcript.state.hasLocalChanges || audioUpload.state.isUploadingAudio)
      return;
    transcript.actions.scheduleSave(() => notesHook.refs.notesDraftRef.current, 300);
    return () => {};
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    sessionId,
    transcript.state.isLoaded,
    transcript.state.hasLocalChanges,
    notesHook.refs.notesDraftRef,
    transcript.actions.scheduleSave,
    audioUpload.state.isUploadingAudio,
  ]);

  const { workflowStatus, statusClass } = useWorkflowStatus({
    processingStatus: processing.processingStatus,
    audioUpload: audioUpload.state,
    ppt: ppt.state,
    recording: recording.state,
    transcript: transcript.state,
    mindMap: mindMap.state,
    quiz: quiz.state,
  });

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

  const detectDropTarget = useCallback(
    (clientX: number, clientY: number): { index: number | null; position: 'before' | 'after' | null } => {
      const el = document.elementFromPoint(clientX, clientY);
      const blockEl = el?.closest('[data-block-index]') as HTMLElement | null;
      if (!blockEl) return { index: null, position: null };
      const index = Number(blockEl.getAttribute('data-block-index'));
      if (Number.isNaN(index)) return { index: null, position: null };
      const rect = blockEl.getBoundingClientRect();
      const position: 'before' | 'after' = clientY < rect.top + rect.height / 2 ? 'before' : 'after';
      return { index, position };
    },
    [],
  );

  const insertSlideBlock = useCallback(
    (slide: Slide, targetIndex: number, position: 'before' | 'after') => {
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
    },
    [sessionId, transcript.actions, transcript.state.contentBlocks],
  );

  const updateDrag = useCallback(
    (clientX: number, clientY: number) => {
      const target = detectDropTarget(clientX, clientY);
      setDragState((prev) => ({
        ...prev,
        pointer: { x: clientX, y: clientY },
        targetIndex: target.index,
        targetPosition: target.position,
      }));
    },
    [detectDropTarget],
  );

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

  const handleSlideMouseDown = useCallback(
    (slide: Slide) => (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      startDrag(slide, e.clientX, e.clientY);
    },
    [startDrag],
  );

  const handleSlideTouchStart = useCallback(
    (slide: Slide) => (e: React.TouchEvent) => {
      const touch = e.touches[0];
      dragStartPosRef.current = { x: touch.clientX, y: touch.clientY };
      if (longPressTimerRef.current) window.clearTimeout(longPressTimerRef.current);
      longPressTimerRef.current = window.setTimeout(() => {
        longPressTimerRef.current = null;
        startDrag(slide, touch.clientX, touch.clientY);
      }, 400);
    },
    [startDrag],
  );

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, transcript.state.hasLocalChanges, transcript.actions.saveContent, notesHook.refs.notesDraftRef, navigate, id]);

  // ---- PPT ----
  const handlePPTClick = () => fileInputRef.current?.click();

  const handlePPTSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    await ppt.actions.handlePPTUpload(file);
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const handleStopRecording = useCallback(async () => {
    const result = await recording.actions.stopRecording(transcript.actions.receiveAiText);
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [recording.actions.stopRecording, transcript.actions.receiveAiText, processing.refresh]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50 dark:bg-slate-950">
        <div className="flex items-center gap-2 text-slate-400">
          <Loader2 className="w-5 h-5 animate-spin" /> 加载中...
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-950">
      {/* ---- Top Nav ---- */}
      <NoteDetailTopNav
        displaySession={displaySession}
        displayNotebook={displayNotebook}
        profile={profile}
        sessionId={sessionId}
        onBack={handleBack}
        onNavigateProfile={() => navigate('/profile')}
        transcriptText={transcript.state.transcriptText}
        contentBlocks={transcript.state.contentBlocks}
        notes={notesHook.state.notes}
        exportTools={exportTools}
        share={share}
        rag={rag}
        mindMap={mindMap}
        quiz={quiz}
        vectorIndex={vectorIndex}
      />

      {/* ---- Toolbar ---- */}
      <NoteDetailToolbar
        fileInputRef={fileInputRef}
        onPPTClick={handlePPTClick}
        onPPTSelect={handlePPTSelect}
        onStopRecording={handleStopRecording}
        activeTextElRef={activeTextElRef}
        paragraphContainerRef={paragraphContainerRef}
        ppt={ppt}
        recording={recording}
        transcript={transcript}
        audioUpload={audioUpload}
        setAiCorrectionStatus={setAiCorrectionStatus}
      />

      <NoteDetailStatusBanners
        autoGen={autoGen}
        workflowStatus={workflowStatus}
        statusClass={statusClass}
        ppt={ppt}
        recording={recording}
        transcript={transcript}
        audioUpload={audioUpload}
        processingStatus={processing.processingStatus}
        processingOverallStatus={processing.processingStatus?.overall_status}
        onRetryAgents={(agents) => autoGen.actions.handleTriggerAgents(sessionId, agents, true)}
        onRetrySave={() => {
          notesHook.actions.commitNotesDraft();
          transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, true);
        }}
        onDismissRecordingError={() => {
          recording.actions.setIsError(false);
          recording.actions.setErrorMessage('');
        }}
        onDismissPPTError={() => ppt.actions.setUploadError(null)}
        onDismissAudioError={() => audioUpload.actions.setAudioUploadError(null)}
      />

      {/* ---- Three-column layout (sidebars overlay on tablet) ---- */}
      <div className="flex-1 flex overflow-hidden">
        {hasPPT && !showLeftPanel && (
          <button
            onClick={() => setShowLeftPanel(true)}
            className="lg:hidden fixed bottom-20 right-6 z-40 w-11 h-11 rounded-full bg-blue-500 text-white shadow-lg flex items-center justify-center hover:bg-blue-600 transition-colors"
            title="PPT 与笔记"
          >
            <FileText className="w-5 h-5" />
          </button>
        )}
        {!hasPPT && !showNotesDrawer && (
          <button
            onClick={() => setShowNotesDrawer(true)}
            className="fixed bottom-20 right-6 z-40 w-11 h-11 rounded-full bg-amber-500 text-white shadow-lg flex items-center justify-center hover:bg-amber-600 transition-colors"
            title="随堂思考"
          >
            <Edit3 className="w-5 h-5" />
          </button>
        )}

        {/* ---- Left auxiliary panel (PPT + notes) ---- */}
        {hasPPT && showLeftPanel && (
          <div
            onClick={() => setShowLeftPanel(false)}
            className="lg:hidden fixed inset-0 z-40 bg-black/50 backdrop-blur-sm"
          />
        )}
        {hasPPT && (
          <aside
            className={`${
              showLeftPanel ? 'fixed inset-y-0 left-0 z-50 w-80' : 'hidden'
            } lg:relative lg:flex lg:w-[30%] flex-shrink-0 bg-white/60 dark:bg-slate-800/60 backdrop-blur-sm border-r border-slate-200/60 dark:border-slate-700/60 flex flex-col overflow-hidden`}
          >
            <div className="lg:hidden flex-shrink-0 px-3 py-2 flex items-center justify-between border-b border-slate-200/60 dark:border-slate-700/60">
              <div className="flex items-center gap-1.5">
                <FileText className="w-3.5 h-3.5 text-blue-500" />
                <h3 className="text-xs font-semibold text-slate-600 dark:text-slate-300">PPT 与笔记</h3>
              </div>
              <button
                onClick={() => setShowLeftPanel(false)}
                className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <PPTPanel
              ppt={ppt}
              dragState={dragState}
              sessionId={sessionId}
              onSlideMouseDown={handleSlideMouseDown}
              onSlideTouchStart={handleSlideTouchStart}
              onSlideTouchMove={handleSlideTouchMove}
              onSlideTouchEnd={handleSlideTouchEnd}
            />

            <SideNotesPanel
              noteEditRef={noteEditRef}
              notesHook={notesHook}
              transcript={transcript}
              activeTextElRef={activeTextElRef}
            />
          </aside>
        )}

        {/* ---- Right: Transcript (full width when no PPT) ---- */}
        <NotesPanel
          sessionId={sessionId}
          recording={recording}
          transcript={transcript}
          notesHook={notesHook}
          ppt={ppt}
          audioUpload={audioUpload}
          restructure={restructure}
          processingStatus={processing.processingStatus}
          autoGen={autoGen}
          aiCorrectionStatus={aiCorrectionStatus}
          setAiCorrectionStatus={setAiCorrectionStatus}
          transcriptEditRef={transcriptEditRef}
          paragraphContainerRef={paragraphContainerRef}
          activeTextElRef={activeTextElRef}
          lastSentenceIdxRef={lastSentenceIdxRef}
          normalizeTranscriptBlockForDisplay={normalizeTranscriptBlockForDisplay}
          onShowLeftPanel={() => setShowLeftPanel(true)}
          dragState={dragState}
        />
      </div>

      {/* ---- Notes drawer (when no PPT) ---- */}
      {!hasPPT && showNotesDrawer && (
        <div className="fixed inset-0 z-50 flex justify-end">
          <div
            className="absolute inset-0 bg-black/30 backdrop-blur-sm"
            onClick={() => setShowNotesDrawer(false)}
          />
          <div
            className="relative w-full max-w-lg h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-slate-200 dark:border-slate-700 flex-shrink-0">
              <div className="flex items-center gap-2">
                <Edit3 className="w-5 h-5 text-amber-500" />
                <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">随堂思考与重难点</h2>
              </div>
              <button
                onClick={() => setShowNotesDrawer(false)}
                className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="flex-1 overflow-hidden">
              <SideNotesPanel
                noteEditRef={noteEditRef}
                notesHook={notesHook}
                transcript={transcript}
                activeTextElRef={activeTextElRef}
              />
            </div>
          </div>
        </div>
      )}

      <MindMapDrawer
        mindMap={mindMap}
        ppt={ppt}
        displaySession={displaySession}
        displayNotebook={displayNotebook}
        sessionId={sessionId}
        paragraphContainerRef={paragraphContainerRef}
      />

      <QuizDrawer
        quiz={quiz}
        rag={rag}
        vectorIndex={vectorIndex}
        sessionId={sessionId}
        displayNotebook={displayNotebook}
        onRagSourceClick={handleRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />

      <RagSearchModal
        rag={rag}
        vectorIndex={vectorIndex}
        sessionId={sessionId}
        displayNotebook={displayNotebook}
        onRagSourceClick={handleRagSourceClick}
        getRagSourceTypeLabel={getRagSourceTypeLabel}
      />

      <ShareModal share={share} sessionId={sessionId} />

      <DragPreviewOverlay dragState={dragState} sessionId={sessionId} />
    </div>
  );
}
