"""
MIIC-Sec — Emotion & Behaviour Analysis
Runs in a background thread during an active interview session.

Dependencies:
    FER          — facial emotion recognition
    MediaPipe    — face mesh / gaze estimation
    OpenAI Whisper (local, "small" model) — speech transcription
"""

import threading
import time
from queue import Empty, Queue
from typing import Dict, List

import numpy as np

import config


# ─── Lazy-loaded module caches ───────────────────────────────────
_whisper_model = None
_face_mesh = None
_fer_detector = None


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        _whisper_model = whisper.load_model(config.WHISPER_MODEL)
    return _whisper_model


def _get_fer():
    global _fer_detector
    if _fer_detector is None:
        from fer import FER
        _fer_detector = FER(mtcnn=True)
    return _fer_detector


def _get_face_mesh():
    global _face_mesh
    if _face_mesh is None:
        import mediapipe as mp
        _face_mesh = mp.solutions.face_mesh.FaceMesh(
            static_image_mode=True,
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
        )
    return _face_mesh


# Filler words to track
FILLER_WORDS = {"uh", "um", "hmm", "like", "you", "know"}
FILLER_PHRASES = {"you know"}


# ═══════════════════════════════════════════════════════════════════
# 1. analyze_emotion
# ═══════════════════════════════════════════════════════════════════

def analyze_emotion(frame: np.ndarray) -> dict:
    """
    Detect the dominant emotion in a video frame using the FER library.

    Args:
        frame: BGR image as a numpy array (H, W, 3).

    Returns:
        {"emotion": str, "confidence": float}
        On error: {"emotion": "unknown", "confidence": 0.0}
    """
    try:
        detector = _get_fer()
        results = detector.detect_emotions(frame)

        if not results:
            return {"emotion": "neutral", "confidence": 0.0}

        # Take the first detected face
        emotions: dict = results[0]["emotions"]
        top_emotion = max(emotions, key=emotions.get)
        confidence = round(float(emotions[top_emotion]), 4)

        return {"emotion": top_emotion, "confidence": confidence}

    except Exception as exc:
        print(f"⚠️  analyze_emotion error: {exc}")
        return {"emotion": "unknown", "confidence": 0.0}


# ═══════════════════════════════════════════════════════════════════
# 2. analyze_gaze
# ═══════════════════════════════════════════════════════════════════

def analyze_gaze(frame: np.ndarray) -> dict:
    """
    Estimate whether the candidate is looking at the screen using
    MediaPipe Face Mesh landmarks.

    Heuristic: compute the horizontal and vertical offset of the nose
    tip (landmark 1) relative to the frame centre. If the offset exceeds
    20 % of the frame dimensions the candidate is considered to be
    looking away.

    Args:
        frame: BGR image as a numpy array (H, W, 3).

    Returns:
        {"looking_at_screen": bool, "gaze_score": float}
        gaze_score is 1.0 when centred, 0.0 when fully off-centre.
    """
    try:
        import cv2
        import mediapipe as mp

        h, w = frame.shape[:2]
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        mesh = _get_face_mesh()
        result = mesh.process(rgb)

        if not result.multi_face_landmarks:
            return {"looking_at_screen": False, "gaze_score": 0.0}

        landmarks = result.multi_face_landmarks[0].landmark
        # Landmark 1 = nose tip; landmark 4 = nose bridge
        nose_x = landmarks[1].x  # normalised 0–1
        nose_y = landmarks[1].y

        # Deviation from centre (0.5, 0.5)
        dx = abs(nose_x - 0.5)
        dy = abs(nose_y - 0.5)
        max_deviation = max(dx, dy)

        # Threshold: 20 % of normalised coordinate space
        THRESHOLD = 0.20
        looking = max_deviation < THRESHOLD
        gaze_score = round(max(0.0, 1.0 - (max_deviation / THRESHOLD)), 4)

        return {"looking_at_screen": looking, "gaze_score": min(1.0, gaze_score)}

    except Exception as exc:
        print(f"⚠️  analyze_gaze error: {exc}")
        return {"looking_at_screen": False, "gaze_score": 0.0}


# ═══════════════════════════════════════════════════════════════════
# 3. analyze_speech
# ═══════════════════════════════════════════════════════════════════

def analyze_speech(audio_array: np.ndarray, sample_rate: int) -> dict:
    """
    Transcribe an audio clip with local Whisper and compute basic
    fluency metrics.

    Args:
        audio_array:  Float32 mono audio samples.
        sample_rate:  Samples per second (typically 16 000).

    Returns:
        {
            "transcript":         str,
            "filler_count":       int,
            "words_per_minute":   float,
            "speech_confidence":  float   # Whisper segment-level avg
        }
    """
    try:
        import whisper

        model = _get_whisper()

        # Whisper expects float32 mono at 16 kHz
        if audio_array.dtype != np.float32:
            audio_array = audio_array.astype(np.float32)

        result = model.transcribe(audio_array, language="en", fp16=False)
        transcript: str = result.get("text", "").strip()

        # ── Filler word count ─────────────────────────────────────
        words = transcript.lower().split()
        filler_count = sum(1 for w in words if w in FILLER_WORDS)
        # Also catch bi-gram filler "you know"
        bigrams = [f"{words[i]} {words[i+1]}" for i in range(len(words) - 1)]
        filler_count += sum(1 for bg in bigrams if bg in FILLER_PHRASES)

        # ── Words per minute ──────────────────────────────────────
        duration_seconds = len(audio_array) / max(sample_rate, 1)
        duration_minutes = duration_seconds / 60.0
        wpm = round(len(words) / duration_minutes, 2) if duration_minutes > 0 else 0.0

        # ── Whisper confidence (average no_speech_prob inverse) ───
        segments = result.get("segments", [])
        if segments:
            avg_no_speech = sum(s.get("no_speech_prob", 0.0) for s in segments) / len(segments)
            speech_confidence = round(1.0 - avg_no_speech, 4)
        else:
            speech_confidence = 1.0 if transcript else 0.0

        return {
            "transcript": transcript,
            "filler_count": filler_count,
            "words_per_minute": wpm,
            "speech_confidence": speech_confidence,
        }

    except Exception as exc:
        print(f"⚠️  analyze_speech error: {exc}")
        return {
            "transcript": "",
            "filler_count": 0,
            "words_per_minute": 0.0,
            "speech_confidence": 0.0,
        }


# ═══════════════════════════════════════════════════════════════════
# 4. run_emotion_analysis_loop
# ═══════════════════════════════════════════════════════════════════

def run_emotion_analysis_loop(
    session_id: str,
    frame_queue: Queue,
    audio_queue: Queue,
    result_store: dict,
    stop_event: threading.Event,
) -> None:
    """
    Background analysis loop that runs in a dedicated thread.

    Schedule:
        • Every 15 seconds — process the latest video frame from frame_queue.
        • Every 30 seconds — process the latest audio chunk from audio_queue.

    Results are appended to result_store[session_id] as a list of dicts.

    Args:
        session_id:   Session identifier.
        frame_queue:  Queue of np.ndarray BGR frames (producer: webcam capture).
        audio_queue:  Queue of (np.ndarray, int) tuples — (audio, sample_rate).
        result_store: Shared dict; entries appended under key session_id.
        stop_event:   Threading event; loop exits when set.
    """
    if session_id not in result_store:
        result_store[session_id] = []

    last_frame_time = 0.0
    last_audio_time = 0.0

    FRAME_INTERVAL = 15   # seconds
    AUDIO_INTERVAL = 30   # seconds

    print(f"🔍 Emotion analysis loop started for session {session_id}")

    while not stop_event.is_set():
        now = time.time()
        snapshot: dict = {"timestamp": now}

        # ── Video (emotion + gaze) ────────────────────────────────
        if now - last_frame_time >= FRAME_INTERVAL:
            latest_frame = None
            while True:
                try:
                    latest_frame = frame_queue.get_nowait()
                except Empty:
                    break

            if latest_frame is not None:
                snapshot["emotion"] = analyze_emotion(latest_frame)
                snapshot["gaze"] = analyze_gaze(latest_frame)
                last_frame_time = now
                print(f"📷  [{session_id}] emotion={snapshot['emotion']['emotion']} "
                      f"gaze={snapshot['gaze']['looking_at_screen']}")

        # ── Audio (speech analysis) ───────────────────────────────
        if now - last_audio_time >= AUDIO_INTERVAL:
            latest_audio = None
            while True:
                try:
                    latest_audio = audio_queue.get_nowait()
                except Empty:
                    break

            if latest_audio is not None:
                audio_array, sample_rate = latest_audio
                snapshot["speech"] = analyze_speech(audio_array, sample_rate)
                last_audio_time = now
                print(f"🎤  [{session_id}] filler_count={snapshot['speech']['filler_count']} "
                      f"wpm={snapshot['speech']['words_per_minute']}")

        if len(snapshot) > 1:  # something was added beyond timestamp
            result_store[session_id].append(snapshot)

        # Sleep in small increments so stop_event is responsive
        for _ in range(5):
            if stop_event.is_set():
                break
            time.sleep(1)

    print(f"🛑 Emotion analysis loop stopped for session {session_id}")
