"""Masar recommendation engine.

The engine is rule-based and deterministic: identical input always produces
identical output (NFR 3.3). It builds three genuinely different semester
options (Safer / Balanced / Advanced). Hard constraints for every option:

* completed courses are never recommended again          (NFR 7.2)
* prerequisites are enforced, including
    - OR alternatives      "ITBP301 or ITBP280"
    - co-requisites        "CSBP119 (co)"  -> may be taken in the SAME semester
    - credit-hour rules    "Minimum 80 completed credit hours"      (FR 3.2)
* total weekly workload never exceeds the student's stated tolerance (FR 4.1)
* at most N high-difficulty courses (FR 4.3) and at most one very
  math-intensive course unless math confidence >= 4               (FR 4.4)

Co-requisites are handled by grouping courses that need each other into one
"item" (e.g. Design of Security Protocols + Cryptography Lab) that is chosen
or skipped as a whole, so a plan is never invalid.

The optional AI layer (ai_explanation.py) only rewrites the wording of the
"why this course" text. It never influences which courses are selected.
"""
from __future__ import annotations

import logging
import re
import math
import time
import json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal

import pandas as pd
from sqlalchemy import text

import ai_explanation
from db import engine
from prereq import Requirement, describe_group, normalize_code, parse_requirement

logger = logging.getLogger("masar.recommender")

_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "recommendation_rules.json"

def _load_recommendation_config() -> dict:
    """Load recommendation rules from external configuration (NFR 6.1)."""
    try:
        with _CONFIG_PATH.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load recommendation rules from {_CONFIG_PATH}: {exc}") from exc

_RECOMMENDATION_CONFIG = _load_recommendation_config()
_THRESHOLD_CONFIG = _RECOMMENDATION_CONFIG["thresholds"]
_DEFAULT_CONFIG = _RECOMMENDATION_CONFIG["defaults"]
_MATH_CAP_CONFIG = _RECOMMENDATION_CONFIG["math_cap"]

HIGH_DIFFICULTY_THRESHOLD = int(_THRESHOLD_CONFIG["high_difficulty"])
HIGH_MATH_THRESHOLD = int(_THRESHOLD_CONFIG["high_math"])
DEFAULT_WORKLOAD_TOLERANCE = int(_DEFAULT_CONFIG["workload_tolerance_hours"])
_CACHE_TTL_SECONDS = 60.0
_COURSE_CACHE = None
_COURSE_CACHE_AT = 0.0
_PREREQ_CACHE = None
_PREREQ_CACHE_AT = 0.0

                                                                    
PLAN_VARIANTS = _RECOMMENDATION_CONFIG["plan_variants"]

MAJOR_CORE_AREAS = {
    "information security": {"Information Security", "Computer Science", "Information Technology", "Computer Engineering", "Mathematics", "Software Engineering", "Physics"},
    "computer science": {"Computer Science", "Mathematics", "Software Engineering", "Computer Engineering", "Information Technology"},
    "information technology": {"Information Technology", "Computer Science", "Information Security", "Software Engineering", "Computer Engineering", "Mathematics"},
    "software engineering": {"Software Engineering", "Computer Science", "Mathematics", "Information Technology", "Computer Engineering"},
}
_GOAL_BONUS_MAX = float(_RECOMMENDATION_CONFIG["fit_scoring"]["goal_bonus_max"])
_MAX_FIT_SCORE = 5 * 2.0 + 4 * 1.7 + 5 * 0.65 + 3 * 0.55 + 5 * 0.35 + 2.0 + _GOAL_BONUS_MAX                                     

def compute_risk_level(total_workload: int, tolerance: float | None = None) -> str:
    """Single source of truth for "risk level".

    With the student's tolerance the risk is relative to *their* capacity
    (<=65% Low, <=90% Medium, else High). Without it we fall back to absolute hours.
    """
    if tolerance and tolerance > 0:
        ratio = total_workload / float(tolerance)
        return "Low" if ratio <= 0.65 else ("Medium" if ratio <= 0.90 else "High")
    return "Low" if total_workload <= 25 else ("Medium" if total_workload <= 38 else "High")

                                                                            
def sanitize(value):
    """Make a value JSON-safe: numpy -> python, NaN/NaT -> None, Decimal -> float."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if value is pd.NaT or (not isinstance(value, (list, dict, tuple, str)) and pd.isna(value) is True):
        return None
    return value

def records(df: pd.DataFrame) -> list[dict]:
    if df is None or df.empty:
        return []
    return [{k: sanitize(v) for k, v in row.items()} for row in df.to_dict(orient="records")]

def _num(value, default: float) -> float:
    try:
        v = float(value)
        return default if math.isnan(v) else v
    except (TypeError, ValueError):
        return default

def get_prerequisite_map() -> dict[int, list[int]]:
    """Fallback prerequisites from the course_prerequisites table (only 'pre' links)."""
    global _PREREQ_CACHE, _PREREQ_CACHE_AT
    now = time.monotonic()
    if _PREREQ_CACHE is not None and now - _PREREQ_CACHE_AT < _CACHE_TTL_SECONDS:
        return _PREREQ_CACHE
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT course_id, prerequisite_course_id FROM course_prerequisites WHERE relation_type = 'pre'")).fetchall()
    result: dict[int, list[int]] = {}
    for course_id, prereq_id in rows:
        result.setdefault(course_id, []).append(prereq_id)
    _PREREQ_CACHE, _PREREQ_CACHE_AT = result, now
    return result

def get_courses_df() -> pd.DataFrame:
    """Cache the small course catalog briefly so requests do not hit PostgreSQL repeatedly."""
    global _COURSE_CACHE, _COURSE_CACHE_AT
    now = time.monotonic()
    if _COURSE_CACHE is not None and now - _COURSE_CACHE_AT < _CACHE_TTL_SECONDS:
        return _COURSE_CACHE.copy(deep=True)
    courses_df = pd.read_sql("SELECT * FROM course;", con=engine)
    _COURSE_CACHE, _COURSE_CACHE_AT = courses_df.copy(deep=True), now
    return courses_df

                                                                             
def _core_areas(student_data: dict) -> set:
    return MAJOR_CORE_AREAS.get(str(student_data.get("major") or "").strip().lower(), set())

def _is_core(course, student_data) -> bool:
    return course.get("subject_area") in _core_areas(student_data)

def _goal_terms(student_data: dict) -> set[str]:
    raw = str(student_data.get("academic_career_goals") or "").lower()
    return {t for t in re.findall(r"[a-z0-9\u0600-\u06ff]+", raw) if len(t) >= 3}

_GOAL_ALIASES = {
    "security": {"security", "cybersecurity", "cyber", "infosec", "information", "الأمن", "السيبراني", "أمن"},
    "software": {"software", "developer", "development", "programming", "applications", "apps", "البرمجيات", "البرمجة", "تطوير"},
    "data": {"data", "analytics", "analysis", "machine", "learning", "ai", "artificial", "intelligence", "البيانات", "تحليل", "الذكاء", "اصطناعي"},
    "network": {"network", "networking", "cloud", "infrastructure", "الشبكات", "الشبكة", "السحابة"},
    "business": {"business", "management", "entrepreneurship", "finance", "marketing"},
    "research": {"research", "researcher", "academia", "academic"},
}

def _goal_alignment(course, student_data: dict) -> float:
    terms = _goal_terms(student_data)
    if not terms:
        return 0.0
    text = " ".join(str(course.get(k) or "") for k in ("course_code", "course_name", "subject_area", "assessment_type", "prerequisite_text")).lower()
    words = set(re.findall(r"[a-z0-9\u0600-\u06ff]+", text))
    direct = len(terms & words)
    alias_hits = sum(1 for aliases in _GOAL_ALIASES.values() if terms & aliases and words & aliases)
    return min(_GOAL_BONUS_MAX, direct * 0.8 + alias_hits * 0.8)

def _fit_score(course, student_data) -> float:
    difficulty = _num(course.get("difficulty_level"), 3)
    gpa = _num(student_data.get("gpa"), 3.0)
    math_conf = _num(student_data.get("math_confidence"), 3)
    programming = _num(student_data.get("programming_confidence"), 3)
    workload = _num(course.get("weekly_workload"), 6)
    tolerance = _num(student_data.get("workload_tolerance"), DEFAULT_WORKLOAD_TOLERANCE)

    score = max(0.0, 5 - abs(difficulty - min(5, gpa + 1.0))) * 2.0
    score += max(0.0, 4 - abs(_num(course.get("math_intensity"), 1) - math_conf)) * 1.7
    if str(course.get("has_programming", "No")).lower() == "yes":
        score += programming * 0.65
    score += max(0.0, 3 - abs(workload - min(tolerance / 5, 8))) * 0.55
                                                                         
    score += max(0.0, 6 - _num(course.get("course_level"), 100) / 100.0) * 0.35
    if _is_core(course, student_data):
        score += 2.0
    score += _goal_alignment(course, student_data)
    return score

def match_percent(course, student_data) -> int:
    return int(max(1, min(99, round(100 * _fit_score(course, student_data) / _MAX_FIT_SCORE))))

                                                                           
def generate_course_reason(course, student_data, taken_with=None) -> str:
    gpa = _num(student_data.get("gpa"), 3.0)
    language = "ar" if str(student_data.get("language") or "en").lower().startswith("ar") else "en"
    reasons = []
    if language == "ar":
        if _is_core(course, student_data):
            reasons.append("مقرر أساسي لتخصصك")
        if _goal_alignment(course, student_data) > 0:
            reasons.append("يتوافق مع أهدافك الأكاديمية أو المهنية")
        if _num(course.get("difficulty_level"), 3) <= min(5.0, gpa + 1.0) + 0.5:
            reasons.append(f"يتناسب مع مستواك الأكاديمي (المعدل {gpa:.2f})")
        else:
            reasons.append("يمثل تحدياً مناسباً لملفك الأكاديمي الحالي")
        math_conf = int(_num(student_data.get("math_confidence"), 3))
        if _num(course.get("math_intensity"), 1) <= math_conf:
            reasons.append(f"يتناسب مع مستوى ثقتك في الرياضيات ({math_conf}/5)")
        prog_conf = int(_num(student_data.get("programming_confidence"), 3))
        if str(course.get("has_programming", "No")) == "Yes" and prog_conf >= 3:
            reasons.append(f"يتوافق مع مستوى ثقتك في البرمجة ({prog_conf}/5)")
        workload = _num(course.get("weekly_workload"), 6)
        if workload <= 6:
            reasons.append("يساعد على إبقاء عبء الفصل متوازناً")
        elif workload >= 8:
            reasons.append("خيار ذو عبء دراسي أعلى لكنه ضمن حدود خطتك الحالية")
        if taken_with:
            reasons.append("يُدرس مع " + ", ".join(taken_with) + " (متطلب مصاحب)")
        return "تم ترشيح هذا المقرر لأنه " + "؛ ".join(reasons) + "."

    if _is_core(course, student_data):
        reasons.append("is a core course for your major")
    if _goal_alignment(course, student_data) > 0:
        reasons.append("aligns with your academic/career goals")
    if _num(course.get("difficulty_level"), 3) <= min(5.0, gpa + 1.0) + 0.5:
        reasons.append(f"fits your academic standing (GPA {gpa:.2f})")
    else:
        reasons.append("adds an appropriate challenge for your current profile")
    math_conf = int(_num(student_data.get("math_confidence"), 3))
    if _num(course.get("math_intensity"), 1) <= math_conf:
        reasons.append(f"fits your math confidence ({math_conf}/5)")
    prog_conf = int(_num(student_data.get("programming_confidence"), 3))
    if str(course.get("has_programming", "No")) == "Yes" and prog_conf >= 3:
        reasons.append(f"aligns with your programming confidence ({prog_conf}/5)")
    workload = _num(course.get("weekly_workload"), 6)
    if workload <= 6:
        reasons.append("helps keep the semester balanced")
    elif workload >= 8:
        reasons.append("is a higher-workload option within your selected plan")
    if taken_with:
        reasons.append("is taken together with " + ", ".join(taken_with) + " (co-requisite)")
    return "Recommended: " + "; ".join(reasons) + "."

def generate_exclusion_reason(reason_code: str, extra: str = "") -> str:
    messages = {
        "missing_prereq": f"Not eligible yet, missing prerequisite(s): {extra}.",
        "credit_hours": f"Not eligible yet, it requires {extra}.",
        "already_completed": "Already completed, not recommended again.",
        "high_difficulty_cap": "Skipped because this plan limits the number of high-difficulty courses.",
        "high_math_cap": "Skipped because this plan limits math-intensive courses for your current confidence.",
        "credit_limit": "Not selected because the plan's credit target was filled with higher-fit courses.",
        "workload_limit": "Not selected because adding it would exceed this plan's workload budget.",
        "corequisite_not_selected": f"Not selected because it must be taken together with {extra}, which is not part of this plan.",
    }
    return messages.get(reason_code, "Not included in this plan.")

def _ai_facts(rec: dict, student_data: dict) -> dict:
    """Ground-truth facts the AI may talk about (identical for every plan)."""
    return {
        "course_code": rec["course_code"],
        "course_name": rec["course_name"],
        "credits": int(_num(rec.get("credits"), 3)),
        "difficulty_level": int(_num(rec.get("difficulty_level"), 3)),
        "math_intensity": int(_num(rec.get("math_intensity"), 1)),
        "weekly_workload": int(_num(rec.get("weekly_workload"), 6)),
        "has_programming": str(rec.get("has_programming") or "No"),
        "core_for_student_major": bool(rec.get("core_for_major")),
        "taken_with": list(rec.get("taken_with") or []),
        "student_gpa": round(_num(student_data.get("gpa"), 3.0), 2),
        "student_math_confidence": int(_num(student_data.get("math_confidence"), 3)),
        "student_programming_confidence": int(_num(student_data.get("programming_confidence"), 3)),
        "student_workload_tolerance_hours": int(_num(student_data.get("workload_tolerance"), DEFAULT_WORKLOAD_TOLERANCE)),
        "language": "ar" if str(student_data.get("language") or "en").lower().startswith("ar") else "en",
        "rating_scale_max": 5,
    }

def apply_ai_reasons(record_lists: list[list[dict]], student_data: dict) -> None:
    """Replace deterministic reasons with AI wording - ONE provider request for all lists."""
    if not ai_explanation.is_enabled():
        return
    facts, seen = [], set()
    for lst in record_lists:
        for rec in lst:
            code = rec["course_code"]
            if code not in seen:
                seen.add(code)
                facts.append({"course_code": code, "facts": _ai_facts(rec, student_data)})
    explained = ai_explanation.generate_ai_explanations(facts)
    for lst in record_lists:
        for rec in lst:
            text_ = explained.get(rec["course_code"])
            if text_:
                rec["reason"] = text_
                rec["reason_source"] = "ai"

                                                                             
@dataclass
class _Item:
    idx: int
    codes: list
    credits: int = 0
    workload: int = 0
    high_diff: int = 0
    high_math: int = 0
    score: float = 0.0
    dep_groups: list = field(default_factory=list)                                                      

def _analyse(rows: dict, completed_codes, student_data: dict):
    """Work out which courses are selectable and group co-requisite courses.

    Returns (items, blocked, completed, completed_credits) where
    blocked = {code: (reason_code, detail)}.
    """
    names = {c: r["course_name"] for c, r in rows.items()}
    completed = {c for c in (normalize_code(x) for x in completed_codes) if c in rows}
    completed_credits = int(sum(_num(rows[c].get("credits"), 0) for c in completed))

    prereq_map = get_prerequisite_map()
    id_to_code = {r["course_id"]: c for c, r in rows.items()}

    reqs: dict[str, Requirement] = {}
    for code, rec in rows.items():
        req = parse_requirement(rec.get("prerequisite_text"))
        if req.is_empty and not req.notes and not str(rec.get("prerequisite_text") or "").strip():
            linked = [id_to_code[i] for i in prereq_map.get(rec["course_id"], []) if i in id_to_code]
            if linked:
                req = Requirement(groups=tuple(((c, "pre"),) for c in linked))
        reqs[code] = req

    blocked: dict[str, tuple] = {}
    need: dict[str, list] = {}
    for code in sorted(rows):
        if code in completed:
            continue
        req = reqs[code]
        if req.min_credits and completed_credits < req.min_credits:
            blocked[code] = ("credit_hours", f"at least {req.min_credits} completed credit hours (you have {completed_credits})")
            continue
        missing, co_groups = [], []
        for group in req.groups:
            if any(c in completed for c, _ in group):
                continue
            co_opts = [c for c, kind in group if kind == "co" and c in rows and c != code]
            if co_opts:
                co_groups.append(co_opts)
            else:
                missing.append(describe_group(group, names))
        if missing:
            blocked[code] = ("missing_prereq", ", ".join(missing))
        else:
            need[code] = co_groups

    changed = True
    while changed:
        changed = False
        for code in sorted(need):
            for group in need[code]:
                if not any(o in need for o in group):
                    blocked[code] = ("missing_prereq", " or ".join(names[o] for o in group) + " (must be taken together)")
                    del need[code]
                    changed = True
                    break

    adj = {c: sorted({o for g in need[c] for o in g if o in need}) for c in need}

    def reach(start):
        seen, stack = set(), [start]
        while stack:
            for nxt in adj.get(stack.pop(), []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        return seen

    reach_map = {c: reach(c) for c in need}
    comp_of: dict[str, int] = {}
    comps: list[list[str]] = []
    for c in sorted(need):
        if c in comp_of:
            continue
        members = sorted({c} | {x for x in reach_map[c] if c in reach_map[x]})
        for m in members:
            comp_of[m] = len(comps)
        comps.append(members)

    comp_deps = []
    for members in comps:
        deps = {comp_of[o] for m in members for g in need[m] for o in g if o in need and comp_of[o] != comp_of[m]}
        comp_deps.append(sorted(deps))

    order, state = [], {}

    def visit(ci):
        if state.get(ci):
            return
        state[ci] = 1
        for d in comp_deps[ci]:
            visit(d)
        order.append(ci)

    for ci in sorted(range(len(comps)), key=lambda i: comps[i][0]):
        visit(ci)
    new_index = {ci: pos for pos, ci in enumerate(order)}

    items: list[_Item] = []
    for ci in order:
        members = comps[ci]
        item = _Item(idx=new_index[ci], codes=members)
        for m in members:
            r = rows[m]
            item.credits += int(_num(r.get("credits"), 3))
            item.workload += int(_num(r.get("weekly_workload"), 6))
            item.high_diff += int(_num(r.get("difficulty_level"), 3) >= HIGH_DIFFICULTY_THRESHOLD)
            item.high_math += int(_num(r.get("math_intensity"), 1) >= HIGH_MATH_THRESHOLD)
            item.score += _fit_score(r, student_data)
            for group in need[m]:
                if any(comp_of[o] == ci for o in group if o in need):
                    continue                               
                dep = sorted({new_index[comp_of[o]] for o in group if o in need})
                if dep and dep not in item.dep_groups:
                    item.dep_groups.append(dep)
        items.append(item)
    return items, blocked, completed, completed_credits

def _choose_best_items(items: list[_Item], student_data: dict, target: int, workload_budget: int, max_high_difficulty: int, workload_goal: float):
    """Exact dynamic programme: highest-fit set of items reaching `target` credits
    (or the most credits attainable) under all hard constraints."""
    if not items or target <= 0:
        return []
    math_cap = (int(_MATH_CAP_CONFIG["low_confidence_max_high_math_courses"]) if _num(student_data.get("math_confidence"), 3) < int(_MATH_CAP_CONFIG["confidence_threshold"]) else int(_MATH_CAP_CONFIG["high_confidence_max_high_math_courses"]))
    providers = {d for it in items for grp in it.dep_groups for d in grp}

    dp = {(0, 0, 0, 0, frozenset()): (0.0, ())}
    for item in items:
        next_dp = dict(dp)
        for state, (score, chosen) in dp.items():
            credits, workload, high_diff, high_math, prov = state
            nc, nw = credits + item.credits, workload + item.workload
            nd, nm = high_diff + item.high_diff, high_math + item.high_math
            if nc > target or nw > workload_budget or nd > max_high_difficulty or nm > math_cap:
                continue
            if item.dep_groups and not all(any(o in chosen for o in grp) for grp in item.dep_groups):
                continue
            fit = (abs(workload_goal - workload) - abs(workload_goal - nw)) * 0.18
            new_key = (nc, nw, nd, nm, prov | {item.idx} if item.idx in providers else prov)
            new_score = score + item.score + fit
            old = next_dp.get(new_key)
            if old is None or new_score > old[0]:
                next_dp[new_key] = (new_score, chosen + (item.idx,))
        dp = next_dp

    exact = [(s, ch) for (c, *_), (s, ch) in dp.items() if c == target]
    if exact:
        return list(max(exact, key=lambda x: x[0])[1])
    attainable = [(c, s, ch) for (c, *_), (s, ch) in dp.items() if c > 0]
    if not attainable:
        return []
    top = max(x[0] for x in attainable)
    return list(max((x for x in attainable if x[0] == top), key=lambda x: x[1])[2])

def _slim(rec: dict, reason_code: str, message: str) -> dict:
    keys = ("course_id", "course_code", "course_name", "credits", "subject_area", "difficulty_level", "math_intensity", "weekly_workload")
    out = {k: sanitize(rec.get(k)) for k in keys}
    out.update({"reason": message, "reason_code": reason_code})
    return out

def _course_rows(courses_df: pd.DataFrame) -> dict:
    df = courses_df.dropna(subset=["course_id", "course_code", "course_name"]).copy()
    out = {}
    for rec in df.to_dict(orient="records"):
        rec = {k: sanitize(v) for k, v in rec.items()}
        rec["course_code"] = normalize_code(rec["course_code"])
        out[rec["course_code"]] = rec
    return out

def generate_recommendations(
    student_data: dict,
    completed_course_codes: list[str],
    credit_target_max: int = 16,
    max_high_difficulty: int = 2,
    workload_multiplier: float = 1.0,
    plan_label: str = "Balanced",
    use_ai: bool = False,
    workload_target_share: float = 0.85,
):
    rows = _course_rows(get_courses_df())
    if not rows:
        return pd.DataFrame(), [], "No courses found in the database. Has seed_db.py been run?"

    items, blocked, completed, _credits = _analyse(rows, completed_course_codes, student_data)

    tolerance = int(_num(student_data.get("workload_tolerance"), DEFAULT_WORKLOAD_TOLERANCE))
                                                                         
    workload_budget = max(1, min(tolerance, int(round(tolerance * min(1.0, float(workload_multiplier))))))
    workload_goal = float(student_data.get("plan_workload_target") or tolerance * workload_target_share)

    excluded_map: dict[str, tuple] = {}
    for code, (rc, detail) in blocked.items():
        excluded_map[code] = (rc, generate_exclusion_reason(rc, detail))

    if not items:
        excluded = _build_exclusions(rows, set(), completed, excluded_map)
        return pd.DataFrame(), excluded, "No eligible courses found. All remaining courses are either completed or missing prerequisites."

    chosen = _choose_best_items(items, student_data, int(credit_target_max), workload_budget, int(max_high_difficulty), workload_goal)
    selected_codes: set[str] = set()
    included: list[dict] = []
    for idx in chosen:
        item = items[idx]
        for code in item.codes:
            selected_codes.add(code)
    for idx in chosen:
        item = items[idx]
        for code in item.codes:
            rec = dict(rows[code])
            others = [c for c in item.codes if c != code]
            rec["taken_with"] = others
            rec["core_for_major"] = _is_core(rec, student_data)
            rec["reason"] = generate_course_reason(rec, student_data, taken_with=others)
            rec["reason_source"] = "rule"
            rec["match_percent"] = match_percent(rec, student_data)
            included.append(rec)

    if included and use_ai:
        apply_ai_reasons([included], student_data)

    recs_df = pd.DataFrame(included)
    if not recs_df.empty:
        recs_df = recs_df.sort_values(["difficulty_level", "course_code"], ascending=[True, True]).reset_index(drop=True)

    sel_credits = int(recs_df["credits"].sum()) if not recs_df.empty else 0
    sel_workload = int(recs_df["weekly_workload"].sum()) if not recs_df.empty else 0
    sel_hd = int((recs_df["difficulty_level"] >= HIGH_DIFFICULTY_THRESHOLD).sum()) if not recs_df.empty else 0
    sel_hm = int((recs_df["math_intensity"] >= HIGH_MATH_THRESHOLD).sum()) if not recs_df.empty else 0
    math_cap = (int(_MATH_CAP_CONFIG["low_confidence_max_high_math_courses"]) if _num(student_data.get("math_confidence"), 3) < int(_MATH_CAP_CONFIG["confidence_threshold"]) else int(_MATH_CAP_CONFIG["high_confidence_max_high_math_courses"]))
    chosen_set = set(chosen)

    for item in items:
        if item.idx in chosen_set:
            continue
        names = {c: rows[c]["course_name"] for c in rows}
        unmet = [g for g in item.dep_groups if not any(o in chosen_set for o in g)]
        if unmet:
            partners = ", ".join(" or ".join(names[c] for o in g for c in items[o].codes) for g in unmet)
            rc, msg = "corequisite_not_selected", generate_exclusion_reason("corequisite_not_selected", partners)
        elif sel_credits + item.credits > credit_target_max:
            rc, msg = "credit_limit", generate_exclusion_reason("credit_limit")
        elif sel_workload + item.workload > workload_budget:
            rc, msg = "workload_limit", generate_exclusion_reason("workload_limit")
        elif item.high_diff and sel_hd + item.high_diff > max_high_difficulty:
            rc, msg = "high_difficulty_cap", generate_exclusion_reason("high_difficulty_cap")
        elif item.high_math and sel_hm + item.high_math > math_cap:
            rc, msg = "high_math_cap", generate_exclusion_reason("high_math_cap")
        else:
            rc, msg = "credit_limit", generate_exclusion_reason("credit_limit")
        for code in item.codes:
            excluded_map[code] = (rc, msg)

    excluded = _build_exclusions(rows, selected_codes, completed, excluded_map)
    message = f"Generated {len(recs_df)} course recommendations ({sel_credits} credits, {sel_workload} hrs/week). {len(excluded)} course(s) excluded."
    return recs_df, excluded, message

def _build_exclusions(rows: dict, selected_codes: set, completed: set, excluded_map: dict) -> list[dict]:
    out = []
    for code in sorted(rows):
        if code in selected_codes:
            continue
        if code in completed:
            out.append(_slim(rows[code], "already_completed", generate_exclusion_reason("already_completed")))
        elif code in excluded_map:
            rc, msg = excluded_map[code]
            out.append(_slim(rows[code], rc, msg))
    return out

def _generate_one_plan(name: str, cfg: dict, student_data: dict, completed_course_codes: list[str]) -> tuple:
    recs_df, excluded, message = generate_recommendations(
        student_data,
        completed_course_codes,
        credit_target_max=cfg["credit_target_max"],
        max_high_difficulty=cfg["max_high_difficulty"],
        workload_multiplier=cfg["workload_multiplier"],
        plan_label=name.capitalize(),
        use_ai=False,
        workload_target_share=cfg["workload_target_share"],
    )
    total_credits = int(recs_df["credits"].sum()) if not recs_df.empty else 0
    total_workload = int(recs_df["weekly_workload"].sum()) if not recs_df.empty else 0
    tolerance = _num(student_data.get("workload_tolerance"), DEFAULT_WORKLOAD_TOLERANCE)
    return name, {
        "recommendations": records(recs_df),
        "excluded": excluded,
        "message": message,
        "total_credits": total_credits,
        "target_credits": cfg["target_credits"],
        "total_workload": total_workload,
        "risk_level": compute_risk_level(total_workload, tolerance),
    }

def generate_all_plans(student_data: dict, completed_course_codes: list[str], use_ai: bool = True) -> dict:
    """Build Safer/Balanced/Advanced plans. The three plans are computed in
    parallel; then ONE AI request explains every distinct course."""
    results = {}
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(_generate_one_plan, n, cfg, student_data, completed_course_codes) for n, cfg in PLAN_VARIANTS.items()]
        for future in futures:
            name, plan = future.result()
            results[name] = plan
    if use_ai:
        apply_ai_reasons([p["recommendations"] for p in results.values()], student_data)
    return results

def validate_plan_eligibility(course_codes: list[str], completed_course_codes: list[str]) -> list[str]:
    """Check a hand-picked plan against prerequisite rules. Co-requisites may be
    satisfied by another course in the same plan. Returns human-readable problems."""
    rows = _course_rows(get_courses_df())
    completed = {c for c in (normalize_code(x) for x in completed_course_codes) if c in rows}
    credits = int(sum(_num(rows[c].get("credits"), 0) for c in completed))
    selected = {normalize_code(c) for c in course_codes}
    names = {c: r["course_name"] for c, r in rows.items()}
    problems = []
    for code in sorted(selected):
        if code not in rows:
            continue
        req = parse_requirement(rows[code].get("prerequisite_text"))
        if req.min_credits and credits < req.min_credits:
            problems.append(f"{code} requires at least {req.min_credits} completed credit hours (you have {credits}).")
        for group in req.groups:
            ok = any(c in completed or (k == "co" and c in selected and c != code) for c, k in group)
            if not ok:
                problems.append(f"{code} requires {describe_group(group, names)} first.")
    return problems

def save_recommendation_to_db(conn, student_id: str, recs, plan_label: str = "Balanced", workload_tolerance: float | None = None) -> int:
    recs_list = records(recs) if isinstance(recs, pd.DataFrame) else list(recs)
    total_workload = int(sum(_num(r.get("weekly_workload"), 0) for r in recs_list))
    risk_level = compute_risk_level(total_workload, workload_tolerance)
    summary = f"{plan_label} Plan ({len(recs_list)} Courses)"
    rec_id = conn.execute(
        text("""
            INSERT INTO recommendation (student_id, total_workload, overall_risk_level, plan_summary)
            VALUES (:student_id, :workload, :risk, :summary)
            RETURNING recommendation_id;
        """),
        {"student_id": student_id, "workload": total_workload, "risk": risk_level, "summary": summary},
    ).scalar()
    if recs_list:
        conn.execute(
            text("INSERT INTO recommended_courses (recommendation_id, course_id, reason) VALUES (:rec_id, :course_id, :reason)"),
            [{"rec_id": rec_id, "course_id": int(r["course_id"]), "reason": r.get("reason")} for r in recs_list],
        )
    return rec_id
