from pathlib import Path
import re
import pandas as pd
from sqlalchemy import text
from db import engine, run_schema
from prereq import normalize_code as _normalize_code, parse_requirement

BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR / "masar_course_dataset.xlsx"

def normalize_code(value) -> str:
    return _normalize_code(value)

def _num(value, default=0.0) -> float:
    try:
        v = float(value)
        return default if v != v else v                  
    except (TypeError, ValueError):
        return default

def normalize_yes_no(value) -> str:
    if pd.isna(value):
        return "No"
    value = str(value).strip().lower()
    return "Yes" if value.startswith("yes") else "No"

def subject_area(course_code: str) -> str:
    prefix = re.match(r"[A-Z]+", course_code or "")
    return {
        "ISEC": "Information Security",
        "CSBP": "Computer Science",
        "ITBP": "Information Technology",
        "SWEB": "Software Engineering",
        "CENG": "Computer Engineering",
        "MATH": "Mathematics",
        "STAT": "Mathematics",
        "PHYS": "Physics",
        "BIOC": "Biology",
        "CHEM": "Chemistry",
        "GEIT": "General Education",
        "GESU": "General Education",
        "ESPU": "English & Communication",
        "HSS": "Humanities & Social Science",
        "ISLM": "Humanities & Social Science",
        "AGRB": "Humanities & Social Science",
        "ECON": "Humanities & Social Science",
        "HSR": "Humanities & Social Science",
        "PSY": "Humanities & Social Science",
        "GEO": "Humanities & Social Science",
        "GHEP": "Humanities & Social Science",
        "ARCH": "Humanities & Social Science",
        "PHI": "Humanities & Social Science",
        "HIS": "Humanities & Social Science",
    }.get(prefix.group(0) if prefix else "", "General")

def derive_difficulty(row) -> int:
    level = int(_num(row.get("Course_Level"), 100))
    assessments = int(_num(row.get("Number_Major_Assessments"), 0))
    problem_solving = normalize_yes_no(row.get("Problem_Solving")) == "Yes"
    base = min(5, max(1, level // 100))
    bonus = 1 if assessments >= 5 else 0
    if problem_solving and base < 3 and assessments >= 4:
        bonus = 1
    return min(5, max(1, base + bonus))

def derive_math_intensity(row) -> int:
    return 4 if normalize_yes_no(row.get("Has_Math")) == "Yes" else 1

def derive_weekly_workload(row) -> int:
    credits = _num(row.get("Credit_Hours"), 3)
    assessments = _num(row.get("Number_Major_Assessments"), 0)
    group_work = normalize_yes_no(row.get("Group_Work_Required")) == "Yes"
    workload = credits * 2 + assessments * 0.5 + (1 if group_work else 0)
    return max(1, int(round(workload)))

def clean_prerequisite_text(value) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()

def prepare_courses(df: pd.DataFrame) -> pd.DataFrame:
    df = df.dropna(subset=["Course_Code", "Course_Name"]).copy()
    df["course_code"] = df["Course_Code"].map(normalize_code)
    df["course_name"] = df["Course_Name"].astype(str).str.strip()
    df["credits"] = pd.to_numeric(df["Credit_Hours"], errors="coerce").fillna(3).round().astype(int)
    df["subject_area"] = df["course_code"].map(subject_area)
    df["difficulty_level"] = df.apply(derive_difficulty, axis=1)
    df["math_intensity"] = df.apply(derive_math_intensity, axis=1)
    df["weekly_workload"] = df.apply(derive_weekly_workload, axis=1)
    df["assessment_type"] = df.apply(
        lambda r: "Exams + Projects" if normalize_yes_no(r.get("Does the course rely more on exams?")) == "Yes" else "Mixed",
        axis=1,
    )
    df["prerequisite_text"] = df["Prerequisites"].map(clean_prerequisite_text)
    df["prerequisite_names"] = df["Prerequisite_Names"].map(clean_prerequisite_text)
    df["theory_based"] = df["Theory_Based"].map(normalize_yes_no)
    df["problem_solving"] = df["Problem_Solving"].map(normalize_yes_no)
    df["has_math"] = df["Has_Math"].map(normalize_yes_no)
    df["has_programming"] = df["Has_Programming"].map(normalize_yes_no)
    df["course_level"] = pd.to_numeric(df["Course_Level"], errors="coerce").fillna(100).round().astype(int)
    df["number_major_assessments"] = pd.to_numeric(df["Number_Major_Assessments"], errors="coerce").fillna(0).round().astype(int)
    df["group_work_required"] = df["Group_Work_Required"].map(normalize_yes_no)
    for source, target in [
        ("Quiz_percentage", "quiz_percentage"),
        ("Assignment_Project_percentage", "assignment_project_percentage"),
        ("Midterm_percentage", "midterm_percentage"),
        ("Final _exam_percentage", "final_exam_percentage"),
    ]:
        df[target] = pd.to_numeric(df[source], errors="coerce").fillna(0.0)
    df["exam_heavy"] = df["Does the course rely more on exams?"].map(normalize_yes_no)
    return df

def apply_schema():
    run_schema()

def migrate_course_columns():
    additions = {
        "prerequisite_text": "TEXT",
        "prerequisite_names": "TEXT",
        "theory_based": "VARCHAR(10)",
        "problem_solving": "VARCHAR(10)",
        "has_math": "VARCHAR(10)",
        "has_programming": "VARCHAR(10)",
        "course_level": "INT",
        "number_major_assessments": "INT",
        "group_work_required": "VARCHAR(10)",
        "quiz_percentage": "NUMERIC(5,4)",
        "assignment_project_percentage": "NUMERIC(5,4)",
        "midterm_percentage": "NUMERIC(5,4)",
        "final_exam_percentage": "NUMERIC(5,4)",
        "exam_heavy": "VARCHAR(10)",
    }
    with engine.begin() as conn:
        for column, definition in additions.items():
            conn.execute(text(f"ALTER TABLE course ADD COLUMN IF NOT EXISTS {column} {definition}"))

def seed_courses(course_df: pd.DataFrame) -> dict:
    code_to_id = {}
    with engine.begin() as conn:
        for _, row in course_df.iterrows():
            params = row.to_dict()
            result = conn.execute(
                text("""
                    INSERT INTO course (
                        course_code, course_name, credits, subject_area,
                        difficulty_level, math_intensity, weekly_workload, assessment_type,
                        prerequisite_text, prerequisite_names, theory_based, problem_solving, has_math,
                        has_programming, course_level, number_major_assessments,
                        group_work_required, quiz_percentage, assignment_project_percentage,
                        midterm_percentage, final_exam_percentage, exam_heavy
                    ) VALUES (
                        :course_code, :course_name, :credits, :subject_area,
                        :difficulty_level, :math_intensity, :weekly_workload, :assessment_type,
                        :prerequisite_text, :prerequisite_names, :theory_based, :problem_solving, :has_math,
                        :has_programming, :course_level, :number_major_assessments,
                        :group_work_required, :quiz_percentage, :assignment_project_percentage,
                        :midterm_percentage, :final_exam_percentage, :exam_heavy
                    )
                    ON CONFLICT (course_code) DO UPDATE SET
                        course_name = EXCLUDED.course_name,
                        credits = EXCLUDED.credits,
                        subject_area = EXCLUDED.subject_area,
                        difficulty_level = EXCLUDED.difficulty_level,
                        math_intensity = EXCLUDED.math_intensity,
                        weekly_workload = EXCLUDED.weekly_workload,
                        assessment_type = EXCLUDED.assessment_type,
                        prerequisite_text = EXCLUDED.prerequisite_text,
                        prerequisite_names = EXCLUDED.prerequisite_names,
                        theory_based = EXCLUDED.theory_based,
                        problem_solving = EXCLUDED.problem_solving,
                        has_math = EXCLUDED.has_math,
                        has_programming = EXCLUDED.has_programming,
                        course_level = EXCLUDED.course_level,
                        number_major_assessments = EXCLUDED.number_major_assessments,
                        group_work_required = EXCLUDED.group_work_required,
                        quiz_percentage = EXCLUDED.quiz_percentage,
                        assignment_project_percentage = EXCLUDED.assignment_project_percentage,
                        midterm_percentage = EXCLUDED.midterm_percentage,
                        final_exam_percentage = EXCLUDED.final_exam_percentage,
                        exam_heavy = EXCLUDED.exam_heavy
                    RETURNING course_id, course_code
                """),
                params,
            )
            course_id, course_code = result.fetchone()
            code_to_id[course_code] = course_id
    print(f"Seeded/updated {len(code_to_id)} courses from the new dataset.")
    return code_to_id

def replace_old_courses(course_codes: list[str], force: bool = False):
    """Delete courses that are no longer in the dataset.

    Deleting a course cascades to completed_courses / ratings / saved plans, so a
    truncated Excel file could silently wipe student data. Refuse to remove more
    than half of the catalog unless --force is given."""
    if not course_codes:
        return
    with engine.begin() as conn:
        existing = conn.execute(text("SELECT COUNT(*) FROM course")).scalar() or 0
        stale = conn.execute(text("SELECT COUNT(*) FROM course WHERE course_code <> ALL(:codes)"), {"codes": course_codes}).scalar() or 0
        if stale and existing and stale > existing / 2 and not force:
            print(f"SAFETY STOP: {stale} of {existing} existing courses are missing from the dataset. "
                  "Not deleting them (this would also delete students' completed courses). Re-run with --force if intended.")
            return
        result = conn.execute(text("DELETE FROM course WHERE course_code <> ALL(:codes)"), {"codes": course_codes})
    print(f"Removed {result.rowcount} course(s) not present in the new dataset.")

def seed_prerequisites(course_df: pd.DataFrame, code_to_id: dict):
    """Store prerequisite links with their meaning (pre / co, and OR-group number).
    The recommender reads the text via prereq.parse_requirement; this table is the
    relational (ER diagram) view of the same information."""
    inserted = 0
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM course_prerequisites"))
        for _, row in course_df.iterrows():
            course_id = code_to_id.get(row["course_code"])
            if course_id is None:
                continue
            req = parse_requirement(row.get("prerequisite_text"))
            for group_no, group in enumerate(req.groups, start=1):
                for code, kind in group:
                    prereq_id = code_to_id.get(code)
                    if prereq_id is None or prereq_id == course_id:
                        continue
                    conn.execute(
                        text("""
                            INSERT INTO course_prerequisites (course_id, prerequisite_course_id, relation_type, alt_group)
                            VALUES (:course_id, :prereq_id, :kind, :grp)
                            ON CONFLICT (course_id, prerequisite_course_id) DO NOTHING
                        """),
                        {"course_id": course_id, "prereq_id": prereq_id, "kind": kind, "grp": group_no},
                    )
                    inserted += 1
    print(f"Linked {inserted} prerequisite relationships found within the dataset.")

def seed_database(force: bool = False):
    apply_schema()
    migrate_course_columns()
    raw_df = pd.read_excel(EXCEL_PATH)
    course_df = prepare_courses(raw_df)
    if course_df.empty:
        raise ValueError("The new Excel dataset contains no valid courses.")
    code_to_id = seed_courses(course_df)
    replace_old_courses(list(code_to_id.keys()), force=force)
    seed_prerequisites(course_df, code_to_id)
    print(f"New dataset loaded successfully: {len(course_df)} courses.")

if __name__ == "__main__":
    import sys
    seed_database(force="--force" in sys.argv)
