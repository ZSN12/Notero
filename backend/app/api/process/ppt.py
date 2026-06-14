import os
import re

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import Note, Session as DBSession, Notebook, User
from app.services.ppt_service import extract_keywords_from_ppt, parse_ppt_to_slides
from app.services.slide_aligner import SlideAligner
from app.services.file_service import save_file
from app.config import SLIDE_DIR, MAX_PPT_SIZE

MAX_PPT_FILE_SIZE = MAX_PPT_SIZE  # Use centralized config

ALLOWED_PPT_TYPES = {
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-powerpoint",
    "application/pdf",
    "application/octet-stream",
}

router = APIRouter()


def get_transcript_text(note) -> str:
    """Extract full transcript text from a note.

    Prioritise transcript array (latest ASR data), then fall back to
    stripping "## 语音转文字" sections from note.content.
    """
    # 1) Prefer latest transcript chunks (sorted by chunk_index)
    if note.transcript:
        texts = []
        for seg in sorted(
            note.transcript,
            key=lambda s: s.get("chunk_index", 0) if isinstance(s, dict) else 0,
        ):
            if isinstance(seg, dict):
                text = seg.get("text", "")
            else:
                text = str(seg)
            if text:
                texts.append(text)
        joined = " ".join(texts).strip()
        if joined:
            return joined

    # 2) Fall back to note.content, stripping markdown wrapper
    if note.content and note.content.strip():
        import re
        clean = re.sub(r'^##\s*语音转文字\s*\n*', '', note.content.strip())
        clean = re.sub(r'\n*---\s*$', '', clean)
        return clean.strip()

    return ""


@router.post("/ppt-insert")
def insert_ppt_into_transcript(
    session_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Match transcript text against PPT slides and insert slide images into the text flow.

    Returns a list of content blocks:
    - {"type": "text", "content": "..."}
    - {"type": "image", "src": "/api/media/slides/{id}/slide_01.png", "page": 1}
    """
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    # Verify session ownership
    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get note with transcript and PPT data
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    if not note.ppt_images:
        return {"blocks": [{"type": "text", "content": get_transcript_text(note)}]}

    last_ppt = note.ppt_images[-1]
    slides = last_ppt.get("slides", []) if isinstance(last_ppt, dict) else []
    if not slides:
        return {"blocks": [{"type": "text", "content": get_transcript_text(note)}]}

    transcript = get_transcript_text(note)
    if not transcript.strip():
        return {"blocks": [{"type": "text", "content": ""}]}

    # Create a fresh aligner instance for this request (avoid shared state)
    request_aligner = SlideAligner()
    request_aligner.set_slides(slides)

    # Split transcript into sentences for matching
    sentences = re.split(r'(?<=[。！？\n])', transcript)
    sentences = [s.strip() for s in sentences if s.strip()]

    if not sentences:
        return {"blocks": [{"type": "text", "content": transcript.strip()}]}

    # ── Build result blocks with sliding-window PPT matching ──
    # Keep the title/cover slide (page 1) in alignment but rely on
    # SlideAligner to weight it only by title, so the first real topic
    # mention can match the cover slide without it stealing later matches.
    content_slides = slides
    request_aligner.set_slides(content_slides)
    idx_map = {i: i for i in range(len(slides))}

    # Use a tight window (max 2 sentences) to avoid *lookahead pollution*:
    # a long window that includes the next slide's keywords pulls the current
    # sentence forward into the wrong slide.
    # During the opening phase we use a single-sentence window so the cover
    # slide can be matched from the very first topic mention without being
    # overwhelmed by the next sentence's section keywords.
    WINDOW_OPEN = 1
    WINDOW_MAX = 2
    THRESHOLD = 0.15
    STICKY_MARGIN = 0.08

    blocks: list[dict] = []
    matched_pages: set[int] = set()
    seg_idx = 0
    current_slide_idx: int | None = None

    def _match_window(start: int, end: int, th: float) -> int | None:
        text = "".join(sentences[start:end])
        if not text.strip():
            return None
        return request_aligner.match(text, threshold=th)

    while seg_idx < len(sentences):
        # Keep the aligner's positional state in sync with the slide we have
        # actually accepted; guards/sticky logic may override a raw match so
        # the aligner's internal current_page can drift otherwise.
        if current_slide_idx is None:
            request_aligner.current_page = None
        else:
            request_aligner.current_page = current_slide_idx

        # Opening phase: single-sentence window to protect the cover slide match.
        if current_slide_idx is None:
            window_end = min(seg_idx + WINDOW_OPEN, len(sentences))
        else:
            window_end = min(seg_idx + WINDOW_MAX, len(sentences))
        matched_idx = _match_window(seg_idx, window_end, THRESHOLD)

        # ── Sequential constraint + opening guard ──
        if matched_idx is not None:
            matched_page = content_slides[matched_idx]["page"]

            if current_slide_idx is None:
                # Opening phase: don't jump to a late slide (summary etc.)
                # Allow the cover slide (page 1) or first content slide (page 2)
                # so the initial topic mention aligns with the title slide.
                if matched_page > 2:
                    matched_idx = None
            else:
                current_page = content_slides[current_slide_idx]["page"]
                # No back-jumps — once we passed slide N, we don't return
                if matched_page < current_page:
                    matched_idx = current_slide_idx

        # ── Sticky logic ──
        if (
            matched_idx is not None
            and current_slide_idx is not None
            and matched_idx != current_slide_idx
        ):
            window_text = "".join(sentences[seg_idx:window_end])
            best_score = request_aligner.get_slide_score(window_text, matched_idx)
            current_score = request_aligner.get_slide_score(
                window_text, current_slide_idx
            )
            if current_score >= THRESHOLD and (
                current_score + STICKY_MARGIN
            ) >= best_score:
                matched_idx = current_slide_idx

        # ── Summary guard ──
        # The last slide is usually a keyword catch-all.  Don't jump to it
        # from a content slide unless it wins by a clear margin or we have
        # already covered most of the deck.
        if (
            matched_idx is not None
            and current_slide_idx is not None
            and matched_idx == len(content_slides) - 1
            and current_slide_idx != len(content_slides) - 1
        ):
            window_text = "".join(sentences[seg_idx:window_end])
            summary_score = request_aligner.get_slide_score(
                window_text, matched_idx
            )
            current_score = request_aligner.get_slide_score(
                window_text, current_slide_idx
            )
            if (
                summary_score <= current_score + 0.15
                and len(matched_pages) < len(content_slides) // 2
            ):
                matched_idx = current_slide_idx

        if matched_idx is not None:
            current_slide_idx = matched_idx
            orig_idx = idx_map[matched_idx]
            slide = slides[orig_idx]
            page_num = slide["page"]
            if page_num not in matched_pages:
                matched_pages.add(page_num)
                if slide.get("image_path"):
                    blocks.append({
                        "type": "image",
                        "src": f"/api/media/slides/{session_id}/{slide['image_path']}",
                        "page": page_num,
                        "title": slide.get("title", ""),
                    })

        first_sentence = sentences[seg_idx]
        if first_sentence:
            if blocks and blocks[-1]["type"] == "text":
                blocks[-1]["content"] += " " + first_sentence
            else:
                blocks.append({"type": "text", "content": first_sentence})

        seg_idx += 1

    # ── Post-process: merge consecutive image blocks of the same slide ──
    # (shouldn't happen with matched_pages set, but kept for safety)
    deduped: list[dict] = []
    last_img_page: int | None = None
    for b in blocks:
        if b["type"] == "image":
            if b["page"] != last_img_page:
                deduped.append(b)
                last_img_page = b["page"]
        else:
            deduped.append(b)
    blocks = deduped

    return {"blocks": blocks}


@router.post("/ppt-upload")
async def upload_ppt(
    file: UploadFile = File(...),
    session_id: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload PPT/PDF file, parse slides, extract images, and return slide data for frontend display."""
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    file_ext = os.path.splitext(file.filename or "")[1].lower()
    if file_ext not in ['.ppt', '.pptx', '.pdf']:
        raise HTTPException(status_code=400, detail="Only PPT, PPTX, and PDF files are supported")

    if file.content_type and file.content_type not in ALLOWED_PPT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported file type: {file.content_type}. Allowed: application/vnd.openxmlformats-officedocument.presentationml.presentation, application/pdf, etc."
        )

    try:
        file_bytes = await file.read()
        file_size = len(file_bytes)
        if file_size > MAX_PPT_FILE_SIZE:
            raise HTTPException(
                status_code=413,
                detail=f"PPT file too large: {file_size} bytes (max {MAX_PPT_FILE_SIZE} bytes)"
            )

        ppt_path = save_file("ppt", session_id, file.filename or f"upload{file_ext}", file_bytes)
        ppt_path_str = str(ppt_path)

        # Render slides to disk files (not base64 in DB)
        slide_dir = SLIDE_DIR / session_id
        slide_dir.mkdir(parents=True, exist_ok=True)

        slides = parse_ppt_to_slides(ppt_path_str, output_dir=str(slide_dir))
        if not slides:
            raise HTTPException(status_code=500, detail="Failed to parse PPT, no slides found")

        try:
            keywords = extract_keywords_from_ppt(ppt_path_str, session.title)
            if keywords:
                session.keywords = keywords
                db.commit()
        except Exception as kw_error:
            logger.warning("Keyword extraction failed: %s", kw_error)

        ppt_data = {
            "filename": file.filename,
            "path": ppt_path_str,
            "total_pages": len(slides),
            "slides": slides,  # image_path instead of image_base64
        }

        existing_note = db.query(Note).filter(Note.session_id == session_id).first()
        if not existing_note:
            note = Note(
                session_id=session_id,
                content="",
                transcript=[],
                ppt_images=[ppt_data],
                vocabulary=[],
            )
            db.add(note)
        else:
            note = existing_note
            # Replace instead of append — only keep the latest PPT
            note.ppt_images = [ppt_data]

        db.commit()
        db.refresh(note)

        return {
            "status": "success",
            "filename": file.filename,
            "total_pages": len(slides),
            "slides": slides,
            "note_id": note.id,
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.exception("PPT upload failed")
        raise HTTPException(status_code=500, detail="PPT processing failed")


@router.post("/ppt-align")
def align_ppt_with_text(
    session_id: str = "",
    text: str = "",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Match transcript text against PPT slides and return the best-matching slide index.

    If slides haven't been pre-loaded for this session, loads them from the note's ppt_images.
    """
    if not session_id or not text:
        raise HTTPException(status_code=400, detail="session_id and text are required")

    session = db.query(DBSession).filter(
        DBSession.id == session_id
    ).join(Notebook).filter(
        Notebook.user_id == current_user.id
    ).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get note with PPT data
    note = db.query(Note).filter(Note.session_id == session_id).first()
    if not note or not note.ppt_images:
        return {"matched_page": None, "similarity": 0.0}

    last_ppt = note.ppt_images[-1]
    slides = last_ppt.get("slides", []) if isinstance(last_ppt, dict) else []
    if not slides:
        return {"matched_page": None, "similarity": 0.0}

    # Create a fresh aligner instance per request to avoid shared state
    request_aligner = SlideAligner()
    request_aligner.set_slides(slides)

    # Match text to slide
    matched_idx = request_aligner.match(text)

    if matched_idx is not None:
        return {
            "matched_page": matched_idx,
            "similarity": 1.0,
            "slide": slides[matched_idx],
        }

    return {"matched_page": None, "similarity": 0.0}
