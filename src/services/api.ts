// Barrel export: all API modules re-exported for backward compatibility.
// Prefer importing from specific modules (e.g. `@/services/api/notebook`) in new code.

export { API_BASE, authHeaders, getMediaUrl, request, formatDuration } from './api/core';
export { mapBackendNotebook, mapBackendSession } from './api/mappers';

export type {
  TranscriptChunk,
  PPTSlide,
  PPTImageData,
  VocabularyItem,
  BackendNotebook,
  BackendSession,
  BackendNote,
  ContentBlock,
  Slide,
  AudioUploadCallbacks,
  VectorIndexStatus,
  VectorSearchResult,
  MindMapNode,
  MindMapRelation,
  MindMapData,
  MindMapStatus,
  QuizOption,
  QuizMode,
  QuizQuestion,
  QuizBankStatus,
  QuizListItem,
  QuizDetail,
  QuizSubmitResult,
  QuizMasteryPoint,
  QuizMastery,
  AgentTask,
  RAGSource,
  RAGCallbacks,
  RAGMessage,
  ParagraphTimeRange,
  ProcessingStage,
  ProcessingStatusValue,
  ProcessingStageState,
  AgentTaskSummary,
  SessionProcessingStatus,
} from './api/types';

export {
  fetchNotebooks,
  createNotebook,
  deleteNotebook,
  updateNotebook,
  fetchNotebookDetail,
} from './api/notebook';

export {
  fetchSessions,
  fetchSessionDetail,
  fetchSessionById,
  createSession,
  deleteSession,
  updateSessionDuration,
} from './api/session';

export {
  fetchNote,
  updateNote,
  finishRecording,
  getAudioUrl,
  deleteAudio,
  updateTranscript,
  finalizeTranscript,
} from './api/note';

export {
  alignPPTWithText,
  insertPPTIntoTranscript,
  uploadPPT,
  streamAudioChunk,
  uploadAudio,
} from './api/media';

export {
  enableShare,
  disableShare,
  getShareStatus,
  getShareMediaUrl,
} from './api/share';

export {
  rebuildSessionVectorIndex,
  rebuildNotebookVectorIndex,
  getSessionVectorStatus,
  searchVectors,
} from './api/vector';

export {
  getSessionMindMap,
  generateSessionMindMap,
  deleteSessionMindMap,
  saveMindMapPositions,
} from './api/mindmap';

export {
  getQuizBankStatus,
  rebuildQuizBank,
  getSessionQuizzes,
  generateSessionQuiz,
  getQuizDetail,
  submitQuizAnswers,
  getQuizMastery,
  deleteQuiz,
} from './api/quiz';

export {
  runAllAgents,
  getAgentTasks,
  restructureTranscript,
} from './api/agent';

export {
  askRAG,
  fetchRAGMessages,
  clearRAGMessages,
  serializeRAGSources,
} from './api/rag';

export {
  importNotebook,
  exportNotebook,
} from './api/import-export';

export {
  getSessionProcessingStatus,
} from './api/status';
