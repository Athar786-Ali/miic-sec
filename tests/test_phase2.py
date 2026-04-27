"""
MIIC-Sec Phase 2 Tests
Verifies: TOTP, JWT, audit log hash chain, and face embedding serialization.
"""

import os
import sys
import pickle
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pytest

# ── Ensure backend/ is on the path ──────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)


# ═════════════════════════════════════════════════════════════════
# TEST 1: TOTP generation and verification
# ═════════════════════════════════════════════════════════════════

class TestTOTP:
    """Verify TOTP secret generation and code verification."""

    def test_generate_secret(self):
        from auth.totp_auth import generate_totp_secret
        secret = generate_totp_secret()
        assert secret is not None
        assert len(secret) == 32  # pyotp default base32 length

    def test_verify_valid_code(self):
        import pyotp
        from auth.totp_auth import generate_totp_secret, verify_totp

        secret = generate_totp_secret()
        totp = pyotp.TOTP(secret)
        current_code = totp.now()

        result = verify_totp(secret, current_code)
        assert result["verified"] is True

    def test_verify_invalid_code(self):
        from auth.totp_auth import generate_totp_secret, verify_totp

        secret = generate_totp_secret()
        result = verify_totp(secret, "000000")
        assert result["verified"] is False

    def test_qr_code_generation(self):
        from auth.totp_auth import generate_totp_secret, get_totp_qr_code

        secret = generate_totp_secret()
        qr_b64 = get_totp_qr_code(secret, "test@miicsec.com")

        assert qr_b64 is not None
        assert len(qr_b64) > 100  # Base64 encoded PNG should be substantial


# ═════════════════════════════════════════════════════════════════
# TEST 2: JWT creation and verification
# ═════════════════════════════════════════════════════════════════

class TestJWT:
    """Verify JWT token creation and verification."""

    def test_create_and_verify_token(self):
        from auth.jwt_manager import create_session_token, verify_token

        token = create_session_token("test-candidate-123", "test-session-456")
        assert token is not None
        assert isinstance(token, str)

        payload = verify_token(token)
        assert payload is not None
        assert payload["candidate_id"] == "test-candidate-123"
        assert payload["session_id"] == "test-session-456"
        assert payload["mfa_passed"] is True

    def test_verify_invalid_token(self):
        from auth.jwt_manager import verify_token

        result = verify_token("invalid.token.string")
        assert result is None

    def test_token_contains_expiry(self):
        from auth.jwt_manager import create_session_token, verify_token

        token = create_session_token("cand-1", "sess-1")
        payload = verify_token(token)

        assert "exp" in payload
        assert "iat" in payload

    def test_expired_token_rejected(self):
        """Test that an expired token is rejected."""
        from jose import jwt
        from auth.jwt_manager import load_private_key, load_public_key, verify_token
        import config

        # Create a token that's already expired
        now = datetime.now(timezone.utc)
        payload = {
            "candidate_id": "expired-cand",
            "session_id": "expired-sess",
            "mfa_passed": True,
            "iat": now - timedelta(hours=3),
            "exp": now - timedelta(hours=1),  # Expired 1 hour ago
        }

        private_key = load_private_key()
        expired_token = jwt.encode(payload, private_key, algorithm=config.JWT_ALGORITHM)

        result = verify_token(expired_token)
        assert result is None


# ═════════════════════════════════════════════════════════════════
# TEST 3: Audit log hash chain integrity
# ═════════════════════════════════════════════════════════════════

class TestAuditLog:
    """Verify audit log hash chain creation and integrity verification."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        """Create a temp database for testing."""
        db_path = tmp_path / "test_audit.db"
        monkeypatch.setattr("config.DATABASE_URL", f"sqlite:///{db_path}")

        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        import database

        test_engine = create_engine(
            f"sqlite:///{db_path}",
            connect_args={"check_same_thread": False},
        )
        monkeypatch.setattr(database, "engine", test_engine)
        test_session_local = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
        monkeypatch.setattr(database, "SessionLocal", test_session_local)

        database.Base.metadata.create_all(bind=test_engine)

        self.db = test_session_local()
        yield
        self.db.close()

    def test_log_single_event(self):
        from crypto.audit_log import log_event

        entry = log_event(
            session_id="sess-test-1",
            event_type="TEST_EVENT",
            detail={"info": "test"},
            db_session=self.db,
        )

        assert entry["session_id"] == "sess-test-1"
        assert entry["event_type"] == "TEST_EVENT"
        assert entry["previous_hash"] == "0" * 64  # Genesis
        assert len(entry["entry_hash"]) == 64

    def test_hash_chain_links(self):
        from crypto.audit_log import log_event

        entry1 = log_event("sess-chain", "EVENT_1", {"step": 1}, self.db)
        entry2 = log_event("sess-chain", "EVENT_2", {"step": 2}, self.db)

        # Entry 2's previous_hash should be entry 1's hash
        assert entry2["previous_hash"] == entry1["entry_hash"]

    def test_chain_verification_valid(self):
        from crypto.audit_log import log_event, verify_audit_chain

        log_event("sess-verify", "EVENT_A", {"a": 1}, self.db)
        log_event("sess-verify", "EVENT_B", {"b": 2}, self.db)
        log_event("sess-verify", "EVENT_C", {"c": 3}, self.db)

        result = verify_audit_chain("sess-verify", self.db)
        assert result["valid"] is True
        assert result["total_entries"] == 3
        assert result["broken_at_entry"] is None

    def test_chain_breaks_on_tamper(self):
        from crypto.audit_log import log_event, verify_audit_chain
        from database import AuditLog

        log_event("sess-tamper", "EVENT_1", {"x": 1}, self.db)
        entry2 = log_event("sess-tamper", "EVENT_2", {"x": 2}, self.db)
        log_event("sess-tamper", "EVENT_3", {"x": 3}, self.db)

        # Tamper with entry 2's detail
        db_entry = (
            self.db.query(AuditLog)
            .filter(AuditLog.id == entry2["id"])
            .first()
        )
        db_entry.detail = '{"x": 999}'  # Tampered!
        self.db.commit()

        result = verify_audit_chain("sess-tamper", self.db)
        assert result["valid"] is False
        assert result["broken_at_entry"] == entry2["id"]

    def test_get_session_audit_log(self):
        from crypto.audit_log import log_event, get_session_audit_log

        log_event("sess-list", "A", {"a": 1}, self.db)
        log_event("sess-list", "B", {"b": 2}, self.db)

        entries = get_session_audit_log("sess-list", self.db)
        assert len(entries) == 2
        assert entries[0]["event_type"] == "A"
        assert entries[1]["event_type"] == "B"


# ═════════════════════════════════════════════════════════════════
# TEST 4: Face embedding serialization
# ═════════════════════════════════════════════════════════════════

class TestEmbeddingSerialization:
    """Verify numpy embedding pickle serialization round-trip."""

    def test_serialize_deserialize_face_embedding(self):
        """Test that a 128-d face embedding survives pickle round-trip."""
        original = np.random.rand(128).astype(np.float32)

        serialized = pickle.dumps(original)
        deserialized = pickle.loads(serialized)

        assert isinstance(deserialized, np.ndarray)
        assert deserialized.shape == (128,)
        assert deserialized.dtype == np.float32
        np.testing.assert_array_almost_equal(original, deserialized)

    def test_serialize_deserialize_voice_embedding(self):
        """Test that a 768-d voice embedding survives pickle round-trip."""
        original = np.random.rand(768).astype(np.float32)

        serialized = pickle.dumps(original)
        deserialized = pickle.loads(serialized)

        assert isinstance(deserialized, np.ndarray)
        assert deserialized.shape == (768,)
        np.testing.assert_array_almost_equal(original, deserialized)
