"""Quiz agent: generates a question bank from session notes."""

import logging
import time

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.normalizers import normalize_quiz_data
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


class QuizAgent(BaseAgent):
    """Generates a bank of single-choice questions in two batches."""

    role = "quiz"
    task_type = "agent_quiz"
    output_kind = "quiz_bank"
    prompt_name = "quiz"

    temperature = 0.4
    max_tokens = 12000

    # Number of questions per batch.
    BATCH1_COUNT = 15
    BATCH2_COUNT = 15
    MIN_TOTAL_QUESTIONS = 30

    def _call_batch(
        self,
        prompt_template,
        ctx: AgentContext,
        count: int,
        focus: str,
        existing_questions: list[str] | None = None,
        retry: bool = True,
    ) -> list[dict]:
        """Generate a single batch of questions.

        If the returned valid questions are fewer than ``count``,
        retry once with a stronger instruction. If still insufficient, raise.
        """
        focus_text = focus
        if existing_questions:
            focus_text += "\n\n已生成的题目（请避免重复以下题干）：\n" + "\n".join(
                f"{i + 1}. {q[:120]}" for i, q in enumerate(existing_questions)
            )

        prompt = prompt_template.render(
            title=ctx.session.title or "未命名课次",
            keywords=ctx.get_keywords_text(),
            content=ctx.get_content_text_for_agent(max_length=8000),
            count=count,
            focus=focus_text,
        )

        questions = self._try_generate(prompt_template, prompt, count)
        if len(questions) >= count:
            return questions[:count]

        if retry:
            logger.info(
                "quiz_agent_batch_retry session_id=%s requested=%s actual=%s",
                ctx.session_id,
                count,
                len(questions),
            )
            retry_prompt = prompt_template.render(
                title=ctx.session.title or "未命名课次",
                keywords=ctx.get_keywords_text(),
                content=ctx.get_content_text_for_agent(max_length=8000),
                count=count,
                focus=focus_text
                + f"\n\n注意：上一轮只返回了 {len(questions)} 道有效题目，"
                f"请务必严格返回 {count} 道符合要求的题目。",
            )
            retry_questions = self._try_generate(prompt_template, retry_prompt, count)
            if len(retry_questions) >= len(questions):
                questions = retry_questions

        if len(questions) < count:
            raise ValueError(
                f"AI 返回的题目数量不足: 要求 {count} 道，实际仅 {len(questions)} 道有效题目"
            )
        return questions[:count]

    def _try_generate(
        self,
        prompt_template,
        prompt: str,
        min_count: int,
    ) -> list[dict]:
        """Call LLM and parse questions; return list (may be shorter than min_count)."""
        raw = self.call_llm(prompt_template, prompt)
        batch_data = self.parse_json(raw, repair=True)
        batch_data = normalize_quiz_data(batch_data)
        questions = batch_data.get("questions", [])

        if not questions:
            return []
        if len(questions) < min_count:
            logger.warning(
                "quiz_agent_batch_fewer_questions_than_requested expected=%s actual=%s",
                min_count,
                len(questions),
            )
        return questions

    @staticmethod
    def _normalize_question(text: str) -> str:
        """Normalize question text for deduplication."""
        import re
        t = text.strip().lower()
        # Remove common punctuation and whitespace variations
        t = re.sub(r"[\s\n\r\t]+", " ", t)
        t = re.sub(r"[。？?！!，,、；;：:\"\"''（）()【】\[\]{}]+", "", t)
        return t.strip()

    def _update_progress(self, ctx: AgentContext, progress: float) -> None:
        if ctx.task:
            ctx.task.progress = progress
            ctx.db.commit()

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.monotonic()
        try:
            content_text = ctx.get_content_text_for_agent(max_length=8000)
            if not content_text.strip():
                return AgentResult(success=False, error_message="没有可用的索引内容")

            prompt_template = self.load_prompt_template()

            # Batch 1: easy questions (基础概念)
            batch1 = self._call_batch(
                prompt_template,
                ctx,
                count=self.BATCH1_COUNT,
                focus="请生成基础概念题，侧重课程中最基础、最容易理解的知识点，难度为简单。",
            )
            self._update_progress(ctx, 0.45)

            # Batch 2: medium/hard questions (细节与难点)
            batch1_texts = [q["question"] for q in batch1]
            batch2 = self._call_batch(
                prompt_template,
                ctx,
                count=self.BATCH2_COUNT,
                focus="请生成进阶题，侧重课程的细节、难点和深入理解，难度为中等或较难。",
                existing_questions=batch1_texts,
            )
            self._update_progress(ctx, 0.85)

            all_questions = batch1 + batch2

            # Hard deduplication by normalized question text
            seen_normalized: set[str] = set()
            deduped: list[dict] = []
            for q in all_questions:
                norm = self._normalize_question(q.get("question", ""))
                if norm and norm not in seen_normalized:
                    seen_normalized.add(norm)
                    deduped.append(q)
            all_questions = deduped

            if len(all_questions) < self.MIN_TOTAL_QUESTIONS:
                raise ValueError(
                    f"题库题目数量不足: 去重后共 {len(all_questions)} 道，"
                    f"至少需要 {self.MIN_TOTAL_QUESTIONS} 道"
                )

            for i, q in enumerate(all_questions, 1):
                q["id"] = f"q{i}"

            bank_data = {
                "title": "本节课测验",
                "questions": all_questions,
            }

            content_hash = _compute_session_content_hash(ctx.note)
            self.save_to_vocabulary(
                ctx,
                bank_data,
                extra={"content_hash": content_hash},
            )
            ctx.db.commit()

            logger.info(
                "quiz_agent_success session_id=%s user_id=%s elapsed_ms=%s",
                ctx.session_id,
                ctx.user.id,
                int((time.monotonic() - started) * 1000),
            )
            return AgentResult(success=True, data=bank_data)
        except Exception as e:
            logger.exception("quiz_agent_failed session_id=%s", ctx.session_id)
            ctx.db.rollback()
            return AgentResult(success=False, error_message=str(e))
