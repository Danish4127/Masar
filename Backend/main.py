"""Masar Academic Advisor API (FastAPI)."""
from __future__ import annotations

import json
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import Depends, FastAPI, HTTPException, Request              
from fastapi.middleware.cors import CORSMiddleware              
from fastapi.responses import JSONResponse              
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer              
from pydantic import BaseModel, Field, field_validator              
from sqlalchemy import text              

import ai_explanation              
from db import engine, run_schema              
from email_utils import send_otp_email              
from prereq import normalize_code as normalize_course_code              
from recommender import (              
    PLAN_VARIANTS,
    HIGH_DIFFICULTY_THRESHOLD,
    compute_risk_level,
    generate_all_plans,
    generate_recommendations,
    get_courses_df,
    records,
    save_recommendation_to_db,
    validate_plan_eligibility,
)
from security import (              
    burn_password_check,
    generate_otp,
    hash_otp,
    hash_password,
    issue_token,
    limiter,
    verify_password,
    verify_token,
)

log = logging.getLogger("masar.api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

MIN_PASSWORD_LENGTH = 8
MAX_PHOTO_CHARS = 2_500_000
OTP_TTL_MINUTES = 10

@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        run_schema()                                             
        try:
            get_courses_df()
        except Exception as exc:
            log.warning("Course-cache warm-up failed: %s", exc)
    except Exception as exc:
        log.error("Database initialisation failed: %s", exc)
    yield

app = FastAPI(title="Masar Academic Advisor API", version="3.0", lifespan=lifespan)

                                                                           
                                                                                    
@app.middleware("http")
async def _catch_all(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception:
        log.exception("Unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})

_origins = [x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",") if x.strip()]
_origin_regex = os.getenv("FRONTEND_ORIGIN_REGEX", "").strip() or None                                       
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_ALLOWED_EMAIL_DOMAINS = [d.strip().lower() for d in os.getenv("ALLOWED_EMAIL_DOMAINS", "uaeu.ac.ae").split(",") if d.strip()]
_EMAIL_DOMAIN_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@(" + "|".join(re.escape(d) for d in _ALLOWED_EMAIL_DOMAINS) + r")$", flags=re.IGNORECASE)

def _is_allowed_email(value: str | None) -> bool:
    return bool(value and _EMAIL_DOMAIN_PATTERN.fullmatch(value.strip()))

def _email_domain_error() -> str:
    if _ALLOWED_EMAIL_DOMAINS == ["uaeu.ac.ae"]:
        return "Please use your official UAEU email address ending in @uaeu.ac.ae."
    return f"Please use an email ending in one of: {', '.join('@' + d for d in _ALLOWED_EMAIL_DOMAINS)}."

                                                                           
bearer_scheme = HTTPBearer(auto_error=False)

def _require_student(credentials: HTTPAuthorizationCredentials | None, student_id: str | None = None) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required.")
    owner = verify_token(credentials.credentials)
    if not owner or (student_id is not None and owner != student_id):
        raise HTTPException(status_code=401, detail="Invalid or expired session.")
    return owner

def _too_many(message: str = "Too many attempts. Please wait a few minutes and try again."):
    return HTTPException(status_code=429, detail=message)

def _validate_password(password: str | None) -> str:
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(status_code=400, detail=f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 128:
        raise HTTPException(status_code=400, detail="Password is too long (128 characters maximum).")
    return password

                                                                           
class StudentProfileRequest(BaseModel):
    student_id: str
    full_name: str = Field(min_length=1, max_length=100)
    academic_major: Optional[str] = Field(default=None, max_length=100)
    academic_career_goals: Optional[str] = Field(default=None, max_length=500)
    gpa: float = Field(ge=0, le=4)
    math_confidence: int = Field(ge=1, le=5)
    programming_confidence: int = Field(ge=1, le=5)
    workload_tolerance: int = Field(ge=10, le=50)
    email: Optional[str] = Field(default=None, max_length=255)
    password: Optional[str] = None
    profile_photo: Optional[str] = None
    completed_courses: List[str] = Field(default_factory=list, max_length=80)
    completed_grades: dict[str, str] = Field(default_factory=dict)
    plan_type: str = "balanced"
    privacy_consent: Optional[bool] = None

    @field_validator("completed_courses", mode="before")
    @classmethod
    def clean_completed_courses(cls, value):
        if not isinstance(value, (list, tuple, set)):
            return []
        cleaned = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("course_code") or item.get("code")
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

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, value):
        value = re.sub(r"\s+", " ", str(value)).strip()
        if not value:
            raise ValueError("Full name is required.")
        return value

    @field_validator("email")
    @classmethod
    def validate_email(cls, value):
        return value.strip().lower() if value is not None else value

    @field_validator("profile_photo")
    @classmethod
    def validate_photo(cls, value):
        if value is None or value == "":
            return value
        if not value.startswith("data:image/") or len(value) > MAX_PHOTO_CHARS:
            raise ValueError("Profile photo must be a small image (JPEG/PNG/WebP).")
        return value

class LoginRequest(BaseModel):
    identifier: str = Field(max_length=255)
    password: str = Field(default="", max_length=256)

class LoginVerifyRequest(BaseModel):
    identifier: str = Field(max_length=255)
    otp_code: str = Field(max_length=12)

class SignupVerifyRequest(BaseModel):
    email: str = Field(max_length=255)
    otp_code: str = Field(max_length=12)

class ForgotPasswordRequest(BaseModel):
    identifier: str = Field(max_length=255)

class VerifyOtpRequest(BaseModel):
    identifier: str = Field(max_length=255)
    otp_code: str = Field(max_length=12)

class ResetPasswordRequest(BaseModel):
    identifier: str = Field(max_length=255)
    otp_code: str = Field(max_length=12)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=128)

class ManualPlanRequest(BaseModel):
    student_id: str
    course_codes: List[str] = Field(default_factory=list, max_length=12)
    plan_label: str = Field(default="Custom", max_length=40)

class CourseRatingRequest(BaseModel):
    student_id: str
    course_code: str
    difficulty_rating: int = Field(ge=1, le=5)
    workload_rating: int = Field(ge=1, le=5)
    comment: Optional[str] = Field(default=None, max_length=500)

                                                                            
def _find_student(conn, identifier: str):
    return conn.execute(
        text("SELECT * FROM student WHERE student_id = :i OR LOWER(email) = LOWER(:i) LIMIT 1"),
        {"i": identifier.strip()},
    ).mappings().fetchone()

def _completed_rows(conn, student_id: str):
    return conn.execute(
        text("""SELECT c.course_code, c.course_name, c.credits, cc.grade
                FROM completed_courses cc JOIN course c ON c.course_id = cc.course_id
                WHERE cc.student_id = :sid ORDER BY c.course_code"""),
        {"sid": student_id},
    ).mappings().all()

def _student_profile_from_row(row):
    return {
        "student_id": row["student_id"],
        "email": row.get("email"),
        "full_name": row["full_name"],
        "academic_major": row["major"],
        "academic_career_goals": row.get("academic_career_goals"),
        "gpa": float(row["gpa"]) if row["gpa"] is not None else 0,
        "math_confidence": row["math_confidence"] or 3,
        "programming_confidence": row["programming_confidence"] or 3,
        "workload_tolerance": row["workload_tolerance"] or 30,
        "profile_photo": row.get("profile_photo"),
    }

def _student_data(profile: StudentProfileRequest) -> dict:
    return {
        "gpa": profile.gpa,
        "math_confidence": profile.math_confidence,
        "programming_confidence": profile.programming_confidence,
        "workload_tolerance": profile.workload_tolerance,
        "major": profile.academic_major,
        "academic_career_goals": profile.academic_career_goals,
    }

def _validate_completed_grades(course_codes: List[str], grades: dict[str, str] | None = None) -> dict[str, str]:
    """Every completed course needs a valid passing grade; raised before any write or e-mail."""
    grades = {normalize_course_code(k): str(v).strip().upper() for k, v in (grades or {}).items()}
    allowed = {"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D"}
    if any(value not in allowed for value in grades.values()):
        raise HTTPException(status_code=422, detail="Only passing grades A+ through D are allowed for completed courses.")
    if [c for c in course_codes if normalize_course_code(c) not in grades]:
        raise HTTPException(status_code=422, detail="Select a grade for every completed course.")
    return grades

def _sync_completed_courses(conn, student_id: str, course_codes: List[str], grades: dict[str, str] | None = None):
    grades = _validate_completed_grades(course_codes, grades)
    codes = list(dict.fromkeys(normalize_course_code(c) for c in course_codes if str(c).strip()))
    rows = conn.execute(text("SELECT course_id, course_code FROM course WHERE course_code = ANY(:codes)"), {"codes": codes}).mappings().all() if codes else []
    unknown = sorted(set(codes) - {r["course_code"] for r in rows})
    if unknown:
        raise HTTPException(status_code=422, detail=f"Unknown course code(s): {', '.join(unknown)}")
    conn.execute(text("DELETE FROM completed_courses WHERE student_id = :sid"), {"sid": student_id})
    if rows:
        conn.execute(
            text("INSERT INTO completed_courses (student_id, course_id, grade) VALUES (:sid, :course_id, :grade)"),
            [{"sid": student_id, "course_id": r["course_id"], "grade": grades.get(r["course_code"])} for r in rows],
        )

def _upsert_student(conn, profile: StudentProfileRequest):
    current = conn.execute(
        text("SELECT email, password_hash, profile_photo, major, academic_career_goals, privacy_consent, privacy_consent_at FROM student WHERE student_id = :sid"),
        {"sid": profile.student_id},
    ).mappings().fetchone()
    password_hash = hash_password(profile.password) if profile.password else (current["password_hash"] if current else None)
    email = (profile.email or (current["email"] if current else None) or "").strip().lower() or None
    if email and (not current or email != (current["email"] or "").lower()):
        clash = conn.execute(text("SELECT 1 FROM student WHERE LOWER(email) = :e AND student_id <> :sid"), {"e": email, "sid": profile.student_id}).scalar()
        if clash:
            raise HTTPException(status_code=409, detail="This email is already used by another account.")
    major = profile.academic_major if profile.academic_major is not None else (current["major"] if current else None)
    goals = profile.academic_career_goals if profile.academic_career_goals is not None else (current["academic_career_goals"] if current else None)
    goals = re.sub(r"\s+", " ", goals or "").strip() or None
    photo = profile.profile_photo if profile.profile_photo is not None else (current["profile_photo"] if current else None)
    consent = profile.privacy_consent if profile.privacy_consent is not None else bool(current["privacy_consent"] if current else False)
    consent_at = current["privacy_consent_at"] if current else None
    if profile.privacy_consent is True and consent_at is None:
        consent_at = datetime.now(timezone.utc).replace(tzinfo=None)
    conn.execute(
        text("""
            INSERT INTO student (student_id, email, full_name, major, academic_career_goals, gpa, math_confidence, programming_confidence,
                                 workload_tolerance, password_hash, profile_photo, privacy_consent, privacy_consent_at)
            VALUES (:student_id, :email, :full_name, :major, :academic_career_goals, :gpa, :math_conf, :prog_conf, :workload_tol,
                    :password_hash, :profile_photo, :privacy_consent, :privacy_consent_at)
            ON CONFLICT (student_id) DO UPDATE SET
                email = EXCLUDED.email, full_name = EXCLUDED.full_name, major = EXCLUDED.major, academic_career_goals = EXCLUDED.academic_career_goals, gpa = EXCLUDED.gpa,
                math_confidence = EXCLUDED.math_confidence, programming_confidence = EXCLUDED.programming_confidence,
                workload_tolerance = EXCLUDED.workload_tolerance, password_hash = EXCLUDED.password_hash,
                profile_photo = EXCLUDED.profile_photo, privacy_consent = EXCLUDED.privacy_consent,
                privacy_consent_at = EXCLUDED.privacy_consent_at
        """),
        {"student_id": profile.student_id, "email": email, "full_name": profile.full_name, "major": major,
         "academic_career_goals": goals, "gpa": profile.gpa, "math_conf": profile.math_confidence, "prog_conf": profile.programming_confidence,
         "workload_tol": profile.workload_tolerance, "password_hash": password_hash, "profile_photo": photo,
         "privacy_consent": consent, "privacy_consent_at": consent_at},
    )

def _check_signup_conflict(conn, student_id: str, email: str):
    existing = conn.execute(
        text("SELECT student_id FROM student WHERE student_id = :sid OR (LOWER(email) = :email AND :email <> '')"),
        {"sid": student_id, "email": email},
    ).mappings().fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this Student ID or email already exists. Please sign in instead.")

def _validate_signup_profile(profile: StudentProfileRequest) -> str:
    _validate_password(profile.password)
    if not profile.privacy_consent:
        raise HTTPException(status_code=400, detail="Privacy consent is required to create an account.")
    email = (profile.email or "").strip().lower()
    if not _is_allowed_email(email):
        raise HTTPException(status_code=400, detail=_email_domain_error())
    _validate_completed_grades(profile.completed_courses, profile.completed_grades)
    return email

def _signup_response(profile: StudentProfileRequest) -> dict:
    plans = generate_all_plans(_student_data(profile), profile.completed_courses)
    return {
        "success": True,
        "access_token": issue_token(profile.student_id),
        "student": _student_profile_from_row({
            "student_id": profile.student_id, "full_name": profile.full_name, "email": profile.email,
            "major": profile.academic_major, "academic_career_goals": profile.academic_career_goals, "gpa": profile.gpa, "math_confidence": profile.math_confidence,
            "programming_confidence": profile.programming_confidence, "workload_tolerance": profile.workload_tolerance,
        }),
        "completed_courses": [normalize_course_code(c) for c in profile.completed_courses],
        "completed_grades": profile.completed_grades,
        "plans": plans,
    }

                                                                           
def _create_otp(conn, purpose: str, identifier: str, student_id: str | None = None, payload: dict | None = None) -> str:
    """Create a fresh one-time code; older unused codes for the same flow are invalidated."""
    conn.execute(text("DELETE FROM password_reset_otp WHERE expires_at < NOW() - INTERVAL '1 day'"))
    conn.execute(text("UPDATE password_reset_otp SET used = TRUE WHERE identifier = :i AND purpose = :p AND used = FALSE"), {"i": identifier, "p": purpose})
    code = generate_otp()
    conn.execute(
        text(f"""INSERT INTO password_reset_otp (student_id, identifier, purpose, otp_hash, payload, expires_at)
                 VALUES (:sid, :i, :p, :h, {'CAST(:payload AS JSONB)' if payload is not None else 'NULL'}, NOW() + INTERVAL '{OTP_TTL_MINUTES} minutes')"""),
        {"sid": student_id, "i": identifier, "p": purpose, "h": hash_otp(code, purpose, identifier),
         **({"payload": json.dumps(payload)} if payload is not None else {})},
    )
    return code

def _check_otp(conn, purpose: str, identifier: str, code: str, consume: bool = True):
    """Validate a code with brute-force protection (5 wrong tries per 10 minutes)."""
    key = ("otp-verify", purpose, identifier.lower())
    if limiter.is_blocked(key, 5, 600):
        raise _too_many("Too many incorrect codes. Please request a new code in a few minutes.")
    row = conn.execute(
        text("""SELECT otp_id, payload FROM password_reset_otp
                WHERE identifier = :i AND purpose = :p AND otp_hash = :h AND used = FALSE AND expires_at > NOW()
                ORDER BY created_at DESC LIMIT 1"""),
        {"i": identifier, "p": purpose, "h": hash_otp(code.strip(), purpose, identifier)},
    ).mappings().fetchone()
    if not row:
        limiter.record(key)
        return None
    limiter.clear(key)
    if consume:
        conn.execute(text("UPDATE password_reset_otp SET used = TRUE WHERE otp_id = :o"), {"o": row["otp_id"]})
    return row

def _deliver_otp(email: str, code: str, purpose: str):
    if not send_otp_email(email, code, purpose=purpose):
        raise HTTPException(status_code=503, detail="We could not send the verification email right now. Please try again in a moment.")

                                                                            
@app.get("/")
def read_root():
    return {"status": "online", "message": "Masar Advisor API Engine"}

@app.get("/health")
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "healthy", "database": "connected"}
    except Exception:
        log.exception("Health check failed")
        raise HTTPException(status_code=503, detail="Database unavailable.")

@app.get("/system/config")
def system_config():
    return {
        "success": True, "supported_languages": ["en", "ar"], "default_language": "en",
        "plan_variants": PLAN_VARIANTS, "high_difficulty_threshold": HIGH_DIFFICULTY_THRESHOLD, "workload_is_hard_cap": True,
        "ai_explanations_enabled": ai_explanation.is_enabled(),
    }

@app.get("/courses")
def get_courses():
    courses_df = get_courses_df().sort_values("course_code").reset_index(drop=True)
    return {"success": True, "courses": records(courses_df)}

                                                                          
@app.post("/students/signup")
def signup(profile: StudentProfileRequest):
    """Direct account creation WITHOUT e-mail verification. Disabled by default:
    real users must use /students/signup/request-otp + /verify-otp. Enable only
    for local scripting with ALLOW_DIRECT_SIGNUP=true."""
    if os.getenv("ALLOW_DIRECT_SIGNUP", "false").strip().lower() not in {"1", "true", "yes"}:
        raise HTTPException(status_code=403, detail="Direct sign-up is disabled. Please sign up with e-mail verification.")
    email = _validate_signup_profile(profile)
    with engine.begin() as conn:
        _check_signup_conflict(conn, profile.student_id, email)
        _upsert_student(conn, profile)
        _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
    return _signup_response(profile)

@app.post("/students/signup/request-otp")
def signup_request_otp(profile: StudentProfileRequest):
    email = _validate_signup_profile(profile)
    if not limiter.allow(("otp-send", "signup", email), 3, 600):
        raise _too_many("Too many verification codes requested. Please wait a few minutes.")
    with engine.begin() as conn:
        _check_signup_conflict(conn, profile.student_id, email)
        pending = profile.model_dump()
        pending.pop("password", None)
        pending["password_hash"] = hash_password(profile.password)
        pending["email"] = email
        code = _create_otp(conn, "signup", email, payload=pending)
    _deliver_otp(email, code, "signup")
    return {"success": True, "message": "Verification code sent to your UAEU email."}

@app.post("/students/signup/verify-otp")
def signup_verify_otp(payload: SignupVerifyRequest):
    email = payload.email.strip().lower()
    with engine.begin() as conn:
        otp_row = _check_otp(conn, "signup", email, payload.otp_code)
        if not otp_row:
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        data = otp_row["payload"]
        if isinstance(data, str):
            data = json.loads(data)
        _check_signup_conflict(conn, data["student_id"], email)
        profile = StudentProfileRequest(**{k: v for k, v in data.items() if k != "password_hash"})
        _upsert_student(conn, profile)
        conn.execute(text("UPDATE student SET password_hash = :ph WHERE student_id = :sid"), {"ph": data["password_hash"], "sid": profile.student_id})
        _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
    return _signup_response(profile)

                                                                          
@app.post("/students/login")
def login(payload: LoginRequest):
    """Password check, then an e-mailed code for accounts that have an e-mail on file.
    The same generic error is returned for unknown accounts and wrong passwords."""
    identifier = payload.identifier.strip()
    key = ("login", identifier.lower())
    if not limiter.allow(key, 10, 300):
        raise _too_many("Too many sign-in attempts. Please wait a few minutes and try again.")
    with engine.connect() as conn:
        row = _find_student(conn, identifier)
        if not row:
            burn_password_check(payload.password)
            raise HTTPException(status_code=401, detail="Invalid username/email or password.")
        if not verify_password(payload.password, row.get("password_hash")):
            raise HTTPException(status_code=401, detail="Invalid username/email or password.")
        limiter.clear(key)
        email = (row.get("email") or "").strip()
        if not email:                                                       
            return {"success": True, "otp_required": False, "access_token": issue_token(row["student_id"]),
                    "student": _student_profile_from_row(row), "completed_courses": [dict(c) for c in _completed_rows(conn, row["student_id"])]}
    if not limiter.allow(("otp-send", "login", row["student_id"]), 3, 600):
        raise _too_many("Too many verification codes requested. Please wait a few minutes.")
    with engine.begin() as conn:
        code = _create_otp(conn, "login", row["student_id"], student_id=row["student_id"])
    _deliver_otp(email, code, "login")
    return {"success": True, "otp_required": True, "student_id": row["student_id"], "message": "A verification code has been sent to your registered email."}

@app.post("/students/login/verify-otp")
def login_verify_otp(payload: LoginVerifyRequest):
    ident = payload.identifier.strip()
    with engine.begin() as conn:
        row = _find_student(conn, ident)
        if not row:
            limiter.record(("otp-verify", "login", ident.lower()))
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        if not _check_otp(conn, "login", row["student_id"], payload.otp_code):
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        completed = _completed_rows(conn, row["student_id"])
    return {"success": True, "access_token": issue_token(row["student_id"]), "student": _student_profile_from_row(row), "completed_courses": [dict(c) for c in completed]}

                                                                          
@app.post("/students/forgot-password")
def forgot_password(payload: ForgotPasswordRequest):
    """Always returns the same message so it cannot be used to discover accounts."""
    identifier = payload.identifier.strip()
    if not identifier:
        raise HTTPException(status_code=400, detail="Enter your username or email.")
    generic = {"success": True, "message": "If the account exists, a verification code has been sent to the registered email."}
    with engine.begin() as conn:
        row = _find_student(conn, identifier)
        if not row or not row["email"]:
            return generic
        if not limiter.allow(("otp-send", "reset", row["student_id"]), 3, 600):
            return generic
        code = _create_otp(conn, "reset", row["student_id"], student_id=row["student_id"])
        email = row["email"]
    if not send_otp_email(email, code, purpose="reset"):
        log.error("Password-reset e-mail could not be delivered to a registered address.")
    return generic

@app.post("/students/verify-otp")
def verify_otp(payload: VerifyOtpRequest):
    ident = payload.identifier.strip()
    with engine.begin() as conn:
        student = _find_student(conn, ident)
        if not student:
            limiter.record(("otp-verify", "reset", ident.lower()))
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        if not _check_otp(conn, "reset", student["student_id"], payload.otp_code, consume=False):
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
    return {"success": True, "message": "Code verified."}

@app.post("/students/reset-password")
def reset_password(payload: ResetPasswordRequest):
    ident = payload.identifier.strip()
    with engine.begin() as conn:
        student = _find_student(conn, ident)
        if not student:
            limiter.record(("otp-verify", "reset", ident.lower()))
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        if not _check_otp(conn, "reset", student["student_id"], payload.otp_code):
            raise HTTPException(status_code=400, detail="Invalid or expired code.")
        conn.execute(text("UPDATE student SET password_hash = :ph WHERE student_id = :sid"), {"ph": hash_password(payload.new_password), "sid": student["student_id"]})
    return {"success": True, "message": "Password updated. You can now log in with your new password."}

                                                                          
@app.get("/students/{student_id}")
def get_student(student_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    with engine.connect() as conn:
        student_row = conn.execute(text("SELECT * FROM student WHERE student_id = :sid"), {"sid": student_id}).mappings().fetchone()
        if not student_row:
            raise HTTPException(status_code=404, detail="Student not found")
        completed = _completed_rows(conn, student_id)
        latest_rec = conn.execute(
            text("""SELECT recommendation_id, generated_date, total_workload, overall_risk_level, plan_summary
                    FROM recommendation WHERE student_id = :sid
                    ORDER BY generated_date DESC, recommendation_id DESC LIMIT 1"""), {"sid": student_id}).mappings().fetchone()
        rec_courses = []
        if latest_rec:
            rec_courses = conn.execute(
                text("""SELECT c.course_code, c.course_name, c.credits, c.difficulty_level, c.math_intensity,
                               c.weekly_workload, c.subject_area, c.assessment_type, rc.reason
                        FROM recommended_courses rc JOIN course c ON c.course_id = rc.course_id
                        WHERE rc.recommendation_id = :rid ORDER BY c.course_code"""), {"rid": latest_rec["recommendation_id"]}).mappings().all()
    return {"success": True, "student": _student_profile_from_row(student_row), "completed_courses": [dict(c) for c in completed],
            "latest_recommendation": dict(latest_rec) if latest_rec else None, "recommended_courses": [dict(r) for r in rec_courses]}

@app.get("/students/{student_id}/recommendation-history")
def recommendation_history(student_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    """Saved semester-plan decisions for the student's Active History view."""
    _require_student(credentials, student_id)
    with engine.connect() as conn:
        if not conn.execute(text("SELECT 1 FROM student WHERE student_id = :sid"), {"sid": student_id}).scalar():
            raise HTTPException(status_code=404, detail="Student not found")
        rows = conn.execute(
            text("""SELECT recommendation_id, generated_date, total_workload, overall_risk_level, plan_summary
                    FROM recommendation WHERE student_id = :sid
                    ORDER BY generated_date DESC, recommendation_id DESC LIMIT 20"""), {"sid": student_id}).mappings().all()
        history = []
        if rows:
            ids = [r["recommendation_id"] for r in rows]
            course_rows = conn.execute(
                text("""SELECT rc.recommendation_id, c.course_code, c.course_name, c.credits, rc.reason
                        FROM recommended_courses rc JOIN course c ON c.course_id = rc.course_id
                        WHERE rc.recommendation_id = ANY(:ids) ORDER BY rc.recommendation_id DESC, c.course_code"""), {"ids": ids}).mappings().all()
            by_rec = {rid: [] for rid in ids}
            for c in course_rows:
                by_rec[c["recommendation_id"]].append({"course_code": c["course_code"], "course_name": c["course_name"], "credits": c["credits"], "reason": c["reason"]})
            history = [{**dict(row), "courses": by_rec.get(row["recommendation_id"], [])} for row in rows]
    return {"success": True, "history": history}

@app.put("/students/{student_id}")
def update_student(student_id: str, profile: StudentProfileRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    if profile.student_id != student_id:
        raise HTTPException(status_code=400, detail="Student ID in the body must match the URL.")
    if profile.email is not None and not _is_allowed_email(profile.email):
        raise HTTPException(status_code=400, detail=_email_domain_error())
    if profile.password:
        _validate_password(profile.password)
    with engine.begin() as conn:
        if not conn.execute(text("SELECT 1 FROM student WHERE student_id = :sid"), {"sid": student_id}).scalar():
            raise HTTPException(status_code=404, detail="Student not found.")
        _upsert_student(conn, profile)
        _sync_completed_courses(conn, student_id, profile.completed_courses, profile.completed_grades)
        updated_row = conn.execute(text("SELECT * FROM student WHERE student_id = :sid"), {"sid": student_id}).mappings().fetchone()
    return {"success": True, "message": "Profile and completed courses updated.", "student": _student_profile_from_row(updated_row),
            "completed_courses": [normalize_course_code(c) for c in profile.completed_courses], "completed_grades": profile.completed_grades}

@app.post("/plans/save")
def save_manual_plan(payload: ManualPlanRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, payload.student_id)
    codes = list(dict.fromkeys(normalize_course_code(c) for c in payload.course_codes if str(c).strip()))
    label = re.sub(r"[^\w \-]", "", payload.plan_label).strip()[:40] or "Custom"
    with engine.begin() as conn:
        student = conn.execute(text("SELECT student_id, workload_tolerance FROM student WHERE student_id = :sid"), {"sid": payload.student_id}).mappings().fetchone()
        if not student:
            raise HTTPException(status_code=404, detail="Student not found.")
        rows = conn.execute(text("SELECT * FROM course WHERE course_code = ANY(:codes)"), {"codes": codes}).mappings().all() if codes else []
        missing = [c for c in codes if c not in {r["course_code"] for r in rows}]
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown course code(s): {', '.join(missing)}")
        completed_codes = [r["course_code"] for r in _completed_rows(conn, payload.student_id)]
        passed = [c for c in codes if c in completed_codes]
        if passed:
            raise HTTPException(status_code=400, detail=f"These courses are already passed and cannot be added: {', '.join(passed)}")
        problems = validate_plan_eligibility(codes, completed_codes)
        if problems:
            raise HTTPException(status_code=400, detail="Prerequisites not met: " + " ".join(problems))
        tolerance = int(student["workload_tolerance"] or 30)
        total_workload = sum(int(r["weekly_workload"] or 0) for r in rows)
        if total_workload > tolerance:
            raise HTTPException(status_code=400, detail=f"This custom plan requires {total_workload} hrs/week, above your {tolerance} hrs/week workload tolerance.")
        if sum(1 for r in rows if int(r["difficulty_level"] or 0) >= 4) > 2:
            raise HTTPException(status_code=400, detail="A semester plan cannot contain more than 2 high-difficulty courses.")
        rec_id = conn.execute(
            text("""INSERT INTO recommendation (student_id, total_workload, overall_risk_level, plan_summary)
                    VALUES (:sid, :w, :risk, :summary) RETURNING recommendation_id"""),
            {"sid": payload.student_id, "w": total_workload, "risk": compute_risk_level(total_workload, tolerance), "summary": f"{label} Plan ({len(rows)} Courses)"}).scalar()
        if rows:
            conn.execute(text("INSERT INTO recommended_courses (recommendation_id, course_id, reason) VALUES (:rid, :cid, :reason)"),
                         [{"rid": rec_id, "cid": r["course_id"], "reason": "Manually selected by the student from the course catalog."} for r in rows])
    return {"success": True, "recommendation_id": rec_id, "saved_courses": codes}

                                                                           
@app.put("/courses/{course_code}/rating")
def rate_course(course_code: str, payload: CourseRatingRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, payload.student_id)
    code = normalize_course_code(course_code)
    if normalize_course_code(payload.course_code) != code:
        raise HTTPException(status_code=400, detail="Course code in the body must match the URL.")
    with engine.begin() as conn:
        course = conn.execute(text("SELECT course_id FROM course WHERE course_code = :code"), {"code": code}).scalar()
        if not course:
            raise HTTPException(status_code=404, detail="Course not found.")
        if not conn.execute(text("SELECT 1 FROM completed_courses WHERE student_id = :sid AND course_id = :cid"), {"sid": payload.student_id, "cid": course}).scalar():
            raise HTTPException(status_code=400, detail="Only completed courses can be rated.")
        conn.execute(
            text("""INSERT INTO course_ratings (student_id, course_id, difficulty_rating, workload_rating, comment)
                    VALUES (:sid, :cid, :d, :w, :c)
                    ON CONFLICT (student_id, course_id) DO UPDATE SET difficulty_rating = EXCLUDED.difficulty_rating,
                        workload_rating = EXCLUDED.workload_rating, comment = EXCLUDED.comment, updated_at = CURRENT_TIMESTAMP"""),
            {"sid": payload.student_id, "cid": course, "d": payload.difficulty_rating, "w": payload.workload_rating, "c": payload.comment})
    return {"success": True, "message": "Course rating saved."}

@app.get("/students/{student_id}/ratings")
def get_ratings(student_id: str, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, student_id)
    with engine.connect() as conn:
        rows = conn.execute(
            text("""SELECT c.course_code, cr.difficulty_rating, cr.workload_rating, cr.comment
                    FROM course_ratings cr JOIN course c ON c.course_id = cr.course_id
                    WHERE cr.student_id = :sid ORDER BY c.course_code"""), {"sid": student_id}).mappings().all()
    return {"success": True, "ratings": [dict(r) for r in rows]}

                                                                            
@app.post("/recommend/preview")
def preview_plans(profile: StudentProfileRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    """Compute the three plans without saving anything. Requires sign-in
    (it can trigger AI calls, so it must not be open to anonymous traffic)."""
    _require_student(credentials, profile.student_id)
    return {"success": True, "plans": generate_all_plans(_student_data(profile), profile.completed_courses)}

@app.post("/recommend")
def get_recommendation(profile: StudentProfileRequest, credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)):
    _require_student(credentials, profile.student_id)
    if profile.plan_type not in PLAN_VARIANTS:
        raise HTTPException(status_code=400, detail=f"plan_type must be one of {list(PLAN_VARIANTS.keys())}")
    cfg = PLAN_VARIANTS[profile.plan_type]
    recs_df, excluded, message = generate_recommendations(
        _student_data(profile), profile.completed_courses,
        credit_target_max=cfg["credit_target_max"], max_high_difficulty=cfg["max_high_difficulty"],
        workload_multiplier=cfg["workload_multiplier"], plan_label=profile.plan_type.capitalize(),
        use_ai=True, workload_target_share=cfg["workload_target_share"],
    )
    with engine.begin() as conn:
        _upsert_student(conn, profile)
        _sync_completed_courses(conn, profile.student_id, profile.completed_courses, profile.completed_grades)
        if recs_df.empty:
            return {"success": False, "message": message, "recommendations": [], "excluded": excluded}
        recs = records(recs_df)
        rec_id = save_recommendation_to_db(conn, profile.student_id, recs, plan_label=profile.plan_type.capitalize(), workload_tolerance=profile.workload_tolerance)
    total_workload = int(sum(r["weekly_workload"] or 0 for r in recs))
    return {"success": True, "message": message, "recommendation_id": rec_id, "plan_type": profile.plan_type, "recommendations": recs,
            "excluded": excluded, "total_credits": int(sum(r["credits"] or 0 for r in recs)), "total_workload": total_workload,
            "risk_level": compute_risk_level(total_workload, profile.workload_tolerance)}
