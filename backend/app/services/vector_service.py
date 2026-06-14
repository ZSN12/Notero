"""Local vector service with neural embedding fallback to TF-IDF.

Uses DashScope text-embedding-v2 for high-quality semantic vectors.
Falls back to TF-IDF hashing when the neural service is unavailable.
Search uses numpy for fast vectorized cosine similarity.
"""

import hashlib
import json
import math
import re
import struct
from collections import Counter
from typing import Optional, List

import jieba
import numpy as np

from app.models import (
    VectorChunk, Session as DBSession, Note, Notebook, User,
)
from sqlalchemy.orm import Session as DBSessionType

from app.services.embedding_service import (
    neural_embedding, neural_embedding_batch, EMBEDDING_DIM,
)
from app.services.note_utils import (
    get_canonical_transcript_text,
    _extract_notes_from_content,
    _extract_ppt_text_parts,
)

# ── Constants ──
VEC_DIM_LEGACY = 512  # dimension of legacy TF-IDF vector
MIN_CHUNK_CHARS = 10  # skip chunks shorter than this
CHUNK_SIZE = 300  # target chars per chunk
CHUNK_OVERLAP = 50  # overlap between chunks


# ── Legacy TF-IDF Embedding (fallback) ──

def _tokenize(text: str) -> list[str]:
    """Tokenize Chinese + English text into words."""
    words: list[str] = []
    for segment in re.split(r'\s+', text):
        if not segment:
            continue
        cjk_count = sum(1 for c in segment if '\u4e00' <= c <= '\u9fff')
        if cjk_count > len(segment) * 0.3:
            words.extend(jieba.lcut(segment))
        else:
            words.append(segment.lower())
    return [w for w in words if len(w) >= 2]


def _hash_feature(token: str) -> int:
    """Map a token to a deterministic bucket index in [0, VEC_DIM_LEGACY)."""
    h = hashlib.md5(token.encode('utf-8')).hexdigest()
    return int(h, 16) % VEC_DIM_LEGACY


def _text_to_embedding_tfidf(text: str) -> bytes:
    """Legacy TF-IDF embedding."""
    tokens = _tokenize(text)
    if not tokens:
        return struct.pack(f'{VEC_DIM_LEGACY}f', *([0.0] * VEC_DIM_LEGACY))

    counter = Counter(tokens)
    vec = [0.0] * VEC_DIM_LEGACY
    for token, count in counter.items():
        idx = _hash_feature(token)
        vec[idx] += math.log1p(count)

    norm = math.sqrt(sum(v * v for v in vec))
    if norm > 0:
        vec = [v / norm for v in vec]

    return struct.pack(f'{VEC_DIM_LEGACY}f', *vec)


def _text_to_embedding(text: str) -> tuple[bytes, Optional[bytes]]:
    """Generate both legacy and neural embeddings.

    Returns (legacy_embedding, neural_embedding_or_none).
    """
    legacy = _text_to_embedding_tfidf(text)
    neural = neural_embedding(text)
    return legacy, neural


# ── Cosine Similarity (numpy vectorized) ──

def _cosine_similarity(query_vec: np.ndarray, embeddings: np.ndarray) -> np.ndarray:
    """Compute cosine similarity between query and a batch of embeddings.

    Args:
        query_vec: shape (D,)
        embeddings: shape (N, D)

    Returns:
        scores: shape (N,)
    """
    # L2 normalize
    query_norm = np.linalg.norm(query_vec)
    emb_norms = np.linalg.norm(embeddings, axis=1)

    if query_norm == 0:
        return np.zeros(len(embeddings))

    # Avoid division by zero
    emb_norms = np.where(emb_norms == 0, 1, emb_norms)

    dot = embeddings @ query_vec  # shape (N,)
    scores = dot / (emb_norms * query_norm)
    return scores


def _unpack_embeddings(chunks: list[VectorChunk], prefer_v2: bool = True) -> tuple[np.ndarray, list[VectorChunk]]:
    """Unpack embeddings from chunks into a numpy array.

    Returns (embeddings_array, valid_chunks).
    """
    valid = []
    vectors = []

    for chunk in chunks:
        emb_bytes = chunk.embedding_v2 if (prefer_v2 and chunk.embedding_v2) else chunk.embedding
        if not emb_bytes:
            continue
        try:
            vec = np.frombuffer(emb_bytes, dtype=np.float32)
            vectors.append(vec)
            valid.append(chunk)
        except Exception:
            continue

    if not vectors:
        return np.array([]), []

    return np.stack(vectors), valid


# ── Chunking ──

def _chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks of roughly chunk_size characters."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ── Content extraction ──

def _extract_text_from_note(note: Note) -> list[tuple[str, str, str, dict]]:
    """Extract indexable text chunks from a Note.

    Returns list of (source_type, source_id, text, metadata).

    The canonical transcript is the single source of truth for transcript text;
    PPT slides and student notes are kept as supplemental sources. We do not
    treat layout_blocks as primary content so that user edits / deletions are
    never resurrected from an older view.
    """
    results = []

    # 1. Canonical transcript (single source of truth).
    canonical_transcript = get_canonical_transcript_text(note)
    if canonical_transcript and len(canonical_transcript.strip()) >= MIN_CHUNK_CHARS:
        results.append((
            "transcript",
            "canonical-transcript",
            canonical_transcript.strip(),
            {"block_type": "transcript", "source": "canonical"},
        ))

    # 2. Student notes section from note.content.
    notes_text = _extract_notes_from_content(note.content)
    if notes_text and len(notes_text.strip()) >= MIN_CHUNK_CHARS:
        results.append((
            "note",
            "student-notes",
            notes_text.strip(),
            {"block_type": "note", "source": "content_notes"},
        ))

    # 3. PPT text as supplemental material.
    for ppt_part in _extract_ppt_text_parts(note):
        if ppt_part and len(ppt_part.strip()) >= MIN_CHUNK_CHARS:
            results.append(("ppt", f"ppt-{str(hash(ppt_part) & 0xffffffff)}", ppt_part.strip(), {"block_type": "ppt"}))

    # 4. Layout blocks fallback (only when no canonical content exists).
    if not results:
        layout_blocks = note.layout_blocks
        if layout_blocks and isinstance(layout_blocks, list):
            for i, block in enumerate(layout_blocks):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type", "")
                content = block.get("content", "")
                page = block.get("page")
                title = block.get("title", "")
                block_id = block.get("id") or f"block-{i}"

                if btype == "transcript" and content and len(content.strip()) >= MIN_CHUNK_CHARS:
                    meta = {"block_id": block_id, "block_index": i, "block_type": "transcript"}
                    results.append(("transcript", block_id, content.strip(), meta))
                elif btype == "note" and content and len(content.strip()) >= MIN_CHUNK_CHARS:
                    meta = {"block_id": block_id, "block_index": i, "block_type": "note"}
                    results.append(("note", block_id, content.strip(), meta))
                elif btype == "ppt":
                    ppt_text = ""
                    if title:
                        ppt_text += title + " "
                    if content:
                        ppt_text += content + " "
                    if ppt_text.strip() and len(ppt_text.strip()) >= MIN_CHUNK_CHARS:
                        meta = {"block_id": block_id, "block_index": i, "block_type": "ppt", "page": page}
                        results.append(("ppt", block_id, ppt_text.strip(), meta))

    # 5. Raw note content fallback.
    if not results and note.content:
        content = note.content.strip()
        if len(content) >= MIN_CHUNK_CHARS:
            results.append(("note", note.id, content, {}))

    return results


# ── Content fingerprint ──

def _compute_session_content_hash(note: Note) -> str:
    """Compute a stable SHA-256 fingerprint of all note content."""
    payload = {
        "content": note.content or "",
        "transcript": note.transcript or [],
        "ppt_images": note.ppt_images or [],
        "layout_blocks": note.layout_blocks or [],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Index building ──

def build_session_index(session_id: str, user: User, db: DBSessionType, use_neural: bool = True) -> int:
    """Build vector index for a single session. Returns number of chunks created."""
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(Notebook.user_id == user.id).first()
    if not session:
        raise ValueError("Session not found or access denied")

    # Delete old chunks for this session
    db.query(VectorChunk).filter(VectorChunk.session_id == session_id).delete()

    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        db.commit()
        return 0

    session_content_hash = _compute_session_content_hash(note)
    extracted = _extract_text_from_note(note)
    chunk_count = 0

    # Collect all chunk texts for batch neural embedding
    chunk_texts = []
    chunk_metas = []
    chunk_sources = []

    for source_type, source_id, text, meta in extracted:
        text_chunks = _chunk_text(text)
        for idx, chunk_text in enumerate(text_chunks):
            if len(chunk_text.strip()) < MIN_CHUNK_CHARS:
                continue
            chunk_texts.append(chunk_text)
            chunk_metas.append({
                **meta,
                "chunk_in_source": idx,
                "chunk_index": meta.get("chunk_index", idx),
                "session_content_hash": session_content_hash,
            })
            chunk_sources.append((source_type, source_id))

    # Batch neural embedding
    neural_embeddings = [None] * len(chunk_texts)
    if use_neural:
        neural_embeddings = neural_embedding_batch(chunk_texts)

    # Create VectorChunk records
    for i, chunk_text in enumerate(chunk_texts):
        content_hash = hashlib.sha256(chunk_text.encode('utf-8')).hexdigest()
        legacy_emb = _text_to_embedding_tfidf(chunk_text)  # legacy TF-IDF only

        vc = VectorChunk(
            user_id=user.id,
            notebook_id=session.notebook_id,
            session_id=session_id,
            source_type=chunk_sources[i][0],
            source_id=chunk_sources[i][1],
            chunk_index=chunk_count,
            text=chunk_text,
            chunk_meta=chunk_metas[i],
            embedding=legacy_emb,
            embedding_v2=neural_embeddings[i],
            content_hash=content_hash,
        )
        db.add(vc)
        chunk_count += 1

    db.commit()
    return chunk_count


def build_notebook_index(notebook_id: str, user: User, db: DBSessionType, use_neural: bool = True) -> int:
    """Build vector index for all sessions in a notebook. Returns total chunks."""
    notebook = db.query(Notebook).filter(
        Notebook.id == notebook_id,
        Notebook.user_id == user.id,
    ).first()
    if not notebook:
        raise ValueError("Notebook not found or access denied")

    total = 0
    for session in notebook.sessions:
        total += build_session_index(session.id, user, db, use_neural=use_neural)
    return total


# ── Search ──

def search_vectors(
    user: User,
    query: str,
    session_id: Optional[str] = None,
    notebook_id: Optional[str] = None,
    limit: int = 20,
    db: DBSessionType = None,
) -> list[dict]:
    """Search vector chunks by query. Returns sorted results with scores."""
    if not query.strip():
        return []

    # Build base query - only user's own chunks
    q = db.query(VectorChunk).filter(VectorChunk.user_id == user.id)

    if session_id:
        q = q.filter(VectorChunk.session_id == session_id)
    if notebook_id:
        q = q.filter(VectorChunk.notebook_id == notebook_id)

    chunks = q.all()
    if not chunks:
        return []

    # Determine if we have neural embeddings available
    has_v2 = any(c.embedding_v2 is not None for c in chunks)
    prefer_v2 = has_v2

    # Get query embedding (match the type used in chunks)
    if prefer_v2:
        query_emb_bytes = neural_embedding(query)
        if query_emb_bytes is None:
            # Neural service unavailable, fallback to legacy
            prefer_v2 = False

    if not prefer_v2:
        query_emb_bytes = _text_to_embedding_tfidf(query)

    # Unpack chunk embeddings into numpy array
    embeddings_np, valid_chunks = _unpack_embeddings(chunks, prefer_v2=prefer_v2)
    if len(valid_chunks) == 0:
        return []

    # Unpack query vector
    query_vec = np.frombuffer(query_emb_bytes, dtype=np.float32)

    # Vectorized cosine similarity (batched to avoid OOM with large N)
    MAX_BATCH = 2000
    if len(valid_chunks) > MAX_BATCH:
        all_scores = []
        for i in range(0, len(valid_chunks), MAX_BATCH):
            batch_emb = embeddings_np[i:i+MAX_BATCH]
            batch_scores = _cosine_similarity(query_vec, batch_emb)
            all_scores.extend(batch_scores.tolist())
        scores = np.array(all_scores)
    else:
        scores = _cosine_similarity(query_vec, embeddings_np)

    # Build scored results
    scored = []
    for chunk, score in zip(valid_chunks, scores):
        if score > 0.01:
            scored.append((chunk, float(score)))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    # Build results
    results = []
    for chunk, score in scored[:limit]:
        session = db.query(DBSession).filter(DBSession.id == chunk.session_id).first()
        notebook = db.query(Notebook).filter(Notebook.id == chunk.notebook_id).first()

        results.append({
            "chunk_id": chunk.id,
            "notebook_id": chunk.notebook_id,
            "notebook_title": notebook.title if notebook else "未知",
            "session_id": chunk.session_id,
            "session_title": session.title if session else "未知",
            "source_type": chunk.source_type,
            "source_id": chunk.source_id,
            "snippet": chunk.text[:200] + ("..." if len(chunk.text) > 200 else ""),
            "score": round(score, 4),
            "metadata": chunk.chunk_meta or {},
        })

    return results


# ── Status ──

def get_session_index_status(session_id: str, user: User, db: DBSessionType) -> dict:
    """Get indexing status for a session."""
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(Notebook.user_id == user.id).first()
    if not session:
        raise ValueError("Session not found or access denied")

    chunk_count = db.query(VectorChunk).filter(
        VectorChunk.session_id == session_id
    ).count()

    note = db.query(Note).filter(Note.session_id == session_id).first()
    has_content = bool(note and (note.content or note.transcript or note.ppt_images or note.layout_blocks))

    if not has_content:
        status = "empty"
    elif chunk_count == 0:
        status = "not_indexed"
    else:
        current_hash = _compute_session_content_hash(note) if note else ""
        sample_chunk = db.query(VectorChunk).filter(
            VectorChunk.session_id == session_id
        ).first()
        indexed_hash = ""
        if sample_chunk and sample_chunk.chunk_meta:
            indexed_hash = sample_chunk.chunk_meta.get("session_content_hash", "")
        status = "indexed" if indexed_hash == current_hash else "stale"

    # Check if has neural embeddings
    has_neural = db.query(VectorChunk).filter(
        VectorChunk.session_id == session_id,
        VectorChunk.embedding_v2.isnot(None),
    ).count() > 0

    return {
        "session_id": session_id,
        "chunk_count": chunk_count,
        "has_content": has_content,
        "status": status,
        "has_neural_embedding": has_neural,
    }
