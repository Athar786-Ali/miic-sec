"""
MIIC-Sec — Cryptographic Report Signer (Tier 5)
Generates a tamper-evident interview report signed with RSA-2048 / SHA-256.

Flow:
  collect_session_data()  →  sign_report()  →  save_report()
  verify_report_signature() for post-hoc integrity checks.
"""

import base64
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from crypto.audit_log import get_session_audit_log, verify_audit_chain
from database import AuditLog, InterviewLog, Session as DBSession

import config

# ─── Recommendation thresholds ────────────────────────────────────────────────
HIRE_THRESHOLD   = 7.5   # average_score >= 7.5 → HIRE
REVIEW_THRESHOLD = 5.0   # average_score >= 5.0 → REVIEW
                          # otherwise           → REJECT

REPORTS_DIR = Path("reports")


# ═════════════════════════════════════════════════════════════════════════════
# 1. collect_session_data
# ═════════════════════════════════════════════════════════════════════════════

def collect_session_data(
    session_id: str,
    db_session,
    emotion_store: dict,
    interview_store: dict,
) -> dict:
    """
    Assemble the complete report data dict from DB + in-memory stores.

    Args:
        session_id:      Interview session UUID.
        db_session:      Active SQLAlchemy session.
        emotion_store:   Dict keyed by session_id → list of emotion snapshots
                         (from interview.routes.emotion_result_store).
        interview_store: Dict keyed by session_id → session state
                         (from interview.llm_interviewer.session_store).

    Returns:
        Full report dict (unsigned).
    """
    # ── Load session row ──────────────────────────────────────────────────────
    session = db_session.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise ValueError(f"Session {session_id} not found in database")

    candidate_id = session.candidate_id

    # ── Interview log entries ─────────────────────────────────────────────────
    log_entries = (
        db_session.query(InterviewLog)
        .filter(InterviewLog.session_id == session_id)
        .order_by(InterviewLog.question_number.asc())
        .all()
    )

    interview_scores = [
        {
            "question_number": e.question_number,
            "question":        e.question_text or "",
            "response":        e.response_text or "",
            "score":           float(e.score) if e.score is not None else 0.0,
            "difficulty":      e.difficulty or "easy",
            "timestamp":       e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in log_entries
    ]

    scores = [e["score"] for e in interview_scores]
    average_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    # ── Recommendation ────────────────────────────────────────────────────────
    if average_score >= HIRE_THRESHOLD:
        recommendation = "HIRE"
    elif average_score >= REVIEW_THRESHOLD:
        recommendation = "REVIEW"
    else:
        recommendation = "REJECT"

    # ── Audit log entries ─────────────────────────────────────────────────────
    audit_entries = get_session_audit_log(session_id, db_session)
    security_events = [
        {
            "timestamp":  e["timestamp"],
            "event_type": e["event_type"],
            "detail":     e["detail"],
        }
        for e in audit_entries
    ]

    # ── Audit chain validity ──────────────────────────────────────────────────
    chain_result      = verify_audit_chain(session_id, db_session)
    audit_chain_valid = chain_result.get("valid", False)

    # ── Tier 1 result (derived from audit log) ────────────────────────────────
    event_types = {e["event_type"] for e in audit_entries}
    tier_1_result = {
        "face_verified":    "LOGIN_SUCCESS" in event_types,
        "voice_verified":   "LOGIN_SUCCESS" in event_types,
        "totp_verified":    "LOGIN_SUCCESS" in event_types,
        "liveness_passed":  "LOGIN_SUCCESS" in event_types,
    }

    # ── Emotion timeseries ────────────────────────────────────────────────────
    emotion_timeseries = emotion_store.get(session_id, [])

    # ── Merge interview_store override scores (if available) ──────────────────
    # session_store may have richer final data after end_session() is called
    store_state = interview_store.get(session_id, {})
    if store_state.get("scores") and not interview_scores:
        # Fallback: build minimal entries from in-memory scores
        interview_scores = [
            {
                "question_number": i + 1,
                "question":        "",
                "response":        "",
                "score":           float(s),
                "difficulty":      "medium",
                "timestamp":       None,
            }
            for i, s in enumerate(store_state["scores"])
        ]
        scores = store_state["scores"]
        average_score = round(sum(scores) / len(scores), 2) if scores else 0.0

    return {
        "report_id":          str(uuid.uuid4()),
        "session_id":         session_id,
        "candidate_id":       candidate_id,
        "generated_at":       datetime.now(timezone.utc).isoformat(),
        "session_start":      session.started_at.isoformat() if session.started_at else None,
        "session_end":        session.ended_at.isoformat()   if session.ended_at   else None,
        "tier_1_result":      tier_1_result,
        "interview_scores":   interview_scores,
        "average_score":      average_score,
        "recommendation":     recommendation,
        "emotion_timeseries": emotion_timeseries,
        "security_events":    security_events,
        "audit_chain_valid":  audit_chain_valid,
    }


# ═════════════════════════════════════════════════════════════════════════════
# 2. sign_report
# ═════════════════════════════════════════════════════════════════════════════

def sign_report(
    report: dict,
    private_key_path: str = config.PRIVATE_KEY_PATH,
    key_password: bytes    = config.KEY_PASSWORD,
) -> dict:
    """
    Sign the report dict using RSA-2048 PKCS1v15 + SHA-256.

    The entire report (serialised to deterministic JSON) is signed.
    The base64-encoded signature is appended as "report_signature".

    Args:
        report:           Unsigned report dict.
        private_key_path: Path to PEM private key file.
        key_password:     Password used to decrypt the PEM file.

    Returns:
        Report dict with "report_signature" field appended.
    """
    # Deterministic serialisation (no signature field present yet)
    report_json = json.dumps(report, sort_keys=True, default=str).encode("utf-8")

    # Load private key
    with open(private_key_path, "rb") as f:
        private_key = serialization.load_pem_private_key(
            f.read(),
            password=key_password,
        )

    # Sign
    signature = private_key.sign(
        report_json,
        padding.PKCS1v15(),
        hashes.SHA256(),
    )

    # Encode and attach
    signed_report = dict(report)
    signed_report["report_signature"] = base64.b64encode(signature).decode("utf-8")

    return signed_report


# ═════════════════════════════════════════════════════════════════════════════
# 3. save_report
# ═════════════════════════════════════════════════════════════════════════════

def save_report(signed_report: dict, session_id: str) -> str:
    """
    Persist the signed report to disk as JSON.

    File location: reports/{session_id}_report.json

    Args:
        signed_report: Signed report dict (includes report_signature).
        session_id:    Interview session UUID (used in filename).

    Returns:
        Absolute path string of the saved file.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    file_path = REPORTS_DIR / f"{session_id}_report.json"
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(signed_report, f, indent=2, default=str)

    return str(file_path.resolve())


# ═════════════════════════════════════════════════════════════════════════════
# 4. verify_report_signature
# ═════════════════════════════════════════════════════════════════════════════

def verify_report_signature(
    report_path: str,
    public_key_path: str = config.PUBLIC_KEY_PATH,
) -> dict:
    """
    Load a saved report from disk and verify its RSA signature.

    Steps:
      1. Load JSON from disk.
      2. Pop "report_signature" field.
      3. Re-serialise remaining report (sort_keys=True).
      4. Verify signature using the RSA public key.

    Args:
        report_path:     Path to the saved report JSON file.
        public_key_path: Path to PEM public key file.

    Returns:
        { "valid": bool, "report": dict, "verified_at": ISO8601 }
    """
    with open(report_path, "r", encoding="utf-8") as f:
        report = json.load(f)

    # Extract and decode signature
    sig_b64 = report.pop("report_signature", None)
    if sig_b64 is None:
        return {
            "valid":       False,
            "report":      report,
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "error":       "No report_signature field found",
        }

    signature = base64.b64decode(sig_b64)

    # Re-serialise without the signature
    report_json = json.dumps(report, sort_keys=True, default=str).encode("utf-8")

    # Load public key
    with open(public_key_path, "r", encoding="utf-8") as f:
        public_key = serialization.load_pem_public_key(f.read().encode("utf-8"))

    # Verify
    try:
        public_key.verify(
            signature,
            report_json,
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
        valid = True
    except Exception:
        valid = False

    return {
        "valid":       valid,
        "report":      report,
        "verified_at": datetime.now(timezone.utc).isoformat(),
    }


# ═════════════════════════════════════════════════════════════════════════════
# 5. generate_full_report  (orchestrator)
# ═════════════════════════════════════════════════════════════════════════════

def generate_full_report(
    session_id: str,
    db_session,
    emotion_store: dict,
    interview_store: dict,
) -> dict:
    """
    Full pipeline: collect → sign → save.

    Args:
        session_id:      Interview session UUID.
        db_session:      Active SQLAlchemy session.
        emotion_store:   In-memory emotion timeseries store.
        interview_store: In-memory LLM session store.

    Returns:
        { "report_path": str, "report_id": str, "recommendation": str }
    """
    report        = collect_session_data(session_id, db_session, emotion_store, interview_store)
    signed_report = sign_report(report)
    report_path   = save_report(signed_report, session_id)

    print(
        f"[MIIC-Sec] 📄 Report generated — "
        f"session={session_id} "
        f"recommendation={report['recommendation']} "
        f"path={report_path}"
    )

    return {
        "report_path":    report_path,
        "report_id":      report["report_id"],
        "recommendation": report["recommendation"],
    }
