import csv
import math
import os
from collections import defaultdict, Counter
from sklearn.metrics import cohen_kappa_score

HISSAN_FILE = "/mnt/data/Main Data Analysis of diff files(HissanMainData).csv"
VEER_FILE = "/mnt/data/Main Data Analysis of diff files(VeerMainData).csv"
OUT_DIR = "/mnt/data"

RATING_COLS = [
    "task_success",
    "exact_match",
    "unintended_change_present",
    "unintended_change_type",
    "severity",
    "missed_required_change",
]

BASE_COLS = [
    "Diff_ID", "Model", "case_id", "filename", "Repo Name", "Task Type", "clean_task_type", "PR URL", "diff_file_path"
]

ALLOWED = {
    "task_success": {"Yes", "No", "Partial"},
    "exact_match": {"Yes", "No"},
    "unintended_change_present": {"Yes", "No"},
    "severity": {"None", "Low", "Medium", "High"},
    "missed_required_change": {"Yes", "No"},
}

TYPE_ORDER = [
    "Formatting",
    "Comment/Docstring",
    "Import Change",
    "Naming Overreach",
    "Logic Change",
    "API/Signature Overreach",
    "Extra Refactoring",
    "Unrelated Addition",
    "Unrelated Deletion",
    "Typo Introduced",
    "Missed Required Change",
    "None",
]
TYPE_SET = set(TYPE_ORDER)

def read_csv(path):
    with open(path, newline="", encoding="latin1") as f:
        return list(csv.DictReader(f))

def clean_text(v):
    if v is None:
        return ""
    return str(v).strip()

def normalize_basic(value, col):
    raw = clean_text(value)
    lower = raw.lower().strip()

    if lower in ["", "nan", "na", "n/a"]:
        return None, "missing"

    # yes/no normalization
    if lower in ["yes", "y", "ye", "ys", "yse", "tes"]:
        norm = "Yes"
    elif lower in ["no", "n", "np", "noi"]:
        norm = "No"
    elif col == "task_success" and lower in ["partial", "partially"]:
        norm = "Partial"
    elif col == "severity" and lower == "none":
        norm = "None"
    elif col == "severity" and lower == "low":
        norm = "Low"
    elif col == "severity" and lower in ["medium", "med"]:
        norm = "Medium"
    elif col == "severity" and lower == "high":
        norm = "High"
    else:
        return raw, "invalid"

    if norm not in ALLOWED[col]:
        return raw, "invalid"
    return norm, "valid"

def map_type_piece(piece):
    p = clean_text(piece)
    l = p.lower()
    if not p:
        return None

    # Specific cases first
    if "removed unrelated" in l or "unrelated deletion" in l or "removed unrelated code" in l:
        return "Unrelated Deletion"
    if "added unrelated" in l or "unrelated addition" in l or "added unrelated code" in l:
        return "Unrelated Addition"

    if "formatting" in l or "whitespace" in l or "newline" in l or "no newline" in l:
        return "Formatting"
    if "comment" in l or "docstring" in l:
        return "Comment/Docstring"
    if "import" in l:
        return "Import Change"
    if "naming" in l or "rename" in l:
        return "Naming Overreach"
    if "logic" in l or "syntax-breaking" in l or "condition" in l or "return value" in l or "loop" in l:
        return "Logic Change"
    if "api" in l or "signature" in l or "parameter" in l or "call site" in l:
        return "API/Signature Overreach"
    if "extra refactoring" in l or "refactor" in l:
        return "Extra Refactoring"
    if "typo" in l:
        return "Typo Introduced"
    if "missed required" in l:
        return "Missed Required Change"
    if l == "none":
        return "None"

    return p  # keep unknown text so we can flag it

def normalize_unintended_type(value):
    raw = clean_text(value)
    lower = raw.lower()
    if lower in ["", "nan", "na", "n/a"]:
        return None, "missing"
    if lower == "none":
        return "None", "valid"

    # Treat comma, semicolon, pipe, slash, and newlines as possible separators.
    tmp = raw.replace("\n", ";").replace("|", ";").replace("/", ";")
    # Important: many Veer cells use commas; converting makes order irrelevant.
    tmp = tmp.replace(",", ";")
    pieces = [x.strip() for x in tmp.split(";") if x.strip()]
    mapped = []
    unknown = []
    for piece in pieces:
        m = map_type_piece(piece)
        if m:
            mapped.append(m)
            if m not in TYPE_SET:
                unknown.append(m)

    if not mapped:
        return None, "missing"

    # If None appears with another type, remove None because actual types are more informative.
    mapped_set = set(mapped)
    if len(mapped_set) > 1 and "None" in mapped_set:
        mapped_set.remove("None")

    # Canonical order means "Logic Change; Formatting" equals "Formatting, Logic Change".
    canonical = [t for t in TYPE_ORDER if t in mapped_set]
    extra = sorted([t for t in mapped_set if t not in TYPE_SET])
    result = "; ".join(canonical + extra)

    if unknown:
        return result, "invalid"
    return result, "valid"

def normalize(value, col):
    if col == "unintended_change_type":
        return normalize_unintended_type(value)
    return normalize_basic(value, col)

def make_key(row):
    return clean_text(row.get("Diff_ID"))

hissan_rows = read_csv(HISSAN_FILE)
veer_rows = read_csv(VEER_FILE)
h_by_key = {make_key(r): r for r in hissan_rows}
v_by_key = {make_key(r): r for r in veer_rows}
all_keys = sorted(set(h_by_key) | set(v_by_key))

summary_rows = []
disagreement_rows = []
adjudication_rows = []
invalid_rows = []

# Build comparison data keyed by model and column for kappa
comparison_values = defaultdict(lambda: defaultdict(list))  # model -> col -> [(h_norm, v_norm)]

for key in all_keys:
    h = h_by_key.get(key)
    v = v_by_key.get(key)
    base_source = h or v or {}
    base = {c: clean_text(base_source.get(c)) for c in BASE_COLS}
    model = base.get("Model", "")

    row_has_problem = False
    needs_discussion = []
    invalid_vars = []

    adj = dict(base)
    adj["IRR_Status"] = "Agreement"

    disag = dict(base)

    for col in RATING_COLS:
        h_raw = clean_text(h.get(col)) if h else "MISSING_ROW"
        v_raw = clean_text(v.get(col)) if v else "MISSING_ROW"
        h_norm, h_status = normalize(h_raw, col) if h else (None, "missing-row")
        v_norm, v_status = normalize(v_raw, col) if v else (None, "missing-row")

        h_valid = h_status == "valid"
        v_valid = v_status == "valid"
        agree = (h_valid and v_valid and h_norm == v_norm)

        # columns for the disagreement/adjudication sheets
        disag[f"Hissan_{col}_raw"] = h_raw
        disag[f"Veer_{col}_raw"] = v_raw
        disag[f"Hissan_{col}_normalized"] = h_norm
        disag[f"Veer_{col}_normalized"] = v_norm
        disag[f"{col}_agreement"] = "Yes" if agree else "No"
        disag[f"{col}_status"] = "valid" if (h_valid and v_valid) else f"Hissan={h_status}; Veer={v_status}"

        adj[f"Hissan_{col}"] = h_norm
        adj[f"Veer_{col}"] = v_norm
        if agree:
            adj[f"Final_{col}"] = h_norm
            adj[f"Decision_Needed_{col}"] = "No"
        else:
            adj[f"Final_{col}"] = "DISCUSS"
            adj[f"Decision_Needed_{col}"] = "Yes"
            row_has_problem = True
            needs_discussion.append(col)

        if not (h_valid and v_valid):
            invalid_vars.append(col)
            invalid_rows.append({
                **base,
                "Variable": col,
                "Hissan_raw": h_raw,
                "Veer_raw": v_raw,
                "Hissan_normalized": h_norm,
                "Veer_normalized": v_norm,
                "Hissan_status": h_status,
                "Veer_status": v_status,
            })
        else:
            comparison_values[model][col].append((h_norm, v_norm))

    if row_has_problem:
        disag["Needs_Discussion_For"] = "; ".join(needs_discussion)
        disag["Invalid_or_Missing_Labels"] = "; ".join(invalid_vars)
        disagreement_rows.append(disag)
        adj["IRR_Status"] = "Needs discussion"
        adj["Needs_Discussion_For"] = "; ".join(needs_discussion)
    else:
        adj["Needs_Discussion_For"] = ""

    adjudication_rows.append(adj)

# Summary kappa per model and column
for model in sorted(comparison_values):
    for col in RATING_COLS:
        pairs = comparison_values[model][col]
        total_model_keys = len([k for k in all_keys if (h_by_key.get(k) or v_by_key.get(k) or {}).get('Model','').strip()==model])
        valid_pairs = len(pairs)
        if valid_pairs:
            h_vals = [p[0] for p in pairs]
            v_vals = [p[1] for p in pairs]
            agreements = sum(1 for a, b in pairs if a == b)
            disagreements = valid_pairs - agreements
            pct = agreements / valid_pairs * 100
            try:
                kappa = cohen_kappa_score(h_vals, v_vals)
            except Exception:
                kappa = None
        else:
            agreements = disagreements = 0
            pct = None
            kappa = None
        summary_rows.append({
            "Model": model,
            "Variable": col,
            "Total Rows for Model": total_model_keys,
            "Valid Pairs Used in Kappa": valid_pairs,
            "Invalid/Missing Pairs Excluded": total_model_keys - valid_pairs,
            "Agreements": agreements,
            "Disagreements": disagreements,
            "Percent Agreement": round(pct, 2) if pct is not None else "",
            "Cohen Kappa": round(kappa, 4) if kappa is not None and not math.isnan(kappa) else "",
        })

def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

summary_fields = ["Model", "Variable", "Total Rows for Model", "Valid Pairs Used in Kappa", "Invalid/Missing Pairs Excluded", "Agreements", "Disagreements", "Percent Agreement", "Cohen Kappa"]
disag_fields = BASE_COLS + ["Needs_Discussion_For", "Invalid_or_Missing_Labels"]
for col in RATING_COLS:
    disag_fields += [f"Hissan_{col}_raw", f"Veer_{col}_raw", f"Hissan_{col}_normalized", f"Veer_{col}_normalized", f"{col}_agreement", f"{col}_status"]
adj_fields = BASE_COLS + ["IRR_Status", "Needs_Discussion_For"]
for col in RATING_COLS:
    adj_fields += [f"Hissan_{col}", f"Veer_{col}", f"Final_{col}", f"Decision_Needed_{col}"]
invalid_fields = BASE_COLS + ["Variable", "Hissan_raw", "Veer_raw", "Hissan_normalized", "Veer_normalized", "Hissan_status", "Veer_status"]

write_csv(os.path.join(OUT_DIR, "IRR_Summary.csv"), summary_rows, summary_fields)
write_csv(os.path.join(OUT_DIR, "IRR_Disagreements_To_Discuss.csv"), disagreement_rows, disag_fields)
write_csv(os.path.join(OUT_DIR, "IRR_Final_Adjudication_Template.csv"), adjudication_rows, adj_fields)
write_csv(os.path.join(OUT_DIR, "IRR_Invalid_Labels_To_Fix.csv"), invalid_rows, invalid_fields)

print("Summary rows:", len(summary_rows))
print("Rows needing discussion:", len(disagreement_rows))
print("Invalid/missing labels:", len(invalid_rows))
