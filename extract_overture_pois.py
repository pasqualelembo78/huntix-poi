#!/usr/bin/env python3
"""
extract_overture_pois.py — Estrae POI italiani da Overture Maps (DuckDB + S3)
Struttura: italia/{regione}/{citta}/{category}.csv

Uso: python3 extract_overture_pois.py
"""
import subprocess
import sys

def ensure_deps():
    """Install missing Python packages automatically."""
    required = {"duckdb": "duckdb"}
    for mod, pkg in required.items():
        try:
            __import__(mod)
        except ImportError:
            print(f"📦 Installazione {pkg}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", pkg])
            print(f"  ✅ {pkg} installato")

ensure_deps()

import duckdb
import re
import math
import os

REGIONS = {
    "1": ("Abruzzo",           "39.5,13.0,42.5,14.8"),
    "2": ("Basilicata",        "39.5,15.5,41.5,17.0"),
    "3": ("Calabria",          "37.5,15.5,40.0,17.5"),
    "4": ("Campania",          "39.5,13.5,41.5,16.5"),
    "5": ("Emilia-Romagna",    "43.5,10.5,45.5,13.0"),
    "6": ("Friuli V.G.",       "45.5,12.0,47.0,14.0"),
    "7": ("Lazio",             "40.5,11.5,43.0,14.0"),
    "8": ("Liguria",           "43.5,7.5,44.8,10.0"),
    "9": ("Lombardia",         "44.5,8.5,46.5,11.5"),
    "10": ("Marche",           "42.5,12.0,44.0,14.5"),
    "11": ("Molise",           "41.0,13.5,42.0,15.0"),
    "12": ("Piemonte",         "44.0,6.5,46.5,9.5"),
    "13": ("Puglia",           "39.5,15.0,42.5,18.5"),
    "14": ("Sardegna",         "38.5,8.0,41.5,10.0"),
    "15": ("Sicilia",          "36.5,12.0,38.5,15.5"),
    "16": ("Toscana",          "42.0,9.5,44.0,12.5"),
    "17": ("Trentino-A.A.",    "45.5,10.5,47.0,12.5"),
    "18": ("Umbria",           "42.0,12.0,43.5,13.5"),
    "19": ("Valle d'Aosta",    "45.5,6.5,46.5,8.0"),
    "20": ("Veneto",           "44.5,10.5,47.0,13.5"),
}

# Overture Maps basic_category -> our Huntix categories
# Values from actual Overture data (July 2026 release)
CATEGORY_MAP = {
    "hospitals": [
        "hospital",
    ],
    "restaurants": [
        "restaurant",
        "fast_food_restaurant",
        "food_service",
    ],
    "bars_cafes": [
        "bar",
        "cafe",
    ],
    "gyms": [
        "gym",
        "fitness_studio",
        "sport_or_fitness_facility",
    ],
    "landmarks": [
        "museum",
        "monument",
        "castle",
    ],
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

S3_PATH = "s3://overturemaps-us-west-2/release/2026-07-22.0/theme=places/type=place/*"


def normalize_name(name):
    name = name.lower().strip()
    name = name.replace("'", "").replace("'", "")
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "_", name)
    return name


def haversine_km(lat1, lng1, lat2, lng2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def query_overture_pois(con, bbox, categories):
    """Query Overture Maps via DuckDB for places matching categories in bbox."""
    south, west, north, east = [float(x) for x in bbox.split(",")]

    # Build SQL: filter by bbox and category
    cat_filters = " OR ".join([f"basic_category = '{c}'" for c in categories])

    sql = f"""
    SELECT
        ST_Y(geometry) as lat,
        ST_X(geometry) as lng,
        id,
        COALESCE(names.primary, 'unknown') as name,
        basic_category,
        COALESCE(addresses[1].locality, '') as city,
        COALESCE(addresses[1].region, '') as region,
        COALESCE(addresses[1].country, '') as country,
        confidence
    FROM
        read_parquet('{S3_PATH}', filename=true, hive_partitioning=1)
    WHERE
        bbox.xmin BETWEEN {west} AND {east}
        AND bbox.ymin BETWEEN {south} AND {north}
        AND ({cat_filters})
        AND confidence > 0.5
    """

    result = con.execute(sql)
    return result.fetchall()


def query_cities(con, bbox):
    """Query place=city|town|village from Overture divisions theme for reverse geocoding."""
    south, west, north, east = [float(x) for x in bbox.split(",")]

    sql = f"""
    SELECT
        ST_Y(geometry) as lat,
        ST_X(geometry) as lng,
        names.primary as name
    FROM
        read_parquet('s3://overturemaps-us-west-2/release/2026-07-22.0/theme=divisions/type=division_area/*', filename=true, hive_partitioning=1)
    WHERE
        subtype = 'locality'
        AND bbox.xmin BETWEEN {west} AND {east}
        AND bbox.ymin BETWEEN {south} AND {north}
    """

    result = con.execute(sql)
    return result.fetchall()


def find_nearest_city(lat, lng, cities_cache):
    if not cities_cache:
        return None
    best = None
    best_dist = float("inf")
    for c_lat, c_lng, c_name in cities_cache:
        d = haversine_km(lat, lng, c_lat, c_lng)
        if d < best_dist:
            best_dist = d
            best = c_name
    if best_dist <= 30:
        return best
    return None


def save_csv(filename, title, lines):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# lat,lng,id,name,building_type,type\n# {title}\n")
        for l in lines:
            f.write(l + "\n")


def read_existing_keys(filename):
    keys = set()
    if not os.path.exists(filename):
        return keys
    with open(filename, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split(",")
            if len(parts) >= 4:
                keys.add(f"{parts[3]}_{parts[0]}_{parts[1]}")
    return keys


def merge_csv(filename, title, new_lines):
    existing_keys = read_existing_keys(filename)
    existing = []
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                if not line.strip().startswith("#") and line.strip():
                    existing.append(line.strip())
    added = 0
    for l in new_lines:
        parts = l.split(",")
        if len(parts) >= 4:
            key = f"{parts[3]}_{parts[0]}_{parts[1]}"
            if key in existing_keys:
                continue
            existing_keys.add(key)
        existing.append(l)
        added += 1
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# lat,lng,id,name,building_type,type\n# {title}\n")
        for l in existing:
            f.write(l + "\n")
    return added, len(existing)


def main():
    print("=" * 55)
    print("  🗺️  Huntix POI Extractor — Overture Maps")
    print("=" * 55)
    print()

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"📁 Repo: {repo_dir}\n")

    print("Scegli la regione da scaricare:\n")
    for k, (name, _) in sorted(REGIONS.items(), key=lambda x: int(x[0])):
        print(f"  [{k:>2}] {name}")
    print()

    choice = input(">>> Inserisci il numero (1-20): ").strip()
    if choice not in REGIONS:
        print("❌ Scelta non valida.")
        return

    region_name, bbox = REGIONS[choice]
    region_slug = normalize_name(region_name)
    print(f"\n📍 Regione: {region_name}")
    print(f"📦 Bounding box: {bbox}\n")

    # Create directory structure
    region_dir = os.path.join(repo_dir, "italia", region_slug)
    os.makedirs(region_dir, exist_ok=True)

    # Connect to DuckDB
    print("🔌 Connessione a DuckDB + Overture Maps S3...")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    print("  ✅ Connesso\n")

    # Load cities for reverse geocoding
    print("🏙️  Carico città per assegnazione...")
    cities_cache = query_cities(con, bbox)
    print(f"  📦 {len(cities_cache)} luoghi trovati\n")

    all_pois = []
    city_pois = {}

    # Query each category
    for cat_key, overture_cats in CATEGORY_MAP.items():
        print(f"🔍 {cat_key}...")

        rows = query_overture_pois(con, bbox, overture_cats)
        print(f"  📦 {len(rows)} POI totali")

        for row in rows:
            lat, lng, oid, name, basic_cat, city_from_addr, region_from_addr, country_from_addr, confidence = row

            if not lat or not lng:
                continue
            if not name or name == "unknown" or len(name) < 3:
                continue

            # Determine city: use address first, then reverse geocode
            city = city_from_addr if city_from_addr else None
            if not city:
                city = find_nearest_city(lat, lng, cities_cache)
            if not city:
                city = "sconosciuta"

            city_slug = normalize_name(city)
            if city_slug not in city_pois:
                city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": []}

            # Map basic_category to our type and buildingType for app compatibility
            # type="building" + buildingType=HOUSE|RESTAURANT|SUPERMARKET|HOSPITAL|GYM|MONUMENT|MUSEUM
            # For non-enterable POIs: type="landmark", buildingType=""
            ov_to_building = {
                "hospitals": ("building", "HOSPITAL"),
                "restaurants": ("building", "RESTAURANT"),
                "bars_cafes": ("building", "RESTAURANT"),
                "gyms": ("building", "GYM"),
                "landmarks": ("building", "MONUMENT"),
            }
            csv_type, building_type = ov_to_building.get(cat_key, ("landmark", ""))

            # Museums get MUSEUM buildingType
            if cat_key == "landmarks" and basic_cat == "museum":
                building_type = "MUSEUM"

            safe_name = name.replace('"', "").strip()[:60]
            safe_name_csv = f'"{safe_name}"' if "," in safe_name else safe_name
            pid = re.sub(r"[^a-zA-Z0-9]", "_", safe_name.lower())[:40]
            line = f"{lat:.6f},{lng:.6f},ov_{pid}_{lat:.4f}_{lng:.4f},{safe_name_csv},{csv_type},{building_type}"

            city_pois[city_slug][cat_key].append(line)
            all_pois.append(line)

        print()

    # Close DuckDB connection
    con.close()

    # Save per-city files + _all.csv per città
    print("💾 Salvataggio...\n")

    total_cities = 0
    total_files = 0
    city_coords = {}

    for city_slug, data in sorted(city_pois.items()):
        city_dir = os.path.join(region_dir, city_slug)
        os.makedirs(city_dir, exist_ok=True)
        all_city_lines = []
        for cat_key in ["hospitals", "restaurants", "bars_cafes", "gyms", "landmarks"]:
            lines = data[cat_key]
            if lines:
                filepath = os.path.join(city_dir, f"{cat_key}.csv")
                added, total = merge_csv(filepath, f"{data['city_name']} — {cat_key}", lines)
                all_city_lines.extend(lines)
                total_files += 1

        if all_city_lines:
            all_file = os.path.join(city_dir, "_all.csv")
            merge_csv(all_file, f"{data['city_name']} — Tutti i POI", all_city_lines)
            total_files += 1

        # Track city coordinates
        lat_sum, lng_sum, count = 0.0, 0.0, 0
        for cat_key in ["hospitals", "restaurants", "bars_cafes", "gyms", "landmarks"]:
            for line in data[cat_key]:
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        lat_sum += float(parts[0])
                        lng_sum += float(parts[1])
                        count += 1
                    except:
                        pass
        if count > 0:
            city_coords[city_slug] = {
                "lat": lat_sum / count,
                "lng": lng_sum / count,
                "name": data["city_name"],
                "h": len(data["hospitals"]),
                "r": len(data["restaurants"]),
                "g": len(data["gyms"]),
                "l": len(data["landmarks"]),
            }
        total_cities += 1

    # Save region index (_citta.csv)
    index_file = os.path.join(region_dir, "_citta.csv")
    with open(index_file, "w", encoding="utf-8") as f:
        f.write("# lat,lng,citta,slug,ospedali,ristoranti,palestre,monumenti\n")
        for city_slug, coords in sorted(city_coords.items()):
            f.write(f"{coords['lat']:.6f},{coords['lng']:.6f},{coords['name']},{city_slug},{coords['h']},{coords['r']},{coords['g']},{coords['l']}\n")

    # Save region summary
    region_file = os.path.join(region_dir, "_all.csv")
    merge_csv(region_file, f"{region_name} — Tutti i POI", all_pois)

    # Update global index
    regions_index = os.path.join(repo_dir, "italia", "_regioni.csv")
    existing_regions = set()
    if os.path.exists(regions_index):
        with open(regions_index, "r") as f:
            for line in f:
                if not line.startswith("#") and line.strip():
                    existing_regions.add(line.strip().split(",")[0])
    with open(regions_index, "a", encoding="utf-8") as f:
        if region_name not in existing_regions:
            f.write(f"{region_name},{region_slug}\n")

    # Update global_pois.csv
    global_file = os.path.join(repo_dir, "global_pois.csv")
    added, total = merge_csv(global_file, "Huntix Global POI — Tutte le regioni", all_pois)

    print(f"✅ Completato!")
    print(f"   🏘️  {total_cities} città")
    print(f"   📄 {total_files} file CSV")
    print(f"   📊 Global: +{added} nuovi / {total} totali\n")

    # --- GIT PUSH ---
    print("=" * 55)
    print("  📤 Push su GitHub")
    print("=" * 55)
    print()

    token = input(">>> Inserisci il token GitHub (ghp_...): ").strip()
    if not token:
        print("❌ Token vuoto, push annullato.")
        return

    remote_url = f"https://pasqualelembo78:{token}@github.com/pasqualelembo78/huntix-poi.git"

    try:
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(
            ["git", "commit", "-m", f"POI {region_name} (Overture Maps) — {total_cities} città, {len(all_pois)} POI"],
            cwd=repo_dir, check=True
        )
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=repo_dir, check=True)
        result = subprocess.run(["git", "push", "origin", "main"], cwd=repo_dir, capture_output=True, text=True)
        if result.returncode == 0:
            print("\n🎉 Push completato!")
        else:
            print(f"\n❌ Push fallito:\n{result.stderr}")
            return
    except subprocess.CalledProcessError as e:
        print(f"\n❌ Errore git: {e}")
        return
    finally:
        subprocess.run(["git", "remote", "set-url", "origin", "https://github.com/pasqualelembo78/huntix-poi.git"], cwd=repo_dir)


if __name__ == "__main__":
    main()
