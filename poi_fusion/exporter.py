from __future__ import annotations
import csv
import json
import os
from typing import Iterator

from poi_fusion.schema import UnifiedPoi


CSV_HEADER = ["lat", "lng", "id", "name", "building_type", "type", "url", "page_type"]

CSV_HEADER_EXTENDED = [
    "lat", "lng", "id", "name", "name_it", "name_en",
    "building_type", "type",
    "street", "housenumber", "city", "postcode",
    "phone", "email", "website", "hours",
    "description", "wikipedia_url",
    "osm_id", "wikidata_id", "geoname_id", "overture_id",
    "provenance",
]


def export_csv(pois: list[UnifiedPoi], path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {','.join(CSV_HEADER)}\n")
        writer = csv.writer(f, lineterminator="\n")
        for poi in pois:
            writer.writerow(poi.to_csv_tuple())


def export_csv_extended(pois: list[UnifiedPoi], path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(f"# {','.join(CSV_HEADER_EXTENDED)}\n")
        writer = csv.writer(f, lineterminator="\n")
        for poi in pois:
            provenance_json = json.dumps(
                {k: v.value if hasattr(v, "value") else str(v) for k, v in poi.provenance.items()},
                ensure_ascii=False,
            )
            writer.writerow([
                f"{poi.lat:.6f}", f"{poi.lng:.6f}",
                poi.id, poi.name, poi.name_it, poi.name_en,
                poi.building_type, poi.poi_type,
                poi.street, poi.housenumber, poi.city, poi.postcode,
                poi.phone, poi.email, poi.website, poi.hours,
                poi.description, poi.wikipedia_url,
                poi.osm_id or "", poi.wikidata_id or "", poi.geoname_id or "", poi.overture_id or "",
                provenance_json,
            ])


def export_json_page(poi: UnifiedPoi, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(poi.to_json(), f, ensure_ascii=False, indent=2)


def export_json_pages(pois: list[UnifiedPoi], base_dir: str):
    for poi in pois:
        slug = _slugify(poi.effective_name() or poi.id)
        city_slug = _slugify(poi.city) if poi.city else "unknown"
        rel_path = f"pages/{city_slug}/{poi.category}/{slug}.json"
        export_json_page(poi, os.path.join(base_dir, rel_path))
        poi.json_page_url = f"https://raw.githubusercontent.com/pasqualelembo78/huntix-poi/main/{rel_path}"


def export_provenance_report(clusters: list[list[UnifiedPoi]], path: str):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    rows = []
    for cluster in clusters:
        if len(cluster) <= 1:
            continue
        base = cluster[0]
        conflicts = []
        for field in ["name", "lat", "lng", "phone", "website"]:
            vals = set()
            for p in cluster:
                v = getattr(p, field, "")
                if v:
                    vals.add(str(v))
            if len(vals) > 1:
                conflicts.append(f"{field}: {', '.join(vals)}")
        rows.append({
            "id": base.id,
            "name": base.effective_name(),
            "merged_from": len(cluster),
            "sources": ", ".join(p.provenance.get("name", str(p.source_guess())) for p in cluster),
            "conflicts": "; ".join(conflicts),
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=2)


def _slugify(name: str) -> str:
    import re
    s = name.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s_]+", "_", s)
    s = re.sub(r"-+", "_", s)
    return s[:64]
