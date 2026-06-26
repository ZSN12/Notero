import { useMemo } from 'react';
import type { SessionProcessingStatus } from '@/services/api';

type WorkflowTone = 'blue' | 'green' | 'amber' | 'red' | 'violet' | 'slate';

export interface WorkflowStatus {
  tone: WorkflowTone;
  text: string;
  progress?: { current: number; total: number } | null;
  details?: Array<{ label: string; status: string; message?: string | null; error?: string | null; progress?: number | null }>;
  retryAgents?: string[];
  canRetrySave?: boolean;
}

interface AudioUploadState {
  isUploadingAudio: boolean;
  audioQueueProgress: { current: number; total: number } | null;
  uploadPhase: 'uploading' | 'transcribing' | 'finalizing';
}

interface PPTState {
  isUploadingPPT: boolean;
  uploadMessage: string | null;
}

interface RecordingState {
  isProcessing: boolean;
  isRecording: boolean;
  isPaused: boolean;
  currentTime: string;
}

interface TranscriptState {
  isPptMatching: boolean;
  lastSaveTime: number | null;
  pptMatchMessage: string | null;
  saveStatus: 'idle' | 'saving' | 'saved' | 'error';
  saveError: string | null;
}

interface MindMapState {
  mindMapStatus?: {
    mind_map?: { nodes?: unknown[] } | null;
  } | null;
}

interface QuizState {
  bankStatus?: {
    question_count?: number;
  } | null;
}

interface UseWorkflowStatusOptions {
  processingStatus: SessionProcessingStatus | null;
  audioUpload: AudioUploadState;
  ppt: PPTState;
  recording: RecordingState;
  transcript: TranscriptState;
  mindMap: MindMapState;
  quiz: QuizState;
}

const statusClassMap: Record<WorkflowTone, string> = {
  blue: 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800',
  green: 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800',
  amber: 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800',
  red: 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800',
  violet: 'bg-violet-50 text-violet-700 border-violet-200 dark:bg-violet-900/20 dark:text-violet-300 dark:border-violet-800',
  slate: 'bg-slate-50 text-slate-600 border-slate-200 dark:bg-slate-800/60 dark:text-slate-300 dark:border-slate-700',
};

const stageLabels: Record<string, string> = {
  upload_transcribe: '录音转写',
  recording_finalize: '录音保存',
  transcript_finalize: 'AI 整理',
  transcript_organize: '转写排版',
  vector_index: '知识索引',
  mindmap: '知识导图',
  quiz_bank: '题库',
};

const statusLabels: Record<string, string> = {
  idle: '未开始',
  queued: '排队中',
  running: '处理中',
  ready: '完成',
  partial: '部分完成',
  error: '失败',
  stale: '需更新',
  fallback: '本地兜底',
};

function stageDetail(stages: SessionProcessingStatus['stages'] | undefined, stage: keyof SessionProcessingStatus['stages']) {
  const data = stages?.[stage];
  if (!data) return null;
  return {
    label: stageLabels[stage] || stage,
    status: statusLabels[data.status] || data.status,
    message: data.message,
    error: data.error_message,
    progress: data.progress,
  };
}

function compactError(error?: string | null) {
  if (!error) return null;
  return error.length > 80 ? `${error.slice(0, 80)}...` : error;
}

export function useWorkflowStatus({
  processingStatus,
  audioUpload,
  ppt,
  recording,
  transcript,
  mindMap: _mindMap,
  quiz: _quiz,
}: UseWorkflowStatusOptions) {
  const workflowStatus: WorkflowStatus = useMemo(() => {
    const stages = processingStatus?.stages;
    if (ppt.isUploadingPPT) return { tone: 'blue', text: '正在上传并解析 PPT' };
    if (recording.isProcessing) return { tone: 'blue', text: '正在初始化录音设备' };

    if (recording.isRecording) {
      if (recording.isPaused) return { tone: 'amber', text: '录音已暂停' };
      if (transcript.isPptMatching) {
        return { tone: 'blue', text: `录音中 ${recording.currentTime} · 正在匹配 PPT 页面` };
      }
      return { tone: 'red', text: `录音中 ${recording.currentTime}` };
    }

    if (audioUpload.isUploadingAudio || stages?.upload_transcribe?.status === 'running') {
      if (audioUpload.uploadPhase === 'finalizing') {
        return { tone: 'violet', text: '正在整理转写稿' };
      }
      return { tone: 'blue', text: '正在处理录音文件', progress: audioUpload.audioQueueProgress };
    }

    if (stages?.recording_finalize?.status === 'running') return { tone: 'blue', text: '正在保存录音...', details: [stageDetail(stages, 'recording_finalize')].filter(Boolean) as WorkflowStatus['details'] };
    if (stages?.recording_finalize?.status === 'error') {
      return {
        tone: 'red',
        text: `录音保存失败：${compactError(stages.recording_finalize.error_message) || '未知错误'}`,
        details: [stageDetail(stages, 'recording_finalize')].filter(Boolean) as WorkflowStatus['details'],
      };
    }
    if (stages?.recording_finalize?.status === 'ready' && stages?.transcript_finalize?.status === 'idle') {
      return { tone: 'amber', text: '录音已保存，点击 AI 整理生成学习资料' };
    }

    if (stages?.transcript_finalize?.status === 'running') {
      return { tone: 'violet', text: stages.transcript_finalize.message || '正在整理转写稿', details: [stageDetail(stages, 'transcript_finalize')].filter(Boolean) as WorkflowStatus['details'] };
    }
    if (stages?.transcript_finalize?.status === 'error') {
      return {
        tone: 'red',
        text: `整理转写稿失败：${compactError(stages.transcript_finalize.error_message) || '未知错误'}`,
        details: [stageDetail(stages, 'transcript_finalize')].filter(Boolean) as WorkflowStatus['details'],
      };
    }
    if (stages?.upload_transcribe?.status === 'error') {
      return {
        tone: 'red',
        text: `上传转写失败：${compactError(stages.upload_transcribe.error_message) || '未知错误'}`,
        details: [stageDetail(stages, 'upload_transcribe')].filter(Boolean) as WorkflowStatus['details'],
      };
    }

    if (stages?.vector_index?.status === 'running') return { tone: 'violet', text: stages.vector_index.message || '正在建立知识索引', details: [stageDetail(stages, 'vector_index')].filter(Boolean) as WorkflowStatus['details'] };
    if (stages?.vector_index?.status === 'error') {
      return {
        tone: 'red',
        text: `知识索引建立失败：${compactError(stages.vector_index.error_message) || '未知错误'}`,
        details: [stageDetail(stages, 'vector_index')].filter(Boolean) as WorkflowStatus['details'],
      };
    }

    const agentStages = [stages?.mindmap, stages?.quiz_bank];
    const mindmapRunning = stages?.mindmap?.status === 'running';
    const quizRunning = stages?.quiz_bank?.status === 'running';
    const mindmapQueued = stages?.mindmap?.status === 'queued';
    const quizQueued = stages?.quiz_bank?.status === 'queued';
    const anyAgentRunning = mindmapRunning || quizRunning;
    const anyAgentQueued = mindmapQueued || quizQueued;
    const agentErrors: string[] = [];
    const retryAgents: string[] = [];
    if (stages?.mindmap?.status === 'error') {
      agentErrors.push('导图');
      retryAgents.push('mindmap');
    }
    if (stages?.quiz_bank?.status === 'error') {
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
      const runningDetails = [
        mindmapRunning ? stageDetail(stages, 'mindmap') : null,
        quizRunning ? stageDetail(stages, 'quiz_bank') : null,
      ].filter(Boolean) as WorkflowStatus['details'];
      const runningNames = runningDetails?.map((d) => d.label).join('、');
      return {
        tone: 'blue',
        text: runningNames ? `正在生成${runningNames}...` : '正在生成学习资料...',
        details: runningDetails,
      };
    }
    if (anyAgentQueued) {
      const queuedDetails = [
        mindmapQueued ? stageDetail(stages, 'mindmap') : null,
        quizQueued ? stageDetail(stages, 'quiz_bank') : null,
      ].filter(Boolean) as WorkflowStatus['details'];
      const queuedNames = queuedDetails?.map((d) => d.label).join('、');
      return {
        tone: 'amber',
        text: queuedNames ? `${queuedNames}等待前置任务执行...` : '学习资料等待前置任务执行...',
        details: queuedDetails,
      };
    }
    if (agentErrors.length > 0) {
      const errorDetails = [
        stages?.mindmap?.status === 'error' ? stageDetail(stages, 'mindmap') : null,
        stages?.quiz_bank?.status === 'error' ? stageDetail(stages, 'quiz_bank') : null,
      ].filter(Boolean) as WorkflowStatus['details'];
      const reason = errorDetails
        ?.map((d) => `${d.label}: ${compactError(d.error) || '未知错误'}`)
        .join('；');
      return {
        tone: 'red',
        text: `${agentErrors.join('、')}生成失败，可手动重试${reason ? `（${reason}）` : ''}`,
        details: errorDetails,
        retryAgents,
      };
    }
    if (
      hasAgents &&
      allAgentsReady &&
      transcriptFinalized &&
      stages?.vector_index?.status === 'ready'
    ) {
      return { tone: 'green', text: '整理成功' };
    }

    if (stages?.transcript_finalize?.status === 'fallback') {
      return {
        tone: 'amber',
        text: stages.transcript_finalize.message || '已使用本地整理稿',
        details: [stageDetail(stages, 'transcript_finalize')].filter(Boolean) as WorkflowStatus['details'],
      };
    }

    if (transcript.isPptMatching) return { tone: 'blue', text: '正在匹配 PPT 页面' };
    if (transcript.saveStatus === 'error') return { tone: 'red', text: transcript.saveError || '保存失败', canRetrySave: true };
    if (ppt.uploadMessage) return { tone: 'green', text: ppt.uploadMessage };
    if (transcript.pptMatchMessage) return { tone: 'slate', text: transcript.pptMatchMessage };
    if (transcript.lastSaveTime) {
      const time = new Date(transcript.lastSaveTime).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
      return { tone: 'green', text: `已保存 ${time}` };
    }
    return { tone: 'slate', text: '准备记录' };
  }, [
    processingStatus?.stages,
    audioUpload.isUploadingAudio,
    audioUpload.audioQueueProgress,
    audioUpload.uploadPhase,
    ppt.isUploadingPPT,
    ppt.uploadMessage,
    recording.currentTime,
    recording.isPaused,
    recording.isProcessing,
    recording.isRecording,
    transcript.isPptMatching,
    transcript.lastSaveTime,
    transcript.pptMatchMessage,
    transcript.saveError,
    transcript.saveStatus,
  ]);

  const statusClass = statusClassMap[workflowStatus.tone];

  return { workflowStatus, statusClass };
}
