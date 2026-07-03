#!/usr/bin/env python3
"""Fix EOC parsing: read each subject-specific EOC file to get ALL subjects' data."""
import json, csv, os

DATA_DIR = "/home/writingtired/texas-dashboard-demo/data"
RAW_DIR = os.path.join(DATA_DIR, "raw")

# ── Load existing data ──
with open(os.path.join(DATA_DIR, "staar_2026.json")) as f:
    staar_data = json.load(f)

with open(os.path.join(DATA_DIR, "districts.json")) as f:
    districts_data = json.load(f)

# ── EOC Subject files and their column offsets ──
# Each file has the same 291-column mega-structure but only 
# one subject's columns are populated with actual data
EOC_FILES = {
    "eoc_algebra_i_scores.csv": {"Algebra I": 3},
    "eoc_biology_scores.csv": {"Biology": 35},
    "eoc_english_i_scores.csv": {"English I": 67},
    "eoc_english_ii_scores.csv": {"English II": 99},
    "eoc_us_history_scores.csv": {"U.S. History": 195},
}

def safe_float(s):
    s = s.strip()
    if not s: return None
    try: return float(s)
    except: return None

def safe_int(s):
    s = s.strip()
    if not s: return None
    try: return int(s.replace(",", ""))
    except: return None

print("Re-parsing EOC data from individual subject files...")
eoc_parsed = {}  # cdc -> {subject -> {data}}
eoc_subjects_found = set()
districts_with_eoc = set()

for filename, subject_map in EOC_FILES.items():
    filepath = os.path.join(RAW_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  ! Missing: {filename}")
        continue
    
    subject = list(subject_map.keys())[0]
    col_start = list(subject_map.values())[0]
    
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        row_count = 0
        for row in reader:
            if len(row) < col_start + 10:
                continue
            cdc = row[1].strip()
            if not cdc:
                continue
            
            base = col_start
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
            
            if cdc not in eoc_parsed:
                eoc_parsed[cdc] = {}
            eoc_parsed[cdc][subject] = perf
            eoc_subjects_found.add(subject)
            districts_with_eoc.add(cdc)
            row_count += 1
        print(f"  {filename} ({subject}): {row_count} districts")

print(f"\nEOC subjects found: {', '.join(sorted(eoc_subjects_found))}")
print(f"Districts with EOC data: {len(districts_with_eoc)}")

# ── Merge EOC data back into staar_data ──
merged = 0
for cdc in staar_data:
    if cdc in eoc_parsed:
        staar_data[cdc]["eoc"] = eoc_parsed[cdc]
        merged += 1

# Also add districts that only have EOC data
for cdc in eoc_parsed:
    if cdc not in staar_data:
        name = districts_data.get(cdc, {}).get("name", "")
        staar_data[cdc] = {"name": name, "grades_3_8": {}, "eoc": eoc_parsed[cdc], "ecr": {}}
        # Ensure this district exists in districts_data
        if cdc not in districts_data:
            districts_data[cdc] = {"name": name, "county": "", "region": "", "enrollment": 0,
                "econ_disadv_pct": 0, "eb_el_pct": 0, "sped_pct": 0, "at_risk_pct": 0,
                "hispanic_pct": 0, "white_pct": 0, "black_pct": 0, "asian_pct": 0,
                "two_or_more_pct": 0, "bilingual_pct": 0, "tea_rating": "", "charter": False}

print(f"Merged EOC into {merged} existing districts, added {len(eoc_parsed)-merged} new")

# ── Save updated files ──
with open(os.path.join(DATA_DIR, "staar_2026.json"), "w") as f:
    json.dump(staar_data, f)
print(f"✓ staar_2026.json updated ({len(staar_data)} districts)")

with open(os.path.join(DATA_DIR, "districts.json"), "w") as f:
    json.dump(districts_data, f)
print(f"✓ districts.json updated ({len(districts_data)} districts)")

# ── Update district_list.json ──
district_list = []
for cdc, info in sorted(districts_data.items()):
    district_list.append({
        "cdc": cdc,
        "name": info.get("name", ""),
        "county": info.get("county", ""),
        "region": info.get("region", ""),
        "enrollment": info.get("enrollment", 0),
    })

with open(os.path.join(DATA_DIR, "district_list.json"), "w") as f:
    json.dump(district_list, f)
print(f"✓ district_list.json updated ({len(district_list)} entries)")

# ── Print summary ──
print(f"\n{'='*60}")
print("EOC FIX COMPLETE")
print(f"{'='*60}")
eoc_subjects_all = set()
eoc_districts = 0
for cdc, sd in staar_data.items():
    if sd.get("eoc"):
        eoc_districts += 1
        for s in sd["eoc"]:
            eoc_subjects_all.add(s)
print(f"EOC subjects: {', '.join(sorted(eoc_subjects_all))}")
print(f"Districts with EOC data: {eoc_districts}")
