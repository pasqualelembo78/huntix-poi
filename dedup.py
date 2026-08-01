#!/usr/bin/env python3
"""
dedup.py — Deduplica le città presenti in più regioni di huntix-poi.

Problema: i bbox regionali si sovrappongono, quindi l'estrattore ha salvato le
stesse città (e le stesse cartelle/pagine POI) in più regioni (7.617 slug duplicati).

Regole:
  1. Copie dello stesso slug vengono raggruppate per prossimità geografica
     (<= 25 km): copie lontane sono città diverse con lo stesso slug (es.
     "lecce" in Sardegna vs Lecce in Puglia) e NON vengono unite.
  2. Per ogni cluster, la regione canonica è quella con il centro bbox più vicino.
  3. I POI di tutte le copie vengono uniti (union, dedup per lat/lng/nome) nella
     cartella canonica; le pagine JSON vengono copiate; gli url riscritti.
  4. Le cartelle non canoniche vengono eliminate.
  5. _citta.csv e _all.csv di ogni regione vengono rigenerati.

Uso: python3 dedup.py [--dry-run]
"""
import os, sys, math, shutil, glob

REPO = os.path.dirname(os.path.abspath(__file__))
ITALIA = os.path.join(REPO, "italia")

DRY = "--dry-run" in sys.argv

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

REGION_NAMES = {
    "abruzzo": "Abruzzo", "basilicata": "Basilicata", "calabria": "Calabria",
    "campania": "Campania", "emilia-romagna": "Emilia-Romagna",
    "friuli_vg": "Friuli V.G.", "lazio": "Lazio", "liguria": "Liguria",
    "lombardia": "Lombardia", "marche": "Marche", "molise": "Molise",
    "piemonte": "Piemonte", "puglia": "Puglia", "sardegna": "Sardegna",
    "sicilia": "Sicilia", "toscana": "Toscana", "trentino-aa": "Trentino-A.A.",
    "umbria": "Umbria", "valle_daosta": "Valle d'Aosta", "veneto": "Veneto",
}

CATEGORY_FILES = ["restaurants.csv", "bars_cafes.csv", "gyms.csv", "hospitals.csv",
                  "landmarks.csv", "government.csv", "banks.csv", "post_offices.csv",
                  "libraries.csv"]

# colonna conteggio nel _citta.csv per file categoria
CATEGORY_COUNT = {"hospitals.csv": "h", "restaurants.csv": "r", "bars_cafes.csv": "b",
                  "gyms.csv": "g", "landmarks.csv": "l"}

CLUSTER_KM = 25.0


def haversine_km(lat1, lng1, lat2, lng2):
    R, dlat, dlng = 6371.0, math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def dist_to_center(lat, lng, bbox):
    cLat = (bbox[0] + bbox[2]) / 2
    cLng = (bbox[1] + bbox[3]) / 2
    dLat = cLat - lat
    dLng = (cLng - lng) * math.cos(math.radians(lat))
    return dLat * dLat + dLng * dLng


def parse_index(region):
    entries = {}
    path = os.path.join(ITALIA, region, "_citta.csv")
    if not os.path.exists(path):
        return entries
    for line in open(path, encoding="utf-8"):
        if line.startswith("#") or not line.strip():
            continue
        p = line.split(",")
        if len(p) < 4:
            continue
        slug = p[3].strip()
        if not slug:
            continue
        try:
            lat, lng = float(p[0]), float(p[1])
        except ValueError:
            continue
        entries[slug] = {"lat": lat, "lng": lng, "name": p[2].strip(), "row": line.rstrip("\n")}
    return entries


def read_data_lines(path):
    lines = []
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            s = line.strip()
            if s and not s.startswith("#"):
                lines.append(s)
    return lines


def poi_key(line):
    p = line.split(",")
    if len(p) < 3:
        return None
    return p[2].strip()


def rewrite_url(line, member_region, canonical_region, slug):
    return line.replace(f"/italia/{member_region}/{slug}/pages/",
                        f"/italia/{canonical_region}/{slug}/pages/")


def merge_lines(target_lines, new_lines):
    by_key = {}
    for l in target_lines:
        k = poi_key(l)
        by_key[k] = l
    added = 0
    for l in new_lines:
        k = poi_key(l)
        if k is None:
            continue
        if k in by_key:
            continue
        by_key[k] = l
        added += 1
    return list(by_key.values()), added


def copy_pages(src_folder, dst_folder):
    src_pages = os.path.join(src_folder, "pages")
    dst_pages = os.path.join(dst_folder, "pages")
    if not os.path.isdir(src_pages):
        return 0
    os.makedirs(dst_pages, exist_ok=True)
    copied = 0
    for f in os.listdir(src_pages):
        src = os.path.join(src_pages, f)
        dst = os.path.join(dst_pages, f)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copyfile(src, dst)
            copied += 1
    return copied


def load_indexes():
    return {r: parse_index(r) for r in REGION_BBOX}


def main():
    print("Carico indici...")
    indexes = load_indexes()

    # slug -> copie (region, entry)
    slug_copies = {}
    for region, entries in indexes.items():
        for slug, e in entries.items():
            slug_copies.setdefault(slug, []).append((region, e))

    total_rows_before = sum(len(e) for e in indexes.values())

    # assegnazione finale: (slug, cluster_id) -> canonical region
    assigned = {}   # (slug, cluster_idx) -> region
    cluster_info = {}  # (slug, cluster_idx) -> (members, canonical)

    print(f"Slug con copie: {sum(1 for v in slug_copies.values() if len(v) > 1)} / {len(slug_copies)}")

    for slug, copies in slug_copies.items():
        if len(copies) == 1:
            assigned[(slug, 0)] = copies[0][0]
            continue
        # clustering per prossimità
        clusters = []
        for region, e in copies:
            placed = False
            for cl in clusters:
                lat0 = sum(m[1]["lat"] for m in cl) / len(cl)
                lng0 = sum(m[1]["lng"] for m in cl) / len(cl)
                if haversine_km(lat0, lng0, e["lat"], e["lng"]) <= CLUSTER_KM:
                    cl.append((region, e))
                    placed = True
                    break
            if not placed:
                clusters.append([(region, e)])
        for idx, cl in enumerate(clusters):
            canon = min(cl, key=lambda m: dist_to_center(m[1]["lat"], m[1]["lng"], REGION_BBOX[m[0]]))[0]
            assigned[(slug, idx)] = canon
            cluster_info[(slug, idx)] = (cl, canon)

    # merge
    merged_count = 0
    removed_folders = 0
    added_pois = 0
    for (slug, idx), (cl, canon) in cluster_info.items():
        if len(cl) < 2 or not slug:
            continue
        canon_dir = os.path.join(ITALIA, canon, slug)
        os.makedirs(canon_dir, exist_ok=True)
        # category files
        for cat in CATEGORY_FILES:
            base = read_data_lines(os.path.join(canon_dir, cat))
            for member, _e in cl:
                if member == canon:
                    continue
                mpath = os.path.join(ITALIA, member, slug, cat)
                if not os.path.exists(mpath):
                    continue
                mlines = [rewrite_url(l, member, canon, slug) for l in read_data_lines(mpath)]
                base, add = merge_lines(base, mlines)
                added_pois += add
            if base and not DRY:
                with open(os.path.join(canon_dir, cat), "w", encoding="utf-8") as f:
                    f.write(f"# lat,lng,id,name,building_type,type,url,page_type\n# {slug} -- {cat}\n")
                    for l in base:
                        f.write(l + "\n")
        # _all.csv (union)
        base_all = read_data_lines(os.path.join(canon_dir, "_all.csv"))
        for member, _e in cl:
            if member == canon:
                continue
            mpath = os.path.join(ITALIA, member, slug, "_all.csv")
            if not os.path.exists(mpath):
                continue
            mlines = [rewrite_url(l, member, canon, slug) for l in read_data_lines(mpath)]
            base_all, add = merge_lines(base_all, mlines)
            added_pois += add
        if base_all and not DRY:
            with open(os.path.join(canon_dir, "_all.csv"), "w", encoding="utf-8") as f:
                f.write("# lat,lng,id,name,building_type,type,url,page_type\n# " + slug + " -- Tutti\n")
                for l in base_all:
                    f.write(l + "\n")
        # pages
        for member, _e in cl:
            if member == canon:
                continue
            if not DRY:
                copy_pages(os.path.join(ITALIA, member, slug), canon_dir)
        # rimuovi copie non canoniche
        for member, _e in cl:
            if member == canon:
                continue
            mdir = os.path.join(ITALIA, member, slug)
            if os.path.isdir(mdir):
                removed_folders += 1
                if not DRY:
                    shutil.rmtree(mdir)
        merged_count += 1

    # 1) rigenera _citta.csv per ogni regione
    region_entries = {r: {} for r in REGION_BBOX}  # slug -> entry dict
    for (slug, idx), region in assigned.items():
        cl = cluster_info.get((slug, idx), ([], region))
        members = cl[0] if cl[0] else [(region, indexes[region][slug])]
        canon = cl[1]
        # trova la copia canonica per riga/coords
        entry = None
        for mregion, e in members:
            if mregion == canon:
                entry = e
                break
        if entry is None:
            entry = indexes[canon][slug]
        region_entries[canon][slug] = entry

    # conteggi ricalcolati dai file categoria
    if not DRY:
        for region, entries in region_entries.items():
            for slug, e in entries.items():
                counts = {"h": 0, "r": 0, "b": 0, "g": 0, "l": 0}
                cdir = os.path.join(ITALIA, region, slug)
                for cat, col in CATEGORY_COUNT.items():
                    counts[col] = sum(1 for _ in read_data_lines(os.path.join(cdir, cat)))
                e["counts"] = counts

    # 2) rigenera _citta.csv e _all.csv
    rows_after = 0
    for region, entries in region_entries.items():
        rdir = os.path.join(ITALIA, region)
        os.makedirs(rdir, exist_ok=True)
        rows_after += len(entries)
        if DRY:
            continue
        with open(os.path.join(rdir, "_citta.csv"), "w", encoding="utf-8") as f:
            f.write("# lat,lng,citta,slug,ospedali,ristoranti,bar_cafe,palestre,monumenti\n")
            for slug in sorted(entries):
                e = entries[slug]
                c = e.get("counts", {})
                f.write(f"{e['lat']:.6f},{e['lng']:.6f},{e['name']},{slug},{c.get('h',0)},{c.get('r',0)},{c.get('b',0)},{c.get('g',0)},{c.get('l',0)}\n")
        # _all.csv regionale: union dei _all.csv delle città sopravvissute
        all_lines = []
        for slug in entries:
            all_lines.extend(read_data_lines(os.path.join(rdir, slug, "_all.csv")))
        all_lines, _ = merge_lines([], all_lines)
        with open(os.path.join(rdir, "_all.csv"), "w", encoding="utf-8") as f:
            f.write("# lat,lng,id,name,building_type,type,url,page_type\n# " + REGION_NAMES[region] + " -- Tutti (OSM+Overture)\n")
            for l in all_lines:
                f.write(l + "\n")

    # 3) rigenera _regioni.csv pulito
    if not DRY:
        with open(os.path.join(ITALIA, "_regioni.csv"), "w", encoding="utf-8") as f:
            f.write("# nome,slug\n")
            for slug in REGION_NAMES:
                f.write(f"{REGION_NAMES[slug]},{slug}\n")

    print()
    print(f"Righe _citta.csv prima:  {total_rows_before}")
    print(f"Righe _citta.csv dopo:   {rows_after}  (-{total_rows_before - rows_after})")
    print(f"Cluster città unite:     {merged_count}")
    print(f"Cartelle città rimosse:  {removed_folders}")
    print(f"POI aggiunti (union):    {added_pois}")
    print("DRY RUN" if DRY else "APPLICATO")


if __name__ == "__main__":
    main()
