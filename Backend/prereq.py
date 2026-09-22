"""Prerequisite parsing shared by seed_db.py and recommender.py.

The course dataset writes prerequisites as free text, for example:

    "MATH105"                          one prerequisite
    "CSBP121, CSBP219 (co)"            CSBP121 must be passed, CSBP219 may be taken together
    "CENG205 (co/pre) & PHYS105"       CENG205 passed OR taken together, and PHYS105 passed
    "ITBP301 or ITBP280"               either course is enough
    "Minimum 80 completed credit hours"  a credit-hour threshold

This module turns that text into a structured ``Requirement``:

* ``groups``  - AND-list of groups; each group is an OR-list of ``(code, kind)``
                where kind is ``"pre"`` (must already be completed) or ``"co"``
                (completed OR taken in the same semester).
* ``min_credits`` - minimum completed credit hours (0 when not required).
* ``notes``   - fragments that could not be understood (never used to block a
                student, because we cannot verify them automatically).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CODE_RE = re.compile(r"\b([A-Za-z]{2,5})\s*(\d{3,4})\b")
_TAG_RE = re.compile(r"\(\s*(co\s*/\s*pre|pre\s*/\s*co|co|pre)\s*\)", re.IGNORECASE)
_CREDIT_RE = re.compile(
    r"(?:minimum|min\.?|at\s+least)\s+(\d{1,3})\s+(?:completed\s+)?(?:credit\s*hours?|credits?)",
    re.IGNORECASE,
)
_EMPTY_WORDS = {"", "none", "n/a", "na", "-", "nan", "null"}

Alt = tuple                       

@dataclass(frozen=True)
class Requirement:
    groups: tuple = ()
    min_credits: int = 0
    notes: tuple = ()

    @property
    def is_empty(self) -> bool:
        return not self.groups and not self.min_credits

    def all_codes(self) -> list:
        seen, out = set(), []
        for group in self.groups:
            for code, _ in group:
                if code not in seen:
                    seen.add(code)
                    out.append(code)
        return out

def normalize_code(value) -> str:
    if value is None:
        return ""
    text = str(value)
    if text.strip().lower() in ("nan", "none"):
        return ""
    return re.sub(r"\s+", "", text).strip().upper()

def parse_requirement(value) -> Requirement:
    """Parse prerequisite text into a ``Requirement`` (never raises)."""
    if value is None:
        return Requirement()
    text = str(value).strip()
    if text.lower() in _EMPTY_WORDS:
        return Requirement()

    min_credits = 0
    m = _CREDIT_RE.search(text)
    if m:
        min_credits = int(m.group(1))
        text = (text[: m.start()] + " " + text[m.end():]).strip(" ,;&")

                                   
    def _tag(match):
        return " [co] " if "co" in match.group(1).lower() else " [pre] "

    text = _TAG_RE.sub(_tag, text)

    groups, notes = [], []
    for part in re.split(r"\s*(?:,|;|&|\+|\band\b)\s*", text, flags=re.IGNORECASE):
        part = part.strip()
        if not part:
            continue
        alts, seen = [], set()
        for chunk in re.split(r"\s*(?:\bor\b|/)\s*", part, flags=re.IGNORECASE):
            chunk = chunk.strip()
            cm = CODE_RE.search(chunk)
            if not cm:
                cleaned = re.sub(r"\[(?:co|pre)\]", "", chunk).strip()
                if cleaned:
                    notes.append(cleaned)
                continue
            code = normalize_code(cm.group(1) + cm.group(2))
            kind = "co" if "[co]" in chunk.lower() else "pre"
            if code not in seen:
                seen.add(code)
                alts.append((code, kind))
        if alts:
            groups.append(tuple(alts))
    return Requirement(groups=tuple(groups), min_credits=min_credits, notes=tuple(notes))

def describe_group(group, names: dict | None = None) -> str:
    names = names or {}
    parts = [names.get(code, code) for code, _ in group]
    return " or ".join(parts)
