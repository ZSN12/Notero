import type { NoteLayoutBlock } from '@/lib/noteLayout';

export interface TranscriptChunk {
  chunk_index?: number;
  raw_text?: string;
  text?: string;
  display_text?: string;
  corrected_text?: string;
  correction_stage?: string;
  timestamps?: Array<{ text: string; start: number; end: number }>;
}

export interface PPTSlide {
  page: number;
  title: string;
  text: string;
  image_path?: string;
  image_base64?: string;
}

export interface PPTImageData {
  slides: PPTSlide[];
}

export interface VocabularyItem {
  kind: string;
  [key: string]: unknown;
}

export interface BackendNotebook {
  id: string;
  user_id: string;
  title: string;
  description: string | null;
  icon: string | null;
  color: string | null;
  session_count: number;
  created_at: string;
}

export interface BackendSession {
  id: string;
  notebook_id: string;
  title: string;
  keywords: string[];
  status: string;
  created_at: string;
}

export interface BackendNote {
  id: string;
  session_id: string;
  content: string | null;
  transcript: TranscriptChunk[] | null;
  ppt_images: PPTImageData[] | null;
  vocabulary: VocabularyItem[] | null;
  layout_blocks?: NoteLayoutBlock[] | null;
  created_at: string;
}

export interface ContentBlock {
  type: 'text' | 'image' | 'marker';
  content?: string;
  src?: string;
  page?: number;
  title?: string;
}

export interface Slide {
  page: number;
  title: string;
  text: string;
  image_path?: string;
  image_base64?: string;
}

export interface AudioUploadCallbacks {
  onStart?: () => void;
  onStatus?: (message: string, segment: number, total: number) => void;
  onChunk: (
    text: string,
    segment: number,
    segmentTotal: number,
    meta?: {
      chunkId?: string;
      rawText?: string;
      isAiCorrected?: boolean;
      correctionError?: string | null;
      isFinal?: boolean;
    },
  ) => void;
  onCorrection?: (
    text: string,
    segment: number,
    segmentTotal: number,
    meta?: {
      chunkId?: string;
      rawText?: string;
      isAiCorrected?: boolean;
      correctionError?: string | null;
    },
  ) => void;
  onDone: (note: BackendNote | null) => void;
  onError: (error: string) => void;
}

export interface VectorIndexStatus {
  session_id: string;
  chunk_count: number;
  has_content: boolean;
  status: 'indexed' | 'not_indexed' | 'empty' | 'stale';
}

export interface VectorSearchResult {
  chunk_id: string;
  notebook_id: string;
  notebook_title: string;
  session_id: string;
  session_title: string;
  source_type: string;
  snippet: string;
  score: number;
  metadata: Record<string, unknown>;
}

export interface MindMapNode {
  id: string;
  title: string;
  description?: string;
  type: 'topic' | 'concept' | 'key_point' | 'difficulty' | 'example' | 'process' | 'function' | 'question' | 'conclusion';
  importance: 'high' | 'medium' | 'low';
  sources?: Array<{
    source_type: string;
    snippet: string;
    page?: number | null;
    block_id?: string;
  }>;
  children?: MindMapNode[];
}

export interface MindMapRelation {
  source: string;
  target: string;
  type: 'contrast' | 'step' | 'example_of' | 'used_by' | 'depends_on' | 'warning' | 'related';
  label: string;
}

export interface MindMapData {
  title: string;
  summary?: string;
  nodes: MindMapNode[];
  relations?: MindMapRelation[];
  positions?: Record<string, { x: number; y: number }>;
}

export interface MindMapStatus {
  session_id: string;
  status: 'empty' | 'not_generated' | 'generating' | 'ready' | 'stale' | 'error';
  mind_map: MindMapData | null;
  generated_at?: string;
  task_id?: string;
  progress?: number;
  error?: string | null;
}

export interface QuizOption {
  id: string;
  text: string;
  explanation?: string;
}

export interface QuizQuestion {
  id: string;
  question: string;
  options: QuizOption[];
  answer?: string;
  explanation?: string;
  source?: {
    source_type: string;
    snippet: string;
    page?: number | null;
  };
}

export interface QuizBankStatus {
  session_id: string;
  status: 'empty' | 'not_generated' | 'generating' | 'ready' | 'stale' | 'error';
  question_count: number;
  task_id?: string | null;
  progress?: number;
  error?: string | null;
}

export interface QuizListItem {
  quiz_id: string;
  title: string;
  question_count: number;
  questions: Array<{ id: string; question: string; options: Array<{ id: string; text: string }> }>;
  generated_at?: string;
  submitted: boolean;
  score?: {
    score: number;
    total: number;
    percentage: number;
  } | null;
}

export interface QuizDetail {
  quiz_id: string;
  title: string;
  questions: QuizQuestion[];
  generated_at?: string;
  submission?: {
    answers: Record<string, string>;
    score: number;
    total: number;
    percentage: number;
    results: Array<{
      question_id: string;
      correct: boolean;
      selected: string;
      answer: string;
      explanation: string;
    }>;
    submitted_at: string;
  };
}

export interface QuizSubmitResult {
  score: number;
  total: number;
  percentage: number;
  results: Array<{
    question_id: string;
    correct: boolean;
    selected: string;
    answer: string;
    explanation: string;
  }>;
}

export interface AgentTask {
  task_id: string;
  task_type: string;
  status: 'pending' | 'running' | 'success' | 'error';
  progress: number;
  error: string | null;
  created_at: string | null;
}

export interface RAGSource {
  chunk_id: string;
  notebook_id: string;
  notebook_title: string;
  session_id: string;
  session_title: string;
  source_type: string;
  snippet: string;
  score: number;
  page?: number | string | null;
  block_id?: string | null;
  chunk_index?: number | null;
  metadata?: Record<string, unknown>;
}

export interface RAGCallbacks {
  onStatus: (message: string) => void;
  onChunk: (text: string) => void;
  onSources: (sources: RAGSource[]) => void;
  onDone: () => void;
  onError: (error: string) => void;
}

export type ProcessingStage = 'upload_transcribe' | 'recording_finalize' | 'transcript_finalize' | 'transcript_organize' | 'vector_index' | 'mindmap' | 'quiz_bank';
export type ProcessingStatusValue = 'idle' | 'running' | 'ready' | 'error' | 'stale' | 'fallback';

export interface ProcessingStageState {
  status: ProcessingStatusValue;
  progress: number;
  message: string | null;
  error_message: string | null;
  content_hash: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface AgentTaskSummary {
  id: string;
  task_type: string;
  status: string;
  progress: number;
  error_message: string | null;
  created_at: string | null;
}

export interface SessionProcessingStatus {
  session_id: string;
  overall_status: ProcessingStatusValue | 'running';
  stages: Record<ProcessingStage, ProcessingStageState>;
  can_auto_generate: boolean;
  can_ask_rag: boolean;
  needs_user_action: boolean;
  latest_tasks: AgentTaskSummary[];
  vector_chunks_count: number;
}
