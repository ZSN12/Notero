"""Review planner agent: generates a personalized review schedule."""

import json
import logging
import time

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


class ReviewPlannerAgent(BaseAgent):
    """Generates a review plan based on notes, summary, and quiz mistakes."""

    role = "review"
    task_type = "agent_review"
    output_kind = "review_plan"
    prompt_name = "review"

    temperature = 0.4
    max_tokens = 4000

    def _extract_mistakes(self, ctx: AgentContext) -> list[dict]:
        """Collect incorrect answers from previous quiz attempts."""
        mistakes: list[dict] = []
        if not isinstance(ctx.note.vocabulary, list):
            return mistakes

        for item in ctx.note.vocabulary:
            if not isinstance(item, dict) or item.get("kind") != "quiz":
                continue
            submission = item.get("submission")
            if not isinstance(submission, dict):
                continue
            results = submission.get("results", [])
            snapshot = item.get("questions_snapshot", [])
            if not isinstance(results, list) or not isinstance(snapshot, list):
                continue

            # Build a question id -> question lookup
            questions_by_id = {q.get("id"): q for q in snapshot if isinstance(q, dict)}

            for r in results:
                if not isinstance(r, dict):
                    continue
                if r.get("correct"):
                    continue
                qid = r.get("question_id")
                question = questions_by_id.get(qid)
                if not isinstance(question, dict):
                    continue
                mistakes.append({
                    "question": question.get("question", ""),
                    "selected": r.get("selected", ""),
                    "answer": r.get("answer", ""),
                    "explanation": question.get("explanation", ""),
                })

        return mistakes

    def _normalize_plan(self, data: dict) -> dict:
        """Best-effort normalization of the review plan JSON."""
        if not isinstance(data, dict):
            raise ValueError("AI 返回的 JSON 不是对象")

        raw_plan = data.get("plan", [])
        if not isinstance(raw_plan, list):
            raise ValueError("AI 返回的 JSON 中 plan 不是列表")

        normalized_plan: list[dict] = []
        for entry in raw_plan:
            if not isinstance(entry, dict):
                continue
            raw_items = entry.get("items", [])
            items: list[dict] = []
            if isinstance(raw_items, list):
                for it in raw_items:
                    if not isinstance(it, dict):
                        continue
                    item_type = str(it.get("type", "concept"))
                    if item_type not in {"concept", "difficulty", "mistake", "summary"}:
                        item_type = "concept"
                    source_type = str(it.get("source_type", "note"))
                    if source_type not in {"transcript", "note", "ppt", "quiz"}:
                        source_type = "note"
                    items.append({
                        "type": item_type,
                        "title": str(it.get("title", "")),
                        "description": str(it.get("description", "")),
                        "source_type": source_type,
                    })

            normalized_plan.append({
                "day_offset": int(entry.get("day_offset", 1)),
                "focus": str(entry.get("focus", "复习")),
                "items": items,
            })

        if not normalized_plan:
            raise ValueError("AI 返回的复习计划中没有有效条目")

        return {
            "title": str(data.get("title", "本节课复习计划")),
            "plan": normalized_plan,
        }

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.monotonic()
        try:
            content_text = ctx.get_content_text(max_length=6000)
            if not content_text.strip():
                return AgentResult(success=False, error_message="没有可用的索引内容")

            mistakes = self._extract_mistakes(ctx)
            mistakes_text = ""
            if mistakes:
                parts = []
                for i, m in enumerate(mistakes, 1):
                    parts.append(
                        f"{i}. 题目：{m['question']}\n   学生答案：{m['selected']} | 正确答案：{m['answer']}\n   解析：{m['explanation']}"
                    )
                mistakes_text = "\n\n".join(parts)
            else:
                mistakes_text = "暂无测验错题记录。"

            prompt_template = self.load_prompt_template()
            prompt = prompt_template.render(
                title=ctx.session.title or "未命名课次",
                keywords=ctx.get_keywords_text(),
                summary="暂无摘要",
                content=content_text,
                mistakes=mistakes_text,
            )

            raw = self.call_llm(prompt_template, prompt)
            plan_data = self.parse_json(raw, repair=True)
            plan_data = self._normalize_plan(plan_data)

            content_hash = _compute_session_content_hash(ctx.note)
            self.save_to_vocabulary(ctx, plan_data, extra={"content_hash": content_hash})
            ctx.db.commit()

            logger.info(
                "review_agent_success session_id=%s user_id=%s elapsed_ms=%s mistakes=%s",
                ctx.session_id,
                ctx.user.id,
                int((time.monotonic() - started) * 1000),
                len(mistakes),
            )
            return AgentResult(success=True, data=plan_data)
        except Exception as e:
            logger.exception("review_agent_failed session_id=%s", ctx.session_id)
            ctx.db.rollback()
            return AgentResult(success=False, error_message=str(e))
