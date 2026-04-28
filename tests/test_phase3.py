"""
MIIC-Sec — Phase 3 Test Suite
Tests for the AI Interview Engine (Tier 2).

Run with:
    cd backend
    pytest ../tests/test_phase3.py -v
"""

import re
import threading
import time
from queue import Queue
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ═══════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════

def _black_frame(h: int = 480, w: int = 640) -> np.ndarray:
    """Return a pure-black BGR frame for testing."""
    return np.zeros((h, w, 3), dtype=np.uint8)


# ═══════════════════════════════════════════════════════════════════
# TEST 1 — Ollama connection check
# ═══════════════════════════════════════════════════════════════════

class TestOllamaCheck:
    def test_returns_true_when_reachable(self):
        """check_ollama_running should return True for a 200 response."""
        import sys
        sys.path.insert(0, ".")  # ensure backend/ is on path

        from interview.llm_interviewer import check_ollama_running

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("interview.llm_interviewer.requests.get", return_value=mock_response):
            assert check_ollama_running() is True

    def test_returns_false_when_unreachable(self):
        """check_ollama_running should return False on ConnectionError."""
        import sys
        sys.path.insert(0, ".")

        from interview.llm_interviewer import check_ollama_running
        import requests as req_lib

        with patch("interview.llm_interviewer.requests.get", side_effect=req_lib.ConnectionError):
            assert check_ollama_running() is False

    def test_returns_false_on_non_200(self):
        """check_ollama_running should return False for non-200 status."""
        import sys
        sys.path.insert(0, ".")

        from interview.llm_interviewer import check_ollama_running

        mock_response = MagicMock()
        mock_response.status_code = 500

        with patch("interview.llm_interviewer.requests.get", return_value=mock_response):
            assert check_ollama_running() is False


# ═══════════════════════════════════════════════════════════════════
# TEST 2 — Adaptive difficulty logic (no LLM required)
# ═══════════════════════════════════════════════════════════════════

class TestAdaptiveDifficulty:
    def test_rolling_average_full_window(self):
        from interview.adaptive_engine import calculate_rolling_average
        scores = [5.0, 6.0, 8.0, 9.0]
        avg = calculate_rolling_average(scores, window=3)
        assert abs(avg - (8.0 + 9.0 + 6.0) / 3) < 1e-6  # last 3: 6,8,9

    def test_rolling_average_empty(self):
        from interview.adaptive_engine import calculate_rolling_average
        assert calculate_rolling_average([]) == 0.0

    def test_rolling_average_fewer_than_window(self):
        from interview.adaptive_engine import calculate_rolling_average
        scores = [4.0, 6.0]
        avg = calculate_rolling_average(scores, window=3)
        assert abs(avg - 5.0) < 1e-6

    def test_difficulty_increases_on_high_scores(self):
        from interview.adaptive_engine import adjust_difficulty
        scores = [8.0, 9.0, 8.5]
        assert adjust_difficulty("medium", scores) == "hard"

    def test_difficulty_decreases_on_low_scores(self):
        from interview.adaptive_engine import adjust_difficulty
        scores = [2.0, 3.0, 4.0]
        assert adjust_difficulty("medium", scores) == "easy"

    def test_difficulty_unchanged_mid_range(self):
        from interview.adaptive_engine import adjust_difficulty
        scores = [5.0, 6.0, 6.5]
        assert adjust_difficulty("medium", scores) == "medium"

    def test_already_at_hard_stays_hard(self):
        from interview.adaptive_engine import adjust_difficulty
        scores = [9.0, 9.0, 9.0]
        assert adjust_difficulty("hard", scores) == "hard"

    def test_already_at_easy_stays_easy(self):
        from interview.adaptive_engine import adjust_difficulty
        scores = [1.0, 1.0, 1.0]
        assert adjust_difficulty("easy", scores) == "easy"

    def test_get_difficulty_prompt_easy(self):
        from interview.adaptive_engine import get_difficulty_prompt
        prompt = get_difficulty_prompt("easy", "DSA")
        assert "DSA" in prompt
        assert "basic" in prompt.lower() or "beginner" in prompt.lower()

    def test_get_difficulty_prompt_hard(self):
        from interview.adaptive_engine import get_difficulty_prompt
        prompt = get_difficulty_prompt("hard", "OS")
        assert "OS" in prompt
        assert "advanced" in prompt.lower() or "deep" in prompt.lower()

    def test_domain_rotation(self):
        from interview.adaptive_engine import DOMAINS, get_domain_for_question
        for i, domain in enumerate(DOMAINS, start=1):
            assert get_domain_for_question(i) == domain
        # Wraps around
        assert get_domain_for_question(len(DOMAINS) + 1) == DOMAINS[0]


# ═══════════════════════════════════════════════════════════════════
# TEST 3 — Emotion analysis with a dummy black frame
# ═══════════════════════════════════════════════════════════════════

# MediaPipe hard-crashes (SIGSEGV) on Python 3.13 + Anaconda on M1.
# Detect this at collection time and skip gracefully.
def _mediapipe_available() -> bool:
    """Return True only if mediapipe can be imported without crashing."""
    import subprocess, sys
    result = subprocess.run(
        [sys.executable, "-c", "import mediapipe"],
        capture_output=True,
        timeout=15,
    )
    return result.returncode == 0


_mp_available = _mediapipe_available()


@pytest.mark.skipif(
    not _mp_available,
    reason=(
        "MediaPipe cannot be imported in this environment (Python 3.13 + Anaconda M1). "
        "Run with Python ≤3.12 or a dedicated venv to enable emotion tests."
    ),
)
class TestEmotionAnalysis:
    """
    Heavy ML libs (FER/MediaPipe/Whisper) are patched to avoid loading
    TF/Keras on Python 3.13 where they are not yet compatible.
    The tests verify the contract: correct keys, correct types,
    and graceful error handling.
    """


    def test_analyze_emotion_no_face_returns_neutral(self):
        """When FER finds no faces it should return neutral with 0.0 confidence."""
        # Patch _get_fer to return a mock that finds no faces
        mock_fer = MagicMock()
        mock_fer.detect_emotions.return_value = []  # no faces

        import interview.emotion_analysis as ea
        with patch.object(ea, "_get_fer", return_value=mock_fer):
            result = ea.analyze_emotion(_black_frame())

        assert result["emotion"] == "neutral"
        assert result["confidence"] == 0.0

    def test_analyze_emotion_returns_top_emotion(self):
        """When FER finds a face the top emotion should be returned."""
        mock_fer = MagicMock()
        mock_fer.detect_emotions.return_value = [
            {"emotions": {"happy": 0.8, "sad": 0.1, "neutral": 0.1}}
        ]

        import interview.emotion_analysis as ea
        with patch.object(ea, "_get_fer", return_value=mock_fer):
            result = ea.analyze_emotion(_black_frame())

        assert result["emotion"] == "happy"
        assert abs(result["confidence"] - 0.8) < 1e-4

    def test_analyze_emotion_error_returns_unknown(self):
        """Any exception inside FER → {emotion: unknown, confidence: 0.0}."""
        import interview.emotion_analysis as ea
        with patch.object(ea, "_get_fer", side_effect=RuntimeError("FER crash")):
            result = ea.analyze_emotion(_black_frame())

        assert result["emotion"] == "unknown"
        assert result["confidence"] == 0.0

    def test_analyze_gaze_no_face_returns_false(self):
        """No face landmarks → looking_at_screen=False, gaze_score=0.0."""
        mock_mesh_instance = MagicMock()
        mock_result = MagicMock()
        mock_result.multi_face_landmarks = None
        mock_mesh_instance.process.return_value = mock_result

        import interview.emotion_analysis as ea
        with patch.object(ea, "_get_face_mesh", return_value=mock_mesh_instance):
            result = ea.analyze_gaze(_black_frame())

        assert result["looking_at_screen"] is False
        assert result["gaze_score"] == 0.0

    def test_analyze_gaze_centred_face_is_looking(self):
        """A face centred in the frame → looking_at_screen=True."""
        mock_mesh_instance = MagicMock()

        # Build a mock landmark with nose-tip at centre (0.5, 0.5)
        landmark = MagicMock()
        landmark.x = 0.5
        landmark.y = 0.5

        face_landmarks = MagicMock()
        face_landmarks.landmark = [None, landmark]  # index 1 = nose tip

        mock_result = MagicMock()
        mock_result.multi_face_landmarks = [face_landmarks]
        mock_mesh_instance.process.return_value = mock_result

        import cv2
        import interview.emotion_analysis as ea
        with patch.object(ea, "_get_face_mesh", return_value=mock_mesh_instance), \
             patch("interview.emotion_analysis.cv2", cv2):
            result = ea.analyze_gaze(_black_frame())

        assert result["looking_at_screen"] is True
        assert result["gaze_score"] > 0.0


# ═══════════════════════════════════════════════════════════════════
# TEST 4 — Static analysis flags os.system as security issue
# ═══════════════════════════════════════════════════════════════════

class TestStaticAnalysis:
    def test_os_system_flagged(self):
        from interview.code_sandbox import run_static_analysis
        code = "import os\nos.system('rm -rf /')\n"
        issues = run_static_analysis(code, "python")
        severities = [i["severity"] for i in issues]
        messages  = [i["message"] for i in issues]
        assert any("os.system" in m for m in messages), \
            f"Expected os.system issue, got: {issues}"
        assert "HIGH" in severities

    def test_eval_flagged(self):
        from interview.code_sandbox import run_static_analysis
        code = "eval('print(1)')\n"
        issues = run_static_analysis(code, "python")
        messages = [i["message"] for i in issues]
        assert any("eval" in m.lower() for m in messages)

    def test_clean_code_no_issues(self):
        from interview.code_sandbox import run_static_analysis
        code = "def add(a, b):\n    return a + b\nprint(add(1, 2))\n"
        issues = run_static_analysis(code, "python")
        # Should have no HIGH-severity issues from pattern scan
        high_issues = [i for i in issues if i["severity"] == "HIGH"]
        assert len(high_issues) == 0, f"Unexpected HIGH issues: {high_issues}"


# ─── Docker availability helper (must be defined before TestSandboxTimeout) ──

def _is_docker_available() -> bool:
    import subprocess
    try:
        r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════
# TEST 5 — Sandbox timeout (infinite loop)
# ═══════════════════════════════════════════════════════════════════

class TestSandboxTimeout:
    @pytest.mark.skipif(
        not _is_docker_available(),
        reason="Docker not available in this environment",
    )
    def test_infinite_loop_times_out(self):
        from interview.code_sandbox import execute_in_sandbox
        code = "while True: pass\n"
        result = execute_in_sandbox(code, "python", "test-session-timeout")
        assert result["timed_out"] is True
        assert result["exit_code"] != 0

    def test_evaluate_code_blocks_on_security_issue(self):
        """evaluate_code should short-circuit on HIGH-severity static issues."""
        from interview.code_sandbox import evaluate_code
        code = "os.system('whoami')\n"
        result = evaluate_code(code, "python", "test-session-security")
        assert result["passed"] is False
        assert "Security violation" in result.get("reason", "")


# ═══════════════════════════════════════════════════════════════════
# TEST 6 — Score parsing from LLM response string
# ═══════════════════════════════════════════════════════════════════

class TestScoreParsing:
    """Unit tests for _parse_evaluation — no LLM call needed."""

    def _parse(self, text: str) -> dict:
        # Import private helper directly
        from interview.llm_interviewer import _parse_evaluation
        return _parse_evaluation(text)

    def test_standard_format_parsed(self):
        text = (
            "SCORE: 8\n"
            "FEEDBACK: Good explanation of recursion.\n"
            "NEXT_QUESTION: What is a binary search tree?"
        )
        result = self._parse(text)
        assert result["score"] == 8.0
        assert "recursion" in result["feedback"].lower()
        assert "binary search" in result["next_question"].lower()

    def test_decimal_score(self):
        text = "SCORE: 7.5\nFEEDBACK: Decent.\nNEXT_QUESTION: Explain Big-O notation."
        result = self._parse(text)
        assert result["score"] == 7.5

    def test_score_clamped_to_10(self):
        text = "SCORE: 15\nFEEDBACK: Excellent.\nNEXT_QUESTION: Next?"
        result = self._parse(text)
        assert result["score"] == 10.0

    def test_score_clamped_to_0(self):
        text = "SCORE: -3\nFEEDBACK: Terrible.\nNEXT_QUESTION: Try again."
        result = self._parse(text)
        assert result["score"] == 0.0

    def test_regex_fallback_extracts_score(self):
        """When structured tags are absent, regex should still find the score."""
        text = "The candidate scored 6 out of 10. Overall acceptable performance."
        result = self._parse(text)
        # Default is 5.0; regex should override with 6
        assert result["score"] == 6.0

    def test_missing_score_returns_default(self):
        text = "FEEDBACK: No score here.\nNEXT_QUESTION: What is polymorphism?"
        result = self._parse(text)
        # Default score is 5.0
        assert result["score"] == 5.0

    def test_case_insensitive_keys(self):
        text = "score: 9\nfeedback: Perfect.\nnext_question: Describe TCP."
        result = self._parse(text)
        assert result["score"] == 9.0


# ═══════════════════════════════════════════════════════════════════
# Entry point
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
