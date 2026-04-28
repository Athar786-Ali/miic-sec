"""
MIIC-Sec Configuration
All constants and settings in one place.
"""

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
FACE_SIMILARITY_THRESHOLD = 0.75

# ─── Voice Verification ─────────────────────────────────────────
VOICE_SIMILARITY_THRESHOLD = 0.80

# ─── Continuous Verification ────────────────────────────────────
CONTINUOUS_VERIFY_INTERVAL = 30          # seconds
MAX_FAILURES_BEFORE_TERMINATE = 2

# ─── Ollama (Local LLM) ─────────────────────────────────────────
OLLAMA_URL = "http://localhost:11434"
# Yeh do lines badlo
OLLAMA_MODEL = "qwen2.5:7b"
OLLAMA_FALLBACK_MODEL = "qwen2.5:3b"

# ─── Whisper (Speech-to-Text) ───────────────────────────────────
WHISPER_MODEL = "small"

# ─── YOLO (Object Detection) ────────────────────────────────────
YOLO_MODEL = "yolov8n.pt"

