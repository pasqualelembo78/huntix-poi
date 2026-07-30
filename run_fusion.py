#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys

sys.path.insert(0, ".")

from poi_fusion import run_fusion, DEFAULT_CATEGORIES


def main():
    parser = argparse.ArgumentParser(description="Huntix POI Fusion Engine")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_CATEGORIES,
                        help="POI categories to extract")
    parser.add_argument("--regions", nargs="+", default=["IT"],
                        help="ISO region codes")
    parser.add_argument("--output", default="output",
                        help="Output directory")
    parser.add_argument("--bbox", default=None,
                        help="OSM bbox (min_lat,min_lon,max_lat,max_lon)")
    parser.add_argument("--light", action="store_true",
                        help="Run OSM-only for quick testing")
    args = parser.parse_args()

    if args.light:
        from poi_fusion import run_fusion_light
        merged = run_fusion_light(
            categories=args.categories,
            output_dir=args.output,
            bbox=args.bbox,
        )
    else:
        merged = run_fusion(
            categories=args.categories,
            regions=args.regions,
            output_dir=args.output,
            bbox=args.bbox,
        )

    print(f"\nDone. {len(merged)} POIs exported.")


if __name__ == "__main__":
    main()
