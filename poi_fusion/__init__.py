from __future__ import annotations
import os
import sys
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


def _human_size(path: str) -> str:
    size = os.path.getsize(path)
    for unit in ("B", "KB", "MB"):
        if size < 1024:
            return f"{size:.0f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def _print_progress(pct: float, label: str):
    bar_len = 30
    filled = int(bar_len * pct / 100)
    bar = "█" * filled + "░" * (bar_len - filled)
    sys.stdout.write(f"\r  [{bar}] {pct:.0f}%  {label}    ")
    sys.stdout.flush()


def _print_cat_counts(pois: list[UnifiedPoi], indent: str = "  "):
    if not pois:
        return
    counts: dict[str, (int, dict)] = {}
    for p in pois:
        if p.category not in counts:
            counts[p.category] = [0, {}]
        counts[p.category][0] += 1
        src = str(p.source_guess().value)
        counts[p.category][1][src] = counts[p.category][1].get(src, 0) + 1

    for cat in sorted(counts):
        total, srcs = counts[cat]
        src_parts = [f"{s}={n}" for s, n in sorted(srcs.items())]
        print(f"  {indent}├ {cat}: {total}  ({', '.join(src_parts)})")


def _run_source(ext, categories, collected, output_dir, phase_pct_start: float, phase_pct_end: float,
                src_index: int, total_sources: int):
    name = type(ext).__name__

    cats_to_fetch = categories
    gap_label = ""
    if collected:
        cats_with_data = set()
        for poi in collected:
            if poi.category:
                cats_with_data.add(poi.category)
        missing = [c for c in categories if c not in cats_with_data]
        if missing and len(missing) < len(categories):
            cats_to_fetch = missing
            gap_label = f" gap: {missing}"
        else:
            low_cats = []
            for cat in categories:
                count = sum(1 for p in collected if p.category == cat)
                if count < 3:
                    low_cats.append(cat)
            if low_cats and len(low_cats) < len(categories):
                cats_to_fetch = low_cats
                gap_label = f" boost: {low_cats}"

    count = 0
    cat_count: dict[str, int] = {}
    t0 = time.time()

    progress_callback = getattr(ext, "set_progress_callback", None)
    if progress_callback:
        def on_tile(pct_tile):
            overall = phase_pct_start + (phase_pct_end - phase_pct_start) * pct_tile / 100
            _print_progress(overall, f"[{src_index}/{total_sources}] {name}{gap_label}")
        ext.set_progress_callback(on_tile)

    try:
        for poi in ext.extract(cats_to_fetch):
            collected.append(poi)
            count += 1
            cat_count[poi.category] = cat_count.get(poi.category, 0) + 1
    except Exception as e:
        traceback.print_exc()
        print(f"\n  [FAIL] {name}: {e}")

    elapsed = time.time() - t0
    _print_progress(phase_pct_end, f"[{src_index}/{total_sources}] {name}: {count} POI in {elapsed:.1f}s")
    print()

    parts = [f"{c}: {n}" for c, n in sorted(cat_count.items()) if n > 0]
    for cat, n in sorted(cat_count.items()):
        print(f"  ├ {cat}: {n}")

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
    print(f"Categorie ({len(categories)}): {', '.join(categories)}")
    print(f"Fonti ({len(SOURCE_PRIORITY)}): {', '.join(n for n, _ in SOURCE_PRIORITY)}")

    all_pois: list[UnifiedPoi] = []
    n_sources = len(SOURCE_PRIORITY)
    extract_pct = 50

    for idx, (src_name, src_factory) in enumerate(SOURCE_PRIORITY):
        ext = src_factory(region)
        pct_start = (idx / n_sources) * extract_pct
        pct_end = ((idx + 1) / n_sources) * extract_pct
        _run_source(ext, categories, all_pois, output_dir, pct_start, pct_end,
                    idx + 1, n_sources)

    print()
    _print_progress(52, "Dedup in corso...")
    t0 = time.time()
    matcher = PoiMatcher(max_distance_m=80)
    clusters = matcher.cluster(all_pois)
    dedup_elapsed = time.time() - t0

    singletons = sum(1 for c in clusters if len(c) == 1)
    multi = sum(1 for c in clusters if len(c) > 1)
    overlap_sizes = [len(c) for c in clusters if len(c) > 1]
    avg_overlap = sum(overlap_sizes) / len(overlap_sizes) if overlap_sizes else 0
    removed = len(all_pois) - len(clusters)

    _print_progress(62, f"Dedup: {len(all_pois)} → {len(clusters)} cluster in {dedup_elapsed:.2f}s")
    print()
    print(f"  ├ singletons: {singletons}")
    print(f"  ├ multi-fonte: {multi}")
    print(f"  ├ overlap medio: {avg_overlap:.1f} POI per cluster")
    print(f"  ├ duplicati: {removed} ({removed/len(all_pois)*100:.1f}%)")

    _print_progress(65, "Merge in corso...")
    t0 = time.time()
    merger = PoiMerger()
    merged = [merger.merge_cluster(c) for c in clusters]
    merge_elapsed = time.time() - t0
    removed_after_merge = len(all_pois) - len(merged)

    _print_progress(75, f"Merge: {len(merged)} POI in {merge_elapsed:.2f}s")
    print()
    print(f"  ├ raw: {len(all_pois)} POI da {n_sources} fonti")
    print(f"  ├ cluster: {len(clusters)}")
    print(f"  ├ finali: {len(merged)}")
    print(f"  ├ rimossi: {removed_after_merge} ({removed_after_merge/len(all_pois)*100:.1f}%)")
    _print_cat_counts(merged)

    _print_progress(78, "Export CSV...")
    csv_path = os.path.join(output_dir, "poi.csv")
    export_csv(merged, csv_path)

    csv_ext_path = os.path.join(output_dir, "poi_extended.csv")
    export_csv_extended(merged, csv_ext_path)
    _print_progress(85, "Export JSON pages...")

    json_dir = os.path.join(output_dir, "pages")
    n_cities = len(set(p.city or "unknown" for p in merged))
    export_json_pages(merged, json_dir)

    _print_progress(92, "Export report...")
    report_path = os.path.join(output_dir, "provenance_report.json")
    export_provenance_report(clusters, report_path)

    _print_progress(95, "Integrity check...")
    integrity = check_integrity(merged)

    _print_progress(100, "Completato!")
    print()

    print(f"\n  ┌─ {'='*40}")
    print(f"  │ Riepilogo")
    print(f"  ├─ Fonti: {len(SOURCE_PRIORITY)}")
    print(f"  ├─ POI grezzi: {len(all_pois)}")
    print(f"  ├─ POI finali: {len(merged)}")
    print(f"  ├─ Città: {n_cities}")
    print(f"  ├─ CSV: {_human_size(csv_path)} ({csv_path})")
    print(f"  ├─ JSON: {n_cities} città, {len(merged)} pagine")
    print(f"  ├─ Dedup: {dedup_elapsed:.2f}s")
    print(f"  ├─ Merge: {merge_elapsed:.2f}s")
    print(f"  └─ Integrity: {'OK' if integrity.ok else 'FAIL'}")
    print()

    integrity.print_report()

    return merged, integrity
