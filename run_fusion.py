#!/usr/bin/env python3
from __future__ import annotations
import sys

sys.path.insert(0, ".")

from poi_fusion import DEFAULT_CATEGORIES
from poi_fusion.regions import prompt_region


def main():
    region = prompt_region()

    from poi_fusion import run_fusion
    merged = run_fusion(
        categories=DEFAULT_CATEGORIES,
        output_dir="output",
        region=region,
    )

    print(f"\nDone. {len(merged)} POIs exported.")


if __name__ == "__main__":
    main()
