"""Study planner agent: supervises generated learning materials."""

from __future__ import annotations

import logging
import time
from typing import Any

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.models import RAGMessage, Task
from app.services.agent_state_service import set_agent_progress, set_agent_ready
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = {
    "run_agent",
    "reindex_session",
    "create_review_plan",
    "flag_uncertain_transcript_span",
    "suggest_note_patch",
}
_AUTO_ALLOWED_LOW_RISK_ACTIONS = {
    "run_agent",
    "reindex_session",
    "create_review_plan",
}


class StudyPlannerAgent(BaseAgent):
    """Analyze a session and recommend bounded follow-up learning actions."""

    role = "study_planner"
    task_type = "agent_study_planner"
    output_kind = "study_plan"
    prompt_name = "study_planner"

    temperature = 0.2
    max_tokens = 3500
    timeout = 90.0

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

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.monotonic()
        try:
            content_text = ctx.get_content_text_for_agent(max_length=9000)
            if not content_text.strip():
                return AgentResult(success=False, error_message="没有可用的课程内容")

            self._update_progress(ctx, 0.10, "收集学习资料状态")
            prompt_template = self.load_prompt_template()
            prompt = prompt_template.render(
                title=ctx.session.title or "未命名课次",
                keywords=ctx.get_keywords_text(),
                content=content_text,
                materials_summary=self._build_materials_summary(ctx),
                recent_conversation=self._build_recent_conversation(ctx),
                task_summary=self._build_task_summary(ctx),
            )

            self._update_progress(ctx, 0.35, "分析资料缺口与复习建议")
            raw = self.call_llm(prompt_template, prompt)

            self._update_progress(ctx, 0.80, "校验学习计划")
            plan_data = self._normalize_plan(self.parse_json(raw, repair=True))

            content_hash = _compute_session_content_hash(ctx.note)
            self.save_to_vocabulary(
                ctx,
                plan_data,
                extra={"content_hash": content_hash},
            )
            self._update_progress(ctx, 0.95, "保存学习计划")
            ctx.db.commit()

            if ctx.task:
                set_agent_ready(
                    ctx.db,
                    ctx.session_id,
                    self.role,
                    ctx.task.id,
                    content_hash=content_hash,
                    message="完成",
                    user_id=ctx.user.id,
                )

            logger.info(
                "study_planner_agent_success session_id=%s user_id=%s elapsed_ms=%s",
                ctx.session_id,
                ctx.user.id,
                int((time.monotonic() - started) * 1000),
            )
            return AgentResult(success=True, data=plan_data)
        except Exception as e:
            logger.exception("study_planner_agent_failed session_id=%s", ctx.session_id)
            try:
                ctx.db.rollback()
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
            return AgentResult(success=False, error_message=str(e))

    def _build_materials_summary(self, ctx: AgentContext) -> str:
        entries = ctx.note.vocabulary if isinstance(ctx.note.vocabulary, list) else []
        kinds = {
            item.get("kind"): item
            for item in entries
            if isinstance(item, dict) and item.get("kind")
        }
        lines = []

        transcript = kinds.get("organized_transcript")
        if transcript:
            plain_text = ((transcript.get("data") or {}).get("plain_text") or "").strip()
            lines.append(f"- 整理稿：已生成，约 {len(plain_text)} 字")
        else:
            lines.append("- 整理稿：未生成")

        mind_map = kinds.get("mind_map")
        if mind_map:
            data = mind_map.get("data") or {}
            nodes = self._count_mindmap_nodes(data.get("nodes") or [])
            relations = len(data.get("relations") or [])
            lines.append(f"- 知识导图：已生成，{nodes} 个节点，{relations} 条关系")
        else:
            lines.append("- 知识导图：未生成")

        quiz_bank = kinds.get("quiz_bank")
        if quiz_bank:
            questions = (quiz_bank.get("data") or {}).get("questions") or []
            difficulties = self._count_by_key(questions, "difficulty")
            lines.append(
                "- 题库：已生成，"
                f"{len(questions)} 道题，难度分布 {difficulties or '未知'}"
            )
        else:
            lines.append("- 题库：未生成")

        return "\n".join(lines)

    def _build_recent_conversation(self, ctx: AgentContext) -> str:
        rows = (
            ctx.db.query(RAGMessage)
            .filter(RAGMessage.session_id == ctx.session_id)
            .order_by(RAGMessage.created_at.desc())
            .limit(8)
            .all()
        )
        if not rows:
            return "（无最近问答）"
        rows = list(reversed(rows))
        lines = []
        for row in rows:
            label = "学生" if row.role == "user" else "助教"
            content = (row.content or "").strip().replace("\n", " ")
            if content:
                lines.append(f"{label}：{content[:240]}")
        return "\n".join(lines) if lines else "（无最近问答）"

    def _build_task_summary(self, ctx: AgentContext) -> str:
        rows = (
            ctx.db.query(Task)
            .filter(Task.session_id == ctx.session_id)
            .filter(Task.task_type.like("agent_%"))
            .order_by(Task.created_at.desc())
            .limit(12)
            .all()
        )
        if not rows:
            return "（无 agent 任务记录）"
        lines = []
        for task in rows:
            role = task.task_type.removeprefix("agent_")
            if role == self.role and ctx.task and task.id == ctx.task.id:
                continue
            status = task.status or "unknown"
            msg = f"，错误：{task.error_message[:120]}" if task.error_message else ""
            lines.append(f"- {role}: {status}{msg}")
        return "\n".join(lines) if lines else "（无其他 agent 任务记录）"

    @classmethod
    def _count_mindmap_nodes(cls, nodes: list[dict[str, Any]]) -> int:
        count = 0
        for node in nodes:
            if not isinstance(node, dict):
                continue
            count += 1
            children = node.get("children")
            if isinstance(children, list):
                count += cls._count_mindmap_nodes(children)
        return count

    @staticmethod
    def _count_by_key(items: list[dict[str, Any]], key: str) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            value = str(item.get(key) or "unknown")
            counts[value] = counts.get(value, 0) + 1
        return counts

    @staticmethod
    def _normalize_plan(data: dict[str, Any]) -> dict[str, Any]:
        findings = data.get("findings")
        actions = data.get("recommended_actions")
        review_plan = data.get("review_plan")
        confidence = data.get("confidence")

        if not isinstance(findings, list):
            findings = []
        if not isinstance(actions, list):
            actions = []
        if not isinstance(review_plan, list):
            review_plan = []
        if not isinstance(confidence, (int, float)):
            confidence = 0.5

        normalized = {
            "goal": str(data.get("goal") or "完善本节课的学习资料与复习路径"),
            "summary": str(data.get("summary") or ""),
            "confidence": max(0.0, min(1.0, float(confidence))),
            "findings": findings,
            "recommended_actions": StudyPlannerAgent._normalize_actions(actions),
            "review_plan": review_plan,
        }
        return normalized

    @staticmethod
    def _normalize_actions(actions: list[Any]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for item in actions:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or "").strip()
            if action not in _ALLOWED_ACTIONS:
                continue
            params = item.get("params")
            if not isinstance(params, dict):
                params = {}
            risk = str(item.get("risk") or "medium").strip().lower()
            if risk not in {"low", "medium", "high"}:
                risk = "medium"
            requires_confirmation = bool(item.get("requires_confirmation", True))
            if risk != "low" or action not in _AUTO_ALLOWED_LOW_RISK_ACTIONS:
                requires_confirmation = True
            normalized.append(
                {
                    "action": action,
                    "params": params,
                    "reason": str(item.get("reason") or ""),
                    "risk": risk,
                    "requires_confirmation": requires_confirmation,
                    "verification": str(item.get("verification") or ""),
                }
            )
        return normalized
