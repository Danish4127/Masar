import sys
import re
import os
import pandas as pd

try:
    import pdfplumber
    PDF_SUPPORT = True
except ImportError:                                
    PDF_SUPPORT = False

DEFAULT_OUTPUT = "masar_course_dataset.xlsx"


def read_syllabus_content(file_path: str) -> str:
    """Reads a syllabus file, supporting both .txt and .pdf. Raises a clear
    error if a .pdf is given but pdfplumber isn't installed."""
    ext = os.path.splitext(file_path)[1].lower()

    if ext == ".pdf":
        if not PDF_SUPPORT:
            raise RuntimeError(
                "pdfplumber is not installed. Run: pip install pdfplumber"
            )
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                text_parts.append(page_text)
        return "\n".join(text_parts)

                         
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def parse_syllabus_text(file_path: str) -> dict:
    content = read_syllabus_content(file_path)

    def extract_val(pattern, default=""):
        match = re.search(pattern, content, re.IGNORECASE)
        return match.group(1).strip() if match else default

    prerequisites = extract_val(r"PREREQUISITES:\s*(.+)", default="")
    if prerequisites.lower() in ("none", "n/a", "-"):
        prerequisites = ""

    return {
        "Course_Code": extract_val(r"COURSE CODE:\s*(.+)"),
        "Course_Name": extract_val(r"COURSE NAME:\s*(.+)"),
        "Credits": int(extract_val(r"CREDITS:\s*(\d+)", default="3")),
        "Subject_Area": extract_val(r"SUBJECT AREA:\s*(.+)", default="General"),
        "Difficulty_Level": int(extract_val(r"DIFFICULTY:\s*(\d+)", default="3")),
        "Math_Intensity": int(extract_val(r"MATH INTENSITY:\s*(\d+)", default="1")),
        "Weekly_Workload_Hours": int(extract_val(r"WEEKLY WORKLOAD:\s*(\d+)", default="5")),
        "Assessment_Type": extract_val(r"ASSESSMENT TYPE:\s*(.+)", default="Exam"),
        "Prerequisites": prerequisites,
        "Group_Work_Required": "Yes" if re.search(r"GROUP WORK:\s*Yes", content, re.IGNORECASE) else "No",
        "Course_Level": int(extract_val(r"COURSE LEVEL:\s*(\d+)", default="300")),
    }


def process_syllabi(input_files: list[str], output_excel: str = DEFAULT_OUTPUT):
    extracted_records = []

    for file_path in input_files:
        if not os.path.exists(file_path):
            print(f"[X] File not found: {file_path}")
            continue
        try:
            data = parse_syllabus_text(file_path)
            extracted_records.append(data)
            print(f"[OK] Extracted: {file_path} -> {data['Course_Code']} ({data['Course_Name']})")
        except Exception as exc:
            print(f"[X] Failed to process {file_path}: {exc}")

    if not extracted_records:
        print("No valid syllabus records extracted.")
        return

    new_df = pd.DataFrame(extracted_records)

    next_id = 1
    if os.path.exists(output_excel):
        existing_df = pd.read_excel(output_excel)
        if "Course_ID" in existing_df.columns and not existing_df.empty:
            next_id = int(existing_df["Course_ID"].max()) + 1
        new_df.insert(0, "Course_ID", range(next_id, next_id + len(new_df)))
        combined_df = pd.concat([existing_df, new_df]).drop_duplicates(subset=['Course_Code'], keep='last')
    else:
        new_df.insert(0, "Course_ID", range(1, len(new_df) + 1))
        combined_df = new_df

    combined_df.to_excel(output_excel, index=False)
    print(f"\n[SUCCESS] Updated: {os.path.abspath(output_excel)}")
    print("Next step: run python seed_db.py to load this into Neon.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extractor.py <syllabus1.txt|.pdf> [syllabus2.txt|.pdf ...] [output.xlsx]")
        print(f"  (output.xlsx defaults to {DEFAULT_OUTPUT})")
        print("  Both .txt and .pdf syllabus files are supported and can be mixed in one run.")
    else:
        args = sys.argv[1:]
        if args[-1].endswith(".xlsx"):
            target_excel = args[-1]
            files_to_process = args[:-1]
        else:
            target_excel = DEFAULT_OUTPUT
            files_to_process = args

        process_syllabi(files_to_process, target_excel)
