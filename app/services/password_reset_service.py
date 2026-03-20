"""Service layer for password reset flows."""

from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import hashlib
import logging
import secrets
import smtplib

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.security import hash_password
from app.models.password_reset_model import PasswordResetToken
from app.models.user_model import User

log = logging.getLogger(__name__)

RESET_TOKEN_BYTES = 32
RESET_TOKEN_EXP_MINUTES = 15


def _hash_token(raw_token: str) -> str:
    """Return SHA256 hash hex digest for the token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def generate_reset_token() -> str:
    """Generate a secure random token for password reset."""
    return secrets.token_urlsafe(RESET_TOKEN_BYTES)


def create_reset_token(db: Session, user: User) -> str:
    """
    Create and persist a reset token for the given user.

    Returns the raw token (not hashed). Only used internally; never exposed via API.
    """
    raw_token = generate_reset_token()
    token_hash = _hash_token(raw_token)

    now_utc = datetime.now(timezone.utc)
    expires_at = now_utc + timedelta(minutes=RESET_TOKEN_EXP_MINUTES)

    token = PasswordResetToken(
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    return raw_token


def _build_reset_link(raw_token: str) -> str:
    """Build the password reset URL with token (token never logged in production)."""
    base = get_settings().RESET_LINK_BASE_URL.rstrip("/")
    return f"{base}?token={raw_token}"


def _send_reset_email(to_email: str, reset_link: str) -> None:
    """Send password reset email via SMTP. Fails silently with a warning log."""
    settings = get_settings()

    if not settings.SMTP_HOST or not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        log.warning("SMTP not configured — skipping password reset email delivery")
        return

    from_email = settings.SMTP_FROM_EMAIL or settings.SMTP_USERNAME

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Password Reset Request — CIBIL Bureau"
    msg["From"] = from_email
    msg["To"] = to_email

    text_body = (
        "You requested a password reset for your CIBIL Bureau account.\n\n"
        f"Click the link below to reset your password:\n{reset_link}\n\n"
        f"This link expires in {RESET_TOKEN_EXP_MINUTES} minutes.\n"
        "If you did not request this, ignore this email."
    )
    html_body = (
        "<p>You requested a password reset for your <strong>CIBIL Bureau</strong> account.</p>"
        f'<p><a href="{reset_link}">Click here to reset your password</a></p>'
        f"<p>This link expires in {RESET_TOKEN_EXP_MINUTES} minutes.</p>"
        "<p>If you did not request this, ignore this email.</p>"
    )

    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.sendmail(from_email, to_email, msg.as_string())
        log.info("Password reset email sent", extra={"to": to_email})
    except Exception:
        log.exception("Failed to send password reset email", extra={"to": to_email})


def request_password_reset(db: Session, email: str) -> str | None:
    """
    If a user exists for the email, create a reset token and deliver the reset link.

    In dev mode (ENV=dev) the reset link is returned so it can be shown in the
    API response for demo purposes. In production (ENV=prod) the link is sent
    via SMTP and never exposed in the response.

    Returns the reset link in dev mode, None otherwise.
    """
    user = db.query(User).filter(User.email == email).first()
    if not user:
        return None

    raw_token = create_reset_token(db, user)
    link = _build_reset_link(raw_token)
    settings = get_settings()

    if settings.ENV.value == "dev":
        log.info("[DEV] Password reset link generated (demo mode)")
        return link

    _send_reset_email(user.email, link)
    return None


def reset_password_with_token(
    db: Session,
    token: str,
    new_password: str,
) -> None:
    """Validate reset token and update user password. Only unused tokens are valid."""
    token_hash = _hash_token(token)

    reset_token = (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.token_hash == token_hash,
            PasswordResetToken.used.is_(False),
        )
        .first()
    )
    if not reset_token:
        raise ValueError("Invalid or used token")

    now_utc = datetime.now(timezone.utc)
    if reset_token.expires_at < now_utc:
        raise ValueError("Token has expired")

    user = db.query(User).filter(User.id == reset_token.user_id).first()
    if not user:
        raise ValueError("Associated user not found")

    user.hashed_password = hash_password(new_password)
    reset_token.used = True

    # Invalidate all other unused tokens for this user
    (
        db.query(PasswordResetToken)
        .filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False),
        )
        .update({PasswordResetToken.used: True}, synchronize_session="fetch")
    )

    db.add(user)
    db.add(reset_token)
    db.commit()

