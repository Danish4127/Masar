"""Authentication helpers: password hashing, signed tokens, OTP hashing and
a small in-memory rate limiter. Kept separate from main.py (NFR 4.3, 6.3)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")                                              

log = logging.getLogger("masar.security")

_PLACEHOLDER_SECRETS = {"change-this-secret-in-production"}

def _load_secret() -> bytes:
    value = os.getenv("AUTH_SECRET", "").strip()
    if value and value not in _PLACEHOLDER_SECRETS and not value.startswith("replace-with") and len(value) >= 16:
        return value.encode("utf-8")
    database_url = os.getenv("DATABASE_URL", "")
    if database_url:
        log.warning(
            "AUTH_SECRET is missing or too weak - deriving a private signing key from DATABASE_URL. "
            "Set AUTH_SECRET to a long random value (python -c \"import secrets;print(secrets.token_urlsafe(48))\")."
        )
        return hashlib.sha256(b"masar-auth-fallback|" + database_url.encode("utf-8")).digest()
    log.warning("AUTH_SECRET is not set - using a random key; sessions will not survive a restart.")
    return secrets.token_bytes(32)

AUTH_SECRET = _load_secret()
AUTH_TTL_SECONDS = int(os.getenv("AUTH_TTL_SECONDS", "28800"))

                                                                            
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"

def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("pbkdf2_sha256$"):
        return False
    try:
        _, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False

_DUMMY_HASH = hash_password("masar-dummy-password")

def burn_password_check(password: str) -> None:
    """Spend the same time as a real check so unknown accounts are not detectable by timing."""
    verify_password(password, _DUMMY_HASH)

                                                                           
def issue_token(student_id: str) -> str:
    payload = {"sub": student_id, "exp": int(time.time()) + AUTH_TTL_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"

def verify_token(token: str) -> str | None:
    """Return the student id if the token is valid and unexpired, otherwise None."""
    try:
        raw, sig = token.rsplit(".", 1)
        expected = hmac.new(AUTH_SECRET, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        owner = str(payload.get("sub", ""))
        return owner or None
    except Exception:
        return None

                                                                           
def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"

def hash_otp(code: str, purpose: str, identifier: str) -> str:
    """Keyed hash bound to the purpose and identifier, so a code for one flow is useless in another."""
    message = f"otp|{purpose}|{identifier.strip().lower()}|{code.strip()}".encode("utf-8")
    return hmac.new(AUTH_SECRET, message, hashlib.sha256).hexdigest()

                                                                            
class RateLimiter:
    """Sliding-window limiter kept in process memory (fine for one server
    process; use Redis or a gateway limit if you scale horizontally)."""

    def __init__(self):
        self._hits: dict = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key, window: float, now: float):
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        return q

    def allow(self, key, limit: int, window: float) -> bool:
        """Record one hit; return False when the limit is already reached."""
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, window, now)
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def is_blocked(self, key, limit: int, window: float) -> bool:
        now = time.monotonic()
        with self._lock:
            return len(self._prune(key, window, now)) >= limit

    def record(self, key) -> None:
        with self._lock:
            self._hits[key].append(time.monotonic())

    def clear(self, key) -> None:
        with self._lock:
            self._hits.pop(key, None)

limiter = RateLimiter()
