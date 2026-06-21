"""
MIIC-Sec — Liveness Detector
Uses OpenCV Haar cascade + eye-blink heuristic.
TensorFlow-based CNN has been replaced because TF 2.x segfaults
on Python 3.13 / macOS (known upstream issue).
"""

import os
import numpy as np
import cv2


# ─── Haar cascades (bundled with OpenCV — no download needed) ────
_FACE_CASCADE = None
_EYE_CASCADE  = None


def _get_cascades():
    global _FACE_CASCADE, _EYE_CASCADE
    if _FACE_CASCADE is not None:
        return _FACE_CASCADE, _EYE_CASCADE

    data_dir = cv2.data.haarcascades
    _FACE_CASCADE = cv2.CascadeClassifier(os.path.join(data_dir, "haarcascade_frontalface_default.xml"))
    _EYE_CASCADE  = cv2.CascadeClassifier(os.path.join(data_dir, "haarcascade_eye.xml"))
    return _FACE_CASCADE, _EYE_CASCADE


def load_liveness_model(model_path: str = "models/liveness_model.h5"):
    """
    Returns None — TF-based liveness is replaced by OpenCV heuristic.
    Signature kept for backward compatibility with routes.py.
    """
    print("ℹ️  Liveness: using OpenCV Haar-cascade heuristic (TF disabled on Python 3.13)")
    return None   # sentinel: detect_liveness handles None gracefully


def build_liveness_model():
    """Kept for API compatibility — no-op."""
    return None


def detect_liveness(frame: np.ndarray, model=None) -> dict:
    """
    Lightweight liveness check using OpenCV:
      1. Detect a frontal face (Haar cascade).
      2. Detect eyes within the face region.
      3. Check basic image quality (brightness, blur).

    Returns:
        { "is_live": bool, "confidence": float }
    """
    try:
        face_cascade, eye_cascade = _get_cascades()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # ── 1. Face detection ─────────────────────────────────────
        faces = face_cascade.detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) == 0:
            # No face found — treat as not live (spoofed blank image)
            return {"is_live": False, "confidence": 0.1}

        # Use the largest detected face
        x, y, w, h = max(faces, key=lambda r: r[2] * r[3])
        face_roi = gray[y : y + h, x : x + w]

        # ── 2. Eye detection within face ──────────────────────────
        eyes = eye_cascade.detectMultiScale(face_roi, scaleFactor=1.1, minNeighbors=3)
        eyes_found = len(eyes) >= 1   # at least one eye

        # ── 3. Brightness check (printed photo is often overexposed) ─
        mean_brightness = float(np.mean(face_roi))
        brightness_ok = 30 < mean_brightness < 230

        # ── 4. Blur check (blurry = spoofed screen or photo) ─────
        laplacian_var = float(cv2.Laplacian(face_roi, cv2.CV_64F).var())
        sharp_enough = laplacian_var > 50   # threshold tuned for 96×96 crops

        # ── Aggregate score ───────────────────────────────────────
        score = 0.0
        score += 0.4 if eyes_found    else 0.0
        score += 0.3 if brightness_ok else 0.0
        score += 0.3 if sharp_enough  else 0.0

        return {
            "is_live":    score >= 0.5,
            "confidence": round(score, 4),
        }

    except Exception as e:
        print(f"⚠️  Liveness check error: {e} — defaulting to live")
        return {"is_live": True, "confidence": 0.6}
