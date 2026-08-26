"""Mind map agent: generates structured knowledge maps from session notes."""

import logging
import time

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.normalizers import normalize_mind_map_data
from app.services.agent_state_service import set_agent_progress, set_agent_ready
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


class MindmapAgent(BaseAgent):
    """Generates a hierarchical knowledge map with cross-node relations."""

    role = "mindmap"
    task_type = "agent_mindmap"
    output_kind = "mind_map"
    prompt_name = "mindmap"

    temperature = 0.3
    max_tokens = 5000
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
            max_length = ctx.input_length_limit or 12000
            content_text = ctx.get_content_text_for_agent(max_length=max_length)
            if not content_text.strip():
                return AgentResult(success=False, error_message="没有可用的索引内容")

            prompt_template = self.load_prompt_template()
            render_vars = {
                "title": ctx.session.title or "未命名课次",
                "keywords": ctx.get_keywords_text(),
                "content": content_text,
                "strict_requirements": "",
            }
            if ctx.review_feedback:
                render_vars["review_feedback"] = ctx.review_feedback
            if ctx.strict_output:
                render_vars["strict_requirements"] = (
                    "\n\n## 严格输出要求\n"
                    "- 必须输出合法且完整的 JSON\n"
                    "- 不要输出 Markdown 代码块\n"
                    "- 不要输出任何 JSON 以外的文字\n"
                    "- 确保最后一个 `]` 和 `}` 都完整输出\n"
                )
            prompt = prompt_template.render(**render_vars)

            self._update_progress(ctx, 0.10, "准备课程内容")
            self._update_progress(ctx, 0.25, "调用 AI 模型生成导图")

            raw = self.call_llm(prompt_template, prompt)

            self._update_progress(ctx, 0.80, "校验导图结构")
            mind_map_data = self.parse_json(raw, repair=True)
            mind_map_data = normalize_mind_map_data(mind_map_data)

            content_hash = _compute_session_content_hash(ctx.note)
            self.save_to_vocabulary(
                ctx,
                mind_map_data,
                extra={"content_hash": content_hash},
            )
            self._update_progress(ctx, 0.95, "保存知识导图")
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
                "mindmap_agent_success session_id=%s user_id=%s elapsed_ms=%s",
                ctx.session_id,
                ctx.user.id,
                int((time.monotonic() - started) * 1000),
            )
            return AgentResult(success=True, data=mind_map_data)
        except Exception as e:
            logger.exception("mindmap_agent_failed session_id=%s", ctx.session_id)
            try:
                ctx.db.rollback()
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)
            return AgentResult(success=False, error_message=str(e))
