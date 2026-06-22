import { X, Sparkles, Search, ClipboardCheck, ChevronDown, Loader2, AlertCircle, Trash2, CircleDot, RefreshCw } from 'lucide-react';
import RagSourceCards from '@/pages/note-detail/components/RagSourceCards';
import type { useQuiz } from '@/pages/note-detail/hooks/useQuiz';
import type { useRAG } from '@/pages/note-detail/hooks/useRAG';
import type { useVectorIndex } from '@/pages/note-detail/hooks/useVectorIndex';
import type { RAGSource } from '@/services/api';

interface QuizDrawerProps {
  quiz: ReturnType<typeof useQuiz>;
  rag: ReturnType<typeof useRAG>;
  vectorIndex: ReturnType<typeof useVectorIndex>;
  sessionId?: string;
  displayNotebook?: { id?: string; title?: string } | null;
  onRagSourceClick: (source: RAGSource, closePanel?: () => void) => void;
  getRagSourceTypeLabel: (source: RAGSource) => string;
}

export function QuizDrawer({
  quiz,
  rag,
  vectorIndex,
  sessionId,
  displayNotebook,
  onRagSourceClick,
  getRagSourceTypeLabel,
}: QuizDrawerProps) {
  if (!quiz.state.showQuiz) return null;

  const closeQuiz = () => {
    quiz.actions.setShowQuiz(false);
    quiz.actions.setShowQuizQA(false);
  };

  const ask = () => {
    rag.actions.handleRAGAsk(sessionId, displayNotebook?.id, vectorIndex.actions.ensureIndexed);
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" onClick={closeQuiz} />

      {/* Left QA Panel */}
      {quiz.state.showQuizQA && (
        <div className="relative z-10 w-full max-w-lg h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col border-r border-slate-200 dark:border-slate-700">
          {/* Header */}
          <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-violet-500" />
              <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">AI 答疑</h2>
            </div>
            <button
              onClick={() => quiz.actions.setShowQuizQA(false)}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Search input */}
          <div className="p-4 border-b border-slate-200 dark:border-slate-700 space-y-3">
            <div className="flex items-center gap-2">
              <input
                value={rag.state.searchQuery}
                onChange={(e) => rag.actions.setSearchQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') ask();
                }}
                placeholder="输入问题，AI 将基于课堂资料回答..."
                className="flex-1 text-sm bg-transparent outline-none text-slate-700 dark:text-slate-200 placeholder:text-slate-400"
                autoFocus
              />
              <button
                onClick={ask}
                disabled={rag.state.isAskingRAG}
                className="px-3 py-1.5 text-xs font-medium text-white bg-violet-500 rounded-lg hover:bg-violet-600 disabled:opacity-50"
              >
                {rag.state.isAskingRAG ? '...' : '提问'}
              </button>
            </div>
            <div className="flex items-center justify-between">
              <div className="flex items-center rounded-lg border border-slate-200 dark:border-slate-600 overflow-hidden">
                <button
                  onClick={() => rag.actions.setSearchScope('session')}
                  className={`px-2 py-1 text-[10px] font-medium transition-colors ${
                    rag.state.searchScope === 'session'
                      ? 'bg-blue-500 text-white'
                      : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  本课次
                </button>
                <button
                  onClick={() => rag.actions.setSearchScope('notebook')}
                  className={`px-2 py-1 text-[10px] font-medium transition-colors ${
                    rag.state.searchScope === 'notebook'
                      ? 'bg-blue-500 text-white'
                      : 'text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700'
                  }`}
                >
                  本课程
                </button>
              </div>
              <span className="text-[10px] text-slate-400">基于测验和课次内容答疑</span>
            </div>
            {rag.state.ragError && <div className="text-xs text-red-500">{rag.state.ragError}</div>}
            {rag.state.ragStatus && (
              <div className="text-xs text-violet-500 flex items-center gap-1">
                <Loader2 className="w-3 h-3 animate-spin" />
                {rag.state.ragStatus}
              </div>
            )}
          </div>

          {/* Answer area */}
          <div className="flex-1 overflow-y-auto p-4">
            {rag.state.ragAnswer || rag.state.ragSources.length > 0 ? (
              <div className="space-y-3">
                {rag.state.ragAnswer ? (
                  <div className="text-sm text-slate-700 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
                    {rag.state.ragAnswer}
                  </div>
                ) : (
                  <div className="text-xs text-slate-400">
                    AI 暂时没有生成回答，但已检索到相关课堂来源。
                  </div>
                )}
                {rag.state.ragSources.length > 0 && (
                  <div className="pt-3 border-t border-slate-100 dark:border-slate-700">
                    <p className="text-[10px] text-slate-400 mb-2">参考来源</p>
                    <RagSourceCards
                      sources={rag.state.ragSources}
                      onSourceClick={onRagSourceClick}
                      getSourceTypeLabel={getRagSourceTypeLabel}
                      onClose={() => quiz.actions.setShowQuizQA(false)}
                    />
                  </div>
                )}
              </div>
            ) : (
              <div className="h-full flex flex-col items-center justify-center text-slate-400 gap-3">
                <Sparkles className="w-10 h-10 opacity-30" />
                <p className="text-sm">
                  {rag.state.isAskingRAG ? '正在思考中...' : '输入问题，AI 将基于课堂资料回答'}
                </p>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Right Quiz Panel */}
      <div
        className="relative w-full max-w-2xl h-full bg-white dark:bg-slate-800 shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <ClipboardCheck className="w-5 h-5 text-emerald-500" />
            <h2 className="text-base font-semibold text-slate-800 dark:text-slate-200">课次测验</h2>
          </div>
          <div className="flex items-center gap-2">
            {quiz.state.activeQuiz && (
              <>
                <button
                  onClick={() => {
                    quiz.actions.setActiveQuiz(null);
                    quiz.actions.setQuizSubmitted(false);
                    quiz.actions.setQuizAnswers({});
                    quiz.actions.setShowQuizQA(false);
                  }}
                  className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                  title="返回列表"
                >
                  <ChevronDown className="w-4 h-4 rotate-90" />
                </button>
                <button
                  onClick={() => quiz.actions.setShowQuizQA(!quiz.state.showQuizQA)}
                  className={`p-2 rounded-lg transition-colors ${
                    quiz.state.showQuizQA
                      ? 'text-blue-600 bg-blue-50 dark:bg-blue-900/20'
                      : 'text-slate-400 hover:text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-900/20'
                  }`}
                  title="测验答疑"
                >
                  <Search className="w-4 h-4" />
                </button>
              </>
            )}
            <button
              onClick={closeQuiz}
              className="p-2 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto">
          {quiz.state.quizError && (
            <div className="mx-5 mt-4 p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-sm text-red-600 dark:text-red-400 flex items-center gap-2">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              {quiz.state.quizError}
              <button
                onClick={() => quiz.actions.setQuizError(null)}
                className="ml-auto text-red-400 hover:text-red-600"
              >
                <X className="w-3 h-3" />
              </button>
            </div>
          )}

          {quiz.state.activeQuiz ? (
            /* Active Quiz View */
            <div className="p-5">
              <h3 className="text-lg font-bold text-slate-800 dark:text-slate-100 mb-4">
                {quiz.state.activeQuiz.title}
              </h3>

              {quiz.state.quizSubmitted && quiz.state.activeQuiz.submission ? (
                /* Results View */
                <div>
                  <div className="flex items-center gap-4 mb-6 p-4 rounded-xl bg-slate-50 dark:bg-slate-700/50">
                    <div className="text-center">
                      <div
                        className={`text-3xl font-bold ${
                          quiz.state.activeQuiz.submission.percentage >= 60 ? 'text-emerald-500' : 'text-red-500'
                        }`}
                      >
                        {quiz.state.activeQuiz.submission.percentage}%
                      </div>
                      <div className="text-xs text-slate-400 mt-1">正确率</div>
                    </div>
                    <div className="text-center">
                      <div className="text-2xl font-bold text-slate-700 dark:text-slate-200">
                        {quiz.state.activeQuiz?.submission?.score}/{quiz.state.activeQuiz?.submission?.total}
                      </div>
                      <div className="text-xs text-slate-400 mt-1">答对题数</div>
                    </div>
                  </div>

                  <div className="space-y-4">
                    {quiz.state.activeQuiz?.questions.map((q, idx) => {
                      const result = quiz.state.activeQuiz?.submission?.results.find(
                        (r) => r.question_id === q.id,
                      );
                      const isCorrect = result?.correct;
                      return (
                        <div
                          key={q.id}
                          className={`p-4 rounded-xl border ${
                            isCorrect
                              ? 'border-emerald-200 dark:border-emerald-800 bg-emerald-50/50 dark:bg-emerald-900/10'
                              : 'border-red-200 dark:border-red-800 bg-red-50/50 dark:bg-red-900/10'
                          }`}
                        >
                          <div className="flex items-start gap-2 mb-2">
                            <span
                              className={`text-xs font-bold mt-0.5 ${
                                isCorrect ? 'text-emerald-500' : 'text-red-500'
                              }`}
                            >
                              {isCorrect ? '✓' : '✗'}
                            </span>
                            <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
                              {idx + 1}. {q.question}
                            </span>
                          </div>
                          <div className="space-y-1.5 ml-5">
                            {q.options.map((opt) => {
                              const isSelected = result?.selected === opt.id;
                              const isAnswer = q.answer === opt.id;
                              return (
                                <div
                                  key={opt.id}
                                  className={`text-xs px-2.5 py-1.5 rounded-lg ${
                                    isAnswer
                                      ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 font-medium'
                                      : isSelected
                                        ? 'bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 line-through'
                                        : 'text-slate-500 dark:text-slate-400'
                                  }`}
                                >
                                  <span className="font-medium mr-1">{opt.id}.</span> {opt.text}
                                  {opt.explanation && <span className="ml-1 opacity-70">— {opt.explanation}</span>}
                                </div>
                              );
                            })}
                          </div>
                          {q.explanation && (
                            <div className="mt-2 ml-5 text-xs text-slate-500 dark:text-slate-400">
                              <span className="font-medium">解析：</span>
                              {q.explanation}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                /* Taking Quiz View */
                <div>
                  <div className="space-y-5">
                    {quiz.state.activeQuiz?.questions.map((q, idx) => (
                      <div key={q.id} className="p-4 rounded-xl border border-slate-200 dark:border-slate-600">
                        <p className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-3">
                          <span className="text-emerald-500 mr-1">{idx + 1}.</span>
                          {q.question}
                        </p>
                        <div className="space-y-2">
                          {q.options.map((opt) => (
                            <button
                              key={opt.id}
                              onClick={() =>
                                quiz.actions.setQuizAnswers((prev) => ({ ...prev, [q.id]: opt.id }))
                              }
                              className={`w-full text-left px-3 py-2.5 rounded-lg text-sm transition-colors flex items-center gap-2 ${
                                quiz.state.quizAnswers[q.id] === opt.id
                                  ? 'bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700'
                                  : 'bg-slate-50 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border border-transparent hover:bg-slate-100 dark:hover:bg-slate-600'
                              }`}
                            >
                              <CircleDot
                                className={`w-4 h-4 flex-shrink-0 ${
                                  quiz.state.quizAnswers[q.id] === opt.id
                                    ? 'text-emerald-500'
                                    : 'text-slate-300 dark:text-slate-500'
                                }`}
                              />
                              <span className="font-medium mr-1">{opt.id}.</span>
                              {opt.text}
                            </button>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="mt-6 flex items-center justify-between">
                    <span className="text-xs text-slate-400">
                      已答 {Object.keys(quiz.state.quizAnswers).length}/
                      {quiz.state.activeQuiz.questions.length} 题
                    </span>
                    <button
                      onClick={quiz.actions.handleSubmitQuiz}
                      disabled={
                        Object.keys(quiz.state.quizAnswers).length < quiz.state.activeQuiz.questions.length
                      }
                      className="px-5 py-2.5 text-sm font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                      提交答案
                    </button>
                  </div>
                </div>
              )}
            </div>
          ) : (
            /* Quiz List View */
            <div className="p-5">
              {/* Bank Status Banner */}
              {quiz.state.bankStatus && quiz.state.bankStatus.status !== 'ready' && (
                <div
                  className={`mb-4 p-3 rounded-lg text-sm flex items-center gap-2 ${
                    quiz.state.bankStatus.status === 'generating'
                      ? 'bg-blue-50 dark:bg-blue-900/20 text-blue-600 dark:text-blue-400'
                      : quiz.state.bankStatus.status === 'queued'
                        ? 'bg-amber-50 dark:bg-amber-900/20 text-amber-600 dark:text-amber-400'
                        : quiz.state.bankStatus.status === 'error'
                          ? 'bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400'
                          : quiz.state.bankStatus.status === 'empty'
                            ? 'bg-slate-50 dark:bg-slate-700 text-slate-500'
                            : 'bg-slate-50 dark:bg-slate-700 text-slate-500'
                  }`}
                >
                  {quiz.state.bankStatus.status === 'generating' && (
                    <Loader2 className="w-4 h-4 animate-spin flex-shrink-0" />
                  )}
                  {quiz.state.bankStatus.status === 'error' && <AlertCircle className="w-4 h-4 flex-shrink-0" />}
                  <span>
                    {quiz.state.bankStatus.status === 'generating' && '题库生成中，请稍候...'}
                    {quiz.state.bankStatus.status === 'queued' && (quiz.state.bankStatus.message || '题库等待前置任务执行...')}
                    {quiz.state.bankStatus.status === 'error' && `题库生成失败: ${quiz.state.bankStatus.error || '未知错误'}`}
                    {quiz.state.bankStatus.status === 'empty' && '当前课次没有可生成的内容'}
                    {quiz.state.bankStatus.status === 'not_generated' && '尚未生成题库'}
                  </span>
                  {(quiz.state.bankStatus.status === 'error' || quiz.state.bankStatus.status === 'not_generated') && (
                    <button
                      onClick={quiz.actions.handleRebuildBank}
                      disabled={quiz.state.isRebuildingBank}
                      className="ml-auto px-2.5 py-1 text-xs font-medium text-white bg-blue-500 rounded hover:bg-blue-600 disabled:opacity-50 flex items-center gap-1"
                    >
                      {quiz.state.isRebuildingBank && <Loader2 className="w-3 h-3 animate-spin" />}
                      生成题库
                    </button>
                  )}
                </div>
              )}

              {/* Rebuild Bank Button (when bank is ready) */}
              {quiz.state.bankStatus && quiz.state.bankStatus.status === 'ready' && (
                <div className="mb-4 flex items-center justify-between p-3 rounded-lg bg-emerald-50 dark:bg-emerald-900/10 text-sm">
                  <span className="text-emerald-600 dark:text-emerald-400">
                    题库已就绪 ({quiz.state.bankStatus.question_count} 题)
                  </span>
                  <button
                    onClick={quiz.actions.handleRebuildBank}
                    disabled={quiz.state.isRebuildingBank}
                    className="px-2.5 py-1 text-xs font-medium text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-900/20 rounded hover:bg-amber-100 dark:hover:bg-amber-900/40 disabled:opacity-50 flex items-center gap-1"
                    title="重新生成题库会调用 AI"
                  >
                    {quiz.state.isRebuildingBank ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}
                    重新生成题库
                  </button>
                </div>
              )}

              {quiz.state.isGeneratingQuiz ? (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-3">
                  <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
                  <p className="text-sm">正在从题库抽取题目...</p>
                </div>
              ) : quiz.state.quizList.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-slate-400 gap-4">
                  <ClipboardCheck className="w-10 h-10 opacity-30" />
                  <p className="text-sm">尚未开始测验</p>
                  <button
                    onClick={quiz.actions.handleGenerateQuiz}
                    disabled={!quiz.state.bankStatus || quiz.state.bankStatus.status !== 'ready'}
                    className="px-4 py-2 text-sm font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600 disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-2"
                  >
                    开始测验
                  </button>
                </div>
              ) : (
                <div>
                  <div className="flex items-center justify-between mb-4">
                    <span className="text-sm text-slate-500">历史测验</span>
                    <button
                      onClick={quiz.actions.handleGenerateQuiz}
                      disabled={
                        quiz.state.isGeneratingQuiz ||
                        !quiz.state.bankStatus ||
                        quiz.state.bankStatus.status !== 'ready'
                      }
                      className="px-3 py-1.5 text-xs font-medium text-white bg-emerald-500 rounded-lg hover:bg-emerald-600 disabled:opacity-50 flex items-center gap-1"
                    >
                      {quiz.state.isGeneratingQuiz ? <Loader2 className="w-3 h-3 animate-spin" /> : null}
                      开始新测验
                    </button>
                  </div>
                  <div className="space-y-2">
                    {quiz.state.quizList.map((q) => (
                      <div
                        key={q.quiz_id}
                        className="flex items-center justify-between p-3 rounded-xl border border-slate-200 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors"
                      >
                        <button
                          onClick={() => quiz.actions.handleOpenQuiz(q.quiz_id, q.submitted)}
                          className="flex-1 text-left"
                        >
                          <div className="text-sm font-medium text-slate-700 dark:text-slate-200">{q.title}</div>
                          <div className="text-xs text-slate-400 mt-0.5">
                            {q.question_count} 题 · {q.submitted ? '已完成' : '未完成'}
                            {q.score && ` · ${q.score.percentage}%`}
                            {q.generated_at && ` · ${new Date(q.generated_at).toLocaleDateString()}`}
                          </div>
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            quiz.actions.handleDeleteQuiz(q.quiz_id);
                          }}
                          className="p-1.5 rounded-lg text-slate-300 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                          title="删除"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
