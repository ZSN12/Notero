import { request } from './core';
import type { QuizBankStatus, QuizListItem, QuizDetail, QuizSubmitResult, QuizMode, QuizMastery, QuizQuestion } from './types';

export async function getQuizBankStatus(sessionId: string): Promise<QuizBankStatus> {
  return request(`/api/quiz/session/${sessionId}/bank/status`, { timeoutMs: 15000 });
}

export async function rebuildQuizBank(sessionId: string): Promise<QuizBankStatus> {
  return request(`/api/quiz/session/${sessionId}/bank/rebuild`, { method: 'POST', timeoutMs: 30000 });
}

export async function getSessionQuizzes(sessionId: string): Promise<QuizListItem[]> {
  return request(`/api/quiz/session/${sessionId}`, { timeoutMs: 15000 });
}

export async function generateSessionQuiz(sessionId: string, mode: QuizMode = 'diagnostic'): Promise<{ quiz_id: string; title: string; mode?: QuizMode; questions: QuizQuestion[] } | QuizBankStatus | { status: 'no_mistakes'; message: string }> {
  return request(`/api/quiz/session/${sessionId}/generate`, {
    method: 'POST',
    body: JSON.stringify({ mode }),
    timeoutMs: 30000,
  });
}

export async function getQuizDetail(sessionId: string, quizId: string): Promise<QuizDetail> {
  return request(`/api/quiz/session/${sessionId}/${quizId}`, { timeoutMs: 15000 });
}

export async function submitQuizAnswers(sessionId: string, quizId: string, answers: Record<string, string>): Promise<QuizSubmitResult> {
  return request(`/api/quiz/session/${sessionId}/${quizId}/submit`, { method: 'POST', body: JSON.stringify({ answers }), timeoutMs: 15000 });
}

export async function getQuizMastery(sessionId: string): Promise<QuizMastery> {
  return request(`/api/quiz/session/${sessionId}/mastery`, { timeoutMs: 15000 });
}

export async function deleteQuiz(sessionId: string, quizId: string): Promise<{ session_id: string; quiz_id: string; status: string }> {
  return request(`/api/quiz/session/${sessionId}/${quizId}`, { method: 'DELETE' });
}
