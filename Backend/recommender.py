"""Masar recommendation engine.

The engine keeps the project's rule-based approach but builds three genuinely
separate semester options.  Each option has a different credit target,
workload budget and difficulty allowance, while prerequisite and completed-
course checks remain hard constraints.
"""

import re
import time
import pandas as pd
from sqlalchemy import text
from db import engine

HIGH_DIFFICULTY_THRESHOLD = 4
HIGH_MATH_THRESHOLD = 4
DEFAULT_WORKLOAD_TOLERANCE = 30
_CACHE_TTL_SECONDS = 60.0
_COURSE_CACHE = None
_COURSE_CACHE_AT = 0.0
_PREREQ_CACHE = None
_PREREQ_CACHE_AT = 0.0

PLAN_VARIANTS = {
    "safer":    {"credit_target_max": 12, "max_high_difficulty": 1, "workload_multiplier": 0.75, "target_credits": 12},
    "balanced": {"credit_target_max": 15, "max_high_difficulty": 2, "workload_multiplier": 1.00, "target_credits": 15},
    "advanced": {"credit_target_max": 18, "max_high_difficulty": 2, "workload_multiplier": 1.25, "target_credits": 18},
}


def normalize_code(value) -> str:
    return re.sub(r"\s+", "", str(value)).strip().upper()


def parse_prerequisite_codes(value) -> list[str]:
    if value is None or pd.isna(value) or not str(value).strip():
        return []
    cleaned = re.sub(r"\((?:co|pre|co/pre)\)", "", str(value), flags=re.IGNORECASE)
    parts = re.split(r",|\band\b|\bor\b|&|/", cleaned, flags=re.IGNORECASE)
    return [normalize_code(p) for p in parts if normalize_code(p)]


def get_prerequisite_map() -> dict[int, list[int]]:
    global _PREREQ_CACHE, _PREREQ_CACHE_AT
    now = time.monotonic()
    if _PREREQ_CACHE is not None and now - _PREREQ_CACHE_AT < _CACHE_TTL_SECONDS:
        return _PREREQ_CACHE
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT course_id, prerequisite_course_id FROM course_prerequisites")).fetchall()
    result: dict[int, list[int]] = {}
    for course_id, prereq_id in rows:
        result.setdefault(course_id, []).append(prereq_id)
    _PREREQ_CACHE = result
    _PREREQ_CACHE_AT = now
    return result


def get_courses_df() -> pd.DataFrame:
    """Cache the small course catalog briefly so login/preview/plan generation does not repeatedly hit PostgreSQL."""
    global _COURSE_CACHE, _COURSE_CACHE_AT
    now = time.monotonic()
    if _COURSE_CACHE is not None and now - _COURSE_CACHE_AT < _CACHE_TTL_SECONDS:
        return _COURSE_CACHE.copy(deep=True)
    courses_df = pd.read_sql("SELECT * FROM course;", con=engine)
    _COURSE_CACHE = courses_df.copy(deep=True)
    _COURSE_CACHE_AT = now
    return courses_df


def generate_course_reason(course, student_data) -> str:
    reasons = []
    if course["difficulty_level"] <= max(1, student_data["gpa"] + 0.4):
        reasons.append(f"fits your academic standing (GPA {student_data['gpa']:.2f})")
    else:
        reasons.append("adds an appropriate challenge for your current profile")
    if course["math_intensity"] <= student_data["math_confidence"]:
        reasons.append(f"fits your math confidence ({student_data['math_confidence']}/5)")
    if course.get("has_programming", "No") == "Yes" and student_data.get("programming_confidence", 3) >= 3:
        reasons.append(f"aligns with your programming confidence ({student_data.get('programming_confidence', 3)}/5)")
    if course["weekly_workload"] <= 6:
        reasons.append("helps keep the semester balanced")
    elif course["weekly_workload"] >= 8:
        reasons.append("is a higher-workload option within your selected plan")
    return "Recommended: " + "; ".join(reasons) + "."


def generate_exclusion_reason(reason_code: str, extra: str = "") -> str:
    messages = {
        "missing_prereq": f"Not eligible yet, missing prerequisite(s): {extra}.",
        "already_completed": "Already completed, not recommended again.",
        "high_difficulty_cap": "Skipped because this plan limits the number of high-difficulty courses.",
        "high_math_cap": "Skipped because this plan limits math-intensive courses for your current confidence.",
        "credit_limit": "Not selected because the plan's credit target was filled with higher-fit courses.",
        "workload_limit": "Not selected because adding it would exceed this plan's workload budget.",
    }
    return messages.get(reason_code, "Not included in this plan.")


def _fit_score(course, student_data) -> float:
    score = 0.0
    difficulty = float(course["difficulty_level"])
    gpa = float(student_data.get("gpa", 3.0))
    math = float(student_data.get("math_confidence", 3))
    programming = float(student_data.get("programming_confidence", 3))
    workload = float(course["weekly_workload"])
    tolerance = float(student_data.get("workload_tolerance", DEFAULT_WORKLOAD_TOLERANCE))

    score += max(0, 5 - abs(difficulty - min(5, gpa + 1.0))) * 2.0
    score += max(0, 4 - abs(float(course["math_intensity"]) - math)) * 1.7
    if str(course.get("has_programming", "No")).lower() == "yes":
        score += programming * 0.65
    score += max(0, 3 - abs(workload - min(tolerance / 5, 8))) * 0.55
                                                                               
    score += float(course.get("course_level", 100)) / 1000.0
    return score


def _choose_best_subset(eligible_df: pd.DataFrame, student_data: dict, target: int, workload_budget: int, max_high_difficulty: int):
    """Find the highest-fit subset at the target credit count when possible.

    Dynamic programming is used instead of the old first-fit loop so Safer,
    Balanced and Advanced plans can actually land on 12/15/18 credits when the
    eligible course pool makes those totals possible.
    """
    if eligible_df.empty or target <= 0:
        return []

    math_cap = 1 if student_data.get("math_confidence", 3) < HIGH_MATH_THRESHOLD else 3
    items = []
    for _, row in eligible_df.iterrows():
        items.append({
            "row": row,
            "credits": int(row["credits"]),
            "workload": int(row["weekly_workload"]),
            "high_diff": int(row["difficulty_level"] >= HIGH_DIFFICULTY_THRESHOLD),
            "high_math": int(row["math_intensity"] >= HIGH_MATH_THRESHOLD),
            "score": _fit_score(row, student_data),
        })

                                                                           
    dp = {(0, 0, 0, 0): (0.0, ())}
    for idx, item in enumerate(items):
        next_dp = dict(dp)
        for state, (score, chosen) in dp.items():
            credits, workload, high_diff, high_math = state
            nc = credits + item["credits"]
            nw = workload + item["workload"]
            nd = high_diff + item["high_diff"]
            nm = high_math + item["high_math"]
            if nc > target or nw > workload_budget or nd > max_high_difficulty or nm > math_cap:
                continue
                                                                                 
                                                                                
                                                                              
                                                                
            plan_target = float(student_data.get("plan_workload_target", 30))
            current_load = workload
            added_load = item["workload"]
            before_distance = abs(plan_target - current_load)
            after_distance = abs(plan_target - (current_load + added_load))
            workload_fit = (before_distance - after_distance) * 0.18
            ns = score + item["score"] + workload_fit
            old = next_dp.get((nc, nw, nd, nm))
            if old is None or ns > old[0]:
                next_dp[(nc, nw, nd, nm)] = (ns, chosen + (idx,))
        dp = next_dp

    exact = [(score, chosen) for (credits, _, _, _), (score, chosen) in dp.items() if credits == target]
    if exact:
        return list(max(exact, key=lambda x: x[0])[1])

                                                                           
                                                                         
    attainable = [(credits, score, chosen) for (credits, _, _, _), (score, chosen) in dp.items() if credits > 0]
    if not attainable:
        return []
    max_credit = max(x[0] for x in attainable)
    best = max((x for x in attainable if x[0] == max_credit), key=lambda x: x[1])
    return list(best[2])


def _build_exclusions(courses_df, selected_ids, completed_ids, eligible_reasons):
    excluded = []
    for _, course in courses_df.iterrows():
        cid = course["course_id"]
        if cid in selected_ids:
            continue
        reason = eligible_reasons.get(cid)
        if reason:
            excluded.append({**course.to_dict(), "reason": reason})
        elif cid in completed_ids:
            excluded.append({**course.to_dict(), "reason": generate_exclusion_reason("already_completed")})
    return excluded


def generate_recommendations(
    student_data: dict,
    completed_course_codes: list[str],
    credit_target_max: int = 16,
    max_high_difficulty: int = 2,
    workload_multiplier: float = 1.0,
    plan_label: str = "Balanced",
):
    courses_df = get_courses_df()
    courses_df = courses_df.dropna(subset=["course_id", "course_code", "course_name"]).copy()
    if courses_df.empty:
        return pd.DataFrame(), [], "No courses found in the database. Has seed_db.py been run?"

    courses_df["course_code"] = courses_df["course_code"].map(normalize_code)
    completed_codes = {normalize_code(c) for c in completed_course_codes if normalize_code(c)}
    code_to_id = dict(zip(courses_df["course_code"], courses_df["course_id"]))
    code_to_name = dict(zip(courses_df["course_code"], courses_df["course_name"]))
    completed_ids = {code_to_id[c] for c in completed_codes if c in code_to_id}
    prereq_map = get_prerequisite_map()

    eligible = []
    reasons = {}
    for _, course in courses_df.iterrows():
        cid = course["course_id"]
        if cid in completed_ids:
            continue
        required_ids = prereq_map.get(cid, [])
        required_codes = parse_prerequisite_codes(course.get("prerequisite_text"))
        if required_codes:
            missing = [code for code in required_codes if code not in completed_codes]
        else:
            missing = [normalize_code(courses_df.loc[courses_df["course_id"] == x, "course_code"].iloc[0]) for x in required_ids if x not in completed_ids]
        if missing:
            missing_display = [code_to_name.get(code, code) for code in missing]
            reasons[cid] = generate_exclusion_reason("missing_prereq", ", ".join(missing_display))
            continue
        eligible.append(course)

    if not eligible:
        excluded = _build_exclusions(courses_df, set(), completed_ids, reasons)
        return pd.DataFrame(), excluded, "No eligible courses found. All remaining courses are either completed or missing prerequisites."

    eligible_df = pd.DataFrame(eligible)
    base_tolerance = int(student_data.get("workload_tolerance", DEFAULT_WORKLOAD_TOLERANCE))
    workload_budget = max(1, int(round(base_tolerance * workload_multiplier)))
    selected_indices = _choose_best_subset(eligible_df, student_data, int(credit_target_max), workload_budget, int(max_high_difficulty))

    selected_ids = set()
    included = []
    if selected_indices:
        for idx in selected_indices:
            course = eligible_df.iloc[idx]
            selected_ids.add(course["course_id"])
            item = course.to_dict()
            item["reason"] = generate_course_reason(course, student_data)
            included.append(item)

    recommendations_df = pd.DataFrame(included)
    if not recommendations_df.empty:
        recommendations_df = recommendations_df.sort_values(["difficulty_level", "course_code"], ascending=[True, True]).reset_index(drop=True)

                                                                            
                                                              
    selected_workload = int(recommendations_df["weekly_workload"].sum()) if not recommendations_df.empty else 0
    selected_credits = int(recommendations_df["credits"].sum()) if not recommendations_df.empty else 0
    selected_high_diff = int((recommendations_df["difficulty_level"] >= HIGH_DIFFICULTY_THRESHOLD).sum()) if not recommendations_df.empty else 0
    selected_high_math = int((recommendations_df["math_intensity"] >= HIGH_MATH_THRESHOLD).sum()) if not recommendations_df.empty else 0
    math_cap = 1 if student_data.get("math_confidence", 3) < HIGH_MATH_THRESHOLD else 3

    for _, course in eligible_df.iterrows():
        if course["course_id"] in selected_ids:
            continue
        if selected_credits + int(course["credits"]) > credit_target_max:
            reasons[course["course_id"]] = generate_exclusion_reason("credit_limit")
        elif selected_workload + int(course["weekly_workload"]) > workload_budget:
            reasons[course["course_id"]] = generate_exclusion_reason("workload_limit")
        elif int(course["difficulty_level"] >= HIGH_DIFFICULTY_THRESHOLD) and selected_high_diff >= max_high_difficulty:
            reasons[course["course_id"]] = generate_exclusion_reason("high_difficulty_cap")
        elif int(course["math_intensity"] >= HIGH_MATH_THRESHOLD) and selected_high_math >= math_cap:
            reasons[course["course_id"]] = generate_exclusion_reason("high_math_cap")
        else:
            reasons[course["course_id"]] = generate_exclusion_reason("credit_limit")

    excluded = _build_exclusions(courses_df, selected_ids, completed_ids, reasons)
    message = f"Generated {len(recommendations_df)} course recommendations ({selected_credits} credits, {selected_workload} hrs/week). {len(excluded)} course(s) excluded."
    return recommendations_df, excluded, message


def generate_all_plans(student_data: dict, completed_course_codes: list[str]) -> dict:
    results = {}
    for name, cfg in PLAN_VARIANTS.items():
        plan_data = dict(student_data)
        tolerance = float(student_data.get("workload_tolerance", DEFAULT_WORKLOAD_TOLERANCE))
        plan_data["plan_workload_target"] = {
            "safer": max(18.0, tolerance * 0.70),
            "balanced": max(24.0, tolerance * 0.95),
            "advanced": max(30.0, tolerance * 1.20),
        }[name]
        recs_df, excluded, message = generate_recommendations(
            plan_data,
            completed_course_codes,
            credit_target_max=cfg["credit_target_max"],
            max_high_difficulty=cfg["max_high_difficulty"],
            workload_multiplier=cfg["workload_multiplier"],
            plan_label=name.capitalize(),
        )
        total_credits = int(recs_df["credits"].sum()) if not recs_df.empty else 0
        total_workload = int(recs_df["weekly_workload"].sum()) if not recs_df.empty else 0
        risk_level = "Low" if name == "safer" else ("Medium" if name == "balanced" else "High")
        results[name] = {
            "recommendations": recs_df.to_dict(orient="records"),
            "excluded": excluded,
            "message": message,
            "total_credits": total_credits,
            "target_credits": cfg["target_credits"],
            "total_workload": total_workload,
            "risk_level": risk_level,
        }
    return results


def save_recommendation_to_db(conn, student_id: str, recs_df: pd.DataFrame, plan_label: str = "Balanced") -> int:
    total_workload = int(recs_df["weekly_workload"].sum()) if "weekly_workload" in recs_df else 0
    risk_level = "Low" if total_workload <= 25 else ("Medium" if total_workload <= 38 else "High")
    summary = f"{plan_label} Plan ({len(recs_df)} Courses)"
    rec_id = conn.execute(
        text("""
            INSERT INTO recommendation (student_id, total_workload, overall_risk_level, plan_summary)
            VALUES (:student_id, :workload, :risk, :summary)
            RETURNING recommendation_id;
        """),
        {"student_id": student_id, "workload": total_workload, "risk": risk_level, "summary": summary},
    ).scalar()
    if not recs_df.empty:
                                                                           
                                                                            
        rows = [
            {"rec_id": rec_id, "course_id": int(course["course_id"]), "reason": course["reason"]}
            for _, course in recs_df.iterrows()
        ]
        conn.execute(
            text("""
                INSERT INTO recommended_courses (recommendation_id, course_id, reason)
                VALUES (:rec_id, :course_id, :reason)
            """),
            rows,
        )
    return rec_id
