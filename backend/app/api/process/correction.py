import copy
import logging
import threading
import time

from app.models import Note
from app.services.term_corrector import corrector


logger = logging.getLogger(__name__)

CORRECTION_INTERVAL_SECONDS = 20
_correction_lock = threading.Lock()
_correction_tasks: dict[str, bool] = {}
_last_correction_time: dict[str, float] = {}
_pending_force_correction: dict[str, tuple[str, list]] = {}


def _extract_ppt_slides(note: Note) -> list | None:
    if isinstance(note.ppt_images, list) and note.ppt_images:
        last_ppt = note.ppt_images[-1]
        if isinstance(last_ppt, dict):
            slides = last_ppt.get("slides", [])
            return slides or None
    return None


def _display_text_from_entry(entry: dict) -> str:
    return (
        entry.get("display_text")
        or entry.get("text")
        or entry.get("raw_text")
        or ""
    ).strip()


def correct_uncorrected_transcripts_from_data(
    session_id: str,
    course_title: str,
    keywords: list,
    transcript_data: list,
    db,
    snapshot_max_chunk: int = -1,
    is_final: bool = False,
):
    """Correct and restructure a transcript snapshot.

    The snapshot may become stale while DeepSeek is working. We therefore
    re-read the note, correct only chunks that existed in the snapshot, and
    append any newer chunks unchanged so live recording can keep flowing.
    """
    try:
        logger.info(
            "transcript_correction_start session_id=%s snapshot_max_chunk=%s",
            session_id,
            snapshot_max_chunk,
        )

        fresh_note = db.query(Note).filter(Note.session_id == session_id).first()
        if not fresh_note or not fresh_note.transcript:
            logger.info("transcript_correction_skip_empty session_id=%s", session_id)
            return

        latest_transcript = list(fresh_note.transcript)
        snapshot_chunks = [
            entry for entry in latest_transcript
            if entry.get("chunk_index", -1) <= snapshot_max_chunk
        ]
        new_chunks = [
            entry for entry in latest_transcript
            if entry.get("chunk_index", -1) > snapshot_max_chunk
        ]

        all_texts: list[str] = []
        all_timestamps: list[dict] = []
        for entry in snapshot_chunks:
            text = _display_text_from_entry(entry)
            if text:
                all_texts.append(text)
            timestamps = entry.get("timestamps", [])
            if timestamps:
                all_timestamps.extend(timestamps)

        if not all_texts:
            logger.info("transcript_correction_skip_no_text session_id=%s", session_id)
            return

        all_texts = corrector.dedupe_repeated_texts(all_texts)
        full_text = "\n".join(all_texts)
        ppt_slides = _extract_ppt_slides(fresh_note)
        logger.info(
            "transcript_correction_llm_start session_id=%s chunks=%s chars=%s new_chunks=%s has_ppt=%s",
            session_id,
            len(all_texts),
            len(full_text),
            len(new_chunks),
            bool(ppt_slides),
        )

        corrected = corrector.restructure_transcript(
            text=full_text,
            course_title=course_title,
            keywords=keywords,
            ppt_slides=ppt_slides,
        )
        logger.info(
            "transcript_correction_llm_raw session_id=%s input_len=%s output_len=%s output_preview=%r",
            session_id, len(full_text), len(corrected or ""), (corrected or "")[:120],
        )

        base_for_display = full_text
        if corrected and corrected != full_text:
            try:
                review = corrector.review_and_repair_candidate(
                    full_text,
                    corrected,
                    protected_terms=keywords,
                )
                logger.info(
                    "transcript_correction_llm_accepted session_id=%s source_chars=%s corrected_chars=%s reviewed=%s repaired=%s",
                    session_id,
                    len(full_text),
                    len(review["text"]),
                    review["review_performed"],
                    review["review_repaired"],
                )
                base_for_display = review["text"]
            except Exception as exc:
                logger.warning(
                    "transcript_correction_llm_rejected session_id=%s source_chars=%s corrected_chars=%s error=%s",
                    session_id,
                    len(full_text),
                    len(corrected),
                    type(exc).__name__,
                    exc_info=True,
                )

        display_corrected = corrector.clean_transcript_for_display(base_for_display)
        corrected_entry = {
            "chunk_index": 0,
            "text": display_corrected,
            "raw_text": full_text,
            "display_text": display_corrected,
            "timestamps": all_timestamps,
            "is_corrected": True,
            "is_restructured": False,
            "correction_stage": "final" if is_final else "rolling",
        }

        merged = [corrected_entry]
        for i, new_chunk in enumerate(new_chunks, start=1):
            new_chunk["chunk_index"] = i
            merged.append(new_chunk)

        fresh_note.transcript = merged
        db.commit()
        logger.info(
            "transcript_correction_saved session_id=%s corrected_chars=%s new_chunks=%s total_chunks=%s",
            session_id,
            len(display_corrected),
            len(new_chunks),
            len(merged),
        )

    except Exception as exc:
        logger.exception(
            "transcript_correction_failed session_id=%s error_type=%s error=%s",
            session_id,
            type(exc).__name__,
            exc,
        )


def schedule_correction(
    session_id: str,
    course_title: str,
    keywords: list,
    db,
    *,
    force: bool = False,
    delay_seconds: float = 0.5,
):
    """Schedule a background correction task.

    Live recording calls this periodically for rolling cleanup. Stop recording
    calls it with force=True so the final note does not get blocked by the
    periodic throttle.
    """
    now = time.time()

    with _correction_lock:
        last_time = _last_correction_time.get(session_id, 0)
        time_since_last = now - last_time

        if session_id in _correction_tasks:
            if force:
                _pending_force_correction[session_id] = (course_title, list(keywords or []))
                logger.info("transcript_correction_pending_force session_id=%s", session_id)
            else:
                logger.info("transcript_correction_skip_running session_id=%s", session_id)
            return

        if not force and time_since_last < CORRECTION_INTERVAL_SECONDS:
            logger.info(
                "transcript_correction_skip_throttled session_id=%s elapsed=%.1fs need=%ss",
                session_id,
                time_since_last,
                CORRECTION_INTERVAL_SECONDS,
            )
            return

        _correction_tasks[session_id] = True
        _last_correction_time[session_id] = now

    def run_correction():
        thread_db = None
        pending_force: tuple[str, list] | None = None
        try:
            if delay_seconds > 0:
                time.sleep(delay_seconds)

            from app.core.database import SessionLocal
            from app.models import Note as NoteModel

            thread_db = SessionLocal()
            fresh_note = thread_db.query(NoteModel).filter(NoteModel.session_id == session_id).first()
            if not fresh_note or not fresh_note.transcript:
                logger.info("transcript_correction_thread_skip_empty session_id=%s", session_id)
                with _correction_lock:
                    _last_correction_time[session_id] = 0
                return

            transcript_copy = copy.deepcopy(fresh_note.transcript)
            snapshot_max = max(
                (entry.get("chunk_index", -1) for entry in transcript_copy),
                default=-1,
            )
            total_text = " ".join(
                _display_text_from_entry(entry)
                for entry in transcript_copy
                if _display_text_from_entry(entry)
            ).strip()
            if not total_text:
                logger.info("transcript_correction_thread_skip_no_text session_id=%s", session_id)
                with _correction_lock:
                    _last_correction_time[session_id] = 0
                return

            logger.info(
                "transcript_correction_thread_run session_id=%s chars=%s snapshot_max_chunk=%s force=%s",
                session_id,
                len(total_text),
                snapshot_max,
                force,
            )
            correct_uncorrected_transcripts_from_data(
                session_id,
                course_title,
                keywords,
                transcript_copy,
                thread_db,
                snapshot_max_chunk=snapshot_max,
                is_final=force,
            )

        except Exception as exc:
            logger.exception(
                "transcript_correction_thread_failed session_id=%s error_type=%s error=%s",
                session_id,
                type(exc).__name__,
                exc,
            )
        finally:
            try:
                if thread_db is not None:
                    thread_db.close()
            finally:
                with _correction_lock:
                    _correction_tasks.pop(session_id, None)
                    pending_force = _pending_force_correction.pop(session_id, None)

            if pending_force:
                pending_course_title, pending_keywords = pending_force
                schedule_correction(
                    session_id,
                    pending_course_title,
                    pending_keywords,
                    None,
                    force=True,
                    delay_seconds=0.1,
                )

    thread = threading.Thread(target=run_correction, daemon=True)
    thread.start()
    logger.info(
        "transcript_correction_scheduled session_id=%s force=%s delay=%.1fs",
        session_id,
        force,
        delay_seconds,
    )
