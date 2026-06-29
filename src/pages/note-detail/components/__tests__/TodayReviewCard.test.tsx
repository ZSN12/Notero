import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { ComponentProps } from 'react';
import { TodayReviewCard } from '../TodayReviewCard';
import type { QuizBankStatus, QuizMastery } from '@/services/api';

function makeQuiz(overrides: {
  bankStatus?: QuizBankStatus | null;
  mastery?: QuizMastery | null;
  isGeneratingQuiz?: boolean;
  isRebuildingBank?: boolean;
} = {}) {
  const actions = {
    setShowQuiz: vi.fn(),
    setQuizError: vi.fn(),
    setActiveQuiz: vi.fn(),
    setQuizSubmitted: vi.fn(),
    setQuizAnswers: vi.fn(),
    handleRebuildBank: vi.fn().mockResolvedValue(undefined),
    handleGenerateQuiz: vi.fn().mockResolvedValue(undefined),
  };

  return {
    state: {
      bankStatus: overrides.bankStatus ?? {
        session_id: 's1',
        status: 'ready',
        question_count: 10,
      },
      mastery: overrides.mastery ?? {
        session_id: 's1',
        knowledge_points: [],
        summary: { weak_count: 0, pending_review_count: 0 },
      },
      isGeneratingQuiz: overrides.isGeneratingQuiz ?? false,
      isRebuildingBank: overrides.isRebuildingBank ?? false,
    },
    actions,
  } as unknown as ComponentProps<typeof TodayReviewCard>['quiz'];
}

describe('TodayReviewCard', () => {
  it('shows stable state when mastery is empty', () => {
    render(<TodayReviewCard quiz={makeQuiz()} />);

    expect(screen.getByText('今日复习')).toBeInTheDocument();
    expect(screen.getByText('薄弱 0')).toBeInTheDocument();
    expect(screen.getByText('待复习 0')).toBeInTheDocument();
    expect(screen.getByText('建议：状态稳定，可继续学习')).toBeInTheDocument();
  });

  it('shows rebuild action when bank is not ready', async () => {
    const user = userEvent.setup();
    const quiz = makeQuiz({
      bankStatus: { session_id: 's1', status: 'not_generated', question_count: 0 },
      mastery: null,
    });
    render(<TodayReviewCard quiz={quiz} />);

    expect(screen.getByText('建议：先生成题库')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /生成题库/ }));

    expect(quiz.actions.setShowQuiz).toHaveBeenCalledWith(true);
    expect(quiz.actions.handleRebuildBank).toHaveBeenCalledTimes(1);
  });

  it('does not offer generation when there is no reviewable content', async () => {
    const user = userEvent.setup();
    const quiz = makeQuiz({
      bankStatus: { session_id: 's1', status: 'empty', question_count: 0 },
      mastery: null,
    });
    render(<TodayReviewCard quiz={quiz} />);

    expect(screen.getByText('建议：暂无可复习内容')).toBeInTheDocument();
    const button = screen.getByRole('button', { name: /等待内容/ });
    expect(button).toBeDisabled();
    await user.click(button);
    expect(quiz.actions.handleRebuildBank).not.toHaveBeenCalled();
  });

  it('starts variant practice when weak points exist', async () => {
    const user = userEvent.setup();
    const quiz = makeQuiz({
      mastery: {
        session_id: 's1',
        knowledge_points: [
          {
            knowledge_point: '单例模式',
            mastery: 45,
            attempts: 2,
            correct: 0,
            wrong: 2,
            pending_review: false,
            weak: true,
            last_mode: 'diagnostic',
          },
        ],
        summary: { weak_count: 2, pending_review_count: 1 },
      },
    });
    render(<TodayReviewCard quiz={quiz} />);

    expect(screen.getByText('建议：错题变式练习')).toBeInTheDocument();
    expect(screen.getByText('单例模式')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /开始变式/ }));

    expect(quiz.actions.setShowQuiz).toHaveBeenCalledWith(true);
    expect(quiz.actions.handleGenerateQuiz).toHaveBeenCalledWith('variant');
    expect(quiz.actions.setShowQuiz).not.toHaveBeenCalledWith(false);
  });

  it('starts review quiz when only pending review points exist', async () => {
    const user = userEvent.setup();
    const quiz = makeQuiz({
      mastery: {
        session_id: 's1',
        knowledge_points: [],
        summary: { weak_count: 0, pending_review_count: 3 },
      },
    });
    render(<TodayReviewCard quiz={quiz} />);

    expect(screen.getByText('建议：复习后测验')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /开始复习/ }));

    expect(quiz.actions.setShowQuiz).toHaveBeenCalledWith(true);
    expect(quiz.actions.handleGenerateQuiz).toHaveBeenCalledWith('review');
  });
});
