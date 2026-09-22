"""AI layer tests with a fake provider (no network)."""
import json

import pytest

import ai_explanation as ai

class FakeResp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers, self.text = status, body or {}, headers or {}, json.dumps(body or {})

    def json(self):
        return self._body

def ok_response(codes, extra=""):
    content = {c: f"{c} fits your profile and needs about 8 hours each week.{extra}" for c in codes}
    return FakeResp(200, {"choices": [{"message": {"content": json.dumps(content)}, "finish_reason": "stop"}]})

def facts(code):
    return {"course_code": code, "facts": {"course_code": code, "course_name": "Course", "weekly_workload": 8, "difficulty_level": 2,
                                           "rating_scale_max": 5, "student_gpa": 3.4}}

@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("AI_EXPLANATION_ENABLED", "true")
    monkeypatch.setenv("AI_API_KEY", "x")
    monkeypatch.setenv("AI_EXPLANATION_MAX_RETRIES", "2")
    monkeypatch.setattr(ai, "_db_get", lambda keys: {})
    monkeypatch.setattr(ai, "_db_put", lambda rows: None)
    monkeypatch.setattr(ai.time, "sleep", lambda s: None)
    ai.reset_state_for_tests()
    yield
    ai.reset_state_for_tests()

def test_one_request_explains_every_course(monkeypatch):
    calls = []
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: calls.append(1) or ok_response(["A100", "B200", "C300"]))
    out = ai.generate_ai_explanations([facts("A100"), facts("B200"), facts("C300")])
    assert set(out) == {"A100", "B200", "C300"} and len(calls) == 1

def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    seq = [FakeResp(429, {}, {"Retry-After": "1"}), FakeResp(429), ok_response(["A100"])]
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: seq.pop(0))
    assert "A100" in ai.generate_ai_explanations([facts("A100")])

def test_results_are_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: calls.append(1) or ok_response(["A100"]))
    ai.generate_ai_explanations([facts("A100")])
    ai.generate_ai_explanations([facts("A100")])
    assert len(calls) == 1

def test_invented_numbers_are_rejected(monkeypatch):
    bad = FakeResp(200, {"choices": [{"message": {"content": json.dumps({"A100": "This course will raise your GPA by 0.7 points next term."})}}]})
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: bad)
    assert ai.generate_ai_explanations([facts("A100")]) == {}

def test_failure_falls_back_and_circuit_breaker_opens(monkeypatch):
    calls = []
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: calls.append(1) or FakeResp(500))
    assert ai.generate_ai_explanations([facts("A100")]) == {}
    n = len(calls)
    assert ai.generate_ai_explanations([facts("B200")]) == {}
    assert len(calls) == n, "provider must not be called again while the breaker is open"

def test_bad_key_opens_breaker_without_retries(monkeypatch):
    calls = []
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: calls.append(1) or FakeResp(401))
    ai.generate_ai_explanations([facts("A100")])
    assert len(calls) == 1

def test_disabled_makes_no_calls(monkeypatch):
    monkeypatch.setenv("AI_EXPLANATION_ENABLED", "false")
    monkeypatch.setattr(ai.requests, "post", lambda *a, **k: pytest.fail("must not call"))
    assert ai.generate_ai_explanations([facts("A100")]) == {}

def test_low_timeout_setting_is_raised(monkeypatch):
    monkeypatch.setenv("AI_EXPLANATION_TIMEOUT_SECONDS", "2.5")
    assert ai._cfg()["timeout"] >= 5
