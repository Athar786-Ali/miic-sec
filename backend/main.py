"""
MIIC-Sec — FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import init_db

# ─── Real Routers ────────────────────────────────────────────────
from auth.routes import router as auth_router

# ─── Placeholder Routers (to be replaced in later phases) ───────
from fastapi import APIRouter

interview_router = APIRouter(prefix="/interview", tags=["Interview"])
verify_router = APIRouter(prefix="/verify", tags=["Verification"])
report_router = APIRouter(prefix="/report", tags=["Reports"])
security_router = APIRouter(prefix="/security", tags=["Security"])


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
app.include_router(verify_router)
app.include_router(report_router)
app.include_router(security_router)


# ─── Health Check ────────────────────────────────────────────────

@app.get("/health", tags=["System"])
async def health_check():
    """Returns service status."""
    return {"status": "ok", "version": "1.0"}
