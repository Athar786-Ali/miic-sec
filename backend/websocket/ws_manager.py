"""
MIIC-Sec — WebSocket Connection Manager
Real-time bidirectional event delivery to candidate and recruiter clients.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


# ─── Event Type Constants ────────────────────────────────────────────────────

STEP_UP_TOTP_REQUIRED  = "STEP_UP_TOTP_REQUIRED"
SESSION_TERMINATED     = "SESSION_TERMINATED"
MULTIPLE_PERSONS_ALERT = "MULTIPLE_PERSONS_ALERT"
MULTIPLE_SPEAKERS_ALERT = "MULTIPLE_SPEAKERS_ALERT"
TAB_SWITCH_WARNING     = "TAB_SWITCH_WARNING"
RECHECK_PASSED         = "RECHECK_PASSED"
CANDIDATE_CONNECTED    = "CANDIDATE_CONNECTED"
INTERVIEW_COMPLETED    = "INTERVIEW_COMPLETED"


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _iso_now() -> str:
    """Return current UTC time as ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()


def _build_message(event: str, data: dict) -> dict:
    """
    Construct the canonical MIIC-Sec WebSocket message envelope.

    Args:
        event:  One of the event-type constants above.
        data:   Arbitrary event payload.

    Returns:
        { "event": str, "data": dict, "timestamp": ISO8601 }
    """
    return {
        "event":     event,
        "data":      data,
        "timestamp": _iso_now(),
    }


# ─── ConnectionManager ────────────────────────────────────────────────────────

class ConnectionManager:
    """
    Manages active WebSocket connections for candidates and recruiters.

    Each session_id maps to at most one candidate WebSocket and one
    recruiter WebSocket.  All send operations are fire-and-forget:
    a missing or disconnected socket is logged but never raises.
    """

    def __init__(self) -> None:
        # { session_id: WebSocket }
        self.candidate_connections: Dict[str, WebSocket] = {}
        self.recruiter_connections: Dict[str, WebSocket] = {}

    # ── Connect / Disconnect ─────────────────────────────────────────────────

    async def connect_candidate(self, session_id: str, websocket: WebSocket) -> None:
        """
        Accept and register a candidate WebSocket for the given session.

        Args:
            session_id: Interview session UUID.
            websocket:  Incoming WebSocket connection.
        """
        await websocket.accept()
        self.candidate_connections[session_id] = websocket
        logger.info("Candidate connected — session=%s", session_id)

        # Immediately notify the candidate that they are connected
        await self.send_to_candidate(
            session_id,
            _build_message(CANDIDATE_CONNECTED, {"session_id": session_id}),
        )

        # Notify recruiter if already connected
        await self.send_to_recruiter(
            session_id,
            _build_message(
                CANDIDATE_CONNECTED,
                {"session_id": session_id, "message": "Candidate has joined the session"},
            ),
        )

    async def connect_recruiter(self, session_id: str, websocket: WebSocket) -> None:
        """
        Accept and register a recruiter WebSocket for the given session.

        Args:
            session_id: Interview session UUID.
            websocket:  Incoming WebSocket connection.
        """
        await websocket.accept()
        self.recruiter_connections[session_id] = websocket
        logger.info("Recruiter connected — session=%s", session_id)

    def disconnect(self, session_id: str, role: str) -> None:
        """
        Remove a WebSocket registration for the given session and role.

        Args:
            session_id: Interview session UUID.
            role:       "candidate" or "recruiter".
        """
        role = role.lower()
        if role == "candidate":
            removed = self.candidate_connections.pop(session_id, None)
        elif role == "recruiter":
            removed = self.recruiter_connections.pop(session_id, None)
        else:
            logger.warning("disconnect() called with unknown role '%s'", role)
            return

        if removed:
            logger.info("Disconnected %s — session=%s", role, session_id)
        else:
            logger.debug("disconnect() called but no %s socket for session=%s", role, session_id)

    # ── Send Helpers ─────────────────────────────────────────────────────────

    async def send_to_candidate(self, session_id: str, message: dict) -> None:
        """
        Send a JSON message to the candidate for the given session.

        If the candidate is not connected the call is silently skipped
        (no exception is raised).

        Args:
            session_id: Interview session UUID.
            message:    Dict conforming to { event, data, timestamp }.
        """
        ws = self.candidate_connections.get(session_id)
        if ws is None:
            logger.warning(
                "send_to_candidate: no candidate socket for session=%s (event=%s)",
                session_id,
                message.get("event", "?"),
            )
            return

        try:
            await ws.send_json(message)
        except Exception as exc:
            logger.warning(
                "send_to_candidate failed — session=%s event=%s: %s",
                session_id, message.get("event"), exc,
            )
            # Remove stale connection
            self.candidate_connections.pop(session_id, None)

    async def send_to_recruiter(self, session_id: str, message: dict) -> None:
        """
        Send a JSON message to the recruiter monitoring the given session.

        If the recruiter is not connected the call is silently skipped.

        Args:
            session_id: Interview session UUID.
            message:    Dict conforming to { event, data, timestamp }.
        """
        ws = self.recruiter_connections.get(session_id)
        if ws is None:
            logger.debug(
                "send_to_recruiter: no recruiter socket for session=%s (event=%s)",
                session_id,
                message.get("event", "?"),
            )
            return

        try:
            await ws.send_json(message)
        except Exception as exc:
            logger.warning(
                "send_to_recruiter failed — session=%s event=%s: %s",
                session_id, message.get("event"), exc,
            )
            self.recruiter_connections.pop(session_id, None)

    # ── Broadcast ────────────────────────────────────────────────────────────

    async def broadcast_security_event(
        self,
        session_id: str,
        event_type: str,
        detail: dict,
    ) -> None:
        """
        Send a security event to both the candidate and the recruiter
        simultaneously (asyncio.gather).

        Args:
            session_id:  Interview session UUID.
            event_type:  One of the event-type constants at module level.
            detail:      Arbitrary event payload dict.
        """
        message = _build_message(event_type, detail)

        await asyncio.gather(
            self.send_to_candidate(session_id, message),
            self.send_to_recruiter(session_id, message),
            return_exceptions=True,   # never raise; log inside send_* methods
        )

        logger.info(
            "Security broadcast — session=%s event=%s",
            session_id, event_type,
        )


# ─── Module-level singleton ───────────────────────────────────────────────────

# Import this singleton in routes and background tasks; do not instantiate
# ConnectionManager yourself.
manager = ConnectionManager()
