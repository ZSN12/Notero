import { useParams, useNavigate } from 'react-router-dom';
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  ArrowLeft,
  BrainCircuit,
  ClipboardCheck,
  Download,
  Search,
  Share2,
  ChevronLeft,
  ChevronRight,
  Pen,
  Eraser,
  Undo,
  Redo,
  Trash2,
  Circle,
  Minus,
  Plus,
  Play,
  Pause,
  FileText,
  Menu,
  X,
} from 'lucide-react';

import { useStore } from '@/store/useStore';
import { getProfile, getAvatarUrl } from '@/services/auth';
import type { UserProfile } from '@/services/auth';
import { fetchNotebookDetail, fetchSessionById, getMediaUrl } from '@/services/api';
import { layoutFromNoteParts } from '@/lib/noteLayout';
import type { Notebook, Session } from '@/types';
import type { ContentBlock, RAGSource } from '@/services/api/types';

import { useRecording } from '@/pages/note-detail/useRecording';
import { useTranscript } from '@/pages/note-detail/useTranscript';
import { usePPT } from '@/pages/note-detail/usePPT';
import { useNotes } from '@/pages/note-detail/useNotes';
import { useExport } from '@/pages/note-detail/useExport';
import { useShare } from '@/pages/note-detail/hooks/useShare';
import { useVectorIndex } from '@/pages/note-detail/hooks/useVectorIndex';
import { useRAG } from '@/pages/note-detail/hooks/useRAG';
import { useMindMap } from '@/pages/note-detail/hooks/useMindMap';
import { useQuiz } from '@/pages/note-detail/hooks/useQuiz';
import { useProcessingStatus } from '@/pages/note-detail/hooks/useProcessingStatus';

import { NoteDetailTopNav } from '@/pages/note-detail/components/NoteDetailTopNav';
import { MindMapDrawer } from '@/pages/note-detail/components/MindMapDrawer';
import { QuizDrawer } from '@/pages/note-detail/components/QuizDrawer';
import { RagSearchModal } from '@/pages/note-detail/components/RagSearchModal';
import { ShareModal } from '@/pages/note-detail/components/ShareModal';

import { SlideAnnotationLayer, type AnnotationTool } from '@/pages/pad/components/SlideAnnotationLayer';
import { usePadAnnotations } from '@/pages/pad/hooks/usePadAnnotations';

const PRESET_COLORS = [
  { value: '#ef4444', label: '红' },
  { value: '#eab308', label: '黄' },
  { value: '#3b82f6', label: '蓝' },
  { value: '#22c55e', label: '绿' },
  { value: '#1e293b', label: '黑' },
];

const MIN_STROKE_WIDTH = 2;
const MAX_STROKE_WIDTH = 16;

function getRagSourceTypeLabel(source: RAGSource) {
  const rawType =
    source.source_type === 'layout'
      ? String(source.metadata?.block_type || source.source_type)
      : source.source_type;
  if (rawType === 'ppt') return 'PPT';
  if (rawType === 'transcript') return '转写';
  if (rawType === 'note') return '笔记';
  return '资料';
}

export default function PadPage() {
  const { id, sessionId } = useParams<{ id: string; sessionId: string }>();
  const navigate = useNavigate();
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

  const ppt = usePPT(sessionId);
  const processing = useProcessingStatus(sessionId);
  const recording = useRecording(sessionId, { onFinalize: processing.refresh });
  const transcript = useTranscript(sessionId, recording.state.isRecording, ppt.state.slides);
  const notesHook = useNotes();
  const exportTools = useExport(displaySession, displayNotebook);
  const share = useShare();
  const vectorIndex = useVectorIndex(sessionId, processing.processingStatus);
  const rag = useRAG();
  const mindMap = useMindMap(sessionId, processing.processingStatus);
  const quiz = useQuiz(sessionId, processing.processingStatus);

  const paragraphContainerRef = useRef<HTMLDivElement>(null);

  const activePage = ppt.state.activeSlideIndex + 1;
  const padAnnotations = usePadAnnotations({
    sessionId,
    note: transcript.state.loadedNote,
    initialPage: activePage,
  });

  // Keep annotation page in sync with PPT active slide.
  useEffect(() => {
    padAnnotations.actions.setPage(activePage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activePage]);

  const [tool, setTool] = useState<AnnotationTool>('pen');
  const [color, setColor] = useState(PRESET_COLORS[2].value);
  const [strokeWidth, setStrokeWidth] = useState(4);
  const [showTranscript, setShowTranscript] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);

  const handleBack = async () => {
    if (sessionId && transcript.state.hasLocalChanges) {
      await transcript.actions.saveContent(notesHook.refs.notesDraftRef.current, false);
    }
    navigate(`/subject/${id}`);
  };

  const handlePPTClick = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.ppt,.pptx,.pdf';
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;
      await ppt.actions.handlePPTUpload(file);
    };
    input.click();
  };

  const handleRagSourceClick = useMemo(
    () => (source: RAGSource, closePanel?: () => void) => {
      closePanel?.();
      if (source.session_id && source.session_id !== sessionId) {
        navigate(`/subject/${source.notebook_id}/session/${source.session_id}`, { state: { ragSource: source } });
        return;
      }
      const pageNumber = source.page == null ? null : Number(source.page);
      if (getRagSourceTypeLabel(source) === 'PPT' && Number.isFinite(pageNumber) && pageNumber! > 0) {
        ppt.actions.setActiveSlideIndex(pageNumber! - 1);
        return;
      }
      toast.info('已找到来源，但当前页面没有可定位的 PPT 页面');
    },
    [navigate, ppt.actions, sessionId]
  );

  const goPrev = () => {
    if (ppt.state.activeSlideIndex > 0) {
      ppt.actions.setActiveSlideIndex(ppt.state.activeSlideIndex - 1);
    }
  };

  const goNext = () => {
    if (ppt.state.activeSlideIndex < ppt.state.slides.length - 1) {
      ppt.actions.setActiveSlideIndex(ppt.state.activeSlideIndex + 1);
    }
  };

  const currentSlide = ppt.state.slides[ppt.state.activeSlideIndex];

  return (
    <div className="h-screen flex flex-col bg-slate-50 dark:bg-slate-950 overflow-hidden">
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

      {/* Toolbar */}
      <div className="flex-shrink-0 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md border-b border-slate-200/60 dark:border-slate-800/60">
        <div className="px-3 py-2 flex items-center justify-between gap-2">
          <div className="flex items-center gap-1 sm:gap-2">
            <button
              onClick={() => setTool('pen')}
              className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                tool === 'pen' ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
              title="画笔"
            >
              <Pen className="w-5 h-5" />
            </button>
            <button
              onClick={() => setTool('eraser')}
              className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                tool === 'eraser' ? 'bg-amber-100 text-amber-600 dark:bg-amber-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
              title="橡皮擦"
            >
              <Eraser className="w-5 h-5" />
            </button>

            <div className="w-px h-8 bg-slate-200 dark:bg-slate-700 mx-1" />

            {PRESET_COLORS.map((c) => (
              <button
                key={c.value}
                onClick={() => { setColor(c.value); setTool('pen'); }}
                className={`min-w-[36px] min-h-[36px] rounded-full border-2 transition-transform ${
                  color === c.value ? 'border-slate-400 scale-110' : 'border-transparent'
                }`}
                style={{ backgroundColor: c.value }}
                title={c.label}
              />
            ))}

            <div className="w-px h-8 bg-slate-200 dark:bg-slate-700 mx-1" />

            <button
              onClick={() => setStrokeWidth((w) => Math.max(MIN_STROKE_WIDTH, w - 2))}
              className="min-w-[40px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              title="细"
            >
              <Minus className="w-4 h-4" />
            </button>
            <div
              className="rounded-full bg-slate-800 dark:bg-slate-200"
              style={{ width: Math.max(4, strokeWidth), height: Math.max(4, strokeWidth) }}
            />
            <button
              onClick={() => setStrokeWidth((w) => Math.min(MAX_STROKE_WIDTH, w + 2))}
              className="min-w-[40px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
              title="粗"
            >
              <Plus className="w-4 h-4" />
            </button>
          </div>

          <div className="flex items-center gap-1 sm:gap-2">
            <button
              onClick={padAnnotations.actions.undo}
              disabled={!padAnnotations.canUndo}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
              title="撤销"
            >
              <Undo className="w-5 h-5" />
            </button>
            <button
              onClick={padAnnotations.actions.redo}
              disabled={!padAnnotations.canRedo}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
              title="重做"
            >
              <Redo className="w-5 h-5" />
            </button>
            <button
              onClick={padAnnotations.actions.clear}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
              title="清空"
            >
              <Trash2 className="w-5 h-5" />
            </button>
            {padAnnotations.saveError ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-red-600 dark:text-red-400">{padAnnotations.saveError}</span>
                <button
                  onClick={padAnnotations.actions.retrySave}
                  className="px-2 py-1 text-xs font-medium text-white bg-red-500 rounded-md hover:bg-red-600"
                >
                  重试
                </button>
              </div>
            ) : padAnnotations.isSaving ? (
              <span className="text-xs text-slate-400">保存中…</span>
            ) : null}
          </div>
        </div>
      </div>

      {/* Main stage */}
      <div className="flex-1 min-h-0 flex flex-col">
        {ppt.state.slides.length === 0 ? (
          <div className="flex-1 flex flex-col items-center justify-center text-slate-400 gap-3 p-8">
            <FileText className="w-16 h-16 opacity-40" />
            <p className="text-sm">当前课次没有 PPT</p>
            <button
              onClick={handlePPTClick}
              disabled={ppt.state.isUploadingPPT}
              className="px-4 py-2 text-sm text-blue-600 bg-blue-50 dark:bg-blue-900/20 rounded-lg hover:bg-blue-100 dark:hover:bg-blue-900/30 disabled:opacity-50"
            >
              {ppt.state.isUploadingPPT ? '上传中…' : '上传 PPT'}
            </button>
          </div>
        ) : (
          <SlideAnnotationLayer
            sessionId={sessionId}
            slide={currentSlide}
            tool={tool}
            color={color}
            width={strokeWidth}
            strokes={padAnnotations.strokes}
            onAddStroke={padAnnotations.actions.addStroke}
            onErase={padAnnotations.actions.erase}
            className="flex-1 min-h-0"
          />
        )}

        {/* Bottom control bar */}
        {ppt.state.slides.length > 0 && (
          <div className="flex-shrink-0 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md border-t border-slate-200/60 dark:border-slate-800/60 px-3 py-2 flex items-center justify-between">
            <button
              onClick={goPrev}
              disabled={ppt.state.activeSlideIndex === 0}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 disabled:opacity-30"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>

            <div className="flex items-center gap-3">
              <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                {ppt.state.activeSlideIndex + 1} / {ppt.state.slides.length}
              </span>
              <button
                onClick={() => setShowTranscript((v) => !v)}
                className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                  showTranscript ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
                title="转写/录音"
              >
                {showTranscript ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
              </button>
            </div>

            <button
              onClick={goNext}
              disabled={ppt.state.activeSlideIndex === ppt.state.slides.length - 1}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 disabled:opacity-30"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>
        )}
      </div>

      {/* Transcript / audio playback sheet */}
      {showTranscript && (
        <div className="flex-shrink-0 bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-700 max-h-[35vh] flex flex-col">
          <div className="px-4 py-2 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">转写与回放</span>
            <button onClick={() => setShowTranscript(false)} className="text-slate-400 hover:text-slate-600">
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="p-4 space-y-3 overflow-y-auto">
            {recording.state.audioPlaybackUrl ? (
              <audio
                ref={recording.refs.audioPlayerRef}
                src={recording.state.audioPlaybackUrl}
                className="w-full"
                controls
                onPlay={() => setIsPlaying(true)}
                onPause={() => setIsPlaying(false)}
              />
            ) : (
              <div className="text-xs text-slate-400">暂无录音回放</div>
            )}
            <div
              ref={paragraphContainerRef}
              className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap leading-6 max-h-[20vh] overflow-y-auto"
            >
              {transcript.state.transcriptText || '还没有转写内容。'}
            </div>
          </div>
        </div>
      )}

      {/* Overlays */}
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
    </div>
  );
}
