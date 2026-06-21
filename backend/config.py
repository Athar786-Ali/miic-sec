"""
MIIC-Sec Configuration
All constants and settings in one place.
"""

import os

# ─── Database ────────────────────────────────────────────────────
DATABASE_URL = "sqlite:///./miic_sec.db"

# ─── RSA Keys ────────────────────────────────────────────────────
PRIVATE_KEY_PATH = "keys/private_key.pem"
PUBLIC_KEY_PATH = "keys/public_key.pem"
KEY_PASSWORD = b"miicsec_secret"

# ─── JWT ─────────────────────────────────────────────────────────
JWT_ALGORITHM = "RS256"
JWT_EXPIRY_HOURS = 2

# ─── Face Verification ──────────────────────────────────────────
FACE_SIMILARITY_THRESHOLD = 0.55   # facenet-pytorch InceptionResnetV1 VGGFace2 512-d cosine similarity

# ─── Voice Verification ─────────────────────────────────────────
VOICE_SIMILARITY_THRESHOLD = 0.60  # wav2vec2 cosine similarity (5s login vs 10s enroll)

# ─── Continuous Verification ────────────────────────────────────
CONTINUOUS_VERIFY_INTERVAL = 30          # seconds
MAX_FAILURES_BEFORE_TERMINATE = 2

# ─── Ollama (Local LLM) ─────────────────────────────────────────
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_FALLBACK_MODEL = "qwen2.5:3b"

# ─── Deepgram (Speech-to-Text) ──────────────────────────────────
# API key is loaded from DEEPGRAM_API_KEY env var in backend/.env
DEEPGRAM_MODEL    = "nova-2"
DEEPGRAM_LANGUAGE = "en-IN"    # Indian English; change to "en" for global

# ─── Whisper (local fallback transcription) ──────────────────────
WHISPER_MODEL = "base"         # tiny | base | small | medium

# ─── YOLO (Object Detection) ────────────────────────────────────
YOLO_MODEL = "yolov8n.pt"

# ─── Email / SMTP (Phase 1) ─────────────────────────────────────
SMTP_HOST  = os.environ.get("SMTP_HOST",  "")
SMTP_PORT  = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER  = os.environ.get("SMTP_USER",  "")
SMTP_PASS  = os.environ.get("SMTP_PASS",  "")
FROM_EMAIL = os.environ.get("FROM_EMAIL", SMTP_USER or "noreply@miic-sec.local")
