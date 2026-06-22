import { useState, useEffect, useRef } from 'react';

function useElapsedTimer(running: boolean) {
  const [elapsed, setElapsed] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (running) {
      if (!timerRef.current) {
        timerRef.current = setInterval(() => setElapsed((s) => s + 1), 1000);
      }
    } else {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      setElapsed(0);
    }
    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [running]);

  return elapsed;
}
import {
  getSessionQuizzes, generateSessionQuiz, getQuizDetail,
  submitQuizAnswers, deleteQuiz, rebuildQuizBank, getQuizBankStatus,
} from '@/services/api';
import type { QuizListItem, QuizDetail, QuizBankStatus, SessionProcessingStatus } from '@/services/api';

function deriveBankStatus(
  sessionId: string,
  processingStatus: SessionProcessingStatus | null,
): QuizBankStatus | null {
  if (!processingStatus) return null;
  const stage = processingStatus.stages.quiz_bank;
  if (!stage) return null;
  const status = stage.status === 'running'
    ? 'generating'
    : stage.status === 'fallback'
    ? 'stale'
    : stage.status as QuizBankStatus['status'];

  return {
    session_id: sessionId,
    status,
    question_count: 0,
    progress: stage.progress,
    message: stage.message,
    error: stage.error_message,
  };
}

export function useQuiz(
  sessionId: string | undefined,
  processingStatus: SessionProcessingStatus | null,
) {
  const [showQuiz, setShowQuiz] = useState(false);
  const [showQuizQA, setShowQuizQA] = useState(false);
  const [quizList, setQuizList] = useState<QuizListItem[]>([]);
  const [activeQuiz, setActiveQuiz] = useState<QuizDetail | null>(null);
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [quizAnswers, setQuizAnswers] = useState<Record<string, string>>({});
  const [quizSubmitted, setQuizSubmitted] = useState(false);
  const [quizError, setQuizError] = useState<string | null>(null);
  const [isRebuildingBank, setIsRebuildingBank] = useState(false);
  const [actualBankStatus, setActualBankStatus] = useState<QuizBankStatus | null>(null);

  const derivedBankStatus = deriveBankStatus(sessionId || '', processingStatus);
  const bankStatus = actualBankStatus
    ? {
        ...actualBankStatus,
        status: derivedBankStatus?.status === 'generating' ? derivedBankStatus.status : actualBankStatus.status,
        progress: derivedBankStatus?.status === 'generating' ? derivedBankStatus.progress : actualBankStatus.progress,
        message: derivedBankStatus?.status === 'generating' ? derivedBankStatus.message : actualBankStatus.message,
        error: derivedBankStatus?.status === 'generating' ? derivedBankStatus.error : actualBankStatus.error,
      }
    : derivedBankStatus;

  const isGenerating = isRebuildingBank || bankStatus?.status === 'generating';
  const generatingElapsed = useElapsedTimer(isGenerating);

  const loadQuizList = async () => {
    if (!sessionId) return;
    try {
      const list = await getSessionQuizzes(sessionId);
      setQuizList(list);
    } catch { /* ignore */ }
  };

  const loadBankStatus = async () => {
    if (!sessionId) return;
    try {
      const status = await getQuizBankStatus(sessionId);
      setActualBankStatus(status);
    } catch { /* ignore */ }
  };

  useEffect(() => {
    if (sessionId && showQuiz) {
      loadQuizList();
      loadBankStatus();
    }
  }, [sessionId, showQuiz]);

  useEffect(() => {
    if (!sessionId) {
      setActualBankStatus(null);
      return;
    }
    const stageStatus = processingStatus?.stages.quiz_bank?.status;
    if (!showQuiz && stageStatus !== 'ready' && stageStatus !== 'error') return;
    loadBankStatus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, showQuiz, processingStatus?.stages.quiz_bank?.status]);

  const handleRebuildBank = async () => {
    if (!sessionId) return;
    setIsRebuildingBank(true);
    setQuizError(null);
    try {
      const status = await rebuildQuizBank(sessionId);
      setActualBankStatus(status);
    } catch (err: unknown) {
      setQuizError(err instanceof Error ? err.message : '生成题库失败');
    } finally {
      setIsRebuildingBank(false);
    }
  };

  const handleGenerateQuiz = async () => {
    if (!sessionId) return;
    setIsGeneratingQuiz(true);
    setQuizError(null);
    try {
      const result = await generateSessionQuiz(sessionId);
      if ('status' in result && (result.status === 'generating')) {
        setActualBankStatus(result as QuizBankStatus);
        
        setIsGeneratingQuiz(false);
        return;
      }
      const q = result as { quiz_id: string; title: string; questions: Array<{ id: string; question: string; options: Array<{ id: string; text: string }> }> };
      setActiveQuiz({
        quiz_id: q.quiz_id,
        title: q.title,
        questions: q.questions.map(qq => ({ ...qq, options: qq.options.map(o => ({ id: o.id, text: o.text })) })),
        generated_at: undefined,
        submission: undefined,
      });
      setQuizAnswers({});
      setQuizSubmitted(false);
      await loadQuizList();
      await loadBankStatus();
    } catch (err: unknown) {
      setQuizError(err instanceof Error ? err.message : '生成测验失败');
    } finally {
      setIsGeneratingQuiz(false);
    }
  };

  const handleOpenQuiz = async (quizId: string, alreadySubmitted: boolean) => {
    if (!sessionId) return;
    try {
      const detail = await getQuizDetail(sessionId, quizId);
      setActiveQuiz(detail);
      setQuizSubmitted(alreadySubmitted);
      if (alreadySubmitted && detail.submission) {
        setQuizAnswers(detail.submission.answers);
      } else {
        setQuizAnswers({});
      }
    } catch (err: unknown) {
      setQuizError(err instanceof Error ? err.message : '加载测验失败');
    }
  };

  const handleSubmitQuiz = async () => {
    if (!sessionId || !activeQuiz) return;
    try {
      await submitQuizAnswers(sessionId, activeQuiz.quiz_id, quizAnswers);
      const detail = await getQuizDetail(sessionId, activeQuiz.quiz_id);
      setActiveQuiz(detail);
      setQuizSubmitted(true);
      await loadQuizList();
    } catch (err: unknown) {
      setQuizError(err instanceof Error ? err.message : '提交失败');
    }
  };

  const handleDeleteQuiz = async (quizId: string) => {
    if (!sessionId || !window.confirm('确定要删除这次测验吗？')) return;
    try {
      await deleteQuiz(sessionId, quizId);
      if (activeQuiz?.quiz_id === quizId) {
        setActiveQuiz(null);
        setQuizSubmitted(false);
        setQuizAnswers({});
      }
      await loadQuizList();
    } catch { /* ignore */ }
  };

  return {
    state: { showQuiz, showQuizQA, quizList, activeQuiz, isGeneratingQuiz, quizAnswers, quizSubmitted, quizError, bankStatus, isRebuildingBank, generatingElapsed },
    actions: { setShowQuiz, setShowQuizQA, setActiveQuiz, setQuizAnswers, setQuizSubmitted, setQuizError, handleRebuildBank, handleGenerateQuiz, handleOpenQuiz, handleSubmitQuiz, handleDeleteQuiz },
  };
}
