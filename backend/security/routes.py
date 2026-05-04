"""
MIIC-Sec — Security Routes (Tier 3 / Tier 4)
FastAPI router for browser-side security events:

  POST /security/tab-switch       — candidate switched browser tab
  POST /security/step-up-verify   — candidate submitting step-up TOTP code
"""

import logging
from datetime import datetime, timezone
from typing import Dict

import cv2
import numpy as np
import pyotp
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from auth.jwt_manager import get_current_candidate
from auth.face_auth import verify_face
from crypto.audit_log import log_event
from database import Candidate, Session as DBSession, SessionLocal, get_db
from verification.continuous_verifier import (
    MAX_FAILURES_BEFORE_TERMINATE,
    resolve_step_up,
    terminate_session,
    trigger_step_up_totp,
)
from verification.proxy_detector import ProxyDetector
from websocket.ws_manager import (
    RECHECK_PASSED,
    TAB_SWITCH_WARNING,
    MULTIPLE_PERSONS_ALERT,
    _build_message,
    manager as ws_manager,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/security", tags=["Security"])

# Global proxy detector instance (loads YOLO once)
proxy_detector = ProxyDetector()

# ─── Bearer token extractor ───────────────────────────────────────────────────

_bearer = HTTPBearer()


def _get_payload(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    """Extract and verify the JWT Bearer token; return the decoded payload."""
    return get_current_candidate(creds.credentials)


# ─── In-memory tab-switch counters ────────────────────────────────────────────
#
# Keyed by session_id.  Intentionally in-memory (not persisted to DB) as
# specified — counts reset if the server restarts, which is acceptable for
# an interview session that is always active.
#
_tab_switch_counts: Dict[str, int] = {}

TAB_SWITCH_WARNING_THRESHOLD   = 3   # send warning starting at this count
TAB_SWITCH_TERMINATE_THRESHOLD = 5   # terminate session at this count


# ─── Request / Response models ────────────────────────────────────────────────

class TabSwitchRequest(BaseModel):
    timestamp: str   # ISO 8601 string from the browser


class TabSwitchResponse(BaseModel):
    warning_count: int
    terminated:    bool


class StepUpVerifyRequest(BaseModel):
    totp_code: str


class StepUpVerifyResponse(BaseModel):
    verified:          bool
    remaining_attempts: int = 2   # only meaningful when verified=False


# ═════════════════════════════════════════════════════════════════════════════
# POST /security/tab-switch
# ═════════════════════════════════════════════════════════════════════════════

@router.post(
    "/tab-switch",
    response_model=TabSwitchResponse,
    summary="Report a browser tab-switch event",
)
async def report_tab_switch(
    body:    TabSwitchRequest,
    payload: dict = Depends(_get_payload),
    db=Depends(get_db),
) -> TabSwitchResponse:
    """
    Called by the frontend whenever the candidate switches away from the
    interview tab (via the Page Visibility API).

    Behaviour:
      • Logs a TAB_SWITCH audit entry.
      • Increments an in-memory counter for the session.
      • At count ≥ 3: sends TAB_SWITCH_WARNING via WebSocket.
      • At count ≥ 5: terminates the session.

    Returns:
        { warning_count: int, terminated: bool }
    """
    session_id   = payload.get("session_id", "")
    candidate_id = payload.get("candidate_id", "")

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing session_id in token",
        )

    # ── Validate session is still ACTIVE ─────────────────────────────────────
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    if session.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is already {session.status}",
        )

    # ── Increment counter ─────────────────────────────────────────────────────
    _tab_switch_counts[session_id] = _tab_switch_counts.get(session_id, 0) + 1
    count = _tab_switch_counts[session_id]

    # ── Audit log ─────────────────────────────────────────────────────────────
    try:
        log_event(
            session_id=session_id,
            event_type="TAB_SWITCH",
            detail={
                "candidate_id":    candidate_id,
                "tab_switch_count": count,
                "client_timestamp": body.timestamp,
            },
            db_session=db,
        )
    except Exception as exc:
        logger.error("audit log error in tab_switch: %s", exc)

    logger.info(
        "TAB_SWITCH — session=%s count=%d timestamp=%s",
        session_id, count, body.timestamp,
    )

    terminated = False

    # ── Warning threshold ─────────────────────────────────────────────────────
    if count >= TAB_SWITCH_WARNING_THRESHOLD:
        warning_msg = _build_message(
            TAB_SWITCH_WARNING,
            {
                "session_id":    session_id,
                "switch_count":  count,
                "message": (
                    f"Warning: you have switched tabs {count} time(s). "
                    f"Switching {TAB_SWITCH_TERMINATE_THRESHOLD} times will terminate your session."
                ),
            },
        )
        await ws_manager.send_to_candidate(session_id, warning_msg)
        logger.warning("TAB_SWITCH_WARNING sent — session=%s count=%d", session_id, count)

    # ── Terminate threshold ───────────────────────────────────────────────────
    if count >= TAB_SWITCH_TERMINATE_THRESHOLD:
        await terminate_session(
            session_id=session_id,
            reason=f"Tab switched {count} times (limit {TAB_SWITCH_TERMINATE_THRESHOLD})",
            db_session=db,
            ws_manager=ws_manager,
        )
        terminated = True
        _tab_switch_counts.pop(session_id, None)   # clean up

    return TabSwitchResponse(warning_count=count, terminated=terminated)


# ═════════════════════════════════════════════════════════════════════════════
# POST /security/step-up-verify
# ═════════════════════════════════════════════════════════════════════════════

@router.post(
    "/step-up-verify",
    response_model=StepUpVerifyResponse,
    summary="Verify a step-up TOTP challenge",
)
async def step_up_verify(
    body:    StepUpVerifyRequest,
    payload: dict = Depends(_get_payload),
    db=Depends(get_db),
) -> StepUpVerifyResponse:
    """
    The candidate submits their authenticator TOTP code in response to a
    STEP_UP_TOTP_REQUIRED WebSocket event.

    Behaviour:
      • Verifies the code with pyotp.
      • Correct:
          - Resolves the in-memory future (unblocks the verification loop).
          - Sends RECHECK_PASSED via WebSocket.
          - Logs STEP_UP_PASSED to audit log.
      • Wrong:
          - Increments failure_count in DB.
          - Logs STEP_UP_FAILED to audit log.
          - If failure_count >= 2: terminates the session.
          - Returns remaining_attempts.

    Returns:
        { verified: bool, remaining_attempts: int }
    """
    session_id   = payload.get("session_id", "")
    candidate_id = payload.get("candidate_id", "")

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing session_id in token",
        )

    # ── Load session & candidate ──────────────────────────────────────────────
    session = db.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate or not candidate.totp_secret:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="TOTP not enrolled for this candidate",
        )

    # ── Verify TOTP ───────────────────────────────────────────────────────────
    totp      = pyotp.TOTP(candidate.totp_secret)
    is_valid  = totp.verify(body.totp_code, valid_window=1)

    if is_valid:
        # ── Success path ──────────────────────────────────────────────────────
        # Unblock the waiting continuous_verification_loop (if any)
        resolve_step_up(session_id, True)

        # Notify candidate
        await ws_manager.send_to_candidate(
            session_id,
            _build_message(
                RECHECK_PASSED,
                {"session_id": session_id, "message": "Step-up verification passed."},
            ),
        )

        # Audit
        try:
            log_event(
                session_id=session_id,
                event_type="STEP_UP_PASSED",
                detail={"candidate_id": candidate_id},
                db_session=db,
            )
        except Exception as exc:
            logger.error("audit log error in step_up_verify: %s", exc)

        logger.info("STEP_UP_PASSED — session=%s", session_id)
        return StepUpVerifyResponse(verified=True, remaining_attempts=0)

    else:
        # ── Failure path ──────────────────────────────────────────────────────
        session.failure_count = (session.failure_count or 0) + 1
        db.commit()
        failure_count = session.failure_count

        # Audit
        try:
            log_event(
                session_id=session_id,
                event_type="STEP_UP_FAILED",
                detail={
                    "candidate_id": candidate_id,
                    "failure_count": failure_count,
                },
                db_session=db,
            )
        except Exception as exc:
            logger.error("audit log error in step_up_verify failure: %s", exc)

        logger.warning(
            "STEP_UP_FAILED — session=%s failure_count=%d",
            session_id, failure_count,
        )

        remaining = max(0, MAX_FAILURES_BEFORE_TERMINATE - failure_count)

        if failure_count >= MAX_FAILURES_BEFORE_TERMINATE:
            # Unblock the loop with failure so it can terminate
            resolve_step_up(session_id, False)

            await terminate_session(
                session_id=session_id,
                reason=f"Step-up TOTP failed {failure_count} times",
                db_session=db,
                ws_manager=ws_manager,
            )

        return StepUpVerifyResponse(verified=False, remaining_attempts=remaining)

# ═════════════════════════════════════════════════════════════════════════════
# POST /security/face-recheck
# ═════════════════════════════════════════════════════════════════════════════

@router.post(
    "/face-recheck",
    summary="Continuous background face verification and proxy detection",
)
async def face_recheck(
    frame: UploadFile = File(...),
    payload: dict = Depends(_get_payload),
    db=Depends(get_db),
):
    """
    Receives a webcam frame every ~30s from the frontend.
    1. Runs YOLO to detect multiple persons in the frame.
    2. Runs DeepFace to verify identity against the enrolled face.
    """
    session_id = payload.get("session_id", "")
    candidate_id = payload.get("candidate_id", "")

    if not session_id or not candidate_id:
        raise HTTPException(status_code=400, detail="Missing auth payload")

    # Read image
    img_bytes = await frame.read()
    nparr = np.frombuffer(img_bytes, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if image is None:
        raise HTTPException(status_code=400, detail="Invalid image frame")

    # 1. YOLO Proxy Detection (Multiple Persons)
    try:
        person_count = proxy_detector.analyze_frame(image)
        if person_count > 1:
            logger.warning(f"MULTIPLE PERSONS ({person_count}) detected in session {session_id}")
            # Audit log
            log_event(
                session_id=session_id,
                event_type="MULTIPLE_PERSONS_DETECTED",
                detail={"person_count": person_count},
                db_session=db
            )
            # Notify via websocket
            alert_msg = _build_message(MULTIPLE_PERSONS_ALERT, {"session_id": session_id, "person_count": person_count})
            await ws_manager.send_to_candidate(session_id, alert_msg)
            await ws_manager.send_to_recruiter(session_id, alert_msg)
    except Exception as e:
        logger.error(f"ProxyDetector error: {e}")

    # 2. Face Identity Verification
    try:
        result = verify_face(candidate_id, image, db)
        similarity = result.get("similarity", 0.0)
        
        # Log the check
        log_event(
            session_id=session_id,
            event_type="FACE_RECHECK",
            detail={"similarity": similarity, "verified": result.get("verified")},
            db_session=db
        )

        # Threshold check for Step-Up TOTP (0.35 from config, let's say < 0.35 triggers TOTP)
        import config
        if similarity < config.FACE_SIMILARITY_THRESHOLD:
            logger.warning(f"IDENTITY_MISMATCH in session {session_id} (sim: {similarity:.4f})")
            log_event(
                session_id=session_id,
                event_type="IDENTITY_MISMATCH",
                detail={"similarity": similarity},
                db_session=db
            )
            # Trigger TOTP
            await trigger_step_up_totp(session_id, ws_manager)
            return {"status": "identity_mismatch", "similarity": similarity}
            
    except Exception as e:
        logger.error(f"verify_face error during face-recheck: {e}")
        return {"status": "error", "detail": str(e)}

    return {"status": "ok", "message": "Face recheck passed"}
