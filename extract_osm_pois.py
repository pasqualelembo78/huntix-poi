#!/usr/bin/env python3
"""
extract_osm_pois.py — Estrae POI italiani da OpenStreetMap (Overpass API)
Struttura: italia/{regione}/{citta}/{category}.csv

Uso: python3 extract_osm_pois.py
"""
import json
import urllib.request
import urllib.parse
import re
import time
import os
import subprocess

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

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

CATEGORIES = [
    ("hospitals",  '"amenity"="hospital"',                       "hospital"),
    ("restaurants",'"amenity"~"restaurant|fast_food"',           "ristorante"),
    ("bars_cafes", '"amenity"~"bar|cafe|pub"',                  "bar_cafe"),
    ("gyms",       '"leisure"="fitness_centre"',                 "palestra"),
    ("government", '"amenity"~"townhall|courthouse|registration_hall|job_centre"', "ufficio_pubblico"),
    ("banks",      '"amenity"="bank"',                         "banca"),
    ("post_offices",'"amenity"="post_office"',                      "ufficio_postale"),
    ("libraries",  '"amenity"="library"',                          "biblioteca"),
]

LANDMARK_TAGS = [
    '"tourism"="attraction"',
    '"tourism"="museum"',
    '"tourism"="castle"',
    '"tourism"="gallery"',
    '"historic"="monument"',
    '"historic"="castle"',
    '"historic"="archaeological_site"',
    '"historic"="memorial"',
    '"historic"="ruins"',
    '"amenity"="place_of_worship"',
]


def query_overpass(query_str, retries=3):
    for attempt in range(retries):
        try:
            data = urllib.parse.urlencode({"data": query_str}).encode("utf-8")
            req = urllib.request.Request(OVERPASS_URL, data=data, method="POST")
            req.add_header("User-Agent", "Huntix-POI-Extractor/1.0")
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8")).get("elements", [])
        except Exception as e:
            print(f"    ⚠️  Tentativo {attempt+1} fallito: {e}")
            if attempt < retries - 1:
                wait = 15 * (attempt + 1)
                print(f"    ⏳ Attendo {wait}s...")
                time.sleep(wait)
    return []


def query_cities_in_region(bbox):
    """Query all places (city/town/village) in the region for reverse assignment."""
    q = f'[out:json][timeout:120];(node["place"~"city|town|village"]({bbox}););out tags;'
    els = query_overpass(q)
    cities = []
    for el in els:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:it")
        lat, lng = el.get("lat"), el.get("lon")
        if name and lat and lng:
            cities.append({"name": name.strip(), "lat": lat, "lng": lng})
    return cities


def haversine_km(lat1, lng1, lat2, lng2):
    """Haversine distance in km between two points."""
    import math
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def find_nearest_city(lat, lng, cities_cache):
    """Find nearest city from pre-loaded cities list."""
    if not cities_cache:
        return None
    best = None
    best_dist = float("inf")
    for c in cities_cache:
        d = haversine_km(lat, lng, c["lat"], c["lng"])
        if d < best_dist:
            best_dist = d
            best = c
    if best_dist <= 30:
        return best["name"]
    return None


def extract_city(tags):
    """Extract city name from OSM tags."""
    city = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village")
    if city:
        return city.strip()
    # Fallback: try to get from is_in or place tags
    is_in = tags.get("is_in:city") or tags.get("is_in")
    if is_in:
        return is_in.split(",")[0].strip()
    return None


def normalize_name(name):
    """Normalize city/region name for folder names."""
    name = name.lower().strip()
    name = name.replace("'", "").replace("'", "")
    name = re.sub(r"[^a-z0-9\s-]", "", name)
    name = re.sub(r"\s+", "_", name)
    return name


def parse_pois(elements, csv_type, cities_cache=None):
    """Parse OSM elements into structured POI dicts."""
    pois = []
    seen = set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:it") or tags.get("name:en")
        if not name or len(name) < 3:
            continue
        if el["type"] == "node":
            lat, lng = el.get("lat"), el.get("lon")
        else:
            c = el.get("center", {})
            lat, lng = c.get("lat"), c.get("lon")
        if not lat or not lng:
            continue
        city = extract_city(tags)
        if not city and cities_cache:
            city = find_nearest_city(lat, lng, cities_cache)
        name = name.replace('"', "").strip()[:60]
        key = f"{name}_{lat:.3f}_{lng:.3f}"
        if key in seen:
            continue
        seen.add(key)
        pid = re.sub(r"[^a-zA-Z0-9]", "_", name.lower())[:40]
        safe_name = f'"{name}"' if "," in name else name
        pois.append({
            "lat": lat,
            "lng": lng,
            "id": f"osm_{pid}_{lat:.4f}_{lng:.4f}",
            "name": safe_name,
            "type": csv_type,
            "city": city,
            "line": f"{lat:.6f},{lng:.6f},osm_{pid}_{lat:.4f}_{lng:.4f},{safe_name},{csv_type},{csv_type}"
        })
    return pois


def save_csv(filename, title, lines):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# lat,lng,id,name,building_type,type\n# {title}\n")
        for l in lines:
            f.write(l + "\n")


def read_existing_keys(filename):
    """Read existing CSV and return set of dedup keys."""
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
    """Merge new lines into existing CSV, skip duplicates. Returns (added, total)."""
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
    print("  🗺️  Huntix POI Extractor — OpenStreetMap")
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

    # Query all places in region for reverse geocoding
    print("🏙️  Carico città/town/village per assegnazione...")
    cities_cache = query_cities_in_region(bbox)
    print(f"  📦 {len(cities_cache)} luoghi trovati\n")

    # Create directory structure
    region_dir = os.path.join(repo_dir, "italia", region_slug)
    os.makedirs(region_dir, exist_ok=True)

    all_pois = []  # All POIs for summary
    city_pois = {}  # city_name -> { category -> [lines] }

    # --- HOSPITALS ---
    print("🔍 hospitals...")
    q = f'[out:json][timeout:120];(node["amenity"="hospital"]({bbox});way["amenity"="hospital"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "hospital", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": []}
        city_pois[city_slug]["hospitals"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- RESTAURANTS ---
    print("🔍 restaurants...")
    q = f'[out:json][timeout:120];(node["amenity"~"restaurant|fast_food|pizzeria"]({bbox});way["amenity"~"restaurant|fast_food|pizzeria"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "ristorante", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": []}
        city_pois[city_slug]["restaurants"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- GYMS ---
    print("🔍 gyms...")
    q = f'[out:json][timeout:120];(node["leisure"="fitness_centre"]({bbox});way["leisure"="fitness_centre"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "palestra", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["gyms"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- BARS & CAFES ---
    print("🔍 bars_cafes...")
    q = f'[out:json][timeout:120];(node["amenity"~"bar|cafe|pub"]({bbox});way["amenity"~"bar|cafe|pub"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "bar_cafe", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["bars_cafes"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- LANDMARKS (unica query con union) ---
    print("🔍 landmarks...")
    lm_union = ";".join([f'node[{t}]({bbox});way[{t}]({bbox})' for t in LANDMARK_TAGS])
    q = f'[out:json][timeout:120];({lm_union});out center tags;'
    els = query_overpass(q)
    all_landmarks = parse_pois(els, "monumento", cities_cache)
    seen_lm = set()
    unique_landmarks = []
    for p in all_landmarks:
        if p["id"] not in seen_lm:
            seen_lm.add(p["id"])
            unique_landmarks.append(p)
    print(f"  📦 {len(unique_landmarks)} POI totali")
    for p in unique_landmarks:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["landmarks"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- GOVERNMENT ---
    print("🔍 government...")
    gov_tags = [
        '"amenity"="townhall"', '"amenity"="courthouse"',
        '"amenity"="registration_hall"', '"amenity"="job_centre"',
        '"office"="government"',
    ]
    gov_union = ";".join([f'node[{t}]({bbox});way[{t}]({bbox})' for t in gov_tags])
    q = f'[out:json][timeout:120];({gov_union});out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "ufficio_pubblico", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["government"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- BANKS ---
    print("🔍 banks...")
    q = f'[out:json][timeout:120];(node["amenity"="bank"]({bbox});way["amenity"="bank"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "banca", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["banks"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- POST OFFICES ---
    print("🔍 post_offices...")
    q = f'[out:json][timeout:120];(node["amenity"="post_office"]({bbox});way["amenity"="post_office"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "ufficio_postale", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["post_offices"].append(p["line"])
        all_pois.append(p["line"])
    print()
    time.sleep(5)

    # --- LIBRARIES ---
    print("🔍 libraries...")
    q = f'[out:json][timeout:120];(node["amenity"="library"]({bbox});way["amenity"="library"]({bbox}););out center tags;'
    elements = query_overpass(q)
    pois = parse_pois(elements, "biblioteca", cities_cache)
    print(f"  📦 {len(pois)} POI totali")
    for p in pois:
        city = p["city"] or "sconosciuta"
        city_slug = normalize_name(city)
        if city_slug not in city_pois:
            city_pois[city_slug] = {"city_name": city, "hospitals": [], "restaurants": [], "bars_cafes": [], "gyms": [], "landmarks": [], "government": [], "banks": [], "post_offices": [], "libraries": []}
        city_pois[city_slug]["libraries"].append(p["line"])
        all_pois.append(p["line"])
    print()

    # --- SAVE FILES ---
    print("💾 Salvataggio...\n")

    # Save per-city files + _all.csv per città
    total_cities = 0
    total_files = 0
    city_coords = {}  # city_slug -> {lat_sum, lng_sum, count, city_name}
    CAT_KEYS = ["hospitals", "restaurants", "bars_cafes", "gyms", "landmarks",
                "government", "banks", "post_offices", "libraries"]
    for city_slug, data in sorted(city_pois.items()):
        city_dir = os.path.join(region_dir, city_slug)
        os.makedirs(city_dir, exist_ok=True)
        all_city_lines = []
        for cat_key in CAT_KEYS:
            lines = data[cat_key]
            if lines:
                filepath = os.path.join(city_dir, f"{cat_key}.csv")
                added, total = merge_csv(filepath, f"{data['city_name']} — {cat_key}", lines)
                all_city_lines.extend(lines)
                total_files += 1
        # Create _all.csv per city
        if all_city_lines:
            all_file = os.path.join(city_dir, "_all.csv")
            merge_csv(all_file, f"{data['city_name']} — Tutti i POI", all_city_lines)
            total_files += 1
        # Track city coordinates (centroid)
        lat_sum, lng_sum, count = 0.0, 0.0, 0
        for cat_key in CAT_KEYS:
            for line in data[cat_key]:
                parts = line.split(",")
                if len(parts) >= 2:
                    try:
                        lat_sum += float(parts[0])
                        lng_sum += float(parts[1])
                        count += 1
                    except: pass
        if count > 0:
            city_coords[city_slug] = {
                "lat": lat_sum / count,
                "lng": lng_sum / count,
                "name": data["city_name"],
                "h": len(data["hospitals"]),
                "r": len(data["restaurants"]),
                "b": len(data["bars_cafes"]),
                "g": len(data["gyms"]),
                "l": len(data["landmarks"]),
                "gov": len(data["government"]),
                "bank": len(data["banks"]),
                "post": len(data["post_offices"]),
                "lib": len(data["libraries"]),
            }
        total_cities += 1

    # Save region index (_citta.csv) with coordinates
    index_file = os.path.join(region_dir, "_citta.csv")
    with open(index_file, "w", encoding="utf-8") as f:
        f.write("# lat,lng,citta,slug,ospedali,ristoranti,bar_cafe,palestre,monumenti,governo,banche,poste,biblioteche\n")
        for city_slug, coords in sorted(city_coords.items()):
            f.write(f"{coords['lat']:.6f},{coords['lng']:.6f},{coords['name']},{city_slug},"
                    f"{coords['h']},{coords['r']},{coords['b']},{coords['g']},{coords['l']},"
                    f"{coords['gov']},{coords['bank']},{coords['post']},{coords['lib']}\n")

    # Save region summary (flat CSV for app)
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
        subprocess.run(["git", "commit", "-m", f"POI {region_name} — {total_cities} città, {len(all_pois)} POI"], cwd=repo_dir, check=True)
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=repo_dir, check=True)
        result = subprocess.run(["git", "push", "origin", "test"], cwd=repo_dir, capture_output=True, text=True)
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
