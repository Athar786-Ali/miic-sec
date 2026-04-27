"""
MIIC-Sec — Audit Log with SHA-256 Hash Chaining
Tamper-proof event logging for interview sessions.
"""

import hashlib
import json
from datetime import datetime, timezone

from database import AuditLog


def get_last_hash(session_id: str, db_session) -> str:
    """
    Get the entry_hash of the last audit log entry for a session.

    Args:
        session_id: Session UUID.
        db_session: SQLAlchemy DB session.

    Returns:
        Last entry_hash, or "0" * 64 (genesis hash) if no entries.
    """
    last_entry = (
        db_session.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.desc())
        .first()
    )

    if last_entry:
        return last_entry.entry_hash

    return "0" * 64  # Genesis hash


def log_event(
    session_id: str,
    event_type: str,
    detail: dict,
    db_session,
) -> dict:
    """
    Log an event with SHA-256 hash chaining.

    Each entry's hash is computed from: session_id, event_type,
    detail, timestamp, and the previous entry's hash — forming
    a tamper-evident chain.

    Args:
        session_id: Session UUID.
        event_type: Type of event (e.g., LOGIN_SUCCESS, FACE_CHECK).
        detail: Event details as dict (stored as JSON string).
        db_session: SQLAlchemy DB session.

    Returns:
        Saved entry as dict.
    """
    # Get previous hash
    previous_hash = get_last_hash(session_id, db_session)

    # Build entry content for hashing
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")
    entry_content = {
        "session_id": session_id,
        "event_type": event_type,
        "detail": detail,
        "timestamp": timestamp,
        "previous_hash": previous_hash,
    }

    # Compute SHA-256 hash
    content_str = json.dumps(entry_content, sort_keys=True)
    entry_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

    # Save to database
    log_entry = AuditLog(
        session_id=session_id,
        event_type=event_type,
        detail=json.dumps(detail),
        previous_hash=previous_hash,
        entry_hash=entry_hash,
        timestamp=datetime.fromisoformat(timestamp),
    )
    db_session.add(log_entry)
    db_session.commit()

    return {
        "id": log_entry.id,
        "session_id": session_id,
        "event_type": event_type,
        "detail": detail,
        "previous_hash": previous_hash,
        "entry_hash": entry_hash,
        "timestamp": timestamp,
    }


def get_session_audit_log(session_id: str, db_session) -> list[dict]:
    """
    Retrieve all audit log entries for a session, ordered by ID.

    Args:
        session_id: Session UUID.
        db_session: SQLAlchemy DB session.

    Returns:
        List of entry dicts.
    """
    entries = (
        db_session.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.asc())
        .all()
    )

    return [
        {
            "id": e.id,
            "session_id": e.session_id,
            "event_type": e.event_type,
            "detail": json.loads(e.detail) if e.detail else {},
            "previous_hash": e.previous_hash,
            "entry_hash": e.entry_hash,
            "timestamp": e.timestamp.isoformat() if e.timestamp else None,
        }
        for e in entries
    ]


def verify_audit_chain(session_id: str, db_session) -> dict:
    """
    Verify the integrity of the hash chain for a session.

    Re-computes all hashes from scratch and compares with stored values.

    Args:
        session_id: Session UUID.
        db_session: SQLAlchemy DB session.

    Returns:
        { "valid": bool, "broken_at_entry": int | None, "total_entries": int }
    """
    entries = (
        db_session.query(AuditLog)
        .filter(AuditLog.session_id == session_id)
        .order_by(AuditLog.id.asc())
        .all()
    )

    if not entries:
        return {"valid": True, "broken_at_entry": None, "total_entries": 0}

    expected_previous_hash = "0" * 64  # Genesis hash

    for i, entry in enumerate(entries):
        # Check previous_hash linkage
        if entry.previous_hash != expected_previous_hash:
            return {
                "valid": False,
                "broken_at_entry": entry.id,
                "total_entries": len(entries),
            }

        # Re-compute hash
        detail = json.loads(entry.detail) if entry.detail else {}
        entry_content = {
            "session_id": entry.session_id,
            "event_type": entry.event_type,
            "detail": detail,
            "timestamp": entry.timestamp.strftime("%Y-%m-%dT%H:%M:%S.%f") if entry.timestamp else "",
            "previous_hash": entry.previous_hash,
        }
        content_str = json.dumps(entry_content, sort_keys=True)
        recomputed_hash = hashlib.sha256(content_str.encode("utf-8")).hexdigest()

        if recomputed_hash != entry.entry_hash:
            return {
                "valid": False,
                "broken_at_entry": entry.id,
                "total_entries": len(entries),
            }

        expected_previous_hash = entry.entry_hash

    return {
        "valid": True,
        "broken_at_entry": None,
        "total_entries": len(entries),
    }
