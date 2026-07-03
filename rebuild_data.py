#!/usr/bin/env python3
"""Complete rebuild of staar_2026.json from raw CSVs with correct column parsing."""
import json, os, csv
from collections import defaultdict

RAW_DIR = "/home/writingtired/texas-dashboard-demo/data/raw"
DATA_DIR = "/home/writingtired/texas-dashboard-demo/data"

def sf(s):
    s = s.strip() if s else ""
    if not s: return None
    try: return float(s)
    except: return None

def si(s):
    s = s.strip() if s else ""
    if not s: return None
    try: return int(s.replace(",", ""))
    except: return None

# Fresh structures
staar_data = {}
district_info = {}

def ensure_d(cdc, org):
    if cdc not in staar_data:
        # Extract clean name
        name = org.split("(")[0].strip() if "(" in org else org
        staar_data[cdc] = {"name": name, "grades_3_8": {}, "eoc": {}, "ecr": {}}
    if cdc not in district_info:
        name = org.split("(")[0].strip() if "(" in org else org
        county = ""
        if "(" in org and ")" in org:
            cnty_raw = org.split("(")[1].replace("County)", "").strip()
            county = cnty_raw.replace("County", "").strip()
        district_info[cdc] = {"name": name, "county": county, "region": ""}

# ── STAAR 3-8 Scores ──
print("★ STAAR 3-8 Scores (dynamic header parsing)")
for grade in range(3, 9):
    fp = os.path.join(RAW_DIR, f"staar_3-8_g0{grade}_scores.csv")
    if not os.path.exists(fp): 
        print(f"  ! Missing grade {grade}"); continue
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        # Find main-subject columns
        subj_cols = {}
        for idx, h in enumerate(headers):
            h = h.strip()
            if h.startswith("STAAR - ") and h.endswith("|Tests Taken") and "Spanish" not in h:
                subj = h.replace("STAAR - ", "").replace("|Tests Taken", "").strip()
                subj_cols[subj] = idx
        row_count = 0
        for row in reader:
            if len(row) < 5: continue
            cdc = row[1].strip()
            org = row[0].strip()
            if not cdc: continue
            ensure_d(cdc, org)
            gs = str(grade)
            for subj, base in subj_cols.items():
                if base + 9 >= len(row): continue
                t = si(row[base])
                if t is None or t == 0: continue
                if gs not in staar_data[cdc]["grades_3_8"]:
                    staar_data[cdc]["grades_3_8"][gs] = {}
                staar_data[cdc]["grades_3_8"][gs][subj] = {
                    "tests_taken": t,
                    "avg_scale": si(row[base+1]),
                    "dnm_pct": sf(row[base+3]),
                    "app_pct": sf(row[base+5]),
                    "meets_pct": sf(row[base+7]),
                    "mast_pct": sf(row[base+9]),
                }
            row_count += 1
        print(f"  Grade {grade}: {row_count} rows, subjects: {', '.join(subj_cols.keys())}")

# ── STAAR 3-8 ECR ──
print("\n★ STAAR 3-8 ECR")
for grade in range(3, 9):
    fp = os.path.join(RAW_DIR, f"staar_3-8_g0{grade}_ecr.csv")
    if not os.path.exists(fp): continue
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)
        row_count = 0
        for row in reader:
            if len(row) < 5: continue
            cdc = row[1].strip()
            org = row[0].strip()
            if not cdc: continue
            ensure_d(cdc, org)
            try: vn = int(row[2]) if row[2].strip() else None
            except: vn = None
            if vn is None or vn == 0: continue
            ratings = {}
            for r in range(11):
                pi = 4 + r * 2
                if pi < len(row):
                    try: p = float(row[pi]) if row[pi].strip() else 0; ratings[str(r)] = p
                    except: pass
            staar_data[cdc]["ecr"][str(grade)] = {"valid_n": vn, "ratings": ratings}
            row_count += 1
        print(f"  Grade {grade}: {row_count} districts with ECR")

# ── EOC Scores (each file independently) ──
print("\n★ EOC Scores")
eoc_files = [
    ("eoc_algebra_i_scores.csv", "Algebra I"),
    ("eoc_biology_scores.csv", "Biology"),
    ("eoc_english_i_scores.csv", "English I"),
    ("eoc_english_ii_scores.csv", "English II"),
    ("eoc_us_history_scores.csv", "U.S. History"),
]
# EOC cols: Org(0), CDC(1), Admin(2), then per subject block starting at base+0
# All EOC files have the same 291-col structure; we read the subject at its known offset
EOC_COLS = {
    "Algebra I": 3, "Biology": 35, "English I": 67,
    "English II": 99, "U.S. History": 195,
}
for efn, ename in eoc_files:
    fp = os.path.join(RAW_DIR, efn)
    if not os.path.exists(fp): continue
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f); next(reader)
        base = EOC_COLS[ename]
        c = 0
        for row in reader:
            if len(row) < base + 10: continue
            cdc = row[1].strip(); org = row[0].strip()
            if not cdc: continue
            ensure_d(cdc, org)
            t = si(row[base])
            if t is None or t == 0: continue
            staar_data[cdc]["eoc"][ename] = {
                "tests_taken": t,
                "avg_scale": si(row[base+1]),
                "dnm_pct": sf(row[base+3]),
                "app_pct": sf(row[base+5]),
                "meets_pct": sf(row[base+7]),
                "mast_pct": sf(row[base+9]),
            }
            c += 1
        print(f"  {ename}: {c} districts")

# ── EOC ECR ──
print("\n★ EOC ECR")
for efn, ename in [("eoc_english_i_ecr.csv", "English I"), ("eoc_english_ii_ecr.csv", "English II")]:
    fp = os.path.join(RAW_DIR, efn)
    if not os.path.exists(fp): continue
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f); next(reader)
        c = 0
        for row in reader:
            if len(row) < 5: continue
            cdc = row[1].strip(); org = row[0].strip()
            if not cdc: continue
            ensure_d(cdc, org)
            try: vn = int(row[2]) if row[2].strip() else None
            except: vn = None
            if vn is None or vn == 0: continue
            ratings = {}
            for r in range(11):
                pi = 4 + r * 2
                if pi < len(row):
                    try: p = float(row[pi]) if row[pi].strip() else 0; ratings[str(r)] = p
                    except: pass
            staar_data[cdc]["ecr"][ename] = {"valid_n": vn, "ratings": ratings}
            c += 1
        print(f"  {ename}: {c} districts")

# ── Summary ──
print(f"\n{'='*50}")
print(f"Total districts: {len(staar_data)}")
print(f"Districts with grade data: {len([c for c in staar_data if staar_data[c]['grades_3_8']])}")
print(f"Districts with EOC data: {len([c for c in staar_data if staar_data[c]['eoc']])}")
print(f"Districts with ECR data: {len([c for c in staar_data if staar_data[c]['ecr']])}")

# Verify Farmersville
fv = staar_data.get("043904", {})
print(f"\n★ Farmersville ISD Verification:")
for g in sorted(fv.get("grades_3_8", {}).keys()):
    subs = list(fv["grades_3_8"][g].keys())
    for s in subs:
        d = fv["grades_3_8"][g][s]
        print(f"  Gr{g} {s}: N={d['tests_taken']}, Avg={d['avg_scale']}, App={d['app_pct']}%, Meets={d['meets_pct']}%")
print(f"  EOC: {', '.join(fv.get('eoc', {}).keys())}")
if fv.get("ecr"):
    print(f"  ECR grades/subjects: {', '.join(fv['ecr'].keys())}")

# ── Save ──
with open(os.path.join(DATA_DIR, "staar_2026.json"), "w") as f:
    json.dump(staar_data, f)
print("\n✓ staar_2026.json")
with open(os.path.join(DATA_DIR, "districts.json"), "w") as f:
    json.dump(district_info, f)
print("✓ districts.json")
