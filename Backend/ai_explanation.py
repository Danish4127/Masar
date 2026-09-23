"""AI explanation layer (Additional Feature)

The rule engine in recommender.py decides WHICH courses are recommended. This
module only rewrites the supplied facts into friendly prose. It is designed to
be robust against slow / rate-limited providers (e.g. Groq free tier):

* ONE request explains ALL courses of a page load (not one request per course),
  so a page load costs a single provider call instead of 12-18.
* Explanations are cached in memory and in PostgreSQL (ai_explanation_cache),
  so the same student/course facts never call the provider twice
  (keeps NFR 3.3 - identical input, identical output - true).
* HTTP 429 / 5xx / timeouts are retried with back-off (honouring Retry-After)
  inside an overall time budget.
* A circuit breaker pauses AI calls for a while after repeated failures, so a
  broken provider never slows every page load.
* Every explanation is validated (no invented numbers, no personal data).
  Anything missing or invalid falls back to the deterministic sentence.

Environment variables (all optional):
  AI_EXPLANATION_ENABLED            true/false (default false)
  AI_API_KEY, AI_API_BASE, AI_MODEL provider settings (OpenAI-compatible)
  AI_EXPLANATION_TIMEOUT_SECONDS    per-request timeout, minimum 5 (default 12)
  AI_EXPLANATION_MAX_RETRIES        default 2
  AI_EXPLANATION_BUDGET_SECONDS     total time budget per batch (default 25)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from collections import OrderedDict
from typing import Any

import requests
from sqlalchemy import bindparam, text

from db import engine

logger = logging.getLogger("masar.ai_explanations")

CACHE_VERSION = "v7-language-validated"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_API_BASE = "https://api.groq.com/openai/v1"
MIN_TIMEOUT_SECONDS = 5.0

_MEM_CACHE: "OrderedDict[str, str]" = OrderedDict()
_MEM_LOCK = threading.Lock()
_MEM_MAX = 4000
_PROVIDER_SLOTS = threading.BoundedSemaphore(2)
_cooldown_until = 0.0
_table_ready = False
_table_lock = threading.Lock()
_warned_timeout = False

last_status: dict = {"ok": None, "detail": "not called yet", "at": None}

                                                                           
def _cfg() -> dict:
    def _float(name, default):
        try:
            return float(os.getenv(name, "") or default)
        except ValueError:
            return float(default)

    global _warned_timeout
    timeout = _float("AI_EXPLANATION_TIMEOUT_SECONDS", 12)
    if timeout < MIN_TIMEOUT_SECONDS:
        if not _warned_timeout:
            _warned_timeout = True
            logger.warning("AI_EXPLANATION_TIMEOUT_SECONDS=%.1f is too low for an LLM call; using %.1f.", timeout, MIN_TIMEOUT_SECONDS)
        timeout = MIN_TIMEOUT_SECONDS
    return {
        "enabled": os.getenv("AI_EXPLANATION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"},
        "key": os.getenv("AI_API_KEY", "").strip(),
        "base": (os.getenv("AI_API_BASE", DEFAULT_API_BASE).strip() or DEFAULT_API_BASE).rstrip("/"),
        "model": os.getenv("AI_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL,
        "timeout": timeout,
        "retries": max(0, int(_float("AI_EXPLANATION_MAX_RETRIES", 2))),
        "budget": max(timeout, _float("AI_EXPLANATION_BUDGET_SECONDS", 25)),
    }

def is_enabled() -> bool:
    cfg = _cfg()
    return bool(cfg["enabled"] and cfg["key"])

def _set_status(ok: bool, detail: str) -> None:
    last_status.update({"ok": ok, "detail": detail, "at": time.time()})

                                                                           
def _course_system_prompt(language: str) -> str:
    language_name = "Arabic" if str(language).lower().startswith("ar") else "English"
    return f"""You are the natural-language explanation layer of an academic course recommendation system.
The recommendation engine has ALREADY decided which courses are recommended. Only turn the supplied facts into short explanations in {language_name}.

Rules:
- Write ONLY in {language_name}; do not mix English explanation sentences into Arabic mode. Course codes and official course names may remain in their original form.
- Do not change, rank, approve, reject or re-score any recommendation.
- Use ONLY the supplied facts. Never invent prerequisites, grades, skills, goals, benefits or scores.
- Never mention a student name, student ID, email or password.
- Do not introduce numbers that are not in the facts. The rating scale is 1 to 5.
- Do not promise GPA or academic-success outcomes.
- Write 1-2 plain, friendly sentences per course, addressed to the student (you).
- Mention why the course fits the student's GPA, confidence levels or workload facts.
- If "taken_with" is not empty, mention that it is taken together with those courses.
- Return ONLY a JSON object whose keys are the exact course codes given and whose values are the explanation strings."""

def _build_messages(items: list[dict]) -> list[dict]:
    language = "en"
    if items and isinstance(items[0].get("facts"), dict):
        language = str(items[0]["facts"].get("language") or "en")
    user = json.dumps({"course_facts": items, "output_format": {"COURSE_CODE": "short explanation"}}, ensure_ascii=False)
    return [{"role": "system", "content": _course_system_prompt(language)}, {"role": "user", "content": user}]

                                                                           
def _parse_json_object(content: str) -> dict[str, str]:
    if not isinstance(content, str) or not content.strip():
        return {}
    content = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
    content = re.sub(r"\s*```$", "", content)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k).strip(): v.strip() for k, v in parsed.items() if isinstance(v, str) and v.strip()}

def _allowed_numbers(facts: Any) -> set[str]:
    allowed: set[str] = set()

    def collect(value):
        if isinstance(value, bool):
            return
        if isinstance(value, (int, float)):
            allowed.update({str(value), f"{value:g}", f"{value:.1f}", f"{value:.2f}"})
        elif isinstance(value, str):
            allowed.update(re.findall(r"\d+(?:\.\d+)?", value))
        elif isinstance(value, (list, tuple)):
            for v in value:
                collect(v)
        elif isinstance(value, dict):
            for v in value.values():
                collect(v)

    collect(facts)
    return allowed

def _has_arabic_text(value: str) -> bool:
    # Arabic explanations must contain actual Arabic-script text. English
    # course names/codes are allowed, but an all-English answer is rejected.
    return len(re.findall(r"[\u0600-\u06FF]", value or "")) >= 4


def _validate(explanation: str, facts: dict) -> bool:
    if not isinstance(explanation, str):
        return False
    explanation = explanation.strip()
    if not 25 <= len(explanation) <= 650:
        return False
    lowered = explanation.lower()
    if any(p in lowered for p in ("student id", "student_id", "email", "password")):
        return False
    language = str(facts.get("language") or "en").lower()
    if language.startswith("ar") and not _has_arabic_text(explanation):
        return False
    allowed = _allowed_numbers(facts)
    return all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", explanation))

def cache_key(course_code: str, facts: dict, model: str) -> str:
    raw = json.dumps({"v": CACHE_VERSION, "code": course_code, "model": model, "facts": facts},
                     sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

                                                                           
def _mem_get(key: str):
    with _MEM_LOCK:
        if key in _MEM_CACHE:
            _MEM_CACHE.move_to_end(key)
            return _MEM_CACHE[key]
    return None

def _mem_put(key: str, value: str) -> None:
    with _MEM_LOCK:
        _MEM_CACHE[key] = value
        _MEM_CACHE.move_to_end(key)
        while len(_MEM_CACHE) > _MEM_MAX:
            _MEM_CACHE.popitem(last=False)

def _ensure_table() -> None:
    global _table_ready
    if _table_ready:
        return
    with _table_lock:
        if _table_ready:
            return
        try:
            with engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS ai_explanation_cache (cache_key VARCHAR(64) PRIMARY KEY, "
                    "course_code VARCHAR(20) NOT NULL, model VARCHAR(100) NOT NULL, explanation TEXT NOT NULL, "
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"))
            _table_ready = True
        except Exception as exc:                                           
            logger.warning("Could not ensure ai_explanation_cache table: %s", exc)

def _db_get(keys: list[str]) -> dict[str, str]:
    if not keys:
        return {}
    _ensure_table()
    try:
        stmt = text("SELECT cache_key, explanation FROM ai_explanation_cache WHERE cache_key IN :k").bindparams(bindparam("k", expanding=True))
        with engine.connect() as conn:
            return {r[0]: r[1] for r in conn.execute(stmt, {"k": keys}).fetchall()}
    except Exception as exc:
        logger.warning("AI cache read failed: %s", exc)
        return {}

def _db_put(rows: list[dict]) -> None:
    if not rows:
        return
    _ensure_table()
    try:
        with engine.begin() as conn:
            conn.execute(text(
                "INSERT INTO ai_explanation_cache (cache_key, course_code, model, explanation) "
                "VALUES (:cache_key, :course_code, :model, :explanation) "
                "ON CONFLICT (cache_key) DO UPDATE SET explanation = EXCLUDED.explanation, model = EXCLUDED.model"), rows)
    except Exception as exc:
        logger.warning("AI cache write failed: %s", exc)

                                                                          
class _ProviderError(Exception):
    def __init__(self, message, fatal=False):
        super().__init__(message)
        self.fatal = fatal

def _retry_after(resp) -> float | None:
    try:
        return float(resp.headers.get("Retry-After", ""))
    except (TypeError, ValueError):
        return None

def _call_provider(items: list[dict], cfg: dict) -> dict[str, str]:
    """One chat-completions request (with retries) returning {course_code: text}."""
    payload: dict = {
        "model": cfg["model"],
        "messages": _build_messages(items),
        "temperature": 0.2,

        "max_completion_tokens": min(4000, 300 * len(items) + 1200),
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in cfg["model"]:
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"}
    deadline = time.monotonic() + cfg["budget"]
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining < 1.5:
            raise _ProviderError("time budget exhausted")
        try:
            with _PROVIDER_SLOTS:
                resp = requests.post(f"{cfg['base']}/chat/completions", headers=headers, json=payload,
                                     timeout=(min(5.0, remaining), min(cfg["timeout"], remaining)))
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt >= cfg["retries"]:
                raise _ProviderError(f"{type(exc).__name__}") from exc
            attempt += 1
            time.sleep(min(1.5 * 2 ** (attempt - 1), 4, max(0, deadline - time.monotonic() - 1)))
            continue

        if resp.status_code == 400 and "response_format" in payload and "response_format" in resp.text.lower():
            payload.pop("response_format")                                    
            continue
        if resp.status_code in (401, 403):
            raise _ProviderError(f"HTTP {resp.status_code} (check AI_API_KEY / model access)", fatal=True)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt >= cfg["retries"]:
                raise _ProviderError(f"HTTP {resp.status_code} after {attempt + 1} attempt(s)")
            wait = _retry_after(resp)
            wait = min(wait if wait is not None else 1.5 * 2 ** attempt, 6.0)
            attempt += 1
            logger.info("AI provider returned %s - retrying in %.1fs (attempt %d)", resp.status_code, wait, attempt)
            time.sleep(min(wait, max(0.0, deadline - time.monotonic() - 1)))
            continue
        if resp.status_code >= 400:
            raise _ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            choice = (resp.json().get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
        except ValueError as exc:
            raise _ProviderError("invalid JSON from provider") from exc
        result = _parse_json_object(content)
        if not result:
            raise _ProviderError(f"empty/unparseable answer (finish_reason={choice.get('finish_reason')})")
        return result

                                                                            
def generate_ai_explanations(course_facts: list[dict]) -> dict[str, str]:
    """course_facts: [{"course_code": "MATH105", "facts": {...}}, ...].
    Returns {course_code: explanation} for every course that could be
    explained. Missing courses simply keep their deterministic text."""
    global _cooldown_until
    if not course_facts:
        return {}
    cfg = _cfg()
    if not (cfg["enabled"] and cfg["key"]):
        return {}

    unique: dict[str, dict] = {}
    for item in course_facts:
        code = str(item.get("course_code", "")).strip()
        facts = item.get("facts")
        if code and isinstance(facts, dict) and code not in unique:
            unique[code] = facts
    keys = {code: cache_key(code, facts, cfg["model"]) for code, facts in unique.items()}

    result: dict[str, str] = {}
    need_db = []
    for code, key in keys.items():
        hit = _mem_get(key)
        if hit:
            result[code] = hit
        else:
            need_db.append(code)
    if need_db:
        db_hits = _db_get([keys[c] for c in need_db])
        for code in need_db:
            text_ = db_hits.get(keys[code])
            if text_:
                result[code] = text_
                _mem_put(keys[code], text_)
    missing = [c for c in unique if c not in result]
    if not missing:
        return result

    if time.monotonic() < _cooldown_until:
        return result                                                                   

    items = [{"course_code": c, "facts": unique[c]} for c in missing]
    try:
        generated = _call_provider(items, cfg)
    except _ProviderError as exc:
        _cooldown_until = time.monotonic() + (300 if exc.fatal else 45)
        _set_status(False, str(exc))
        logger.warning("AI explanations unavailable (%s) - using deterministic text.", exc)
        return result
    except Exception as exc:                                                 
        _cooldown_until = time.monotonic() + 45
        _set_status(False, f"{type(exc).__name__}: {exc}")
        logger.warning("AI explanation call failed unexpectedly: %s", exc)
        return result

    rows = []
    rejected = 0
    for code in missing:
        candidate = generated.get(code)
        if candidate and _validate(candidate, unique[code]):
            result[code] = candidate
            _mem_put(keys[code], candidate)
            rows.append({"cache_key": keys[code], "course_code": code, "model": cfg["model"], "explanation": candidate})
        else:
            rejected += 1
    _db_put(rows)
    _set_status(True, f"{len(rows)} generated, {rejected} rejected/missing")
    if rejected:
        logger.info("AI explanations: %d valid, %d rejected or missing (deterministic text used for those).", len(rows), rejected)
    return result


def _plan_messages(facts: dict) -> list[dict]:
    language = "Arabic" if str(facts.get("language")).lower().startswith("ar") else "English"
    system = f"""You are the explanation layer of the Masar academic recommendation system.\nThe deterministic recommendation engine has ALREADY selected the semester plan. Your job is only to explain that decision in {language}.\n\nRules:\n- Never change, rank, approve, reject, or re-score the plan.\n- Use ONLY the supplied facts. Never invent prerequisites, grades, goals, course benefits, or scores.\n- Do not mention student name, student ID, email, password, or other identifying information.\n- Do not introduce numbers that are not present in the supplied facts.\n- Explain why the selected courses fit the profile, how the workload and reported plan risk/complexity relate to the student's workload tolerance, and why some alternatives were not included.\n- Distinguish facts from interpretation. Use cautious wording such as 'Masar selected' rather than promising academic success.\n- Keep each field concise but meaningful: summary 2-3 sentences; profile_fit 2-4 sentences; workload 2-4 sentences; exclusions 2-4 sentences.\n- Return ONLY a JSON object with exactly these keys: summary, profile_fit, workload, exclusions."""
    return [{"role": "system", "content": system}, {"role": "user", "content": json.dumps(facts, ensure_ascii=False)}]


def _call_plan_provider(facts: dict, cfg: dict) -> dict[str, str]:
    payload: dict = {
        "model": cfg["model"],
        "messages": _plan_messages(facts),
        "temperature": 0.2,
        "max_completion_tokens": 1200,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in cfg["model"]:
        payload["reasoning_effort"] = "low"
    headers = {"Authorization": f"Bearer {cfg['key']}", "Content-Type": "application/json"}
    deadline = time.monotonic() + min(cfg["budget"], 20.0)
    attempt = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining < 1.5:
            raise _ProviderError("time budget exhausted")
        try:
            with _PROVIDER_SLOTS:
                resp = requests.post(f"{cfg['base']}/chat/completions", headers=headers, json=payload,
                                     timeout=(min(5.0, remaining), min(cfg["timeout"], remaining)))
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt >= cfg["retries"]:
                raise _ProviderError(f"{type(exc).__name__}") from exc
            attempt += 1
            time.sleep(min(1.5 * 2 ** (attempt - 1), 4, max(0, deadline - time.monotonic() - 1)))
            continue
        if resp.status_code == 400 and "response_format" in payload and "response_format" in resp.text.lower():
            payload.pop("response_format")
            continue
        if resp.status_code in (401, 403):
            raise _ProviderError(f"HTTP {resp.status_code} (check AI_API_KEY / model access)", fatal=True)
        if resp.status_code in (429, 500, 502, 503, 504):
            if attempt >= cfg["retries"]:
                raise _ProviderError(f"HTTP {resp.status_code} after {attempt + 1} attempt(s)")
            wait = min(_retry_after(resp) or 1.5 * 2 ** attempt, 6.0)
            attempt += 1
            time.sleep(min(wait, max(0.0, deadline - time.monotonic() - 1)))
            continue
        if resp.status_code >= 400:
            raise _ProviderError(f"HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            choice = (resp.json().get("choices") or [{}])[0]
            content = (choice.get("message") or {}).get("content") or ""
        except ValueError as exc:
            raise _ProviderError("invalid JSON from provider") from exc
        result = _parse_json_object(content)
        return result


def _valid_plan_text(value: str, facts: dict) -> bool:
    if not isinstance(value, str) or not 35 <= len(value.strip()) <= 900:
        return False
    lowered = value.lower()
    if any(p in lowered for p in ("student id", "student_id", "email", "password")):
        return False
    language = str(facts.get("language") or "en").lower()
    if language.startswith("ar") and not _has_arabic_text(value):
        return False
    allowed = _allowed_numbers(facts)
    return all(n in allowed for n in re.findall(r"\d+(?:\.\d+)?", value))


def generate_plan_explanation(facts: dict) -> dict[str, str]:
    """Explain one already-computed plan. Returns an empty dict when AI is unavailable."""
    global _cooldown_until
    if not isinstance(facts, dict):
        return {}
    cfg = _cfg()
    if not (cfg["enabled"] and cfg["key"]):
        return {}
    key = hashlib.sha256(json.dumps({"v": CACHE_VERSION, "type": "plan", "model": cfg["model"], "facts": facts},
                                    sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")).hexdigest()
    cached = _mem_get(key)
    if cached:
        try:
            return json.loads(cached)
        except Exception:
            pass
    if time.monotonic() < _cooldown_until:
        return {}
    try:
        generated = _call_plan_provider(facts, cfg)
    except _ProviderError as exc:
        _cooldown_until = time.monotonic() + (300 if exc.fatal else 45)
        _set_status(False, str(exc))
        logger.warning("Plan explanation unavailable (%s) - using deterministic explanation.", exc)
        return {}
    except Exception as exc:
        _cooldown_until = time.monotonic() + 45
        _set_status(False, f"{type(exc).__name__}: {exc}")
        logger.warning("Plan explanation failed unexpectedly: %s", exc)
        return {}
    result = {k: str(generated.get(k, "")).strip() for k in ("summary", "profile_fit", "workload", "exclusions")}
    if not all(_valid_plan_text(v, facts) for v in result.values()):
        _set_status(False, "plan explanation validation rejected provider output")
        return {}
    _mem_put(key, json.dumps(result, ensure_ascii=False))
    _set_status(True, "plan explanation generated")
    return result

def reset_state_for_tests() -> None:
    global _cooldown_until, _table_ready
    _cooldown_until = 0.0
    with _MEM_LOCK:
        _MEM_CACHE.clear()
