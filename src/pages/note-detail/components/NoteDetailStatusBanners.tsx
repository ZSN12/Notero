import { AlertCircle, CheckCircle2, Clock, Database, Loader2, X, FileText, Brain, ListChecks } from 'lucide-react';
import type { WorkflowStatus } from '@/pages/note-detail/hooks/useWorkflowStatus';
import type { usePPT } from '@/pages/note-detail/usePPT';
import type { useRecording } from '@/pages/note-detail/useRecording';
import type { useTranscript } from '@/pages/note-detail/useTranscript';
import type { useAudioUpload } from '@/pages/note-detail/hooks/useAudioUpload';
import type { useAutoGenerate } from '@/pages/note-detail/hooks/useAutoGenerate';
import type { ProcessingStage, ProcessingStageState, SessionProcessingStatus } from '@/services/api';

interface NoteDetailStatusBannersProps {
  autoGen: ReturnType<typeof useAutoGenerate>;
  workflowStatus: WorkflowStatus;
  statusClass: string;
  ppt: ReturnType<typeof usePPT>;
  recording: ReturnType<typeof useRecording>;
  transcript: ReturnType<typeof useTranscript>;
  audioUpload: ReturnType<typeof useAudioUpload>;
  processingStatus?: SessionProcessingStatus | null;
  processingOverallStatus?: string | null;
  onRetryAgents: (agents: string[]) => void;
  onRetrySave: () => void;
  onDismissRecordingError: () => void;
  onDismissPPTError: () => void;
  onDismissAudioError: () => void;
}

export function NoteDetailStatusBanners({
  autoGen,
  workflowStatus,
  statusClass,
  ppt,
  recording,
  transcript,
  audioUpload,
  processingStatus,
  processingOverallStatus,
  onRetryAgents,
  onRetrySave,
  onDismissRecordingError,
  onDismissPPTError,
  onDismissAudioError,
}: NoteDetailStatusBannersProps) {
  const isBusy =
    ppt.state.isUploadingPPT ||
    audioUpload.state.isUploadingAudio ||
    recording.state.isProcessing ||
    transcript.state.isPptMatching ||
    processingOverallStatus === 'running';

  const transientMessage = autoGen.state.autoGenerateToast;
  const displayText = transientMessage || workflowStatus.text;
  const isTransientRunning = transientMessage?.startsWith('正在') ?? false;
  const statusDetails = workflowStatus.details?.filter(Boolean) ?? [];
  const displayStatusClass = transientMessage
    ? isTransientRunning
      ? 'bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-900/20 dark:text-blue-300 dark:border-blue-800'
      : transientMessage.includes('失败')
        ? 'bg-red-50 text-red-700 border-red-200 dark:bg-red-900/20 dark:text-red-300 dark:border-red-800'
        : transientMessage.includes('完成') || transientMessage.includes('成功')
          ? 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-900/20 dark:text-emerald-300 dark:border-emerald-800'
          : 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-900/20 dark:text-amber-300 dark:border-amber-800'
    : statusClass;

  const stageRows: Array<{
    key: ProcessingStage;
    label: string;
    icon: typeof FileText;
    retryAgent?: string;
  }> = [
    { key: 'transcript_finalize', label: '转写整理', icon: FileText },
    { key: 'vector_index', label: '知识索引', icon: Database },
    { key: 'mindmap', label: '知识导图', icon: Brain, retryAgent: 'mindmap' },
    { key: 'quiz_bank', label: '题库', icon: ListChecks, retryAgent: 'quiz' },
  ];

  const normalizeProgress = (value?: number | null) => {
    if (typeof value !== 'number' || Number.isNaN(value)) return null;
    const pct = value <= 1 ? value * 100 : value;
    return Math.max(0, Math.min(100, Math.round(pct)));
  };

  const stageLabel = (stage?: ProcessingStageState) => {
    switch (stage?.status) {
      case 'queued':
        return '排队中';
      case 'running': {
        const progress = normalizeProgress(stage.progress);
        return progress && progress > 0 && progress < 100 ? `处理中 ${progress}%` : '处理中';
      }
      case 'ready':
        return '已完成';
      case 'partial':
        return '部分完成';
      case 'error':
        return '失败';
      case 'stale':
        return '需更新';
      case 'fallback':
        return '本地兜底';
      default:
        return '未开始';
    }
  };

  const stageToneClass = (stage?: ProcessingStageState) => {
    switch (stage?.status) {
      case 'ready':
        return 'border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300';
      case 'running':
      case 'queued':
        return 'border-blue-200 bg-blue-50 text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300';
      case 'partial':
      case 'fallback':
      case 'stale':
        return 'border-amber-200 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300';
      case 'error':
        return 'border-red-200 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300';
      default:
        return 'border-slate-200 bg-white/50 text-slate-500 dark:border-slate-700 dark:bg-slate-900/30 dark:text-slate-400';
    }
  };

  const stageStatusIcon = (stage?: ProcessingStageState) => {
    if (stage?.status === 'ready') return <CheckCircle2 className="w-3.5 h-3.5" />;
    if (stage?.status === 'running' || stage?.status === 'queued') return <Loader2 className="w-3.5 h-3.5 animate-spin" />;
    if (stage?.status === 'error') return <AlertCircle className="w-3.5 h-3.5" />;
    return <Clock className="w-3.5 h-3.5" />;
  };

  const shouldShowLearningQueue = stageRows.some(({ key }) => {
    const status = processingStatus?.stages?.[key]?.status;
    return status && status !== 'idle';
  });

  return (
    <>
      <div className={`flex-shrink-0 mx-4 mt-3 px-3 py-2 border rounded-xl flex items-start gap-2 text-xs ${displayStatusClass}`}>
        {(isBusy || isTransientRunning) && <Loader2 className="w-3.5 h-3.5 animate-spin flex-shrink-0 mt-0.5" />}
        <div className="flex-1 min-w-0">
          <div className="font-medium">{displayText}</div>
          {statusDetails.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1.5 opacity-90">
              {statusDetails.map((detail) => {
                const detailText = detail.error || detail.message;
                return (
                  <span
                    key={`${detail.label}-${detail.status}`}
                    className="inline-flex max-w-full items-center gap-1 rounded-md bg-white/55 dark:bg-slate-900/35 px-1.5 py-0.5"
                    title={detailText || undefined}
                  >
                    <span className="font-medium">{detail.label}</span>
                    <span>·</span>
                    <span>{detail.status}</span>
                    {typeof detail.progress === 'number' && detail.progress > 0 && detail.progress < 100 && (
                      <>
                        <span>·</span>
                        <span>{Math.round(detail.progress)}%</span>
                      </>
                    )}
                    {detailText && (
                      <>
                        <span>·</span>
                        <span className="truncate">{detailText}</span>
                      </>
                    )}
                  </span>
                );
              })}
            </div>
          )}
        </div>
        {workflowStatus.progress && workflowStatus.progress.total > 1 && (
          <div className="flex items-center gap-2 w-28 sm:w-36">
            <div className="flex-1 h-1.5 bg-current opacity-20 rounded-full overflow-hidden">
              <div
                className="h-full bg-current rounded-full transition-all duration-300"
                style={{ width: `${((workflowStatus.progress.current / workflowStatus.progress.total) * 100).toFixed(1)}%` }}
              />
            </div>
            <span className="text-xs tabular-nums opacity-90">
              {workflowStatus.progress.current}/{workflowStatus.progress.total}
            </span>
          </div>
        )}
        {workflowStatus.retryAgents && workflowStatus.retryAgents.length > 0 && (
          <button
            onClick={() => onRetryAgents(workflowStatus.retryAgents!)}
            disabled={autoGen.state.isTriggeringAgents}
            className="px-2 py-1 rounded-md bg-white/70 dark:bg-slate-900/60 hover:bg-white text-xs font-medium disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
          >
            {autoGen.state.isTriggeringAgents && <Loader2 className="w-3 h-3 animate-spin" />}
            {workflowStatus.retryAgents.length === 1
              ? workflowStatus.retryAgents[0] === 'mindmap'
                ? '重新生成导图'
                : workflowStatus.retryAgents[0] === 'quiz'
                  ? '重新生成题库'
                  : `重新生成${workflowStatus.retryAgents[0]}`
              : '重新生成'}
          </button>
        )}
        {transcript.state.saveStatus === 'error' && (
          <button
            onClick={onRetrySave}
            className="px-2 py-1 rounded-md bg-white/70 dark:bg-slate-900/60 hover:bg-white text-xs font-medium"
          >
            重试保存
          </button>
        )}
      </div>

      {shouldShowLearningQueue && (
        <div className="flex-shrink-0 mx-4 mt-2 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-2">
          {stageRows.map(({ key, label, icon: Icon, retryAgent }) => {
            const stage = processingStatus?.stages?.[key];
            const title = stage?.error_message || stage?.message || undefined;
            const canRetry = stage?.status === 'error' && retryAgent;
            return (
              <div
                key={key}
                className={`min-w-0 rounded-xl border px-3 py-2 text-xs ${stageToneClass(stage)}`}
                title={title}
              >
                <div className="flex items-center gap-2">
                  <Icon className="w-3.5 h-3.5 shrink-0 opacity-80" />
                  <span className="font-medium truncate">{label}</span>
                  <span className="ml-auto shrink-0">{stageStatusIcon(stage)}</span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="truncate">{stageLabel(stage)}</span>
                  {canRetry && (
                    <button
                      type="button"
                      onClick={() => onRetryAgents([retryAgent])}
                      disabled={autoGen.state.isTriggeringAgents}
                      className="ml-auto shrink-0 rounded-md bg-white/70 dark:bg-slate-900/50 px-1.5 py-0.5 font-medium hover:bg-white disabled:opacity-50"
                    >
                      重试
                    </button>
                  )}
                </div>
                {stage?.status === 'running' && normalizeProgress(stage.progress) !== null && (
                  <div className="mt-2 h-1 rounded-full bg-current/15 overflow-hidden">
                    <div
                      className="h-full rounded-full bg-current transition-all duration-300"
                      style={{ width: `${normalizeProgress(stage.progress)}%` }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {recording.state.isError && recording.state.errorMessage && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-xs text-red-600 dark:text-red-400">{recording.state.errorMessage}</p>
          </div>
          <button
            onClick={onDismissRecordingError}
            className="p-0.5 text-red-400 hover:text-red-600"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}

      {ppt.state.uploadError && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-xs text-red-600 dark:text-red-400">{ppt.state.uploadError}</p>
          </div>
          <button onClick={onDismissPPTError} className="text-red-400 hover:text-red-600">
            <X className="w-4 h-4" />
          </button>
        </div>
      )}

      {audioUpload.state.audioUploadError && (
        <div className="flex-shrink-0 mx-4 mt-3 p-3 bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 rounded-xl flex items-start gap-2">
          <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0 mt-0.5" />
          <div className="flex-1">
            <p className="text-xs text-red-600 dark:text-red-400">{audioUpload.state.audioUploadError}</p>
          </div>
          <button onClick={onDismissAudioError} className="p-0.5 text-red-400 hover:text-red-600">
            <X className="w-3.5 h-3.5" />
          </button>
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
            <p className="text-xs text-violet-700 dark:text-violet-300">
              有 AI 整理版本可应用，当前编辑内容不会被自动覆盖。
            </p>
          </div>
          <button
            onClick={transcript.actions.applyPendingAiText}
            className="px-2 py-1 rounded-md bg-violet-500 text-white text-xs font-medium hover:bg-violet-600"
          >
            应用
          </button>
          <button
            onClick={transcript.actions.dismissPendingAiText}
            className="text-violet-400 hover:text-violet-600"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      )}
    </>
  );
}
