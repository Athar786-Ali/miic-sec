"""
MIIC-Sec — Phase 6 Tests
Verifies the voice-to-text pipeline contracts:
  - Audio upload returns 400 (not 500) on bad audio
  - WAV input is accepted and passed to Whisper with expected options

Run with:
    cd backend
    pytest ../tests/test_phase6.py -v
"""

import io
import math
import os
import struct
import sys
import wave
from unittest.mock import patch

import pytest


# ── Ensure backend/ is on the path ──────────────────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND_DIR = os.path.join(ROOT_DIR, "backend")
sys.path.insert(0, BACKEND_DIR)


# ═════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════

def _wav_sine_bytes(duration_s: float = 1.2, freq_hz: float = 440.0, sample_rate: int = 16000) -> bytes:
    """Generate a small mono PCM16 WAV (in-memory) for testing."""
    frames = max(1, int(duration_s * sample_rate))
    amp = 0.25
    pcm = bytearray()
    for i in range(frames):
        sample = int(amp * 32767.0 * math.sin(2.0 * math.pi * freq_hz * (i / sample_rate)))
        pcm += struct.pack("<h", sample)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(bytes(pcm))
    return buf.getvalue()


# ═════════════════════════════════════════════════════════════════
# Tests
# ═════════════════════════════════════════════════════════════════

class TestTranscribeRoute:
    def _client(self):
        from fastapi.testclient import TestClient
        from main import app
        from interview.routes import get_token_payload

        # Bypass auth for this test suite
        app.dependency_overrides[get_token_payload] = lambda: {"sub": "test"}
        return TestClient(app)

    def test_bad_audio_returns_400_not_500(self):
        client = self._client()
        files = {"audio_file": ("voice.webm", b"0" * 110, "audio/webm")}
        r = client.post("/interview/transcribe", files=files)
        assert r.status_code == 400
        assert "decode" in r.json()["detail"].lower() or "short" in r.json()["detail"].lower()

    def test_wav_upload_calls_whisper_with_expected_options(self):
        client = self._client()

        audio = _wav_sine_bytes()
        files = {"audio_file": ("voice.wav", audio, "audio/wav")}

        class _FakeModel:
            def __init__(self):
                self.calls = []

            def transcribe(self, path, **kwargs):
                # Ensure ffmpeg produced a real file that Whisper would read
                assert os.path.exists(path)
                self.calls.append((path, kwargs))
                return {"text": "test transcript"}

        fake = _FakeModel()

        # Avoid downloading/loading a real Whisper model in tests
        with patch("interview.transcriber._get_model", return_value=fake):
            r = client.post("/interview/transcribe", files=files)

        assert r.status_code == 200
        data = r.json()
        assert data["transcript"] == "test transcript"
        assert data["confidence"] == pytest.approx(0.95)

        assert len(fake.calls) == 1
        _path, kwargs = fake.calls[0]
        assert kwargs.get("language") is None
        assert kwargs.get("task") == "transcribe"
        assert kwargs.get("fp16") is False
        assert kwargs.get("condition_on_previous_text") is False
