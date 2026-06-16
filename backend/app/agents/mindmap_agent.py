"""Mind map agent: generates structured knowledge maps from session notes."""

import logging
import time

from app.agents.base import AgentContext, AgentResult, BaseAgent
from app.agents.normalizers import normalize_mind_map_data
from app.services.vector_service import _compute_session_content_hash

logger = logging.getLogger(__name__)


class MindmapAgent(BaseAgent):
    """Generates a hierarchical knowledge map with cross-node relations."""

    role = "mindmap"
    task_type = "agent_mindmap"
    output_kind = "mind_map"
    prompt_name = "mindmap"

    temperature = 0.3
    max_tokens = 4000

    def run(self, ctx: AgentContext) -> AgentResult:
        started = time.monotonic()
        try:
            content_text = ctx.get_content_text_for_agent(max_length=6000)
            if not content_text.strip():
                return AgentResult(success=False, error_message="没有可用的索引内容")

            prompt_template = self.load_prompt_template()
            prompt = prompt_template.render(
                title=ctx.session.title or "未命名课次",
                keywords=ctx.get_keywords_text(),
                content=content_text,
            )

            raw = self.call_llm(prompt_template, prompt)
            mind_map_data = self.parse_json(raw, repair=True)
            mind_map_data = normalize_mind_map_data(mind_map_data)

            content_hash = _compute_session_content_hash(ctx.note)
            self.save_to_vocabulary(
                ctx,
                mind_map_data,
                extra={"content_hash": content_hash},
            )
            ctx.db.commit()

            logger.info(
                "mindmap_agent_success session_id=%s user_id=%s elapsed_ms=%s",
                ctx.session_id,
                ctx.user.id,
                int((time.monotonic() - started) * 1000),
            )
            return AgentResult(success=True, data=mind_map_data)
        except Exception as e:
            logger.exception("mindmap_agent_failed session_id=%s", ctx.session_id)
            ctx.db.rollback()
            return AgentResult(success=False, error_message=str(e))
