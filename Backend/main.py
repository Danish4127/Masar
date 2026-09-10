from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional
import re
import hashlib
import hmac
import secrets
import base64
import json
import time
from datetime import datetime
from fastapi import Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import text
import os
import pandas as pd
from dotenv import load_dotenv

load_dotenv()


def normalize_course_code(value: str) -> str:
    return re.sub(r"\s+", "", str(value)).strip().upper()


from db import engine
from recommender import generate_recommendations, generate_all_plans, save_recommendation_to_db, PLAN_VARIANTS, get_courses_df
from email_utils import send_otp_email

app = FastAPI(title="Masar Academic Advisor API", version="2.1")

AUTH_SECRET = os.getenv("AUTH_SECRET", "change-this-secret-in-production").encode("utf-8")
AUTH_TTL_SECONDS = int(os.getenv("AUTH_TTL_SECONDS", "28800"))
bearer_scheme = HTTPBearer(auto_error=False)

def _issue_token(student_id: str) -> str:
    payload = {"sub": student_id, "exp": int(time.time()) + AUTH_TTL_SECONDS}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    sig = hmac.new(AUTH_SECRET, raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"

def _require_student(credentials: HTTPAuthorizationCredentials | None, student_id: str | None = None) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    try:
        raw, sig = credentials.credentials.rsplit(".", 1)
        expected = hmac.new(AUTH_SECRET, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        padded = raw + "=" * (-len(raw) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        if int(payload.get("exp", 0)) < int(time.time()):
            raise ValueError("expired")
        owner = str(payload.get("sub", ""))
        if not owner or (student_id is not None and owner != student_id):
            raise ValueError("wrong student")
        return owner
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session.")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if x.strip()],
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class StudentProfileRequest(BaseModel):
    student_id: str = "202300000"
    full_name: str
    academic_major: Optional[str] = None
    gpa: float = Field(ge=0, le=4)
    math_confidence: int = Field(ge=1, le=5)
    programming_confidence: int = Field(ge=1, le=5)
    workload_tolerance: int = Field(ge=10, le=50)
    email: Optional[str] = None
    password: Optional[str] = None
    profile_photo: Optional[str] = None
    completed_courses: List[str] = Field(default_factory=list)
    completed_grades: dict[str, str] = Field(default_factory=dict)
    plan_type: str = "balanced"
    privacy_consent: Optional[bool] = None

    @field_validator("completed_courses", mode="before")
    @classmethod
    def clean_completed_courses(cls, value):
        if value is None:
            return []
        if not isinstance(value, (list, tuple, set)):
            return []
        cleaned = []
        for item in value:
            if isinstance(item, str):
                code = normalize_course_code(item)
            elif isinstance(item, dict):
                code = normalize_course_code(item.get("course_code") or item.get("code"))
            else:
                code = normalize_course_code(item)
            if code:
                cleaned.append(code)
        return list(dict.fromkeys(cleaned))

    @field_validator("student_id")
    @classmethod
    def validate_student_id(cls, value):
        value = str(value).strip()
        if not re.fullmatch(r"\d{9}", value):
            raise ValueError("Student ID must contain exactly 9 digits.")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        if value is None:
            return value
        value = value.strip().lower()
        if value and not re.fullmatch(r"[A-Za-z0-9._%+-]+@uaeu\.ac\.ae", value):
            raise ValueError("Email must use the @uaeu.ac.ae domain.")
        return value

    @field_validator("completed_grades", mode="before")
    @classmethod
    def clean_completed_grades(cls, value):
        if not isinstance(value, dict):
            return {}
        allowed = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D"}
        cleaned = {normalize_course_code(k): str(v).strip().upper() for k, v in value.items() if normalize_course_code(k)}
        invalid = [grade for grade in cleaned.values() if grade not in allowed]
        if invalid:
            raise ValueError("F and other unsupported grades are not allowed for passed courses.")
        return cleaned


class LoginRequest(BaseModel):
    identifier: str
    password: str = ""


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 240_000)
    return f"pbkdf2_sha256$240000${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str | None) -> bool:
    if not encoded or not encoded.startswith("pbkdf2_sha256$"):
        return False
    try:
        _, iterations, salt_hex, digest_hex = encoded.split("$", 3)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations))
        return hmac.compare_digest(candidate.hex(), digest_hex)
    except (ValueError, TypeError):
        return False


def _upsert_student(conn, profile: StudentProfileRequest):
    current = conn.execute(text("SELECT email, password_hash, profile_photo, privacy_consent, privacy_consent_at FROM student WHERE student_id = :sid"), {"sid": profile.student_id}).mappings().fetchone()
    password_hash = _hash_password(profile.password) if profile.password else (current["password_hash"] if current else None)
    email = (profile.email or (current["email"] if current else None) or "").strip().lower() or None
    profile_photo = profile.profile_photo if profile.profile_photo is not None else (current["profile_photo"] if current else None)
    privacy_consent = profile.privacy_consent if profile.privacy_consent is not None else bool(current["privacy_consent"] if current else False)
    privacy_consent_at = (current["privacy_consent_at"] if current else None)
    if profile.privacy_consent is True and privacy_consent_at is None:
        privacy_consent_at = datetime.utcnow()
    conn.execute(
        text("""
            INSERT INTO student (
                student_id, email, full_name, major, gpa, math_confidence,
                programming_confidence, workload_tolerance, password_hash, profile_photo, privacy_consent, privacy_consent_at
            ) VALUES (
                :student_id, :email, :full_name, :major, :gpa, :math_conf,
                :prog_conf, :workload_tol, :password_hash, :profile_photo, :privacy_consent, :privacy_consent_at
            )
            ON CONFLICT (student_id) DO UPDATE SET
                email = EXCLUDED.email, full_name = EXCLUDED.full_name, major = EXCLUDED.major, gpa = EXCLUDED.gpa,
                math_confidence = EXCLUDED.math_confidence, programming_confidence = EXCLUDED.programming_confidence,
                workload_tolerance = EXCLUDED.workload_tolerance, password_hash = EXCLUDED.password_hash,
                profile_photo = EXCLUDED.profile_photo, privacy_consent = EXCLUDED.privacy_consent,
                privacy_consent_at = EXCLUDED.privacy_consent_at;
        """),
        {
            "student_id": profile.student_id, "email": email, "full_name": profile.full_name, "major": profile.academic_major,
            "gpa": profile.gpa, "math_conf": profile.math_confidence, "prog_conf": profile.programming_confidence,
            "workload_tol": profile.workload_tolerance, "password_hash": password_hash, "profile_photo": profile_photo,
            "privacy_consent": privacy_consent, "privacy_consent_at": privacy_consent_at,
        },
    )


def ensure_student_columns():
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE student ADD COLUMN IF NOT EXISTS email TEXT"))
        conn.execute(text("ALTER TABLE student ADD COLUMN IF NOT EXISTS password_hash TEXT"))
        conn.execute(text("ALTER TABLE student ADD COLUMN IF NOT EXISTS profile_photo TEXT"))
        conn.execute(text("ALTER TABLE student ADD COLUMN IF NOT EXISTS privacy_consent BOOLEAN NOT NULL DEFAULT FALSE"))
        conn.execute(text("ALTER TABLE student ADD COLUMN IF NOT EXISTS privacy_consent_at TIMESTAMP"))
        conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS idx_student_email ON student(email) WHERE email IS NOT NULL AND email <> ''"))
        conn.execute(text("""CREATE TABLE IF NOT EXISTS course_ratings (rating_id SERIAL PRIMARY KEY, student_id VARCHAR(20) REFERENCES student(student_id) ON DELETE CASCADE, course_id INT REFERENCES course(course_id) ON DELETE CASCADE, difficulty_rating INT NOT NULL CHECK (difficulty_rating BETWEEN 1 AND 5), workload_rating INT NOT NULL CHECK (workload_rating BETWEEN 1 AND 5), comment TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(student_id, course_id))"""))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_course_ratings_course ON course_ratings(course_id)"))
        # OTP flow now also covers signup + login (previously reset-password only).
        # student_id stays nullable (a pending signup has no student row yet), and the
        # new columns default so the existing reset-password rows/queries are unaffected.
        conn.execute(text("ALTER TABLE password_reset_otp ALTER COLUMN student_id DROP NOT NULL"))
        conn.execute(text("ALTER TABLE password_reset_otp ADD COLUMN IF NOT EXISTS purpose VARCHAR(20) NOT NULL DEFAULT 'reset'"))
        conn.execute(text("ALTER TABLE password_reset_otp ADD COLUMN IF NOT EXISTS identifier TEXT"))
        conn.execute(text("ALTER TABLE password_reset_otp ADD COLUMN IF NOT EXISTS payload JSONB"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_password_reset_otp_identifier ON password_reset_otp(identifier, purpose, created_at DESC)"))


def _sync_completed_courses(conn, student_id: str, course_codes: List[str], grades: dict[str, str] | None = None):
    grades = {normalize_course_code(k): str(v).strip().upper() for k, v in (grades or {}).items()}
    allowed = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D"}
    if any(value not in allowed for value in grades.values()):
        raise HTTPException(status_code=422, detail="Only passing grades A+ through D are allowed for completed courses.")
    missing = [code for code in course_codes if code not in grades]
    if missing:
        raise HTTPException(status_code=422, detail="Select a grade for every completed course.")
    course_codes = [normalize_course_code(c) for c in course_codes if str(c).strip()]
    conn.execute(
        text("DELETE FROM completed_courses WHERE student_id = :sid"),
        {"sid": student_id},
    )
    if not course_codes:
        return

    rows = conn.execute(
        text("""
            SELECT course_id, course_code
            FROM course
            WHERE course_code = ANY(:codes)
        """),
        {"codes": list(dict.fromkeys(course_codes))},
    ).mappings().all()

    if rows:
                                                                         
                                                                 
        conn.execute(
            text("""
                INSERT INTO completed_courses (student_id, course_id, grade)
                VALUES (:sid, :course_id, :grade)
            """),
            [{"sid": student_id, "course_id": row["course_id"], "grade": grades.get(normalize_course_code(row["course_code"]))} for row in rows],
        )


def _student_profile_from_row(row):
    return {
        "student_id": row["student_id"],
        "email": row.get("email") if hasattr(row, "get") else None,
        "full_name": row["full_name"],
        "academic_major": row["major"],
        "gpa": float(row["gpa"]) if row["gpa"] is not None else 0,
        "math_confidence": row["math_confidence"] or 3,
        "programming_confidence": row["programming_confidence"] or 3,
        "workload_tolerance": row["workload_tolerance"] or 30,
        "profile_photo": row.get("profile_photo") if hasattr(row, "get") else None,
    }


@app.on_event("startup")
def startup():
    try:
        from db import run_schema
        run_schema()
        ensure_student_columns()
        try:
            get_courses_df()
        except Exception as cache_exc:
            print(f"Masar course-cache warmup warning: {cache_exc}")
    except Exception as exc:
        print(f"Masar startup database initialization warning: {exc}")


@app.get("/")
def read_root():
    return {"status": "online", "message": "Masar Advisor API Engine"}


@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {e}")


@app.get("/system/config")
def system_config():
    return {"success": True, "supported_languages": ["en", "ar"], "default_language": "en", "plan_variants": PLAN_VARIANTS, "high_difficulty_threshold": 4, "workload_is_hard_cap": True}

@app.get("/courses")
def get_courses():
    try:
        courses_df = get_courses_df().sort_values("course_code").reset_index(drop=True)
        return {"success": True, "courses": courses_df.to_dict(orient="records")}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _signup_response(profile: StudentProfileRequest) -> dict:
    student_data = {
        "gpa": profile.gpa,
        "math_confidence": profile.math_confidence,
        "programming_confidence": profile.programming_confidence,
        "workload_tolerance": profile.workload_tolerance,
    }
    plans = generate_all_plans(student_data, profile.completed_courses)
    return {
        "success": True,
        "access_token": _issue_token(profile.student_id),
        "student": _student_profile_from_row({
            "student_id": profile.student_id,
            "full_name": profile.full_name,
            "email": profile.email,
            "major": profile.academic_major,
            "gpa": profile.gpa,
            "math_confidence": profile.math_confidence,
            "programming_confidence": profile.programming_confidence,
            "workload_tolerance": profile.workload_tolerance,
        }),
        "completed_courses": [normalize_course_code(c) for c in profile.completed_courses],
        "completed_grades": profile.completed_grades,
        "plans": plans,
    }


def _check_signup_conflict(conn, student_id: str, email: str):
    existing = conn.execute(
        text("SELECT student_id FROM student WHERE student_id = :sid OR (email = :email AND :email <> '')"),
        {"sid": student_id, "email": email},
    ).mappings().fetchone()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="An account with this Student ID or email already exists. Please sign in instead.",
        )


def _validate_signup_profile(profile: StudentProfileRequest) -> str:
    """Runs the same checks the direct /students/signup endpoint always ran,
    so a bad signup never gets as far as sending an OTP email. Returns the
    normalized email."""
    if not profile.password or len(profile.password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    if not profile.privacy_consent:
        raise HTTPException(status_code=400, detail="Privacy consent is required to create an account.")
    email = (profile.email or "").strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9._%+-]+@uaeu\.ac\.ae", email, flags=re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Please use your official UAEU email address ending in @uaeu.ac.ae.")
    return email


@app.post("/students/signup")
def signup(profile: StudentProfileRequest):
    """Kept for direct/scripted account creation (e.g. the synthetic data
    generator) that intentionally bypasses the OTP flow. Real users go
    through /students/signup/request-otp + /students/signup/verify-otp
    instead (see Auth() in the frontend)."""
    email = _validate_signup_profile(profile)
    try:
        with engine.begin() as conn:
            _check_signup_conflict(conn, profile.student_id, email)
            _upsert_student(conn, profile)
            _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
        return _signup_response(profile)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/students/login")
def login(payload: LoginRequest):
    """Verifies the password, then requires an OTP for accounts that have an
    email on file (all real signups do). Accounts without an email (e.g.
    synthetic/test data seeded directly into the DB) log in immediately,
    since there is nowhere to send a code."""
    try:
        with engine.connect() as conn:
            identifier = payload.identifier.strip()
            row = conn.execute(
                text("SELECT * FROM student WHERE student_id = :identifier OR LOWER(email) = LOWER(:identifier) LIMIT 1"),
                {"identifier": identifier},
            ).mappings().fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Account not found.")
            if not _verify_password(payload.password, row.get("password_hash")):
                raise HTTPException(status_code=401, detail="Invalid username/email or password.")

            email = (row.get("email") or "").strip()
            if not email:
                completed = conn.execute(
                    text("""
                        SELECT c.course_code, c.course_name, c.credits, cc.grade
                        FROM completed_courses cc
                        JOIN course c ON c.course_id = cc.course_id
                        WHERE cc.student_id = :sid
                        ORDER BY c.course_code
                    """),
                    {"sid": row["student_id"]},
                ).mappings().all()
                return {
                    "success": True,
                    "otp_required": False,
                    "access_token": _issue_token(row["student_id"]),
                    "student": _student_profile_from_row(row),
                    "completed_courses": [dict(c) for c in completed],
                }

        with engine.begin() as conn:
            otp_code = _generate_otp()
            conn.execute(
                text("""
                    INSERT INTO password_reset_otp (student_id, identifier, purpose, otp_hash, expires_at)
                    VALUES (:sid, :identifier, 'login', :otp_hash, NOW() + INTERVAL '10 minutes')
                """),
                {"sid": row["student_id"], "identifier": row["student_id"], "otp_hash": _hash_otp(otp_code)},
            )
            send_otp_email(email, otp_code)

        return {"success": True, "otp_required": True, "student_id": row["student_id"], "message": "A verification code has been sent to your registered email."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class LoginVerifyRequest(BaseModel):
    identifier: str
    otp_code: str


@app.post("/students/login/verify-otp")
def login_verify_otp(payload: LoginVerifyRequest):
    """Second step of login for accounts with an email on file: confirms the
    OTP sent by /students/login and only then issues the access token."""
    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT * FROM student WHERE student_id = :identifier OR LOWER(email) = LOWER(:identifier) LIMIT 1"),
            {"identifier": payload.identifier.strip()},
        ).mappings().fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")

        otp_row = conn.execute(
            text("""
                SELECT otp_id FROM password_reset_otp
                WHERE identifier = :sid AND purpose = 'login' AND otp_hash = :otp_hash
                  AND used = FALSE AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
            """),
            {"sid": row["student_id"], "otp_hash": _hash_otp(payload.otp_code.strip())},
        ).mappings().fetchone()
        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")

        conn.execute(text("UPDATE password_reset_otp SET used = TRUE WHERE otp_id = :oid"), {"oid": otp_row["otp_id"]})

        completed = conn.execute(
            text("""
                SELECT c.course_code, c.course_name, c.credits, cc.grade
                FROM completed_courses cc
                JOIN course c ON c.course_id = cc.course_id
                WHERE cc.student_id = :sid
                ORDER BY c.course_code
            """),
            {"sid": row["student_id"]},
        ).mappings().all()

    return {
        "success": True,
        "access_token": _issue_token(row["student_id"]),
        "student": _student_profile_from_row(row),
        "completed_courses": [dict(c) for c in completed],
    }


class SignupOtpRequest(StudentProfileRequest):
    pass


class SignupVerifyRequest(BaseModel):
    email: str
    otp_code: str


@app.post("/students/signup/request-otp")
def signup_request_otp(profile: SignupOtpRequest):
    """Validates the signup exactly like /students/signup would, but instead
    of creating the account immediately, stashes it (password already
    hashed) against an OTP and emails the code. The account is only created
    once /students/signup/verify-otp confirms the code."""
    email = _validate_signup_profile(profile)
    with engine.begin() as conn:
        _check_signup_conflict(conn, profile.student_id, email)

        pending = profile.model_dump()
        pending.pop("password", None)
        pending["password_hash"] = _hash_password(profile.password)
        pending["email"] = email

        otp_code = _generate_otp()
        conn.execute(
            text("""
                INSERT INTO password_reset_otp (identifier, purpose, otp_hash, payload, expires_at)
                VALUES (:identifier, 'signup', :otp_hash, CAST(:payload AS JSONB), NOW() + INTERVAL '10 minutes')
            """),
            {"identifier": email, "otp_hash": _hash_otp(otp_code), "payload": json.dumps(pending)},
        )
        send_otp_email(email, otp_code)

    return {"success": True, "message": "Verification code sent to your UAEU email."}


@app.post("/students/signup/verify-otp")
def signup_verify_otp(payload: SignupVerifyRequest):
    """Confirms the signup OTP, then actually creates the account using the
    data captured at request-otp time."""
    email = payload.email.strip().lower()
    with engine.begin() as conn:
        otp_row = conn.execute(
            text("""
                SELECT otp_id, payload FROM password_reset_otp
                WHERE identifier = :identifier AND purpose = 'signup' AND otp_hash = :otp_hash
                  AND used = FALSE AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
            """),
            {"identifier": email, "otp_hash": _hash_otp(payload.otp_code.strip())},
        ).mappings().fetchone()
        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")

        data = otp_row["payload"]
        if isinstance(data, str):
            data = json.loads(data)

        _check_signup_conflict(conn, data["student_id"], email)

        profile = StudentProfileRequest(**{k: v for k, v in data.items() if k != "password_hash"})
        _upsert_student(conn, profile)
        conn.execute(
            text("UPDATE student SET password_hash = :ph WHERE student_id = :sid"),
            {"ph": data["password_hash"], "sid": profile.student_id},
        )
        _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
        conn.execute(text("UPDATE password_reset_otp SET used = TRUE WHERE otp_id = :oid"), {"oid": otp_row["otp_id"]})

    return _signup_response(profile)


class ForgotPasswordRequest(BaseModel):
    identifier: str


class VerifyOtpRequest(BaseModel):
    identifier: str
    otp_code: str


class ResetPasswordRequest(BaseModel):
    identifier: str
    otp_code: str
    new_password: str = Field(min_length=8)


def _generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def _hash_otp(otp_code: str) -> str:
    return hashlib.sha256(otp_code.encode("utf-8")).hexdigest()


@app.post("/students/forgot-password")
def forgot_password(payload: ForgotPasswordRequest):
    """Generates a one-time code and emails it to the student's registered
    UAEU email address (see email_utils.py for provider setup). Always
    returns the same response regardless of whether the account exists, so
    the endpoint cannot be used to enumerate valid student IDs/emails."""
    identifier = payload.identifier.strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Enter your username or email.")

    generic_message = "If the account exists, a verification code has been sent to the registered email."

    with engine.begin() as conn:
        row = conn.execute(
            text("SELECT student_id, email FROM student WHERE student_id = :identifier OR LOWER(email) = LOWER(:identifier) LIMIT 1"),
            {"identifier": identifier},
        ).mappings().fetchone()

        if not row or not row["email"]:
            return {"success": True, "message": generic_message}

        otp_code = _generate_otp()
        conn.execute(
            text(
                """
                INSERT INTO password_reset_otp (student_id, otp_hash, expires_at)
                VALUES (:sid, :otp_hash, NOW() + INTERVAL '10 minutes')
                """
            ),
            {"sid": row["student_id"], "otp_hash": _hash_otp(otp_code)},
        )
        send_otp_email(row["email"], otp_code)

    return {"success": True, "message": generic_message}


@app.post("/students/verify-otp")
def verify_otp(payload: VerifyOtpRequest):
    """Checks a submitted OTP without consuming it, so the frontend can show
    a 'code verified' step before asking for the new password."""
    with engine.connect() as conn:
        student = conn.execute(
            text("SELECT student_id FROM student WHERE student_id = :identifier OR LOWER(email) = LOWER(:identifier) LIMIT 1"),
            {"identifier": payload.identifier.strip()},
        ).mappings().fetchone()
        if not student:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")

        valid = conn.execute(
            text(
                """
                SELECT 1 FROM password_reset_otp
                WHERE student_id = :sid AND otp_hash = :otp_hash
                  AND used = FALSE AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"sid": student["student_id"], "otp_hash": _hash_otp(payload.otp_code.strip())},
        ).scalar()

    if not valid:
        raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return {"success": True, "message": "Code verified."}


@app.post("/students/reset-password")
def reset_password(payload: ResetPasswordRequest):
    """Verifies the OTP (marking it used) and sets the new password hash."""
    with engine.begin() as conn:
        student = conn.execute(
            text("SELECT student_id FROM student WHERE student_id = :identifier OR LOWER(email) = LOWER(:identifier) LIMIT 1"),
            {"identifier": payload.identifier.strip()},
        ).mappings().fetchone()
        if not student:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")

        otp_row = conn.execute(
            text(
                """
                SELECT otp_id FROM password_reset_otp
                WHERE student_id = :sid AND otp_hash = :otp_hash
                  AND used = FALSE AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1
                """
            ),
            {"sid": student["student_id"], "otp_hash": _hash_otp(payload.otp_code.strip())},
        ).mappings().fetchone()

        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")

        conn.execute(
            text("UPDATE password_reset_otp SET used = TRUE WHERE otp_id = :oid"),
            {"oid": otp_row["otp_id"]},
        )
        conn.execute(
            text("UPDATE student SET password_hash = :ph WHERE student_id = :sid"),
            {"ph": _hash_password(payload.new_password), "sid": student["student_id"]},
        )

    return {"success": True, "message": "Password updated. You can now log in with your new password."}


@app.get("/students/{student_id}")
def get_student(student_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    try:
        with engine.connect() as conn:
            student_row = conn.execute(
                text("SELECT * FROM student WHERE student_id = :sid"),
                {"sid": student_id},
            ).mappings().fetchone()

            if not student_row:
                raise HTTPException(status_code=404, detail="Student not found")

            completed = conn.execute(
                text("""
                    SELECT c.course_code, c.course_name, c.credits, cc.grade
                    FROM completed_courses cc
                    JOIN course c ON c.course_id = cc.course_id
                    WHERE cc.student_id = :sid
                    ORDER BY c.course_code
                """),
                {"sid": student_id},
            ).mappings().all()

            latest_rec = conn.execute(
                text("""
                    SELECT recommendation_id, generated_date, total_workload,
                           overall_risk_level, plan_summary
                    FROM recommendation
                    WHERE student_id = :sid
                    ORDER BY generated_date DESC, recommendation_id DESC
                    LIMIT 1
                """),
                {"sid": student_id},
            ).mappings().fetchone()

            rec_courses = []
            if latest_rec:
                rec_courses = conn.execute(
                    text("""
                        SELECT c.course_code, c.course_name, c.credits,
                               c.difficulty_level, c.math_intensity,
                               c.weekly_workload, c.subject_area, c.assessment_type,
                               rc.reason
                        FROM recommended_courses rc
                        JOIN course c ON c.course_id = rc.course_id
                        WHERE rc.recommendation_id = :rid
                        ORDER BY c.course_code
                    """),
                    {"rid": latest_rec["recommendation_id"]},
                ).mappings().all()

        return {
            "success": True,
            "student": _student_profile_from_row(student_row),
            "completed_courses": [dict(c) for c in completed],
            "latest_recommendation": dict(latest_rec) if latest_rec else None,
            "recommended_courses": [dict(r) for r in rec_courses],
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/students/{student_id}/recommendation-history")
def recommendation_history(student_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    """Return saved semester-plan decisions for the student's Active History view."""
    try:
        with engine.connect() as conn:
            exists = conn.execute(text("SELECT 1 FROM student WHERE student_id = :sid"), {"sid": student_id}).scalar()
            if not exists:
                raise HTTPException(status_code=404, detail="Student not found")
            rows = conn.execute(text("""
                SELECT recommendation_id, generated_date, total_workload,
                       overall_risk_level, plan_summary
                FROM recommendation
                WHERE student_id = :sid
                ORDER BY generated_date DESC, recommendation_id DESC
                LIMIT 20
            """), {"sid": student_id}).mappings().all()
            history = []
            if rows:
                                                                                           
                ids = [r["recommendation_id"] for r in rows]
                course_rows = conn.execute(text("""
                    SELECT rc.recommendation_id, c.course_code, c.course_name, c.credits, rc.reason
                    FROM recommended_courses rc
                    JOIN course c ON c.course_id = rc.course_id
                    WHERE rc.recommendation_id = ANY(:ids)
                    ORDER BY rc.recommendation_id DESC, c.course_code
                """), {"ids": ids}).mappings().all()
                by_rec = {rid: [] for rid in ids}
                for course in course_rows:
                    by_rec.setdefault(course["recommendation_id"], []).append({
                        "course_code": course["course_code"],
                        "course_name": course["course_name"],
                        "credits": course["credits"],
                        "reason": course["reason"],
                    })
                history = [{**dict(row), "courses": by_rec.get(row["recommendation_id"], [])} for row in rows]
        return {"success": True, "history": history}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/students/{student_id}")
def update_student(student_id: str, profile: StudentProfileRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    if profile.student_id != student_id:
        raise HTTPException(status_code=400, detail="Student ID in the body must match the URL.")
    if profile.email is not None and not re.fullmatch(r"[A-Za-z0-9._%+-]+@uaeu\.ac\.ae", profile.email.strip(), flags=re.IGNORECASE):
        raise HTTPException(status_code=400, detail="Please use your official UAEU email address ending in @uaeu.ac.ae.")
    try:
        with engine.begin() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM student WHERE student_id = :sid"),
                {"sid": student_id},
            ).scalar()
            if not exists:
                raise HTTPException(status_code=404, detail="Student not found.")
            _upsert_student(conn, profile)
            _sync_completed_courses(conn, student_id, profile.completed_courses, profile.completed_grades)
            updated_row = conn.execute(
                text("SELECT * FROM student WHERE student_id = :sid"),
                {"sid": student_id},
            ).mappings().fetchone()
        return {
            "success": True,
            "message": "Profile and completed courses updated.",
            "student": _student_profile_from_row(updated_row),
            "completed_courses": [normalize_course_code(c) for c in profile.completed_courses],
            "completed_grades": profile.completed_grades,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class ManualPlanRequest(BaseModel):
    student_id: str
    course_codes: List[str] = Field(default_factory=list)
    plan_label: str = "Custom"


@app.post("/plans/save")
def save_manual_plan(payload: ManualPlanRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, payload.student_id)
    try:
        codes = list(dict.fromkeys(normalize_course_code(c) for c in payload.course_codes if str(c).strip()))
        with engine.begin() as conn:
            student = conn.execute(text("SELECT student_id FROM student WHERE student_id = :sid"), {"sid": payload.student_id}).scalar()
            if not student:
                raise HTTPException(status_code=404, detail="Student not found.")
            rows = conn.execute(text("SELECT * FROM course WHERE course_code = ANY(:codes)"), {"codes": codes}).mappings().all() if codes else []
            found = {r["course_code"]: r for r in rows}
            missing = [c for c in codes if c not in found]
            if missing:
                raise HTTPException(status_code=400, detail=f"Unknown course code(s): {', '.join(missing)}")
            passed_rows = conn.execute(text("""
                SELECT c.course_code
                FROM completed_courses cc
                JOIN course c ON c.course_id = cc.course_id
                WHERE cc.student_id = :sid AND c.course_code = ANY(:codes)
            """), {"sid": payload.student_id, "codes": codes}).scalars().all() if codes else []
            if passed_rows:
                raise HTTPException(status_code=400, detail=f"These courses are already passed and cannot be added: {', '.join(passed_rows)}")
            student_tolerance = int(conn.execute(text("SELECT workload_tolerance FROM student WHERE student_id = :sid"), {"sid": payload.student_id}).scalar() or 30)
            total_workload = sum(int(r["weekly_workload"] or 0) for r in rows)
            high_difficulty = sum(1 for r in rows if int(r["difficulty_level"] or 0) >= 4)
            if total_workload > student_tolerance:
                raise HTTPException(status_code=400, detail=f"This custom plan requires {total_workload} hrs/week, above your {student_tolerance} hrs/week workload tolerance.")
            if high_difficulty > 2:
                raise HTTPException(status_code=400, detail="A semester plan cannot contain more than 2 high-difficulty courses.")
            risk = "Low" if total_workload <= 25 else ("Medium" if total_workload <= 38 else "High")
            rec_id = conn.execute(text("""INSERT INTO recommendation (student_id,total_workload,overall_risk_level,plan_summary) VALUES (:sid,:workload,:risk,:summary) RETURNING recommendation_id"""), {"sid": payload.student_id, "workload": total_workload, "risk": risk, "summary": f"{payload.plan_label} Plan ({len(rows)} Courses)"}).scalar()
            if rows:
                conn.execute(
                    text("INSERT INTO recommended_courses (recommendation_id,course_id,reason) VALUES (:rid,:cid,:reason)"),
                    [{"rid": rec_id, "cid": row["course_id"], "reason": "Manually selected by the student from the course catalog."} for row in rows],
                )
        return {"success": True, "recommendation_id": rec_id, "saved_courses": codes}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class CourseRatingRequest(BaseModel):
    student_id: str
    course_code: str
    difficulty_rating: int = Field(ge=1, le=5)
    workload_rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)

@app.put("/courses/{course_code}/rating")
def rate_course(payload: CourseRatingRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, payload.student_id)
    code = normalize_course_code(payload.course_code)
    with engine.begin() as conn:
        course = conn.execute(text("SELECT course_id FROM course WHERE course_code = :code"), {"code": code}).scalar()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found.")
        passed = conn.execute(text("SELECT 1 FROM completed_courses WHERE student_id=:sid AND course_id=:cid"), {"sid": payload.student_id, "cid": course}).scalar()
        if not passed:
            raise HTTPException(status_code=400, detail="Only completed courses can be rated.")
        conn.execute(text("""INSERT INTO course_ratings(student_id,course_id,difficulty_rating,workload_rating,comment) VALUES(:sid,:cid,:difficulty,:workload,:comment) ON CONFLICT(student_id,course_id) DO UPDATE SET difficulty_rating=EXCLUDED.difficulty_rating, workload_rating=EXCLUDED.workload_rating, comment=EXCLUDED.comment, updated_at=CURRENT_TIMESTAMP"""), {"sid":payload.student_id,"cid":course,"difficulty":payload.difficulty_rating,"workload":payload.workload_rating,"comment":payload.comment})
    return {"success": True, "message": "Course rating saved."}

@app.get("/students/{student_id}/ratings")
def get_ratings(student_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    with engine.connect() as conn:
        rows = conn.execute(text("""SELECT c.course_code, cr.difficulty_rating, cr.workload_rating, cr.comment FROM course_ratings cr JOIN course c ON c.course_id=cr.course_id WHERE cr.student_id=:sid ORDER BY c.course_code"""), {"sid":student_id}).mappings().all()
    return {"success": True, "ratings": [dict(r) for r in rows]}

@app.post("/recommend/preview")
def preview_plans(profile: StudentProfileRequest):
    try:
        student_data = {
            "gpa": profile.gpa,
            "math_confidence": profile.math_confidence,
            "programming_confidence": profile.programming_confidence,
            "workload_tolerance": profile.workload_tolerance,
        }
        plans = generate_all_plans(student_data, profile.completed_courses)
        return {"success": True, "plans": plans}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/recommend")
def get_recommendation(profile: StudentProfileRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, profile.student_id)
    try:
        if profile.plan_type not in PLAN_VARIANTS:
            raise HTTPException(
                status_code=400,
                detail=f"plan_type must be one of {list(PLAN_VARIANTS.keys())}",
            )

        cfg = PLAN_VARIANTS[profile.plan_type]
        student_data = {
            "gpa": profile.gpa,
            "math_confidence": profile.math_confidence,
            "programming_confidence": profile.programming_confidence,
            "workload_tolerance": profile.workload_tolerance,
        }

        recs_df, excluded, message = generate_recommendations(
            student_data,
            profile.completed_courses,
            credit_target_max=cfg["credit_target_max"],
            max_high_difficulty=cfg["max_high_difficulty"],
            workload_multiplier=cfg["workload_multiplier"],
            plan_label=profile.plan_type.capitalize(),
        )

        if recs_df.empty:
            with engine.begin() as conn:
                _upsert_student(conn, profile)
                _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
            return {
                "success": False,
                "message": message,
                "recommendations": [],
                "excluded": excluded,
            }

        with engine.begin() as conn:
            _upsert_student(conn, profile)
            _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
            rec_id = save_recommendation_to_db(
                conn,
                profile.student_id,
                recs_df,
                plan_label=profile.plan_type.capitalize(),
            )

        return {
            "success": True,
            "message": message,
            "recommendation_id": rec_id,
            "plan_type": profile.plan_type,
            "recommendations": recs_df.to_dict(orient="records"),
            "excluded": excluded,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
