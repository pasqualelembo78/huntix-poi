#!/usr/bin/env python3
"""
extract_all_pois.py — Estrae POI italiani da OSM (Overpass) + Overture Maps (S3),
li combina deduplicando e li salva in italia/{regione}/{citta}/{categoria}.csv

Strategia:
  - Se un POI esiste in entrambe le fonti, Overture vince (dati piu strutturati)
  - OSM riempie i buchi (copertura piu ampia)
  - Processa una categoria alla volta per tenere la RAM leggera
  - Scrive su file CSV per città, poi genera riepiloghi

Uso: python3 extract_all_pois.py
"""
import json, urllib.request, urllib.parse, re, time, os, subprocess, sys, math

# ────────────────────── DIPENDENZE ──────────────────────
def ensure_deps():
    try:
        import duckdb
    except ImportError:
        print("📦 Installazione duckdb...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "duckdb"])
        print("  ✅ duckdb installato")

ensure_deps()
import duckdb

# ────────────────────── CONFIG ──────────────────────
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
S3_PATH = "s3://overturemaps-us-west-2/release/2026-07-22.0/theme=places/type=place/*"
S3_DIVISIONS = "s3://overturemaps-us-west-2/release/2026-07-22.0/theme=divisions/type=division_area/*"

REGIONS = {
    "1": ("Abruzzo",        "39.5,13.0,42.5,14.8"),
    "2": ("Basilicata",     "39.5,15.5,41.5,17.0"),
    "3": ("Calabria",       "37.5,15.5,40.0,17.5"),
    "4": ("Campania",       "39.5,13.5,41.5,16.5"),
    "5": ("Emilia-Romagna", "43.5,10.5,45.5,13.0"),
    "6": ("Friuli V.G.",    "45.5,12.0,47.0,14.0"),
    "7": ("Lazio",          "40.5,11.5,43.0,14.0"),
    "8": ("Liguria",        "43.5,7.5,44.8,10.0"),
    "9": ("Lombardia",      "44.5,8.5,46.5,11.5"),
    "10":("Marche",         "42.5,12.0,44.0,14.5"),
    "11":("Molise",         "41.0,13.5,42.0,15.0"),
    "12":("Piemonte",       "44.0,6.5,46.5,9.5"),
    "13":("Puglia",         "39.5,15.0,42.5,18.5"),
    "14":("Sardegna",       "38.5,8.0,41.5,10.0"),
    "15":("Sicilia",        "36.5,12.0,38.5,15.5"),
    "16":("Toscana",        "42.0,9.5,44.0,12.5"),
    "17":("Trentino-A.A.",  "45.5,10.5,47.0,12.5"),
    "18":("Umbria",         "42.0,12.0,43.5,13.5"),
    "19":("Valle d'Aosta",  "45.5,6.5,46.5,8.0"),
    "20":("Veneto",         "44.5,10.5,47.0,13.5"),
}

CATEGORIES = [
    ("hospitals",  "hospital"),
    ("restaurants","ristorante"),
    ("bars_cafes", "bar_cafe"),
    ("gyms",       "palestra"),
    ("landmarks",  "monumento"),
    ("government", "ufficio_pubblico"),
    ("banks",      "banca"),
    ("post_offices","ufficio_postale"),
    ("libraries",  "biblioteca"),
]

OSM_QUERIES = {
    "hospitals":  '"amenity"="hospital"',
    "restaurants":'"amenity"~"restaurant|fast_food|pizzeria"',
    "bars_cafes": '"amenity"~"bar|cafe|pub"',
    "gyms":       '"leisure"="fitness_centre"',
    "government": '"amenity"~"townhall|courthouse|registration_hall|job_centre"',
    "banks":      '"amenity"="bank"',
    "post_offices":'"amenity"="post_office"',
    "libraries":  '"amenity"="library"',
}

OSM_LANDMARK_TAGS = [
    '"tourism"="attraction"',     '"tourism"="museum"',
    '"tourism"="castle"',         '"tourism"="gallery"',
    '"historic"="monument"',      '"historic"="castle"',
    '"historic"="archaeological_site"', '"historic"="memorial"',
    '"historic"="ruins"',         '"amenity"="place_of_worship"',
]

OV_BUILDING_TYPE = {
    "hospitals":"HOSPITAL", "restaurants":"RESTAURANT",
    "bars_cafes":"RESTAURANT", "gyms":"GYM", "landmarks":"MONUMENT",
    "government":"GOVERNMENT", "banks":"BANK",
    "post_offices":"POST_OFFICE", "libraries":"LIBRARY",
}

OV_CATEGORY_MAP = {
    "hospitals":  ["hospital"],
    "restaurants":["restaurant","fast_food_restaurant","food_service"],
    "bars_cafes": ["bar","cafe","pub","brewery"],
    "gyms":       ["gym","fitness_studio","sport_or_fitness_facility"],
    "landmarks":  ["museum","monument","castle","place_of_worship"],
    "government": ["government","courthouse","town_hall","public_administration"],
    "banks":      ["bank","financial_institution"],
    "post_offices":["post_office"],
    "libraries":  ["library"],
}

def norm_name(name):
    name = name.lower().strip().replace("'","").replace("'","")
    return re.sub(r"\s+", "_", re.sub(r"[^a-z0-9\s-]","", name))[:40]

def dedup_key(name, lat, lng):
    return f"{norm_name(name)}_{lat:.3f}_{lng:.3f}"

def haversine_km(lat1, lng1, lat2, lng2):
    R, dlat, dlng = 6371.0, math.radians(lat2-lat1), math.radians(lng2-lng1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlng/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))

TEMPLATE_MAP = {
    "restaurants": "restaurant.json",
    "bars_cafes": "bar.json",
    "gyms": "gym.json",
    "hospitals": "hospital.json",
    "government": "government.json",
    "banks": "bank.json",
    "post_offices": "post_office.json",
    "libraries": "library.json",
}

def generate_poi_page(name, cat_key, building_type, website, region_slug, city_slug, lat, lng, repo_dir):
    if building_type == "MUSEUM":
        tmpl = "museum.json"
    elif cat_key in TEMPLATE_MAP:
        tmpl = TEMPLATE_MAP[cat_key]
    else:
        tmpl = "landmark.json"
    tpath = os.path.join(repo_dir, "templates", tmpl)
    with open(tpath, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["banner"]["title"] = name
    website = (website or "").strip()
    data["sections"] = [s for s in data["sections"] if s.get("type") != "link" or website]
    for s in data["sections"]:
        if s.get("type") == "link" and s.get("url") == "{website}":
            s["url"] = website
    slug = f"{norm_name(name)}_{lat:.4f}_{lng:.4f}"
    pages_dir = os.path.join(repo_dir, "italia", region_slug, city_slug, "pages")
    os.makedirs(pages_dir, exist_ok=True)
    with open(os.path.join(pages_dir, f"{slug}.json"), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return f"https://raw.githubusercontent.com/pasqualelembo78/huntix-poi/test/italia/{region_slug}/{city_slug}/pages/{slug}.json"

# ────────────────────── OSM ──────────────────────
def query_osm(query_str, retries=3):
    for attempt in range(retries):
        try:
            data = urllib.parse.urlencode({"data": query_str}).encode("utf-8")
            req = urllib.request.Request(OVERPASS_URL, data=data, method="POST")
            req.add_header("User-Agent", "Huntix-POI-Extractor/1.0")
            with urllib.request.urlopen(req, timeout=180) as resp:
                return json.loads(resp.read().decode("utf-8")).get("elements", [])
        except Exception as e:
            print(f"    ⚠️  OSM tentativo {attempt+1} fallito: {e}")
            if attempt < retries-1:
                time.sleep(15*(attempt+1))
    return []

def parse_osm_poi(el, csv_type, cities_cache):
    tags = el.get("tags", {})
    name = tags.get("name") or tags.get("name:it") or tags.get("name:en")
    if not name or len(name) < 3:
        return None
    if el["type"] == "node":
        lat, lng = el.get("lat"), el.get("lon")
    else:
        c = el.get("center", {})
        lat, lng = c.get("lat"), c.get("lon")
    if not lat or not lng:
        return None
    name = name.replace('"', "").strip()[:60]
    city = tags.get("addr:city") or tags.get("addr:town") or tags.get("addr:village")
    if not city and cities_cache:
        best, best_dist = None, float("inf")
        for cc in cities_cache:
            d = haversine_km(lat, lng, cc["lat"], cc["lng"])
            if d < best_dist:
                best_dist, best = d, cc["name"]
        if best_dist <= 30:
            city = best
    pid = re.sub(r"[^a-zA-Z0-9]", "_", name.lower())[:40]
    return {
        "name": name, "lat": lat, "lng": lng,
        "id": f"osm_{pid}_{lat:.4f}_{lng:.4f}",
        "city": city or "sconosciuta",
        "csv_type": csv_type,
        "building_type": csv_type,
        "url": tags.get("website", ""),
    }

def load_osm_cities(bbox):
    q = f'[out:json][timeout:120];(node["place"~"city|town|village"]({bbox}););out tags;'
    cities = []
    for el in query_osm(q):
        tags = el.get("tags", {})
        name = tags.get("name") or tags.get("name:it")
        lat, lng = el.get("lat"), el.get("lon")
        if name and lat and lng:
            cities.append({"name": name.strip(), "lat": lat, "lng": lng})
    return cities

# ────────────────────── OVERTURE ──────────────────────
def query_overture(con, bbox, categories):
    s,w,n,e = [float(x) for x in bbox.split(",")]
    cat_filters = " OR ".join([f"basic_category = '{c}'" for c in categories])
    sql = f"""
    SELECT ST_Y(geometry) as lat, ST_X(geometry) as lng, id,
           COALESCE(names.primary,'unknown') as name,
           basic_category,
           COALESCE(addresses[1].locality,'') as city,
           COALESCE(addresses[1].region,'') as region,
           COALESCE(addresses[1].country,'') as country, confidence,
           COALESCE(websites[1],'') as website
    FROM read_parquet('{S3_PATH}', filename=true, hive_partitioning=1)
    WHERE bbox.xmin BETWEEN {w} AND {e}
      AND bbox.ymin BETWEEN {s} AND {n}
      AND ({cat_filters})
      AND confidence > 0.5
    """
    return con.execute(sql).fetchall()

def query_overture_cities(con, bbox):
    s,w,n,e = [float(x) for x in bbox.split(",")]
    sql = f"""
    SELECT ST_Y(ST_Centroid(geometry)) as lat,
           ST_X(ST_Centroid(geometry)) as lng,
           names.primary as name
    FROM read_parquet('{S3_DIVISIONS}', filename=true, hive_partitioning=1)
    WHERE subtype = 'locality'
      AND bbox.xmin BETWEEN {w} AND {e}
      AND bbox.ymin BETWEEN {s} AND {n}
    """
    return con.execute(sql).fetchall()

# ────────────────────── FILE IO ──────────────────────
def merge_csv(filename, title, new_lines):
    old_by_key = {}
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#"):
                    continue
                p = s.split(",")
                if len(p) >= 4:
                    old_by_key[f"{p[3]}_{p[0]}_{p[1]}"] = s
    added = 0
    seen = set()
    out = []
    for l in new_lines:
        p = l.split(",")
        if len(p) >= 4:
            key = f"{p[3]}_{p[0]}_{p[1]}"
            if key in seen:
                continue
            seen.add(key)
            old = old_by_key.get(key)
            if old is not None and old == l:
                out.append(old)
                continue
            if old is None:
                added += 1
            out.append(l)
        else:
            out.append(l)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# lat,lng,id,name,building_type,type,url,page_type\n# {title}\n")
        for l in out:
            f.write(l + "\n")
    return added, len(out)

def osm_category_query(cat_key, bbox):
    if cat_key == "landmarks":
        parts = ";".join([
            f'node[{t}]({bbox});way[{t}]({bbox})' for t in OSM_LANDMARK_TAGS
        ])
        return f'[out:json][timeout:120];({parts});out center tags;'
    if cat_key == "government":
        gov_tags = [
            '"amenity"="townhall"', '"amenity"="courthouse"',
            '"amenity"="registration_hall"', '"amenity"="job_centre"',
            '"office"="government"',
        ]
        parts = ";".join([
            f'node[{t}]({bbox});way[{t}]({bbox})' for t in gov_tags
        ])
        return f'[out:json][timeout:120];({parts});out center tags;'
    tq = OSM_QUERIES[cat_key]
    return f'[out:json][timeout:120];(node[{tq}]({bbox});way[{tq}]({bbox}););out center tags;'

# ────────────────────── MAIN ──────────────────────
def main():
    print("=" * 55)
    print("  Huntix POI Extractor — OSM + Overture Maps (unificato)")
    print("=" * 55)
    print()

    repo_dir = os.path.dirname(os.path.abspath(__file__))
    print(f"Repo: {repo_dir}\n")

    print("Scegli la regione:\n")
    for k, (n, _) in sorted(REGIONS.items(), key=lambda x: int(x[0])):
        print(f"  [{k:>2}] {n}")
    print()
    choice = input(">>> Numero (1-20): ").strip()
    if choice not in REGIONS:
        print("Scelta non valida.")
        return

    region_name, bbox = REGIONS[choice]
    region_slug = norm_name(region_name)
    print(f"\n  {region_name} — {bbox}\n")

    region_dir = os.path.join(repo_dir, "italia", region_slug)
    os.makedirs(region_dir, exist_ok=True)

    # Carica città di riferimento (da OSM — piu ricco di nomi locali)
    print("Carico citta da OSM...")
    cities_cache = load_osm_cities(bbox)
    print(f"  {len(cities_cache)} luoghi\n")

    # Connessione DuckDB + Overture
    print("Connessione a Overture Maps (S3)...")
    con = duckdb.connect()
    con.execute("INSTALL spatial; LOAD spatial;")
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("SET s3_region='us-west-2';")
    print("  Connesso\n")

    # Carica citta Overture per reverse geocoding
    print("Carico citta da Overture...")
    ov_cities = query_overture_cities(con, bbox)
    print(f"  {len(ov_cities)} luoghi\n")

    # Processa una categoria alla volta (RAM leggera)
    city_counts = {}

    for cat_key, csv_type in CATEGORIES:
        print("-" * 50)
        print(f"  {cat_key}...")

        # 1. Overture
        ov_pois = []
        cat_keys = set()  # dedup intra-categoria
        ov_rows = query_overture(con, bbox, OV_CATEGORY_MAP[cat_key])
        print(f"  Overture: {len(ov_rows)} POI")

        for row in ov_rows:
            lat, lng, oid, name, basic_cat, city_addr, reg_addr, cntry_addr, conf, website = row
            if not lat or not lng or not name or name == "unknown" or len(name) < 3:
                continue

            city = city_addr if city_addr else None
            if not city:
                best, bd = None, float("inf")
                for clat, clng, cname in ov_cities:
                    d = haversine_km(lat, lng, clat, clng)
                    if d < bd:
                        bd, best = d, cname
                if bd <= 30:
                    city = best
            if not city:
                best, bd = None, float("inf")
                for cc in cities_cache:
                    d = haversine_km(lat, lng, cc["lat"], cc["lng"])
                    if d < bd:
                        bd, best = d, cc["name"]
                if bd <= 30:
                    city = best
            if not city:
                city = "sconosciuta"

            btype = OV_BUILDING_TYPE.get(cat_key, "")
            if cat_key == "landmarks" and basic_cat == "museum":
                btype = "MUSEUM"

            safe_name = name.replace('"', "").strip()[:60]
            name_csv = f'"{safe_name}"' if "," in safe_name else safe_name
            pid = re.sub(r"[^a-zA-Z0-9]", "_", safe_name.lower())[:40]
            website_url = website.strip() if website else ""
            city_slug = norm_name(city or "sconosciuta")
            json_url = generate_poi_page(safe_name, cat_key, btype, website_url, region_slug, city_slug, lat, lng, repo_dir)
            line = f"{lat:.6f},{lng:.6f},ov_{pid}_{lat:.4f}_{lng:.4f},{name_csv},{btype},{csv_type},{json_url},custom"

            k = dedup_key(safe_name, lat, lng)
            cat_keys.add(k)
            ov_pois.append((city, k, line))

        # 2. OSM (complementare — solo intra-categoria)
        elements = query_osm(osm_category_query(cat_key, bbox))
        print(f"  OSM:     {len(elements)} elementi grezzi")

        osm_pois = []
        osm_seen = set()  # evita duplicati anche dentro OSM stessa categoria
        for el in elements:
            poi = parse_osm_poi(el, csv_type, cities_cache)
            if not poi:
                continue
            k = dedup_key(poi["name"], poi["lat"], poi["lng"])
            if k in cat_keys or k in osm_seen:
                continue  # Overture vince; OSM stesso no
            osm_seen.add(k)
            osm_city_slug = norm_name(poi["city"])
            json_url = generate_poi_page(poi["name"], cat_key, poi["building_type"], poi["url"], region_slug, osm_city_slug, poi["lat"], poi["lng"], repo_dir)
            line = f"{poi['lat']:.6f},{poi['lng']:.6f},{poi['id']},{poi['name']},{poi['building_type']},{poi['csv_type']},{json_url},custom"
            osm_pois.append((poi["city"], k, line))

        print(f"  -> Overture: {len(ov_pois)} | OSM (no dup): {len(osm_pois)} | tot: {len(ov_pois)+len(osm_pois)}")

        # 3. Scrivi per citta
        city_lines = {}
        for city, k, line in ov_pois + osm_pois:
            slug = norm_name(city)
            city_lines.setdefault(slug, []).append(line)

        for slug, lines in city_lines.items():
            city_dir = os.path.join(region_dir, slug)
            os.makedirs(city_dir, exist_ok=True)
            fp = os.path.join(city_dir, f"{cat_key}.csv")
            added, total = merge_csv(fp, f"{slug} -- {cat_key}", lines)

            # Aggiorna contatori citta
            if slug not in city_counts:
                city_counts[slug] = {"name": slug, "h":0, "r":0, "b":0, "g":0, "l":0, "gov":0, "bank":0, "post":0, "lib":0}

            # Recupera nome citta originale
            for city, k, line in ov_pois + osm_pois:
                if norm_name(city) == slug:
                    city_counts[slug]["name"] = city
                    break

            if cat_key == "hospitals":   city_counts[slug]["h"] += added
            elif cat_key == "restaurants": city_counts[slug]["r"] += added
            elif cat_key == "bars_cafes": city_counts[slug]["b"] += added
            elif cat_key == "gyms":       city_counts[slug]["g"] += added
            elif cat_key == "landmarks":  city_counts[slug]["l"] += added
            elif cat_key == "government": city_counts[slug]["gov"] += added
            elif cat_key == "banks":      city_counts[slug]["bank"] += added
            elif cat_key == "post_offices": city_counts[slug]["post"] += added
            elif cat_key == "libraries":  city_counts[slug]["lib"] += added

        print()

    con.close()

    # 4. _all.csv per ogni citta (unendo i file categoria)
    print("Creazione _all.csv per citta...")
    for slug, info in city_counts.items():
        city_dir = os.path.join(region_dir, slug)
        all_lines = []
        for cat_key, _ in CATEGORIES:
            fp = os.path.join(city_dir, f"{cat_key}.csv")
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip().startswith("#") and line.strip():
                            all_lines.append(line.strip())
        if all_lines:
            merge_csv(os.path.join(city_dir, "_all.csv"), f"{info['name']} -- Tutti", all_lines)

    # 5. _citta.csv per regione
    print("Creazione _citta.csv...")
    city_coords = {}
    for slug, info in city_counts.items():
        city_dir = os.path.join(region_dir, slug)
        lat_sum, lng_sum, count = 0.0, 0.0, 0
        for cat_key, _ in CATEGORIES:
            fp = os.path.join(city_dir, f"{cat_key}.csv")
            if os.path.exists(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    for line in f:
                        if not line.strip().startswith("#") and line.strip():
                            parts = line.split(",")
                            if len(parts) >= 2:
                                try:
                                    lat_sum += float(parts[0])
                                    lng_sum += float(parts[1])
                                    count += 1
                                except:
                                    pass
        if count > 0:
            city_coords[slug] = {
                "lat": lat_sum / count, "lng": lng_sum / count,
                "name": info["name"],
                "h": info["h"], "r": info["r"], "b": info["b"],
                "g": info["g"], "l": info["l"],
                "gov": info["gov"], "bank": info["bank"],
                "post": info["post"], "lib": info["lib"],
            }

    with open(os.path.join(region_dir, "_citta.csv"), "w", encoding="utf-8") as f:
        f.write("# lat,lng,citta,slug,ospedali,ristoranti,bar_cafe,palestre,monumenti,governo,banche,poste,biblioteche\n")
        for slug, c in sorted(city_coords.items()):
            f.write(f"{c['lat']:.6f},{c['lng']:.6f},{c['name']},{slug},"
                    f"{c['h']},{c['r']},{c['b']},{c['g']},{c['l']},"
                    f"{c['gov']},{c['bank']},{c['post']},{c['lib']}\n")

    # 6. _all.csv regionale (leggendo i _all.csv delle citta)
    print("Creazione _all.csv regionale...")
    all_region = []
    for slug in city_counts:
        fp = os.path.join(region_dir, slug, "_all.csv")
        if os.path.exists(fp):
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip().startswith("#") and line.strip():
                        all_region.append(line.strip())

    merge_csv(os.path.join(region_dir, "_all.csv"),
              f"{region_name} -- Tutti (OSM+Overture)", all_region)

    # 7. Indice regioni
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

    # 8. global_pois.csv
    print("Aggiornamento global_pois.csv...")
    global_file = os.path.join(repo_dir, "global_pois.csv")
    added, total = merge_csv(global_file,
        "Huntix Global POI -- Tutte le regioni (OSM+Overture)", all_region)

    print(f"\n{'=' * 55}")
    print(f"  Completato!")
    print(f"   {len(city_counts)} citta")
    print(f"   Global: +{added} nuovi / {total} totali")
    print(f"{'=' * 55}\n")

    # GIT PUSH
    resp = input(">>> Push su GitHub? (s/N): ").strip().lower()
    if resp != "s":
        print("Push saltato.")
        return

    token = input(">>> Token GitHub (ghp_...): ").strip()
    if not token:
        print("Token vuoto.")
        return

    remote_url = f"https://pasqualelembo78:{token}@github.com/pasqualelembo78/huntix-poi.git"
    try:
        subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
        subprocess.run(["git", "commit", "-m",
            f"POI {region_name} -- {len(all_region)} POI (OSM+Overture unificato)"],
            cwd=repo_dir, check=True)
        subprocess.run(["git", "remote", "set-url", "origin", remote_url], cwd=repo_dir, check=True)
        result = subprocess.run(["git", "push", "origin", "test"],
            cwd=repo_dir, capture_output=True, text=True)
        if result.returncode == 0:
            print("\nPush completato!")
        else:
            print(f"\nPush fallito:\n{result.stderr}")
    except subprocess.CalledProcessError as e:
        print(f"\nErrore git: {e}")
    finally:
        subprocess.run(["git", "remote", "set-url", "origin",
            "https://github.com/pasqualelembo78/huntix-poi.git"], cwd=repo_dir)


if __name__ == "__main__":
    main()
