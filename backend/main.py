"""
MIIC-Sec — FastAPI Application Entry Point
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from database import init_db

# ─── Real Routers ────────────────────────────────────────────────
from auth.routes import router as auth_router
from interview.routes import router as interview_router
from security.routes import router as security_router

# ─── WebSocket Manager ──────────────────────────────────────────
from websocket.ws_manager import manager as ws_manager

# ─── Placeholder Routers (to be replaced in later phases) ───────
from fastapi import APIRouter

verify_router = APIRouter(prefix="/verify", tags=["Verification"])
report_router = APIRouter(prefix="/report", tags=["Reports"])


# ─── Lifespan ────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""
    # — Startup —
    init_db()
    print("🚀 MIIC-Sec backend started")
    yield
    # — Shutdown —
    print("🛑 MIIC-Sec backend stopped")


# ─── App ─────────────────────────────────────────────────────────

app = FastAPI(
    title="MIIC-Sec",
    description="AI-Powered Secure Interview Platform",
    version="1.0",
    lifespan=lifespan,
)

# ─── CORS ────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Register Routers ───────────────────────────────────────────
app.include_router(auth_router)
app.include_router(interview_router)
app.include_router(security_router)
app.include_router(verify_router)
app.include_router(report_router)


# ─── WebSocket Endpoints ────────────────────────────────────────

@app.websocket("/ws/candidate/{session_id}")
async def websocket_candidate(session_id: str, websocket: WebSocket):
    """
    Persistent WebSocket connection for the candidate.
    Receives real-time security events:
      • STEP_UP_TOTP_REQUIRED  — identity mismatch, enter TOTP
      • SESSION_TERMINATED     — session ended by the system
      • MULTIPLE_PERSONS_ALERT — multiple people detected
      • MULTIPLE_SPEAKERS_ALERT — multiple speakers detected
      • TAB_SWITCH_WARNING     — tab switching warning
      • RECHECK_PASSED         — step-up verification succeeded
      • CANDIDATE_CONNECTED    — connection acknowledgement
      • INTERVIEW_COMPLETED    — interview finished normally

    URL: ws://localhost:8000/ws/candidate/{session_id}
    """
    await ws_manager.connect_candidate(session_id, websocket)
    try:
        while True:
            # Keep connection alive; the server pushes events, no client→server
            # messages are expected on this channel (step-up answers go via REST).
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, "candidate")
    except Exception:
        ws_manager.disconnect(session_id, "candidate")


@app.websocket("/ws/recruiter/{session_id}")
async def websocket_recruiter(session_id: str, websocket: WebSocket):
    """
    Persistent WebSocket connection for the recruiter monitoring a session.
    Receives the same security event stream as the candidate so the
    recruiter can observe in real time.

    URL: ws://localhost:8000/ws/recruiter/{session_id}
    """
    await ws_manager.connect_recruiter(session_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, "recruiter")
    except Exception:
        ws_manager.disconnect(session_id, "recruiter")


# ─── Health Check ────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """Returns service status."""
    return {"status": "ok", "version": "1.0"}
