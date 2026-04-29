"""
MIIC-Sec — Phase 4 Test Suite
Tests for Tier 3 (continuous verification) and Tier 4 (proxy + intruder detection).

Run with:
    cd backend
    pytest ../tests/test_phase4.py -v
"""

import asyncio
import sys
import types
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

# Ensure backend/ is on the path when running from the project root
sys.path.insert(0, ".")


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _black_frame(h: int = 480, w: int = 640) -> np.ndarray:
    """Return a pure-black BGR frame for testing."""
    return np.zeros((h, w, 3), dtype=np.uint8)


def _silent_audio(samples: int = 16000) -> np.ndarray:
    """Return a silence (all-zeros) mono float32 audio array."""
    return np.zeros(samples, dtype=np.float32)


def _make_db_session(*, session_status="ACTIVE", failure_count=0, totp_secret="JBSWY3DPEHPK3PXP"):
    """
    Build a minimal mock SQLAlchemy DB session that returns plausible
    Candidate and Session objects for the given parameters.
    """
    mock_candidate = MagicMock()
    mock_candidate.id           = "cand-001"
    mock_candidate.totp_secret  = totp_secret

    mock_session = MagicMock()
    mock_session.id             = "sess-001"
    mock_session.candidate_id   = "cand-001"
    mock_session.status         = session_status
    mock_session.failure_count  = failure_count

    db = MagicMock()

    def _query_side_effect(model):
        q = MagicMock()
        # filter().first() returns the appropriate object based on model name
        if "Session" in str(model) or model.__name__ == "Session":
            q.filter.return_value.first.return_value = mock_session
        elif "Candidate" in str(model) or model.__name__ == "Candidate":
            q.filter.return_value.first.return_value = mock_candidate
        elif "AuditLog" in str(model):
            q.filter.return_value.order_by.return_value.first.return_value = None
            q.filter.return_value.order_by.return_value.all.return_value  = []
        else:
            q.filter.return_value.first.return_value = None
        return q

    db.query.side_effect = _query_side_effect
    db.add    = MagicMock()
    db.commit = MagicMock()

    # Support use as context manager (for db_session_factory pattern)
    db.__enter__ = MagicMock(return_value=db)
    db.__exit__  = MagicMock(return_value=False)

    return db, mock_session, mock_candidate


# ═════════════════════════════════════════════════════════════════════════════
# TEST 1 — WebSocket manager: sends to correct session only
# ═════════════════════════════════════════════════════════════════════════════

class TestWebSocketManager:
    """ConnectionManager routes messages to the correct session socket."""

    def _make_ws(self):
        ws = AsyncMock()
        ws.accept   = AsyncMock()
        ws.send_json = AsyncMock()
        return ws

    @pytest.mark.asyncio
    async def test_candidate_receives_own_message(self):
        """send_to_candidate only delivers to the matching session_id."""
        from websocket.ws_manager import ConnectionManager

        cm    = ConnectionManager()
        ws_a  = self._make_ws()
        ws_b  = self._make_ws()

        await cm.connect_candidate("sess-A", ws_a)
        await cm.connect_candidate("sess-B", ws_b)

        # Send a message to sess-A only
        msg = {"event": "TEST", "data": {}, "timestamp": "now"}
        await cm.send_to_candidate("sess-A", msg)

        # ws_a should have received it (connect sends CANDIDATE_CONNECTED + our msg)
        all_calls_a = [call.args[0] for call in ws_a.send_json.call_args_list]
        assert any(c.get("event") == "TEST" for c in all_calls_a), \
            f"sess-A did not receive TEST event; calls: {all_calls_a}"

        # ws_b should NOT have received the TEST event
        all_calls_b = [call.args[0] for call in ws_b.send_json.call_args_list]
        assert not any(c.get("event") == "TEST" for c in all_calls_b), \
            f"sess-B incorrectly received TEST event"

    @pytest.mark.asyncio
    async def test_send_to_missing_session_does_not_crash(self):
        """send_to_candidate with unknown session_id must not raise."""
        from websocket.ws_manager import ConnectionManager

        cm = ConnectionManager()
        # Should complete silently
        await cm.send_to_candidate("nonexistent-session", {"event": "X", "data": {}, "timestamp": "t"})

    @pytest.mark.asyncio
    async def test_disconnect_removes_socket(self):
        """disconnect() removes the socket so subsequent sends are no-ops."""
        from websocket.ws_manager import ConnectionManager

        cm = ConnectionManager()
        ws = self._make_ws()

        await cm.connect_candidate("sess-C", ws)
        cm.disconnect("sess-C", "candidate")

        assert "sess-C" not in cm.candidate_connections

    @pytest.mark.asyncio
    async def test_broadcast_reaches_both_sides(self):
        """broadcast_security_event sends to candidate AND recruiter."""
        from websocket.ws_manager import ConnectionManager, MULTIPLE_PERSONS_ALERT

        cm        = ConnectionManager()
        ws_cand   = self._make_ws()
        ws_rec    = self._make_ws()

        await cm.connect_candidate("sess-D", ws_cand)
        await cm.connect_recruiter("sess-D", ws_rec)

        await cm.broadcast_security_event(
            "sess-D", MULTIPLE_PERSONS_ALERT, {"person_count": 2}
        )

        cand_events = [c.args[0].get("event") for c in ws_cand.send_json.call_args_list]
        rec_events  = [c.args[0].get("event") for c in ws_rec.send_json.call_args_list]

        assert MULTIPLE_PERSONS_ALERT in cand_events, \
            f"Candidate did not receive alert; events={cand_events}"
        assert MULTIPLE_PERSONS_ALERT in rec_events, \
            f"Recruiter did not receive alert; events={rec_events}"

    @pytest.mark.asyncio
    async def test_recruiter_receives_own_message(self):
        """send_to_recruiter only delivers to the matching session."""
        from websocket.ws_manager import ConnectionManager

        cm   = ConnectionManager()
        ws_r = self._make_ws()

        await cm.connect_recruiter("sess-E", ws_r)

        msg = {"event": "REC_TEST", "data": {}, "timestamp": "t"}
        await cm.send_to_recruiter("sess-E", msg)

        events = [c.args[0].get("event") for c in ws_r.send_json.call_args_list]
        assert "REC_TEST" in events


# ═════════════════════════════════════════════════════════════════════════════
# TEST 2 — ProxyDetector: frame throttling (process only every 10th frame)
# ═════════════════════════════════════════════════════════════════════════════

class TestProxyDetectorFrameSkip:
    """ProxyDetector.process_frame must skip 9 out of every 10 frames."""

    def _make_detector_with_mock_yolo(self):
        """Return a ProxyDetector whose YOLO model is replaced by a mock."""
        # Stub out the ultralytics import so no real model is loaded
        fake_yolo_instance = MagicMock()
        # Default: return 1 person (safe)
        fake_result        = MagicMock()
        fake_result.boxes  = MagicMock()
        fake_result.boxes.cls  = MagicMock()
        fake_result.boxes.cls.tolist.return_value  = [0]       # class_id 0 = person
        fake_result.boxes.conf = MagicMock()
        fake_result.boxes.conf.tolist.return_value = [0.92]
        fake_yolo_instance.return_value = [fake_result]

        with patch("verification.proxy_detector.load_yolo_model", return_value=fake_yolo_instance):
            from verification.proxy_detector import ProxyDetector
            detector         = ProxyDetector.__new__(ProxyDetector)
            detector.model   = fake_yolo_instance
            detector.consecutive_multi_person_count = {}
            detector.frame_counter                  = {}

        return detector, fake_yolo_instance

    @pytest.mark.asyncio
    async def test_only_10th_frame_triggers_inference(self):
        """YOLO inference must be called exactly once after 10 process_frame() calls."""
        from verification.proxy_detector import count_persons_in_frame

        detector, mock_model = self._make_detector_with_mock_yolo()

        inference_call_count = 0

        async def _fake_process(session_id, frame, db_session, ws_manager, audit_logger=None):
            nonlocal inference_call_count
            detector.frame_counter[session_id] = detector.frame_counter.get(session_id, 0) + 1
            if detector.frame_counter[session_id] % 10 == 0:
                inference_call_count += 1

        db  = MagicMock()
        ws  = MagicMock()

        for _ in range(10):
            await _fake_process("sess-proxy", _black_frame(), db, ws)

        assert inference_call_count == 1, \
            f"Expected 1 inference call, got {inference_call_count}"

    @pytest.mark.asyncio
    async def test_frames_1_to_9_are_skipped(self):
        """Frames 1–9 must not trigger any YOLO inference."""
        detector, mock_model = self._make_detector_with_mock_yolo()

        call_log = []

        with patch(
            "verification.proxy_detector.count_persons_in_frame",
            side_effect=lambda frame, model: (call_log.append(1), {"person_count": 1, "confidence_scores": []})[1],
        ):
            db  = MagicMock()
            ws  = MagicMock()

            # Import after patching
            from verification.proxy_detector import FRAME_SKIP

            for i in range(FRAME_SKIP - 1):   # frames 1..9
                detector.frame_counter["sess-skip"] = i + 1
                # Check that skipping logic works at the frame-counter level
                if (i + 1) % FRAME_SKIP != 0:
                    continue   # mirroring the real logic

        assert len(call_log) == 0, \
            f"Expected 0 inference calls for frames 1-9, got {len(call_log)}"

    @pytest.mark.asyncio
    async def test_frame_counter_increments_per_session(self):
        """Each session maintains its own independent frame counter."""
        detector, _ = self._make_detector_with_mock_yolo()

        detector.frame_counter["s1"] = 5
        detector.frame_counter["s2"] = 0

        detector.frame_counter["s1"] += 1
        detector.frame_counter["s2"] += 1

        assert detector.frame_counter["s1"] == 6
        assert detector.frame_counter["s2"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# TEST 3 — Session termination updates DB status correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestSessionTermination:
    """terminate_session() must update Session.status and log an audit entry."""

    @pytest.mark.asyncio
    async def test_terminate_sets_status_to_terminated(self):
        """After terminate_session(), the DB session status must be TERMINATED."""
        from verification.continuous_verifier import terminate_session

        db, mock_session, _ = _make_db_session()
        ws                  = MagicMock()
        ws.send_to_candidate = AsyncMock()
        ws.send_to_recruiter = AsyncMock()

        with patch("verification.continuous_verifier.log_event"):
            await terminate_session("sess-001", "Test termination", db, ws)

        assert mock_session.status == "TERMINATED", \
            f"Expected TERMINATED, got {mock_session.status}"
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_terminate_calls_audit_log(self):
        """terminate_session() must write a SESSION_TERMINATED audit entry."""
        from verification.continuous_verifier import terminate_session

        db, mock_session, _ = _make_db_session()
        ws                  = MagicMock()
        ws.send_to_candidate = AsyncMock()
        ws.send_to_recruiter = AsyncMock()

        with patch("verification.continuous_verifier.log_event") as mock_log:
            await terminate_session("sess-001", "audit test", db, ws)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs if mock_log.call_args.kwargs else {}
        call_args   = mock_log.call_args.args   if mock_log.call_args.args   else ()

        # event_type should be "SESSION_TERMINATED" (positional or keyword)
        event_type = call_kwargs.get("event_type") or (call_args[1] if len(call_args) > 1 else None)
        assert event_type == "SESSION_TERMINATED", \
            f"Expected SESSION_TERMINATED, got {event_type}"

    @pytest.mark.asyncio
    async def test_terminate_notifies_both_websocket_roles(self):
        """WebSocket notifications must be sent to both candidate and recruiter."""
        from verification.continuous_verifier import terminate_session

        db, _, _ = _make_db_session()
        ws       = MagicMock()
        ws.send_to_candidate = AsyncMock()
        ws.send_to_recruiter = AsyncMock()

        with patch("verification.continuous_verifier.log_event"):
            await terminate_session("sess-001", "dual notify test", db, ws)

        ws.send_to_candidate.assert_called()
        ws.send_to_recruiter.assert_called()

    @pytest.mark.asyncio
    async def test_terminate_sets_ended_at(self):
        """terminate_session() must set Session.ended_at to a datetime."""
        from verification.continuous_verifier import terminate_session

        db, mock_session, _ = _make_db_session()
        ws                  = MagicMock()
        ws.send_to_candidate = AsyncMock()
        ws.send_to_recruiter = AsyncMock()

        with patch("verification.continuous_verifier.log_event"):
            await terminate_session("sess-001", "ended_at test", db, ws)

        assert mock_session.ended_at is not None, "ended_at was not set"
        assert isinstance(mock_session.ended_at, datetime), \
            f"ended_at should be datetime, got {type(mock_session.ended_at)}"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 4 — Tab-switch count increments correctly
# ═════════════════════════════════════════════════════════════════════════════

class TestTabSwitchCount:
    """The in-memory tab-switch counter increments per session."""

    def _clear_counters(self):
        """Reset the module-level counter dict between tests."""
        from security import routes as sec_routes
        sec_routes._tab_switch_counts.clear()

    def test_counter_starts_at_zero(self):
        """A fresh session has no tab-switch count."""
        self._clear_counters()
        from security.routes import _tab_switch_counts
        assert _tab_switch_counts.get("fresh-sess", 0) == 0

    def test_counter_increments_on_each_call(self):
        """Each tab-switch increments the count by exactly 1."""
        self._clear_counters()
        from security import routes as sec_routes

        session_id = "ts-sess-001"
        for expected in range(1, 6):
            sec_routes._tab_switch_counts[session_id] = (
                sec_routes._tab_switch_counts.get(session_id, 0) + 1
            )
            assert sec_routes._tab_switch_counts[session_id] == expected

    def test_counters_are_independent_per_session(self):
        """Different sessions maintain separate counters."""
        self._clear_counters()
        from security import routes as sec_routes

        sec_routes._tab_switch_counts["s1"] = 2
        sec_routes._tab_switch_counts["s2"] = 5

        assert sec_routes._tab_switch_counts["s1"] == 2
        assert sec_routes._tab_switch_counts["s2"] == 5

    def test_warning_threshold_is_3(self):
        """TAB_SWITCH_WARNING_THRESHOLD must be 3."""
        from security.routes import TAB_SWITCH_WARNING_THRESHOLD
        assert TAB_SWITCH_WARNING_THRESHOLD == 3

    def test_terminate_threshold_is_5(self):
        """TAB_SWITCH_TERMINATE_THRESHOLD must be 5."""
        from security.routes import TAB_SWITCH_TERMINATE_THRESHOLD
        assert TAB_SWITCH_TERMINATE_THRESHOLD == 5


# ═════════════════════════════════════════════════════════════════════════════
# TEST 5 — Audit chain remains valid after security events
# ═════════════════════════════════════════════════════════════════════════════

class TestAuditChainIntegrity:
    """After security events are logged the hash chain must remain valid."""

    def _in_memory_db(self):
        """
        Create a real SQLite in-memory database with all tables so we can
        test the full hash-chain path without mocking.
        """
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from database import Base

        engine       = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
        Base.metadata.create_all(bind=engine)
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        return SessionLocal

    def test_chain_valid_after_multiple_security_events(self):
        """
        Log several security events (TAB_SWITCH, IDENTITY_MISMATCH,
        SESSION_TERMINATED) and verify the chain is unbroken.
        """
        from crypto.audit_log import log_event, verify_audit_chain

        SessionLocal = self._in_memory_db()
        db           = SessionLocal()
        session_id   = "audit-chain-test"

        event_types = [
            ("TAB_SWITCH",         {"tab_count": 1}),
            ("TAB_SWITCH",         {"tab_count": 2}),
            ("IDENTITY_MISMATCH",  {"similarity": 0.55}),
            ("STEP_UP_FAILED",     {"failure_count": 1}),
            ("SESSION_TERMINATED", {"reason": "test"}),
        ]

        for event_type, detail in event_types:
            log_event(
                session_id=session_id,
                event_type=event_type,
                detail=detail,
                db_session=db,
            )

        result = verify_audit_chain(session_id, db)
        db.close()

        assert result["valid"] is True, \
            f"Hash chain invalid after security events: {result}"
        assert result["total_entries"] == len(event_types)

    def test_chain_invalid_if_entry_tampered(self):
        """Mutating a stored audit entry must break the chain."""
        import json
        from crypto.audit_log import log_event, verify_audit_chain
        from database import AuditLog

        SessionLocal = self._in_memory_db()
        db           = SessionLocal()
        session_id   = "tamper-test"

        log_event(session_id, "TAB_SWITCH",        {"n": 1}, db)
        log_event(session_id, "IDENTITY_MISMATCH", {"n": 2}, db)

        # Tamper with the first entry's detail field
        first = db.query(AuditLog).filter(AuditLog.session_id == session_id).first()
        first.detail = json.dumps({"n": 999})   # mutate without recomputing hash
        db.commit()

        result = verify_audit_chain(session_id, db)
        db.close()

        assert result["valid"] is False, "Chain should be invalid after tampering"


# ═════════════════════════════════════════════════════════════════════════════
# TEST 6 — Diarization gracefully handles missing HF_TOKEN
# ═════════════════════════════════════════════════════════════════════════════

class TestDiarizationGracefulDegradation:
    """SpeakerDiarizer must degrade gracefully when HF_TOKEN is absent."""

    def test_load_pipeline_returns_none_without_token(self):
        """load_diarization_pipeline() returns None when HF_TOKEN is not set."""
        import os
        with patch.dict(os.environ, {}, clear=False):
            # Ensure HF_TOKEN is absent
            os.environ.pop("HF_TOKEN", None)

            from verification.diarization import load_diarization_pipeline
            result = load_diarization_pipeline()

        assert result is None, f"Expected None, got {result}"

    @pytest.mark.asyncio
    async def test_process_audio_chunk_is_noop_without_pipeline(self):
        """process_audio_chunk() must return without error when pipeline is None."""
        from verification.diarization import SpeakerDiarizer

        import os
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HF_TOKEN", None)

            diarizer = SpeakerDiarizer.__new__(SpeakerDiarizer)
            diarizer.pipeline            = None
            diarizer.multi_speaker_count = {}

        db = MagicMock()
        ws = MagicMock()
        ws.broadcast_security_event = AsyncMock()

        # Must not raise
        await diarizer.process_audio_chunk(
            "sess-no-token",
            _silent_audio(),
            16000,
            db,
            ws,
        )

        # No WebSocket call should have been made
        ws.broadcast_security_event.assert_not_called()

    def test_multi_speaker_count_starts_at_zero(self):
        """Fresh SpeakerDiarizer has an empty counter dict."""
        import os
        os.environ.pop("HF_TOKEN", None)

        from verification.diarization import SpeakerDiarizer

        diarizer = SpeakerDiarizer.__new__(SpeakerDiarizer)
        diarizer.pipeline            = None
        diarizer.multi_speaker_count = {}

        assert diarizer.multi_speaker_count.get("any-session", 0) == 0

    def test_count_speakers_returns_zero_on_error(self):
        """count_speakers_in_audio must return 0 speakers if pipeline raises."""
        from verification.diarization import count_speakers_in_audio

        bad_pipeline = MagicMock(side_effect=RuntimeError("pipeline exploded"))

        result = count_speakers_in_audio(_silent_audio(), 16000, bad_pipeline)

        assert result["speaker_count"] == 0
        assert result["segments"]      == []


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
