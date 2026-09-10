"""
Email sending utility for Masar.

Supports two providers, selected via the EMAIL_PROVIDER env var:
  - "resend": uses the Resend HTTP API (requires RESEND_API_KEY, RESEND_FROM)
  - "smtp":   uses standard SMTP (requires SMTP_HOST, SMTP_PORT, SMTP_USER,
              SMTP_PASS, SMTP_FROM) -- works with UAEU mail servers or Gmail
              app-passwords.

If neither is configured, emails are printed to the console instead of being
sent (safe default for local development so the app never crashes because an
email provider isn't set up yet).
"""

import os
import smtplib
import ssl
from email.mime.text import MIMEText

import requests


def _send_via_resend(to_email: str, subject: str, body: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM", "Masar <no-reply@masar.app>")
    if not api_key:
        return False
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "from": from_email,
                "to": [to_email],
                "subject": subject,
                "text": body,
            },
            timeout=10,
        )
        return response.status_code < 300
    except Exception as exc:                    
        print(f"[email_utils] Resend send failed: {exc}")
        return False


def _send_via_smtp(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    from_email = os.getenv("SMTP_FROM", user or "no-reply@masar.app")
    if not host or not user or not password:
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        context = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls(context=context)
            server.login(user, password)
            server.sendmail(from_email, [to_email], msg.as_string())
        return True
    except Exception as exc:                    
        print(f"[email_utils] SMTP send failed: {exc}")
        return False


def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email using the configured provider. Falls back to console
    logging in development so the request never fails because email isn't
    configured yet."""
    provider = os.getenv("EMAIL_PROVIDER", "").lower()

    if provider == "resend":
        if _send_via_resend(to_email, subject, body):
            return True
    elif provider == "smtp":
        if _send_via_smtp(to_email, subject, body):
            return True

                                                                            
                                                   
    print(f"[email_utils] (DEV MODE - not actually sent) To: {to_email}\nSubject: {subject}\n{body}")
    return True


def send_otp_email(to_email: str, otp_code: str) -> bool:
    subject = "Masar - Password Reset Code"
    body = (
        f"Your Masar password reset code is: {otp_code}\n\n"
        "This code expires in 10 minutes. If you did not request this, "
        "you can safely ignore this email."
    )
    return send_email(to_email, subject, body)
