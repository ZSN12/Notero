import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { Slide } from '@/services/api';
import NoteDetail from '../../index';

let mockSlides: Slide[] = [];

vi.mock('react-router-dom', () => ({
  useParams: () => ({ id: 'n1', sessionId: 's1' }),
  useNavigate: () => vi.fn(),
  useLocation: () => ({ pathname: '/', state: null }),
}));

vi.mock('@/store/useStore', () => ({
  useStore: (selector: (s: unknown) => unknown) => selector({ notebooks: [], sessions: [] }),
}));

vi.mock('@/services/auth', () => ({
  getProfile: vi.fn().mockResolvedValue({}),
  getAvatarUrl: () => '',
}));

vi.mock('@/services/api', async () => {
  const actual = await vi.importActual<typeof import('@/services/api')>('@/services/api');
  return {
    ...actual,
    fetchNotebookDetail: vi.fn().mockResolvedValue(null),
    fetchSessionById: vi.fn().mockResolvedValue(null),
    insertPPTIntoTranscript: vi.fn().mockResolvedValue({ blocks: [] }),
    getMediaUrl: (url: string) => url,
  };
});

vi.mock('@/components/RichTextEditor', () => ({
  default: () => <div data-testid="rich-text-editor" />,
}));

vi.mock('@/components/AuthenticatedImage', () => ({
  AuthenticatedImage: () => <img data-testid="authenticated-image" alt="" />,
}));

const mockHook = (state: Record<string, unknown>, actions: Record<string, unknown> = {}, refs: Record<string, unknown> = {}) => ({
  state,
  actions,
  refs,
});

vi.mock('../../useRecording', () => ({
  useRecording: () =>
    mockHook(
      {
        isRecording: false,
        isProcessing: false,
        isPaused: false,
        isError: false,
        errorMessage: '',
        audioPlaybackUrl: null,
        isPlayingAudio: false,
      },
      {
        stopRecording: vi.fn(),
        setIsError: vi.fn(),
        setErrorMessage: vi.fn(),
        setIsPlayingAudio: vi.fn(),
      },
      { audioPlayerRef: { current: null } },
    ),
}));

vi.mock('../../useTranscript', () => ({
  useTranscript: () =>
    mockHook(
      {
        transcriptText: '',
        partialText: '',
        contentBlocks: [],
        isLoaded: true,
        hasLocalChanges: false,
        loadedNote: null,
        lastSaveTime: null,
        sentencesWithTime: [],
        activeSentenceIndex: null,
        paragraphTimeRanges: [],
      },
      {
        receiveAiText: vi.fn(),
        updateContentBlocks: vi.fn(),
        updateContentBlockDraft: vi.fn(),
        commitContentBlockDraft: vi.fn(),
        updateTranscriptDraft: vi.fn(),
        commitTranscriptDraft: vi.fn(),
        saveContent: vi.fn(),
        markUserEdited: vi.fn(),
        scheduleSave: vi.fn(),
        clearPartialText: vi.fn(),
        setGetCurrentNotes: vi.fn(),
        setActiveSentenceIndex: vi.fn(),
        setSentencesWithTime: vi.fn(),
        setEditorFocused: vi.fn(),
      },
    ),
}));

vi.mock('../../usePPT', () => ({
  usePPT: () =>
    mockHook(
      { slides: mockSlides, activeSlideIndex: 0 },
      { setSlides: vi.fn(), setActiveSlideIndex: vi.fn(), setUploadError: vi.fn(), handlePPTUpload: vi.fn() },
    ),
}));

vi.mock('../../useNotes', () => ({
  useNotes: () =>
    mockHook(
      { notes: [] },
      {
        parseNotesFromContent: vi.fn().mockReturnValue([]),
        setNotes: vi.fn(),
        resetDrafts: vi.fn(),
        updateNoteDraft: vi.fn(),
        commitNotesDraft: vi.fn(),
      },
      { notesDraftRef: { current: '' } },
    ),
}));

vi.mock('../../useExport', () => ({
  useExport: () => mockHook({ showExportMenu: false, isExportingPDF: false, isExportingPackage: false }, { exportMarkdown: vi.fn(), exportPDF: vi.fn(), exportNotebookPackage: vi.fn(), setShowExportMenu: vi.fn() }),
}));

vi.mock('../../hooks/useShare', () => ({
  useShare: () => mockHook({ shareExpiresIn: 1, shareMaxViewsInput: '' }, { handleShareSession: vi.fn() }),
}));

vi.mock('../../hooks/useVectorIndex', () => ({
  useVectorIndex: () => mockHook({ vectorStatus: null, isRebuilding: false }, { ensureIndexed: vi.fn().mockResolvedValue(undefined), handleRebuildIndex: vi.fn() }),
}));

vi.mock('../../hooks/useRAG', () => ({
  useRAG: () =>
    mockHook(
      {
        showSearch: false,
        searchQuery: '',
        searchScope: 'session',
        messages: [],
        ragAnswer: '',
        ragSources: [],
        isAskingRAG: false,
        ragError: null,
        ragStatus: null,
      },
      {
        setShowSearch: vi.fn(),
        setSearchQuery: vi.fn(),
        setSearchScope: vi.fn(),
        handleRAGAsk: vi.fn(),
        clearMessages: vi.fn(),
        loadMessages: vi.fn(),
      },
    ),
}));

vi.mock('../../hooks/useMindMap', () => ({
  useMindMap: () => mockHook({ showMindMap: false, mindMapStatus: null, copyMindMapSuccess: false }, { setShowMindMap: vi.fn(), handleCopyMindMapOutline: vi.fn() }),
}));

vi.mock('../../hooks/useQuiz', () => ({
  useQuiz: () =>
    mockHook(
      { showQuiz: false, showQuizQA: false, activeQuiz: null, quizSubmitted: false, quizAnswers: {}, quizError: null },
      {
        setShowQuiz: vi.fn(),
        setShowQuizQA: vi.fn(),
        setActiveQuiz: vi.fn(),
        setQuizSubmitted: vi.fn(),
        setQuizAnswers: vi.fn(),
        setQuizError: vi.fn(),
      },
    ),
}));

vi.mock('../../hooks/useAudioUpload', () => ({
  useAudioUpload: () =>
    mockHook(
      { isUploadingAudio: false, audioUploadStatus: '', audioUploadError: null },
      { setAudioUploadError: vi.fn() },
    ),
}));

vi.mock('../../hooks/useAutoGenerate', () => ({
  useAutoGenerate: () => mockHook({ autoGenerateStudyMaterials: false }, { handleTriggerAgents: vi.fn() }),
}));

vi.mock('../../hooks/useRestructure', () => ({
  useRestructure: () => mockHook({ isRestructuring: false }, { handleRestructure: vi.fn().mockResolvedValue(false) }),
}));

vi.mock('../../hooks/useProcessingStatus', () => ({
  useProcessingStatus: () => mockHook({ processingStatus: null }, { refresh: vi.fn() }),
}));

vi.mock('../../hooks/useWorkflowStatus', () => ({
  useWorkflowStatus: () => ({ workflowStatus: null, statusClass: '' }),
}));

vi.mock('../../components/NoteDetailTopNav', () => ({
  NoteDetailTopNav: () => <nav data-testid="top-nav" />,
}));

vi.mock('../../components/NoteDetailToolbar', () => ({
  NoteDetailToolbar: () => <div data-testid="toolbar" />,
}));

vi.mock('../../components/NoteDetailStatusBanners', () => ({
  NoteDetailStatusBanners: () => <div data-testid="status-banners" />,
}));

vi.mock('../../components/PPTPanel', () => ({
  PPTPanel: () => <div data-testid="ppt-panel" />,
}));

vi.mock('../../components/SideNotesPanel', () => ({
  SideNotesPanel: () => <div data-testid="side-notes-panel" />,
}));

vi.mock('../../components/NotesPanel', () => ({
  NotesPanel: () => <main data-testid="transcript-panel" />,
}));

vi.mock('../../components/MindMapDrawer', () => ({
  MindMapDrawer: () => <div data-testid="mind-map-drawer" />,
}));

vi.mock('../../components/QuizDrawer', () => ({
  QuizDrawer: () => <div data-testid="quiz-drawer" />,
}));

vi.mock('../../components/RagSearchModal', () => ({
  RagSearchModal: () => <div data-testid="rag-search-modal" />,
}));

vi.mock('../../components/ShareModal', () => ({
  ShareModal: () => <div data-testid="share-modal" />,
}));

vi.mock('../../components/DragPreviewOverlay', () => ({
  DragPreviewOverlay: () => <div data-testid="drag-preview-overlay" />,
}));

describe('NoteDetail layout fallback without PPT', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSlides = [];
  });

  it('hides the auxiliary sidebar and shows transcript full-width when no PPT', () => {
    render(<NoteDetail />);

    expect(screen.queryByTestId('ppt-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('side-notes-panel')).not.toBeInTheDocument();
    expect(screen.getByTestId('transcript-panel')).toBeInTheDocument();

    const layoutContainer = screen.getByTestId('transcript-panel').parentElement;
    expect(layoutContainer).not.toBeNull();
    expect(layoutContainer?.querySelector('aside')).toBeNull();
  });

  it('shows the auxiliary sidebar with correct width when PPT exists', () => {
    mockSlides = [{ page: 1, title: 'Slide 1', text: 'slide text', image_path: 's1.png' }];

    render(<NoteDetail />);

    const aside = screen.getByTestId('transcript-panel').parentElement?.querySelector('aside');
    expect(aside).toBeInTheDocument();
    expect(aside?.className).toContain('lg:w-[30%]');
    expect(screen.getByTestId('ppt-panel')).toBeInTheDocument();
  });
});
