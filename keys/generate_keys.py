"""
RSA-2048 Keypair Generator for MIIC-Sec

- Private key: AES-256 encrypted with password "miicsec_secret"
- Public key: PEM format
- Skips generation if keys already exist
"""

import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

# Resolve paths relative to this script's directory
KEYS_DIR = os.path.dirname(os.path.abspath(__file__))
PRIVATE_KEY_PATH = os.path.join(KEYS_DIR, "private_key.pem")
PUBLIC_KEY_PATH = os.path.join(KEYS_DIR, "public_key.pem")
KEY_PASSWORD = b"miicsec_secret"


def generate_keys():
    """Generate RSA-2048 keypair and save to PEM files."""

    # ── Skip if both keys already exist ──────────────────────────
    if os.path.exists(PRIVATE_KEY_PATH) and os.path.exists(PUBLIC_KEY_PATH):
        print("🔑 Keys already exist — skipping generation.")
        print(f"   Private: {PRIVATE_KEY_PATH}")
        print(f"   Public:  {PUBLIC_KEY_PATH}")
        return

    # ── Generate RSA-2048 private key ────────────────────────────
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # ── Serialize private key (AES-256 encrypted) ────────────────
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(KEY_PASSWORD),
    )

    with open(PRIVATE_KEY_PATH, "wb") as f:
        f.write(private_pem)

    # ── Serialize public key ─────────────────────────────────────
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    with open(PUBLIC_KEY_PATH, "wb") as f:
        f.write(public_pem)

    # ── Confirmation ─────────────────────────────────────────────
    print("✅ RSA-2048 keypair generated successfully!")
    print(f"   Private key (AES-256 encrypted): {PRIVATE_KEY_PATH}")
    print(f"   Public key:                      {PUBLIC_KEY_PATH}")


if __name__ == "__main__":
    generate_keys()
