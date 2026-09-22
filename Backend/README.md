# Masar Backend

FastAPI backend and rule-based recommendation engine for Masar (AI-powered academic advisor).

## What it does

- PostgreSQL persistence, PBKDF2 password hashing, signed bearer tokens
- UAEU e-mail + 9-digit Student ID validation, privacy-consent storage
- E-mail OTP for sign-up, login and password reset (Resend or SMTP)
- Course catalog (58 courses) with prerequisites, **co-requisites, OR-alternatives and credit-hour rules**
- Deterministic recommender: Safer / Balanced / Advanced plans, hard workload cap, difficulty and math limits
- Explanations for every recommended **and** every excluded course
- Optional AI wording of the explanations (one batched, cached request per page load)
- Recommendation history, hand-made plans (prerequisite-checked), course ratings
- Syllabus extractor (TXT/PDF -> Excel dataset)

## Setup

```bash
python -m venv venv
venv\Scripts\activate          # Windows      (macOS/Linux: source venv/bin/activate)
python -m pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
```

Edit `.env` (at least `DATABASE_URL` and `AUTH_SECRET`), then load the catalog and start the API:

```bash
python seed_db.py              # creates/updates tables and loads the course dataset
uvicorn main:app --reload --port 8000
```

`seed_db.py` refuses to delete more than half of the existing catalog (deleting courses also deletes students'
completed courses); use `python seed_db.py --force` if you really mean it.

## Prerequisite notation (dataset column `Prerequisites`)

| Text | Meaning |
|------|---------|
| `MATH105` | must be completed |
| `CSBP121, CSBP219 (co)` | CSBP121 completed; CSBP219 may be taken **in the same semester** |
| `ITBP301 or ITBP280` | either one |
| `CENG205 (co/pre) & PHYS105` | CENG205 completed or concurrent, and PHYS105 completed |
| `Minimum 80 completed credit hours` | credit-hour threshold |

Courses that need each other (e.g. Design of Security Protocols + Cryptography Lab) are always recommended as a pair.

## Adding courses from syllabi

```bash
python extractor.py syllabus1.txt syllabus2.pdf     # updates masar_course_dataset.xlsx
python seed_db.py
```
The extractor is heuristic - review the new Excel rows (flags such as `Has_Math`, grading percentages).

## AI explanations (optional)

Set `AI_EXPLANATION_ENABLED=true` and `AI_API_KEY`. One request explains all courses of a page load, retries on
HTTP 429/5xx, is cached in memory and in the `ai_explanation_cache` table, and pauses itself if the provider is down.
Anything that fails validation falls back to the built-in sentence. `GET /system/config` reports whether it is on.

## Tests

Use a **throw-away** database - the tests seed it and create/delete test students. They never read `DATABASE_URL`.

```bash
python -m pip install -r requirements-dev.txt
set MASAR_TEST_DATABASE_URL=postgresql://user:pass@localhost/masar_test     # Windows (macOS/Linux: export ...)
python -m pytest
```
Without `MASAR_TEST_DATABASE_URL` only the database-free tests run.

Other tools: `python generate_synthetic_students.py 200 --seed 1` then `--benchmark` (NFR 1.3), `--cleanup` removes them.
`python performance_test.py` times the public endpoints.

## API overview

| Method | Path | Notes |
|---|---|---|
| GET | `/health`, `/system/config`, `/courses` | public |
| POST | `/students/signup/request-otp`, `/students/signup/verify-otp` | e-mail verified sign-up |
| POST | `/students/login`, `/students/login/verify-otp` | password, then e-mailed code |
| POST | `/students/forgot-password`, `/students/verify-otp`, `/students/reset-password` | password reset |
| GET/PUT | `/students/{id}` | own profile only |
| GET | `/students/{id}/recommendation-history`, `/students/{id}/ratings` | own data only |
| POST | `/recommend/preview` | 3 plans, nothing saved (sign-in required) |
| POST | `/recommend` | one plan, saved to history |
| POST | `/plans/save` | hand-made plan; prerequisites, workload and difficulty checked |
| PUT | `/courses/{code}/rating` | only for completed courses |
| POST | `/students/signup` | **disabled** unless `ALLOW_DIRECT_SIGNUP=true` (skips e-mail verification) |

## Security notes

- Never commit or share `.env`. Set a strong `AUTH_SECRET`; use HTTPS in production.
- OTP codes are stored as keyed hashes, expire after 10 minutes, are single-use, and are limited to 5 wrong attempts
  per 10 minutes. Rate limits live in process memory: use a gateway/Redis limit if you run several server processes.
- Keep `EMAIL_DEV_CONSOLE=false` in production so codes never appear in logs.

### Recommendation rules configuration (NFR 6.1)
Recommendation thresholds, workload defaults, plan variants, math-cap rules, and scoring constants are stored in `config/recommendation_rules.json`. The recommendation engine loads this file at startup instead of hard-coding these system rules in Python.
