"""
MIIC-Sec — Face Authentication Module
facenet-pytorch (InceptionResnetV1 + MTCNN) based face embedding.
Pure PyTorch — works on Python 3.13 without TensorFlow.
"""

import pickle
import numpy as np
import torch
from scipy.spatial.distance import cosine

from config import FACE_SIMILARITY_THRESHOLD

# ─── Module-level model cache ────────────────────────────────────
_mtcnn = None
_resnet = None


def _load_models():
    """Lazy-load MTCNN detector + InceptionResnetV1 encoder."""
    global _mtcnn, _resnet
    if _mtcnn is not None and _resnet is not None:
        return _mtcnn, _resnet

    from facenet_pytorch import MTCNN, InceptionResnetV1

    print("📦 Loading face models (facenet-pytorch / VGGFace2)…")
    _mtcnn = MTCNN(
        image_size=160,
        margin=20,
        keep_all=False,
        min_face_size=20,
        device="cpu",
        post_process=True,   # normalise to [-1, 1]
    )
    _resnet = InceptionResnetV1(pretrained="vggface2").eval()
    print("✅ Face models loaded")
    return _mtcnn, _resnet


def extract_face_embedding(frame: np.ndarray) -> np.ndarray | None:
    """
    Extract a 512-d face embedding from a frame using facenet-pytorch.

    Args:
        frame: BGR or RGB image as numpy array (any size).

    Returns:
        512-d numpy embedding (float32), or None if no face detected.
    """
    try:
        mtcnn, resnet = _load_models()

        import cv2
        # Convert BGR → RGB (PIL-like array expected by MTCNN)
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) if frame.shape[2] == 3 else frame

        # Detect and align face → (1, 3, 160, 160) tensor or None
        face_tensor = mtcnn(rgb)   # returns tensor or None

        if face_tensor is None:
            print("   ⚠️  No face detected in frame")
            return None

        # Add batch dim if needed
        if face_tensor.dim() == 3:
            face_tensor = face_tensor.unsqueeze(0)

        with torch.no_grad():
            embedding = resnet(face_tensor)   # (1, 512)

        return embedding.squeeze(0).numpy().astype(np.float32)

    except Exception as e:
        print(f"⚠️  Face embedding extraction failed: {e}")
        return None


def enroll_face(
    candidate_id: str,
    frames: list[np.ndarray],
    db_session,
) -> dict:
    """
    Enroll a candidate's face using up to 5 frames.

    Extracts embeddings from each frame, averages them, and stores
    the result in the candidate's DB record.

    Args:
        candidate_id: UUID of the candidate.
        frames: List of face images as numpy arrays.
        db_session: SQLAlchemy DB session.

    Returns:
        { "success": bool, "message": str }
    """
    from database import Candidate

    if len(frames) < 5:
        return {"success": False, "message": f"Need 5 frames, got {len(frames)}"}

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

    avg_embedding = np.mean(embeddings, axis=0).astype(np.float32)

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

    candidate = db_session.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate or not candidate.face_embedding:
        return {"verified": False, "similarity": 0.0}

    stored_embedding = pickle.loads(candidate.face_embedding)

    live_embedding = extract_face_embedding(frame)
    if live_embedding is None:
        return {"verified": False, "similarity": 0.0}

    # Cosine similarity (1 - cosine distance)
    similarity = 1 - cosine(stored_embedding, live_embedding)
    similarity = round(float(similarity), 4)

    return {
        "verified": similarity >= FACE_SIMILARITY_THRESHOLD,
        "similarity": similarity,
    }
