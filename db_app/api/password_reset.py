"""
Password reset endpoints.
Set in Northflank Environment:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, APP_URL
"""
import os, secrets, smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import bcrypt
from fastapi import APIRouter, Body, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db_app.database import get_db
from db_app.models.user import User
from db_app.models.password_reset_token import PasswordResetToken

router = APIRouter()
TOKEN_EXPIRY_MINUTES = 30


class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


def _send_reset_email(to_email: str, reset_url: str) -> None:
    smtp_host = os.environ.get("SMTP_HOST", "")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASSWORD", "")

    if not all([smtp_host, smtp_user, smtp_pass]):
        raise RuntimeError("SMTP not configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD.")

    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:480px;margin:0 auto;padding:32px;">
      <h2 style="color:#1a1a2e;">Reset your Accfino password</h2>
      <p style="color:#555;line-height:1.6;">
        Click the button below to reset your password. Link expires in {TOKEN_EXPIRY_MINUTES} minutes.
      </p>
      <div style="text-align:center;margin:32px 0;">
        <a href="{reset_url}" style="background:#FF6B35;color:#fff;padding:14px 32px;
           border-radius:8px;text-decoration:none;font-weight:600;">Reset Password</a>
      </div>
      <p style="color:#888;font-size:.85rem;">{reset_url}</p>
    </div>
    """
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Reset your Accfino password"
    msg["From"]    = smtp_user
    msg["To"]      = to_email
    msg.attach(MIMEText(f"Reset link: {reset_url}", "plain"))
    msg.attach(MIMEText(html, "html"))
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.ehlo(); s.starttls(); s.login(smtp_user, smtp_pass)
        s.sendmail(smtp_user, to_email, msg.as_string())


@router.post("/forgot-password")
def forgot_password(request: ForgotPasswordRequest = Body(...), db: Session = Depends(get_db)):
    email = request.email.strip().lower()
    user  = db.query(User).filter(User.email.ilike(email)).first()
    if user:
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used    == False,
        ).update({"used": True})
        db.flush()
        raw_token = secrets.token_urlsafe(48)
        db.add(PasswordResetToken(
            user_id=user.id, token=raw_token,
            expires_at=datetime.utcnow() + timedelta(minutes=TOKEN_EXPIRY_MINUTES),
            used=False,
        ))
        db.commit()
        app_url   = os.environ.get("APP_URL", "https://accfino.com").rstrip("/")
        reset_url = f"{app_url}/reset-password?token={raw_token}"
        try:
            _send_reset_email(user.email, reset_url)
        except Exception as e:
            print(f"[reset] Email send failed: {e}")
    return {"message": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
def reset_password(request: ResetPasswordRequest = Body(...), db: Session = Depends(get_db)):
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token == request.token).first()
    if not row or row.used:
        raise HTTPException(400, "Invalid or already-used reset link.")
    if datetime.utcnow() > row.expires_at:
        raise HTTPException(400, "Reset link expired. Please request a new one.")
    if len(request.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    user = db.query(User).filter(User.id == row.user_id).first()
    if not user:
        raise HTTPException(400, "User not found.")
    user.password = bcrypt.hashpw(request.new_password.encode(), bcrypt.gensalt()).decode()
    row.used = True
    db.commit()
    return {"message": "Password updated successfully."}


@router.get("/verify-reset-token")
def verify_reset_token(token: str, db: Session = Depends(get_db)):
    row = db.query(PasswordResetToken).filter(PasswordResetToken.token == token).first()
    if not row or row.used or datetime.utcnow() > row.expires_at:
        raise HTTPException(400, "Invalid or expired reset link.")
    user = db.query(User).filter(User.id == row.user_id).first()
    return {"valid": True, "email": user.email if user else ""}
