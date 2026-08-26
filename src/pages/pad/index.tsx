import { useParams, useNavigate, useLocation } from 'react-router-dom';
import { useEffect, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import {
  ChevronLeft,
  ChevronRight,
  Pen,
  Eraser,
  Undo,
  Redo,
  Trash2,
  Minus,
  Plus,
  FileText,
  Menu,
  X,
  BookOpen,
  StickyNote,
  UserCircle,
  ImageDown,
  FileDown,
  ImagePlus,
  CopyPlus,
  Search,
  Link2,
  Type,
  Image,
  Bot,
  ListChecks,
  CheckSquare,
} from 'lucide-react';

import { useStore } from '@/store/useStore';
import { getProfile } from '@/services/auth';
import type { UserProfile } from '@/services/auth';
import { fetchNotebookDetail, fetchSessionById } from '@/services/api';
import type { Notebook, Session } from '@/types';
import type { FreeNoteAiBlockType, FreeNoteBackground, FreeNoteInsert, FreeNoteReviewStatus, RAGSource } from '@/services/api/types';

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
import { exportFreeNotePagePng, exportFreeNotesPdf, type FreeNoteExportPage } from '@/pages/pad/lib/freeNoteExport';
import { createSlideSnapshotDataUrl } from '@/pages/pad/lib/slideSnapshot';
import { getFreeNoteSourcePage } from '@/pages/pad/lib/ragSourceNavigation';
import { filterFreeNoteSummaries, getFreeNoteReviewStats, getRelatedFreeNoteSummaries, getReviewQueueSummaries, type FreeNoteQueueFilter } from '@/pages/pad/lib/freeNoteDirectory';
import { buildFreeNoteAiContext } from '@/pages/pad/lib/freeNoteAiContext';

const PRESET_COLORS = [
  { value: '#ef4444', label: '红' },
  { value: '#eab308', label: '黄' },
  { value: '#3b82f6', label: '蓝' },
  { value: '#22c55e', label: '绿' },
  { value: '#1e293b', label: '黑' },
];

const MIN_STROKE_WIDTH = 2;
const MAX_STROKE_WIDTH = 16;
type PadTab = 'slides' | 'notes' | 'me';
const BACKGROUND_OPTIONS: Array<{ value: FreeNoteBackground; label: string }> = [
  { value: 'grid', label: '网格' },
  { value: 'lined', label: '横线' },
  { value: 'blank', label: '空白' },
];
const REVIEW_STATUS_OPTIONS: Array<{ value: FreeNoteReviewStatus; label: string }> = [
  { value: 'normal', label: '普通' },
  { value: 'important', label: '重点' },
  { value: 'todo', label: '待处理' },
  { value: 'reviewed', label: '已复习' },
];
const AI_ACTION_LABELS = {
  summarize: '总结本页',
  quiz: '生成复习题',
  explain: '解释关联课件',
} as const;
type FreeNoteAiAction = keyof typeof AI_ACTION_LABELS;
const AI_ACTION_TO_BLOCK_TYPE: Record<FreeNoteAiAction, FreeNoteAiBlockType> = {
  summarize: 'summary',
  quiz: 'quiz',
  explain: 'explanation',
};

function getReviewStatusLabel(status: FreeNoteReviewStatus) {
  return REVIEW_STATUS_OPTIONS.find((item) => item.value === status)?.label || '普通';
}

function getAiBlockTypeLabel(type: FreeNoteAiBlockType) {
  if (type === 'summary') return 'AI 总结';
  if (type === 'quiz') return '复习题';
  return '课件解释';
}

async function imageFileToDataUrl(file: File): Promise<string> {
  if (!file.type.startsWith('image/')) throw new Error('请选择图片文件');
  const image = await new Promise<HTMLImageElement>((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = document.createElement('img');
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new Error('图片读取失败'));
    };
    img.src = url;
  });
  const maxSide = 1600;
  const ratio = Math.min(1, maxSide / Math.max(image.naturalWidth, image.naturalHeight));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(image.naturalWidth * ratio));
  canvas.height = Math.max(1, Math.round(image.naturalHeight * ratio));
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('图片处理失败');
  ctx.drawImage(image, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL(file.type === 'image/png' ? 'image/png' : 'image/jpeg', 0.86);
}

function getRagSourceTypeLabel(source: RAGSource) {
  const rawType =
    source.source_type === 'layout'
      ? String(source.metadata?.block_type || source.source_type)
      : source.source_type;
  if (rawType === 'ppt') return 'PPT';
  if (rawType === 'transcript') return '转写';
  if (rawType === 'note') return '笔记';
  if (rawType === 'free_note') return '自由笔记';
  if (rawType === 'web') return '网页';
  return '资料';
}

export default function PadPage() {
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
    scope: 'slides',
  });
  const freeNoteAnnotations = usePadAnnotations({
    sessionId,
    note: transcript.state.loadedNote,
    initialPage: 1,
    scope: 'free_notes',
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
  const [activeTab, setActiveTab] = useState<PadTab>('slides');
  const [showFreePages, setShowFreePages] = useState(false);
  const [defaultFreeBackground, setDefaultFreeBackground] = useState<FreeNoteBackground>('grid');
  const [selectedInsertId, setSelectedInsertId] = useState<string | null>(null);
  const [selectedTextBlockId, setSelectedTextBlockId] = useState<string | null>(null);
  const [freeNoteSearch, setFreeNoteSearch] = useState('');
  const [freeNoteStatusFilter, setFreeNoteStatusFilter] = useState<FreeNoteReviewStatus | 'all'>('all');
  const [noteMode, setNoteMode] = useState<'page' | 'queue'>('page');
  const [queueFilter, setQueueFilter] = useState<FreeNoteQueueFilter>('all');
  const [batchMode, setBatchMode] = useState(false);
  const [selectedBatchPages, setSelectedBatchPages] = useState<number[]>([]);
  const [showRelatedNotes, setShowRelatedNotes] = useState(false);
  const [textFontSize, setTextFontSize] = useState(18);
  const [textColor, setTextColor] = useState('#1e293b');
  const [aiPanel, setAiPanel] = useState<{ action: FreeNoteAiAction; context: Record<string, unknown> } | null>(null);
  const [aiDraftContent, setAiDraftContent] = useState('');

  useEffect(() => {
    setSelectedInsertId(null);
    setSelectedTextBlockId(null);
  }, [tool, activeTab, freeNoteAnnotations.page]);

  useEffect(() => {
    const params = new URLSearchParams(location.search);
    const tab = params.get('tab');
    if (tab === 'notes' || tab === 'slides' || tab === 'me') {
      setActiveTab(tab);
    }
    const pageParam = params.get('page');
    const pageNumber = pageParam == null ? null : Number(pageParam);
    if (tab === 'notes' && Number.isFinite(pageNumber) && pageNumber! > 0) {
      freeNoteAnnotations.actions.setPage(pageNumber!);
      setShowFreePages(true);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.search]);

  const activeAnnotations = activeTab === 'notes' ? freeNoteAnnotations : padAnnotations;
  const freeNoteTotalPages = freeNoteAnnotations.pageSummaries.length;
  const exportTitle = (displaySession?.title || '课堂笔记').replace(/[\\/:*?"<>|]/g, '-').trim() || '课堂笔记';
  const filteredFreeNoteSummaries = useMemo(() => {
    const byQuery = filterFreeNoteSummaries(freeNoteAnnotations.pageSummaries, freeNoteSearch);
    if (freeNoteStatusFilter === 'all') return byQuery;
    return byQuery.filter((item) => item.reviewStatus === freeNoteStatusFilter);
  }, [freeNoteAnnotations.pageSummaries, freeNoteSearch, freeNoteStatusFilter]);
  const relatedFreeNotePages = useMemo(
    () => getRelatedFreeNoteSummaries(freeNoteAnnotations.pageSummaries, ppt.state.activeSlideIndex),
    [freeNoteAnnotations.pageSummaries, ppt.state.activeSlideIndex],
  );
  const reviewQueuePages = useMemo(() => {
    return getReviewQueueSummaries(freeNoteAnnotations.pageSummaries, queueFilter);
  }, [freeNoteAnnotations.pageSummaries, queueFilter]);
  const reviewStats = useMemo(() => {
    return getFreeNoteReviewStats(freeNoteAnnotations.pageSummaries);
  }, [freeNoteAnnotations.pageSummaries]);
  const pendingReviewCount = reviewStats.important + reviewStats.todo;

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
      if (source.source_type === 'web') {
        const url = typeof source.metadata?.url === 'string' ? source.metadata.url : source.block_id;
        if (url) window.open(url, '_blank', 'noopener,noreferrer');
        return;
      }
      if (source.session_id && source.session_id !== sessionId) {
        const targetTab = source.source_type === 'free_note' ? '/pad?tab=notes' : '';
        navigate(`/subject/${source.notebook_id}/session/${source.session_id}${targetTab}`, { state: { ragSource: source } });
        return;
      }
      const freeNotePage = getFreeNoteSourcePage(source);
      if (freeNotePage) {
        setActiveTab('notes');
        freeNoteAnnotations.actions.setPage(freeNotePage);
        setShowFreePages(true);
        return;
      }
      const pageNumber = source.page == null ? null : Number(source.page);
      if (getRagSourceTypeLabel(source) === 'PPT' && Number.isFinite(pageNumber) && pageNumber! > 0) {
        ppt.actions.setActiveSlideIndex(pageNumber! - 1);
        return;
      }
      toast.info('已找到来源，但当前页面没有可定位的 PPT 页面');
    },
    [freeNoteAnnotations.actions, navigate, ppt.actions, sessionId]
  );

  useEffect(() => {
    const source = (location.state as { ragSource?: RAGSource } | null)?.ragSource;
    if (!source || source.session_id !== sessionId) return;
    const timer = window.setTimeout(() => {
      handleRagSourceClick(source);
      navigate(location.pathname + location.search, { replace: true, state: null });
    }, 500);
    return () => window.clearTimeout(timer);
  }, [handleRagSourceClick, location.pathname, location.search, location.state, navigate, sessionId]);

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
  const goFreePrev = () => {
    const pages = freeNoteAnnotations.pageSummaries.map((item) => item.page);
    const currentIndex = pages.indexOf(freeNoteAnnotations.page);
    const nextPage = pages[Math.max(0, currentIndex - 1)] ?? 1;
    freeNoteAnnotations.actions.setPage(nextPage);
  };
  const goFreeNext = () => {
    const pages = freeNoteAnnotations.pageSummaries.map((item) => item.page);
    const currentIndex = pages.indexOf(freeNoteAnnotations.page);
    const nextPage = pages[Math.min(pages.length - 1, currentIndex + 1)] ?? freeNoteAnnotations.page;
    freeNoteAnnotations.actions.setPage(nextPage);
  };
  const handleAddFreePage = () => {
    freeNoteAnnotations.actions.addPage(defaultFreeBackground);
    setShowFreePages(true);
  };
  const handleDeleteFreePage = (pageToDelete: number) => {
    const target = freeNoteAnnotations.pageSummaries.find((item) => item.page === pageToDelete);
    if (target && !target.isBlank && !window.confirm(`删除第 ${pageToDelete} 页自由笔记？`)) return;
    freeNoteAnnotations.actions.deletePage(pageToDelete, defaultFreeBackground);
  };
  const handleDeleteSelectedInsert = () => {
    if (!selectedInsertId) return;
    if (!window.confirm('删除选中的课件截图？')) return;
    freeNoteAnnotations.actions.deleteInsert(selectedInsertId);
    setSelectedInsertId(null);
  };
  const handleDeleteSelectedTextBlock = () => {
    if (!selectedTextBlockId) return;
    if (!window.confirm('删除选中的文本框？')) return;
    freeNoteAnnotations.actions.deleteTextBlock(selectedTextBlockId);
    setSelectedTextBlockId(null);
  };
  const jumpToFreeNotePage = (pageNumber: number) => {
    freeNoteAnnotations.actions.setPage(pageNumber);
    setActiveTab('notes');
    setNoteMode('page');
    setShowFreePages(true);
    setShowRelatedNotes(false);
  };
  const handleSelectAllFilteredPages = () => {
    setSelectedBatchPages(filteredFreeNoteSummaries.map((item) => item.page));
  };
  const toggleBatchPage = (pageNumber: number) => {
    setSelectedBatchPages((pages) =>
      pages.includes(pageNumber) ? pages.filter((pageItem) => pageItem !== pageNumber) : [...pages, pageNumber],
    );
  };
  const handleBatchStatusChange = (reviewStatus: FreeNoteReviewStatus) => {
    if (selectedBatchPages.length === 0) return;
    if (!window.confirm(`将 ${selectedBatchPages.length} 页批量设为「${getReviewStatusLabel(reviewStatus)}」？`)) return;
    freeNoteAnnotations.actions.setPagesReviewStatus(selectedBatchPages, reviewStatus);
    setSelectedBatchPages([]);
    setBatchMode(false);
  };
  const makeSlideSnapshotInsert = async (): Promise<FreeNoteInsert> => {
    if (!currentSlide) throw new Error('当前课次没有可插入的 PPT 页面');
    const dataUrl = await createSlideSnapshotDataUrl(currentSlide, sessionId, padAnnotations.strokes);
    return {
      id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
      type: 'slide_snapshot',
      slideIndex: ppt.state.activeSlideIndex,
      dataUrl,
      createdAt: new Date().toISOString(),
      x: 0,
      y: 0,
      width: 1,
      height: 1,
    };
  };
  const handleImageInsert = () => {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = 'image/png,image/jpeg,image/webp,image/gif';
    input.onchange = async (event) => {
      try {
        const file = (event.target as HTMLInputElement).files?.[0];
        if (!file) return;
        const dataUrl = await imageFileToDataUrl(file);
        freeNoteAnnotations.actions.addInsert({
          id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
          type: 'image',
          dataUrl,
          createdAt: new Date().toISOString(),
          fileName: file.name,
          x: 0.12,
          y: 0.12,
          width: 0.48,
          height: 0.36,
        });
        setActiveTab('notes');
        toast.success('已插入图片');
      } catch (err) {
        toast.error(err instanceof Error ? err.message : '插入图片失败');
      }
    };
    input.click();
  };
  const getCurrentFreeNoteAiContext = () => {
    return buildFreeNoteAiContext({
      title: freeNoteAnnotations.pageTitle,
      page: freeNoteAnnotations.page,
      reviewStatus: freeNoteAnnotations.pageReviewStatus,
      inserts: freeNoteAnnotations.pageInserts,
      textBlocks: freeNoteAnnotations.pageTextBlocks,
      strokes: freeNoteAnnotations.strokes,
    });
  };
  const handleFreeNoteAiAction = (action: FreeNoteAiAction) => {
    try {
      // TODO: 接入后端自由笔记 AI 接口时，将整理后的 context 作为请求体传递并展示真实结果。
      setAiPanel({ action, context: getCurrentFreeNoteAiContext() });
      setAiDraftContent('');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '整理自由笔记上下文失败');
    }
  };
  const handleSaveAiDraft = () => {
    if (!aiPanel) return;
    if (!aiDraftContent.trim()) {
      toast.error('请先填写要保存到本页的 AI 草稿内容');
      return;
    }
    freeNoteAnnotations.actions.addAiBlock({
      type: AI_ACTION_TO_BLOCK_TYPE[aiPanel.action],
      title: AI_ACTION_LABELS[aiPanel.action],
      content: aiDraftContent.trim(),
      sourceContext: aiPanel.context,
    });
    setAiPanel(null);
    setAiDraftContent('');
    toast.success('已保存到本页自由笔记');
  };
  const handleDeleteAiBlock = (blockId: string) => {
    if (!window.confirm('删除这条 AI 内容？')) return;
    freeNoteAnnotations.actions.deleteAiBlock(blockId);
  };
  const handleInsertSlideToCurrentFreePage = async () => {
    try {
      const insert = await makeSlideSnapshotInsert();
      freeNoteAnnotations.actions.addInsert(insert);
      setActiveTab('notes');
      setShowFreePages(true);
      toast.success('已插入到当前自由笔记页');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '插入课件页失败');
    }
  };
  const handleInsertSlideToNewFreePage = async () => {
    try {
      const insert = await makeSlideSnapshotInsert();
      freeNoteAnnotations.actions.addPageWithInsert(insert, defaultFreeBackground);
      setActiveTab('notes');
      setShowFreePages(true);
      toast.success('已新建笔记页并插入课件页');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '插入课件页失败');
    }
  };
  const currentFreeExportPage = (): FreeNoteExportPage => ({
    page: freeNoteAnnotations.page,
    background: freeNoteAnnotations.pageBackground,
    title: freeNoteAnnotations.pageTitle,
    inserts: freeNoteAnnotations.pageInserts,
    textBlocks: freeNoteAnnotations.pageTextBlocks,
    aiBlocks: freeNoteAnnotations.pageAiBlocks,
    reviewStatus: freeNoteAnnotations.pageReviewStatus,
    strokes: freeNoteAnnotations.strokes,
  });
  const allFreeExportPages = (): FreeNoteExportPage[] =>
    freeNoteAnnotations.pageSummaries.map((item) => ({
      page: item.page,
      background: item.background,
      title: item.title,
      inserts: item.inserts,
      textBlocks: item.textBlocks,
      aiBlocks: item.aiBlocks,
      reviewStatus: item.reviewStatus,
      strokes: item.strokes,
    }));
  const handleExportCurrentFreePage = async () => {
    try {
      await exportFreeNotePagePng(
        currentFreeExportPage(),
        `${exportTitle}-free-note-page-${freeNoteAnnotations.page}.png`,
      );
      toast.success('已导出当前自由笔记页');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导出 PNG 失败');
    }
  };
  const handleExportAllFreePages = async () => {
    try {
      await exportFreeNotesPdf(allFreeExportPages(), `${exportTitle}-free-notes.pdf`, `${exportTitle} 自由笔记`);
      toast.success('已导出自由笔记 PDF');
    } catch (err) {
      toast.error(err instanceof Error ? err.message : '导出 PDF 失败');
    }
  };
  const tabItems: Array<{ id: PadTab; label: string; icon: typeof FileText }> = [
    { id: 'slides', label: '课件批注', icon: BookOpen },
    { id: 'notes', label: '笔记本', icon: StickyNote },
    { id: 'me', label: '我的', icon: UserCircle },
  ];

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
      {activeTab !== 'me' && (
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
            {activeTab === 'notes' && (
              <button
                onClick={() => setTool('text')}
                className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                  tool === 'text' ? 'bg-blue-100 text-blue-600 dark:bg-blue-900/30' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                }`}
                title="文本"
              >
                <Type className="w-5 h-5" />
              </button>
            )}

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
            {activeTab === 'notes' && (
              <>
                <div className="w-px h-8 bg-slate-200 dark:bg-slate-700 mx-1" />
                <select
                  value={freeNoteAnnotations.pageReviewStatus}
                  onChange={(event) => freeNoteAnnotations.actions.setReviewStatus(event.target.value as FreeNoteReviewStatus)}
                  className="h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 text-xs text-slate-600 dark:text-slate-200"
                  title="复习状态"
                >
                  {REVIEW_STATUS_OPTIONS.map((item) => (
                    <option key={item.value} value={item.value}>{item.label}</option>
                  ))}
                </select>
                <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                  {BACKGROUND_OPTIONS.map((item) => (
                    <button
                      key={item.value}
                      onClick={() => freeNoteAnnotations.actions.setBackground(item.value)}
                      className={`px-2.5 py-2 text-[11px] font-medium transition-colors ${
                        freeNoteAnnotations.pageBackground === item.value
                          ? 'bg-blue-500 text-white'
                          : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                      }`}
                    >
                      {item.label}
                    </button>
                  ))}
                </div>
                {tool === 'text' && (
                  <>
                    <input
                      type="number"
                      min={12}
                      max={36}
                      value={textFontSize}
                      onChange={(event) => setTextFontSize(Number(event.target.value))}
                      className="w-14 h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 text-xs text-slate-600 dark:text-slate-200"
                      title="字号"
                    />
                    <input
                      type="color"
                      value={textColor}
                      onChange={(event) => setTextColor(event.target.value)}
                      className="w-9 h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-transparent p-1"
                      title="文字颜色"
                    />
                  </>
                )}
              </>
            )}
          </div>

          <div className="flex items-center gap-1 sm:gap-2">
            {activeTab === 'slides' && (
              <>
                {relatedFreeNotePages.length > 0 && (
                  <div className="relative">
                    <button
                      onClick={() => setShowRelatedNotes((value) => !value)}
                      className="min-h-[44px] px-2.5 flex items-center gap-1.5 rounded-lg text-blue-600 bg-blue-50 hover:bg-blue-100 dark:bg-blue-900/20 dark:hover:bg-blue-900/30"
                      title="查看关联自由笔记"
                    >
                      <Link2 className="w-4 h-4" />
                      <span className="text-xs font-medium">相关笔记 {relatedFreeNotePages.length}</span>
                    </button>
                    {showRelatedNotes && (
                      <div className="absolute right-0 top-full mt-2 w-52 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg p-2 z-30">
                        {relatedFreeNotePages.map((item) => (
                          <button
                            key={item.page}
                            onClick={() => jumpToFreeNotePage(item.page)}
                            className="w-full rounded-lg px-2 py-2 text-left hover:bg-slate-50 dark:hover:bg-slate-800"
                          >
                            <span className="block text-xs font-medium text-slate-700 dark:text-slate-200 truncate">{item.title}</span>
                            <span className="text-[10px] text-slate-400">第 {item.page} 页</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                )}
                <button
                  onClick={handleInsertSlideToCurrentFreePage}
                  disabled={!currentSlide}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                  title="插入到笔记本当前页"
                >
                  <ImagePlus className="w-5 h-5" />
                </button>
                <button
                  onClick={handleInsertSlideToNewFreePage}
                  disabled={!currentSlide}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
                  title="新建笔记页并插入"
                >
                  <CopyPlus className="w-5 h-5" />
                </button>
              </>
            )}
            {activeTab === 'notes' && (
              <>
                <button
                  onClick={() => setNoteMode((mode) => mode === 'queue' ? 'page' : 'queue')}
                  className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                    noteMode === 'queue' ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                  title="复习队列"
                >
                  <ListChecks className="w-5 h-5" />
                </button>
                <button
                  onClick={() => {
                    setBatchMode((value) => !value);
                    setSelectedBatchPages([]);
                    setShowFreePages(true);
                  }}
                  className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                    batchMode ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                  title="批量选择"
                >
                  <CheckSquare className="w-5 h-5" />
                </button>
                {selectedInsertId && (
                  <button
                    onClick={handleDeleteSelectedInsert}
                    className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                    title="删除选中截图"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                )}
                {selectedTextBlockId && (
                  <button
                    onClick={handleDeleteSelectedTextBlock}
                    className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                    title="删除选中文本"
                  >
                    <Trash2 className="w-5 h-5" />
                  </button>
                )}
                <button
                  onClick={handleImageInsert}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="插入图片"
                >
                  <Image className="w-5 h-5" />
                </button>
                <div className="relative group">
                  <button
                    className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                    title="AI 复习"
                  >
                    <Bot className="w-5 h-5" />
                  </button>
                  <div className="hidden group-hover:block absolute right-0 top-full z-30 w-36 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 p-1 shadow-lg">
                    {(Object.keys(AI_ACTION_LABELS) as FreeNoteAiAction[]).map((action) => (
                      <button
                        key={action}
                        onClick={() => handleFreeNoteAiAction(action)}
                        className="w-full rounded-lg px-2 py-2 text-left text-xs text-slate-600 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800"
                      >
                        {AI_ACTION_LABELS[action]}
                      </button>
                    ))}
                  </div>
                </div>
                <button
                  onClick={() => setShowFreePages((value) => !value)}
                  className={`min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg transition-colors ${
                    showFreePages ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20' : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                  }`}
                  title="页面缩略图"
                >
                  <FileText className="w-5 h-5" />
                </button>
                <button
                  onClick={handleExportCurrentFreePage}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="导出当前页 PNG"
                >
                  <ImageDown className="w-5 h-5" />
                </button>
                <button
                  onClick={handleExportAllFreePages}
                  className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800"
                  title="导出全部 PDF"
                >
                  <FileDown className="w-5 h-5" />
                </button>
              </>
            )}
            <button
              onClick={activeAnnotations.actions.undo}
              disabled={!activeAnnotations.canUndo}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
              title="撤销"
            >
              <Undo className="w-5 h-5" />
            </button>
            <button
              onClick={activeAnnotations.actions.redo}
              disabled={!activeAnnotations.canRedo}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-30"
              title="重做"
            >
              <Redo className="w-5 h-5" />
            </button>
            <button
              onClick={activeAnnotations.actions.clear}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
              title="清空"
            >
              <Trash2 className="w-5 h-5" />
            </button>
            {activeAnnotations.saveError ? (
              <div className="flex items-center gap-2">
                <span className="text-xs text-red-600 dark:text-red-400">{activeAnnotations.saveError}</span>
                <button
                  onClick={activeAnnotations.actions.retrySave}
                  className="px-2 py-1 text-xs font-medium text-white bg-red-500 rounded-md hover:bg-red-600"
                >
                  重试
                </button>
              </div>
            ) : activeAnnotations.isSaving ? (
              <span className="text-xs text-slate-400">保存中…</span>
            ) : null}
          </div>
        </div>
      </div>
      )}

      {/* Main stage */}
      <div className="flex-1 min-h-0 flex flex-col">
        {activeTab === 'me' ? (
          <div className="flex-1 overflow-y-auto p-6 bg-slate-50 dark:bg-slate-950">
            <div className="mx-auto max-w-xl space-y-4">
              <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
                <div className="flex items-center gap-3">
                  <div className="w-12 h-12 rounded-full bg-blue-50 dark:bg-blue-900/30 flex items-center justify-center">
                    <UserCircle className="w-7 h-7 text-blue-500" />
                  </div>
                  <div>
                    <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">
                      {profile?.username || profile?.email || 'Notero 用户'}
                    </p>
                    <p className="text-xs text-slate-400">{displayNotebook?.title || '当前课程'}</p>
                  </div>
                </div>
              </div>
              <div className="rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-3">
                <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">Pad 设置</h2>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">默认笔色</span>
                  <span className="w-5 h-5 rounded-full border border-slate-200" style={{ backgroundColor: color }} />
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">笔迹粗细</span>
                  <span className="text-slate-700 dark:text-slate-200">{strokeWidth}px</span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">自由笔记页</span>
                  <span className="text-slate-700 dark:text-slate-200">{freeNoteTotalPages} 页</span>
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3">
                    <span className="block text-[11px] text-slate-400">待复习</span>
                    <span className="text-lg font-semibold text-blue-600">{pendingReviewCount}</span>
                  </div>
                  <div className="rounded-lg bg-slate-50 dark:bg-slate-800/60 p-3">
                    <span className="block text-[11px] text-slate-400">含 AI 内容</span>
                    <span className="text-lg font-semibold text-blue-600">{reviewStats.aiPages}</span>
                  </div>
                </div>
                <div className="grid grid-cols-4 gap-1 text-center text-[11px] text-slate-500 dark:text-slate-400">
                  {REVIEW_STATUS_OPTIONS.map((item) => (
                    <div key={item.value} className="rounded-lg bg-slate-50 dark:bg-slate-800/60 py-2">
                      <span className="block">{item.label}</span>
                      <span className="font-semibold text-slate-700 dark:text-slate-200">{reviewStats[item.value]}</span>
                    </div>
                  ))}
                </div>
                <button
                  onClick={() => {
                    setActiveTab('notes');
                    setNoteMode('queue');
                  }}
                  className="w-full rounded-lg bg-blue-50 dark:bg-blue-900/20 px-3 py-2 text-sm font-medium text-blue-600 dark:text-blue-300 hover:bg-blue-100 dark:hover:bg-blue-900/30"
                >
                  查看复习队列
                </button>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">新建页模板</span>
                  <div className="flex rounded-lg border border-slate-200 dark:border-slate-700 overflow-hidden">
                    {BACKGROUND_OPTIONS.map((item) => (
                      <button
                        key={item.value}
                        onClick={() => {
                          setDefaultFreeBackground(item.value);
                          freeNoteAnnotations.actions.setDefaultBackground(item.value);
                        }}
                        className={`px-2 py-1 text-[11px] ${
                          defaultFreeBackground === item.value
                            ? 'bg-blue-500 text-white'
                            : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
                        }`}
                      >
                        {item.label}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">当前页模板</span>
                  <span className="text-slate-700 dark:text-slate-200">
                    {BACKGROUND_OPTIONS.find((item) => item.value === freeNoteAnnotations.pageBackground)?.label || '网格'}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm">
                  <span className="text-slate-500 dark:text-slate-400">最近保存</span>
                  <span className="text-slate-700 dark:text-slate-200">
                    {freeNoteAnnotations.lastSavedAt
                      ? new Date(freeNoteAnnotations.lastSavedAt).toLocaleTimeString()
                      : '本次会话暂无'}
                  </span>
                </div>
              </div>
            </div>
          </div>
        ) : activeTab === 'notes' && noteMode === 'queue' ? (
          <div className="flex-1 min-h-0 overflow-y-auto bg-slate-50 dark:bg-slate-950 p-4">
            <div className="mx-auto max-w-3xl space-y-3">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold text-slate-800 dark:text-slate-100">复习队列</h2>
                  <p className="text-xs text-slate-400">默认收纳重点和待处理自由笔记页</p>
                </div>
                <select
                  value={queueFilter}
                  onChange={(event) => setQueueFilter(event.target.value as FreeNoteQueueFilter)}
                  className="h-9 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 px-2 text-xs text-slate-600 dark:text-slate-200"
                >
                  <option value="all">全部待复习</option>
                  <option value="important">重点</option>
                  <option value="todo">待处理</option>
                </select>
              </div>
              {reviewQueuePages.length === 0 ? (
                <div className="rounded-xl border border-dashed border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-8 text-center text-sm text-slate-400">
                  当前没有需要复习的自由笔记页
                </div>
              ) : (
                <div className="space-y-2">
                  {reviewQueuePages.map((item) => {
                    const linkedSlides = item.metadata?.slide_indexes ?? [];
                    return (
                      <button
                        key={item.page}
                        onClick={() => jumpToFreeNotePage(item.page)}
                        className="w-full rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 text-left hover:border-blue-200 dark:hover:border-blue-800 transition-colors"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-sm font-semibold text-slate-800 dark:text-slate-100 truncate">{item.title}</span>
                          <span className="rounded-full bg-blue-50 dark:bg-blue-900/30 px-2 py-0.5 text-[11px] text-blue-600 dark:text-blue-300">
                            {getReviewStatusLabel(item.reviewStatus)}
                          </span>
                        </div>
                        <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-slate-500 dark:text-slate-400">
                          <span>自由笔记第 {item.page} 页</span>
                          {linkedSlides.length > 0 && <span>关联 PPT：{linkedSlides.map((index) => index + 1).join(', ')}</span>}
                          {item.strokes.length > 0 && <span>有手写</span>}
                          {item.textBlocks.length > 0 && <span>文本 {item.textBlocks.length}</span>}
                          {item.inserts.length > 0 && <span>图片 {item.inserts.length}</span>}
                          {item.aiBlocks.length > 0 && <span>AI 内容 {item.aiBlocks.length}</span>}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          </div>
        ) : activeTab === 'notes' ? (
          <div className="flex-1 min-h-0 flex overflow-hidden">
            <div className="flex-1 min-h-0 flex flex-col">
              <SlideAnnotationLayer
                sessionId={sessionId}
                allowDrawingWithoutSlide
                background={freeNoteAnnotations.pageBackground}
                tool={tool}
                color={color}
                width={strokeWidth}
                strokes={freeNoteAnnotations.strokes}
                inserts={freeNoteAnnotations.pageInserts}
                textBlocks={freeNoteAnnotations.pageTextBlocks}
                selectedInsertId={selectedInsertId}
                selectedTextBlockId={selectedTextBlockId}
                onSelectInsert={(insertId) => {
                  setSelectedInsertId(insertId);
                  if (insertId) setSelectedTextBlockId(null);
                }}
                onUpdateInsert={freeNoteAnnotations.actions.updateInsert}
                onSelectTextBlock={(blockId) => {
                  setSelectedTextBlockId(blockId);
                  if (blockId) setSelectedInsertId(null);
                }}
                onAddTextBlock={(point) => freeNoteAnnotations.actions.addTextBlock(point, textColor, textFontSize)}
                onUpdateTextBlock={freeNoteAnnotations.actions.updateTextBlock}
                onAddStroke={freeNoteAnnotations.actions.addStroke}
                onErase={freeNoteAnnotations.actions.erase}
                className="flex-1 min-h-0"
              />
              {freeNoteAnnotations.pageAiBlocks.length > 0 && (
                <div className="flex-shrink-0 max-h-36 overflow-y-auto border-t border-slate-200 dark:border-slate-800 bg-white/90 dark:bg-slate-900/90 px-3 py-2 space-y-2">
                  {freeNoteAnnotations.pageAiBlocks.map((block) => (
                    <div key={block.id} className="rounded-lg border border-slate-200 dark:border-slate-700 px-3 py-2">
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs font-semibold text-slate-700 dark:text-slate-200">{getAiBlockTypeLabel(block.type)} · {block.title}</span>
                        <button
                          onClick={() => handleDeleteAiBlock(block.id)}
                          className="text-slate-400 hover:text-red-500"
                          title="删除 AI 内容"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                      <p className="mt-1 text-xs text-slate-500 dark:text-slate-400 whitespace-pre-wrap line-clamp-3">{block.content}</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
            {showFreePages && (
              <aside className="w-40 sm:w-52 flex-shrink-0 border-l border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 overflow-y-auto">
                <div className="sticky top-0 z-10 bg-white dark:bg-slate-900 px-3 py-2 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
                  <div className="w-full space-y-2">
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-semibold text-slate-600 dark:text-slate-300">页面</span>
                      <button
                        onClick={handleAddFreePage}
                        className="min-w-[32px] min-h-[32px] flex items-center justify-center rounded-lg text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20"
                        title="新增页面"
                      >
                        <Plus className="w-4 h-4" />
                      </button>
                    </div>
                    <div className="relative">
                      <Search className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-400" />
                      <input
                        value={freeNoteSearch}
                        onChange={(event) => setFreeNoteSearch(event.target.value)}
                        className="w-full h-8 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 pl-7 pr-2 text-xs text-slate-700 dark:text-slate-200 outline-none focus:border-blue-300"
                        placeholder="搜索标题 / PPT"
                      />
                    </div>
                    <select
                      value={freeNoteStatusFilter}
                      onChange={(event) => setFreeNoteStatusFilter(event.target.value as FreeNoteReviewStatus | 'all')}
                      className="w-full h-8 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-2 text-xs text-slate-600 dark:text-slate-200"
                    >
                      <option value="all">全部状态</option>
                      {REVIEW_STATUS_OPTIONS.map((item) => (
                        <option key={item.value} value={item.value}>{item.label}</option>
                      ))}
                    </select>
                    {batchMode && (
                      <div className="space-y-1 rounded-lg bg-slate-50 dark:bg-slate-800/60 p-2">
                        <div className="flex items-center justify-between">
                          <button onClick={handleSelectAllFilteredPages} className="text-[10px] text-blue-500">全选结果</button>
                          <span className="text-[10px] text-slate-400">已选 {selectedBatchPages.length}</span>
                        </div>
                        <select
                          value=""
                          onChange={(event) => {
                            if (event.target.value) handleBatchStatusChange(event.target.value as FreeNoteReviewStatus);
                            event.currentTarget.value = '';
                          }}
                          className="w-full h-7 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 px-1 text-[11px]"
                        >
                          <option value="">批量设状态</option>
                          {REVIEW_STATUS_OPTIONS.map((item) => (
                            <option key={item.value} value={item.value}>{item.label}</option>
                          ))}
                        </select>
                      </div>
                    )}
                  </div>
                </div>
                <div className="p-2 space-y-2">
                  {filteredFreeNoteSummaries.length === 0 && (
                    <div className="px-2 py-6 text-center text-xs text-slate-400">没有匹配的自由笔记页</div>
                  )}
                  {filteredFreeNoteSummaries.map((item) => {
                    const active = item.page === freeNoteAnnotations.page;
                    return (
                      <div
                        key={item.page}
                        className={`rounded-lg border p-1.5 transition-colors ${
                          active
                            ? 'border-blue-400 bg-blue-50 dark:border-blue-500 dark:bg-blue-900/20'
                            : 'border-slate-200 dark:border-slate-700 hover:border-slate-300 dark:hover:border-slate-600'
                        }`}
                      >
                        {batchMode && (
                          <label className="mb-1 flex items-center gap-1 text-[10px] text-slate-500">
                            <input
                              type="checkbox"
                              checked={selectedBatchPages.includes(item.page)}
                              onChange={() => toggleBatchPage(item.page)}
                            />
                            选择
                          </label>
                        )}
                        <button
                          type="button"
                          onClick={() => freeNoteAnnotations.actions.setPage(item.page)}
                          className="w-full aspect-[4/3] rounded-md overflow-hidden bg-white dark:bg-slate-950 relative"
                        >
                          <div
                            className="absolute inset-0"
                            style={{
                              backgroundImage: item.background === 'grid'
                                ? 'linear-gradient(rgba(148,163,184,.25) 1px, transparent 1px), linear-gradient(90deg, rgba(148,163,184,.25) 1px, transparent 1px)'
                                : item.background === 'lined'
                                  ? 'linear-gradient(rgba(148,163,184,.28) 1px, transparent 1px)'
                                  : undefined,
                              backgroundSize: item.background === 'grid' ? '14px 14px' : '100% 18px',
                            }}
                          />
                          {item.inserts.map((insert) => (
                            <img
                              key={insert.id}
                              src={insert.dataUrl}
                              alt=""
                              className="absolute object-contain"
                              style={{
                                left: `${(insert.x ?? 0) * 100}%`,
                                top: `${(insert.y ?? 0) * 100}%`,
                                width: `${(insert.width ?? 1) * 100}%`,
                                height: `${(insert.height ?? 1) * 100}%`,
                              }}
                              draggable={false}
                            />
                          ))}
                          {item.textBlocks.map((block) => (
                            <div
                              key={block.id}
                              className="absolute truncate rounded-sm bg-white/70 px-0.5 text-[5px]"
                              style={{
                                left: `${block.x * 100}%`,
                                top: `${block.y * 100}%`,
                                width: `${block.width * 100}%`,
                                color: block.color,
                              }}
                            >
                              {block.text || '文本'}
                            </div>
                          ))}
                          <svg viewBox="0 0 1 1" preserveAspectRatio="none" className="absolute inset-0 w-full h-full">
                            {item.strokes.map((strokeItem, strokeIndex) => (
                              <polyline
                                key={strokeIndex}
                                points={strokeItem.points.map((point) => `${point.x},${point.y}`).join(' ')}
                                fill="none"
                                stroke={strokeItem.color}
                                strokeWidth={Math.max(0.004, strokeItem.width / 600)}
                                strokeLinecap="round"
                                strokeLinejoin="round"
                              />
                            ))}
                          </svg>
                        </button>
                        <div className="mt-1 flex items-center justify-between gap-1">
                          <div className="min-w-0">
                            <span className="block truncate text-[10px] text-slate-500 dark:text-slate-400">{item.title}</span>
                            {item.reviewStatus !== 'normal' && (
                              <span className="text-[9px] text-blue-500">
                                {REVIEW_STATUS_OPTIONS.find((option) => option.value === item.reviewStatus)?.label}
                              </span>
                            )}
                          </div>
                          <button
                            onClick={() => handleDeleteFreePage(item.page)}
                            className="min-w-[28px] min-h-[28px] flex items-center justify-center rounded-md text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                            title="删除页面"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </aside>
            )}
          </div>
        ) : ppt.state.slides.length === 0 ? (
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
        {activeTab === 'notes' ? (
          <div className="flex-shrink-0 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md border-t border-slate-200/60 dark:border-slate-800/60 px-3 py-2 flex items-center justify-between">
            <button
              onClick={goFreePrev}
              disabled={freeNoteAnnotations.page === freeNoteAnnotations.pageSummaries[0]?.page}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 disabled:opacity-30"
            >
              <ChevronLeft className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-2">
              <StickyNote className="w-4 h-4 text-amber-500" />
              <input
                value={freeNoteAnnotations.pageTitle}
                onChange={(event) => freeNoteAnnotations.actions.setTitle(event.target.value)}
                className="w-28 sm:w-44 bg-transparent text-center text-sm font-medium text-slate-700 dark:text-slate-200 outline-none border-b border-transparent focus:border-blue-300"
                aria-label="自由笔记标题"
              />
              <span className="text-xs text-slate-400">
                第 {freeNoteAnnotations.page} 页 / 共 {freeNoteTotalPages} 页
              </span>
              <button
                onClick={handleAddFreePage}
                className="min-w-[36px] min-h-[36px] flex items-center justify-center rounded-lg text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20"
                title="新增页面"
              >
                <Plus className="w-4 h-4" />
              </button>
            </div>
            <button
              onClick={goFreeNext}
              disabled={freeNoteAnnotations.page === freeNoteAnnotations.pageSummaries[freeNoteAnnotations.pageSummaries.length - 1]?.page}
              className="min-w-[44px] min-h-[44px] flex items-center justify-center rounded-lg text-slate-600 dark:text-slate-300 bg-slate-100 dark:bg-slate-800"
            >
              <ChevronRight className="w-5 h-5" />
            </button>
          </div>
        ) : activeTab === 'slides' && ppt.state.slides.length > 0 && (
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

      <nav className="flex-shrink-0 bg-white dark:bg-slate-900 border-t border-slate-200 dark:border-slate-800 px-2 py-1.5 grid grid-cols-3 gap-1">
        {tabItems.map((item) => {
          const Icon = item.icon;
          const active = activeTab === item.id;
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveTab(item.id)}
              className={`min-h-[52px] rounded-xl flex flex-col items-center justify-center gap-0.5 text-xs font-medium transition-colors ${
                active
                  ? 'bg-blue-50 text-blue-600 dark:bg-blue-900/30 dark:text-blue-300'
                  : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800'
              }`}
            >
              <Icon className="w-5 h-5" />
              {item.label}
            </button>
          );
        })}
      </nav>

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

      {aiPanel && (
        <div className="absolute right-4 bottom-20 z-40 w-[min(420px,calc(100vw-2rem))] rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-xl">
          <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
            <div>
              <p className="text-sm font-semibold text-slate-800 dark:text-slate-100">{AI_ACTION_LABELS[aiPanel.action]}</p>
              <p className="text-[11px] text-slate-400">AI 接口占位 · 已整理本页上下文</p>
            </div>
            <button onClick={() => setAiPanel(null)} className="text-slate-400 hover:text-slate-600">
              <X className="w-4 h-4" />
            </button>
          </div>
          <pre className="max-h-72 overflow-auto p-4 text-[11px] leading-relaxed text-slate-600 dark:text-slate-300 whitespace-pre-wrap">
            {JSON.stringify(aiPanel.context, null, 2)}
          </pre>
          <div className="border-t border-slate-200 dark:border-slate-700 p-3 space-y-2">
            <textarea
              value={aiDraftContent}
              onChange={(event) => setAiDraftContent(event.target.value)}
              className="w-full h-24 resize-none rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-950 p-2 text-xs text-slate-700 dark:text-slate-200 outline-none focus:border-blue-300"
              placeholder="填写要沉淀到本页的 AI 草稿内容。真实 AI 接口接入后，这里会保存接口返回结果。"
            />
            <button
              onClick={handleSaveAiDraft}
              className="w-full rounded-lg bg-blue-500 px-3 py-2 text-xs font-medium text-white hover:bg-blue-600"
            >
              保存到本页笔记
            </button>
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
