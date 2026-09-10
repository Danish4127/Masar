# Masar Backend

FastAPI backend and recommendation engine for Masar.

## Features

- PostgreSQL persistence
- Student registration and signed bearer authentication
- UAEU email and nine-digit Student ID validation
- PBKDF2 password hashing
- Privacy-consent storage
- Completed-course and passing-grade validation
- Course catalog and prerequisite data
- Course difficulty/workload ratings
- Rule-based recommendation and plan generation
- Safer, Balanced and Advanced plan variants
- Recommendation history and saved plans
- PDF/TXT syllabus extraction
- Email OTP password reset with Resend or SMTP
- Automated recommendation tests

## Setup

```bash
python -m venv venv

# Windows
venv\Scripts\activate

# macOS/Linux
source venv/bin/activate

python -m pip install -r requirements.txt
copy .env.example .env
```

Configure the database, frontend origins, authentication secret and email provider in `.env`.

## Run

```bash
uvicorn main:app --reload --port 8000
```

## Data setup

The repository includes the 58-course dataset and database schema. Use `seed_db.py` to load the course data into PostgreSQL.

## Tests

```bash
python test_recommender.py
```

## API overview

- `GET /health`
- `GET /courses`
- `POST /students/signup`
- `POST /students/login`
- `POST /students/forgot-password`
- `POST /students/verify-otp`
- `POST /students/reset-password`
- `GET /students/{student_id}`
- `PUT /students/{student_id}`
- `GET /students/{student_id}/recommendation-history`
- `POST /recommend`
- `POST /recommend/preview`
- `POST /plans/save`
- `PUT /courses/{course_code}/rating`
- `GET /students/{student_id}/ratings`

## Security

Keep `.env` out of version control. Use a strong `AUTH_SECRET` and HTTPS in production.
