"""Recommendation engine tests: every hard constraint, on many generated profiles."""
import json
import random

import pytest

from prereq import parse_requirement
from recommender import (PLAN_VARIANTS, compute_risk_level, generate_all_plans, generate_recommendations,
                         records, validate_plan_eligibility)

BIG = dict(credit_target_max=99, max_high_difficulty=99, workload_multiplier=10)
SD = {"gpa": 3.5, "math_confidence": 5, "programming_confidence": 5, "workload_tolerance": 50, "major": "Information Security"}

def rec_codes(sd, completed, **kw):
    recs, excluded, _ = generate_recommendations(sd, sorted(completed), **kw)
    return (set(recs.course_code) if not recs.empty else set()), recs, excluded

def realistic_completed(rng, courses, n):
    """A random completed set that is closed under hard prerequisites."""
    done, codes = set(), sorted(courses)
    for _ in range(n * 3):
        code = rng.choice(codes)
        req = parse_requirement(courses[code].prerequisite_text)
        if req.min_credits:
            continue
        if all(any(c in done for c, _ in g) or any(k == "co" for _, k in g) for g in req.groups):
            done.add(code)
        if len(done) >= n:
            break
    return done

def test_every_course_can_be_recommended_somewhere(courses):
    """Regression: mutual co-requisite courses used to be permanently blocked."""
    stuck = []
    for code in courses:
        got, _, _ = rec_codes(SD, set(courses) - {code}, **BIG)
        if code not in got:
            stuck.append(code)
    assert stuck == []

def test_mutual_corequisites_are_recommended_together(courses):
    """Design & Analysis of Security Protocols <-> Cryptography Lab are mutual co-requisites.
    A student who has everything else must be offered BOTH (they used to be blocked forever)."""
    left = {"ISEC322", "ISEC324", "ISEC413", "ISEC423", "ISEC428"}                                  
    got, _, excluded = rec_codes(SD, set(courses) - left, credit_target_max=12, max_high_difficulty=5, workload_multiplier=1)
    assert got == {"ISEC322", "ISEC324"}
    assert next(e for e in excluded if e["course_code"] == "ISEC413")["reason_code"] == "missing_prereq"

    left = {"ISEC321", "ISEC414", "ISEC412"}                                                                       
    got, _, _ = rec_codes(SD, set(courses) - left, credit_target_max=12, max_high_difficulty=5, workload_multiplier=1)
    assert got == {"ISEC321", "ISEC414"}

def test_corequisite_is_never_recommended_alone(courses):
    """If the budget only fits one of a co-requisite pair, neither may be chosen."""
    left = {"ISEC322", "ISEC324"}
    got, _, excluded = rec_codes({**SD, "workload_tolerance": 10}, set(courses) - left - {"ISEC413", "ISEC423", "ISEC428"},
                                 credit_target_max=12, max_high_difficulty=5, workload_multiplier=1)
    assert not (got & left) or got == left
    if not got:
        assert next(e for e in excluded if e["course_code"] == "ISEC324")["reason_code"] in {"workload_limit", "corequisite_not_selected", "credit_limit"}

def test_one_way_corequisite_taken_together(courses):
    """Programming Lab I needs CSBP119 (co): both may enter the same plan."""
    pending = {"CSBP119", "CSBP121"}
    others = set(courses) - pending - {c for c in courses if "CSBP119" in str(courses[c].prerequisite_text) or "CSBP121" in str(courses[c].prerequisite_text)}
    got, _, _ = rec_codes(SD, others, credit_target_max=12, max_high_difficulty=5, workload_multiplier=1)
    assert pending <= got

def test_or_prerequisite(courses):
    got, _, _ = rec_codes(SD, {"CENG205", "PHYS105", "CENG210", "ITBP301"}, **BIG)
    assert "ITBP418" in got

def test_credit_hour_rule(courses):
    _, _, excluded = rec_codes(SD, {"MATH105", "CSBP119"}, **BIG)
    msg = next(e for e in excluded if e["course_code"] == "ITBP495")
    assert msg["reason_code"] == "credit_hours" and "80" in msg["reason"] and "MINIMUM" not in msg["reason"]
    many = sorted(set(courses) - {"ITBP495", "ITBP481", "ITBP480", "ISEC412"})[:30]
    got, _, _ = rec_codes(SD, set(many), **BIG)
    assert "ITBP495" in got

def test_hard_prerequisite_blocks(courses):
    got, _, excluded = rec_codes(SD, set(), **BIG)
    assert "ISEC413" not in got
    assert next(e for e in excluded if e["course_code"] == "ISEC413")["reason_code"] == "missing_prereq"

@pytest.mark.parametrize("seed", range(25))
def test_all_hard_constraints_on_generated_profiles(courses, seed):
    rng = random.Random(seed)
    sd = {"gpa": round(rng.uniform(1.6, 4.0), 2), "math_confidence": rng.randint(1, 5), "programming_confidence": rng.randint(1, 5),
          "workload_tolerance": rng.randint(10, 50), "major": rng.choice(["Information Security", "Computer Science", "Other"])}
    completed = realistic_completed(rng, courses, rng.randint(0, 35))
    plans = generate_all_plans(sd, sorted(completed), use_ai=False)
    for name, plan in plans.items():
        cfg = PLAN_VARIANTS[name]
        recs = plan["recommendations"]
        codes = [r["course_code"] for r in recs]
        assert len(codes) == len(set(codes)), "duplicate course"
        assert not (set(codes) & completed), "recommended a completed course"
        assert plan["total_workload"] <= sd["workload_tolerance"], "workload tolerance exceeded (FR 4.1)"
        assert plan["total_credits"] <= cfg["credit_target_max"]
        assert sum(r["difficulty_level"] >= 4 for r in recs) <= cfg["max_high_difficulty"]
        if sd["math_confidence"] < 4:
            assert sum(r["math_intensity"] >= 4 for r in recs) <= 1
        assert validate_plan_eligibility(codes, sorted(completed)) == [], "recommended a course with unmet prerequisites"
        for r in recs:
            assert r["reason"] and 1 <= r["match_percent"] <= 99
        json.dumps(plan, allow_nan=False)                                
                                                                                                               
    for plan in plans.values():
        assert plan["risk_level"] == compute_risk_level(plan["total_workload"], sd["workload_tolerance"])

def test_determinism(courses):
    sd = {**SD, "workload_tolerance": 33}
    a = generate_all_plans(sd, ["MATH105", "CSBP119"], use_ai=False)
    b = generate_all_plans(sd, ["MATH105", "CSBP119"], use_ai=False)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)

def test_excluded_courses_have_reasons_and_codes(courses):
    plans = generate_all_plans(SD, ["MATH105"], use_ai=False)
    for plan in plans.values():
        chosen = {r["course_code"] for r in plan["recommendations"]}
        assert not ({e["course_code"] for e in plan["excluded"]} & chosen)
        assert all(e["reason"] and e["reason_code"] for e in plan["excluded"])

def test_json_safe_course_records(courses):
    from recommender import get_courses_df
    json.dumps(records(get_courses_df()), allow_nan=False)

def test_validate_plan_eligibility_for_manual_plans(courses):
    assert validate_plan_eligibility(["ISEC413"], []) != []
    assert validate_plan_eligibility(["ISEC322", "ISEC324"], sorted(set(courses) - {"ISEC322", "ISEC324"} - {"ISEC413", "ISEC423"})) == []
    assert validate_plan_eligibility(["CSBP119", "CSBP121"], []) == []
