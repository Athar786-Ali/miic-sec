"""
MIIC-Sec Database Layer
SQLAlchemy models + SQLite engine for all core tables.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import DATABASE_URL

# ─── Engine & Session ────────────────────────────────────────────
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def _uuid() -> str:
    """Generate a new UUID4 string."""
    return str(uuid.uuid4())


def _utcnow() -> datetime:
    """Return current UTC time."""
    return datetime.now(timezone.utc)


# ═══════════════════════════════════════════════════════════════════
# TABLE 1: candidates
# ═══════════════════════════════════════════════════════════════════
class Candidate(Base):
    __tablename__ = "candidates"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String, nullable=False)
    email = Column(String, unique=True, nullable=False)
    face_embedding = Column(LargeBinary, nullable=True)
    voice_embedding = Column(LargeBinary, nullable=True)
    totp_secret = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)

    # ── Phase 1: Email/password auth ─────────────────────────────
    password_hash      = Column(String,  nullable=True)           # bcrypt hash
    is_email_verified  = Column(Boolean, nullable=True, default=False)
    auth_method        = Column(String,  nullable=True, default="biometric")  # "password" | "biometric" | "both"


# ═══════════════════════════════════════════════════════════════════
# TABLE 2: sessions
# ═══════════════════════════════════════════════════════════════════
class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=_uuid)
    candidate_id = Column(String, ForeignKey("candidates.id"), nullable=False)
    status = Column(String, default="ACTIVE")  # ACTIVE / TERMINATED / COMPLETED
    started_at = Column(DateTime, default=_utcnow)
    ended_at = Column(DateTime, nullable=True)
    final_score = Column(Float, nullable=True)
    failure_count = Column(Integer, default=0)
    pressure_mode = Column(String, nullable=True, default="practice")  # "practice" | "simulated"


# ═══════════════════════════════════════════════════════════════════
# TABLE 3: interview_log
# ═══════════════════════════════════════════════════════════════════
class InterviewLog(Base):
    __tablename__ = "interview_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    question_number = Column(Integer, nullable=False)
    question_text = Column(Text, nullable=False)
    response_text = Column(Text, nullable=True)
    score = Column(Float, nullable=True)
    difficulty = Column(String, default="easy")  # easy / medium / hard
    timestamp = Column(DateTime, default=_utcnow)


# ═══════════════════════════════════════════════════════════════════
# TABLE 4: audit_log  (hash-chain for tamper detection)
# ═══════════════════════════════════════════════════════════════════
class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    detail = Column(Text, nullable=True)       # JSON string
    previous_hash = Column(String(64), nullable=True)
    entry_hash = Column(String(64), nullable=False)
    timestamp = Column(DateTime, default=_utcnow)


# ═══════════════════════════════════════════════════════════════════
# TABLE 5: otp_tokens  (email verification OTPs)
# ═══════════════════════════════════════════════════════════════════
class OtpToken(Base):
    __tablename__ = "otp_tokens"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    email      = Column(String, nullable=False, index=True)
    otp_code   = Column(String(6), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used       = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)


# ═══════════════════════════════════════════════════════════════════
# TABLE 6: topic_performance  (per-topic progress tracking)
# ═══════════════════════════════════════════════════════════════════
class TopicPerformance(Base):
    __tablename__ = "topic_performance"

    id              = Column(Integer, primary_key=True, autoincrement=True)
    candidate_id    = Column(String, ForeignKey("candidates.id"), nullable=False)
    topic           = Column(String, nullable=False)    # DSA | OS | DBMS | Networking | OOP
    total_score     = Column(Float,  default=0.0)
    attempt_count   = Column(Integer, default=0)
    avg_score       = Column(Float,  default=0.0)
    last_attempted_at = Column(DateTime, nullable=True)
    trend_last_5    = Column(Text, nullable=True)       # JSON list of last 5 scores


# ─── Helpers ─────────────────────────────────────────────────────

def get_db():
    """Yield a database session; auto-closes when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_SAFE_MIGRATIONS = [
    # (table, column, sql_type, default_value)
    ("candidates", "password_hash",     "TEXT",    "NULL"),
    ("candidates", "is_email_verified",  "INTEGER", "0"),
    ("candidates", "auth_method",        "TEXT",    "'biometric'"),
    ("sessions",   "pressure_mode",      "TEXT",    "'practice'"),
]


def _safe_migrate(connection):
    """Add new columns to existing tables without losing data (SQLite safe)."""
    for table, column, sql_type, default in _SAFE_MIGRATIONS:
        try:
            connection.execute(
                text(f"ALTER TABLE {table} ADD COLUMN {column} {sql_type} DEFAULT {default}")
            )
        except Exception:
            pass  # Column already exists — ignore


def init_db():
    """Create all tables and run safe column migrations."""
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        _safe_migrate(conn)
        conn.commit()
    print("✅ Database initialized — all tables ready.")
