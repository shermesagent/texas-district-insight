#!/usr/bin/env python3
"""Texas School Compass Dashboard — Backend API (2026 data)"""
import json, math, os, pwd
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import uvicorn

# ── Paths ──
# Use pwd to get real home directory (resilient to $HOME being overridden by profile env)
REAL_HOME = Path(pwd.getpwuid(os.getuid()).pw_dir)
BASE = Path(__file__).parent
DATA = BASE / "data"
PEER = REAL_HOME / ".hermes" / "persistent_workspace" / "district-comparison"

# ── Load data ──
print("Loading 2026 STAAR data...")
with open(DATA / "staar_2026.json") as f:
    staar = json.load(f)

with open(DATA / "districts.json") as f:
    district_info = json.load(f)

with open(PEER / "master_district_list_enriched.json") as f:
    master_list = json.load(f)

with open(PEER / "demographic_similarity.json") as f:
    demo_sim = json.load(f)

with open(PEER / "geographic_proximity.json") as f:
    geo_prox = json.load(f)

# ── Build lookup indexes ──
# master_by_cdc: enriched demographics keyed by CDC
master_by_cdc = {}
for d in master_list:
    cdc = d["cdc"]
    master_by_cdc[cdc] = d

# district_regions: map CDC → ESC region
district_region = {}
for cdc, info in district_info.items():
    m = master_by_cdc.get(cdc, {})
    district_region[cdc] = m.get("region_name", "")

# region_districts: map region → list of CDC codes
region_districts = {}
for cdc, info in district_info.items():
    region = district_region.get(cdc, "")
    if region:
        region_districts.setdefault(region, []).append(cdc)

# ── Build search index ──
# Name→CDC lookup (case-insensitive)
name_to_cdc = {}
search_index = []
for cdc, info in district_info.items():
    name = info.get("name", "")
    if name:
        key = name.upper()
        name_to_cdc[key] = cdc
        search_index.append({
            "cdc": cdc,
            "name": name,
            "county": info.get("county", ""),
            "region": district_region.get(cdc, ""),
        })
search_index.sort(key=lambda x: x["name"])

print(f"  {len(staar)} districts loaded")
print(f"  {len(search_index)} districts in search index")
print(f"  {len(demo_sim)} demographic peer sets")
print(f"  {len(geo_prox)} geographic peer sets")

# ── Helper: compute state/region benchmarks ──
def compute_benchmarks(subject, grade_or_eoc=None, is_eoc=False):
    """Compute state averages for a given subject/grade across all districts."""
    vals = []
    for cdc, data in staar.items():
        source = data.get("eoc" if is_eoc else "grades_3_8", {})
        grade_str = str(grade_or_eoc)
        if is_eoc:
            subj_data = source.get(subject)
        else:
            grade_data = source.get(grade_str, {})
            subj_data = grade_data.get(subject)
        if subj_data and subj_data.get("tests_taken", 0) > 0 and subj_data.get("avg_scale"):
            vals.append({
                "tests_taken": subj_data["tests_taken"],
                "avg_scale": subj_data["avg_scale"],
                "dnm_pct": subj_data.get("dnm_pct"),
                "app_pct": subj_data.get("app_pct"),
                "meets_pct": subj_data.get("meets_pct"),
                "mast_pct": subj_data.get("mast_pct"),
            })
    if not vals:
        return None
    total_t = sum(v["tests_taken"] for v in vals)
    avg_scale = round(sum(v["avg_scale"] * v["tests_taken"] for v in vals) / total_t) if total_t else None
    app_pct = round(sum(v["app_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    meets_pct = round(sum(v["meets_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    mast_pct = round(sum(v["mast_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    dnm_pct = round(sum(v["dnm_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    return {
        "tests_taken": total_t,
        "avg_scale": avg_scale,
        "dnm_pct": dnm_pct,
        "app_pct": app_pct,
        "meets_pct": meets_pct,
        "mast_pct": mast_pct,
    }

def compute_region_benchmark(region, subject, grade_or_eoc=None, is_eoc=False):
    """Compute region average for a given subject/grade."""
    cdcs = region_districts.get(region, [])
    vals = []
    for cdc in cdcs:
        data = staar.get(cdc)
        if not data:
            continue
        source = data.get("eoc" if is_eoc else "grades_3_8", {})
        grade_str = str(grade_or_eoc)
        if is_eoc:
            subj_data = source.get(subject)
        else:
            grade_data = source.get(grade_str, {})
            subj_data = grade_data.get(subject)
        if subj_data and subj_data.get("tests_taken", 0) > 0 and subj_data.get("avg_scale"):
            vals.append(subj_data)
    if not vals:
        return None
    total_t = sum(v["tests_taken"] for v in vals)
    avg_scale = round(sum(v["avg_scale"] * v["tests_taken"] for v in vals) / total_t) if total_t else None
    app_pct = round(sum(v["app_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    meets_pct = round(sum(v["meets_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    mast_pct = round(sum(v["mast_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    dnm_pct = round(sum(v["dnm_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    return {
        "tests_taken": total_t,
        "avg_scale": avg_scale,
        "dnm_pct": dnm_pct,
        "app_pct": app_pct,
        "meets_pct": meets_pct,
        "mast_pct": mast_pct,
    }

# ── Helper: compute ECR state/region benchmarks ──
def compute_ecr_benchmarks(grade):
    """Compute weighted state ECR score distribution for a grade across all districts."""
    ratings_sum = {str(i): 0.0 for i in range(11)}
    total_n = 0
    for cdc, data in staar.items():
        ecr = data.get("ecr", {})
        grade_ecr = ecr.get(str(grade))
        if not grade_ecr or not grade_ecr.get("valid_n", 0):
            continue
        n = grade_ecr["valid_n"]
        total_n += n
        for i in range(11):
            si = str(i)
            ratings_sum[si] += grade_ecr.get("ratings", {}).get(si, 0) * n
    if total_n == 0:
        return None
    return {
        "valid_n": total_n,
        "ratings": {si: round(ratings_sum[si] / total_n, 1) for si in ratings_sum},
    }

def compute_region_ecr_benchmark(region, grade):
    """Compute weighted region ECR score distribution for a grade."""
    cdcs = region_districts.get(region, [])
    ratings_sum = {str(i): 0.0 for i in range(11)}
    total_n = 0
    for cdc in cdcs:
        data = staar.get(cdc)
        if not data:
            continue
        ecr = data.get("ecr", {})
        grade_ecr = ecr.get(str(grade))
        if not grade_ecr or not grade_ecr.get("valid_n", 0):
            continue
        n = grade_ecr["valid_n"]
        total_n += n
        for i in range(11):
            si = str(i)
            ratings_sum[si] += grade_ecr.get("ratings", {}).get(si, 0) * n
    if total_n == 0:
        return None
    return {
        "valid_n": total_n,
        "ratings": {si: round(ratings_sum[si] / total_n, 1) for si in ratings_sum},
    }

# ── Composite definitions (All Reading, All Math, All Scores) ──
COMPOSITE_DEFS = {
    "all-reading": [
        (False, "3", "Reading"), (False, "4", "Reading"), (False, "5", "Reading"),
        (False, "6", "Reading"), (False, "7", "Reading"), (False, "8", "Reading"),
        (True, None, "English I"), (True, None, "English II"),
    ],
    "all-math": [
        (False, "3", "Mathematics"), (False, "4", "Mathematics"), (False, "5", "Mathematics"),
        (False, "6", "Mathematics"), (False, "7", "Mathematics"), (False, "8", "Mathematics"),
        (True, None, "Algebra I"),
    ],
    "all-scores": [
        (False, "3", "Reading"), (False, "4", "Reading"), (False, "5", "Reading"),
        (False, "6", "Reading"), (False, "7", "Reading"), (False, "8", "Reading"),
        (True, None, "English I"), (True, None, "English II"),
        (False, "3", "Mathematics"), (False, "4", "Mathematics"), (False, "5", "Mathematics"),
        (False, "6", "Mathematics"), (False, "7", "Mathematics"), (False, "8", "Mathematics"),
        (True, None, "Algebra I"),
        (True, None, "Biology"), (True, None, "U.S. History"),
    ],
}

COMPOSITE_ECR_GRADES = {
    "all-reading": ["3", "4", "5", "6", "7", "8"],
    "all-scores": ["3", "4", "5", "6", "7", "8"],
}


def compute_composite_benchmark(key):
    """Weighted state averages for a composite (all-reading, all-math, all-scores)."""
    defs = COMPOSITE_DEFS.get(key)
    if not defs:
        return None
    vals = []
    for cdc, data in staar.items():
        for is_eoc, grade, subject in defs:
            source = data.get("eoc" if is_eoc else "grades_3_8", {})
            if is_eoc:
                subj_data = source.get(subject)
            else:
                subj_data = source.get(str(grade), {}).get(subject)
            if subj_data and subj_data.get("tests_taken", 0) > 0 and subj_data.get("avg_scale"):
                vals.append(subj_data)
    if not vals:
        return None
    total_t = sum(v["tests_taken"] for v in vals)
    avg_scale = round(sum(v["avg_scale"] * v["tests_taken"] for v in vals) / total_t) if total_t else None
    app_pct = round(sum(v["app_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    meets_pct = round(sum(v["meets_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    mast_pct = round(sum(v["mast_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    dnm_pct = round(sum(v["dnm_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    return {
        "tests_taken": total_t,
        "avg_scale": avg_scale,
        "dnm_pct": dnm_pct,
        "app_pct": app_pct,
        "meets_pct": meets_pct,
        "mast_pct": mast_pct,
    }


def compute_region_composite_benchmark(region, key):
    """Weighted region averages for a composite."""
    defs = COMPOSITE_DEFS.get(key)
    if not defs:
        return None
    cdcs = region_districts.get(region, [])
    vals = []
    for cdc in cdcs:
        data = staar.get(cdc)
        if not data:
            continue
        for is_eoc, grade, subject in defs:
            source = data.get("eoc" if is_eoc else "grades_3_8", {})
            if is_eoc:
                subj_data = source.get(subject)
            else:
                subj_data = source.get(str(grade), {}).get(subject)
            if subj_data and subj_data.get("tests_taken", 0) > 0 and subj_data.get("avg_scale"):
                vals.append(subj_data)
    if not vals:
        return None
    total_t = sum(v["tests_taken"] for v in vals)
    avg_scale = round(sum(v["avg_scale"] * v["tests_taken"] for v in vals) / total_t) if total_t else None
    app_pct = round(sum(v["app_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    meets_pct = round(sum(v["meets_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    mast_pct = round(sum(v["mast_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    dnm_pct = round(sum(v["dnm_pct"] * v["tests_taken"] for v in vals) / total_t, 1) if total_t else None
    return {
        "tests_taken": total_t,
        "avg_scale": avg_scale,
        "dnm_pct": dnm_pct,
        "app_pct": app_pct,
        "meets_pct": meets_pct,
        "mast_pct": mast_pct,
    }


def compute_composite_ecr_benchmark(key):
    """Weighted state ECR distribution across multiple grades for a composite."""
    grades = COMPOSITE_ECR_GRADES.get(key)
    if not grades:
        return None
    ratings_sum = {str(i): 0.0 for i in range(11)}
    total_n = 0
    for cdc, data in staar.items():
        ecr = data.get("ecr", {})
        for g in grades:
            grade_ecr = ecr.get(g)
            if not grade_ecr or not grade_ecr.get("valid_n", 0):
                continue
            n = grade_ecr["valid_n"]
            total_n += n
            for i in range(11):
                si = str(i)
                ratings_sum[si] += grade_ecr.get("ratings", {}).get(si, 0) * n
    if total_n == 0:
        return None
    return {
        "valid_n": total_n,
        "ratings": {si: round(ratings_sum[si] / total_n, 1) for si in ratings_sum},
    }


def compute_region_composite_ecr_benchmark(region, key):
    """Weighted region ECR distribution across multiple grades for a composite."""
    grades = COMPOSITE_ECR_GRADES.get(key)
    if not grades:
        return None
    cdcs = region_districts.get(region, [])
    ratings_sum = {str(i): 0.0 for i in range(11)}
    total_n = 0
    for cdc in cdcs:
        data = staar.get(cdc)
        if not data:
            continue
        ecr = data.get("ecr", {})
        for g in grades:
            grade_ecr = ecr.get(g)
            if not grade_ecr or not grade_ecr.get("valid_n", 0):
                continue
            n = grade_ecr["valid_n"]
            total_n += n
            for i in range(11):
                si = str(i)
                ratings_sum[si] += grade_ecr.get("ratings", {}).get(si, 0) * n
    if total_n == 0:
        return None
    return {
        "valid_n": total_n,
        "ratings": {si: round(ratings_sum[si] / total_n, 1) for si in ratings_sum},
    }

# ── Benchmark cache ──
from functools import lru_cache

@lru_cache(maxsize=500)
def get_benchmark(subject, grade, is_eoc=False):
    return compute_benchmarks(subject, grade, is_eoc)

@lru_cache(maxsize=500)
def get_region_benchmark(region, subject, grade, is_eoc=False):
    return compute_region_benchmark(region, subject, grade, is_eoc)

@lru_cache(maxsize=250)
def get_ecr_benchmark(grade):
    return compute_ecr_benchmarks(grade)

@lru_cache(maxsize=250)
def get_region_ecr_benchmark(region, grade):
    return compute_region_ecr_benchmark(region, grade)

# ── FastAPI ──
app = FastAPI(title="Texas School Compass Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ── API: Search ──
@app.get("/api/search")
def search_districts(q: str = Query("", min_length=0)):
    if not q:
        return {"results": search_index[:50]}
    q = q.upper().strip()
    results = [d for d in search_index if q in d["name"].upper()]
    return {"results": results[:50]}

# ── API: District data (full) ──
@app.get("/api/district/{cdc}")
def get_district(cdc: str):
    district = district_info.get(cdc)
    if not district:
        raise HTTPException(404, f"District {cdc} not found")
    
    data = staar.get(cdc, {})
    master = master_by_cdc.get(cdc, {})
    
    result = {
        "cdc": cdc,
        "name": district.get("name", ""),
        "county": district.get("county", ""),
        "region": district_region.get(cdc, ""),
        "enrollment": master.get("enrollment", 0),
        "econ_disadv_pct": master.get("econ_disadv_pct", 0),
        "eb_el_pct": master.get("eb_el_pct", 0),
        "sped_pct": master.get("sped_pct", 0),
        "grades_3_8": data.get("grades_3_8", {}),
        "eoc": data.get("eoc", {}),
        "ecr": data.get("ecr", {}),
    }
    
    # ── Demographic peers ──
    demo_peers_raw = demo_sim.get(cdc, [])
    demo_peers = []
    for p in demo_peers_raw:
        pcdc = p["cdc"]
        pdata = staar.get(pcdc, {})
        pmaster = master_by_cdc.get(pcdc, {})
        demo_peers.append({
            "cdc": pcdc,
            "name": p["name"],
            "score": p["score"],
            "rank": p["rank"],
            "enrollment": pmaster.get("enrollment", 0),
            "econ_disadv_pct": pmaster.get("econ_disadv_pct", 0),
            "eb_el_pct": pmaster.get("eb_el_pct", 0),
            "sped_pct": pmaster.get("sped_pct", 0),
            "grades_3_8": pdata.get("grades_3_8", {}),
            "eoc": pdata.get("eoc", {}),
            "ecr": pdata.get("ecr", {}),
        })
    result["demo_peers"] = demo_peers
    
    # ── Geographic peers ──
    geo_peers_raw = geo_prox.get(cdc, [])
    geo_peers = []
    for p in geo_peers_raw:
        pcdc = p["cdc"]
        pdata = staar.get(pcdc, {})
        pmaster = master_by_cdc.get(pcdc, {})
        geo_peers.append({
            "cdc": pcdc,
            "name": p["name"],
            "dist_mi": p.get("dist_mi", 0),
            "rank": p["rank"],
            "enrollment": pmaster.get("enrollment", 0),
            "econ_disadv_pct": pmaster.get("econ_disadv_pct", 0),
            "eb_el_pct": pmaster.get("eb_el_pct", 0),
            "sped_pct": pmaster.get("sped_pct", 0),
            "grades_3_8": pdata.get("grades_3_8", {}),
            "eoc": pdata.get("eoc", {}),
            "ecr": pdata.get("ecr", {}),
        })
    result["geo_peers"] = geo_peers
    
    return result

# ── API: Subject benchmark ──
@app.get("/api/benchmark/{subject}/{grade}")
def get_benchmark_endpoint(subject: str, grade: str, region: Optional[str] = None):
    """Get state and optional region benchmarks for a subject/grade."""
    is_eoc = grade.upper() == "EOC"
    grade_val = grade
    state = get_benchmark(subject, grade_val, is_eoc)
    reg = None
    if region:
        reg = get_region_benchmark(region, subject, grade_val, is_eoc)
    return {"state": state, "region": reg}

# ── API: ECR benchmark ──
@app.get("/api/ecr-benchmark/{grade}")
def get_ecr_benchmark_endpoint(grade: str, region: Optional[str] = None):
    """Get state and optional region ECR score distributions for a grade."""
    grade_val = str(grade)
    state = get_ecr_benchmark(grade_val)
    reg = None
    if region:
        reg = get_region_ecr_benchmark(region, grade_val)
    return {"state": state, "region": reg}

# ── Composite cached wrappers ──
@lru_cache(maxsize=100)
def get_composite_benchmark(key):
    return compute_composite_benchmark(key)

@lru_cache(maxsize=100)
def get_region_composite_benchmark(region, key):
    return compute_region_composite_benchmark(region, key)

@lru_cache(maxsize=50)
def get_composite_ecr_benchmark(key):
    return compute_composite_ecr_benchmark(key)

@lru_cache(maxsize=50)
def get_region_composite_ecr_benchmark(region, key):
    return compute_region_composite_ecr_benchmark(region, key)

# ── API: Composite benchmark ──
@app.get("/api/composite-benchmark/{key}")
def get_composite_benchmark_endpoint(key: str, region: Optional[str] = None):
    """Get state and optional region benchmarks for a composite (all-reading, all-math, all-scores)."""
    if key not in COMPOSITE_DEFS:
        raise HTTPException(404, f"Composite '{key}' not found")
    state = get_composite_benchmark(key)
    reg = None
    if region:
        reg = get_region_composite_benchmark(region, key)
    return {"state": state, "region": reg}

# ── API: Composite ECR benchmark ──
@app.get("/api/composite-ecr-benchmark/{key}")
def get_composite_ecr_benchmark_endpoint(key: str, region: Optional[str] = None):
    """Get state and optional region ECR distributions for a composite."""
    if key not in COMPOSITE_ECR_GRADES:
        raise HTTPException(404, f"Composite ECR '{key}' not found")
    state = get_composite_ecr_benchmark(key)
    reg = None
    if region:
        reg = get_region_composite_ecr_benchmark(region, key)
    return {"state": state, "region": reg}

# ── API: Available subjects ──
@app.get("/api/catalog")
def get_catalog():
    """Return all available subjects and grades in the dataset."""
    catalog = {"grades_3_8": {}, "eoc": []}
    grades_seen = set()
    subjects_seen = set()
    
    # Scan 3-8
    for cdc, data in staar.items():
        for g, subs in data.get("grades_3_8", {}).items():
            grades_seen.add(g)
            for s in subs:
                subjects_seen.add(s)
    
    # Sort grades and subjects
    sorted_grades = sorted(grades_seen, key=int)
    sorted_subjects = sorted(subjects_seen)
    
    # Organize by grade
    for g in sorted_grades:
        g_subjects = set()
        for cdc, data in staar.items():
            for s in data.get("grades_3_8", {}).get(g, {}):
                g_subjects.add(s)
        catalog["grades_3_8"][g] = sorted(g_subjects)
    
    catalog["eoc"] = sorted(set(
        s for cdc, data in staar.items() for s in data.get("eoc", {})
    ))
    
    # ECR availability
    ecr_grades = set()
    ecr_eoc = set()
    for cdc, data in staar.items():
        for key in data.get("ecr", {}):
            if key in "0123456789":
                ecr_grades.add(key)
            else:
                ecr_eoc.add(key)
    catalog["ecr"] = {
        "grades_3_8": sorted(ecr_grades, key=int),
        "eoc": sorted(ecr_eoc),
    }
    
    catalog["grade_labels"] = {g: f"Grade {g}" for g in sorted_grades}
    catalog["grade_labels"]["EOC"] = "EOC"
    
    return catalog

# ── Server HTML ──
with open(BASE / "templates" / "index.html") as f:
    FRONTEND = f.read()

@app.get("/", response_class=HTMLResponse)
def index():
    return FRONTEND

@app.get("/favicon.ico")
def favicon():
    return HTMLResponse("")

# ── Run ──
if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8786
    print(f"\n🚀 Texas School Compass Dashboard")
    print(f"   http://localhost:{port}\n")
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
