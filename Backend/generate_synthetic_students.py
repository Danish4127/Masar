"""
Synthetic student data generator (scalability demo).

Inserts N fake students directly into the database (bypassing the OTP-based
signup flow entirely, since these are bulk demo accounts, not real users).
Useful for showing the system handles NFR 5.1 (500 concurrent students) and
for timing NFR 1.3 (50-student batch in under 30 seconds).

Synthetic students:
  - Use student IDs in the 999xxxxxx range so they're always easy to find
    and clean up separately from real UAEU student IDs.
  - Have NO email on file, so they log in directly without an OTP step
    (see main.py's /students/login: accounts without an email skip OTP).
  - Share one fixed password for convenience: Test@1234
  - Get a random GPA, confidence levels, workload tolerance, major, and a
    random set of "completed" courses (with valid passing grades) pulled
    from whatever is currently in the `course` table.

Usage:
    python generate_synthetic_students.py            # inserts 200 students
    python generate_synthetic_students.py 500         # inserts 500 students
    python generate_synthetic_students.py --cleanup   # deletes ALL synthetic students
    python generate_synthetic_students.py --benchmark # times recommendation generation for existing synthetic students
    add  --seed 42  for reproducible data,  --yes  to skip the safety prompt

SAFETY: synthetic accounts share a KNOWN password, so never leave them in a real / production
database. The script asks for confirmation unless the database is on localhost (or --yes is given),
and --cleanup removes them all.
"""

import random
import sys
import time

from sqlalchemy import text

from db import DATABASE_URL, engine
from prereq import normalize_code as normalize_course_code
from prereq import parse_requirement
from recommender import generate_recommendations
from security import hash_password as _hash_password

SYNTHETIC_ID_PREFIX = "999"                                                       
SYNTHETIC_PASSWORD = "Test@1234"                                                 
MAJORS = ["Computer Science", "Information Security", "Information Technology", "Software Engineering"]
GRADES = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D+", "D"]

FIRST_NAMES = [
    "Ahmed", "Mohammed", "Ali", "Omar", "Khalid", "Saeed", "Rashid", "Hamdan",
    "Fatima", "Aisha", "Maryam", "Salama", "Shamma", "Alya", "Hessa", "Reem",
    "Yousef", "Sultan", "Zayed", "Hamad", "Noora", "Mariam", "Latifa", "Amna",
]
LAST_NAMES = [
    "Al-Mansoori", "Al-Shamsi", "Al-Suwaidi", "Al-Kaabi", "Al-Nuaimi",
    "Al-Zaabi", "Al-Blooshi", "Al-Marzooqi", "Al-Hosani", "Al-Dhaheri",
]

def _random_student_id(offset: int) -> str:
                                                    
    return f"{SYNTHETIC_ID_PREFIX}{offset:06d}"

def _random_completed_courses(conn, count: int) -> dict[str, str]:
    """Random passing history that respects prerequisites (a student who passed a
    400-level course also passed what it requires), so benchmarks use realistic profiles."""
    rows = conn.execute(text("SELECT course_code, prerequisite_text FROM course ORDER BY course_code")).mappings().all()
    reqs = {normalize_course_code(r["course_code"]): parse_requirement(r["prerequisite_text"]) for r in rows}
    done: set[str] = set()
    codes = sorted(reqs)
    for _ in range(count * 6):
        if len(done) >= count:
            break
        code = random.choice(codes)
        req = reqs[code]
        if code in done or req.min_credits:
            continue
                                                                                    
        if all(any(c in done for c, _ in g) or all(k == "co" for _, k in g) for g in req.groups):
            done.add(code)
    return {code: random.choice(GRADES) for code in done}

def generate(n: int):
    password_hash = _hash_password(SYNTHETIC_PASSWORD)
    created = 0
    t0 = time.time()

    with engine.begin() as conn:
        existing_max = conn.execute(
            text("SELECT COALESCE(MAX(CAST(SUBSTRING(student_id FROM 4) AS INT)), 0) FROM student WHERE student_id ~ :pattern"),
            {"pattern": f"^{SYNTHETIC_ID_PREFIX}[0-9]{{6}}$"},
        ).scalar() or 0
        start_offset = existing_max + 1

        for i in range(start_offset, start_offset + n):
            student_id = _random_student_id(i)
            full_name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
            gpa = round(random.uniform(2.0, 4.0), 2)
            math_confidence = random.randint(1, 5)
            programming_confidence = random.randint(1, 5)
            workload_tolerance = random.randint(10, 50)
            major = random.choice(MAJORS)

            inserted = conn.execute(
                text("""
                    INSERT INTO student (
                        student_id, email, full_name, major, gpa, math_confidence,
                        programming_confidence, workload_tolerance, password_hash,
                        privacy_consent, privacy_consent_at
                    ) VALUES (
                        :student_id, NULL, :full_name, :major, :gpa, :math_conf,
                        :prog_conf, :workload_tol, :password_hash, TRUE, NOW()
                    )
                    ON CONFLICT (student_id) DO NOTHING
                """),
                {
                    "student_id": student_id, "full_name": full_name, "major": major,
                    "gpa": gpa, "math_conf": math_confidence, "prog_conf": programming_confidence,
                    "workload_tol": workload_tolerance, "password_hash": password_hash,
                },
            ).rowcount
            if not inserted:
                continue

            grades = _random_completed_courses(conn, random.randint(0, 8))
            if grades:
                rows = conn.execute(
                    text("SELECT course_id, course_code FROM course WHERE course_code = ANY(:codes)"),
                    {"codes": list(grades.keys())},
                ).mappings().all()
                conn.execute(
                    text("""
                        INSERT INTO completed_courses (student_id, course_id, grade)
                        VALUES (:sid, :course_id, :grade)
                        ON CONFLICT DO NOTHING
                    """),
                    [{"sid": student_id, "course_id": row["course_id"], "grade": grades[normalize_course_code(row["course_code"])]} for row in rows],
                )
            created += 1

    elapsed = time.time() - t0
    print(f"Created {created} synthetic students in {elapsed:.2f}s (student_id range: {SYNTHETIC_ID_PREFIX}{start_offset:06d}-{SYNTHETIC_ID_PREFIX}{start_offset+n-1:06d})")
    print(f"All synthetic students share the password: {SYNTHETIC_PASSWORD}")

def cleanup():
    with engine.begin() as conn:
        deleted = conn.execute(
            text("DELETE FROM student WHERE student_id LIKE :prefix"),
            {"prefix": f"{SYNTHETIC_ID_PREFIX}%"},
        ).rowcount
    print(f"Deleted {deleted} synthetic students (completed_courses/recommendations cascade-deleted too).")

def benchmark():
    """Times how long it takes to generate a recommendation for every
    synthetic student currently in the database -- evidence for NFR 1.3
    (50 students / 30s) and NFR 5.1 (handles up to 500 students)."""
    with engine.connect() as conn:
        students = conn.execute(
            text("SELECT student_id, gpa, major, math_confidence, programming_confidence, workload_tolerance FROM student WHERE student_id LIKE :prefix"),
            {"prefix": f"{SYNTHETIC_ID_PREFIX}%"},
        ).mappings().all()
        if not students:
            print("No synthetic students found. Run `python generate_synthetic_students.py` first.")
            return

        completed_by_student: dict[str, list[str]] = {}
        for row in students:
            codes = conn.execute(
                text("""
                    SELECT c.course_code FROM completed_courses cc
                    JOIN course c ON c.course_id = cc.course_id
                    WHERE cc.student_id = :sid
                """),
                {"sid": row["student_id"]},
            ).scalars().all()
            completed_by_student[row["student_id"]] = [normalize_course_code(c) for c in codes]

    print(f"Benchmarking recommendation generation for {len(students)} synthetic students...")
    t0 = time.time()
    for row in students:
        student_data = {
            "gpa": float(row["gpa"]),
            "math_confidence": row["math_confidence"],
            "programming_confidence": row["programming_confidence"],
            "workload_tolerance": row["workload_tolerance"],
            "major": row["major"],
        }
        generate_recommendations(student_data, completed_by_student[row["student_id"]])
    elapsed = time.time() - t0

    print(f"Generated recommendations for {len(students)} students in {elapsed:.2f}s "
          f"({elapsed / len(students) * 1000:.0f}ms per student on average).")
    if len(students) >= 50:
        first_50_elapsed = elapsed / len(students) * 50
        verdict = "PASS" if first_50_elapsed <= 30 else "FAIL"
        print(f"NFR 1.3 check (50 students in <=30s, extrapolated): {first_50_elapsed:.2f}s -> {verdict}")

def _confirm_safe_target(args: list[str]) -> bool:
    if "--yes" in args or any(h in (DATABASE_URL or "") for h in ("localhost", "127.0.0.1", "@db:")):
        return True
    print("The target database is NOT on localhost. Synthetic accounts use a known password and must not live in a real database.")
    return input("Type YES to continue anyway: ").strip() == "YES"

if __name__ == "__main__":
    args = sys.argv[1:]
    if "--seed" in args:
        random.seed(int(args[args.index("--seed") + 1]))
    if "--cleanup" in args:
        cleanup()
    elif "--benchmark" in args:
        benchmark()
    else:
        if not _confirm_safe_target(args):
            sys.exit("Aborted.")
        count = next((int(a) for a in args if a.isdigit() and args.index(a) == 0), 200)
        generate(count)
