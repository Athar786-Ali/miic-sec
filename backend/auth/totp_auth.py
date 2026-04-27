"""
MIIC-Sec — TOTP Authentication Module
Time-based One-Time Password generation, QR codes, and verification.
"""

import base64
import io

import pyotp
import qrcode


def generate_totp_secret() -> str:
    """
    Generate a random Base32 TOTP secret.

    Returns:
        Base32 encoded secret string.
    """
    return pyotp.random_base32()


def get_totp_qr_code(secret: str, candidate_email: str) -> str:
    """
    Generate a QR code image for TOTP enrollment.

    Args:
        secret: Base32 TOTP secret.
        candidate_email: Email to display in authenticator app.

    Returns:
        Base64-encoded PNG string of the QR code.
    """
    totp = pyotp.totp.TOTP(secret)
    provisioning_uri = totp.provisioning_uri(
        name=candidate_email,
        issuer_name="MIIC-Sec",
    )

    # Generate QR code image
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    # Convert to base64 PNG
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    b64_string = base64.b64encode(buffer.getvalue()).decode("utf-8")

    return b64_string


def verify_totp(secret: str, code: str) -> dict:
    """
    Verify a TOTP code against the secret.

    Args:
        secret: Base32 TOTP secret.
        code: 6-digit TOTP code from authenticator app.

    Returns:
        { "verified": bool }
    """
    totp = pyotp.TOTP(secret)
    is_valid = totp.verify(code, valid_window=1)

    return {"verified": bool(is_valid)}


def enroll_totp(candidate_id: str, db_session) -> dict:
    """
    Enroll TOTP for a candidate.

    Generates a secret, stores it in the DB, and returns
    the secret + QR code for the authenticator app.

    Args:
        candidate_id: UUID of the candidate.
        db_session: SQLAlchemy DB session.

    Returns:
        { "secret": str, "qr_code_base64": str }
    """
    from database import Candidate

    candidate = db_session.query(Candidate).filter(Candidate.id == candidate_id).first()
    if not candidate:
        return {"secret": None, "qr_code_base64": None}

    # Generate and store secret
    secret = generate_totp_secret()
    candidate.totp_secret = secret
    db_session.commit()

    # Generate QR code
    qr_b64 = get_totp_qr_code(secret, candidate.email)

    return {
        "secret": secret,
        "qr_code_base64": qr_b64,
    }
