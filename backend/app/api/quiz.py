from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from app.core.database import get_db
from app.core.auth import get_current_user
from app.models import User
from app.services import quiz_service

router = APIRouter(prefix="/api/quiz", tags=["quiz"])


class SubmitAnswersRequest(BaseModel):
    answers: dict[str, str]


class GenerateQuizRequest(BaseModel):
    mode: str = "diagnostic"


@router.get("/session/{session_id}/bank/status")
def get_bank_status(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get question bank status for a session."""
    try:
        return quiz_service.get_bank_status(session_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/session/{session_id}/bank/rebuild")
def rebuild_bank(
    session_id: str,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force rebuild the question bank (calls AI)."""
    try:
        result = quiz_service.start_bank_generation(session_id, current_user, db, force=True)
        if result.get("status") == "generating":
            response.status_code = status.HTTP_202_ACCEPTED
        return result
    except ValueError as e:
        error_msg = str(e)
        if "DEEPSEEK_API_KEY" in error_msg:
            raise HTTPException(status_code=503, detail=error_msg)
        if "JSON" in error_msg or "结构" in error_msg or "对象" in error_msg or "题目" in error_msg or "选项" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg)
        if "失败" in error_msg or "超时" in error_msg or "timeout" in error_msg.lower():
            raise HTTPException(status_code=502, detail=error_msg)
        raise HTTPException(status_code=404, detail=error_msg)


@router.get("/session/{session_id}")
def get_session_quizzes(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all quiz attempts for a session (without answers)."""
    try:
        return quiz_service.get_session_quizzes(session_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/session/{session_id}/generate")
def generate_quiz(
    session_id: str,
    response: Response,
    body: GenerateQuizRequest | None = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate a new quiz attempt from the question bank (no AI call).

    If bank is not ready, returns status so frontend can trigger bank generation.
    """
    try:
        result = quiz_service.generate_quiz(session_id, current_user, db, mode=(body.mode if body else "diagnostic"))
        if result.get("status") in ("need_bank", "stale"):
            # Auto-trigger bank generation if needed
            if result["status"] == "need_bank":
                bank_result = quiz_service.start_bank_generation(session_id, current_user, db, force=False)
                response.status_code = status.HTTP_202_ACCEPTED
                return bank_result
            response.status_code = status.HTTP_202_ACCEPTED
            return result
        return result
    except ValueError as e:
        error_msg = str(e)
        if "DEEPSEEK_API_KEY" in error_msg:
            raise HTTPException(status_code=503, detail=error_msg)
        if "JSON" in error_msg or "结构" in error_msg or "对象" in error_msg or "题目" in error_msg or "选项" in error_msg:
            raise HTTPException(status_code=422, detail=error_msg)
        if "失败" in error_msg or "超时" in error_msg or "timeout" in error_msg.lower():
            raise HTTPException(status_code=502, detail=error_msg)
        raise HTTPException(status_code=404, detail=error_msg)


@router.get("/session/{session_id}/mastery")
def get_quiz_mastery(
    session_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get weighted knowledge point mastery for a session."""
    try:
        return quiz_service.get_quiz_mastery(session_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/session/{session_id}/{quiz_id}/submit")
def submit_quiz_answers(
    session_id: str,
    quiz_id: str,
    body: SubmitAnswersRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit quiz answers."""
    try:
        return quiz_service.submit_quiz_answers(session_id, quiz_id, current_user, db, body.answers)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/session/{session_id}/{quiz_id}")
def get_quiz_detail(
    session_id: str,
    quiz_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get quiz detail. If not submitted, strips answers. If submitted, returns full detail."""
    try:
        return quiz_service.get_quiz_detail(session_id, quiz_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/session/{session_id}/{quiz_id}")
def delete_quiz(
    session_id: str,
    quiz_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a quiz attempt (not the bank)."""
    try:
        return quiz_service.delete_quiz(session_id, quiz_id, current_user, db)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
