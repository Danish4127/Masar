"""
Recommendation engine test suite.

Fulfils NFR 7.4 from the SGP1 report: "The system should be tested on at
least 20 different student profiles before final launch." This script runs
the recommendation engine against 20 varied synthetic student profiles and
checks the hard constraints (NFR 7.2, FR 3.2, FR 4.1, FR 4.3) hold for every
one of them.

Requires a working DATABASE_URL (Neon) with the schema + course dataset
already loaded via `python seed_db.py`.

Run with: python test_recommender.py
"""

from sqlalchemy import text
from db import engine
from recommender import generate_recommendations, generate_all_plans, PLAN_VARIANTS

                                                                            
                                                   
TEST_PROFILES = [
    {"gpa": 3.9, "math_confidence": 5, "programming_confidence": 5, "workload_tolerance": 45, "completed": ["ITBP101", "CSBP101", "CSBP102"]},
    {"gpa": 2.1, "math_confidence": 1, "programming_confidence": 1, "workload_tolerance": 10, "completed": []},
    {"gpa": 3.2, "math_confidence": 3, "programming_confidence": 4, "workload_tolerance": 25, "completed": ["ITBP101", "CSBP101", "CSBP102"]},
    {"gpa": 2.8, "math_confidence": 2, "programming_confidence": 3, "workload_tolerance": 20, "completed": ["ITBP101"]},
    {"gpa": 3.5, "math_confidence": 4, "programming_confidence": 2, "workload_tolerance": 30, "completed": ["CSBP101"]},
    {"gpa": 2.5, "math_confidence": 3, "programming_confidence": 3, "workload_tolerance": 15, "completed": []},
    {"gpa": 4.0, "math_confidence": 5, "programming_confidence": 4, "workload_tolerance": 50, "completed": ["ITBP101", "CSBP101", "CSBP102", "ISEC312"]},
    {"gpa": 1.9, "math_confidence": 1, "programming_confidence": 2, "workload_tolerance": 10, "completed": []},
    {"gpa": 3.0, "math_confidence": 2, "programming_confidence": 5, "workload_tolerance": 22, "completed": ["ITBP101", "CSBP102"]},
    {"gpa": 3.7, "math_confidence": 4, "programming_confidence": 4, "workload_tolerance": 35, "completed": ["ITBP101", "CSBP101"]},
    {"gpa": 2.3, "math_confidence": 2, "programming_confidence": 2, "workload_tolerance": 12, "completed": []},
    {"gpa": 3.4, "math_confidence": 3, "programming_confidence": 3, "workload_tolerance": 28, "completed": ["CSBP101", "CSBP102"]},
    {"gpa": 2.9, "math_confidence": 3, "programming_confidence": 1, "workload_tolerance": 18, "completed": ["ITBP101"]},
    {"gpa": 3.8, "math_confidence": 5, "programming_confidence": 3, "workload_tolerance": 40, "completed": ["ITBP101", "CSBP101", "CSBP102", "ISEC321"]},
    {"gpa": 2.0, "math_confidence": 1, "programming_confidence": 1, "workload_tolerance": 10, "completed": ["ITBP101"]},
    {"gpa": 3.1, "math_confidence": 4, "programming_confidence": 2, "workload_tolerance": 24, "completed": []},
    {"gpa": 2.6, "math_confidence": 2, "programming_confidence": 4, "workload_tolerance": 20, "completed": ["CSBP101"]},
    {"gpa": 3.6, "math_confidence": 3, "programming_confidence": 5, "workload_tolerance": 32, "completed": ["ITBP101", "CSBP101", "CSBP102"]},
    {"gpa": 2.4, "math_confidence": 1, "programming_confidence": 3, "workload_tolerance": 14, "completed": []},
    {"gpa": 3.3, "math_confidence": 5, "programming_confidence": 1, "workload_tolerance": 26, "completed": ["ITBP101", "CSBP102"]},
]


def _check_constraints(recs, completed_codes, workload_budget):
    """Returns a list of violation strings (empty = all constraints held)."""
    violations = []
    if recs.empty:
        return violations

    total_workload = recs["weekly_workload"].sum() if "weekly_workload" in recs.columns else 0
    if total_workload > workload_budget:
        violations.append(f"total workload {total_workload} exceeds budget {workload_budget}")

    if "difficulty_level" in recs.columns:
        high_difficulty = (recs["difficulty_level"] >= 4).sum()
        if high_difficulty > 2:
            violations.append(f"{high_difficulty} high-difficulty courses recommended (max 2 allowed)")

    if "course_code" in recs.columns:
        overlap = set(recs["course_code"]).intersection(set(completed_codes))
        if overlap:
            violations.append(f"already-completed course(s) re-recommended: {overlap}")

    return violations


def run_tests():
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version();")).fetchone()[0]
        course_count = conn.execute(text("SELECT COUNT(*) FROM course;")).scalar()
        prereq_count = conn.execute(text("SELECT COUNT(*) FROM course_prerequisites;")).scalar()

    print("Neon DB Connection Active:", version)
    print(f"{course_count} courses, {prereq_count} prerequisite links loaded.\n")
    print(f"Running recommendation engine against {len(TEST_PROFILES)} student profiles...\n")

    passed = 0
    failed = 0

    for i, profile in enumerate(TEST_PROFILES, start=1):
        student_data = {
            "gpa": profile["gpa"],
            "math_confidence": profile["math_confidence"],
            "programming_confidence": profile["programming_confidence"],
            "workload_tolerance": profile["workload_tolerance"],
        }
        completed = profile["completed"]

        try:
            recs, excluded, message = generate_recommendations(student_data, completed)
            violations = _check_constraints(recs, completed, profile["workload_tolerance"])

            if violations:
                failed += 1
                print(f"[FAIL] Profile {i:02d} (GPA {profile['gpa']}): {'; '.join(violations)}")
            else:
                passed += 1
                print(f"[PASS] Profile {i:02d} (GPA {profile['gpa']}): {len(recs)} recommended, {len(excluded)} excluded - {message}")
        except Exception as exc:
            failed += 1
            print(f"[ERROR] Profile {i:02d}: {exc}")

    print("\n--- Summary ---")
    print(f"Passed: {passed}/{len(TEST_PROFILES)}")
    print(f"Failed: {failed}/{len(TEST_PROFILES)}")

    if failed == 0:
        print("All profiles satisfy NFR 7.4 (>=20 tested profiles) and hard constraints.")
    else:
        print("Some profiles failed constraint checks - review recommender.py logic above.")



def run_plan_variant_tests():
    print("\nRunning Safer/Balanced/Advanced hard-constraint checks...")
    for i, profile in enumerate(TEST_PROFILES, start=1):
        student_data = {k: profile[k] for k in ("gpa", "math_confidence", "programming_confidence", "workload_tolerance")}
        plans = generate_all_plans(student_data, profile["completed"])
        for name, plan in plans.items():
            recs = pd.DataFrame(plan["recommendations"])
            if recs.empty:
                continue
            workload = int(recs["weekly_workload"].sum())
            high = int((recs["difficulty_level"] >= 4).sum())
            assert workload <= profile["workload_tolerance"], f"Profile {i} {name}: workload {workload} > tolerance"
            assert high <= PLAN_VARIANTS[name]["max_high_difficulty"], f"Profile {i} {name}: high difficulty cap exceeded"
    print("All plan variants respect workload tolerance and difficulty caps.")

if __name__ == "__main__":
    run_tests()
    run_plan_variant_tests()
