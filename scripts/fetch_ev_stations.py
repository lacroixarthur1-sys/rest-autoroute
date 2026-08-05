#!/usr/bin/env python3
"""Match every aire against the French national EV charging station database (IRVE)
by proximity, and cache the aggregated result to scripts/ev_cache.json.

Data source: consolidated IRVE static file from transport.data.gouv.fr / data.gouv.fr
(open data, daily consolidation of all charge-point operators, per arrete du 4 mai 2021).

Run from anywhere: python3 scripts/fetch_ev_stations.py [path-to-csv]
If no CSV path is given, the current consolidated file is downloaded first.
"""
import csv
import json
import math
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate_seo_pages import load_routes, assign_slugs  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
EV_CACHE_PATH = ROOT / "scripts" / "ev_cache.json"
DATASET_API = "https://www.data.gouv.fr/api/1/datasets/base-nationale-des-irve-infrastructures-de-recharge-pour-vehicules-electriques/"
MATCH_RADIUS_KM = 1.0
BUCKET_SIZE = 0.02  # ~2.2km, must be >= MATCH_RADIUS_KM in degrees so neighbor buckets cover it
MAX_PLAUSIBLE_KW = 600  # discard obviously bad data (dataset is known to contain >2MW junk rows)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bucket_key(lat, lon):
    return (round(lat / BUCKET_SIZE), round(lon / BUCKET_SIZE))


def download_csv(dest):
    import urllib.request as req
    meta = json.loads(req.urlopen(DATASET_API, timeout=30).read().decode("utf-8"))
    url = None
    for r in meta.get("resources", []):
        if r.get("format") == "csv" and "Consolidation de la derni" in (r.get("title") or ""):
            url = r["url"]
            break
    if not url:
        raise SystemExit("Could not find consolidated CSV resource")
    print(f"Downloading {url} ...")
    req.urlretrieve(url, dest)
    return dest


def main():
    routes = load_routes()
    for route in routes:
        assign_slugs(route)

    aires = []
    for route in routes:
        for aire in route["aires"]:
            aires.append({"route_id": route["id"], "slug": aire["_slug"], "lat": aire["lat"], "lng": aire["lng"]})

    buckets = {}
    for idx, a in enumerate(aires):
        for dlat in (-BUCKET_SIZE, 0, BUCKET_SIZE):
            for dlon in (-BUCKET_SIZE, 0, BUCKET_SIZE):
                buckets.setdefault(bucket_key(a["lat"] + dlat, a["lng"] + dlon), set()).add(idx)

    if len(sys.argv) > 1:
        csv_path = Path(sys.argv[1])
    else:
        csv_path = Path(download_csv(str(ROOT / "scripts" / "_irve_tmp.csv")))

    matched = {i: {} for i in range(len(aires))}  # aire idx -> station_id -> row info
    n_rows = 0
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            n_rows += 1
            try:
                lat = float(row.get("consolidated_latitude") or row.get("ylatitude") or "")
                lon = float(row.get("consolidated_longitude") or row.get("xlongitude") or "")
            except (TypeError, ValueError):
                continue
            key = bucket_key(lat, lon)
            candidates = buckets.get(key)
            if not candidates:
                continue
            for i in candidates:
                a = aires[i]
                if haversine_km(a["lat"], a["lng"], lat, lon) <= MATCH_RADIUS_KM:
                    try:
                        power = float(row.get("puissance_nominale") or 0)
                    except ValueError:
                        power = 0
                    if power > MAX_PLAUSIBLE_KW:
                        power = 0
                    station_id = row.get("id_station_itinerance") or row.get("id_station_local") or row.get("nom_station")
                    st = matched[i].setdefault(station_id, {
                        "operator": (row.get("nom_operateur") or row.get("nom_enseigne") or "").strip(),
                        "points": 0,
                        "max_power": 0,
                        "connectors": set(),
                    })
                    st["points"] += 1
                    st["max_power"] = max(st["max_power"], power)
                    for field, label in (
                        ("prise_type_2", "Type 2"),
                        ("prise_type_combo_ccs", "Combo CCS"),
                        ("prise_type_chademo", "CHAdeMO"),
                        ("prise_type_ef", "EF"),
                    ):
                        if (row.get(field) or "").strip().lower() == "true":
                            st["connectors"].add(label)
            if n_rows % 40000 == 0:
                print(f"...{n_rows} rows scanned")

    cache = {}
    for i, a in enumerate(aires):
        stations = matched[i]
        if not stations:
            cache[f"{a['lat']:.5f},{a['lng']:.5f}"] = None
            continue
        n_points = sum(s["points"] for s in stations.values())
        max_power = max((s["max_power"] for s in stations.values()), default=0)
        connectors = sorted(set().union(*(s["connectors"] for s in stations.values())))
        operators = sorted({s["operator"] for s in stations.values() if s["operator"]})[:4]
        cache[f"{a['lat']:.5f},{a['lng']:.5f}"] = {
            "n_stations": len(stations),
            "n_points": n_points,
            "max_power_kw": round(max_power),
            "connectors": connectors,
            "operators": operators,
        }

    EV_CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    n_with = sum(1 for v in cache.values() if v)
    print(f"Scanned {n_rows} IRVE rows. {n_with}/{len(aires)} aires matched with at least one charging station.")


if __name__ == "__main__":
    main()
