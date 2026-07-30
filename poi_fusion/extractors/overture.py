from __future__ import annotations
import json
import os
import shutil
import stat
import subprocess
import tempfile
import urllib.request
import zipfile
from pathlib import Path
from typing import Iterator

from poi_fusion.schema import UnifiedPoi, Source
from poi_fusion.extractors.base import BaseExtractor
from poi_fusion.regions import Region


DUCKDB_VERSION = "v1.2.1"
DUCKDB_URL = f"https://github.com/duckdb/duckdb/releases/download/{DUCKDB_VERSION}/duckdb_cli-linux-amd64.zip"


def _find_duckdb() -> str:
    path = shutil.which("duckdb")
    if path:
        return path
    local = os.path.join(os.path.dirname(__file__), "..", ".duckdb", "duckdb")
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return os.path.abspath(local)
    return ""


def _install_duckdb() -> str:
    path = _find_duckdb()
    if path:
        return path
    dest_dir = os.path.join(os.path.dirname(__file__), "..", ".duckdb")
    os.makedirs(dest_dir, exist_ok=True)
    zip_path = os.path.join(dest_dir, "duckdb.zip")
    bin_path = os.path.join(dest_dir, "duckdb")
    print(f"  [DUCKDB] Downloading {DUCKDB_URL}...")
    try:
        urllib.request.urlretrieve(DUCKDB_URL, zip_path)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extract("duckdb", dest_dir)
        st = os.stat(bin_path)
        os.chmod(bin_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        os.remove(zip_path)
        print(f"  [DUCKDB] Installed at {bin_path}")
        return bin_path
    except Exception as e:
        print(f"  [WARN] DuckDB install failed: {e}")
        return ""


DUCKDB_SCRIPT_TEMPLATE = """
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
  AND confidence > 0.5
  {region_filter};
"""


REGION_FILTER = """
  AND subdivisions IS NOT NULL
  AND list_contains(list_filter(
       subdivisions, x -> x IS NOT NULL
     ), '{region_name}')
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

    def __init__(self, db_path: str | None = None, region: Region | None = None):
        self.db_path = db_path or os.path.join(tempfile.gettempdir(), "overture_places.duckdb")
        self.region = region
        self.duckdb_bin = ""

    def extract(self, categories: list[str]) -> Iterator[UnifiedPoi]:
        self.duckdb_bin = _find_duckdb()
        if not self.duckdb_bin:
            self.duckdb_bin = _install_duckdb()
        if not self.duckdb_bin:
            print("  [SKIP] DuckDB non disponibile")
            return
        if not self._ensure_loaded():
            return
        for cat in categories:
            query = CAT_QUERIES.get(cat)
            if not query:
                continue
            yield from self._query_places(cat, query)

    def _ensure_loaded(self) -> bool:
        if os.path.exists(self.db_path) and os.path.getsize(self.db_path) > 1_000_000:
            print("  [DUCKDB] Database già caricato")
            return True
        try:
            region_filter = ""
            if self.region and self.region.overture_region:
                region_filter = REGION_FILTER.format(region_name=self.region.overture_region)
            script = DUCKDB_SCRIPT_TEMPLATE.format(region_filter=region_filter)
            print("  [DUCKDB] Caricamento dati Overture in corso...")
            subprocess.run(
                [self.duckdb_bin, self.db_path, "-c", script],
                capture_output=True, timeout=600,
            )
            print("  [DUCKDB] Caricamento completato")
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
                [self.duckdb_bin, self.db_path, "-json", "-c", sql],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return
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
