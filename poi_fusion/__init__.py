from __future__ import annotations
import os
import time
import traceback

from poi_fusion.schema import UnifiedPoi
from poi_fusion.regions import Region
from poi_fusion.extractors import OsmExtractor, OvertureExtractor, WikidataExtractor, GeoNamesExtractor
from poi_fusion.matcher import PoiMatcher
from poi_fusion.merger import PoiMerger
from poi_fusion.exporter import export_csv, export_csv_extended, export_json_pages, export_provenance_report
from poi_fusion.integrity import check_integrity

DEFAULT_CATEGORIES = ["hospital", "restaurant", "bar_cafe", "gym", "monument", "government", "bank", "post_office", "library"]

SOURCE_PRIORITY = [
    ("OSM",       lambda r: OsmExtractor(bbox=r.bbox if r else None)),
    ("Wikidata",  lambda r: WikidataExtractor(region=r)),
    ("Overture",  lambda r: OvertureExtractor(region=r)),
    ("GeoNames",  lambda r: GeoNamesExtractor(region=r)),
]


def _run_source(ext, categories, collected, output_dir):
    name = type(ext).__name__

    cats_to_fetch = categories
    if collected:
        cats_with_data = set()
        for poi in collected:
            if poi.category:
                cats_with_data.add(poi.category)
        missing = [c for c in categories if c not in cats_with_data]
        if missing:
            cats_to_fetch = missing
            print(f"  -> {name} filling gaps: {missing}")
        else:
            all_count = len(collected)
            low_cats = []
            for cat in categories:
                count = sum(1 for p in collected if p.category == cat)
                if count < 3:
                    low_cats.append(cat)
            if low_cats and len(low_cats) < len(categories):
                cats_to_fetch = low_cats
                print(f"  -> {name} boosting low categories: {low_cats}")

    count = 0
    t0 = time.time()
    try:
        for poi in ext.extract(cats_to_fetch):
            collected.append(poi)
            count += 1
    except Exception as e:
        traceback.print_exc()
        print(f"  [FAIL] {name}: {e}")
    elapsed = time.time() - t0
    print(f"  [{name}] {count} POIs in {elapsed:.1f}s")
    return count


def run_fusion(
    categories: list[str] | None = None,
    output_dir: str = "output",
    region: Region | None = None,
) -> list[UnifiedPoi]:
    categories = categories or DEFAULT_CATEGORIES
    os.makedirs(output_dir, exist_ok=True)

    region_label = region.name if region else "Tutta Italia"
    print(f"\nRegione: {region_label}")
    print(f"Categorie: {', '.join(categories)}")
    print(f"Ordine fonti: {', '.join(name for name, _ in SOURCE_PRIORITY)}")

    all_pois: list[UnifiedPoi] = []

    for src_name, src_factory in SOURCE_PRIORITY:
        ext = src_factory(region)
        _run_source(ext, categories, all_pois, output_dir)

    print(f"\nTotal raw POIs: {len(all_pois)}")

    matcher = PoiMatcher(max_distance_m=80)
    clusters = matcher.cluster(all_pois)
    print(f"Clusters: {len(clusters)} (singletons: {sum(1 for c in clusters if len(c) == 1)})")

    merger = PoiMerger()
    merged = [merger.merge_cluster(c) for c in clusters]
    print(f"Merged POIs: {len(merged)}")

    csv_path = os.path.join(output_dir, "poi.csv")
    export_csv(merged, csv_path)
    print(f"CSV: {csv_path}")

    csv_ext_path = os.path.join(output_dir, "poi_extended.csv")
    export_csv_extended(merged, csv_ext_path)
    print(f"Extended CSV: {csv_ext_path}")

    json_dir = os.path.join(output_dir, "pages")
    export_json_pages(merged, json_dir)
    print(f"JSON pages: {json_dir}")

    report_path = os.path.join(output_dir, "provenance_report.json")
    export_provenance_report(clusters, report_path)
    print(f"Provenance report: {report_path}")

    integrity = check_integrity(merged)
    integrity.print_report()

    return merged, integrity
