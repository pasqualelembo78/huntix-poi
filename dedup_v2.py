#!/usr/bin/env python3
"""
dedup_v2.py — Ricostruzione completa dei dati POI di huntix-poi.

Rispetto a dedup.py:
  - la regione di ogni città è assegnata con i CONFINI AMMINISTRATIVI reali
    (point-in-polygon su regioni ISTAT), non con il centro bbox.
  - vengono considerate anche le cartelle orfane (mai indicizzate) e le
    righe morte (indice senza cartella).
  - merge per prossimità (<= CLUSTER_KM) con guardia di similarità slug.
  - merge "teletrasporto" per slug identici (copie inquinate con coordinate
    errate, es. abruzzo/napoli a Omignano) e per base_name normalizzata
    quando esiste un solo gruppo primario.

Risultato: ogni città esiste UNA volta, nella sua regione corretta, con
l'unione dei POI (dedup per id). _citta.csv, _all.csv e _regioni.csv
vengono rigenerati. Le pagine JSON vengono copiate e gli url riscritti.

Uso: python3 dedup_v2.py [--dry-run]
"""
import os, sys, re, math, shutil

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from region_assign import RegionIndex

REPO = os.path.dirname(os.path.abspath(__file__))
ITALIA = os.path.join(REPO, "italia")
GEOJSON = os.path.join(REPO, "regioni.geojson")

DRY = "--dry-run" in sys.argv

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

CATEGORY_COUNT = {"hospitals.csv": "h", "restaurants.csv": "r", "bars_cafes.csv": "b",
                  "gyms.csv": "g", "landmarks.csv": "l"}

CLUSTER_KM = 1.5
LAT_DEG_PER_KM = 1.0 / 111.0

SUFFIX_TOKENS = ["abruzzo", "basilicata", "calabria", "campania", "emilia-romagna",
                 "emiliaromagna", "friuli", "friuli_venezia_giulia", "lazio", "liguria",
                 "lombardia", "marche", "molise", "piemonte", "puglia", "sardegna",
                 "sicilia", "toscana", "trentino", "trentino_alto_adige", "umbria",
                 "valle_daosta", "valle_d_aosta", "veneto", "venice", "italy", "italia"]


def haversine_km(lat1, lng1, lat2, lng2):
    R, dlat, dlng = 6371.0, math.radians(lat2 - lat1), math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def base_name(slug):
    s = re.sub(r"^[0-9]+_", "", slug)
    s = re.sub(r"_(italy|italia)$", "", s)
    for suf in SUFFIX_TOKENS:
        if s.endswith("_" + suf):
            s = s[:-(len(suf) + 1)]
    s = re.sub(r"_[a-z]{2}$", "", s)
    return s.strip("_")


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


def merge_lines(target_lines, new_lines):
    by_key = {}
    for l in target_lines:
        by_key[poi_key(l)] = l
    added = 0
    for l in new_lines:
        k = poi_key(l)
        if k is None or k in by_key:
            continue
        by_key[k] = l
        added += 1
    return list(by_key.values()), added


def rewrite_url(line, member_region, member_slug, final_region, final_slug):
    return line.replace(f"/italia/{member_region}/{member_slug}/pages/",
                        f"/italia/{final_region}/{final_slug}/pages/")


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
        entries[slug] = {"lat": lat, "lng": lng, "name": p[2].strip()}
    return entries


def poi_centroid(folder):
    f = os.path.join(folder, "_all.csv")
    lats, lngs = [], []
    if os.path.isfile(f):
        for l in open(f, encoding="utf-8", errors="replace"):
            if not l.strip() or l.startswith("#"):
                continue
            p = l.split(",")
            if len(p) >= 3:
                try:
                    lats.append(float(p[0]))
                    lngs.append(float(p[1]))
                except ValueError:
                    pass
    if not lats:
        return None
    return (sum(lats) / len(lats), sum(lngs) / len(lngs))


def collect_nodes():
    nodes = []
    for region in sorted(os.listdir(ITALIA)):
        rd = os.path.join(ITALIA, region)
        if not os.path.isdir(rd):
            continue
        index = parse_index(region)
        seen = set()
        for slug, e in index.items():
            seen.add(slug)
            nodes.append({
                "region": region, "slug": slug, "indexed": True,
                "lat": e["lat"], "lng": e["lng"], "name": e["name"],
            })
        for slug in os.listdir(rd):
            cd = os.path.join(rd, slug)
            f = os.path.join(cd, "_all.csv")
            if not os.path.isdir(cd) or slug == "pages" or not os.path.isfile(f):
                continue
            if slug in seen:
                continue
            c = poi_centroid(cd)
            if c is None:
                continue
            nodes.append({
                "region": region, "slug": slug, "indexed": False,
                "lat": c[0], "lng": c[1],
                "name": slug.replace("_", " ").title(),
            })
    return nodes


def should_merge(a, b):
    if a["slug"].casefold() == b["slug"].casefold():
        return True
    ba, bb = base_name(a["slug"]).casefold(), base_name(b["slug"]).casefold()
    if ba == bb:
        return True
    if len(ba) >= 4 and (ba in bb or bb in ba):
        return True
    return False


_poi_count_cache = {}


def poi_count(node):
    key = (node["region"], node["slug"])
    if key in _poi_count_cache:
        return _poi_count_cache[key]
    p = os.path.join(ITALIA, node["region"], node["slug"], "_all.csv")
    c = 0
    if os.path.exists(p):
        for l in open(p, encoding="utf-8", errors="replace"):
            if l.strip() and not l.startswith("#"):
                c += 1
    _poi_count_cache[key] = c
    return c


def choose_anchor(group, ri):
    best = None
    best_pois = -1
    for m in group:
        if not m["indexed"]:
            continue
        if ri.region_of(m["lat"], m["lng"]) != m["region"]:
            continue
        pc = poi_count(m)
        if pc > best_pois:
            best, best_pois = m, pc
    if best is not None:
        return best
    for m in group:
        pc = poi_count(m)
        if pc > best_pois:
            best, best_pois = m, pc
    return best or group[0]


def cluster_nodes(nodes, ri):
    parent = list(range(len(nodes)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    order = sorted(range(len(nodes)), key=lambda i: nodes[i]["lat"])
    band = CLUSTER_KM * LAT_DEG_PER_KM
    for idx in range(len(order)):
        i = order[idx]
        j = idx + 1
        while j < len(order) and nodes[order[j]]["lat"] - nodes[i]["lat"] <= band:
            k = order[j]
            d = haversine_km(nodes[i]["lat"], nodes[i]["lng"], nodes[k]["lat"], nodes[k]["lng"])
            if d <= CLUSTER_KM and should_merge(nodes[i], nodes[k]):
                union(i, k)
            j += 1

    # fase 2a: teleport per slug identico (case-insensitive), distanza libera
    by_slug = {}
    for i in range(len(nodes)):
        by_slug.setdefault(nodes[i]["slug"].casefold(), []).append(i)
    for slug, idxs in by_slug.items():
        for i in idxs[1:]:
            union(idxs[0], i)

    # fase 2b: teleport per base_name con un solo gruppo primario
    by_base = {}
    for i in range(len(nodes)):
        by_base.setdefault(base_name(nodes[i]["slug"]).casefold(), []).append(i)
    for b, idxs in by_base.items():
        if len(idxs) < 2:
            continue
        primaries = set()
        for i in idxs:
            n = nodes[i]
            if not n["indexed"]:
                continue
            if ri.region_of(n["lat"], n["lng"]) == n["region"]:
                primaries.add(find(i))
        if len(primaries) == 1:
            root = next(iter(primaries))
            for i in idxs:
                union(root, i)

    groups = {}
    for i in range(len(nodes)):
        groups.setdefault(find(i), []).append(nodes[i])
    return list(groups.values())


def has_city_data(members):
    for m in members:
        md = os.path.join(ITALIA, m["region"], m["slug"])
        for cat in CATEGORY_FILES + ["_all.csv"]:
            p = os.path.join(md, cat)
            if os.path.isfile(p) and os.path.getsize(p) > 0:
                return True
        pages = os.path.join(md, "pages")
        if os.path.isdir(pages) and os.listdir(pages):
            return True
    return False


def main():
    ri = RegionIndex(GEOJSON)
    print("Raccolgo le cartelle città...")
    nodes = collect_nodes()
    print(f"  {len(nodes)} città/cartelle totali (indicizzate + orfane)")

    print("Clusterizzazione per prossimità + slug...")
    groups = cluster_nodes(nodes, ri)
    print(f"  {len(groups)} cluster")

    # calcola per ogni gruppo la città finale
    final_cities = []
    merged_count = 0
    for group in groups:
        merged_count += 1 if len(group) > 1 else 0
        anchor = choose_anchor(group, ri)
        final_region = ri.region_of(anchor["lat"], anchor["lng"])
        final_cities.append({
            "region": final_region, "slug": anchor["slug"],
            "name": anchor["name"], "lat": anchor["lat"], "lng": anchor["lng"],
            "members": group,
        })

    # salta le righe morte senza dati (regione/provincia usate come città)
    before = len(final_cities)
    final_cities = [c for c in final_cities if has_city_data(c["members"])]
    dropped = before - len(final_cities)
    # collisioni slug nella regione finale
    claimed = set()
    for c in final_cities:
        key = (c["region"], c["slug"])
        if key in claimed:
            n = 2
            while (c["region"], f"{c['slug']}_{n}") in claimed:
                n += 1
            c["slug"] = f"{c['slug']}_{n}"
        claimed.add((c["region"], c["slug"]))

    removed_folders = added_pois = 0
    for c in final_cities:
        final_path = os.path.join(ITALIA, c["region"], c["slug"])
        if DRY:
            continue
        os.makedirs(final_path, exist_ok=True)
        merged = {cat: [] for cat in CATEGORY_FILES + ["_all.csv"]}
        for m in c["members"]:
            mdir = os.path.join(ITALIA, m["region"], m["slug"])
            for cat in CATEGORY_FILES + ["_all.csv"]:
                mp = os.path.join(mdir, cat)
                if os.path.exists(mp):
                    lines = [rewrite_url(l, m["region"], m["slug"], c["region"], c["slug"])
                             for l in read_data_lines(mp)]
                    merged[cat], add = merge_lines(merged[cat], lines)
                    added_pois += add
        for cat in CATEGORY_FILES + ["_all.csv"]:
            if merged[cat]:
                header = ("# lat,lng,id,name,building_type,type,url,page_type\n"
                          f"# {c['slug']} -- {cat}\n" if cat != "_all.csv" else
                          "# lat,lng,id,name,building_type,type,url,page_type\n"
                          f"# {c['slug']} -- Tutti\n")
                with open(os.path.join(final_path, cat), "w", encoding="utf-8") as f:
                    f.write(header)
                    for l in merged[cat]:
                        f.write(l + "\n")
        for m in c["members"]:
            mdir = os.path.join(ITALIA, m["region"], m["slug"])
            if mdir == final_path:
                continue
            copy_pages(mdir, final_path)
            if os.path.isdir(mdir):
                shutil.rmtree(mdir)
                removed_folders += 1

    # rimuovi cartelle pages a livello di regione (residui)
    for region in os.listdir(ITALIA):
        rd = os.path.join(ITALIA, region)
        if os.path.isdir(os.path.join(rd, "pages")):
            shutil.rmtree(os.path.join(rd, "pages"))

    # rigenera _citta.csv, _all.csv, _regioni.csv
    region_cities = {r: [] for r in REGION_NAMES}
    for c in final_cities:
        region_cities[c["region"]].append(c)

    rows_after = 0
    for region, cities in region_cities.items():
        rdir = os.path.join(ITALIA, region)
        os.makedirs(rdir, exist_ok=True)
        rows_after += len(cities)
        if DRY:
            continue
        with open(os.path.join(rdir, "_citta.csv"), "w", encoding="utf-8") as f:
            f.write("# lat,lng,citta,slug,ospedali,ristoranti,bar_cafe,palestre,monumenti\n")
            for c in sorted(cities, key=lambda x: x["slug"]):
                cdir = os.path.join(rdir, c["slug"])
                counts = {col: 0 for col in CATEGORY_COUNT.values()}
                for cat, col in CATEGORY_COUNT.items():
                    counts[col] = sum(1 for _ in read_data_lines(os.path.join(cdir, cat)))
                f.write(f"{c['lat']:.6f},{c['lng']:.6f},{c['name']},{c['slug']},"
                        f"{counts['h']},{counts['r']},{counts['b']},{counts['g']},{counts['l']}\n")
        all_lines = []
        for c in cities:
            all_lines.extend(read_data_lines(os.path.join(rdir, c["slug"], "_all.csv")))
        all_lines, _ = merge_lines([], all_lines)
        with open(os.path.join(rdir, "_all.csv"), "w", encoding="utf-8") as f:
            f.write("# lat,lng,id,name,building_type,type,url,page_type\n"
                    f"# {REGION_NAMES[region]} -- Tutti (OSM+Overture)\n")
            for l in all_lines:
                f.write(l + "\n")
    if not DRY:
        with open(os.path.join(ITALIA, "_regioni.csv"), "w", encoding="utf-8") as f:
            f.write("# nome,slug\n")
            for slug in REGION_NAMES:
                f.write(f"{REGION_NAMES[slug]},{slug}\n")

    print()
    print(f"Cluster città unite:       {merged_count}")
    print(f"Righe morte rimosse:       {dropped}")
    print(f"Cartelle città rimosse:    {removed_folders}")
    print(f"Righe _citta.csv dopo:     {rows_after}")
    print(f"POI aggiunti (union):      {added_pois}")
    print("DRY RUN" if DRY else "APPLICATO")


if __name__ == "__main__":
    main()
