"""
MIIC-Sec — Student Dashboard API
GET /user/dashboard — Returns candidate profile, aggregate stats, and interview history.
GET /user/progress  — Returns topic-wise performance data (Phase 2).
"""
import json
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from database import get_db, Candidate, Session as DBSession, AuditLog, InterviewLog
from auth.jwt_manager import get_token_payload
from interview.topic_tracker import get_progress_data

router = APIRouter(prefix="/user", tags=["Dashboard"])


# ═══════════════════════════════════════════════════════════════════
# GET /user/dashboard
# ═══════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def get_dashboard(
    payload: dict = Depends(get_token_payload),
    db=Depends(get_db),
):
    """
    Return a complete student dashboard payload.

    Returns:
        {
            candidate: { id, name, email, member_since },
            stats: { total_interviews, average_score, best_score, interviews_this_month },
            sessions: [...],
            streak_days: int,
        }
    """
    candidate_id: str = payload["candidate_id"]

    # ── Fetch candidate ──────────────────────────────────────────
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # ── Fetch all COMPLETED sessions ─────────────────────────────
    sessions_rows = (
        db.query(DBSession)
        .filter(
            DBSession.candidate_id == candidate_id,
            DBSession.status == "COMPLETED",
        )
        .order_by(DBSession.started_at.desc())
        .all()
    )

    # ── For each session, pull job_role / company_target from audit log ──
    sessions_out = []
    all_scores   = []

    now = datetime.now(timezone.utc)

    for s in sessions_rows:
        score = float(s.final_score) if s.final_score is not None else 0.0
        all_scores.append(score)

        # Pull INTERVIEW_STARTED audit event for metadata
        audit_row = (
            db.query(AuditLog)
            .filter(
                AuditLog.session_id == s.id,
                AuditLog.event_type == "INTERVIEW_STARTED",
            )
            .first()
        )
        meta = {}
        if audit_row and audit_row.detail:
            try:
                meta = json.loads(audit_row.detail)
            except Exception:
                meta = {}

        # Count questions answered
        q_count = (
            db.query(InterviewLog)
            .filter(InterviewLog.session_id == s.id)
            .count()
        )

        # Compute duration
        duration = None
        if s.started_at and s.ended_at:
            duration = round((s.ended_at - s.started_at).total_seconds() / 60, 1)

        # Map score to recommendation using the new student-centric labels
        if score >= 7.5:
            recommendation = "EXCELLENT"
        elif score >= 5.0:
            recommendation = "NEEDS PRACTICE"
        else:
            recommendation = "POOR"

        sessions_out.append({
            "session_id":       s.id,
            "date":             s.started_at.isoformat() if s.started_at else None,
            "final_score":      score,
            "recommendation":   recommendation,
            "job_role":         meta.get("job_role", "Software Engineering"),
            "interview_mode":   meta.get("mode", "topic"),
            "company_target":   meta.get("company_target", ""),
            "duration_minutes": duration,
            "question_count":   q_count,
            "pressure_mode":    s.pressure_mode or "practice",
        })

    # ── Aggregate stats ──────────────────────────────────────────
    total_interviews = len(all_scores)
    average_score    = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
    best_score       = round(max(all_scores), 2) if all_scores else 0.0

    # Interviews this month
    this_month = sum(
        1 for s in sessions_rows
        if s.started_at and s.started_at.year == now.year and s.started_at.month == now.month
    )

    # ── Practice streak (Phase 6) ─────────────────────────────────
    streak_days = _compute_streak(sessions_rows, now)

    return {
        "candidate": {
            "id":            candidate_id,
            "name":          candidate.name,
            "email":         candidate.email,
            "member_since":  candidate.created_at.isoformat() if candidate.created_at else None,
        },
        "stats": {
            "total_interviews":      total_interviews,
            "average_score":         average_score,
            "best_score":            best_score,
            "interviews_this_month": this_month,
        },
        "sessions": sessions_out,
        "streak_days": streak_days,
    }


def _compute_streak(sessions_rows, now: datetime) -> int:
    """Compute consecutive days with at least one completed session (looking back from today)."""
    if not sessions_rows:
        return 0
    # Get unique dates of completed sessions (UTC date)
    session_dates = set()
    for s in sessions_rows:
        if s.started_at:
            dt = s.started_at
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            session_dates.add(dt.date())

    streak = 0
    check_date = now.date()
    while check_date in session_dates:
        streak += 1
        check_date -= timedelta(days=1)
    return streak


# ═══════════════════════════════════════════════════════════════════
# GET /user/progress  (Phase 2)
# ═══════════════════════════════════════════════════════════════════

@router.get("/progress")
async def get_progress(
    payload: dict = Depends(get_token_payload),
    db=Depends(get_db),
):
    """
    Return topic-wise performance analytics.

    Returns:
        {
            topics: [{topic, avg_score, attempt_count, trend_last_5}],
            weak_topics: [top-3 lowest (with tip)],
            strong_topics: [top-3 highest],
            overall_trend: [{date, score}],
            improved_topics: [topic names with upward trend],
        }
    """
    candidate_id: str = payload["candidate_id"]
    return get_progress_data(candidate_id, db)


# ═══════════════════════════════════════════════════════════════════
# GET /user/progress/pdf  (Phase 5)
# ═══════════════════════════════════════════════════════════════════

@router.get("/progress/pdf")
async def download_growth_pdf(
    payload: dict = Depends(get_token_payload),
    db=Depends(get_db),
):
    """
    Generate and download a cumulative Growth Report PDF.
    """
    candidate_id: str = payload["candidate_id"]
    try:
        from report.pdf_export import generate_growth_pdf
        path = generate_growth_pdf(candidate_id, db)
        return FileResponse(
            path,
            media_type="application/pdf",
            filename=f"miic_growth_report_{candidate_id[:8]}.pdf",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")



# ═══════════════════════════════════════════════════════════════════
# GET /user/dashboard
# ═══════════════════════════════════════════════════════════════════

@router.get("/dashboard")
async def get_dashboard(
    payload: dict = Depends(get_token_payload),
    db=Depends(get_db),
):
    """
    Return a complete student dashboard payload.

    Returns:
        {
            candidate: { id, name, email, member_since },
            stats: { total_interviews, average_score, best_score, interviews_this_month },
            sessions: [
                {
                    session_id, date, final_score, recommendation,
                    job_role, interview_mode, company_target, duration_minutes,
                    question_count
                },
                ...
            ]
        }
    """
    candidate_id: str = payload["candidate_id"]

    # ── Fetch candidate ──────────────────────────────────────────
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # ── Fetch all COMPLETED sessions ─────────────────────────────
    sessions_rows = (
        db.query(DBSession)
        .filter(
            DBSession.candidate_id == candidate_id,
            DBSession.status == "COMPLETED",
        )
        .order_by(DBSession.started_at.desc())
        .all()
    )

    # ── For each session, pull job_role / company_target from audit log ──
    sessions_out = []
    all_scores   = []

    now = datetime.now(timezone.utc)

    for s in sessions_rows:
        score = float(s.final_score) if s.final_score is not None else 0.0
        all_scores.append(score)

        # Pull INTERVIEW_STARTED audit event for metadata
        audit_row = (
            db.query(AuditLog)
            .filter(
                AuditLog.session_id == s.id,
                AuditLog.event_type == "INTERVIEW_STARTED",
            )
            .first()
        )
        meta = {}
        if audit_row and audit_row.detail:
            try:
                meta = json.loads(audit_row.detail)
            except Exception:
                meta = {}

        # Count questions answered
        q_count = (
            db.query(InterviewLog)
            .filter(InterviewLog.session_id == s.id)
            .count()
        )

        # Compute duration
        duration = None
        if s.started_at and s.ended_at:
            duration = round((s.ended_at - s.started_at).total_seconds() / 60, 1)

        # Map score to recommendation using the new student-centric labels
        if score >= 7.5:
            recommendation = "EXCELLENT"
        elif score >= 5.0:
            recommendation = "NEEDS PRACTICE"
        else:
            recommendation = "POOR"

        sessions_out.append({
            "session_id":       s.id,
            "date":             s.started_at.isoformat() if s.started_at else None,
            "final_score":      score,
            "recommendation":   recommendation,
            "job_role":         meta.get("job_role", "Software Engineering"),
            "interview_mode":   meta.get("mode", "topic"),
            "company_target":   meta.get("company_target", ""),
            "duration_minutes": duration,
            "question_count":   q_count,
        })

    # ── Aggregate stats ──────────────────────────────────────────
    total_interviews = len(all_scores)
    average_score    = round(sum(all_scores) / len(all_scores), 2) if all_scores else 0.0
    best_score       = round(max(all_scores), 2) if all_scores else 0.0

    # Interviews this month
    this_month = sum(
        1 for s in sessions_rows
        if s.started_at and s.started_at.year == now.year and s.started_at.month == now.month
    )

    return {
        "candidate": {
            "id":            candidate_id,
            "name":          candidate.name,
            "email":         candidate.email,
            "member_since":  candidate.created_at.isoformat() if candidate.created_at else None,
        },
        "stats": {
            "total_interviews":      total_interviews,
            "average_score":         average_score,
            "best_score":            best_score,
            "interviews_this_month": this_month,
        },
        "sessions": sessions_out,
    }
