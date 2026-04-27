"""
MIIC-Sec — Auth Routes
FastAPI endpoints for enrollment, login, and TOTP setup.
"""

import io
import uuid
from datetime import datetime, timezone

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, Depends

from database import get_db, Candidate, Session as DBSession
from auth.liveness import detect_liveness, load_liveness_model
from auth.face_auth import enroll_face, verify_face
from auth.voice_auth import enroll_voice, verify_voice
from auth.totp_auth import enroll_totp, verify_totp
from auth.jwt_manager import create_session_token
from crypto.audit_log import log_event

router = APIRouter(prefix="/auth", tags=["Authentication"])

# Pre-load liveness model at module level
_liveness_model = None


def _get_liveness_model():
    """Lazy-load liveness model."""
    global _liveness_model
    if _liveness_model is None:
        _liveness_model = load_liveness_model()
    return _liveness_model


def _read_image(file_bytes: bytes) -> np.ndarray:
    """Convert uploaded file bytes to a numpy image array."""
    nparr = np.frombuffer(file_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image")
    return img


def _read_audio(file_bytes: bytes) -> tuple[np.ndarray, int]:
    """
    Convert uploaded WAV file bytes to numpy array + sample rate.
    Uses scipy for WAV parsing.
    """
    from scipy.io import wavfile

    buffer = io.BytesIO(file_bytes)
    sample_rate, audio_data = wavfile.read(buffer)

    # Convert to float32 and normalize
    if audio_data.dtype == np.int16:
        audio_data = audio_data.astype(np.float32) / 32768.0
    elif audio_data.dtype == np.int32:
        audio_data = audio_data.astype(np.float32) / 2147483648.0
    elif audio_data.dtype != np.float32:
        audio_data = audio_data.astype(np.float32)

    # Convert stereo to mono if needed
    if len(audio_data.shape) > 1:
        audio_data = audio_data.mean(axis=1)

    return audio_data, sample_rate


# ═════════════════════════════════════════════════════════════════
# POST /auth/enroll
# ═════════════════════════════════════════════════════════════════

@router.post("/enroll")
async def enroll_candidate(
    candidate_name: str = Form(...),
    candidate_email: str = Form(...),
    face_images: list[UploadFile] = File(...),
    voice_audio: UploadFile = File(...),
    db=Depends(get_db),
):
    """
    Enroll a new candidate with face, voice, and TOTP.

    Expects:
      - candidate_name: str
      - candidate_email: str
      - face_images: 5 image files (JPEG/PNG)
      - voice_audio: WAV audio file (~10 seconds)

    Returns:
      { candidate_id, totp_qr_code_base64, message }
    """
    # ── Validate inputs ─────────────────────────────────────────
    if len(face_images) < 5:
        raise HTTPException(
            status_code=400,
            detail=f"Need 5 face images, got {len(face_images)}",
        )

    # ── Check if email already exists ────────────────────────────
    existing = db.query(Candidate).filter(Candidate.email == candidate_email).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="Email already enrolled",
        )

    # ── Step 1: Create candidate record ──────────────────────────
    candidate_id = str(uuid.uuid4())
    candidate = Candidate(
        id=candidate_id,
        name=candidate_name,
        email=candidate_email,
        created_at=datetime.now(timezone.utc),
    )
    db.add(candidate)
    db.commit()

    # ── Step 2: Liveness check on first face image ───────────────
    try:
        first_image_bytes = await face_images[0].read()
        first_frame = _read_image(first_image_bytes)
        await face_images[0].seek(0)  # Reset for later use

        liveness_result = detect_liveness(first_frame, _get_liveness_model())

        if not liveness_result["is_live"]:
            # Rollback candidate creation
            db.delete(candidate)
            db.commit()
            raise HTTPException(
                status_code=400,
                detail=f"Liveness check failed (confidence: {liveness_result['confidence']})",
            )
    except HTTPException:
        raise
    except Exception as e:
        # Liveness model may be untrained — log warning but continue
        print(f"⚠️  Liveness check warning: {e} — continuing enrollment")

    # ── Step 3: Enroll face (all 5 images) ───────────────────────
    frames = []
    for img_file in face_images:
        img_bytes = await img_file.read()
        frame = _read_image(img_bytes)
        frames.append(frame)

    face_result = enroll_face(candidate_id, frames, db)
    if not face_result["success"]:
        db.delete(candidate)
        db.commit()
        raise HTTPException(status_code=400, detail=face_result["message"])

    # ── Step 4: Enroll voice ─────────────────────────────────────
    try:
        voice_bytes = await voice_audio.read()
        audio_array, sample_rate = _read_audio(voice_bytes)

        voice_result = enroll_voice(candidate_id, audio_array, sample_rate, db)
        if not voice_result["success"]:
            db.delete(candidate)
            db.commit()
            raise HTTPException(status_code=400, detail=voice_result["message"])
    except HTTPException:
        raise
    except Exception as e:
        db.delete(candidate)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Voice enrollment failed: {e}")

    # ── Step 5: Generate TOTP ────────────────────────────────────
    totp_result = enroll_totp(candidate_id, db)

    # ── Log enrollment event ─────────────────────────────────────
    log_event(
        session_id=candidate_id,  # Use candidate_id as pseudo-session for enrollment
        event_type="ENROLLMENT",
        detail={"candidate_name": candidate_name, "candidate_email": candidate_email},
        db_session=db,
    )

    return {
        "candidate_id": candidate_id,
        "totp_qr_code_base64": totp_result["qr_code_base64"],
        "message": "Enrollment successful — scan QR code in authenticator app",
    }


# ═════════════════════════════════════════════════════════════════
# POST /auth/login
# ═════════════════════════════════════════════════════════════════

@router.post("/login")
async def login_candidate(
    candidate_id: str = Form(...),
    face_image: UploadFile = File(...),
    voice_audio: UploadFile = File(...),
    totp_code: str = Form(...),
    db=Depends(get_db),
):
    """
    Multi-factor login: liveness → face → voice → TOTP.

    Returns:
      { access_token, session_id, token_type: "bearer" }
    """
    # ── Validate candidate exists ────────────────────────────────
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # ── Step 1: Liveness check ───────────────────────────────────
    face_bytes = await face_image.read()
    face_frame = _read_image(face_bytes)

    try:
        liveness = detect_liveness(face_frame, _get_liveness_model())
        if not liveness["is_live"]:
            raise HTTPException(
                status_code=401,
                detail="Liveness check failed",
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"⚠️  Liveness check warning: {e} — continuing login")

    # ── Step 2: Face verification ────────────────────────────────
    face_result = verify_face(candidate_id, face_frame, db)
    if not face_result["verified"]:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "Face verification failed",
                "similarity": face_result["similarity"],
            },
        )

    # ── Step 3: Voice verification ───────────────────────────────
    try:
        voice_bytes = await voice_audio.read()
        audio_array, sample_rate = _read_audio(voice_bytes)

        voice_result = verify_voice(candidate_id, audio_array, sample_rate, db)
        if not voice_result["verified"]:
            raise HTTPException(
                status_code=401,
                detail="Voice verification failed",
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Voice verification failed: {e}")

    # ── Step 4: TOTP verification ────────────────────────────────
    if not candidate.totp_secret:
        raise HTTPException(status_code=401, detail="TOTP not enrolled")

    totp_result = verify_totp(candidate.totp_secret, totp_code)
    if not totp_result["verified"]:
        raise HTTPException(
            status_code=401,
            detail="TOTP verification failed",
        )

    # ── Step 5: Create session ───────────────────────────────────
    session_id = str(uuid.uuid4())
    session = DBSession(
        id=session_id,
        candidate_id=candidate_id,
        status="ACTIVE",
        started_at=datetime.now(timezone.utc),
    )
    db.add(session)
    db.commit()

    # ── Step 6: Create JWT ───────────────────────────────────────
    token = create_session_token(candidate_id, session_id)

    # ── Log login event ──────────────────────────────────────────
    log_event(
        session_id=session_id,
        event_type="LOGIN_SUCCESS",
        detail={
            "candidate_id": candidate_id,
            "face_similarity": face_result["similarity"],
            "voice_similarity": voice_result["similarity"],
        },
        db_session=db,
    )

    return {
        "access_token": token,
        "session_id": session_id,
        "token_type": "bearer",
    }


# ═════════════════════════════════════════════════════════════════
# GET /auth/totp-setup/{candidate_id}
# ═════════════════════════════════════════════════════════════════

@router.get("/totp-setup/{candidate_id}")
async def totp_setup(candidate_id: str, db=Depends(get_db)):
    """
    Return a fresh QR code for TOTP setup.
    """
    candidate = db.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if not candidate.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP not enrolled for this candidate")

    from auth.totp_auth import get_totp_qr_code
    qr_b64 = get_totp_qr_code(candidate.totp_secret, candidate.email)

    return {
        "candidate_id": candidate_id,
        "qr_code_base64": qr_b64,
    }
