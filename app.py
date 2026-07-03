#!/usr/bin/env python3
"""Texas District Dashboard — Prototype MVP"""
import json, csv, re, math
from pathlib import Path
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn

# ── Data paths ──
DATA = Path.home() / ".hermes" / "persistent_workspace" / "district-comparison"
SRC  = Path.home() / "src" / "texas-district-comparison" / "data"
TMP  = Path("/tmp")

# ── Load enriched master list (demographics for all districts) ──
print("Loading enriched master list...")
with open(DATA / "master_district_list_enriched.json") as f:
    all_districts_raw = json.load(f)

by_cdc = {}
for d in all_districts_raw:
    cdc = d["cdc"]
    by_cdc[cdc] = {
        "cdc": cdc,
        "name": d["name"],
        "county": d.get("county", ""),
        "region": d.get("region_name", ""),
        "lat": d.get("lat"),
        "lon": d.get("lon"),
        "enrollment": d.get("enrollment", 0),
        "charter": d.get("charter", False),
        "tea_rating": d.get("tea_rating", ""),
        "econ_disadv_pct": d.get("econ_disadv_pct", 0),
        "eb_el_pct": d.get("eb_el_pct", 0),
        "sped_pct": d.get("sped_pct", 0),
        "at_risk_pct": d.get("at_risk_pct", 0),
        "bilingual_pct": d.get("bilingual_pct", 0),
        "gifted_pct": d.get("gifted_pct", 0),
        "hispanic_pct": d.get("hispanic_pct", 0),
        "white_pct": d.get("white_pct", 0),
        "black_pct": d.get("black_pct", 0),
        "asian_pct": d.get("asian_pct", 0),
        "native_pct": d.get("native_pct", 0),
        "two_or_more_pct": d.get("two_or_more_pct", 0),
    }

print(f"  {len(by_cdc)} districts loaded")

# ── Load demographic similarity peers ──
print("Loading demographic similarity...")
with open(DATA / "demographic_similarity.json") as f:
    demo_sim = json.load(f)
print(f"  {len(demo_sim)} entries")

# ── Load geographic proximity peers ──
print("Loading geographic proximity...")
with open(DATA / "geographic_proximity.json") as f:
    geo_prox = json.load(f)
print(f"  {len(geo_prox)} entries")

# ── Load TAPR performance data ──
print("Loading TAPR performance data...")
# Structure: {cdc: {subject: {grade: {"app": X, "meets": X, "mast": X}}}}
tapr_data = {}

tapr_files = sorted(TMP.glob("tapr_gr*_math_2025.csv"))
for fp in tapr_files:
    # Extract grade from filename (e.g., tapr_gr3_math_2025.csv)
    m = re.search(r"gr(\d+)", fp.name)
    if not m:
        continue
    grade = int(m.group(1))
    subject = "math"

    with open(fp, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row or len(row) < 5:
                continue
            cdc = row[0].strip()
            name = row[1].strip()
            if cdc not in tapr_data:
                tapr_data[cdc] = {"name": name}
            if subject not in tapr_data[cdc]:
                tapr_data[cdc][subject] = {}
            
            # Parse the key columns (App+, Meets+, Masters)
            try:
                app = float(row[2]) if row[2] and row[2] != "-1" else None
            except:
                app = None
            try:
                meets = float(row[3]) if row[3] and row[3] != "-1" else None
            except:
                meets = None
            try:
                mast = float(row[4]) if row[4] and row[4] != "-1" else None
            except:
                mast = None
            
            tapr_data[cdc][subject][grade] = {
                "app": app,
                "meets": meets,
                "mast": mast
            }

print(f"  {len(tapr_data)} districts with TAPR data")
print(f"  Grades: {sorted(set(g for d in tapr_data.values() for s in d if s != 'name' for g in d[s].keys()))}")

# ── Build search index ──
search_index = []
for cdc, d in by_cdc.items():
    search_index.append({
        "cdc": cdc,
        "name": d["name"],
        "county": d["county"],
        "region": d["region"],
    })
search_index.sort(key=lambda x: x["name"])

# ── FastAPI app ──
app = FastAPI(title="Texas District Dashboard", version="0.1.0")

# ── API endpoints ──

@app.get("/api/search")
def search_districts(q: str = Query("", min_length=0)):
    """Search districts by name."""
    if not q:
        return {"results": search_index[:50]}
    
    q = q.upper().strip()
    results = [d for d in search_index if q in d["name"].upper()]
    return {"results": results[:50]}

@app.get("/api/districts/{cdc}")
def get_district(cdc: str):
    """Get full district profile with peer groups."""
    district = by_cdc.get(cdc)
    if not district:
        # Try to find by name?
        raise HTTPException(404, f"District {cdc} not found")
    
    result = {**district}
    
    # Add performance data
    perf = tapr_data.get(cdc, {})
    result["performance"] = {
        k: v for k, v in perf.items() if k != "name"
    }
    
    # Add demographic peers
    demo_peers_raw = demo_sim.get(cdc, [])
    demo_peers = []
    for p in demo_peers_raw:
        peer_info = by_cdc.get(p["cdc"], {})
        demo_peers.append({
            "cdc": p["cdc"],
            "name": p["name"],
            "score": p["score"],
            "rank": p["rank"],
            "enrollment": peer_info.get("enrollment", 0),
            "econ_disadv_pct": peer_info.get("econ_disadv_pct", 0),
            "eb_el_pct": peer_info.get("eb_el_pct", 0),
            "sped_pct": peer_info.get("sped_pct", 0),
            "performance": {
                k: v for k, v in tapr_data.get(p["cdc"], {}).items() if k != "name"
            }
        })
    result["demo_peers"] = demo_peers
    
    # Add geographic peers
    geo_peers_raw = geo_prox.get(cdc, [])
    geo_peers = []
    for p in geo_peers_raw:
        peer_info = by_cdc.get(p["cdc"], {})
        geo_peers.append({
            "cdc": p["cdc"],
            "name": p["name"],
            "dist_mi": p.get("dist_mi", 0),
            "rank": p["rank"],
            "enrollment": peer_info.get("enrollment", 0),
            "econ_disadv_pct": peer_info.get("econ_disadv_pct", 0),
            "eb_el_pct": peer_info.get("eb_el_pct", 0),
            "sped_pct": peer_info.get("sped_pct", 0),
            "performance": {
                k: v for k, v in tapr_data.get(p["cdc"], {}).items() if k != "name"
            }
        })
    result["geo_peers"] = geo_peers
    
    # Calculate peer group averages
    for label, peers_list in [("demo_avg", demo_peers), ("geo_avg", geo_peers)]:
        grades_found = set()
        for p in peers_list:
            for subj, grades in p.get("performance", {}).items():
                for g in grades:
                    grades_found.add(g)
        
        avg = {}
        for g in sorted(grades_found):
            apps = [p["performance"].get("math", {}).get(g, {}).get("app") for p in peers_list]
            meets = [p["performance"].get("math", {}).get(g, {}).get("meets") for p in peers_list]
            masts = [p["performance"].get("math", {}).get(g, {}).get("mast") for p in peers_list]
            apps = [a for a in apps if a is not None]
            meets = [m for m in meets if m is not None]
            masts = [m for m in masts if m is not None]
            avg[g] = {
                "app": round(sum(apps)/len(apps), 1) if apps else None,
                "meets": round(sum(meets)/len(meets), 1) if meets else None,
                "mast": round(sum(masts)/len(masts), 1) if masts else None,
            }
        result[label] = avg
    
    return result

# ── Serve frontend ──
with open(Path(__file__).parent / "templates" / "index.html") as f:
    FRONTEND_HTML = f.read()

@app.get("/", response_class=HTMLResponse)
def index():
    return FRONTEND_HTML

@app.get("/favicon.ico")
def favicon():
    return HTMLResponse("")

# ── Run ──
if __name__ == "__main__":
    print("\n🚀 Starting Texas District Dashboard...")
    print("   Open http://localhost:8000 in your browser\n")
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8786
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
