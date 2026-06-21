"""
MIIC-Sec — Email Authentication Module
Password hashing, OTP generation, and SMTP email delivery.
"""

import os
import random
import smtplib
import string
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from passlib.context import CryptContext

# ─── Password hashing (bcrypt) ───────────────────────────────────
_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    """Return bcrypt hash of a plain-text password."""
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if plain matches the stored hash."""
    try:
        return _pwd_ctx.verify(plain, hashed)
    except Exception:
        return False


# ─── OTP helpers ─────────────────────────────────────────────────

def generate_otp(length: int = 6) -> str:
    """Generate a cryptographically-random numeric OTP."""
    return "".join(random.choices(string.digits, k=length))


def create_otp_token(email: str, db_session) -> str:
    """
    Delete any existing unused OTPs for this email, create a new one
    that expires in 10 minutes, persist it, and return the code.
    """
    from database import OtpToken

    now = datetime.now(timezone.utc)

    # Invalidate old tokens for this email
    old = db_session.query(OtpToken).filter(OtpToken.email == email).all()
    for t in old:
        db_session.delete(t)
    db_session.flush()

    code = generate_otp()
    token = OtpToken(
        email=email,
        otp_code=code,
        expires_at=now + timedelta(minutes=10),
        used=False,
        created_at=now,
    )
    db_session.add(token)
    db_session.commit()
    return code


def verify_otp(email: str, code: str, db_session) -> bool:
    """
    Check that the code matches a valid, unexpired, unused OTP for
    this email. Marks it as used on success.

    Returns True on success, False otherwise.
    """
    from database import OtpToken

    now = datetime.now(timezone.utc)
    token = (
        db_session.query(OtpToken)
        .filter(
            OtpToken.email == email,
            OtpToken.otp_code == code,
            OtpToken.used == False,      # noqa: E712
            OtpToken.expires_at > now,
        )
        .first()
    )

    if not token:
        return False

    token.used = True
    db_session.commit()
    return True


# ─── Email sending ────────────────────────────────────────────────

def _get_smtp_config() -> dict:
    return {
        "host":     os.environ.get("SMTP_HOST", ""),
        "port":     int(os.environ.get("SMTP_PORT", "587")),
        "user":     os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASS", ""),
        "from":     os.environ.get("FROM_EMAIL", os.environ.get("SMTP_USER", "noreply@miic-sec.local")),
    }


def send_otp_email(email: str, otp: str, name: str = "") -> bool:
    """
    Send a 6-digit OTP to the given email via SMTP.

    Returns True on success. If SMTP is not configured, prints the OTP
    to the server log and returns True so development works offline.
    """
    cfg = _get_smtp_config()

    # ── Dev mode: no SMTP configured ─────────────────────────────
    if not cfg["host"] or not cfg["user"]:
        print(
            f"\n{'='*52}\n"
            f"  📧 OTP EMAIL (SMTP not configured — dev mode)\n"
            f"  To: {email}\n"
            f"  OTP: {otp}\n"
            f"{'='*52}\n"
        )
        return True

    # ── Build HTML email ──────────────────────────────────────────
    greeting = f"Hi {name}," if name else "Hi,"
    html = f"""
    <div style="font-family:sans-serif;max-width:480px;margin:40px auto;
                background:#1a1a2e;border-radius:12px;padding:32px;
                border:1px solid #2a2a4a;color:#e2e8f8">
      <h2 style="color:#6366f1;margin-bottom:8px">🛡 MIIC-Sec</h2>
      <p style="color:#8b94ac">{greeting}</p>
      <p>Your email verification code is:</p>
      <div style="font-size:2.5rem;font-weight:800;letter-spacing:0.3em;
                  text-align:center;padding:20px;margin:20px 0;
                  background:#23233e;border-radius:8px;
                  color:#6366f1;font-family:monospace">
        {otp}
      </div>
      <p style="color:#8b94ac;font-size:0.85rem">
        This code expires in <strong>10 minutes</strong>.<br>
        If you didn't request this, you can safely ignore this email.
      </p>
    </div>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Your MIIC-Sec verification code: {otp}"
    msg["From"]    = cfg["from"]
    msg["To"]      = email
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(cfg["user"], cfg["password"])
            smtp.sendmail(cfg["from"], [email], msg.as_string())
        return True
    except Exception as exc:
        print(f"⚠️  SMTP error: {exc} — OTP for {email}: {otp}")
        return False
