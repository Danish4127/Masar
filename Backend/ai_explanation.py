from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from typing import Any

import requests
from sqlalchemy import bindparam, text

from db import engine


logger = logging.getLogger("masar.ai_explanation")

AI_EXPLANATION_CACHE_VERSION = "v2"
DEFAULT_MODEL = "openai/gpt-oss-20b"
DEFAULT_AI_API_BASE = "https://api.groq.com/openai/v1"
DEFAULT_TIMEOUT_SECONDS = 2.5


def _build_prompt(course_items: list[dict[str, Any]]) -> tuple[str, str]:
    system_prompt = """
You are the natural-language explanation layer for an academic course
recommendation system.

The recommendation engine has already decided which courses are recommended.
Your job is ONLY to turn the supplied structured facts into short,
natural-language explanations.

Rules:
- Do not change, rank, approve, reject, or re-score any recommendation.
- Use ONLY the supplied facts.
- Never invent prerequisites, grades, difficulty, workload, skills, goals,
  benefits, scores, or other student/course information.
- Never mention student name, student ID, email, password, or other identity
  information.
- Do not introduce new numeric values.
- Do not make GPA or academic-success guarantees.
- Keep each explanation to 1–2 natural sentences.
- Explain why the course fits the supplied academic/profile/workload facts.
- Return ONLY a JSON object.
- The JSON keys must be the exact course codes supplied by the user.
- The value for each key must be the explanation string.
""".strip()

    user_prompt = json.dumps(
        {
            "course_facts": course_items,
            "output_format": {
                "COURSE_CODE": "short natural-language explanation"
            },
        },
        ensure_ascii=False,
    )

    return system_prompt, user_prompt


def _parse_json_object(content: str) -> dict[str, str]:
    if not isinstance(content, str):
        return {}

    content = content.strip()

    if not content:
        return {}

    # Remove accidental markdown code fences.
    content = re.sub(
        r"^```(?:json)?\s*",
        "",
        content,
        flags=re.IGNORECASE,
    )
    content = re.sub(r"\s*```$", "", content)

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        # Try extracting the first JSON object if the model added extra text.
        match = re.search(r"\{.*\}", content, flags=re.DOTALL)
        if not match:
            return {}

        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return {}

    if not isinstance(parsed, dict):
        return {}

    result: dict[str, str] = {}

    for key, value in parsed.items():
        if not isinstance(key, str):
            continue

        if not isinstance(value, str):
            continue

        explanation = value.strip()

        if explanation:
            result[key.strip()] = explanation

    return result


def _allowed_numbers(facts: dict[str, Any]) -> set[str]:
    allowed: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, bool):
            return

        if isinstance(value, (int, float)):
            allowed.add(str(value))
            allowed.add(f"{value:g}")
            return

        if isinstance(value, str):
            for match in re.findall(r"\d+(?:\.\d+)?", value):
                allowed.add(match)

        elif isinstance(value, list):
            for item in value:
                collect(item)

        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(facts)

    return allowed


def _validate_explanation(
    explanation: str,
    facts: dict[str, Any],
) -> bool:
    if not isinstance(explanation, str):
        return False

    explanation = explanation.strip()

    if not 40 <= len(explanation) <= 650:
        return False

    lowered = explanation.lower()

    forbidden_phrases = (
        "student id",
        "student_id",
        "email",
        "password",
    )

    if any(phrase in lowered for phrase in forbidden_phrases):
        return False

    explanation_numbers = re.findall(
        r"\d+(?:\.\d+)?",
        explanation,
    )

    allowed_numbers = _allowed_numbers(facts)

    for number in explanation_numbers:
        if number not in allowed_numbers:
            return False

    return True


def _cache_key(
    course_code: str,
    facts: dict[str, Any],
    model: str,
) -> str:
    payload = {
        "version": AI_EXPLANATION_CACHE_VERSION,
        "course_code": course_code,
        "model": model,
        "facts": facts,
    }

    serialized = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )

    return hashlib.sha256(
        serialized.encode("utf-8")
    ).hexdigest()


_CACHE_TABLE_READY = False
_CACHE_TABLE_LOCK = threading.Lock()


def ensure_ai_explanation_cache_table() -> None:
    """Create the cache table if schema.sql was never applied. Runs once per
    process, under a lock, because the three plans are generated in parallel
    threads and concurrent CREATE TABLE IF NOT EXISTS can race in PostgreSQL."""
    global _CACHE_TABLE_READY
    if _CACHE_TABLE_READY:
        return
    with _CACHE_TABLE_LOCK:
        if _CACHE_TABLE_READY:
            return
        _create_cache_table()
        _CACHE_TABLE_READY = True


def _create_cache_table() -> None:
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS ai_explanation_cache (
                    cache_key VARCHAR(64) PRIMARY KEY,
                    course_code VARCHAR(20) NOT NULL,
                    model VARCHAR(100) NOT NULL,
                    explanation TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        )

        connection.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS
                idx_ai_explanation_cache_course
                ON ai_explanation_cache(course_code)
                """
            )
        )


def _get_cached_explanations(
    cache_entries: list[tuple[str, str]],
) -> dict[str, str]:
    if not cache_entries:
        return {}

    cache_keys = [item[0] for item in cache_entries]

    statement = text(
        """
        SELECT cache_key, explanation
        FROM ai_explanation_cache
        WHERE cache_key IN :cache_keys
        """
    ).bindparams(
        bindparam("cache_keys", expanding=True)
    )

    with engine.begin() as connection:
        rows = connection.execute(
            statement,
            {"cache_keys": cache_keys},
        ).mappings().all()

    key_to_course = {
        cache_key: course_code
        for cache_key, course_code in cache_entries
    }

    result: dict[str, str] = {}

    for row in rows:
        cache_key = row["cache_key"]
        explanation = row["explanation"]

        course_code = key_to_course.get(cache_key)

        if course_code and isinstance(explanation, str):
            result[course_code] = explanation

    return result


def _save_cached_explanations(
    items: list[dict[str, Any]],
    explanations: dict[str, str],
    model: str,
) -> None:
    if not explanations:
        return

    rows: list[dict[str, Any]] = []

    for item in items:
        course_code = str(
            item.get("course_code", "")
        ).strip()

        if not course_code:
            continue

        explanation = explanations.get(course_code)

        if not explanation:
            continue

        facts = item.get("facts", {})

        rows.append(
            {
                "cache_key": _cache_key(
                    course_code,
                    facts,
                    model,
                ),
                "course_code": course_code,
                "model": model,
                "explanation": explanation,
            }
        )

    if not rows:
        return

    with engine.begin() as connection:
        for row in rows:
            connection.execute(
                text(
                    """
                    INSERT INTO ai_explanation_cache
                        (cache_key, course_code, model, explanation)
                    VALUES
                        (:cache_key, :course_code, :model, :explanation)
                    ON CONFLICT (cache_key)
                    DO UPDATE SET
                        explanation = EXCLUDED.explanation,
                        model = EXCLUDED.model
                    """
                ),
                row,
            )


def _call_ai(
    course_items: list[dict[str, Any]],
    api_key: str,
    model: str,
    api_base: str,
    timeout: float,
) -> dict[str, str]:
    system_prompt, user_prompt = _build_prompt(course_items)

    payload: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
        # Reasoning models (e.g. gpt-oss) spend part of this budget on hidden
        # "thinking" tokens; a small budget can yield an EMPTY answer.
        "max_completion_tokens": 1000,
        "response_format": {"type": "json_object"},
    }
    if "gpt-oss" in model:
        payload["reasoning_effort"] = "low"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    url = f"{api_base}/chat/completions"

    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code == 400 and "response_format" in payload:
        # Some providers/models do not support JSON mode. The parser below
        # already copes with fenced / chatty JSON, so retry once without it.
        logger.info("AI provider rejected response_format (HTTP 400); retrying without it.")
        payload.pop("response_format")
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)

    response.raise_for_status()

    payload = response.json() or {}

    choices = payload.get("choices", [])

    if not choices:
        return {}

    message = choices[0].get("message", {})

    if not isinstance(message, dict):
        return {}

    content = message.get("content", "")

    if not isinstance(content, str):
        return {}

    return _parse_json_object(content)


def generate_ai_explanations(
    course_facts: list[dict[str, Any]],
) -> dict[str, str]:
    """
    Generate natural-language explanations for already-selected courses.

    The deterministic recommendation engine remains the source of truth.
    This function only converts structured recommendation facts into prose.

    Expected input:

    [
        {
            "course_code": "MATH105",
            "facts": {
                ...
            }
        }
    ]

    Returns:

    {
        "MATH105": "This course fits ..."
    }
    """

    if not course_facts:
        return {}

    enabled = os.getenv(
        "AI_EXPLANATION_ENABLED",
        "false",
    ).strip().lower()

    if enabled not in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return {}

    api_key = os.getenv(
        "AI_API_KEY",
        "",
    ).strip()

    if not api_key:
        logger.warning(
            "AI_EXPLANATION_ENABLED=true but AI_API_KEY is empty - "
            "using deterministic explanations."
        )
        return {}

    model = os.getenv(
        "AI_MODEL",
        DEFAULT_MODEL,
    ).strip() or DEFAULT_MODEL

    api_base = os.getenv(
        "AI_API_BASE",
        DEFAULT_AI_API_BASE,
    ).strip().rstrip("/")

    try:
        timeout = float(
            os.getenv("AI_EXPLANATION_TIMEOUT_SECONDS")
            or os.getenv("AI_TIMEOUT_SECONDS")
            or DEFAULT_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS

    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT_SECONDS

    try:
        ensure_ai_explanation_cache_table()
    except Exception as exc:
        logger.warning(
            "Could not ensure ai_explanation_cache table (%s: %s) - "
            "using deterministic explanations.",
            type(exc).__name__,
            exc,
        )
        return {}

    cache_entries: list[tuple[str, str]] = []
    missing_items: list[dict[str, Any]] = []

    for item in course_facts:
        course_code = str(
            item.get("course_code", "")
        ).strip()

        facts = item.get("facts", {})

        if not course_code or not isinstance(facts, dict):
            continue

        cache_entries.append(
            (
                _cache_key(
                    course_code,
                    facts,
                    model,
                ),
                course_code,
            )
        )

    try:
        cached = _get_cached_explanations(
            cache_entries
        )
    except Exception as exc:
        logger.warning(
            "AI explanation cache read failed (%s: %s) - continuing without cache.",
            type(exc).__name__,
            exc,
        )
        cached = {}

    cached_codes = set(cached.keys())

    for item in course_facts:
        course_code = str(
            item.get("course_code", "")
        ).strip()

        if not course_code:
            continue

        if course_code in cached_codes:
            continue

        facts = item.get("facts", {})

        if not isinstance(facts, dict):
            continue

        missing_items.append(
            {
                "course_code": course_code,
                "facts": facts,
            }
        )

    if not missing_items:
        return cached

    try:
        generated = _call_ai(
            missing_items,
            api_key,
            model,
            api_base,
            timeout,
        )
    except requests.exceptions.Timeout:
        logger.warning(
            "AI explanation call timed out after %.1fs - using deterministic text.",
            timeout,
        )
        return cached
    except requests.exceptions.HTTPError as exc:
        # Usually a wrong key, wrong model name or wrong AI_API_BASE; the
        # response body normally says exactly why.
        body = ""
        try:
            body = exc.response.text[:300]
        except Exception:
            pass
        logger.warning(
            "AI explanation call failed with HTTP %s: %s - using deterministic text.",
            getattr(exc.response, "status_code", "?"),
            body,
        )
        return cached
    except Exception as exc:
        # AI is an enhancement layer. If it fails, the deterministic
        # recommender will continue using its normal fallback reason.
        logger.warning(
            "AI explanation call failed (%s: %s) - using deterministic text.",
            type(exc).__name__,
            exc,
        )
        return cached

    if not generated:
        logger.warning(
            "AI explanation response was empty or not valid JSON - using deterministic text."
        )

    validated: dict[str, str] = {}

    facts_by_code = {
        str(item["course_code"]).strip(): item.get(
            "facts",
            {},
        )
        for item in missing_items
    }

    for course_code, explanation in generated.items():
        normalized_code = str(
            course_code
        ).strip()

        facts = facts_by_code.get(
            normalized_code
        )

        if not isinstance(facts, dict):
            continue

        if _validate_explanation(
            explanation,
            facts,
        ):
            validated[
                normalized_code
            ] = explanation.strip()
        else:
            logger.info(
                "AI explanation for %s rejected by validation - using deterministic text.",
                normalized_code,
            )

    if validated:
        logger.info(
            "AI explanations generated for %d/%d course(s) (model=%s).",
            len(validated),
            len(missing_items),
            model,
        )
        try:
            _save_cached_explanations(
                missing_items,
                validated,
                model,
            )
        except Exception as exc:
            logger.warning(
                "AI explanation cache write failed (%s: %s) - explanations still returned.",
                type(exc).__name__,
                exc,
            )

    result = dict(cached)
    result.update(validated)

    return result