"""
MIIC-Sec — Speaker Diarization (Tier 4)
Detects multiple speakers in audio chunks using pyannote.audio.

REQUIRES: HuggingFace token accepted for pyannote/speaker-diarization-3.1
  1. Visit https://hf.co/pyannote/speaker-diarization-3.1 and accept terms.
  2. Generate a token at https://huggingface.co/settings/tokens
  3. Export it:  export HF_TOKEN="hf_..."

If the token is absent or the model cannot be loaded, the module degrades
gracefully — all calls become no-ops.
"""

import io
import logging
import os
from typing import Any, Dict, List, Optional

import numpy as np

from crypto.audit_log import log_event

logger = logging.getLogger(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────

MULTI_SPEAKER_THRESHOLD        = 2   # terminate after this many consecutive chunks
DIARIZATION_MODEL_ID           = "pyannote/speaker-diarization-3.1"
AUDIO_CHUNK_DURATION_SECONDS   = 30


# ─── Pipeline Loader ──────────────────────────────────────────────────────────

def load_diarization_pipeline() -> Optional[Any]:
    """
    Attempt to load the pyannote speaker-diarization pipeline.

    Reads HF_TOKEN from the environment.  Returns None (with a warning)
    if the token is absent, pyannote is not installed, or the model is
    otherwise unavailable.  Never raises.

    Returns:
        Loaded pyannote Pipeline, or None.
    """
    hf_token = os.environ.get("HF_TOKEN", "").strip()

    if not hf_token:
        print(
            "WARNING: Speaker diarization disabled. "
            "Set HF_TOKEN env variable to enable."
        )
        logger.warning("HF_TOKEN not set — speaker diarization disabled")
        return None

    try:
        from pyannote.audio import Pipeline  # type: ignore

        pipeline = Pipeline.from_pretrained(
            DIARIZATION_MODEL_ID,
            use_auth_token=hf_token,
        )

        # Move to CPU explicitly (safe for M1 MPS or CUDA-less environments)
        import torch  # type: ignore
        pipeline = pipeline.to(torch.device("cpu"))

        logger.info("pyannote speaker-diarization-3.1 loaded successfully")
        return pipeline

    except ImportError:
        print(
            "WARNING: Speaker diarization disabled. "
            "Set HF_TOKEN env variable to enable."
        )
        logger.warning("pyannote.audio not installed — diarization disabled")
        return None

    except Exception as exc:
        print(
            "WARNING: Speaker diarization disabled. "
            "Set HF_TOKEN env variable to enable."
        )
        logger.warning("Could not load diarization pipeline: %s", exc)
        return None


# ─── Audio Inference ──────────────────────────────────────────────────────────

def count_speakers_in_audio(
    audio_array: np.ndarray,
    sample_rate: int,
    pipeline: Any,
) -> Dict[str, Any]:
    """
    Run pyannote diarization on a mono float32 audio chunk and count
    unique speakers.

    Internally wraps the numpy array in a dict that pyannote's pipeline
    accepts directly (no temp-file needed as of pyannote.audio ≥3.0).

    Args:
        audio_array:  Mono float32 numpy array (up to ~30 s).
        sample_rate:  Sample rate in Hz (e.g. 16000).
        pipeline:     Loaded pyannote Pipeline instance.

    Returns:
        {
            "speaker_count": int,
            "segments":      list[dict]   ← { speaker, start, end }
        }
    """
    segments: List[Dict[str, Any]] = []

    try:
        import torch  # type: ignore

        # pyannote ≥3 accepts a dict with "waveform" and "sample_rate"
        waveform = torch.from_numpy(audio_array).unsqueeze(0)   # (1, T)

        diarization = pipeline({"waveform": waveform, "sample_rate": sample_rate})

        speakers = set()
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speakers.add(speaker)
            segments.append({
                "speaker": speaker,
                "start":   round(turn.start, 3),
                "end":     round(turn.end,   3),
            })

        return {
            "speaker_count": len(speakers),
            "segments":      segments,
        }

    except Exception as exc:
        logger.error("count_speakers_in_audio raised: %s", exc)
        return {"speaker_count": 0, "segments": []}


# ─── SpeakerDiarizer class ────────────────────────────────────────────────────

class SpeakerDiarizer:
    """
    Stateful per-session speaker diarization processor.

    If the pyannote pipeline could not be loaded, every call to
    process_audio_chunk() silently returns without effect.
    """

    def __init__(self) -> None:
        self.pipeline: Optional[Any] = load_diarization_pipeline()

        # { session_id: int }  — consecutive multi-speaker chunk count
        self.multi_speaker_count: Dict[str, int] = {}

    async def process_audio_chunk(
        self,
        session_id: str,
        audio_array: np.ndarray,
        sample_rate: int,
        db_session,
        ws_manager,
    ) -> None:
        """
        Analyse one audio chunk for the given session.

        Steps:
        1. If pipeline is None → return immediately (no crash).
        2. Run count_speakers_in_audio().
        3. If speaker_count > 1:
           a. Increment consecutive counter.
           b. Log MULTIPLE_SPEAKERS_DETECTED to audit log.
           c. Send MULTIPLE_SPEAKERS_ALERT via WebSocket.
           d. If consecutive count >= MULTI_SPEAKER_THRESHOLD → terminate session.
        4. Otherwise reset consecutive counter to 0.

        Args:
            session_id:   Interview session UUID.
            audio_array:  Mono float32 numpy array.
            sample_rate:  Sample rate in Hz.
            db_session:   Active SQLAlchemy session.
            ws_manager:   ConnectionManager singleton.
        """
        if self.pipeline is None:
            return   # Graceful no-op

        from verification.continuous_verifier import terminate_session
        from websocket.ws_manager import MULTIPLE_SPEAKERS_ALERT

        result        = count_speakers_in_audio(audio_array, sample_rate, self.pipeline)
        speaker_count = result["speaker_count"]
        segments      = result["segments"]

        logger.debug(
            "Diarization — session=%s speakers=%d segments=%d",
            session_id, speaker_count, len(segments),
        )

        if speaker_count > 1:
            self.multi_speaker_count[session_id] = (
                self.multi_speaker_count.get(session_id, 0) + 1
            )
            count = self.multi_speaker_count[session_id]

            # ── Audit ─────────────────────────────────────────────────────────
            try:
                log_event(
                    session_id=session_id,
                    event_type="MULTIPLE_SPEAKERS_DETECTED",
                    detail={
                        "speaker_count":      speaker_count,
                        "consecutive_count":  count,
                        "segments":           segments[:10],   # cap for DB size
                    },
                    db_session=db_session,
                )
            except Exception as exc:
                logger.error("audit log error in diarizer: %s", exc)

            # ── WebSocket alert ───────────────────────────────────────────────
            await ws_manager.broadcast_security_event(
                session_id,
                MULTIPLE_SPEAKERS_ALERT,
                {
                    "session_id":         session_id,
                    "speaker_count":      speaker_count,
                    "consecutive_count":  count,
                    "message": (
                        f"Multiple speakers detected ({speaker_count}). "
                        f"Consecutive chunks: {count}."
                    ),
                },
            )

            logger.warning(
                "MULTIPLE_SPEAKERS_DETECTED — session=%s count=%d consecutive=%d",
                session_id, speaker_count, count,
            )

            # ── Terminate after MULTI_SPEAKER_THRESHOLD consecutive hits ──────
            if count >= MULTI_SPEAKER_THRESHOLD:
                logger.error(
                    "Terminating session %s — %d consecutive multi-speaker chunks",
                    session_id, count,
                )
                await terminate_session(
                    session_id=session_id,
                    reason=f"Multiple speakers detected {count} consecutive times",
                    db_session=db_session,
                    ws_manager=ws_manager,
                )

        else:
            # Single speaker (or silence) — reset streak
            if self.multi_speaker_count.get(session_id, 0) > 0:
                logger.info(
                    "Speaker count normalised — resetting counter for session=%s",
                    session_id,
                )
            self.multi_speaker_count[session_id] = 0
