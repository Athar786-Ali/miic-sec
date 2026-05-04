"""
MIIC-Sec — Audio Transcriber (Whisper)

Browser MediaRecorder sends audio/webm (Opus codec).
Whisper needs PCM WAV (16 kHz, mono) for best results.

Pipeline:
  1. Save incoming bytes to a temp .webm file
  2. Use subprocess ffmpeg to convert → 16 kHz mono WAV
  3. Feed the WAV to Whisper (fp16=False for CPU safety)
  4. Return { transcript, confidence }

Requirements:
  - ffmpeg must be installed (brew install ffmpeg on macOS)
  - openai-whisper must be installed (pip install openai-whisper)
"""

import logging
import os
import subprocess
import tempfile

import whisper

logger = logging.getLogger(__name__)

# ─── Ensure Homebrew ffmpeg is in PATH ───────────────────────────────────────
for _brew_path in ("/opt/homebrew/bin", "/usr/local/bin"):
    if _brew_path not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{_brew_path}:{os.environ.get('PATH', '')}"

# ─── Lazy-load model (singleton) ─────────────────────────────────────────────
_model = None

def _get_model() -> whisper.Whisper:
    """Load the Whisper model once and cache it."""
    global _model
    if _model is None:
        import config
        model_name = getattr(config, "WHISPER_MODEL", "small")
        logger.info("Loading Whisper model: %s …", model_name)
        _model = whisper.load_model(model_name)
        logger.info("Whisper model '%s' ready.", model_name)
    return _model


def _convert_to_wav(input_path: str, output_path: str) -> bool:
    """
    Convert any audio file (webm/ogg/mp4/…) to 16 kHz mono PCM WAV
    using the system ffmpeg.  Returns True on success.

    Tries with an explicit -f webm hint first (handles browsers that write
    incomplete EBML headers), then falls back without the hint.
    """
    base_cmd = [
        "ffmpeg", "-y",
        "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le",
        output_path,
    ]

    # Attempt 1 — with explicit webm format hint (fixes incomplete EBML headers)
    # Attempt 2 — without hint (let ffmpeg auto-detect)
    attempts = [
        ["ffmpeg", "-y", "-f", "webm", "-i", input_path,
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", output_path],
        ["ffmpeg", "-y", "-i", input_path,
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", output_path],
    ]

    for i, cmd in enumerate(attempts, 1):
        try:
            result = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
            if result.returncode == 0:
                logger.info("ffmpeg conversion succeeded (attempt %d)", i)
                return True
            logger.debug(
                "ffmpeg attempt %d failed (code %d): %s",
                i, result.returncode,
                result.stderr.decode(errors="replace")[-300:],
            )
        except FileNotFoundError:
            logger.error("ffmpeg not found. Install it with: brew install ffmpeg")
            return False
        except subprocess.TimeoutExpired:
            logger.error("ffmpeg conversion timed out.")
            return False

    logger.error("ffmpeg: all conversion attempts failed for %s", input_path)
    return False


def transcribe_audio(audio_bytes: bytes) -> dict:
    """
    Transcribe audio bytes (webm/ogg/wav/mp4 …) to text.

    Args:
        audio_bytes: raw bytes from the browser MediaRecorder

    Returns:
        { "transcript": str, "confidence": float }

    Raises:
        RuntimeError on transcription failure
    """
    if not audio_bytes:
        raise RuntimeError("Empty audio data received.")

    if len(audio_bytes) < 1000:
        # Suspiciously small — likely a muted / empty recording
        logger.warning("Audio too short (%d bytes) — returning empty transcript.", len(audio_bytes))
        return {"transcript": "", "confidence": 0.0}

    webm_tmp = None
    wav_tmp  = None
    try:
        # 1. Write incoming bytes to a temp .webm file
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as f:
            f.write(audio_bytes)
            webm_tmp = f.name

        # 2. Convert to WAV
        wav_fd, wav_tmp = tempfile.mkstemp(suffix=".wav")
        os.close(wav_fd)

        converted = _convert_to_wav(webm_tmp, wav_tmp)

        # Choose which file to feed Whisper
        input_file = wav_tmp if converted else webm_tmp

        # 3. Transcribe
        model = _get_model()
        logger.info("Transcribing %s …", input_file)
        result = model.transcribe(
            input_file,
            fp16=False,          # CPU safe
            language=None,       # auto-detect language
            task="transcribe",
        )

        transcript = result.get("text", "").strip()
        logger.info("Transcript (%d chars): %s", len(transcript), transcript[:80])

        return {
            "transcript":  transcript,
            "confidence":  0.95,
        }

    except Exception as exc:
        logger.exception("Transcription error: %s", exc)
        raise RuntimeError(f"Transcription failed: {exc}") from exc

    finally:
        # Clean up temp files
        for path in (webm_tmp, wav_tmp):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
