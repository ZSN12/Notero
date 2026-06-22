"""RAG (Retrieval-Augmented Generation) API.

User asks a question → retrieve relevant chunks from vector index →
construct prompt with context → stream answer from DeepSeek.
"""

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import User, Notebook, RAGMessage
from app.services import vector_service
from app.services.prompt_loader import load_prompt
from app.services.session_service import get_user_session
from app.config import DEEPSEEK_MODEL
from app.middleware.metrics import observe_llm_call
from app.agents.rag_context_agent import RAGContextAgent
from app.agents.rag_memory_agent import RAGMemoryAgent
from app.core.llm import ChatMessage, get_default_chat_provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])


class RAGAskRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    notebook_id: Optional[str] = None
    top_k: int = Field(5)


class SourceItem(BaseModel):
    chunk_id: str
    notebook_id: str
    notebook_title: str
    session_id: str
    session_title: str
    source_type: str
    snippet: str
    score: float
    page: Optional[int | str] = None
    block_id: Optional[str] = None
    chunk_index: Optional[int] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RAGAskResponse(BaseModel):
    answer: str
    sources: list[SourceItem]


class RAGMessageOut(BaseModel):
    id: str
    session_id: str
    notebook_id: str
    role: str
    content: str
    sources: list[SourceItem] = Field(default_factory=list)
    created_at: str

    class Config:
        from_attributes = True


_context_agent: Optional[RAGContextAgent] = None
_memory_agent: Optional[RAGMemoryAgent] = None


def _get_context_agent() -> RAGContextAgent:
    global _context_agent
    if _context_agent is None:
        _context_agent = RAGContextAgent()
    return _context_agent


def _get_memory_agent() -> RAGMemoryAgent:
    global _memory_agent
    if _memory_agent is None:
        _memory_agent = RAGMemoryAgent()
    return _memory_agent


def _call_llm_stream(prompt: str, system: str):
    """Stream LLM response via the unified provider abstraction."""
    import time

    provider = get_default_chat_provider()
    if not provider.available:
        yield f"data: {json.dumps({'type': 'error', 'detail': 'AI 问答服务不可用，但索引资料仍可检索'}, ensure_ascii=False)}\n\n"
        return

    start = time.perf_counter()
    try:
        for text in provider.chat_stream(
            messages=[
                ChatMessage(role="system", content=system),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.3,
        ):
            if text:
                yield f"data: {json.dumps({'type': 'chunk', 'text': text}, ensure_ascii=False)}\n\n"

        observe_llm_call(DEEPSEEK_MODEL, time.perf_counter() - start, success=True)
    except Exception as e:
        observe_llm_call(DEEPSEEK_MODEL, time.perf_counter() - start, success=False)
        logger.exception("rag_llm_stream_failed")
        yield f"data: {json.dumps({'type': 'error', 'detail': f'AI 问答服务不可用，但索引资料仍可检索：{str(e)}'}, ensure_ascii=False)}\n\n"


def _source_payload(result: dict) -> dict:
    metadata = result.get("metadata") or {}
    source_type = result.get("source_type") or metadata.get("block_type") or "unknown"
    block_type = metadata.get("block_type")
    if source_type == "layout" and block_type:
        source_type = block_type
    page = metadata.get("page")
    block_id = metadata.get("block_id") or result.get("source_id")
    chunk_index = metadata.get("chunk_index")
    if chunk_index is None:
        chunk_index = metadata.get("chunk_in_source")

    return {
        "chunk_id": result["chunk_id"],
        "notebook_id": result["notebook_id"],
        "notebook_title": result["notebook_title"],
        "session_id": result["session_id"],
        "session_title": result["session_title"],
        "source_type": source_type,
        "snippet": result["snippet"],
        "score": result["score"],
        "page": page,
        "block_id": block_id,
        "chunk_index": chunk_index,
        "metadata": metadata,
    }


def _serialize_sources(sources: list[dict]) -> list[SourceItem]:
    return [
        SourceItem(**{k: s.get(k) for k in SourceItem.model_fields.keys() if k in s})
        for s in sources
    ]


def _load_history(db: Session, session_id: str, limit: int = 12) -> list[dict[str, Any]]:
    rows = (
        db.query(RAGMessage)
        .filter(RAGMessage.session_id == session_id)
        .order_by(RAGMessage.created_at.desc())
        .limit(limit)
        .all()
    )
    rows = list(reversed(rows))
    return [{"role": r.role, "content": r.content, "is_summary": r.is_summary} for r in rows]


def _build_conversation_context(summary: str, history: list[dict[str, Any]]) -> str:
    if not history and not summary:
        return "（无）"
    parts = []
    if summary:
        parts.append(f"已讨论主题摘要：{summary}")
    if history:
        parts.append("## 最近对话")
        for msg in history[-6:]:
            label = "学生" if msg["role"] == "user" else "助教"
            parts.append(f"{label}：{msg['content']}")
    return "\n".join(parts)


@router.post("/ask")
def rag_ask(
    req: RAGAskRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Ask a question based on local knowledge (notes + transcripts + PPTs).

    Returns SSE stream:
      data: {"type":"status","message":"检索中..."}
      data: {"type":"chunk","text":"..."}
      data: {"type":"sources","sources":[...]}
      data: {"type":"done"}
    """
    if not req.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    if req.top_k < 1 or req.top_k > 50:
        raise HTTPException(status_code=400, detail="top_k must be between 1 and 50")

    # Validate ownership (both must be valid if provided)
    nb = None
    if req.notebook_id:
        nb = db.query(Notebook).filter(
            Notebook.id == req.notebook_id,
            Notebook.user_id == current_user.id,
        ).first()
        if not nb:
            raise HTTPException(status_code=404, detail="Notebook not found")
    sess = None
    if req.session_id:
        sess = get_user_session(db, req.session_id, current_user.id)
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if req.notebook_id and sess.notebook_id != req.notebook_id:
            raise HTTPException(status_code=404, detail="Session not found in notebook")

    # Determine the canonical ids to use for persistence / retrieval
    notebook_id = req.notebook_id or (sess.notebook_id if sess else None)
    session_id = req.session_id

    # Step 1: Build contextualized query from conversation history
    history: list[dict[str, Any]] = []
    standalone_query = req.query
    context_summary = ""
    if session_id:
        history = _load_history(db, session_id)
        if history:
            result = _get_context_agent().contextualize(history, req.query)
            standalone_query = result.get("standalone_query") or req.query
            context_summary = result.get("context_summary") or ""

    # Step 2: Retrieve relevant chunks
    try:
        results = vector_service.search_vectors(
            user=current_user,
            query=standalone_query,
            session_id=req.session_id,
            notebook_id=req.notebook_id,
            limit=req.top_k,
            db=db,
        )
    except Exception as e:
        logger.exception("rag_search_failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    # Step 3: Build context from retrieved chunks
    context_lines = []
    for i, r in enumerate(results, 1):
        source = _source_payload(r)
        location = []
        if source.get("page") not in (None, ""):
            location.append(f"PPT第{source['page']}页")
        if source.get("block_id"):
            location.append(f"块ID:{source['block_id']}")
        if source.get("chunk_index") is not None:
            location.append(f"片段:{source['chunk_index']}")
        location_text = f"；位置：{'，'.join(location)}" if location else ""
        context_lines.append(
            f"[{i}] 来源：{source['session_title']}（{source['source_type']}）{location_text}\n"
            f"内容：{source['snippet']}\n"
        )
    context = "\n".join(context_lines) if context_lines else "（未找到相关课堂资料）"

    # Get course info
    course_title = "未知课程"
    keywords = "无"
    if req.notebook_id:
        course_title = nb.title if nb else "未知课程"
    elif req.session_id and results:
        course_title = results[0].get("notebook_title", "未知课程")

    conversation_context = _build_conversation_context(context_summary, history)

    # Step 4: Render prompt
    prompt_template = load_prompt("rag_qa")
    prompt = prompt_template.render(
        course_title=course_title,
        keywords=keywords,
        context=context,
        conversation_context=conversation_context,
        query=req.query,
    )

    # Step 5: Stream response
    def generate():
        yield f"data: {json.dumps({'type': 'status', 'message': f'找到 {len(results)} 条相关资料'}, ensure_ascii=False)}\n\n"

        # Derive the most recent conversation summary before adding the new turn.
        prior_summary = ""
        for h in reversed(history):
            if h.get("is_summary"):
                prior_summary = h["content"]
                break

        # Persist the user message before streaming the answer
        if session_id and notebook_id:
            db.add(
                RAGMessage(
                    session_id=session_id,
                    notebook_id=notebook_id,
                    role="user",
                    content=req.query,
                    sources=[],
                    is_summary=False,
                )
            )
            db.commit()

        # Stream LLM answer
        answer_text = ""
        for event in _call_llm_stream(prompt, prompt_template.system):
            yield event
            try:
                payload = json.loads(event[len("data: "):])
                if payload.get("type") == "chunk" and payload.get("text"):
                    answer_text += payload["text"]
            except Exception:
                logger.warning("suppressed_exception", exc_info=True)

        # Send sources
        sources = [_source_payload(r) for r in results]
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

        # Persist assistant message and a condensed summary for future turns
        if session_id and notebook_id:
            db.add(
                RAGMessage(
                    session_id=session_id,
                    notebook_id=notebook_id,
                    role="assistant",
                    content=answer_text,
                    sources=sources,
                    is_summary=False,
                )
            )

            turn_summary = _get_memory_agent().summarize_turn(
                prior_summary=prior_summary,
                user_query=req.query,
                assistant_answer=answer_text,
                sources=sources,
            )
            if turn_summary:
                db.add(
                    RAGMessage(
                        session_id=session_id,
                        notebook_id=notebook_id,
                        role="summary",
                        content=turn_summary,
                        sources=[],
                        is_summary=True,
                    )
                )
            db.commit()

        yield f"data: {json.dumps({'type': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/messages", response_model=list[RAGMessageOut])
def list_rag_messages(
    session_id: str = Query(...),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List RAG conversation messages for a session (excludes hidden summaries)."""
    sess = get_user_session(db, session_id, current_user.id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    rows = (
        db.query(RAGMessage)
        .filter(RAGMessage.session_id == session_id, RAGMessage.is_summary.is_(False))
        .order_by(RAGMessage.created_at.asc())
        .limit(limit)
        .all()
    )
    return [
        RAGMessageOut(
            id=r.id,
            session_id=r.session_id,
            notebook_id=r.notebook_id,
            role=r.role,
            content=r.content,
            sources=_serialize_sources(r.sources or []),
            created_at=r.created_at.isoformat() if r.created_at else "",
        )
        for r in rows
    ]


@router.delete("/messages")
def clear_rag_messages(
    session_id: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Clear all RAG conversation messages for a session."""
    sess = get_user_session(db, session_id, current_user.id)
    if not sess:
        raise HTTPException(status_code=404, detail="Session not found")

    deleted = (
        db.query(RAGMessage)
        .filter(RAGMessage.session_id == session_id)
        .delete(synchronize_session=False)
    )
    db.commit()
    return {"deleted": deleted}
