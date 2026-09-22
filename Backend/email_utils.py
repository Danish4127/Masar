"""Email sending for Masar (OTP codes).

Providers, selected with EMAIL_PROVIDER:
  * "resend" - Resend HTTP API (RESEND_API_KEY, RESEND_FROM)
  * "smtp"   - standard SMTP (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM)

Development mode: when no provider is configured, or EMAIL_DEV_CONSOLE=true,
the code is printed to the server console instead. In production keep
EMAIL_DEV_CONSOLE unset/false so a failed send is reported as a failure and
codes are never written to logs.
"""
import logging
import os
import smtplib
import ssl
from email.mime.text import MIMEText

import requests

log = logging.getLogger("masar.email")

def _truthy(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}

def _send_via_resend(to_email: str, subject: str, body: str) -> bool:
    api_key = os.getenv("RESEND_API_KEY")
    from_email = os.getenv("RESEND_FROM", "Masar <onboarding@resend.dev>")
    if not api_key:
        log.error("RESEND_API_KEY is not set")
        return False
    try:
        response = requests.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"from": from_email, "to": [to_email], "subject": subject, "text": body},
            timeout=10,
        )
        if response.status_code >= 300:
                                                                                                                   
            log.error("Resend rejected the email (%s): %s", response.status_code, response.text[:300])
            return False
        return True
    except Exception as exc:
        log.error("Resend send failed: %s", exc)
        return False

def _send_via_smtp(to_email: str, subject: str, body: str) -> bool:
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASS")
    from_email = os.getenv("SMTP_FROM") or user or "no-reply@masar.app"
    if not host or not user or not password:
        log.error("SMTP_HOST / SMTP_USER / SMTP_PASS are not fully set")
        return False
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=10, context=context) as server:
                server.login(user, password)
                server.sendmail(from_email, [to_email], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=10) as server:
                server.starttls(context=context)
                server.login(user, password)
                server.sendmail(from_email, [to_email], msg.as_string())
        return True
    except Exception as exc:
        log.error("SMTP send failed: %s", exc)
        return False

def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email. Returns True only if it was really sent (or printed in dev-console mode)."""
    provider = os.getenv("EMAIL_PROVIDER", "").strip().lower()
    sent = False
    if provider == "resend":
        sent = _send_via_resend(to_email, subject, body)
    elif provider == "smtp":
        sent = _send_via_smtp(to_email, subject, body)
    if sent:
        return True

    dev_console = _truthy("EMAIL_DEV_CONSOLE") or (provider not in ("resend", "smtp") and os.getenv("EMAIL_DEV_CONSOLE", "").strip().lower() not in {"0", "false", "no", "off"})
    if dev_console:
        print(f"[email_utils] DEV MODE - email NOT sent. To: {to_email}\nSubject: {subject}\n{body}\n")
        return True
    log.error("Email to %s could not be delivered.", to_email)
    return False

def send_otp_email(to_email: str, otp_code: str, purpose: str = "reset") -> bool:
    """purpose: 'signup' | 'login' | 'reset' - controls subject/body wording."""
    copy = {
        "signup": ("Masar - Verify Your Account", "Your Masar account verification code is:"),
        "login": ("Masar - Login Verification Code", "Your Masar login verification code is:"),
        "reset": ("Masar - Password Reset Code", "Your Masar password reset code is:"),
    }.get(purpose, ("Masar - Verification Code", "Your Masar verification code is:"))
    body = (
        f"{copy[1]} {otp_code}\n\n"
        "This code expires in 10 minutes. If you did not request this, you can safely ignore this email."
    )
    return send_email(to_email, copy[0], body)
