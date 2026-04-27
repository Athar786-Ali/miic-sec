"""
MIIC-Sec — Voice Authentication Module
wav2vec2-based voice embedding extraction, enrollment, and verification.
"""

import pickle
import numpy as np
import torch
from scipy.spatial.distance import cosine

from config import VOICE_SIMILARITY_THRESHOLD

# ─── Module-level cache ─────────────────────────────────────────
_voice_model = None
_voice_processor = None


def load_voice_model():
    """
    Load facebook/wav2vec2-base from HuggingFace.
    Caches locally after first download.

    Returns:
        (model, processor) tuple
    """
    global _voice_model, _voice_processor

    if _voice_model is not None and _voice_processor is not None:
        return _voice_model, _voice_processor

    from transformers import Wav2Vec2Model, Wav2Vec2Processor

    model_name = "facebook/wav2vec2-base"
    print(f"📦 Loading voice model: {model_name}")

    _voice_processor = Wav2Vec2Processor.from_pretrained(model_name)
    _voice_model = Wav2Vec2Model.from_pretrained(model_name)
    _voice_model.eval()

    print("✅ Voice model loaded")
    return _voice_model, _voice_processor


def extract_voice_embedding(
    audio_array: np.ndarray,
    sample_rate: int,
) -> np.ndarray:
    """
    Extract a voice embedding from audio using wav2vec2.

    Args:
        audio_array: 1-D numpy array of audio samples.
        sample_rate: Sample rate of the audio (Hz).

    Returns:
        1-D numpy embedding (mean-pooled hidden state).
    """
    model, processor = load_voice_model()

    # Resample to 16000 Hz if needed
    if sample_rate != 16000:
        import torchaudio

        audio_tensor = torch.tensor(audio_array, dtype=torch.float32).unsqueeze(0)
        resampler = torchaudio.transforms.Resample(
            orig_freq=sample_rate,
            new_freq=16000,
        )
        audio_tensor = resampler(audio_tensor)
        audio_array = audio_tensor.squeeze(0).numpy()
        sample_rate = 16000

    # Process through wav2vec2
    inputs = processor(
        audio_array,
        sampling_rate=sample_rate,
        return_tensors="pt",
        padding=True,
    )

    with torch.no_grad():
        outputs = model(**inputs)

    # Mean pool over time dimension → 1-D embedding
    hidden_states = outputs.last_hidden_state  # (1, T, 768)
    embedding = hidden_states.mean(dim=1).squeeze(0).numpy()  # (768,)

    return embedding.astype(np.float32)


def enroll_voice(
    candidate_id: str,
    audio_array: np.ndarray,
    sample_rate: int,
    db_session,
) -> dict:
    """
    Enroll a candidate's voice.

    Args:
        candidate_id: UUID of the candidate.
        audio_array: 1-D numpy array of audio.
        sample_rate: Sample rate in Hz.
        db_session: SQLAlchemy DB session.

    Returns:
        { "success": bool, "message": str }
    """
    from database import Candidate

    try:
        embedding = extract_voice_embedding(audio_array, sample_rate)
    except Exception as e:
        return {"success": False, "message": f"Voice embedding extraction failed: {e}"}

    candidate = db_session.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"success": False, "message": "Candidate not found"}

    candidate.voice_embedding = pickle.dumps(embedding)
    db_session.commit()

    return {"success": True, "message": "Voice enrolled successfully"}


def verify_voice(
    candidate_id: str,
    audio_array: np.ndarray,
    sample_rate: int,
    db_session,
) -> dict:
    """
    Verify a candidate's voice against their stored embedding.

    Args:
        candidate_id: UUID of the candidate.
        audio_array: 1-D numpy array of live audio.
        sample_rate: Sample rate in Hz.
        db_session: SQLAlchemy DB session.

    Returns:
        { "verified": bool, "similarity": float }
    """
    from database import Candidate

    candidate = db_session.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate or not candidate.voice_embedding:
        return {"verified": False, "similarity": 0.0}

    stored_embedding = pickle.loads(candidate.voice_embedding)

    try:
        live_embedding = extract_voice_embedding(audio_array, sample_rate)
    except Exception as e:
        print(f"⚠️  Voice verification failed: {e}")
        return {"verified": False, "similarity": 0.0}

    # Cosine similarity (1 - cosine distance)
    similarity = 1 - cosine(stored_embedding, live_embedding)
    similarity = round(float(similarity), 4)

    return {
        "verified": similarity >= VOICE_SIMILARITY_THRESHOLD,
        "similarity": similarity,
    }
