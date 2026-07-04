#!/usr/bin/env python3
"""Rebuild staar_2026.json with correct 3-8 score column parsing.

Fixes SCORE_COL_START from 3→4 and handles variable column layout
by dynamically parsing headers (some subjects have Spanish versions, some don't).
"""
import json, os, csv, re
from collections import defaultdict

RAW_DIR = "/home/writingtired/texas-dashboard-demo/data/raw"
DATA_DIR = "/home/writingtired/texas-dashboard-demo/data"

# ── Load existing data (preserving EOC and ECR) ──
with open(os.path.join(DATA_DIR, "staar_2026.json")) as f:
    staar_data = json.load(f)

with open(os.path.join(DATA_DIR, "districts.json")) as f:
    district_info = json.load(f)

def safe_float(s):
    s = s.strip() if s else ""
    if not s: return None
    try: return float(s)
    except: return None

def safe_int(s):
    s = s.strip() if s else ""
    if not s: return None
    try: return int(s.replace(",", ""))
    except: return None

print("Rebuilding STAAR 3-8 scores with correct column parsing...\n")

for grade in range(3, 9):
    filename = f"staar_3-8_g0{grade}_scores.csv"
    filepath = os.path.join(RAW_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  ! Missing: {filename}")
        continue
    
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        
        # Dynamically find all main-subject columns
        # Pattern: "STAAR - <Subject>|Tests Taken" (NOT Spanish, STAAR A, STAAR L)
        subject_cols = {}
        for idx, h in enumerate(headers):
            h_clean = h.strip()
            if h_clean.startswith("STAAR - ") and h_clean.endswith("|Tests Taken") and "Spanish" not in h_clean:
                # Extract subject name
                subject = h_clean.replace("STAAR - ", "").replace("|Tests Taken", "").strip()
                subject_cols[subject] = idx
        
        subjects_ordered = sorted(subject_cols.keys(), key=lambda s: subject_cols[s])
        
        row_count = 0
        for row in reader:
            if len(row) < 5:
                continue
            cdc = row[1].strip()
            org = row[0].strip()
            if not cdc or not org:
                continue
            
            # Ensure district exists in staar_data
            if cdc not in staar_data:
                staar_data[cdc] = {"name": "", "grades_3_8": {}, "eoc": {}, "ecr": {}}
            
            # Ensure name is set
            if not staar_data[cdc].get("name"):
                staar_data[cdc]["name"] = district_info.get(cdc, {}).get("name", org.split("(")[0].strip())
            
            # Parse each subject at its dynamically-found column
            grade_str = str(grade)
            for subject, base in subject_cols.items():
                if base + 9 >= len(row):
                    continue
                
                tests_taken = safe_int(row[base])
                if tests_taken is None or tests_taken == 0:
                    continue
                
                perf = {
                    "tests_taken": tests_taken,
                    "avg_scale": safe_int(row[base+1]),
                    "dnm_pct": safe_float(row[base+3]),
                    "app_pct": safe_float(row[base+5]),
                    "meets_pct": safe_float(row[base+7]),
                    "mast_pct": safe_float(row[base+9]),
                }
                
                if grade_str not in staar_data[cdc]["grades_3_8"]:
                    staar_data[cdc]["grades_3_8"][grade_str] = {}
                staar_data[cdc]["grades_3_8"][grade_str][subject] = perf
            
            row_count += 1
        
        # Handle renames: Texas calls it "Writing" in 4,7 but for consistency
        # we keep the original header names from the CSV
        print(f"  {filename} (grade {grade}): {row_count} districts, subjects: {', '.join(subjects_ordered)}")

# ── Rebuild districts.json with correct names ──
for cdc, sd in staar_data.items():
    if cdc not in district_info:
        district_info[cdc] = {"name": sd.get("name", ""), "county": "", "region": ""}
    elif sd.get("name") and not district_info[cdc].get("name"):
        district_info[cdc]["name"] = sd["name"]

# ── Verify with sample district ──
print(f"\n✓ Total districts: {len(staar_data)}")

# Check Farmersville
if "043904" in staar_data:
    fv = staar_data["043904"]
    print(f"\nFarmersville ISD verification:")
    for g in sorted(fv["grades_3_8"].keys()):
        subjects = list(fv["grades_3_8"][g].keys())
        print(f"  Grade {g}: {', '.join(subjects)}")
        for s in subjects:
            d = fv["grades_3_8"][g][s]
            print(f"    {s}: tested={d['tests_taken']}, avg={d['avg_scale']}, approaches={d['app_pct']}%, meets={d['meets_pct']}%, masters={d['mast_pct']}%")
    if fv.get("eoc"):
        print(f"  EOC: {', '.join(fv['eoc'].keys())}")

# ── Save ──
with open(os.path.join(DATA_DIR, "staar_2026.json"), "w") as f:
    json.dump(staar_data, f)
print("\n✓ staar_2026.json saved")

with open(os.path.join(DATA_DIR, "districts.json"), "w") as f:
    json.dump(district_info, f)
print("✓ districts.json saved")
