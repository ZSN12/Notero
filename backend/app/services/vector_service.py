"""Local vector service with neural embedding fallback to TF-IDF.

Uses DashScope text-embedding-v2 for high-quality semantic vectors.
Falls back to TF-IDF hashing when the neural service is unavailable.
Search uses numpy for fast vectorized cosine similarity.
"""

import hashlib
import json
import logging
import math
import re
import struct
from collections import Counter
from typing import Optional, List

import jieba
import numpy as np

from app.models import (
    VectorChunk, Session as DBSession, Note, Notebook, User,
    _PGVECTOR_AVAILABLE,
)
from sqlalchemy.orm import Session as DBSessionType

from app.services.embedding_service import (
    neural_embedding, neural_embedding_batch, EMBEDDING_DIM,
)
from app.services.session_service import get_user_session as _get_session_by_user
from app.services.note_utils import (
    _extract_notes_from_content,
    get_canonical_transcript_text,
)

logger = logging.getLogger(__name__)

# ── Constants ──
VEC_DIM_LEGACY = 512  # dimension of legacy TF-IDF vector
MIN_CHUNK_CHARS = 10  # skip chunks shorter than this
CHUNK_SIZE = 300  # target chars per chunk
CHUNK_OVERLAP = 50  # overlap between chunks


def _stable_text_id(prefix: str, index: int, text: str) -> str:
    """Build a stable enough id for source text anchors without a schema change."""
    normalized = re.sub(r"\s+", "", text or "")
    value = 2166136261
    for ch in normalized[:240]:
        value ^= ord(ch)
        value = (value * 16777619) & 0xFFFFFFFF
    return f"{prefix}-{index}-{value:08x}"


def _split_paragraphs(text: str) -> list[str]:
    """Split text using authored paragraph breaks, keeping single paragraphs intact."""
    return [p.strip() for p in re.split(r"\n\s*\n+", text or "") if p.strip()]


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


def _neural_bytes_to_list(emb_bytes: bytes) -> Optional[list[float]]:
    """Unpack packed float32 neural embedding bytes into a list.

    Returns None if the bytes are missing or have the wrong length.
    """
    if not emb_bytes:
        return None
    expected = EMBEDDING_DIM * 4
    if len(emb_bytes) != expected:
        logger.warning(
            "neural_embedding_bytes_wrong_length expected=%s got=%s",
            expected, len(emb_bytes),
        )
        return None
    try:
        return list(struct.unpack(f"{EMBEDDING_DIM}f", emb_bytes))
    except Exception:
        logger.warning("neural_embedding_bytes_unpack_failed", exc_info=True)
        return None


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
    """
    results = []

    # 1. Canonical transcript is the primary source. Do not prefer
    # layout_blocks here; they may contain stale transcript blocks after edits.
    transcript_text = get_canonical_transcript_text(note)
    if transcript_text and len(transcript_text.strip()) >= MIN_CHUNK_CHARS:
        paragraphs = _split_paragraphs(transcript_text)
        if not paragraphs:
            paragraphs = [transcript_text.strip()]
        for idx, para in enumerate(paragraphs):
            if len(para.strip()) < MIN_CHUNK_CHARS:
                continue
            paragraph_id = _stable_text_id("transcript", idx, para)
            results.append(
                (
                    "transcript",
                    paragraph_id,
                    para.strip(),
                    {
                        "block_id": paragraph_id,
                        "block_type": "transcript",
                        "paragraph_id": paragraph_id,
                        "paragraph_index": idx,
                    },
                )
            )

    # 2. Student notes from note.content are supplemental note chunks.
    notes_text = _extract_notes_from_content(note.content)
    if notes_text and len(notes_text.strip()) >= MIN_CHUNK_CHARS:
        note_paragraphs = _split_paragraphs(notes_text)
        if not note_paragraphs:
            note_paragraphs = [notes_text.strip()]
        for idx, para in enumerate(note_paragraphs):
            if len(para.strip()) < MIN_CHUNK_CHARS:
                continue
            block_id = _stable_text_id("note", idx, para)
            results.append(
                (
                    "note",
                    block_id,
                    para.strip(),
                    {
                        "block_id": block_id,
                        "block_type": "note",
                        "paragraph_id": block_id,
                        "paragraph_index": idx,
                    },
                )
            )

    # 3. Plain content fallback for notes without transcript marker.
    if not results and note.content:
        content = note.content.strip()
        if len(content) >= MIN_CHUNK_CHARS:
            results.append(("note", note.id, content, {}))

    # 4. PPT images text is supplemental source, never the primary transcript.
    ppt_images = note.ppt_images
    if ppt_images and isinstance(ppt_images, list):
        for ppt_data in ppt_images:
            if not isinstance(ppt_data, dict):
                continue
            slides = ppt_data.get("slides", [])
            for slide in slides:
                if not isinstance(slide, dict):
                    continue
                slide_text = slide.get("text", "")
                page_num = slide.get("page", "")
                if slide_text and len(slide_text.strip()) >= MIN_CHUNK_CHARS:
                    meta = {"page": page_num}
                    results.append(("ppt", str(page_num), slide_text.strip(), meta))

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
    session = _get_session_by_user(db, session_id, user.id)
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
        neural_emb = neural_embeddings[i]

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
            embedding_v2=neural_emb,
            content_hash=content_hash,
        )
        if _PGVECTOR_AVAILABLE:
            vc.embedding_vector = _neural_bytes_to_list(neural_emb)
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

def _build_result(chunk: VectorChunk, score: float, db: DBSessionType) -> dict:
    """Build a single search result dict with title lookups."""
    session = db.query(DBSession).filter(DBSession.id == chunk.session_id).first()
    notebook = db.query(Notebook).filter(Notebook.id == chunk.notebook_id).first()

    return {
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
    }


def _search_vectors_pgvector(
    user: User,
    query_vec: list[float],
    session_id: Optional[str],
    notebook_id: Optional[str],
    limit: int,
    db: DBSessionType,
) -> Optional[list[dict]]:
    """Use pgvector cosine-distance operator for fast approximate search.

    Returns None if pgvector is unavailable or the query fails, so callers
    can fall back to the numpy scan.
    """
    if not _PGVECTOR_AVAILABLE:
        return None

    embedding_col = getattr(VectorChunk, "embedding_vector", None)
    if embedding_col is None:
        return None

    # cosine distance: 0 = identical, 2 = opposite.
    # score (similarity) = 1 - distance.
    max_distance = 0.99  # equivalent to score > 0.01

    try:
        distance_expr = embedding_col.op("<=>")(query_vec)
        q = (
            db.query(VectorChunk, distance_expr.label("distance"))
            .filter(VectorChunk.user_id == user.id)
            .filter(embedding_col.isnot(None))
            .filter(distance_expr < max_distance)
        )
        if session_id:
            q = q.filter(VectorChunk.session_id == session_id)
        if notebook_id:
            q = q.filter(VectorChunk.notebook_id == notebook_id)

        candidate_limit = max(limit * 4, limit + 12)
        rows = (
            q.order_by(distance_expr.asc())
            .limit(candidate_limit)
            .all()
        )
        return [_build_result(chunk, 1.0 - float(distance), db) for chunk, distance in rows]
    except Exception:
        logger.warning("pgvector_search_failed", exc_info=True)
        return None


def _search_vectors_numpy(
    user: User,
    query_emb_bytes: bytes,
    chunks: list[VectorChunk],
    limit: int,
    db: DBSessionType,
) -> list[dict]:
    """Legacy numpy full-scan cosine similarity (fallback)."""
    has_v2 = any(c.embedding_v2 is not None for c in chunks)
    prefer_v2 = has_v2

    embeddings_np, valid_chunks = _unpack_embeddings(chunks, prefer_v2=prefer_v2)
    if len(valid_chunks) == 0:
        return []

    query_vec = np.frombuffer(query_emb_bytes, dtype=np.float32)

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

    scored = [
        (chunk, float(score))
        for chunk, score in zip(valid_chunks, scores)
        if score > 0.01
    ]
    scored.sort(key=lambda x: x[1], reverse=True)

    candidate_limit = max(limit * 4, limit + 12)
    return [_build_result(chunk, score, db) for chunk, score in scored[:candidate_limit]]


def _balance_search_results(results: list[dict], limit: int) -> list[dict]:
    """Keep relevance order while preventing one source type from crowding out all others."""
    if limit <= 0:
        return []
    if len(results) <= limit or limit <= 2:
        return results[:limit]

    max_per_source = max(1, math.ceil(limit * 0.6))
    selected: list[dict] = []
    selected_ids: set[str] = set()
    per_source: Counter[str] = Counter()

    for result in results:
        source_type = str(result.get("source_type") or "unknown")
        chunk_id = str(result.get("chunk_id") or "")
        if chunk_id in selected_ids:
            continue
        if per_source[source_type] >= max_per_source:
            continue
        selected.append(result)
        selected_ids.add(chunk_id)
        per_source[source_type] += 1
        if len(selected) >= limit:
            selected.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
            return selected

    for result in results:
        chunk_id = str(result.get("chunk_id") or "")
        if chunk_id in selected_ids:
            continue
        selected.append(result)
        selected_ids.add(chunk_id)
        if len(selected) >= limit:
            break

    selected.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
    return selected


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

    # Try neural query embedding first; if the service is unavailable,
    # fall back to legacy TF-IDF for the numpy scan path.
    query_emb_bytes = neural_embedding(query)
    if query_emb_bytes is not None:
        query_vec = _neural_bytes_to_list(query_emb_bytes)
        if query_vec is not None:
            pg_results = _search_vectors_pgvector(
                user, query_vec, session_id, notebook_id, limit, db
            )
            if pg_results is not None:
                return _balance_search_results(pg_results, limit)
        # If pgvector failed, still try numpy with the neural bytes.
        return _balance_search_results(
            _search_vectors_numpy(user, query_emb_bytes, chunks, limit, db),
            limit,
        )

    # Neural service unavailable: TF-IDF fallback.
    query_emb_bytes = _text_to_embedding_tfidf(query)
    return _balance_search_results(
        _search_vectors_numpy(user, query_emb_bytes, chunks, limit, db),
        limit,
    )


# ── Status ──

def get_session_index_status(session_id: str, user: User, db: DBSessionType) -> dict:
    """Get indexing status for a session."""
    session = _get_session_by_user(db, session_id, user.id)
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

    # Check if has neural embeddings (pgvector column is the source of truth)
    neural_col = getattr(VectorChunk, "embedding_vector", None)
    if neural_col is not None:
        has_neural = db.query(VectorChunk).filter(
            VectorChunk.session_id == session_id,
            neural_col.isnot(None),
        ).count() > 0
    else:
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
