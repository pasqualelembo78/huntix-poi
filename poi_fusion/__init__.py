from __future__ import annotations
import os
import time

from poi_fusion.schema import UnifiedPoi
from poi_fusion.regions import Region
from poi_fusion.extractors import OsmExtractor, OvertureExtractor, WikidataExtractor, GeoNamesExtractor
from poi_fusion.matcher import PoiMatcher
from poi_fusion.merger import PoiMerger
from poi_fusion.exporter import export_csv, export_csv_extended, export_json_pages, export_provenance_report

DEFAULT_CATEGORIES = ["hospital", "restaurant", "bar_cafe", "gym", "monument", "government", "bank", "post_office", "library"]


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

    all_pois: list[UnifiedPoi] = []
    extractors = [
        OsmExtractor(bbox=region.bbox if region else None),
        OvertureExtractor(region=region),
        WikidataExtractor(region=region),
        GeoNamesExtractor(region=region),
    ]

    for ext in extractors:
        name = type(ext).__name__
        print(f"\n[{name}] Extracting {categories}...")
        t0 = time.time()
        count = 0
        for poi in ext.extract(categories):
            all_pois.append(poi)
            count += 1
        elapsed = time.time() - t0
        print(f"  -> {count} POIs in {elapsed:.1f}s")

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

    return merged
