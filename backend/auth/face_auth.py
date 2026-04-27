"""
MIIC-Sec — Face Authentication Module
DeepFace-based face embedding extraction, enrollment, and verification.
"""

import pickle
import numpy as np
from scipy.spatial.distance import cosine

from config import FACE_SIMILARITY_THRESHOLD


def extract_face_embedding(frame: np.ndarray) -> np.ndarray | None:
    """
    Extract a 128-d face embedding from a frame using DeepFace + Facenet.

    Args:
        frame: BGR/RGB image as numpy array.

    Returns:
        128-d numpy embedding, or None if no face detected.
    """
    try:
        from deepface import DeepFace

        embeddings = DeepFace.represent(
            img_path=frame,
            model_name="Facenet",
            enforce_detection=True,
            detector_backend="opencv",
        )

        if embeddings and len(embeddings) > 0:
            return np.array(embeddings[0]["embedding"], dtype=np.float32)

        return None

    except Exception as e:
        print(f"⚠️  Face embedding extraction failed: {e}")
        return None


def enroll_face(
    candidate_id: str,
    frames: list[np.ndarray],
    db_session,
) -> dict:
    """
    Enroll a candidate's face using 5 frames.

    Extracts embeddings from each frame, averages them, and stores
    the result in the candidate's DB record.

    Args:
        candidate_id: UUID of the candidate.
        frames: List of 5 face images as numpy arrays.
        db_session: SQLAlchemy DB session.

    Returns:
        { "success": bool, "message": str }
    """
    from database import Candidate

    if len(frames) < 5:
        return {"success": False, "message": f"Need 5 frames, got {len(frames)}"}

    # Extract embeddings from each frame
    embeddings = []
    for i, frame in enumerate(frames):
        emb = extract_face_embedding(frame)
        if emb is not None:
            embeddings.append(emb)
        else:
            print(f"   ⚠️  No face detected in frame {i + 1}")

    if len(embeddings) == 0:
        return {"success": False, "message": "No faces detected in any frame"}

    if len(embeddings) < 3:
        return {
            "success": False,
            "message": f"Only {len(embeddings)}/5 frames had detectable faces. Need at least 3.",
        }

    # Average all embeddings
    avg_embedding = np.mean(embeddings, axis=0).astype(np.float32)

    # Serialize and store
    candidate = db_session.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"success": False, "message": "Candidate not found"}

    candidate.face_embedding = pickle.dumps(avg_embedding)
    db_session.commit()

    return {
        "success": True,
        "message": f"Face enrolled successfully ({len(embeddings)}/5 frames used)",
    }


def verify_face(
    candidate_id: str,
    frame: np.ndarray,
    db_session,
) -> dict:
    """
    Verify a candidate's face against their stored embedding.

    Args:
        candidate_id: UUID of the candidate.
        frame: Live face image as numpy array.
        db_session: SQLAlchemy DB session.

    Returns:
        { "verified": bool, "similarity": float }
    """
    from database import Candidate

    # Load stored embedding
    candidate = db_session.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate or not candidate.face_embedding:
        return {"verified": False, "similarity": 0.0}

    stored_embedding = pickle.loads(candidate.face_embedding)

    # Extract live embedding
    live_embedding = extract_face_embedding(frame)
    if live_embedding is None:
        return {"verified": False, "similarity": 0.0}

    # Compute cosine similarity (1 - cosine distance)
    similarity = 1 - cosine(stored_embedding, live_embedding)
    similarity = round(float(similarity), 4)

    return {
        "verified": similarity >= FACE_SIMILARITY_THRESHOLD,
        "similarity": similarity,
    }
