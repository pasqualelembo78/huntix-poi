#!/usr/bin/env python3
"""
extract_osm_pois.py — Estrae POI italiani da OpenStreetMap (Overpass API)
e li converte nel formato CSV di Huntix: lat,lng,id,name,building_type,type

Uso: python3 extract_osm_pois.py
"""
import json
import urllib.request
import urllib.parse
import re
import time
import os

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
    "0":  ("TUTTA ITALIA",     "36.0,6.0,47.5,19.0"),
}

CATEGORIES = [
    ("hospitals",  '"amenity"="hospital"',                       "hospital",  "hospitals.csv"),
    ("restaurants",'"amenity"~"restaurant|fast_food|pizzeria"',  "ristorante","restaurants.csv"),
    ("gyms",       '"leisure"="fitness_centre"',                 "palestra",  "gyms.csv"),
]

LANDMARK_TAGS = [
    '"tourism"="attraction"',
    '"tourism"="museum"',
    '"tourism"="monument"',
    '"tourism"="castle"',
    '"tourism"="archaeological_site"',
    '"historic"="monument"',
    '"historic"="castle"',
    '"historic"="archaeological_site"',
    '"historic"="memorial"',
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


def to_csv(elements, csv_type):
    lines = []
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
        name = name.replace('"', "").strip()[:60]
        key = f"{name}_{lat:.3f}_{lng:.3f}"
        if key in seen:
            continue
        seen.add(key)
        pid = re.sub(r"[^a-zA-Z0-9]", "_", name.lower())[:40]
        safe_name = f'"{name}"' if "," in name else name
        lines.append(f"{lat:.6f},{lng:.6f},osm_{pid}_{lat:.4f}_{lng:.4f},{safe_name},{csv_type},{csv_type}")
    return lines


def save_csv(filename, title, lines):
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# lat,lng,id,name,building_type,type\n# {title} - OpenStreetMap\n")
        for l in lines:
            f.write(l + "\n")


def main():
    print("=" * 55)
    print("  🗺️  Huntix POI Extractor — OpenStreetMap")
    print("=" * 55)
    print()
    print("Scegli la regione da scaricare:\n")
    for k, (name, _) in sorted(REGIONS.items(), key=lambda x: int(x[0])):
        label = f"  [{k:>2}] {name}"
        if k == "0":
            label = f"  [{k:>2}] {name} ⚠️  (lento!)"
        print(label)

    print()
    choice = input(">>> Inserisci il numero (0-20): ").strip()
    if choice not in REGIONS:
        print("❌ Scelta non valida.")
        return

    region_name, bbox = REGIONS[choice]
    clean_name = region_name.lower().replace(" ", "_").replace("'", "")
    out_dir = f"/tmp/huntix-poi/{clean_name}"
    os.makedirs(out_dir, exist_ok=True)

    print(f"\n📍 Regione: {region_name}")
    print(f"📦 Bounding box: {bbox}")
    print(f"📁 Output: {out_dir}\n")

    all_pois = []

    for cat_key, tag_query, csv_type, filename in CATEGORIES:
        print(f"🔍 {cat_key}...")
        q = f'[out:json][timeout:120];(node[{tag_query}]({bbox});way[{tag_query}]({bbox}););out center;'
        elements = query_overpass(q)
        csv_lines = to_csv(elements, csv_type)
        filepath = os.path.join(out_dir, filename)
        save_csv(filepath, f"Huntix {cat_key.title()} - {region_name}", csv_lines)
        all_pois.extend(csv_lines)
        print(f"  ✅ {len(csv_lines)} POI salvati in {filename}\n")
        time.sleep(5)

    # Landmarks: query each tag separately to avoid OR syntax issues
    print(f"🔍 landmarks...")
    all_landmarks = []
    for tag in LANDMARK_TAGS:
        q = f'[out:json][timeout:90];(node[{tag}]({bbox});way[{tag}]({bbox}););out center;'
        els = query_overpass(q)
        csv_lines = to_csv(els, "monumento")
        all_landmarks.extend(csv_lines)
        time.sleep(3)
    # Deduplicate landmarks
    seen_lm = set()
    unique_landmarks = []
    for l in all_landmarks:
        parts = l.split(",")
        key = f"{parts[3]}_{parts[0]}_{parts[1]}"
        if key not in seen_lm:
            seen_lm.add(key)
            unique_landmarks.append(l)
    lm_file = os.path.join(out_dir, "landmarks.csv")
    save_csv(lm_file, f"Huntix Landmarks - {region_name}", unique_landmarks)
    all_pois.extend(unique_landmarks)
    print(f"  ✅ {len(unique_landmarks)} POI salvati in landmarks.csv\n")

    global_file = os.path.join(out_dir, "global_pois.csv")
    save_csv(global_file, f"Huntix Global POI - {region_name}", all_pois)
    print(f"✅ {len(all_pois)} POI totali salvati in {out_dir}/")
    print(f"   Copia i file in /tmp/huntix-poi/ per fare il push.\n")


if __name__ == "__main__":
    main()
