#!/usr/bin/env python3
"""Analisi preliminare dedup: verifica che le cartelle città duplicate
contengano lo stesso set di POI (stesso id), prima di procedere alla pulizia."""
import os, sys, math, glob

REPO = os.path.dirname(os.path.abspath(__file__))
ITALIA = os.path.join(REPO, "italia")

REGION_BBOX = {
    "abruzzo": [39.5, 13.0, 42.5, 14.8],
    "basilicata": [39.5, 15.5, 41.5, 17.0],
    "calabria": [37.5, 15.5, 40.0, 17.5],
    "campania": [39.5, 13.5, 41.5, 16.5],
    "emilia-romagna": [43.5, 10.5, 45.5, 13.0],
    "friuli_vg": [45.5, 12.0, 47.0, 14.0],
    "lazio": [40.5, 11.5, 43.0, 14.0],
    "liguria": [43.5, 7.5, 44.8, 10.0],
    "lombardia": [44.5, 8.5, 46.5, 11.5],
    "marche": [42.5, 12.0, 44.0, 14.5],
    "molise": [41.0, 13.5, 42.0, 15.0],
    "piemonte": [44.0, 6.5, 46.5, 9.5],
    "puglia": [39.5, 15.0, 42.5, 18.5],
    "sardegna": [38.5, 8.0, 41.5, 10.0],
    "sicilia": [36.5, 12.0, 38.5, 15.5],
    "toscana": [42.0, 9.5, 44.0, 12.5],
    "trentino-aa": [45.5, 10.5, 47.0, 12.5],
    "umbria": [42.0, 12.0, 43.5, 13.5],
    "valle_daosta": [45.5, 6.5, 46.5, 8.0],
    "veneto": [44.5, 10.5, 47.0, 13.5],
}

def dist_to_center(lat, lng, bbox):
    cLat = (bbox[0] + bbox[2]) / 2
    cLng = (bbox[1] + bbox[3]) / 2
    dLat = cLat - lat
    dLng = (cLng - lng) * math.cos(math.radians(lat))
    return dLat * dLat + dLng * dLng

def parse_index(path):
    entries = {}
    if not os.path.exists(path):
        return entries
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.split(",")
        if len(p) < 4:
            continue
        lat = p[0]; lng = p[1]
        try:
            lat = float(lat); lng = float(lng)
        except ValueError:
            continue
        entries[p[3].strip()] = {"lat": lat, "lng": lng, "name": p[2].strip()}
    return entries

def folder_poi_ids(region, slug):
    f = os.path.join(ITALIA, region, slug, "_all.csv")
    ids = set()
    if os.path.exists(f):
        for line in open(f, encoding="utf-8"):
            if line.startswith("#") or not line.strip():
                continue
            p = line.split(",")
            if len(p) >= 6:
                ids.add(p[2].strip())
    return ids

def main():
    indexes = {}
    for region in REGION_BBOX:
        indexes[region] = parse_index(os.path.join(ITALIA, region, "_citta.csv"))

    # slug -> lista (region, entry)
    slug_regions = {}
    for region, entries in indexes.items():
        for slug, e in entries.items():
            slug_regions.setdefault(slug, []).append((region, e))

    # canonical: copia con minima distanza dal centro del proprio bbox
    canonical = {}
    for slug, copies in slug_regions.items():
        best = min(copies, key=lambda rc: dist_to_center(rc[1]["lat"], rc[1]["lng"], REGION_BBOX[rc[0]]))
        canonical[slug] = best[0]

    mismatches = 0
    checked = 0
    removed_rows = 0
    for slug, copies in slug_regions.items():
        if len(copies) < 2:
            continue
        checked += 1
        rem = canonical[slug]
        idsets = {r: folder_poi_ids(r, slug) for r, _ in copies}
        base = idsets[rem]
        for r, _ in copies:
            if r == rem:
                continue
            extra = idsets[r] - base
            missing = base - idsets[r]
            if extra or missing:
                mismatches += 1
                print(f"[DIFF] {slug}: canon={rem} vs {r} extra={len(extra)} missing={len(missing)}")
        removed_rows += len(copies) - 1

    print()
    print(f"Slug con >1 copia: {checked}")
    print(f"Copie da rimuovere: {removed_rows}")
    print(f"Casi con POI diversi tra copie: {mismatches}")

if __name__ == "__main__":
    main()
