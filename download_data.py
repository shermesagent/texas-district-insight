#!/usr/bin/env python3
"""Download all 19 STAAR 2026 CSVs from Google Drive and process into normalized JSON."""
import json, os, csv, re, sys
from collections import defaultdict

# ── Configuration ──
RAW_DIR = "/home/writingtired/texas-dashboard-demo/data/raw"
DATA_DIR = "/home/writingtired/texas-dashboard-demo/data"
os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

FILES = {
    # STAAR 3-8 Scores
    "staar_3-8_g03_scores.csv": "1RSkBwijb-tbaP-Ihfh3Zsbu139_VSY7H",
    "staar_3-8_g04_scores.csv": "1dEkch6ebwslTl9mG0Y2ovD89P-m62C28",
    "staar_3-8_g05_scores.csv": "1pWz-zU15b1cl5tVvIkTd2QtCSM8pbvij",
    "staar_3-8_g06_scores.csv": "1eXmMQKWb24KF10L24rtTRjbD9vqjM7IV",
    "staar_3-8_g07_scores.csv": "1_ckgLlzaGOIYm8NXw41itz_0r77-YOBp",
    "staar_3-8_g08_scores.csv": "1FTg1NqCA4nco-0IHxv3FkdQI8OtNb9CL",
    # STAAR 3-8 ECR
    "staar_3-8_g03_ecr.csv": "1uwr9seTK8uJEtMJlzBMLYWC0jH6In_gq",
    "staar_3-8_g04_ecr.csv": "1Kmx-DPz_WGHSzb7cPrx1Sc147LS573ZN",
    "staar_3-8_g05_ecr.csv": "1vovSdM95-OyK18qcwZFOCoehxUXLziC7",
    "staar_3-8_g06_ecr.csv": "1QcCzjf86sg5ofoDogClhZV2NrL43F9JF",
    "staar_3-8_g07_ecr.csv": "1ybQI7Cq3u7SJ2Z9oW2oKqthF2tUVfLb9",
    "staar_3-8_g08_ecr.csv": "1XNqQezgfJ603capPuEZK36ZYa_PkjFQb",
    # EOC Scores
    "eoc_algebra_i_scores.csv": "1EFPq3SISH1fwbRgRj4ojFfwBk_T_Eaw4",
    "eoc_biology_scores.csv": "1SxScEWsBWcXB4-hZb5RNkR9fhy-cOM8L",
    "eoc_english_i_scores.csv": "1pJ653CpdLwOfeLD6ez3rWnaQ7-IjO3SL",
    "eoc_english_ii_scores.csv": "1LM25bMcQDzoOUvGqYUnCvvaLJLoaR6J9",
    "eoc_us_history_scores.csv": "1qo7ntx70I9YDrieYLprx--E3-fmdn9Ya",
    # EOC ECR
    "eoc_english_i_ecr.csv": "1bwzsa3GNLFzyDw8REAVnjhjmdYJVE77K",
    "eoc_english_ii_ecr.csv": "1oPjama2C1UwQTb9-fSgp1_6put1_dafI",
}

# ── Step 1: Download from Google Drive ──
def download_all():
    """Download all CSV files from Google Drive using google API."""
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload
    import io
    
    creds = Credentials.from_authorized_user_file(
        "/home/writingtired/.hermes/google_token.json",
        ["https://www.googleapis.com/auth/drive.readonly"]
    )
    service = build("drive", "v3", credentials=creds)
    
    for filename, file_id in FILES.items():
        dest = os.path.join(RAW_DIR, filename)
        if os.path.exists(dest) and os.path.getsize(dest) > 1000:
            print(f"  ✓ Already exists: {filename}")
            continue
        print(f"  ↓ Downloading: {filename}...", end=" ", flush=True)
        try:
            request = service.files().get_media(fileId=file_id)
            fh = io.BytesIO()
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                status, done = downloader.next_chunk()
            with open(dest, "wb") as f:
                f.write(fh.getvalue())
            size = os.path.getsize(dest)
            print(f"{size:,} bytes")
        except Exception as e:
            print(f"FAILED: {e}")

print("Step 1: Downloading all CSVs from Google Drive...")
download_all()
print()

# ── Step 2: Parse STAAR 3-8 Scores ──
print("Step 2: Parsing STAAR 3-8 Scores...")
# Subjects in column order within each grade file
# Col 0=Organization, 1=ID/CDC, 2=Administration
# Then per subject: Tests Taken, Avg Scale, DNM Cnt, DNM%, App+ Cnt, App+%, Meets+ Cnt, Meets+%, Masters Cnt, Masters%
# Subjects in order: Mathematics, Reading, Science, Social Studies, Writing
GRADE_SUBJECTS = {
    3: ["Mathematics", "Reading"],
    4: ["Mathematics", "Reading", "Writing"],
    5: ["Mathematics", "Reading", "Science", "Writing"],
    6: ["Mathematics", "Reading", "Science", "Writing"],
    7: ["Mathematics", "Reading", "Science", "Writing"],
    8: ["Mathematics", "Reading", "Science", "Social Studies", "Writing"],
}
SCORE_COL_START = 3

staar_data = {}  # cdc -> {name, grades_3_8: {grade: {subject: {...}}}}
district_info = {}  # cdc -> {name, county, region}

for grade in range(3, 9):
    filename = f"staar_3-8_g0{grade}_scores.csv"
    filepath = os.path.join(RAW_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  ! Missing: {filename}")
        continue
    
    subjects = GRADE_SUBJECTS[grade]
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        row_count = 0
        for row in reader:
            if len(row) < 3:
                continue
            cdc = row[1].strip()
            org = row[0].strip()
            if not cdc or not org:
                continue
            
            # Extract district info
            if cdc not in district_info:
                # Parse name and county from Organization field
                # Format example: "FARMERSVILLE ISD (Collin County)"
                if "(" in org and ")" in org:
                    parts = org.split("(")
                    dname = parts[0].strip()
                    county_raw = parts[1].replace("County)", "").strip()
                else:
                    dname = org
                    county_raw = ""
                district_info[cdc] = {
                    "name": dname,
                    "county": county_raw,
                    "region": "",  # Will fill from TAPR data
                }
            
            # Initialize data structure
            if cdc not in staar_data:
                staar_data[cdc] = {"name": district_info[cdc]["name"], "grades_3_8": {}, "eoc": {}, "ecr": {}}
            
            # Parse per-subject performance data
            # Column offset: 3 + subject_index * 10
            grade_str = str(grade)
            for si, subject in enumerate(subjects):
                base = SCORE_COL_START + si * 10
                if base + 9 >= len(row):
                    continue
                
                def safe_float(s):
                    s = s.strip()
                    if not s:
                        return None
                    try:
                        return float(s)
                    except:
                        return None
                
                def safe_int(s):
                    s = s.strip()
                    if not s:
                        return None
                    try:
                        return int(s.replace(",", ""))
                    except:
                        return None
                
                tests_taken = safe_int(row[base])
                if tests_taken is None or tests_taken == 0:
                    continue  # No data for this subject/grade
                
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
        print(f"  {filename}: {row_count} districts")

print(f"\n  Total districts in STAAR 3-8: {len(staar_data)}")
print()

# ── Step 3: Parse STAAR 3-8 ECR ──
print("Step 3: Parsing STAAR 3-8 ECR...")
for grade in range(3, 9):
    filename = f"staar_3-8_g0{grade}_ecr.csv"
    filepath = os.path.join(RAW_DIR, filename)
    if not os.path.exists(filepath):
        print(f"  ! Missing: {filename}")
        continue
    
    with open(filepath, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        row_count = 0
        for row in reader:
            if len(row) < 3:
                continue
            cdc = row[1].strip()
            if not cdc:
                continue
            
            valid_n = None
            try:
                valid_n = int(row[2].strip()) if row[2].strip() else None
            except:
                pass
            if valid_n is None or valid_n == 0:
                continue
            
            # Parse ratings 0-10 distribution (columns 3-24: pairs of count, percent)
            ratings = {}
            for r in range(11):
                cnt_idx = 3 + r * 2
                pct_idx = 4 + r * 2
                if cnt_idx < len(row) and pct_idx < len(row):
                    try:
                        pct = float(row[pct_idx].strip()) if row[pct_idx].strip() else 0
                        ratings[str(r)] = pct
                    except:
                        pass
            
            if cdc not in staar_data:
                staar_data[cdc] = {"name": district_info.get(cdc, {}).get("name", ""), "grades_3_8": {}, "eoc": {}, "ecr": {}}
            staar_data[cdc]["ecr"][str(grade)] = {
                "valid_n": valid_n,
                "ratings": ratings
            }
            row_count += 1
        print(f"  {filename}: {row_count} districts with ECR")

print()

# ── Step 4: Parse EOC Scores ──
print("Step 4: Parsing EOC Scores...")
# EOC column layout (291 cols total, 0-indexed):
# Col 0=Organization, 1=ID/CDC, 2=Administration
# Algebra I: 3-12 (Tests Taken, Avg Scale, DNM Cnt, DNM%, App+ Cnt, App+%, Meets+ Cnt, Meets+%, Masters Cnt, Masters%)
# Biology: 35-44
# English I: 67-76
# English II: 99-108
# US History: 195-204

EOC_COL_MAP = {
    "Algebra I": 3,
    "Biology": 35,
    "English I": 67,
    "English II": 99,
    "U.S. History": 195,
}

# Use the algebra_i file as the master EOC file (it has the most rows)
eoc_file = os.path.join(RAW_DIR, "eoc_algebra_i_scores.csv")
if not os.path.exists(eoc_file):
    print("  ! Missing eoc_algebra_i_scores.csv")
else:
    with open(eoc_file, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        row_count = 0
        for row in reader:
            if len(row) < 200:
                continue
            cdc = row[1].strip()
            org = row[0].strip()
            if not cdc:
                continue
            
            if cdc not in district_info:
                if "(" in org and ")" in org:
                    parts = org.split("(")
                    dname = parts[0].strip()
                    county_raw = parts[1].replace("County)", "").strip()
                else:
                    dname = org
                    county_raw = ""
                district_info[cdc] = {"name": dname, "county": county_raw, "region": ""}
            
            if cdc not in staar_data:
                staar_data[cdc] = {"name": district_info[cdc]["name"], "grades_3_8": {}, "eoc": {}, "ecr": {}}
            
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
            
            for subject, col_start in EOC_COL_MAP.items():
                base = col_start
                if base + 9 >= len(row):
                    continue
                tests_taken = safe_int(row[base])
                if tests_taken is None or tests_taken == 0:
                    continue
                
                staar_data[cdc]["eoc"][subject] = {
                    "tests_taken": tests_taken,
                    "avg_scale": safe_int(row[base+1]),
                    "dnm_pct": safe_float(row[base+3]),
                    "app_pct": safe_float(row[base+5]),
                    "meets_pct": safe_float(row[base+7]),
                    "mast_pct": safe_float(row[base+9]),
                }
            
            row_count += 1
        print(f"  EOC Algebra I: {row_count} districts processed")

# Also check for any additional districts in other EOC files
eoc_files = ["eoc_biology_scores.csv", "eoc_english_i_scores.csv", 
             "eoc_english_ii_scores.csv", "eoc_us_history_scores.csv"]
for efn in eoc_files:
    fp = os.path.join(RAW_DIR, efn)
    if not os.path.exists(fp):
        continue
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        extra = 0
        for row in reader:
            cdc = row[1].strip()
            if cdc and cdc not in staar_data:
                org = row[0].strip()
                if "(" in org and ")" in org:
                    parts = org.split("(")
                    dname = parts[0].strip()
                else:
                    dname = org
                staar_data[cdc] = {"name": dname, "grades_3_8": {}, "eoc": {}, "ecr": {}}
                if cdc not in district_info:
                    district_info[cdc] = {"name": dname, "county": "", "region": ""}
                extra += 1
        if extra:
            print(f"  {efn}: {extra} additional districts found")
print()

# ── Step 5: Parse EOC ECR ──
print("Step 5: Parsing EOC ECR...")
for eocr_name, eocr_subject in [("eoc_english_i_ecr.csv", "English I"), ("eoc_english_ii_ecr.csv", "English II")]:
    fp = os.path.join(RAW_DIR, eocr_name)
    if not os.path.exists(fp):
        print(f"  ! Missing: {eocr_name}")
        continue
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        row_count = 0
        for row in reader:
            if len(row) < 3:
                continue
            cdc = row[1].strip()
            if not cdc:
                continue
            try:
                valid_n = int(row[2].strip()) if row[2].strip() else None
            except:
                valid_n = None
            if valid_n is None or valid_n == 0:
                continue
            ratings = {}
            for r in range(11):
                pct_idx = 4 + r * 2
                if pct_idx < len(row):
                    try:
                        pct = float(row[pct_idx].strip()) if row[pct_idx].strip() else 0
                        ratings[str(r)] = pct
                    except:
                        pass
            if cdc not in staar_data:
                staar_data[cdc] = {"name": district_info.get(cdc, {}).get("name", ""), "grades_3_8": {}, "eoc": {}, "ecr": {}}
            staar_data[cdc]["ecr"][eocr_subject] = {"valid_n": valid_n, "ratings": ratings}
            row_count += 1
        print(f"  {eocr_name}: {row_count} districts")
print()

# ── Step 6: Load demographics from existing TAPR data ──
print("Step 6: Loading demographics from existing TAPR data...")
tapr_files = sorted([f for f in os.listdir("/tmp") if f.startswith("tapr_gr") and f.endswith("_math_2025.csv")])
tapr_districts = {}
for tf in tapr_files:
    fp = os.path.join("/tmp", tf)
    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            cdc = row.get("cdc", "").strip()
            if not cdc:
                continue
            if cdc not in tapr_districts:
                def sf(val):
                    if val is None: return None
                    s = str(val).strip()
                    if not s: return None
                    try: return float(s)
                    except: return None
                
                tapr_districts[cdc] = {
                    "enrollment": sf(row.get("enrollment")),
                    "econ_disadv_pct": sf(row.get("econ_pct", row.get("econ_disadv_pct"))),
                    "eb_el_pct": sf(row.get("eb_el_pct")),
                    "sped_pct": sf(row.get("sped_pct")),
                    "at_risk_pct": sf(row.get("at_risk_pct")),
                    "hispanic_pct": sf(row.get("hispanic_pct")),
                    "white_pct": sf(row.get("white_pct")),
                    "black_pct": sf(row.get("black_pct")),
                    "asian_pct": sf(row.get("asian_pct")),
                    "two_or_more_pct": sf(row.get("two_or_more_pct")),
                    "bilingual_pct": sf(row.get("bilingual_pct")),
                    "tea_rating": str(row.get("tea_rating", "")).strip() if row.get("tea_rating") else None,
                    "charter": str(row.get("charter", "")).strip().lower() in ("yes", "true", "y", "1") if row.get("charter") else None,
                    "region": str(row.get("region", "")).strip() if row.get("region") else None,
                    "county_tapr": str(row.get("county", "")).strip(),
                }

print(f"  TAPR districts loaded: {len(tapr_districts)}")

# Merge demographics into district_info
for cdc, info in district_info.items():
    if cdc in tapr_districts:
        t = tapr_districts[cdc]
        for key in ["enrollment", "econ_disadv_pct", "eb_el_pct", "sped_pct", "at_risk_pct",
                     "hispanic_pct", "white_pct", "black_pct", "asian_pct", "two_or_more_pct",
                     "bilingual_pct", "tea_rating", "charter", "region"]:
            if t.get(key) is not None:
                info[key] = t[key]
        # Use county from TAPR if not in 2026 data
        if not info.get("county") and t.get("county_tapr"):
            info["county"] = t["county_tapr"]
    # Default values for missing fields
    for key in ["enrollment", "econ_disadv_pct", "eb_el_pct", "sped_pct", "at_risk_pct",
                 "hispanic_pct", "white_pct", "black_pct", "asian_pct", "two_or_more_pct",
                 "bilingual_pct"]:
        if key not in info or info[key] is None:
            info[key] = 0
    if "charter" not in info or info["charter"] is None:
        info["charter"] = False
    if "region" not in info or info["region"] is None:
        info["region"] = ""
    if "tea_rating" not in info or info["tea_rating"] is None:
        info["tea_rating"] = ""
    # Fix empty county
    if not info.get("county"):
        info["county"] = info.get("name", "").split(" ")[0] if info.get("name") else ""

print(f"  Final district info count: {len(district_info)}")
print()

# ── Step 7: Compute Peer Groups ──
print("Step 7: Computing peer groups...")
# Read the existing app.py to understand peer computation
# For now, create simple demographic similarity and geographic proximity

def compute_demo_similarity(d1, d2):
    """Compute demographic similarity score (lower = more similar)."""
    import math
    # Weighted Euclidean distance on key demographics
    weights = {
        "econ_disadv_pct": 3.0,
        "eb_el_pct": 2.0,
        "sped_pct": 1.0,
        "enrollment": 0.001,  # enrollment has large values
        "hispanic_pct": 1.5,
        "white_pct": 1.5,
        "black_pct": 1.5,
        "asian_pct": 1.5,
    }
    sq_sum = 0
    for key, weight in weights.items():
        v1 = d1.get(key, 0) or 0
        v2 = d2.get(key, 0) or 0
        sq_sum += weight * (v1 - v2) ** 2
    return math.sqrt(sq_sum)

# Build peer data
peers_data = {}
district_list = []

for cdc, info in sorted(district_info.items()):
    district_list.append({
        "cdc": cdc,
        "name": info.get("name", ""),
        "county": info.get("county", ""),
        "region": info.get("region", ""),
        "enrollment": info.get("enrollment", 0),
    })
    
    # Compute demo peers (top 20 most similar districts)
    scores = []
    for other_cdc, other_info in district_info.items():
        if other_cdc == cdc:
            continue
        sim = compute_demo_similarity(info, other_info)
        scores.append((sim, other_cdc))
    scores.sort(key=lambda x: x[0])
    
    top_demo = scores[:20]
    demo_peers = []
    for rank, (score, other_cdc) in enumerate(top_demo, 1):
        oi = district_info[other_cdc]
        demo_peers.append({
            "rank": rank,
            "cdc": other_cdc,
            "name": oi.get("name", ""),
            "score": round(score, 4),
            "enrollment": oi.get("enrollment", 0),
            "econ_disadv_pct": oi.get("econ_disadv_pct", 0),
            "eb_el_pct": oi.get("eb_el_pct", 0),
        })
    
    # Compute geo peers (simple - just region-based and alphabetical for now)
    region = info.get("region", "")
    geo_scores = []
    for other_cdc, other_info in district_info.items():
        if other_cdc == cdc:
            continue
        # Same region = closer, different region = farther
        dist = 0 if other_info.get("region") == region else 50
        geo_scores.append((dist, other_cdc))
    geo_scores.sort(key=lambda x: (x[0], district_info[x[1]].get("name", "")))
    
    top_geo = geo_scores[:20]
    geo_peers = []
    for rank, (dist, other_cdc) in enumerate(top_geo, 1):
        oi = district_info[other_cdc]
        geo_peers.append({
            "rank": rank,
            "cdc": other_cdc,
            "name": oi.get("name", ""),
            "dist_mi": dist,
            "enrollment": oi.get("enrollment", 0),
            "econ_disadv_pct": oi.get("econ_disadv_pct", 0),
            "eb_el_pct": oi.get("eb_el_pct", 0),
        })
    
    peers_data[cdc] = {
        "demo_peers": demo_peers,
        "geo_peers": geo_peers,
        "demo_avg": {},
        "geo_avg": {},
    }

# Compute peer averages for performance
for cdc in peers_data:
    for peer_type in ["demo_peers", "geo_peers"]:
        peers = peers_data[cdc][peer_type]
        # Aggregate performance across peers
        grade_subject_sums = {}  # grade-subj -> {app_sum, meets_sum, mast_sum, count}
        for p in peers:
            pcdc = p["cdc"]
            if pcdc not in staar_data:
                continue
            sd = staar_data[pcdc]
            for grade_str, subjects in sd.get("grades_3_8", {}).items():
                for subj, perf in subjects.items():
                    key = f"{grade_str}|{subj}"
                    if key not in grade_subject_sums:
                        grade_subject_sums[key] = {"app_sum": 0, "meets_sum": 0, "mast_sum": 0, "count": 0}
                    gs = grade_subject_sums[key]
                    if perf.get("app_pct") is not None:
                        gs["app_sum"] += perf["app_pct"]
                        gs["meets_sum"] += perf.get("meets_pct", 0) or 0
                        gs["mast_sum"] += perf.get("mast_pct", 0) or 0
                        gs["count"] += 1
            for subj, perf in sd.get("eoc", {}).items():
                key = f"eoc|{subj}"
                if key not in grade_subject_sums:
                    grade_subject_sums[key] = {"app_sum": 0, "meets_sum": 0, "mast_sum": 0, "count": 0}
                gs = grade_subject_sums[key]
                if perf.get("app_pct") is not None:
                    gs["app_sum"] += perf["app_pct"]
                    gs["meets_sum"] += perf.get("meets_pct", 0) or 0
                    gs["mast_sum"] += perf.get("mast_pct", 0) or 0
                    gs["count"] += 1
        
        # Compute averages
        avgs = {}
        for key, gs in grade_subject_sums.items():
            if gs["count"] > 0:
                if "|" in key:
                    parts = key.split("|")
                    if parts[0] == "eoc":
                        avgs[parts[1]] = {
                            "app": round(gs["app_sum"] / gs["count"], 1) if gs["app_sum"] else None,
                            "meets": round(gs["meets_sum"] / gs["count"], 1) if gs["meets_sum"] else None,
                            "mast": round(gs["mast_sum"] / gs["count"], 1) if gs["mast_sum"] else None,
                        }
                    else:
                        if parts[0] not in avgs:
                            avgs[parts[0]] = {}
                        avgs[parts[0]][parts[1]] = {
                            "app": round(gs["app_sum"] / gs["count"], 1) if gs["app_sum"] else None,
                            "meets": round(gs["meets_sum"] / gs["count"], 1) if gs["meets_sum"] else None,
                            "mast": round(gs["mast_sum"] / gs["count"], 1) if gs["mast_sum"] else None,
                        }
        
        if peer_type == "demo_peers":
            peers_data[cdc]["demo_avg"] = avgs
        else:
            peers_data[cdc]["geo_avg"] = avgs

print(f"  Peer groups computed for {len(peers_data)} districts")
print()

# ── Step 8: Write output files ──
print("Step 8: Writing output files...")

# staar_2026.json
outpath = os.path.join(DATA_DIR, "staar_2026.json")
# Clean up: remove duplicate name field in main data (it's in district_info) but keep for legacy
for cdc in list(staar_data.keys()):
    if cdc not in district_info and cdc in staar_data:
        del staar_data[cdc]
    elif cdc in staar_data:
        # Clean up empty structures
        sd = staar_data[cdc]
        if not sd.get("grades_3_8") and not sd.get("eoc") and not sd.get("ecr"):
            del staar_data[cdc]

class CompactEncoder(json.JSONEncoder):
    def default(self, obj):
        return obj

with open(outpath, "w") as f:
    json.dump(staar_data, f, cls=CompactEncoder)
size_mb = os.path.getsize(outpath) / (1024*1024)
print(f"  ✓ staar_2026.json ({size_mb:.1f} MB, {len(staar_data)} districts)")

# districts.json - with demographics
districts_out = {}
for cdc, info in district_info.items():
    if cdc in staar_data or True:  # Include all districts
        districts_out[cdc] = {
            "name": info.get("name", ""),
            "county": info.get("county", ""),
            "region": info.get("region", ""),
            "enrollment": info.get("enrollment", 0),
            "econ_disadv_pct": info.get("econ_disadv_pct", 0),
            "eb_el_pct": info.get("eb_el_pct", 0),
            "sped_pct": info.get("sped_pct", 0),
            "at_risk_pct": info.get("at_risk_pct", 0),
            "hispanic_pct": info.get("hispanic_pct", 0),
            "white_pct": info.get("white_pct", 0),
            "black_pct": info.get("black_pct", 0),
            "asian_pct": info.get("asian_pct", 0),
            "two_or_more_pct": info.get("two_or_more_pct", 0),
            "bilingual_pct": info.get("bilingual_pct", 0),
            "tea_rating": info.get("tea_rating", None) or "",
            "charter": info.get("charter", False),
        }

outpath2 = os.path.join(DATA_DIR, "districts.json")
with open(outpath2, "w") as f:
    json.dump(districts_out, f)
size_mb2 = os.path.getsize(outpath2) / (1024*1024)
print(f"  ✓ districts.json ({size_mb2:.1f} MB, {len(districts_out)} districts)")

# peers.json
outpath3 = os.path.join(DATA_DIR, "peers.json")
with open(outpath3, "w") as f:
    json.dump(peers_data, f)
size_mb3 = os.path.getsize(outpath3) / (1024*1024)
print(f"  ✓ peers.json ({size_mb3:.1f} MB, {len(peers_data)} districts with peers)")

# district_list.json - search index
outpath4 = os.path.join(DATA_DIR, "district_list.json")
with open(outpath4, "w") as f:
    json.dump(district_list, f)
size_kb4 = os.path.getsize(outpath4) / 1024
print(f"  ✓ district_list.json ({size_kb4:.1f} KB, {len(district_list)} entries)")

print()
print("=" * 60)
print("DATA PIPELINE COMPLETE")
print("=" * 60)
print(f"\nSummary:")
print(f"  Districts in 2026 data: {len(staar_data)}")
grades_with_data = set()
subjects_per_grade = defaultdict(set)
for cdc, sd in staar_data.items():
    for g, subs in sd.get("grades_3_8", {}).items():
        grades_with_data.add(g)
        for s in subs:
            subjects_per_grade[g].add(s)
print(f"  Grades 3-8: {sorted(grades_with_data)}")
for g in sorted(grades_with_data):
    print(f"    Grade {g}: {', '.join(sorted(subjects_per_grade[g]))}")

eoc_subjects = set()
eoc_districts = 0
for cdc, sd in staar_data.items():
    if sd.get("eoc"):
        eoc_districts += 1
        for s in sd["eoc"]:
            eoc_subjects.add(s)
print(f"  EOC subjects: {', '.join(sorted(eoc_subjects))}")
print(f"  Districts with EOC data: {eoc_districts}")

ecr_grades = set()
ecr_districts = 0
for cdc, sd in staar_data.items():
    if sd.get("ecr"):
        ecr_districts += 1
        for g in sd["ecr"]:
            ecr_grades.add(g)
print(f"  ECR available for: {', '.join(sorted(ecr_grades))}")
print(f"  Districts with ECR data: {ecr_districts}")
