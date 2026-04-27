"""
MIIC-Sec — Binary CNN Liveness Detector
Detects real faces vs spoofed/printed images.
Architecture: 3x Conv2D blocks → Dense → Sigmoid

All TensorFlow imports are lazy to allow the app to start
without heavy ML dependencies installed.
"""

import os
import numpy as np


def build_liveness_model():
    """
    Build a binary CNN for liveness detection.

    Architecture:
      Input: 96x96x3 RGB
      Conv2D(32) → MaxPool → Conv2D(64) → MaxPool →
      Conv2D(128) → MaxPool → Flatten → Dense(128) →
      Dropout(0.5) → Dense(1, sigmoid)

    Returns:
        Compiled Keras model.
    """
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
    import tensorflow as tf
    from tensorflow import keras
    from tensorflow.keras import layers

    model = keras.Sequential([
        layers.Input(shape=(96, 96, 3)),

        # Block 1
        layers.Conv2D(32, (3, 3), activation="relu"),
        layers.MaxPooling2D((2, 2)),

        # Block 2
        layers.Conv2D(64, (3, 3), activation="relu"),
        layers.MaxPooling2D((2, 2)),

        # Block 3
        layers.Conv2D(128, (3, 3), activation="relu"),
        layers.MaxPooling2D((2, 2)),

        # Classifier head
        layers.Flatten(),
        layers.Dense(128, activation="relu"),
        layers.Dropout(0.5),
        layers.Dense(1, activation="sigmoid"),
    ])

    model.compile(
        optimizer="adam",
        loss="binary_crossentropy",
        metrics=["accuracy"],
    )

    return model


def load_liveness_model(model_path: str = "models/liveness_model.h5"):
    """
    Load a saved liveness model from disk.

    If the model file is not found, builds a fresh untrained model,
    saves it, and returns it with a warning.

    Args:
        model_path: Path to the .h5 model file.

    Returns:
        Loaded (or freshly built) Keras model.
    """
    os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

    try:
        from tensorflow import keras
    except ImportError:
        print("⚠️  TensorFlow not installed — liveness detection disabled")
        return None

    if os.path.exists(model_path):
        model = keras.models.load_model(model_path)
        print(f"✅ Liveness model loaded from {model_path}")
        return model

    # Model not found — build and save a fresh untrained model
    print("⚠️  WARNING: Using untrained liveness model.")
    print("   Train with real data for production use.")

    os.makedirs(os.path.dirname(model_path) if os.path.dirname(model_path) else ".", exist_ok=True)
    model = build_liveness_model()
    model.save(model_path)
    print(f"   Saved fresh model to {model_path}")

    return model


def detect_liveness(frame: np.ndarray, model=None) -> dict:
    """
    Run liveness detection on a single frame.

    Args:
        frame: BGR or RGB image as numpy array (any size).
        model: Pre-loaded Keras model. If None, loads default.

    Returns:
        { "is_live": bool, "confidence": float }
        Threshold: confidence > 0.5 = live
    """
    if model is None:
        model = load_liveness_model()

    # If model couldn't be loaded (TF not installed), pass through
    if model is None:
        print("⚠️  Liveness check skipped — no model available")
        return {"is_live": True, "confidence": 1.0}

    # ── Preprocess ───────────────────────────────────────────────
    import cv2
    img = cv2.resize(frame, (96, 96))

    # Normalize pixel values to [0, 1]
    img = img.astype(np.float32) / 255.0

    # Add batch dimension: (1, 96, 96, 3)
    img = np.expand_dims(img, axis=0)

    # ── Inference ────────────────────────────────────────────────
    prediction = model.predict(img, verbose=0)
    confidence = float(prediction[0][0])

    return {
        "is_live": confidence > 0.5,
        "confidence": round(confidence, 4),
    }
