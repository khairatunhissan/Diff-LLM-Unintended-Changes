import os
import py_compile
import csv

ROOT_FOLDER = "cases"
OUTPUT_CSV = "syntax_check_results.csv"

results = []

model_counts = {
    "GPT": 0,
    "Gemini": 0,
    "Claude": 0,
    "Unknown_LLM": 0
}

def detect_model(filename):
    filename_lower = filename.lower().strip()

    if filename_lower.startswith("llm_gemini_"):
        return "Gemini"
    elif filename_lower.startswith("llm_claude_"):
        return "Claude"
    elif filename_lower.startswith("llm_"):
        return "GPT"
    else:
        return "Unknown_LLM"

for root, dirs, files in os.walk(ROOT_FOLDER):
    for file in files:
        file_clean = file.strip()
        file_lower = file_clean.lower()

        # Check all LLM-generated Python files
        if file_lower.endswith(".py") and file_lower.startswith("llm_"):
            file_path = os.path.join(root, file)

            case_id = os.path.basename(root)
            model = detect_model(file_clean)

            model_counts[model] += 1

            try:
                py_compile.compile(file_path, doraise=True)

                results.append({
                    "case_id": case_id,
                    "model": model,
                    "file_path": file_path,
                    "filename": file_clean,
                    "syntax_valid": "Yes",
                    "syntax_error_message": "None"
                })

            except py_compile.PyCompileError as e:
                error_lines = str(e).splitlines()
                short_error = error_lines[-1] if error_lines else "Unknown syntax error"

                results.append({
                    "case_id": case_id,
                    "model": model,
                    "file_path": file_path,
                    "filename": file_clean,
                    "syntax_valid": "No",
                    "syntax_error_message": short_error
                })

with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "case_id",
            "model",
            "file_path",
            "filename",
            "syntax_valid",
            "syntax_error_message"
        ]
    )
    writer.writeheader()
    writer.writerows(results)

print(f"Done. Checked {len(results)} LLM Python files.")
print(f"GPT files checked: {model_counts['GPT']}")
print(f"Gemini files checked: {model_counts['Gemini']}")
print(f"Claude files checked: {model_counts['Claude']}")
print(f"Unknown LLM files checked: {model_counts['Unknown_LLM']}")
print(f"Results saved to {OUTPUT_CSV}")