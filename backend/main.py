"""
MIIC-Sec — FastAPI Application Entry Point (Final)
All 5 security tiers wired together.
"""

import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# Load .env before any module reads os.environ
from pathlib import Path as _Path
_env_file = _Path(__file__).parent / ".env"
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# Fix macOS segmentation faults with Objective-C frameworks (OpenCV / TF)
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
# Prevent HuggingFace tokenizer deadlocks in forked workers
os.environ["TOKENIZERS_PARALLELISM"] = "false"


from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from database import init_db

# ─── Routers ─────────────────────────────────────────────────────────────────
from auth.routes      import router as auth_router
from interview.routes import router as interview_router
from security.routes  import router as security_router
from report.routes    import router as report_router

# ─── WebSocket Manager ───────────────────────────────────────────────────────
from websocket.ws_manager import manager as ws_manager

# ─── Verify placeholder router (no-op; real endpoints live in verification/) ─
from fastapi import APIRouter
verify_router = APIRouter(prefix="/verify", tags=["Verification"])


# ═════════════════════════════════════════════════════════════════════════════
# Key generation utility
# ═════════════════════════════════════════════════════════════════════════════

def _ensure_rsa_keys() -> None:
    """Generate RSA-2048 keypair if the key files do not already exist."""
    import config
    from pathlib import Path
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    priv_path = Path(config.PRIVATE_KEY_PATH)
    pub_path  = Path(config.PUBLIC_KEY_PATH)

    if priv_path.exists() and pub_path.exists():
        return

    print("🔑 RSA keypair not found — generating...")
    priv_path.parent.mkdir(parents=True, exist_ok=True)

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    # Persist private key (encrypted)
    with open(priv_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(config.KEY_PASSWORD),
            )
        )

    # Persist public key (plain PEM)
    with open(pub_path, "wb") as f:
        f.write(
            private_key.public_key().public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )

    print(f"   ✅ Keys written to {priv_path} / {pub_path}")


def _check_ollama() -> bool:
    """Return True if the local Ollama server is responding."""
    try:
        import requests as req
        import config
        r = req.get(f"{config.OLLAMA_URL}/api/tags", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


# ═════════════════════════════════════════════════════════════════════════════
# Lifespan
# ═════════════════════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle."""

    # ── Startup ──────────────────────────────────────────────────────────────
    init_db()
    _ensure_rsa_keys()

    ollama_ok = _check_ollama()
    hf_token  = bool(os.environ.get("HF_TOKEN", "").strip())

    # System status table
    print("\n" + "═" * 52)
    print("  MIIC-Sec — System Status")
    print("═" * 52)
    print(f"  {'Database':30s}  ✅ ready")
    print(f"  {'RSA-2048 keys':30s}  ✅ ready")
    print(f"  {'Ollama LLM':30s}  {'✅ connected' if ollama_ok else '⚠️  not running'}")
    print(f"  {'Speaker diarization (HF_TOKEN)':30s}  {'✅ enabled' if hf_token else '⚠️  disabled'}")
    print("═" * 52)
    print(f"  Docs:  http://localhost:8000/docs")
    print(f"  WS:    ws://localhost:8000/ws/candidate/{{session_id}}")
    print("═" * 52 + "\n")

    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    # Close all open WebSocket connections gracefully
    all_sessions = (
        set(ws_manager.candidate_connections.keys()) |
        set(ws_manager.recruiter_connections.keys())
    )
    for sid in all_sessions:
        ws_manager.disconnect(sid, "candidate")
        ws_manager.disconnect(sid, "recruiter")

    print("🛑 MIIC-Sec backend stopped")


# ═════════════════════════════════════════════════════════════════════════════
# App
# ═════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="MIIC-Sec",
    description=(
        "AI-Powered Secure Interview Platform — "
        "5-tier cryptographic identity verification system."
    ),
    version="1.0",
    lifespan=lifespan,
)


# ─── Global exception handler ────────────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Return a structured JSON error for any unhandled exception."""
    return JSONResponse(
        status_code=500,
        content={
            "error":     type(exc).__name__,
            "detail":    str(exc),
            "path":      str(request.url),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    )


# ─── CORS ────────────────────────────────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routers ─────────────────────────────────────────────────────────────────

app.include_router(auth_router)
app.include_router(interview_router)
app.include_router(security_router)
app.include_router(report_router)
app.include_router(verify_router)


# ═════════════════════════════════════════════════════════════════════════════
# WebSocket Endpoints
# ═════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/candidate/{session_id}")
async def websocket_candidate(session_id: str, websocket: WebSocket):
    """
    Real-time event stream for the candidate.

    Events pushed from server:
      CANDIDATE_CONNECTED       — connection acknowledged
      STEP_UP_TOTP_REQUIRED     — identity mismatch; submit TOTP via REST
      SESSION_TERMINATED        — session ended by the security system
      MULTIPLE_PERSONS_ALERT    — extra person detected by YOLO
      MULTIPLE_SPEAKERS_ALERT   — extra speaker detected by pyannote
      TAB_SWITCH_WARNING        — tab-switch count approaching limit
      RECHECK_PASSED            — step-up TOTP accepted
      INTERVIEW_COMPLETED       — interview ended normally

    URL: ws://localhost:8000/ws/candidate/{session_id}
    """
    await ws_manager.connect_candidate(session_id, websocket)
    try:
        while True:
            # Server-push channel — ignore any client messages
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(session_id, "candidate")
    except Exception:
        ws_manager.disconnect(session_id, "candidate")


@app.websocket("/ws/recruiter/{session_id}")
async def websocket_recruiter(session_id: str, websocket: WebSocket):
    """
    Real-time event mirror for the recruiter monitoring a session.

    Receives the same security event stream as the candidate.

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


# ─── Health Check ─────────────────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """Returns service health status."""
    return {
        "status":    "ok",
        "version":   "1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
