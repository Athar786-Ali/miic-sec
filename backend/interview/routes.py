"""
MIIC-Sec — Interview Routes (v2)
Adds resume upload, topic selection, status endpoint, voice transcription,
and multi-mode interview support.
"""

import json
import logging
import threading
import uuid
import asyncio
from queue import Queue

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from sqlalchemy.orm import Session as DBSession

from database import InterviewLog, Session as SessionModel, get_db
from auth.jwt_manager import get_current_candidate
from crypto.audit_log import log_event
from crypto.report_signer import generate_full_report

from interview.llm_interviewer import (
    check_ollama_running,
    end_session,
    get_session_status,
    session_store,
    start_session,
    submit_response,
)
from interview.code_sandbox import evaluate_code
from interview.emotion_analysis import run_emotion_analysis_loop
from interview.resume_parser import (
    extract_text_from_pdf,
    extract_resume_sections,
    build_resume_context,
)
from interview.topic_manager import get_all_topics
from interview.transcriber import transcribe_audio

# ─── Router ──────────────────────────────────────────────────────
router = APIRouter(prefix="/interview", tags=["Interview"])

# ─── Security scheme ─────────────────────────────────────────────
bearer_scheme = HTTPBearer()

# ─── Emotion analysis state ──────────────────────────────────────
_emotion_threads: dict[str, threading.Thread] = {}
_frame_queues:    dict[str, Queue]             = {}
_audio_queues:    dict[str, Queue]             = {}
_stop_events:     dict[str, threading.Event]   = {}
emotion_result_store: dict = {}


# ═══════════════════════════════════════════════════════════════════
# Dependency: resolve JWT → candidate payload
# ═══════════════════════════════════════════════════════════════════

def get_token_payload(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    return get_current_candidate(credentials.credentials)


# ═══════════════════════════════════════════════════════════════════
# Request / Response models
# ═══════════════════════════════════════════════════════════════════

class RespondRequest(BaseModel):
    candidate_response: str
    input_mode: str = "text"   # "text" | "voice" — voice is transcribed client-side


class ExecuteCodeRequest(BaseModel):
    code: str
    language: str = "python"


# ═══════════════════════════════════════════════════════════════════
# POST /interview/transcribe (Whisper Audio Upload)
# ═══════════════════════════════════════════════════════════════════

@router.post("/transcribe")
async def transcribe(
    audio_file: UploadFile = File(...),
    payload: dict = Depends(get_token_payload),
):
    """
    Accepts an audio file (.webm) from the browser MediaRecorder,
    converts it to WAV via ffmpeg, and transcribes via Whisper.

    Returns:
        { transcript: str, confidence: float }
    """
    # ── Read incoming audio bytes ─────────────────────────────────
    audio_bytes = await audio_file.read()

    logger.info(
        "Transcribe request — filename=%s size=%d bytes content_type=%s",
        audio_file.filename,
        len(audio_bytes),
        audio_file.content_type,
    )

    if not audio_bytes or len(audio_bytes) < 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Audio file is empty or too short. Please record at least 1 second of speech.",
        )

    if len(audio_bytes) > 50 * 1024 * 1024:  # 50 MB cap
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio file exceeds 50 MB limit.",
        )

    # ── Run synchronous transcription in thread pool ──────────────
    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            transcribe_audio,
            audio_bytes,
            audio_file.filename,
            audio_file.content_type,
        )
        logger.info(
            "Transcription success — transcript_len=%d",
            len(result.get("transcript", "")),
        )
        return result
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except RuntimeError as exc:
        logger.error("Transcription RuntimeError: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        )
    except Exception as exc:
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Transcription failed unexpectedly: {type(exc).__name__}: {exc}",
        )


# ═══════════════════════════════════════════════════════════════════
# GET /interview/topics  (no auth required)
# ═══════════════════════════════════════════════════════════════════

@router.get("/topics")
async def list_topics():
    """
    Return all available interview topics.
    No authentication required — used to populate topic selector UI.
    """
    return {"topics": get_all_topics()}


# ═══════════════════════════════════════════════════════════════════
# POST /interview/upload-resume
# ═══════════════════════════════════════════════════════════════════

@router.post("/upload-resume")
async def upload_resume(
    resume_pdf: UploadFile = File(...),
    payload: dict = Depends(get_token_payload),
):
    """
    Parse an uploaded PDF resume and return a structured context string
    ready to be passed to /interview/start.

    Requires:
        Authorization: Bearer <token>
        Body: multipart form with resume_pdf file (PDF only)

    Returns:
        { resume_context, sections_found, word_count, preview }
    """
    if not resume_pdf.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Only PDF files are accepted for resume upload.",
        )

    pdf_bytes = await resume_pdf.read()
    if len(pdf_bytes) > 5 * 1024 * 1024:   # 5 MB limit
        raise HTTPException(status_code=400, detail="Resume PDF must be under 5 MB.")

    raw_text = extract_text_from_pdf(pdf_bytes)
    if not raw_text:
        raise HTTPException(
            status_code=422,
            detail="Could not extract text from PDF. Try a text-based (non-scanned) PDF.",
        )

    sections       = extract_resume_sections(raw_text)
    resume_context = build_resume_context(sections)

    sections_found = [
        k for k in ("skills", "experience", "projects", "education")
        if sections.get(k)
    ]

    return {
        "resume_context":  resume_context,
        "sections_found":  sections_found,
        "word_count":      len(raw_text.split()),
        "preview":         raw_text[:200],
        "section_counts": {
            "skills":     len(sections.get("skills",     [])),
            "experience": len(sections.get("experience", [])),
            "projects":   len(sections.get("projects",   [])),
            "education":  len(sections.get("education",  [])),
        },
    }


# ═══════════════════════════════════════════════════════════════════
# POST /interview/start  (multipart form)
# ═══════════════════════════════════════════════════════════════════

@router.post("/start")
async def start_interview(
    job_role:            str  = Form("Software Engineering"),
    max_questions:       int  = Form(10),
    time_limit_minutes:  int  = Form(20),
    interview_mode:      str  = Form("topic"),      # "topic" | "resume" | "combined"
    selected_topics:     str  = Form("[]"),          # JSON array string e.g. '["os","dbms"]'
    resume_context:      str  = Form(""),            # pre-parsed context from /upload-resume
    payload: dict            = Depends(get_token_payload),
    db: DBSession            = Depends(get_db),
):
    """
    Initialise an interview session.

    Accepts multipart form so the same endpoint works with or without a resume file.
    The resume context should have been obtained via /interview/upload-resume first.
    """
    candidate_id: str = payload["candidate_id"]
    session_id:   str = payload["session_id"]

    # Validate Ollama
    if not check_ollama_running():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Ollama is not running. Start it with: ollama serve",
        )

    # Clamp parameters
    max_questions      = max(5,  min(20, max_questions))
    time_limit_minutes = max(10, min(60, time_limit_minutes))

    # Parse topics JSON
    try:
        topics_list: list = json.loads(selected_topics) if selected_topics else []
    except json.JSONDecodeError:
        topics_list = []

    # Start LLM session
    try:
        result = start_session(
            session_id          = session_id,
            job_role            = job_role,
            max_questions       = max_questions,
            time_limit_minutes  = time_limit_minutes,
            resume_context      = resume_context,
            selected_topics     = topics_list,
            interview_mode      = interview_mode,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start interview session: {exc}",
        )

    # Audit log
    log_event(
        session_id   = session_id,
        event_type   = "INTERVIEW_STARTED",
        detail       = {
            "candidate_id":   candidate_id,
            "job_role":       job_role,
            "mode":           interview_mode,
            "topics":         topics_list,
            "max_questions":  max_questions,
        },
        db_session   = db,
    )

    # Start background emotion analysis thread
    fq      = Queue(maxsize=10)
    aq      = Queue(maxsize=5)
    stop_ev = threading.Event()

    _frame_queues[session_id]  = fq
    _audio_queues[session_id]  = aq
    _stop_events[session_id]   = stop_ev

    thread = threading.Thread(
        target  = run_emotion_analysis_loop,
        args    = (session_id, fq, aq, emotion_result_store, stop_ev),
        daemon  = True,
        name    = f"emotion-{session_id[:8]}",
    )
    thread.start()
    _emotion_threads[session_id] = thread

    return {
        "session_id":          result["session_id"],
        "first_question":      result["first_question"],
        "difficulty":          result["difficulty"],
        "max_questions":       result["max_questions"],
        "time_limit_minutes":  result["time_limit_minutes"],
        "interview_mode":      result["interview_mode"],
        "selected_topics":     result["selected_topics"],
        "ollama_status":       "connected",
    }





# ═══════════════════════════════════════════════════════════════════
# POST /interview/respond
# ═══════════════════════════════════════════════════════════════════

@router.post("/respond")
async def respond_to_question(
    body:      RespondRequest,
    payload:   dict       = Depends(get_token_payload),
    db:        DBSession  = Depends(get_db),
):
    """
    Submit an answer (text or voice-transcribed) and receive the next question.

    Returns:
        { score, feedback, next_question, difficulty, question_number,
          auto_end, time_elapsed_minutes, questions_remaining }
    """
    session_id: str = payload["session_id"]

    if session_id not in session_store:
        raise HTTPException(
            status_code=400,
            detail="No active interview session found. Call /interview/start first.",
        )

    try:
        result = submit_response(session_id, body.candidate_response)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"LLM evaluation failed: {exc}",
        )

    # Retrieve answered question text for DB logging
    state        = session_store.get(session_id, {})
    history      = state.get("history", [])
    question_text = ""
    for msg in reversed(history):
        if msg["role"] == "assistant":
            question_text = msg["content"][:500]
            break

    # Persist to interview_log
    log_entry = InterviewLog(
        session_id      = session_id,
        question_number = result["question_number"] - 1,
        question_text   = question_text,
        response_text   = body.candidate_response,
        score           = result["score"],
        difficulty      = result["difficulty"],
    )
    db.add(log_entry)
    db.commit()

    # Audit log
    log_event(
        session_id = session_id,
        event_type = "QUESTION_ANSWERED",
        detail     = {
            "question_number": result["question_number"] - 1,
            "score":           result["score"],
            "difficulty":      result["difficulty"],
            "input_mode":      body.input_mode,
        },
        db_session = db,
    )

    return result


# ═══════════════════════════════════════════════════════════════════
# GET /interview/status
# ═══════════════════════════════════════════════════════════════════

@router.get("/status")
async def interview_status(
    payload: dict = Depends(get_token_payload),
):
    """
    Return live session progress: question count, time elapsed, average score, etc.
    """
    session_id: str = payload["session_id"]

    if session_id not in session_store:
        raise HTTPException(status_code=400, detail="No active interview session.")

    try:
        return get_session_status(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ═══════════════════════════════════════════════════════════════════
# POST /interview/execute-code
# ═══════════════════════════════════════════════════════════════════

@router.post("/execute-code")
async def execute_code_endpoint(
    body:    ExecuteCodeRequest,
    payload: dict      = Depends(get_token_payload),
    db:      DBSession = Depends(get_db),
):
    """
    Static-analyse and sandbox-execute candidate code.
    """
    session_id: str = payload["session_id"]
    result = evaluate_code(body.code, body.language, session_id)

    log_event(
        session_id = session_id,
        event_type = "CODE_EXECUTED",
        detail     = {
            "language":            body.language,
            "passed":              result["passed"],
            "timed_out":           result.get("timed_out", False),
            "static_issues_count": len(result.get("static_issues", [])),
        },
        db_session = db,
    )

    return result


# ═══════════════════════════════════════════════════════════════════
# POST /interview/end
# ═══════════════════════════════════════════════════════════════════

@router.post("/end")
async def end_interview(
    payload: dict      = Depends(get_token_payload),
    db:      DBSession = Depends(get_db),
):
    """
    Finalise the interview: compute score, generate LLM feedback, stop threads.

    Returns:
        {
            average_score, recommendation, total_questions, scores,
            time_taken_minutes, interview_mode, topics_covered,
            detailed_feedback: { strengths, weaknesses, topics_to_study, overall_assessment }
        }
    """
    session_id:   str = payload["session_id"]
    candidate_id: str = payload["candidate_id"]

    if session_id not in session_store:
        raise HTTPException(status_code=400, detail="No active interview session to end.")

    try:
        final = end_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # Stop emotion analysis thread
    stop_ev = _stop_events.pop(session_id, None)
    if stop_ev:
        stop_ev.set()
    _frame_queues.pop(session_id, None)
    _audio_queues.pop(session_id, None)
    _emotion_threads.pop(session_id, None)

    # Update session status in DB
    db_session = db.query(SessionModel).filter(SessionModel.id == session_id).first()
    if db_session:
        from datetime import datetime, timezone
        db_session.status      = "COMPLETED"
        db_session.final_score = final["average_score"]
        db_session.ended_at    = datetime.now(timezone.utc)
        db.commit()

    # Audit log
    log_event(
        session_id = session_id,
        event_type = "INTERVIEW_COMPLETED",
        detail     = {
            "candidate_id":   candidate_id,
            "average_score":  final["average_score"],
            "recommendation": final["recommendation"],
            "total_questions":final["total_questions"],
            "mode":           final.get("interview_mode", ""),
        },
        db_session = db,
    )

    # Actually generate and sign the report file so the frontend can download/view it
    try:
        generate_full_report(session_id, db, emotion_result_store, session_store)
    except Exception as exc:
        logger.error(f"Failed to generate report for {session_id}: {exc}")

    return final


# ═══════════════════════════════════════════════════════════════════
# GET /interview/emotion-snapshot
# ═══════════════════════════════════════════════════════════════════

@router.get("/emotion-snapshot")
async def emotion_snapshot(
    payload: dict = Depends(get_token_payload),
):
    session_id: str = payload["session_id"]
    snapshots = emotion_result_store.get(session_id, [])
    return {"session_id": session_id, "snapshots": snapshots, "count": len(snapshots)}
