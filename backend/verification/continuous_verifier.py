"""
MIIC-Sec — Continuous Verification Loop (Tier 3)
Async background task that periodically re-checks the candidate's
identity during an active interview session.

Flow (every 30 seconds):
  1. Grab latest webcam frame from frame_provider.
  2. Run DeepFace verify_face() silently.
  3. If similarity < 0.75 → trigger TOTP step-up challenge.
  4. If step-up fails twice → terminate session.
"""

import asyncio
import logging
from datetime import datetime, timezone

import pyotp

from crypto.audit_log import log_event
from database import Session as DBSession, Candidate
from websocket.ws_manager import (
    ConnectionManager,
    SESSION_TERMINATED,
    STEP_UP_TOTP_REQUIRED,
)

logger = logging.getLogger(__name__)

# ─── Configuration ────────────────────────────────────────────────────────────

IDENTITY_SIMILARITY_THRESHOLD = 0.75   # below → step-up challenge
STEP_UP_TIMEOUT_SECONDS       = 60     # candidate has 60 s to enter TOTP
VERIFICATION_INTERVAL_SECONDS = 30     # re-check period
MAX_FAILURES_BEFORE_TERMINATE = 2      # consecutive failures → terminate


# ─── Session Termination ─────────────────────────────────────────────────────

async def terminate_session(
    session_id: str,
    reason: str,
    db_session,
    ws_manager: ConnectionManager,
) -> None:
    """
    Mark the session as TERMINATED in the database, write an audit entry,
    and notify both the candidate and the recruiter via WebSocket.

    Args:
        session_id:  UUID of the interview session.
        reason:      Human-readable termination reason (stored in audit log).
        db_session:  Active SQLAlchemy session.
        ws_manager:  Module-level ConnectionManager singleton.
    """
    # ── Update DB ────────────────────────────────────────────────────────────
    session = db_session.query(DBSession).filter(DBSession.id == session_id).first()
    if session:
        session.status   = "TERMINATED"
        session.ended_at = datetime.now(timezone.utc)
        db_session.commit()
        logger.info("Session %s marked TERMINATED — reason: %s", session_id, reason)
    else:
        logger.warning("terminate_session: session %s not found in DB", session_id)

    # ── Audit ─────────────────────────────────────────────────────────────────
    try:
        log_event(
            session_id=session_id,
            event_type="SESSION_TERMINATED",
            detail={"reason": reason},
            db_session=db_session,
        )
    except Exception as exc:
        logger.error("audit log failed during termination: %s", exc)

    # ── Notify via WebSocket ──────────────────────────────────────────────────
    payload = {"session_id": session_id, "reason": reason}

    from websocket.ws_manager import _build_message
    msg = _build_message(SESSION_TERMINATED, payload)

    await asyncio.gather(
        ws_manager.send_to_candidate(session_id, msg),
        ws_manager.send_to_recruiter(session_id, msg),
        return_exceptions=True,
    )

    print(f"[MIIC-Sec] ⛔  Session {session_id} TERMINATED — {reason}")


# ─── Step-Up TOTP ────────────────────────────────────────────────────────────

async def trigger_step_up_totp(
    session_id: str,
    ws_manager: ConnectionManager,
) -> None:
    """
    Send a STEP_UP_TOTP_REQUIRED event to the candidate and wait up to
    STEP_UP_TIMEOUT_SECONDS for them to respond via the REST endpoint
    POST /security/step-up-verify.

    The actual verification result is communicated back to the
    continuous_verification_loop via the module-level step_up_results dict.

    Args:
        session_id:  UUID of the interview session.
        ws_manager:  Module-level ConnectionManager singleton.
    """
    from websocket.ws_manager import _build_message

    msg = _build_message(
        STEP_UP_TOTP_REQUIRED,
        {
            "session_id":         session_id,
            "timeout_seconds":    STEP_UP_TIMEOUT_SECONDS,
            "message":            "Identity mismatch detected. Please enter your TOTP code.",
        },
    )

    await ws_manager.send_to_candidate(session_id, msg)
    logger.info("Step-up TOTP triggered for session %s", session_id)


# ─── In-memory result bus ─────────────────────────────────────────────────────
#
# The REST endpoint POST /security/step-up-verify places a True/False result
# here once the candidate submits their TOTP.  The continuous_verification_loop
# uses asyncio.wait_for to poll this dict.
#
step_up_results: dict[str, asyncio.Future] = {}


def resolve_step_up(session_id: str, success: bool) -> None:
    """
    Called by the security route after TOTP verification to unblock the
    waiting continuous_verification_loop.

    Args:
        session_id: UUID of the interview session.
        success:    True if TOTP was correct, False otherwise.
    """
    future = step_up_results.get(session_id)
    if future and not future.done():
        future.get_loop().call_soon_threadsafe(
            future.set_result, success
        )


# ─── TOTP Verification (DB-backed) ───────────────────────────────────────────

async def verify_step_up_totp(
    session_id: str,
    totp_code: str,
    db_session,
) -> bool:
    """
    Load the candidate's TOTP secret from the database (via the session
    record) and verify the submitted code with pyotp.

    Args:
        session_id:  UUID of the interview session.
        totp_code:   6-digit code entered by the candidate.
        db_session:  Active SQLAlchemy session.

    Returns:
        True if the code is correct, False otherwise.
    """
    # Load session → candidate
    session = db_session.query(DBSession).filter(DBSession.id == session_id).first()
    if not session:
        logger.warning("verify_step_up_totp: session %s not found", session_id)
        return False

    candidate = db_session.query(Candidate).filter(
        Candidate.id == session.candidate_id
    ).first()

    if not candidate or not candidate.totp_secret:
        logger.warning(
            "verify_step_up_totp: no TOTP secret for candidate in session %s", session_id
        )
        return False

    totp      = pyotp.TOTP(candidate.totp_secret)
    is_valid  = totp.verify(totp_code, valid_window=1)

    logger.debug(
        "TOTP step-up for session %s — code valid: %s",
        session_id, is_valid,
    )
    return bool(is_valid)


# ─── Continuous Verification Loop ────────────────────────────────────────────

async def continuous_verification_loop(
    session_id: str,
    db_session_factory,
    ws_manager: ConnectionManager,
    frame_provider,
    stop_event: asyncio.Event,
) -> None:
    """
    Asyncio background task — runs for the lifetime of an active session.

    Every VERIFICATION_INTERVAL_SECONDS seconds:
      • Obtains the latest frame from frame_provider (callable → np.ndarray).
      • Silently runs verify_face().
      • If similarity >= 0.75 → logs IDENTITY_VERIFIED and continues.
      • If similarity < 0.75:
          - Logs IDENTITY_MISMATCH.
          - Sends STEP_UP_TOTP_REQUIRED to the candidate.
          - Waits up to 60 seconds for a correct TOTP response.
          - Correct  → logs STEP_UP_PASSED.
          - Wrong/timeout → increments failure_count; if >= 2 → terminates.

    The loop exits cleanly when stop_event is set (session ends normally).

    Args:
        session_id:         UUID of the interview session.
        db_session_factory: Callable that returns a new SQLAlchemy session.
        ws_manager:         Module-level ConnectionManager singleton.
        frame_provider:     Zero-argument async or sync callable returning an
                            np.ndarray (or None if no frame available yet).
        stop_event:         asyncio.Event; set to stop the loop.
    """
    from auth.face_auth import verify_face  # lazy import — avoids circular deps

    logger.info("Continuous verification started — session=%s", session_id)

    # Retrieve the candidate_id once (needs a DB round-trip)
    with db_session_factory() as _init_db:
        session_row = _init_db.query(DBSession).filter(DBSession.id == session_id).first()
        if not session_row:
            logger.error("continuous_verification_loop: session %s not found — aborting", session_id)
            return
        candidate_id = session_row.candidate_id

    while not stop_event.is_set():
        # Wait for the next verification interval (interruptible by stop_event)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=VERIFICATION_INTERVAL_SECONDS)
            # stop_event was set during the wait → exit cleanly
            break
        except asyncio.TimeoutError:
            pass  # Interval elapsed — time to verify

        # ── Obtain frame ─────────────────────────────────────────────────────
        try:
            if asyncio.iscoroutinefunction(frame_provider):
                frame = await frame_provider()
            else:
                frame = frame_provider()
        except Exception as exc:
            logger.warning("frame_provider raised: %s — skipping cycle", exc)
            continue

        if frame is None:
            logger.debug("No frame available for session %s — skipping", session_id)
            continue

        # ── Face verification ─────────────────────────────────────────────────
        with db_session_factory() as db:
            try:
                result     = verify_face(candidate_id, frame, db)
                similarity = result.get("similarity", 0.0)

                log_event(
                    session_id=session_id,
                    event_type="FACE_RECHECK",
                    detail={"similarity": similarity, "verified": result.get("verified")},
                    db_session=db,
                )

            except Exception as exc:
                logger.error("verify_face raised during loop: %s", exc)
                continue

            # ── Similarity OK ─────────────────────────────────────────────────
            if similarity >= IDENTITY_SIMILARITY_THRESHOLD:
                log_event(
                    session_id=session_id,
                    event_type="IDENTITY_VERIFIED",
                    detail={"similarity": similarity},
                    db_session=db,
                )
                logger.info("IDENTITY_VERIFIED — session=%s similarity=%.4f", session_id, similarity)
                continue

            # ── Identity mismatch → step-up challenge ─────────────────────────
            log_event(
                session_id=session_id,
                event_type="IDENTITY_MISMATCH",
                detail={"similarity": similarity},
                db_session=db,
            )
            logger.warning("IDENTITY_MISMATCH — session=%s similarity=%.4f", session_id, similarity)

        # Trigger step-up (outside the DB context to avoid long-held connection)
        await trigger_step_up_totp(session_id, ws_manager)

        # Set up a Future so the REST endpoint can deliver the result
        loop   = asyncio.get_event_loop()
        future = loop.create_future()
        step_up_results[session_id] = future

        # Wait for the candidate to respond within the timeout
        step_up_passed = False
        try:
            step_up_passed = await asyncio.wait_for(
                asyncio.shield(future),
                timeout=STEP_UP_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logger.warning("Step-up TOTP timed out — session=%s", session_id)
        except Exception as exc:
            logger.error("Step-up future error: %s", exc)
        finally:
            step_up_results.pop(session_id, None)

        with db_session_factory() as db:
            if step_up_passed:
                log_event(
                    session_id=session_id,
                    event_type="STEP_UP_PASSED",
                    detail={"similarity": similarity},
                    db_session=db,
                )
                logger.info("STEP_UP_PASSED — session=%s", session_id)
            else:
                # Increment failure count
                session_row = db.query(DBSession).filter(DBSession.id == session_id).first()
                if session_row:
                    session_row.failure_count = (session_row.failure_count or 0) + 1
                    db.commit()
                    failure_count = session_row.failure_count
                else:
                    failure_count = 1

                log_event(
                    session_id=session_id,
                    event_type="STEP_UP_FAILED",
                    detail={"similarity": similarity, "failure_count": failure_count},
                    db_session=db,
                )
                logger.warning(
                    "STEP_UP_FAILED — session=%s failure_count=%d", session_id, failure_count
                )

                if failure_count >= MAX_FAILURES_BEFORE_TERMINATE:
                    await terminate_session(
                        session_id=session_id,
                        reason=f"Identity verification failed {failure_count} times",
                        db_session=db,
                        ws_manager=ws_manager,
                    )
                    stop_event.set()  # Exit the loop

    logger.info("Continuous verification loop stopped — session=%s", session_id)
