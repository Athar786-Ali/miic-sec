"""
MIIC-Sec — Interview Routes
All endpoints require a valid RS256 JWT issued by /auth/login.
"""

import threading
import uuid
from queue import Queue

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import (
    InterviewLog,
    Session as SessionModel,
    get_db,
)
from auth.jwt_manager import get_current_candidate
from crypto.audit_log import log_event

from interview.llm_interviewer import (
    check_ollama_running,
    end_session,
    session_store,
    start_session,
    submit_response,
)
from interview.code_sandbox import evaluate_code
from interview.emotion_analysis import run_emotion_analysis_loop

# ─── Router ──────────────────────────────────────────────────────
router = APIRouter(prefix="/interview", tags=["Interview"])

# ─── Security scheme ─────────────────────────────────────────────
bearer_scheme = HTTPBearer()

# ─── Emotion analysis state ──────────────────────────────────────
# Per-session queues, stop events, and result stores for background threads
_emotion_threads: dict[str, threading.Thread] = {}
_frame_queues: dict[str, Queue] = {}
_audio_queues: dict[str, Queue] = {}
_stop_events: dict[str, threading.Event] = {}
emotion_result_store: dict = {}


# ═══════════════════════════════════════════════════════════════════
# Dependency: resolve JWT → candidate payload
# ═══════════════════════════════════════════════════════════════════

def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    """FastAPI dependency — validates Bearer JWT and returns its payload."""
    return get_current_candidate(credentials.credentials)


# ═══════════════════════════════════════════════════════════════════
# Request / Response models
# ═══════════════════════════════════════════════════════════════════

class StartInterviewRequest(BaseModel):
    job_role: str


class RespondRequest(BaseModel):
    candidate_response: str


class ExecuteCodeRequest(BaseModel):
    code: str
    language: str = "python"


# ═══════════════════════════════════════════════════════════════════
# POST /interview/start
# ═══════════════════════════════════════════════════════════════════

@router.post("/start")
async def start_interview(
    body: StartInterviewRequest,
    payload: dict = Depends(get_token_payload),
    db: DBSession = Depends(get_db),
):
    """
    Initialise an interview session and receive the first question.

    Requires:
        Authorization: Bearer <token>
        Body: { "job_role": "str" }

    Returns:
        { session_id, first_question, difficulty, ollama_status }
    """
    candidate_id: str = payload["candidate_id"]
    session_id: str = payload["session_id"]

    # Verify Ollama is reachable before starting
    if not check_ollama_running():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama is not running. Start it with: ollama serve",
        )

    # ── Start LLM session ────────────────────────────────────────
    try:
        result = start_session(session_id, body.job_role)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start interview session: {exc}",
        )

    # ── Audit log ────────────────────────────────────────────────
    log_event(
        session_id=session_id,
        event_type="INTERVIEW_STARTED",
        detail={"candidate_id": candidate_id, "job_role": body.job_role},
        db_session=db,
    )

    # ── Start background emotion analysis thread ──────────────────
    fq: Queue = Queue(maxsize=10)
    aq: Queue = Queue(maxsize=5)
    stop_ev = threading.Event()

    _frame_queues[session_id] = fq
    _audio_queues[session_id] = aq
    _stop_events[session_id] = stop_ev

    thread = threading.Thread(
        target=run_emotion_analysis_loop,
        args=(session_id, fq, aq, emotion_result_store, stop_ev),
        daemon=True,
        name=f"emotion-{session_id[:8]}",
    )
    thread.start()
    _emotion_threads[session_id] = thread

    return {
        "session_id": result["session_id"],
        "first_question": result["first_question"],
        "difficulty": result["difficulty"],
        "ollama_status": "connected",
    }


# ═══════════════════════════════════════════════════════════════════
# POST /interview/respond
# ═══════════════════════════════════════════════════════════════════

@router.post("/respond")
async def respond_to_question(
    body: RespondRequest,
    payload: dict = Depends(get_token_payload),
    db: DBSession = Depends(get_db),
):
    """
    Submit an answer to the current question and receive the next one.

    Requires:
        Authorization: Bearer <token>
        Body: { "candidate_response": "str" }

    Returns:
        { score, feedback, next_question, difficulty, question_number }
    """
    session_id: str = payload["session_id"]

    if session_id not in session_store:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active interview session found. Call /interview/start first.",
        )

    try:
        result = submit_response(session_id, body.candidate_response)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"LLM evaluation failed: {exc}",
        )

    # ── Retrieve current question text from session history ───────
    state = session_store.get(session_id, {})
    history = state.get("history", [])
    # The question that was answered is the last assistant message before the current one
    question_text = ""
    for msg in reversed(history):
        if msg["role"] == "assistant":
            question_text = msg["content"]
            break

    # ── Persist to interview_log ──────────────────────────────────
    log_entry = InterviewLog(
        session_id=session_id,
        question_number=result["question_number"] - 1,
        question_text=question_text,
        response_text=body.candidate_response,
        score=result["score"],
        difficulty=result["difficulty"],
    )
    db.add(log_entry)
    db.commit()

    # ── Audit log ────────────────────────────────────────────────
    log_event(
        session_id=session_id,
        event_type="QUESTION_ANSWERED",
        detail={
            "question_number": result["question_number"] - 1,
            "score": result["score"],
            "difficulty": result["difficulty"],
        },
        db_session=db,
    )

    return result


# ═══════════════════════════════════════════════════════════════════
# POST /interview/execute-code
# ═══════════════════════════════════════════════════════════════════

@router.post("/execute-code")
async def execute_code_endpoint(
    body: ExecuteCodeRequest,
    payload: dict = Depends(get_token_payload),
    db: DBSession = Depends(get_db),
):
    """
    Static-analyse and sandbox-execute candidate code.

    Requires:
        Authorization: Bearer <token>
        Body: { "code": "str", "language": "python" }

    Returns:
        { passed, stdout, stderr, execution_time_ms, static_issues, timed_out }
    """
    session_id: str = payload["session_id"]

    result = evaluate_code(body.code, body.language, session_id)

    log_event(
        session_id=session_id,
        event_type="CODE_EXECUTED",
        detail={
            "language": body.language,
            "passed": result["passed"],
            "timed_out": result.get("timed_out", False),
            "static_issues_count": len(result.get("static_issues", [])),
        },
        db_session=db,
    )

    return result


# ═══════════════════════════════════════════════════════════════════
# POST /interview/end
# ═══════════════════════════════════════════════════════════════════

@router.post("/end")
async def end_interview(
    payload: dict = Depends(get_token_payload),
    db: DBSession = Depends(get_db),
):
    """
    Finalise the interview: compute aggregate score, store result, stop threads.

    Requires:
        Authorization: Bearer <token>

    Returns:
        { average_score, recommendation, total_questions, scores }
    """
    session_id: str = payload["session_id"]
    candidate_id: str = payload["candidate_id"]

    if session_id not in session_store:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active interview session to end.",
        )

    try:
        final = end_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # ── Stop emotion analysis thread ──────────────────────────────
    stop_ev = _stop_events.pop(session_id, None)
    if stop_ev:
        stop_ev.set()
    _frame_queues.pop(session_id, None)
    _audio_queues.pop(session_id, None)
    _emotion_threads.pop(session_id, None)

    # ── Update session status in DB ───────────────────────────────
    db_session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if db_session:
        from datetime import datetime, timezone

        db_session.status = "COMPLETED"
        db_session.final_score = final["average_score"]
        db_session.ended_at = datetime.now(timezone.utc)
        db.commit()

    # ── Audit log ────────────────────────────────────────────────
    log_event(
        session_id=session_id,
        event_type="INTERVIEW_COMPLETED",
        detail={
            "candidate_id": candidate_id,
            "average_score": final["average_score"],
            "recommendation": final["recommendation"],
            "total_questions": final["total_questions"],
        },
        db_session=db,
    )

    return final


# ═══════════════════════════════════════════════════════════════════
# GET /interview/emotion-snapshot
# ═══════════════════════════════════════════════════════════════════

@router.get("/emotion-snapshot")
async def emotion_snapshot(
    payload: dict = Depends(get_token_payload),
):
    """
    Return the latest emotion analysis data collected for this session.

    Requires:
        Authorization: Bearer <token>

    Returns:
        { session_id, snapshots: list, count: int }
    """
    session_id: str = payload["session_id"]
    snapshots = emotion_result_store.get(session_id, [])

    return {
        "session_id": session_id,
        "snapshots": snapshots,
        "count": len(snapshots),
    }
