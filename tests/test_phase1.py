"""
MIIC-Sec Phase 1 Tests
Verifies: RSA keys, database, tables, config, and /health endpoint.
"""

import os
import sys

import pytest

# ── Ensure backend/ is on the path ──────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)


# ═════════════════════════════════════════════════════════════════
# TEST 1: RSA keys exist at correct paths
# ═════════════════════════════════════════════════════════════════

class TestRSAKeys:
    """Verify RSA keypair files exist."""

    def test_private_key_exists(self):
        path = os.path.join(ROOT_DIR, "keys", "private_key.pem")
        assert os.path.exists(path), f"Private key not found at {path}"

    def test_public_key_exists(self):
        path = os.path.join(ROOT_DIR, "keys", "public_key.pem")
        assert os.path.exists(path), f"Public key not found at {path}"

    def test_private_key_is_encrypted(self):
        path = os.path.join(ROOT_DIR, "keys", "private_key.pem")
        with open(path, "rb") as f:
            content = f.read()
        assert b"ENCRYPTED" in content, "Private key should be encrypted"


# ═════════════════════════════════════════════════════════════════
# TEST 2: Database creation
# ═════════════════════════════════════════════════════════════════

class TestDatabase:
    """Verify database file is created and all tables exist."""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        """Create a temp database for testing."""
        # Override DATABASE_URL to use a temp file
        db_path = tmp_path / "test_miic_sec.db"
        monkeypatch.setattr("config.DATABASE_URL", f"sqlite:///{db_path}")

        # Re-import database module with patched config
        import importlib
        import database
        # Patch the engine to use our temp DB
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        test_engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
        monkeypatch.setattr(database, "engine", test_engine)
        monkeypatch.setattr(database, "SessionLocal", sessionmaker(autocommit=False, autoflush=False, bind=test_engine))

        database.Base.metadata.create_all(bind=test_engine)
        self.db_path = db_path
        self.engine = test_engine

    def test_db_file_created(self):
        assert os.path.exists(self.db_path), "Database file was not created"

    def test_candidates_table_exists(self):
        from sqlalchemy import inspect
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        assert "candidates" in tables

    def test_sessions_table_exists(self):
        from sqlalchemy import inspect
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        assert "sessions" in tables

    def test_interview_log_table_exists(self):
        from sqlalchemy import inspect
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        assert "interview_log" in tables

    def test_audit_log_table_exists(self):
        from sqlalchemy import inspect
        inspector = inspect(self.engine)
        tables = inspector.get_table_names()
        assert "audit_log" in tables


# ═════════════════════════════════════════════════════════════════
# TEST 3: Config constants are defined
# ═════════════════════════════════════════════════════════════════

class TestConfig:
    """Verify all config constants are defined and non-None."""

    def test_database_url(self):
        import config
        assert config.DATABASE_URL is not None

    def test_key_paths(self):
        import config
        assert config.PRIVATE_KEY_PATH is not None
        assert config.PUBLIC_KEY_PATH is not None

    def test_key_password(self):
        import config
        assert config.KEY_PASSWORD is not None

    def test_jwt_settings(self):
        import config
        assert config.JWT_ALGORITHM is not None
        assert config.JWT_EXPIRY_HOURS is not None

    def test_thresholds(self):
        import config
        assert config.FACE_SIMILARITY_THRESHOLD is not None
        assert config.VOICE_SIMILARITY_THRESHOLD is not None

    def test_verification_settings(self):
        import config
        assert config.CONTINUOUS_VERIFY_INTERVAL is not None
        assert config.MAX_FAILURES_BEFORE_TERMINATE is not None

    def test_ollama_settings(self):
        import config
        assert config.OLLAMA_URL is not None
        assert config.OLLAMA_MODEL is not None
        assert config.OLLAMA_FALLBACK_MODEL is not None

    def test_model_settings(self):
        import config
        assert config.WHISPER_MODEL is not None
        assert config.YOLO_MODEL is not None


# ═════════════════════════════════════════════════════════════════
# TEST 4: FastAPI /health endpoint
# ═════════════════════════════════════════════════════════════════

class TestHealthEndpoint:
    """Verify the /health endpoint returns 200 with correct payload."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from main import app
        return TestClient(app)

    def test_health_returns_200(self, client):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_returns_ok_status(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_returns_version(self, client):
        response = client.get("/health")
        data = response.json()
        assert data["version"] == "1.0"
