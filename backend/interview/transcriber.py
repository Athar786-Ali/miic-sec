"""
MIIC-Sec — Audio Transcriber (Deepgram)

Replaces Whisper with Deepgram's pre-recorded transcription REST API.

Pipeline:
  1. Receive raw audio bytes from the browser (WebM / OGG / WAV / MP4)
  2. POST directly to Deepgram /v1/listen (no local ffmpeg conversion needed)
  3. Return { transcript, confidence }

Requirements:
  - DEEPGRAM_API_KEY set in backend/.env
  - httpx installed (already in requirements.txt)
"""

import logging
import os

import httpx

logger = logging.getLogger(__name__)

# ─── Whisper compatibility shim ───────────────────────────────────────────────
# _get_model() is kept as a patchable stub for unit tests that mock Whisper.
# In production the Deepgram REST path is used instead (see transcribe_audio()).
_whisper_model_cache: dict = {}

def _get_model(model_name: str = "base"):
    """Return (or lazily load) a Whisper model — stub for test patching."""
    if model_name not in _whisper_model_cache:
        try:
            import whisper  # type: ignore
            _whisper_model_cache[model_name] = whisper.load_model(model_name)
        except Exception:
            return None
    return _whisper_model_cache.get(model_name)


# ─── Deepgram REST endpoint ───────────────────────────────────────────────────
DEEPGRAM_URL = (
    "https://api.deepgram.com/v1/listen"
    "?model=nova-2"
    "&language=en-IN"          # Indian English; change to 'en' for global
    "&smart_format=true"
    "&punctuate=true"
    "&utterances=false"
    "&detect_language=false"
)

# ─── Content-type map ─────────────────────────────────────────────────────────
_MIME_MAP = {
    ".webm":  "audio/webm",
    ".weba":  "audio/webm",
    ".ogg":   "audio/ogg",
    ".oga":   "audio/ogg",
    ".wav":   "audio/wav",
    ".mp4":   "audio/mp4",
    ".m4a":   "audio/mp4",
    ".mp3":   "audio/mpeg",
    ".flac":  "audio/flac",
}


def _resolve_content_type(filename: str | None, content_type: str | None) -> str:
    """
    Determine the best Content-Type to send to Deepgram.
    Falls back to audio/webm (most common browser MediaRecorder output).
    """
    name = (filename or "").lower()
    for ext, mime in _MIME_MAP.items():
        if name.endswith(ext):
            return mime

    ct = (content_type or "").lower()
    for mime in _MIME_MAP.values():
        if mime in ct:
            return mime

    return "audio/webm"


def transcribe_audio(
    audio_bytes: bytes,
    filename: str | None = None,
    content_type: str | None = None,
) -> dict:
    """
    Transcribe audio bytes.

    Primary path  — Deepgram REST API (requires DEEPGRAM_API_KEY in .env)
    Fallback path — local Whisper model via _get_model() (no API key needed,
                    useful for offline/test environments)

    Args:
        audio_bytes:  Raw bytes from the browser MediaRecorder.
        filename:     Original filename (used for MIME detection).
        content_type: HTTP Content-Type header from upload.

    Returns:
        { "transcript": str, "confidence": float }
    """
    if not audio_bytes or len(audio_bytes) < 100:
        raise ValueError(
            "Audio file is empty or too short. "
            "Please record at least 1 second of speech."
        )

    api_key = (os.environ.get("DEEPGRAM_API_KEY") or "").strip()

    # ── Whisper fallback (no API key / test environment) ──────────────────────
    if not api_key:
        return _transcribe_whisper(audio_bytes, filename)

    # ── Primary: Deepgram REST ────────────────────────────────────────────────
    mime = _resolve_content_type(filename, content_type)
    logger.info(
        "Deepgram transcribe — filename=%s size=%d mime=%s",
        filename, len(audio_bytes), mime,
    )

    headers = {
        "Authorization": f"Token {api_key}",
        "Content-Type":  mime,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            response = client.post(
                DEEPGRAM_URL,
                headers=headers,
                content=audio_bytes,
            )
    except httpx.TimeoutException as exc:
        logger.error("Deepgram request timed out: %s", exc)
        raise RuntimeError(
            "Deepgram transcription timed out. "
            "Check your internet connection and try again."
        ) from exc
    except httpx.HTTPError as exc:
        logger.error("Deepgram HTTP error: %s", exc)
        raise RuntimeError(f"Deepgram request failed: {exc}") from exc

    # ── Parse response ────────────────────────────────────────────────────────
    if response.status_code == 400:
        body = response.text[:300]
        logger.warning("Deepgram 400: %s", body)
        raise ValueError(
            "Deepgram could not decode the audio. "
            "Please record again and speak clearly."
        )

    if response.status_code == 401:
        raise RuntimeError(
            "Deepgram API key is invalid or expired. "
            "Update DEEPGRAM_API_KEY in backend/.env."
        )

    if response.status_code == 402:
        raise RuntimeError(
            "Deepgram account quota exceeded. "
            "Check your Deepgram dashboard for usage limits."
        )

    if response.status_code not in (200, 201):
        body = response.text[:300]
        logger.error("Deepgram unexpected status %d: %s", response.status_code, body)
        raise RuntimeError(
            f"Deepgram returned HTTP {response.status_code}. "
            "Please try again."
        )

    try:
        data = response.json()
    except Exception as exc:
        raise RuntimeError(f"Deepgram returned non-JSON response: {exc}") from exc

    try:
        channel     = data["results"]["channels"][0]
        alternative = channel["alternatives"][0]
        transcript  = alternative.get("transcript", "").strip()
        confidence  = float(alternative.get("confidence", 0.0))
    except (KeyError, IndexError, TypeError) as exc:
        logger.error("Deepgram response parse error: %s — body: %s", exc, str(data)[:300])
        raise ValueError(
            "Deepgram returned an unexpected response format. "
            "Please try recording again."
        ) from exc

    if not transcript:
        raise ValueError(
            "No speech detected in your recording. "
            "Please speak clearly and try again."
        )

    logger.info(
        "Deepgram transcript (%d chars, confidence=%.2f): %s",
        len(transcript), confidence, transcript[:80],
    )

    return {
        "transcript": transcript,
        "confidence": round(confidence, 4),
    }


def _transcribe_whisper(audio_bytes: bytes, filename: str | None) -> dict:
    """
    Local Whisper transcription via _get_model().
    Used when DEEPGRAM_API_KEY is absent (offline / test environments).
    Tests can patch interview.transcriber._get_model to inject a fake model.
    """
    import tempfile, os as _os

    # Write bytes to a temp file so Whisper / the fake model can read it
    suffix = f".{(filename or 'audio.wav').rsplit('.', 1)[-1]}"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio_bytes)
        tmp_path = tmp.name

    try:
        model = _get_model()
        if model is None:
            raise RuntimeError(
                "No transcription backend available. "
                "Set DEEPGRAM_API_KEY in backend/.env or install openai-whisper."
            )
        result = model.transcribe(
            tmp_path,
            language=None,
            task="transcribe",
            fp16=False,
            condition_on_previous_text=False,
        )
        transcript = (result.get("text") or "").strip()
        if not transcript:
            raise ValueError(
                "No speech detected. Please speak clearly and try again."
            )
        return {"transcript": transcript, "confidence": 0.95}
    finally:
        try:
            _os.unlink(tmp_path)
        except OSError:
            pass

