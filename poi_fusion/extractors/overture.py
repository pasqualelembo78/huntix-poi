from __future__ import annotations
import os
import subprocess
import tempfile
from typing import Iterator

from poi_fusion.schema import UnifiedPoi, Source, CATEGORY_MAP
from poi_fusion.extractors.base import BaseExtractor


DUCKDB_SCRIPT = """
INSTALL httpfs;
LOAD httpfs;
INSTALL spatial;
LOAD spatial;

SET s3_region='us-west-2';

CREATE TABLE places AS
SELECT * EXCLUDE (bbox, geometry),
       ST_X(geometry) AS lng,
       ST_Y(geometry) AS lat,
       names,
       categories,
       addresses,
       phones,
       websites,
       socials,
       emails
FROM read_parquet('s3://overturemaps-us-west-2/release/2026-07-22.0/theme=places/type=place/*',
                  filename=true, hive_partitioning=true)
WHERE UPPER(REPLACE(REPLACE(admin_region, '-', ''), '_', '')) LIKE '%IT%'
  AND confidence > 0.5;
"""


CAT_QUERIES = {
    "hospital": "basic_category = 'hospital'",
    "restaurant": "basic_category IN ('restaurant', 'fast_food_restaurant', 'food_service', 'pizzeria')",
    "bar_cafe": "basic_category IN ('bar', 'cafe', 'pub', 'brewery')",
    "gym": "basic_category IN ('gym', 'fitness_studio', 'fitness_center', 'sport_or_fitness_facility')",
    "monument": "basic_category IN ('museum', 'monument', 'castle', 'tourist_attraction', 'place_of_worship')",
    "government": "basic_category IN ('government', 'courthouse', 'town_hall', 'public_administration')",
    "bank": "basic_category IN ('bank', 'financial_institution', 'atm')",
    "post_office": "basic_category = 'post_office'",
    "library": "basic_category = 'library'",
}


def _overture_category(basic_cat: str, categories_list: list | None) -> str | None:
    for our_cat, query in CAT_QUERIES.items():
        if "basic_category" in query:
            expected = query.split("= ")[1].strip("'")
            if basic_cat == expected:
                return our_cat
            if "IN" in query:
                vals = query.split("IN (")[1].rstrip(")")
                for v in vals.split(","):
                    if basic_cat == v.strip().strip("'"):
                        return our_cat
    return None


class OvertureExtractor(BaseExtractor):
    source = Source.OVERTURE

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.path.join(tempfile.gettempdir(), "overture_places.duckdb")

    def extract(self, categories: list[str], regions: list[str] | None = None) -> Iterator[UnifiedPoi]:
        if not self._ensure_loaded():
            return

        for cat in categories:
            query = CAT_QUERIES.get(cat)
            if not query:
                continue
            yield from self._query_places(cat, query)

    def _ensure_loaded(self) -> bool:
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1_000_000:
            return True
        try:
            subprocess.run(
                ["duckdb", self.db_path, "-c", DUCKDB_SCRIPT],
                capture_output=True, timeout=600,
            )
            return True
        except Exception as e:
            print(f"  [WARN] Overture DuckDB load failed: {e}")
            return False

    def _query_places(self, cat: str, condition: str) -> Iterator[UnifiedPoi]:
        sql = f"""
        SELECT id, names, primary_name, lat, lng, basic_category, categories,
               addresses, phones, websites, emails, confidence
        FROM places
        WHERE {condition}
        """
        try:
            result = subprocess.run(
                ["duckdb", self.db_path, "-json", "-c", sql],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return
            import json
            rows = json.loads(result.stdout)
            for row in rows:
                poi = self._row_to_poi(row, cat)
                if poi:
                    yield poi
        except Exception as e:
            print(f"  [WARN] Overture query failed for {cat}: {e}")

    def _row_to_poi(self, row: dict, cat: str) -> UnifiedPoi | None:
        lat = row.get("lat")
        lng = row.get("lng")
        if lat is None or lng is None:
            return None

        names = row.get("names") or {}
        primary = names.get("primary", row.get("primary_name", ""))
        common = names.get("common", "")
        name = common or primary

        addresses = row.get("addresses")
        city = ""
        street = ""
        if addresses and len(addresses) > 0:
            addr = addresses[0]
            city = addr.get("locality", "")
            street = addr.get("street", "")
            if not city:
                city = addr.get("region", "")

        phones = row.get("phones") or []
        phone = phones[0] if phones else ""

        websites = row.get("websites") or []
        website = websites[0] if websites else ""

        emails = row.get("emails") or []
        email = emails[0] if emails else ""

        poi = UnifiedPoi(
            id=f"ov_{cat}_{lat:.4f}_{lng:.4f}",
            category=cat,
            overture_id=row.get("id", ""),
            name=name,
            lat=lat,
            lng=lng,
            city=city,
            street=street,
            phone=phone,
            email=email,
            website=website,
        )
        poi.provenance = {
            "name": self.source, "lat": self.source, "lng": self.source,
            "city": self.source, "street": self.source,
            "phone": self.source, "email": self.source, "website": self.source,
        }
        return poi
