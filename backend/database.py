"""
MIIC-Sec Database Layer
SQLAlchemy models + SQLite engine for all 4 core tables.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    create_engine,
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


# ─── Helpers ─────────────────────────────────────────────────────

def get_db():
    """Yield a database session; auto-closes when done."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create all tables in the database."""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized — all tables created.")
