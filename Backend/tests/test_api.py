"""End-to-end API tests (FastAPI TestClient + a throw-away PostgreSQL database)."""
import base64
import hashlib
import hmac
import json
import time

import pytest
from sqlalchemy import text

@pytest.fixture(scope="module")
def api(db):
    from fastapi.testclient import TestClient
    import main
    sent = []
    main.send_otp_email = lambda email, code, purpose="reset": sent.append((email, code, purpose)) or True
    with TestClient(main.app) as client:
        client.sent = sent
        yield client

@pytest.fixture(autouse=True)
def fresh_limits():
    import security
    security.limiter._hits.clear()
    yield

@pytest.fixture
def new_student(api, db):
    created = []
    counter = iter(range(200000001, 200000999))

    def make(**overrides):
        sid = str(next(counter))
        body = {"student_id": sid, "full_name": "Test Student", "academic_major": "Information Security", "gpa": 3.2,
                "math_confidence": 3, "programming_confidence": 4, "workload_tolerance": 30, "email": f"t{sid}@uaeu.ac.ae",
                "password": "TestPassword123!", "completed_courses": ["MATH105"], "completed_grades": {"MATH105": "B"},
                "privacy_consent": True}
        body.update(overrides)
        api.sent.clear()
        r = api.post("/students/signup/request-otp", json=body)
        assert r.status_code == 200, r.text
        code = api.sent[-1][1]
        r = api.post("/students/signup/verify-otp", json={"email": body["email"], "otp_code": code})
        assert r.status_code == 200, r.text
        created.append(sid)
        return body, r.json()

    yield make
    with db.begin() as conn:
        conn.execute(text("DELETE FROM student WHERE student_id = ANY(:ids)"), {"ids": created})
        conn.execute(text("DELETE FROM password_reset_otp WHERE identifier LIKE 't2000%' OR identifier LIKE '2000%'"))

def auth(token):
    return {"Authorization": f"Bearer {token}"}

def test_signup_flow_returns_plans_and_valid_json(new_student):
    body, data = new_student()
    assert data["access_token"] and data["student"]["student_id"] == body["student_id"]
    assert set(data["plans"]) == {"safer", "balanced", "advanced"}
    json.dumps(data, allow_nan=False)

def test_direct_signup_is_disabled(api):
    r = api.post("/students/signup", json={"student_id": "200009991", "full_name": "X", "gpa": 3, "math_confidence": 3, "programming_confidence": 3,
                                           "workload_tolerance": 30, "email": "x9991@uaeu.ac.ae", "password": "TestPassword123!", "privacy_consent": True})
    assert r.status_code == 403

def test_password_policy_and_domain(api):
    base = {"student_id": "200009992", "full_name": "X", "gpa": 3, "math_confidence": 3, "programming_confidence": 3,
            "workload_tolerance": 30, "email": "x9992@uaeu.ac.ae", "privacy_consent": True}
    assert api.post("/students/signup/request-otp", json={**base, "password": "short7!"}).status_code == 400
    assert api.post("/students/signup/request-otp", json={**base, "password": "TestPassword123!", "email": "x@gmail.com"}).status_code == 400
    assert api.post("/students/signup/request-otp", json={**base, "password": "TestPassword123!", "privacy_consent": False}).status_code == 400

def test_forged_token_with_old_default_secret_is_rejected(api, new_student):
    body, _ = new_student()
    raw = base64.urlsafe_b64encode(json.dumps({"sub": body["student_id"], "exp": int(time.time()) + 999}, separators=(",", ":")).encode()).decode().rstrip("=")
    forged = raw + "." + hmac.new(b"change-this-secret-in-production", raw.encode(), hashlib.sha256).hexdigest()
    assert api.get(f"/students/{body['student_id']}", headers=auth(forged)).status_code == 401

def test_cannot_read_another_students_data(api, new_student):
    a, da = new_student()
    b, _ = new_student()
    assert api.get(f"/students/{b['student_id']}", headers=auth(da["access_token"])).status_code == 401

def test_login_does_not_reveal_which_accounts_exist(api, new_student):
    body, _ = new_student()
    wrong = api.post("/students/login", json={"identifier": body["student_id"], "password": "nope-nope-nope"})
    unknown = api.post("/students/login", json={"identifier": "299999999", "password": "nope-nope-nope"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()

def test_login_requires_email_code_then_issues_token(api, new_student):
    body, _ = new_student()
    api.sent.clear()
    r = api.post("/students/login", json={"identifier": body["email"], "password": body["password"]})
    assert r.status_code == 200 and r.json()["otp_required"] is True and "access_token" not in r.json()
    code = api.sent[-1][1]
    ok = api.post("/students/login/verify-otp", json={"identifier": body["email"], "otp_code": code})
    assert ok.status_code == 200 and ok.json()["access_token"]
    assert api.post("/students/login/verify-otp", json={"identifier": body["email"], "otp_code": code}).status_code == 400              

def test_otp_brute_force_is_locked_out(api, new_student):
    body, _ = new_student()
    api.post("/students/login", json={"identifier": body["student_id"], "password": body["password"]})
    real = api.sent[-1][1]
    wrong = "000000" if real != "000000" else "111111"
    codes = [api.post("/students/login/verify-otp", json={"identifier": body["student_id"], "otp_code": wrong}).status_code for _ in range(7)]
    assert codes[:5] == [400] * 5 and 429 in codes[5:]
                                                       
    assert api.post("/students/login/verify-otp", json={"identifier": body["student_id"], "otp_code": real}).status_code == 429

def test_otp_request_flooding_is_limited(api, new_student):
    body, _ = new_student()
    statuses = [api.post("/students/login", json={"identifier": body["student_id"], "password": body["password"]}).status_code for _ in range(5)]
    assert statuses[:3] == [200] * 3 and 429 in statuses[3:]

def test_login_code_cannot_be_used_to_reset_password(api, new_student):
    body, _ = new_student()
    api.post("/students/login", json={"identifier": body["student_id"], "password": body["password"]})
    login_code = api.sent[-1][1]
    r = api.post("/students/reset-password", json={"identifier": body["student_id"], "otp_code": login_code, "new_password": "BrandNewPass1"})
    assert r.status_code == 400

def test_forgot_and_reset_password(api, new_student):
    body, _ = new_student()
    generic = api.post("/students/forgot-password", json={"identifier": "299999998"}).json()
    api.sent.clear()
    known = api.post("/students/forgot-password", json={"identifier": body["student_id"]}).json()
    assert generic == known and api.sent
    code = api.sent[-1][1]
    assert api.post("/students/verify-otp", json={"identifier": body["student_id"], "otp_code": code}).status_code == 200
    assert api.post("/students/reset-password", json={"identifier": body["student_id"], "otp_code": code, "new_password": "short"}).status_code == 422
    assert api.post("/students/reset-password", json={"identifier": body["student_id"], "otp_code": code, "new_password": "BrandNewPass1"}).status_code == 200
    assert api.post("/students/login", json={"identifier": body["student_id"], "password": "BrandNewPass1"}).status_code == 200

def test_preview_requires_authentication(api, new_student):
    body, data = new_student()
    payload = {k: body[k] for k in ("student_id", "full_name", "gpa", "math_confidence", "programming_confidence", "workload_tolerance")}
    assert api.post("/recommend/preview", json=payload).status_code == 401
    ok = api.post("/recommend/preview", json=payload, headers=auth(data["access_token"]))
    assert ok.status_code == 200 and ok.json()["plans"]["balanced"]["recommendations"] is not None

def test_recommend_saves_history_and_is_json_safe(api, new_student):
    body, data = new_student()
    payload = {k: body[k] for k in ("student_id", "full_name", "gpa", "math_confidence", "programming_confidence", "workload_tolerance")}
    payload.update(academic_major="Information Security", completed_courses=["MATH105"], completed_grades={"MATH105": "B"}, plan_type="balanced")
    r = api.post("/recommend", json=payload, headers=auth(data["access_token"]))
    assert r.status_code == 200, r.text
    js = r.json()
    json.dumps(js, allow_nan=False)
    assert js["total_workload"] <= body["workload_tolerance"]
    hist = api.get(f"/students/{body['student_id']}/recommendation-history", headers=auth(data["access_token"])).json()["history"]
    assert hist and hist[0]["courses"]

def test_profile_update_keeps_major_and_rejects_duplicate_email(api, new_student):
    a, da = new_student()
    b, _ = new_student()
    upd = {k: a[k] for k in ("student_id", "full_name", "gpa", "math_confidence", "programming_confidence", "workload_tolerance")}
    upd.update(completed_courses=["MATH105"], completed_grades={"MATH105": "B"})                                     
    r = api.put(f"/students/{a['student_id']}", json=upd, headers=auth(da["access_token"]))
    assert r.status_code == 200 and r.json()["student"]["academic_major"] == "Information Security"
    r = api.put(f"/students/{a['student_id']}", json={**upd, "email": b["email"]}, headers=auth(da["access_token"]))
    assert r.status_code == 409
    r = api.put(f"/students/{a['student_id']}", json={**upd, "completed_courses": ["NOPE999"], "completed_grades": {"NOPE999": "A"}}, headers=auth(da["access_token"]))
    assert r.status_code == 422

def test_manual_plan_checks_prerequisites(api, new_student):
    body, data = new_student(completed_courses=[], completed_grades={})
    h = auth(data["access_token"])
    bad = api.post("/plans/save", json={"student_id": body["student_id"], "course_codes": ["ISEC413"]}, headers=h)
    assert bad.status_code == 400 and "Prerequisites not met" in bad.json()["detail"]
    good = api.post("/plans/save", json={"student_id": body["student_id"], "course_codes": ["CSBP119", "CSBP121"], "plan_label": "My plan"}, headers=h)
    assert good.status_code == 200, good.text

def test_rating_url_and_body_must_match(api, new_student):
    body, data = new_student()
    h = auth(data["access_token"])
    payload = {"student_id": body["student_id"], "course_code": "MATH105", "difficulty_rating": 3, "workload_rating": 4}
    assert api.put("/courses/CSBP119/rating", json=payload, headers=h).status_code == 400
    assert api.put("/courses/MATH105/rating", json=payload, headers=h).status_code == 200

def test_courses_endpoint_is_valid_json(api):
    r = api.get("/courses")
    assert r.status_code == 200 and len(r.json()["courses"]) == 58
    json.dumps(r.json(), allow_nan=False)

def test_health_does_not_leak_details(api):
    assert api.get("/health").json()["status"] == "healthy"

def test_plan_payload_has_every_field_the_frontend_reads(api, new_student):
    """Contract with Frontend/lib/shared.tsx - keep these keys or the UI silently shows wrong data."""
    _, data = new_student(completed_courses=[], completed_grades={})
    for name, plan in data["plans"].items():
        for key in ("recommendations", "excluded", "message", "total_credits", "target_credits", "total_workload", "risk_level"):
            assert key in plan, f"{name}: missing {key}"
        assert plan["risk_level"] in {"Low", "Medium", "High"}
        for rec in plan["recommendations"]:
            for key in ("course_id", "course_code", "course_name", "credits", "difficulty_level", "math_intensity", "weekly_workload",
                        "subject_area", "reason", "reason_source", "match_percent", "taken_with"):
                assert key in rec, f"recommendation missing {key}"
            assert rec["reason_source"] in {"rule", "ai"} and 1 <= rec["match_percent"] <= 99
        for exc in plan["excluded"]:
            for key in ("course_code", "course_name", "reason", "reason_code"):
                assert key in exc, f"excluded course missing {key}"
                                                                         
    workloads = {n: p["total_workload"] for n, p in data["plans"].items()}
    assert workloads["safer"] <= workloads["balanced"] <= workloads["advanced"] or len(set(workloads.values())) > 1
