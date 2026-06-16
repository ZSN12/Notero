"""RAG (Retrieval-Augmented Generation) API.

User asks a question → retrieve relevant chunks from vector index →
construct prompt with context → stream answer from DeepSeek.
"""

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import User, Notebook, Session as DBSession
from app.services import vector_service
from app.services.prompt_loader import load_prompt
from app.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from app.middleware.metrics import observe_llm_call

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/rag", tags=["rag"])

# Reuse OpenAI client across requests to avoid connection overhead
_llm_client = None


def _get_llm_client():
    global _llm_client
    if _llm_client is None and DEEPSEEK_API_KEY:
        from openai import OpenAI
        _llm_client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    return _llm_client


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


def _call_llm_stream(prompt: str, system: str):
    """Stream LLM response via OpenAI-compatible API."""
    import time
    client = _get_llm_client()
    if not client:
        yield f"data: {json.dumps({'type': 'error', 'detail': 'AI 问答服务不可用，但索引资料仍可检索'}, ensure_ascii=False)}\n\n"
        return

    start = time.perf_counter()
    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            temperature=0.3,
            stream=True,
        )

        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                text = chunk.choices[0].delta.content
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
    if req.notebook_id:
        nb = db.query(Notebook).filter(
            Notebook.id == req.notebook_id,
            Notebook.user_id == current_user.id,
        ).first()
        if not nb:
            raise HTTPException(status_code=404, detail="Notebook not found")
    if req.session_id:
        sess = (
            db.query(DBSession)
            .filter(DBSession.id == req.session_id)
            .join(Notebook)
            .filter(Notebook.user_id == current_user.id)
            .first()
        )
        if not sess:
            raise HTTPException(status_code=404, detail="Session not found")
        if req.notebook_id and sess.notebook_id != req.notebook_id:
            raise HTTPException(status_code=404, detail="Session not found in notebook")

    # Step 1: Retrieve relevant chunks
    try:
        results = vector_service.search_vectors(
            user=current_user,
            query=req.query,
            session_id=req.session_id,
            notebook_id=req.notebook_id,
            limit=req.top_k,
            db=db,
        )
    except Exception as e:
        logger.exception("rag_search_failed")
        raise HTTPException(status_code=500, detail=f"Search failed: {str(e)}")

    # Step 2: Build context from retrieved chunks
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
        course_title = nb.title if 'nb' in locals() else "未知课程"
    elif req.session_id and results:
        course_title = results[0].get("notebook_title", "未知课程")

    # Step 3: Render prompt
    prompt_template = load_prompt("rag_qa")
    prompt = prompt_template.render(
        course_title=course_title,
        keywords=keywords,
        context=context,
        query=req.query,
    )

    # Step 4: Stream response
    def generate():
        yield f"data: {json.dumps({'type': 'status', 'message': f'找到 {len(results)} 条相关资料'}, ensure_ascii=False)}\n\n"

        # Stream LLM answer
        yield from _call_llm_stream(prompt, prompt_template.system)

        # Send sources
        sources = [_source_payload(r) for r in results]
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources}, ensure_ascii=False)}\n\n"

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
