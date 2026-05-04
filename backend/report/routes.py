"""
MIIC-Sec — Report Routes
Serve, verify, and download signed interview reports.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt_manager import get_current_candidate
from crypto.report_signer import (
    generate_full_report,
    verify_report_signature,
)

from interview.routes import emotion_result_store
from interview.llm_interviewer import session_store
from database import get_db

router = APIRouter(prefix="/report", tags=["Reports"])
_bearer = HTTPBearer()

REPORTS_DIR = Path("reports")


def _get_payload(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    return get_current_candidate(creds.credentials)


def _report_path(session_id: str) -> Path:
    return REPORTS_DIR / f"{session_id}_report.json"


# ═════════════════════════════════════════════════════════════════════════════
# POST /report/generate
# ═════════════════════════════════════════════════════════════════════════════

@router.post("/generate")
async def generate_report(
    payload: dict = Depends(_get_payload),
    db=Depends(get_db),
):
    """Generate, sign, and save the final report for the current session."""
    session_id = payload["session_id"]
    try:
        result = generate_full_report(session_id, db, emotion_result_store, session_store)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Report generation failed: {exc}")
    return result


# ═════════════════════════════════════════════════════════════════════════════
# GET /report/{session_id}
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/{session_id}")
async def get_report(session_id: str):
    """Return the full signed report JSON for a given session."""
    path = _report_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ═════════════════════════════════════════════════════════════════════════════
# GET /report/{session_id}/verify
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/{session_id}/verify")
async def verify_report(session_id: str):
    """Verify the RSA signature of a saved report."""
    path = _report_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    result = verify_report_signature(str(path))
    return {"valid": result["valid"], "report": result["report"], "verified_at": result["verified_at"]}


# ═════════════════════════════════════════════════════════════════════════════
# GET /report/{session_id}/download
# ═════════════════════════════════════════════════════════════════════════════

@router.get("/{session_id}/download")
async def download_report(session_id: str):
    """Return the report file as a downloadable attachment."""
    path = _report_path(session_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return FileResponse(
        path=str(path),
        media_type="application/json",
        filename=f"{session_id}_report.json",
        headers={"Content-Disposition": f'attachment; filename="{session_id}_report.json"'},
    )
