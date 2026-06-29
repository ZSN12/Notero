import { AlertCircle, ClipboardCheck, Loader2, Sparkles } from 'lucide-react';
import type { useQuiz } from '@/pages/note-detail/hooks/useQuiz';
import type { QuizMode } from '@/services/api';

interface TodayReviewCardProps {
  quiz: ReturnType<typeof useQuiz>;
}

export function TodayReviewCard({ quiz }: TodayReviewCardProps) {
  const bankStatus = quiz.state.bankStatus;
  const mastery = quiz.state.mastery;
  const weakCount = mastery?.summary.weak_count ?? 0;
  const pendingCount = mastery?.summary.pending_review_count ?? 0;
  const reviewPoints = (mastery?.knowledge_points ?? [])
    .filter((item) => item.weak || item.pending_review)
    .slice(0, 2);
  const bankReady = bankStatus?.status === 'ready';
  const bankBusy = bankStatus?.status === 'generating' || bankStatus?.status === 'queued' || quiz.state.isRebuildingBank;
  const isWorking = bankBusy || quiz.state.isGeneratingQuiz;

  let recommendation = '状态稳定，可继续学习';
  let actionLabel = '查看学习状态';
  let actionMode: QuizMode | null = null;
  let actionKind: 'open' | 'rebuild' | 'generate' = 'open';
  let disabled = false;

  if (!bankStatus) {
    recommendation = '检查复习状态';
    actionLabel = '检查中';
    disabled = true;
  } else if (bankStatus.status === 'empty') {
    recommendation = '暂无可复习内容';
    actionLabel = '等待内容';
    disabled = true;
  } else if (!bankReady) {
    recommendation = bankBusy ? '题库生成中' : '先生成题库';
    actionLabel = bankBusy ? '生成中' : bankStatus.status === 'stale' ? '更新题库' : '生成题库';
    actionKind = 'rebuild';
    disabled = bankBusy;
  } else if (weakCount > 0) {
    recommendation = '错题变式练习';
    actionLabel = '开始变式';
    actionMode = 'variant';
    actionKind = 'generate';
  } else if (pendingCount > 0) {
    recommendation = '复习后测验';
    actionLabel = '开始复习';
    actionMode = 'review';
    actionKind = 'generate';
  }

  const handleAction = async () => {
    quiz.actions.setShowQuiz(true);
    quiz.actions.setQuizError(null);
    quiz.actions.setActiveQuiz(null);
    quiz.actions.setQuizSubmitted(false);
    quiz.actions.setQuizAnswers({});

    if (actionKind === 'rebuild') {
      await quiz.actions.handleRebuildBank();
      return;
    }
    if (actionKind === 'generate' && actionMode) {
      await quiz.actions.handleGenerateQuiz(actionMode);
    }
  };

  const toneClass = !bankReady
    ? bankStatus?.status === 'error'
      ? 'border-red-200 bg-red-50/80 text-red-700 dark:border-red-800 dark:bg-red-900/20 dark:text-red-300'
      : 'border-blue-200 bg-blue-50/80 text-blue-700 dark:border-blue-800 dark:bg-blue-900/20 dark:text-blue-300'
    : weakCount > 0
      ? 'border-violet-200 bg-violet-50/80 text-violet-700 dark:border-violet-800 dark:bg-violet-900/20 dark:text-violet-300'
      : pendingCount > 0
        ? 'border-amber-200 bg-amber-50/80 text-amber-700 dark:border-amber-800 dark:bg-amber-900/20 dark:text-amber-300'
        : 'border-emerald-200 bg-emerald-50/80 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-900/20 dark:text-emerald-300';

  return (
    <div className={`mx-4 mt-1.5 flex flex-shrink-0 items-center gap-2 rounded-lg border px-2.5 py-1.5 text-[11px] ${toneClass}`}>
      <Sparkles className="h-3.5 w-3.5 shrink-0" />
      <span className="font-semibold text-current">今日复习</span>
      <span className="hidden text-current/60 sm:inline">·</span>
      <span className="shrink-0">薄弱 {weakCount}</span>
      <span className="shrink-0">待复习 {pendingCount}</span>
      <span className="min-w-0 flex-1 truncate">建议：{recommendation}</span>
      {reviewPoints.length > 0 && (
        <div className="hidden min-w-0 flex-1 items-center gap-1 md:flex">
          {reviewPoints.map((item) => (
            <span
              key={item.knowledge_point}
              className="max-w-[9rem] truncate rounded-full bg-white/65 px-1.5 py-0.5 text-[10px] font-medium text-current ring-1 ring-current/10 dark:bg-slate-900/40"
              title={`${item.knowledge_point} · ${item.weak ? '薄弱' : '待复习'} · ${item.mastery}%`}
            >
              {item.knowledge_point}
            </span>
          ))}
        </div>
      )}
      {bankStatus?.status === 'error' && <AlertCircle className="h-3.5 w-3.5 shrink-0" />}
      <button
        type="button"
        onClick={handleAction}
        disabled={disabled || isWorking}
        className="inline-flex shrink-0 items-center gap-1 rounded-md bg-white/80 px-2 py-1 font-medium text-slate-700 shadow-sm ring-1 ring-black/5 transition-colors hover:bg-white disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-900/60 dark:text-slate-200 dark:hover:bg-slate-900"
      >
        {isWorking ? <Loader2 className="h-3 w-3 animate-spin" /> : <ClipboardCheck className="h-3 w-3" />}
        {actionLabel}
      </button>
    </div>
  );
}
