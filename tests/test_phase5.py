"""
MIIC-Sec — Phase 5 Test Suite
Tests for the Cryptographic Report System (Tier 5).

Run with:
    cd backend
    pytest ../tests/test_phase5.py -v
"""

import json
import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys_path_inserted = False
import sys
sys.path.insert(0, ".")


# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════

def _in_memory_db():
    """Real SQLite in-memory DB with all tables."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from database import Base
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)()


def _seed_session(db, candidate_id=None, session_id=None):
    """Insert a Candidate + Session row and return (candidate_id, session_id)."""
    from database import Candidate, Session as DBSession
    import pyotp

    cid = candidate_id or str(uuid.uuid4())
    sid = session_id   or str(uuid.uuid4())

    candidate = Candidate(
        id=cid,
        name="Test Candidate",
        email=f"{cid[:8]}@test.com",
        totp_secret=pyotp.random_base32(),
    )
    db.add(candidate)

    session = DBSession(
        id=sid,
        candidate_id=cid,
        status="COMPLETED",
        started_at=datetime.now(timezone.utc),
        ended_at=datetime.now(timezone.utc),
        final_score=8.0,
        failure_count=0,
    )
    db.add(session)
    db.commit()
    return cid, sid


def _make_rsa_keypair(tmp_dir: Path):
    """Generate a fresh RSA-2048 keypair in a temp dir; return (priv_path, pub_path)."""
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    password    = b"test_password"

    priv_path = tmp_dir / "private.pem"
    pub_path  = tmp_dir / "public.pem"

    with open(priv_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(password),
        ))

    with open(pub_path, "wb") as f:
        f.write(private_key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ))

    return str(priv_path), str(pub_path), password


# ═════════════════════════════════════════════════════════════════════════════
# TEST 1 — Report generation with mock session data
# ═════════════════════════════════════════════════════════════════════════════

class TestReportGeneration:
    """collect_session_data() assembles all expected fields."""

    def test_report_has_all_required_fields(self):
        from crypto.report_signer import collect_session_data

        db = _in_memory_db()
        cid, sid = _seed_session(db)

        report = collect_session_data(sid, db, emotion_store={}, interview_store={})

        required_keys = [
            "report_id", "session_id", "candidate_id", "generated_at",
            "session_start", "tier_1_result", "interview_scores",
            "average_score", "recommendation", "emotion_timeseries",
            "security_events", "audit_chain_valid",
        ]
        for key in required_keys:
            assert key in report, f"Missing field: {key}"

        db.close()

    def test_session_id_matches(self):
        from crypto.report_signer import collect_session_data

        db = _in_memory_db()
        cid, sid = _seed_session(db)

        report = collect_session_data(sid, db, {}, {})
        assert report["session_id"]   == sid
        assert report["candidate_id"] == cid
        db.close()

    def test_emotion_timeseries_from_store(self):
        from crypto.report_signer import collect_session_data

        db = _in_memory_db()
        cid, sid = _seed_session(db)

        snapshots = [
            {"timestamp": "t1", "emotion": "neutral", "gaze_score": 0.8},
            {"timestamp": "t2", "emotion": "happy",   "gaze_score": 0.9},
        ]
        report = collect_session_data(sid, db, emotion_store={sid: snapshots}, interview_store={})
        assert report["emotion_timeseries"] == snapshots
        db.close()

    def test_missing_session_raises(self):
        from crypto.report_signer import collect_session_data

        db = _in_memory_db()
        with pytest.raises(ValueError, match="not found"):
            collect_session_data("nonexistent-session-id", db, {}, {})
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# TEST 2 — RSA signature is valid after signing
# ═════════════════════════════════════════════════════════════════════════════

class TestReportSigning:
    """sign_report() produces a verifiable RSA-2048 PKCS1v15 signature."""

    def test_signature_field_added(self, tmp_path):
        from crypto.report_signer import sign_report

        priv, pub, pwd = _make_rsa_keypair(tmp_path)
        report = {"report_id": str(uuid.uuid4()), "session_id": "s1", "average_score": 8.0}

        signed = sign_report(report, private_key_path=priv, key_password=pwd)
        assert "report_signature" in signed
        assert len(signed["report_signature"]) > 50   # non-empty base64

    def test_signature_is_base64(self, tmp_path):
        import base64
        from crypto.report_signer import sign_report

        priv, pub, pwd = _make_rsa_keypair(tmp_path)
        report = {"x": 1}
        signed = sign_report(report, private_key_path=priv, key_password=pwd)

        # Must decode without error
        decoded = base64.b64decode(signed["report_signature"])
        assert len(decoded) == 256   # RSA-2048 → 256-byte signature

    def test_original_fields_preserved(self, tmp_path):
        from crypto.report_signer import sign_report

        priv, pub, pwd = _make_rsa_keypair(tmp_path)
        report = {"average_score": 9.5, "recommendation": "HIRE", "session_id": "abc"}

        signed = sign_report(report, private_key_path=priv, key_password=pwd)
        assert signed["average_score"]   == 9.5
        assert signed["recommendation"]  == "HIRE"
        assert signed["session_id"]      == "abc"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 3 — Signature fails if report is tampered
# ═════════════════════════════════════════════════════════════════════════════

class TestSignatureTampering:
    """verify_report_signature() must return valid=False for a tampered report."""

    def test_tampered_field_fails_verification(self, tmp_path):
        from crypto.report_signer import sign_report, save_report, verify_report_signature

        priv, pub, pwd = _make_rsa_keypair(tmp_path)
        sid = str(uuid.uuid4())

        # Sign and save original
        report = {"session_id": sid, "recommendation": "HIRE", "average_score": 8.5}
        signed = sign_report(report, private_key_path=priv, key_password=pwd)

        # Save to temp directory
        with patch("crypto.report_signer.REPORTS_DIR", tmp_path):
            path = save_report(signed, sid)

        # Tamper: mutate recommendation on disk
        with open(path, "r") as f:
            on_disk = json.load(f)
        on_disk["recommendation"] = "REJECT"   # ← tampered
        with open(path, "w") as f:
            json.dump(on_disk, f)

        result = verify_report_signature(path, public_key_path=pub)
        assert result["valid"] is False, "Expected invalid after tampering"

    def test_valid_report_passes_verification(self, tmp_path):
        from crypto.report_signer import sign_report, save_report, verify_report_signature

        priv, pub, pwd = _make_rsa_keypair(tmp_path)
        sid = str(uuid.uuid4())

        report = {"session_id": sid, "recommendation": "HIRE", "average_score": 8.5}
        signed = sign_report(report, private_key_path=priv, key_password=pwd)

        with patch("crypto.report_signer.REPORTS_DIR", tmp_path):
            path = save_report(signed, sid)

        result = verify_report_signature(path, public_key_path=pub)
        assert result["valid"] is True

    def test_removed_signature_fails(self, tmp_path):
        from crypto.report_signer import sign_report, save_report, verify_report_signature

        priv, pub, pwd = _make_rsa_keypair(tmp_path)
        sid = str(uuid.uuid4())

        report = {"session_id": sid}
        signed = sign_report(report, private_key_path=priv, key_password=pwd)

        with patch("crypto.report_signer.REPORTS_DIR", tmp_path):
            path = save_report(signed, sid)

        # Remove signature field
        with open(path, "r") as f:
            on_disk = json.load(f)
        on_disk.pop("report_signature", None)
        with open(path, "w") as f:
            json.dump(on_disk, f)

        result = verify_report_signature(path, public_key_path=pub)
        assert result["valid"] is False


# ═════════════════════════════════════════════════════════════════════════════
# TEST 4 — Report file is saved correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestReportFileSaving:
    """save_report() persists the file and returns the correct path."""

    def test_file_created(self, tmp_path):
        from crypto.report_signer import save_report

        sid    = str(uuid.uuid4())
        report = {"session_id": sid, "report_signature": "abc123"}

        with patch("crypto.report_signer.REPORTS_DIR", tmp_path):
            path = save_report(report, sid)

        assert Path(path).exists(), "Report file was not created"

    def test_filename_contains_session_id(self, tmp_path):
        from crypto.report_signer import save_report

        sid  = "my-test-session"
        with patch("crypto.report_signer.REPORTS_DIR", tmp_path):
            path = save_report({"session_id": sid}, sid)

        assert sid in Path(path).name

    def test_json_content_roundtrip(self, tmp_path):
        from crypto.report_signer import save_report

        sid    = str(uuid.uuid4())
        report = {"session_id": sid, "average_score": 7.5, "recommendation": "REVIEW"}

        with patch("crypto.report_signer.REPORTS_DIR", tmp_path):
            path = save_report(report, sid)

        with open(path, "r") as f:
            loaded = json.load(f)

        assert loaded["average_score"]  == 7.5
        assert loaded["recommendation"] == "REVIEW"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 5 — Audit chain is valid in generated report
# ═════════════════════════════════════════════════════════════════════════════

class TestAuditChainInReport:
    """After logging events, collect_session_data() must report audit_chain_valid=True."""

    def test_chain_valid_with_events(self):
        from crypto.report_signer import collect_session_data
        from crypto.audit_log import log_event

        db = _in_memory_db()
        cid, sid = _seed_session(db)

        for event in ["LOGIN_SUCCESS", "INTERVIEW_STARTED", "QUESTION_ANSWERED"]:
            log_event(session_id=sid, event_type=event, detail={"ok": True}, db_session=db)

        report = collect_session_data(sid, db, {}, {})
        assert report["audit_chain_valid"] is True
        db.close()

    def test_security_events_captured(self):
        from crypto.report_signer import collect_session_data
        from crypto.audit_log import log_event

        db = _in_memory_db()
        cid, sid = _seed_session(db)

        log_event(sid, "TAB_SWITCH",        {"n": 1}, db)
        log_event(sid, "IDENTITY_MISMATCH", {"similarity": 0.6}, db)

        report = collect_session_data(sid, db, {}, {})
        event_types = [e["event_type"] for e in report["security_events"]]
        assert "TAB_SWITCH"        in event_types
        assert "IDENTITY_MISMATCH" in event_types
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# TEST 6 — Recommendation logic (HIRE / REVIEW / REJECT thresholds)
# ═════════════════════════════════════════════════════════════════════════════

class TestRecommendationLogic:
    """Correct recommendation is derived from average_score."""

    def _get_rec(self, avg_score: float) -> str:
        from crypto.report_signer import HIRE_THRESHOLD, REVIEW_THRESHOLD
        if avg_score >= HIRE_THRESHOLD:   return "HIRE"
        if avg_score >= REVIEW_THRESHOLD: return "REVIEW"
        return "REJECT"

    def test_hire_at_threshold(self):
        assert self._get_rec(7.5) == "HIRE"

    def test_hire_above_threshold(self):
        assert self._get_rec(9.0) == "HIRE"

    def test_review_just_below_hire(self):
        assert self._get_rec(7.4) == "REVIEW"

    def test_review_at_lower_threshold(self):
        assert self._get_rec(5.0) == "REVIEW"

    def test_reject_below_review(self):
        assert self._get_rec(4.9) == "REJECT"

    def test_reject_at_zero(self):
        assert self._get_rec(0.0) == "REJECT"

    def test_recommendation_in_collected_report(self, tmp_path):
        """collect_session_data() sets recommendation correctly from DB scores."""
        from crypto.report_signer import collect_session_data
        from database import InterviewLog

        db  = _in_memory_db()
        cid, sid = _seed_session(db)

        # Add 3 high-score questions (avg = 9.0 → HIRE)
        for q in range(1, 4):
            db.add(InterviewLog(session_id=sid, question_number=q,
                                question_text=f"Q{q}", response_text="A", score=9.0, difficulty="hard"))
        db.commit()

        report = collect_session_data(sid, db, {}, {})
        assert report["recommendation"] == "HIRE"
        assert report["average_score"]  == 9.0
        db.close()


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
