"""Quiz agent: generates a question bank from session notes."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.normalizers import normalize_quiz_data
from app.services.agent_state_service import set_agent_progress, set_agent_ready
from app.services.vector_service import _compute_session_content_hash
from app.services.web_search_service import format_web_results, search_web

logger = logging.getLogger(__name__)


class QuizAgent(BaseAgent):
    """Generates a bank of single-choice questions in two batches."""

    role = "quiz"
    task_type = "agent_quiz"
    output_kind = "quiz_bank"
    prompt_name = "quiz"

    temperature = 0.4
    max_tokens = 8000
    timeout = 90.0

    # Number of questions per batch.
    BATCH1_COUNT = 15
    BATCH2_COUNT = 15
    MIN_TOTAL_QUESTIONS = 30

    def _update_progress(self, ctx: AgentContext, progress: float, message: str) -> None:
        if ctx.task:
            set_agent_progress(
                ctx.db,
                ctx.session_id,
                self.role,
                progress,
                message=message,
                task_id=ctx.task.id,
                user_id=ctx.user.id,
            )

    def _call_batch(
        self,
        prompt_template,
        session_id: str,
        title: str,
        keywords: str,
        content_text: str,
        count: int,
        focus: str,
        existing_questions: list[str] | None = None,
        retry: bool = True,
    ) -> list[dict]:
        """Generate a single batch of questions.

        ``session_id``/``title``/``keywords``/``content_text`` must be plain
        strings pre-computed in the caller thread; this method must NOT touch
        ``AgentContext.db`` because it may run inside a ``ThreadPoolExecutor``.

        Returns whatever valid questions the model produced; callers decide
        whether to raise or continue with fewer questions.
        """
        focus_text = focus
        if existing_questions:
            focus_text += "\n\n已生成的题目（请避免重复以下题干）：\n" + "\n".join(
                f"{i + 1}. {q[:120]}" for i, q in enumerate(existing_questions)
            )

        prompt = prompt_template.render(
            title=title,
            keywords=keywords,
            content=content_text,
            count=count,
            focus=focus_text,
        )

        questions = self._try_generate(prompt_template, prompt, count)
        if len(questions) >= count:
            return questions[:count]

        if retry:
            logger.info(
                "quiz_agent_batch_retry session_id=%s requested=%s actual=%s",
                session_id,
                count,
                len(questions),
            )
            retry_prompt = prompt_template.render(
                title=title,
                keywords=keywords,
                content=content_text,
                count=count,
                focus=focus_text
                + f"\n\n注意：上一轮只返回了 {len(questions)} 道有效题目，"
                f"请务必严格返回 {count} 道符合要求的题目。",
            )
            retry_questions = self._try_generate(prompt_template, retry_prompt, count)
            if len(retry_questions) >= len(questions):
                questions = retry_questions

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

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.monotonic()
        warning_message: str | None = None

        try:
            content_text = ctx.get_content_text_for_agent(max_length=8000)
            if not content_text.strip():
                return AgentResult(success=False, error_message="没有可用的索引内容")

            prompt_template = self.load_prompt_template()
            self._update_progress(ctx, 0.10, "准备课程内容")

            # Pre-compute all ORM-dependent values in the caller thread; the
            # worker threads must not touch AgentContext.db (SQLAlchemy Session
            # is not thread-safe).
            session_id = ctx.session_id
            title = ctx.session.title or "未命名课次"
            keywords = ctx.get_keywords_text()

            # The two independent difficulty bands are requested concurrently.
            # They use distinct prompts; global deduplication and a bounded fill
            # request below handle any overlap.
            self._update_progress(ctx, 0.20, "题库生成中（0/30 题）")
            batch_specs = {
                "easy": (
                    self.BATCH1_COUNT,
                    "请生成基础概念题，侧重课程中最基础、最容易理解的知识点，难度为简单。",
                ),
                "advanced": (
                    self.BATCH2_COUNT,
                    "请生成进阶题，侧重课程的细节、难点和深入理解，难度为中等或较难。",
                ),
            }
            batches: dict[str, list[dict]] = {"easy": [], "advanced": []}
            completed = 0
            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="quiz-batch") as executor:
                futures = {
                    executor.submit(
                        self._call_batch,
                        prompt_template,
                        session_id,
                        title,
                        keywords,
                        content_text,
                        count,
                        focus,
                    ): name
                    for name, (count, focus) in batch_specs.items()
                }
                for future in as_completed(futures):
                    name = futures[future]
                    try:
                        batches[name] = future.result()
                    except Exception as batch_error:
                        logger.warning(
                            "quiz_agent_batch_failed session_id=%s batch=%s error=%s",
                            ctx.session_id,
                            name,
                            batch_error,
                        )
                    completed += 1
                    generated = sum(len(items) for items in batches.values())
                    progress = 0.20 + (0.55 * completed / len(batch_specs))
                    self._update_progress(
                        ctx,
                        progress,
                        f"题库生成中（{min(generated, 30)}/30 题）",
                    )

            batch1 = batches["easy"]
            batch2 = batches["advanced"]
            if not batch1 and not batch2:
                raise ValueError("题库两批生成均失败，请稍后重试")

            all_questions = batch1 + batch2

            # Hard deduplication by normalized question text
            self._update_progress(ctx, 0.85, "题目去重与补全")
            seen_normalized: set[str] = set()
            deduped: list[dict] = []
            for q in all_questions:
                norm = self._normalize_question(q.get("question", ""))
                if norm and norm not in seen_normalized:
                    seen_normalized.add(norm)
                    deduped.append(q)
            all_questions = deduped

            self._update_progress(ctx, 0.90, "正在补充缺少题目")

            # If we still lack questions, try a fill batch focused on remaining angles.
            if 0 < len(all_questions) < self.MIN_TOTAL_QUESTIONS:
                missing = self.MIN_TOTAL_QUESTIONS - len(all_questions)
                existing_texts = [q["question"] for q in all_questions]
                fill = self._call_batch(
                    prompt_template,
                    session_id,
                    title,
                    keywords,
                    content_text,
                    count=missing,
                    focus=(
                        "请补充生成与已有题目不重复的单选题，"
                        "可从概念定义、应用场景、对比区别、步骤流程、易错点等角度扩展。"
                    ),
                    existing_questions=existing_texts,
                    retry=False,
                )
                for q in fill:
                    norm = self._normalize_question(q.get("question", ""))
                    if norm and norm not in seen_normalized:
                        seen_normalized.add(norm)
                        deduped.append(q)
                all_questions = deduped

            if 0 < len(all_questions) < self.MIN_TOTAL_QUESTIONS:
                self._update_progress(ctx, 0.94, "联网搜索补充题目素材")
                search_query = f"{title} {keywords} 核心概念 例题 易错点"
                web_results = search_web(search_query, max_results=3)
                web_context = format_web_results(web_results, max_chars=3500)
                if web_context:
                    missing = self.MIN_TOTAL_QUESTIONS - len(all_questions)
                    existing_texts = [q["question"] for q in all_questions]
                    augmented_content = (
                        f"{content_text}\n\n"
                        "--- 联网补充资料（仅用于补充背景；题目必须围绕本课知识点）---\n"
                        f"{web_context}"
                    )
                    fill = self._call_batch(
                        prompt_template,
                        session_id,
                        title,
                        keywords,
                        augmented_content,
                        count=missing,
                        focus=(
                            "请利用联网补充资料扩展本课知识点的考法，但不要生成脱离本课内容的题目。"
                            "优先补充应用场景、对比区别、易错点和定义辨析题。"
                            "若题目依据联网资料，请在 source.source_type 使用 web，并在 snippet 中写明网页标题或摘要。"
                        ),
                        existing_questions=existing_texts,
                        retry=False,
                    )
                    for q in fill:
                        norm = self._normalize_question(q.get("question", ""))
                        if norm and norm not in seen_normalized:
                            seen_normalized.add(norm)
                            deduped.append(q)
                    all_questions = deduped

            if len(all_questions) < self.MIN_TOTAL_QUESTIONS:
                warning_message = f"题量不足（仅生成 {len(all_questions)} 题）"
                logger.warning(
                    "quiz_agent_insufficient_questions session_id=%s total=%s",
                    ctx.session_id,
                    len(all_questions),
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
                extra={"content_hash": content_hash, "message": warning_message},
            )
            ctx.db.commit()

            if ctx.task:
                set_agent_ready(
                    ctx.db,
                    ctx.session_id,
                    self.role,
                    ctx.task.id,
                    content_hash=content_hash,
                    message=warning_message or "完成",
                    user_id=ctx.user.id,
                )

            logger.info(
                "quiz_agent_success session_id=%s user_id=%s questions=%s warning=%s elapsed_ms=%s",
                ctx.session_id,
                ctx.user.id,
                len(all_questions),
                warning_message,
                int((time.monotonic() - started) * 1000),
            )
            return AgentResult(success=True, data=bank_data, warning_message=warning_message)
        except Exception as e:
            logger.exception("quiz_agent_failed session_id=%s", ctx.session_id)
            try:
                ctx.db.rollback()
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
            return AgentResult(success=False, error_message=str(e))
