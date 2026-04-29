"""
MIIC-Sec — Proxy / Intruder Detection (Tier 4)
Uses YOLOv8n (lightest Ultralytics model) to count persons in each
video frame.  Operates every 10 frames for M1 performance.

If ≥ 2 persons are detected consecutively 3+ times the session is
terminated automatically.
"""

import logging
from typing import Any, Dict, List

import numpy as np

from crypto.audit_log import log_event

logger = logging.getLogger(__name__)

# ─── YOLO class index for "person" ───────────────────────────────────────────
PERSON_CLASS_ID = 0

# ─── How many consecutive multi-person detections trigger termination ─────────
CONSECUTIVE_THRESHOLD = 3

# ─── Only process every N-th frame (performance) ─────────────────────────────
FRAME_SKIP = 10


# ─── Module-level model loader ────────────────────────────────────────────────

def load_yolo_model() -> Any:
    """
    Load the YOLOv8n model from Ultralytics.

    The first call downloads the ~6 MB `yolov8n.pt` weights automatically
    and caches them under ~/.cache/ultralytics (or YOLO's default cache dir).

    Returns:
        Loaded YOLO model instance.

    Raises:
        ImportError: If ultralytics is not installed.
        RuntimeError: If the model cannot be loaded.
    """
    try:
        from ultralytics import YOLO  # type: ignore
    except ImportError as exc:
        raise ImportError(
            "ultralytics is not installed. "
            "Run: pip install ultralytics"
        ) from exc

    model = YOLO("yolov8n.pt")
    logger.info("YOLOv8n model loaded successfully")
    return model


def count_persons_in_frame(frame: np.ndarray, model: Any) -> Dict[str, Any]:
    """
    Run YOLO inference on a single BGR frame and count detected persons.

    Only detections with class_id == 0 ("person") are counted.

    Args:
        frame: BGR image as numpy array (H x W x 3).
        model: Loaded YOLO model instance.

    Returns:
        {
            "person_count":       int,
            "confidence_scores":  list[float]
        }
    """
    try:
        results = model(frame, verbose=False)   # suppress per-frame console output
    except Exception as exc:
        logger.error("YOLO inference failed: %s", exc)
        return {"person_count": 0, "confidence_scores": []}

    confidence_scores: List[float] = []

    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue

        for cls, conf in zip(boxes.cls.tolist(), boxes.conf.tolist()):
            if int(cls) == PERSON_CLASS_ID:
                confidence_scores.append(round(float(conf), 4))

    return {
        "person_count":      len(confidence_scores),
        "confidence_scores": confidence_scores,
    }


# ─── ProxyDetector class ──────────────────────────────────────────────────────

class ProxyDetector:
    """
    Stateful per-session proxy / intruder detector.

    Keeps a per-session frame counter (only processes every FRAME_SKIP-th
    frame) and a consecutive-multi-person counter.  Three consecutive
    detections of >1 person trigger session termination.
    """

    def __init__(self) -> None:
        self.model = load_yolo_model()

        # { session_id: int }
        self.consecutive_multi_person_count: Dict[str, int] = {}
        self.frame_counter:                  Dict[str, int] = {}

    async def process_frame(
        self,
        session_id: str,
        frame: np.ndarray,
        db_session,
        ws_manager,
        audit_logger=None,       # kept for API compatibility; use crypto.audit_log directly
    ) -> None:
        """
        Process one video frame for the given session.

        Steps:
        1. Increment the per-session frame counter.
        2. Skip if this is not the FRAME_SKIP-th frame.
        3. Run YOLO person detection.
        4. If person_count > 1:
           a. Increment consecutive counter.
           b. Log MULTIPLE_PERSONS_DETECTED to audit log.
           c. Send MULTIPLE_PERSONS_ALERT via WebSocket.
           d. If consecutive count >= CONSECUTIVE_THRESHOLD → terminate session.
        5. Otherwise reset consecutive counter.

        Args:
            session_id:    Interview session UUID.
            frame:         BGR image as numpy array.
            db_session:    Active SQLAlchemy session.
            ws_manager:    ConnectionManager singleton.
            audit_logger:  (ignored; kept for interface compatibility).
        """
        from verification.continuous_verifier import terminate_session
        from websocket.ws_manager import MULTIPLE_PERSONS_ALERT, _build_message

        # ── Frame throttling ─────────────────────────────────────────────────
        self.frame_counter[session_id] = self.frame_counter.get(session_id, 0) + 1

        if self.frame_counter[session_id] % FRAME_SKIP != 0:
            return   # skip this frame

        # ── YOLO inference ───────────────────────────────────────────────────
        detection = count_persons_in_frame(frame, self.model)
        person_count      = detection["person_count"]
        confidence_scores = detection["confidence_scores"]

        logger.debug(
            "YOLO — session=%s frame=%d persons=%d",
            session_id, self.frame_counter[session_id], person_count,
        )

        if person_count > 1:
            # ── Multiple persons detected ────────────────────────────────────
            self.consecutive_multi_person_count[session_id] = (
                self.consecutive_multi_person_count.get(session_id, 0) + 1
            )
            count = self.consecutive_multi_person_count[session_id]

            # Audit
            try:
                log_event(
                    session_id=session_id,
                    event_type="MULTIPLE_PERSONS_DETECTED",
                    detail={
                        "person_count":       person_count,
                        "confidence_scores":  confidence_scores,
                        "consecutive_count":  count,
                    },
                    db_session=db_session,
                )
            except Exception as exc:
                logger.error("audit log error in proxy_detector: %s", exc)

            # WebSocket alert
            alert_msg = _build_message(
                MULTIPLE_PERSONS_ALERT,
                {
                    "session_id":          session_id,
                    "person_count":        person_count,
                    "consecutive_count":   count,
                    "confidence_scores":   confidence_scores,
                    "message":             (
                        f"Multiple persons detected ({person_count}). "
                        f"Consecutive detections: {count}."
                    ),
                },
            )
            await ws_manager.broadcast_security_event(
                session_id, MULTIPLE_PERSONS_ALERT,
                alert_msg["data"],
            )

            logger.warning(
                "MULTIPLE_PERSONS_DETECTED — session=%s count=%d consecutive=%d",
                session_id, person_count, count,
            )

            # Terminate after CONSECUTIVE_THRESHOLD consecutive detections
            if count >= CONSECUTIVE_THRESHOLD:
                logger.error(
                    "Terminating session %s — %d consecutive multi-person detections",
                    session_id, count,
                )
                await terminate_session(
                    session_id=session_id,
                    reason=f"Multiple persons detected {count} consecutive times",
                    db_session=db_session,
                    ws_manager=ws_manager,
                )

        else:
            # ── Single person (or no person) → reset streak ──────────────────
            if self.consecutive_multi_person_count.get(session_id, 0) > 0:
                logger.info(
                    "Person count normalised — resetting consecutive counter for session=%s",
                    session_id,
                )
            self.consecutive_multi_person_count[session_id] = 0
