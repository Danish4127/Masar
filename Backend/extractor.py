"""Syllabus extractor: turns syllabus files (.txt / .pdf) into rows of
masar_course_dataset.xlsx - the exact columns that seed_db.py reads.

Usage:
    python extractor.py syllabus1.txt syllabus2.pdf            # updates masar_course_dataset.xlsx
    python extractor.py syllabus1.txt other.xlsx               # legacy form: last .xlsx argument = output
    python extractor.py -o my_dataset.xlsx a.pdf b.txt

Courses already in the workbook are UPDATED (matched by course code), new ones are appended.
After extracting, run `python seed_db.py` to load the dataset into PostgreSQL.

Two syllabus styles are understood:
  1. Labelled lines   e.g. "COURSE CODE: ISEC312", "PREREQUISITES: ISEC311, CSBP219 (co)",
                            "QUIZZES: 20%" ...
  2. Free text        a normal syllabus - the code, credits, prerequisites and the grading
                      percentages are found with patterns; math/programming/group-work flags are
                      keyword based. These are HEURISTICS: check the resulting Excel rows.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pandas as pd

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:                       
    PDF_SUPPORT = False

from prereq import CODE_RE, normalize_code

DEFAULT_OUTPUT = str(Path(__file__).resolve().parent / "masar_course_dataset.xlsx")
COLUMNS = [
    "Course_Name", "Course_Code", "Prerequisite_Names", "Prerequisites", "Theory_Based", "Problem_Solving", "Has_Math",
    "Has_Programming", "Credit_Hours", "Course_Level", "Number_Major_Assessments", "Group_Work_Required", "Quiz_percentage",
    "Assignment_Project_percentage", "Midterm_percentage", "Final _exam_percentage", "Does the course rely more on exams?",
]

MATH_WORDS = r"calculus|algebra|statistic|probabilit|discrete math|differential|integral|linear|numerical|mathematic|matri(?:x|ces)"
PROG_WORDS = r"programming|coding|python|java\b|c\+\+|\bc#|javascript|source code|algorithm implementation|lab"
GROUP_WORDS = r"group (?:project|work|assignment)|team (?:project|work)|teamwork|in groups|group-based"
PROBLEM_WORDS = r"problem[- ]solving|solve problems|exercises|case stud|design and analy|troubleshoot"

def read_syllabus_content(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        if not PDF_SUPPORT:
            raise RuntimeError("pdfplumber is not installed. Run: pip install pdfplumber")
        with pdfplumber.open(file_path) as pdf:
            return "\n".join((page.extract_text() or "") for page in pdf.pages)
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def _label(content: str, names: list[str]) -> str:
    pattern = r"^\s*(?:" + "|".join(names) + r")\s*[:\-\u2013]\s*(.+?)\s*$"
    m = re.search(pattern, content, flags=re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else ""

def _yes_no(flag: bool) -> str:
    return "Yes" if flag else "No"

def _pct(content: str, words: str) -> float:
    """Fraction (0-1) for a grading component, e.g. 'Midterm exam ....... 25%'."""
    total, found = 0.0, False
    for m in re.finditer(rf"(?:{words})[^\n\d%]{{0,40}}?(\d{{1,3}}(?:\.\d+)?)\s*%", content, flags=re.IGNORECASE):
        total += float(m.group(1)); found = True
    if not found:
        for m in re.finditer(rf"(\d{{1,3}}(?:\.\d+)?)\s*%\s*(?:for\s+|of\s+)?(?:{words})", content, flags=re.IGNORECASE):
            total += float(m.group(1)); found = True
    return round(min(total, 100.0) / 100.0, 4) if found else 0.0

def parse_syllabus_text(file_path: str, known_names: dict | None = None) -> dict | None:
    """Return one dataset row, or None when no course code could be found."""
    content = read_syllabus_content(file_path)
    known_names = known_names or {}

    code = normalize_code(_label(content, ["course code", "code"]))
    if not CODE_RE.fullmatch(code or ""):
        head = "\n".join(content.splitlines()[:60])
        m = CODE_RE.search(head)
        code = normalize_code(m.group(1) + m.group(2)) if m else ""
    if not code:
        return None

    name = _label(content, ["course name", "course title", "title", "name"])
    if not name:
        m = re.search(rf"{re.escape(code[:4])}\s*{code[4:]}\s*[:\-\u2013\u2014|]\s*(.+)", content, flags=re.IGNORECASE)
        name = m.group(1).strip() if m else code
    name = re.sub(r"\s+", " ", name)[:150]

    credits = _label(content, ["credit hours?", "credits?"])
    m = re.search(r"\d+", credits)
    if m:
        credit_hours = int(m.group(0))
    else:
        m = re.search(r"(\d)\s*(?:credit|cr\b)", content, flags=re.IGNORECASE)
        credit_hours = int(m.group(1)) if m else 3

    prereq = _label(content, ["prerequisites?", "pre-?requisites?", "prereq"])
    if not prereq:                                            
        m = re.search(r"pre-?requisites?\s*[:\-\u2013]\s*([^\n]+?)(?:\.\s|\.?$)", content, flags=re.IGNORECASE | re.MULTILINE)
        prereq = m.group(1).strip() if m else ""
    if prereq.lower() in {"none", "n/a", "na", "-", "nil", "no"}:
        prereq = ""
    prereq = prereq[:200]
    prereq_names = "; ".join(known_names.get(c, c) for c in dict.fromkeys(normalize_code(a + b) for a, b in CODE_RE.findall(prereq)))

    quiz = _pct(content, r"quiz(?:zes)?")
    project = _pct(content, r"assignments?|projects?|homework|labs?")
    mid = _pct(content, r"mid-?term(?: exam)?")
    final = _pct(content, r"final(?: exam(?:ination)?)?")
    labelled_n = _label(content, ["number of major assessments", "major assessments"])
    n_assess = int(re.search(r"\d+", labelled_n).group(0)) if re.search(r"\d+", labelled_n or "") else sum(1 for v in (quiz, project, mid, final) if v > 0)

    lower = content.lower()
    return {
        "Course_Name": name, "Course_Code": code, "Prerequisite_Names": prereq_names, "Prerequisites": prereq,
        "Theory_Based": _yes_no(bool(re.search(r"theor|concept|principles", lower))),
        "Problem_Solving": _yes_no(bool(re.search(PROBLEM_WORDS, lower))),
        "Has_Math": _yes_no(bool(re.search(MATH_WORDS, lower))),
        "Has_Programming": _yes_no(bool(re.search(PROG_WORDS, lower))),
        "Credit_Hours": credit_hours, "Course_Level": int(code[re.search(r"\d", code).start()]) * 100,
        "Number_Major_Assessments": n_assess,
        "Group_Work_Required": _yes_no(bool(re.search(GROUP_WORDS, lower))),
        "Quiz_percentage": quiz, "Assignment_Project_percentage": project, "Midterm_percentage": mid, "Final _exam_percentage": final,
        "Does the course rely more on exams?": _yes_no((mid + final) > (quiz + project)),
    }

def process_syllabi(input_files: list[str], output_excel: str = DEFAULT_OUTPUT) -> int:
    existing = pd.read_excel(output_excel) if os.path.isfile(output_excel) else pd.DataFrame(columns=COLUMNS)
    for col in COLUMNS:
        if col not in existing.columns:
            existing[col] = pd.NA
    known = {normalize_code(c): n for c, n in zip(existing["Course_Code"], existing["Course_Name"]) if normalize_code(c)}

    rows = []
    for path in input_files:
        if not os.path.isfile(path):
            print(f"  [skip] file not found: {path}")
            continue
        print(f"  Processing: {path}")
        try:
            row = parse_syllabus_text(path, known)
        except Exception as exc:
            print(f"  [skip] could not read {path}: {exc}")
            continue
        if not row:
            print(f"  [skip] no course code (e.g. ISEC312) found in {path}")
            continue
        print(f"    -> {row['Course_Code']} | {row['Course_Name']}")
        known[row["Course_Code"]] = row["Course_Name"]
        rows.append(row)
    if not rows:
        print("No valid syllabi processed - nothing written.")
        return 0

    new_df = pd.DataFrame(rows, columns=COLUMNS)
    codes = set(new_df["Course_Code"])
    kept = existing[~existing["Course_Code"].map(normalize_code).isin(codes)]
    combined = pd.concat([kept[COLUMNS], new_df], ignore_index=True)
    combined.to_excel(output_excel, index=False)
    print(f"Saved {len(combined)} courses ({len(rows)} added/updated) to {output_excel}")
    print("Next step: python seed_db.py")
    return len(rows)

def main(argv: list[str]) -> int:
    args, output = list(argv), DEFAULT_OUTPUT
    if "-o" in args:
        i = args.index("-o")
        output = args[i + 1] if i + 1 < len(args) else output
        del args[i:i + 2]
    elif len(args) >= 2 and args[-1].lower().endswith(".xlsx"):
        output = args.pop()
    if not args:
        print(__doc__)
        return 1
    return 0 if process_syllabi(args, output) else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
