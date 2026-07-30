from __future__ import annotations
import json
import time
import urllib.parse
import urllib.request
from typing import Iterator

from poi_fusion.schema import UnifiedPoi, Source
from poi_fusion.extractors.base import BaseExtractor
from poi_fusion.regions import Region


GEONAMES_API = "http://api.geonames.org/searchJSON"
GEONAMES_USER = "demo"


GEONAMES_FEATURE_CODES = {
    "hospital": "HSP",
    "restaurant": "REST",
    "bar_cafe": "CAFE",
    "gym": "GYM",
    "monument": "MNMT",
    "government": "GVT",
    "bank": "BNK",
    "post_office": "PO",
    "library": "LBRY",
}


class GeoNamesExtractor(BaseExtractor):
    source = Source.GEONAMES

    def __init__(self, username: str = GEONAMES_USER, region: Region | None = None):
        self.username = username
        self.region = region

    def extract(self, categories: list[str]) -> Iterator[UnifiedPoi]:
        for cat in categories:
            yield from self._query_category(cat)

    def _query_category(self, cat: str) -> Iterator[UnifiedPoi]:
        fcode = GEONAMES_FEATURE_CODES.get(cat)
        if not fcode:
            return

        max_rows = 1000
        start_row = 0
        while start_row < 10000:
            params = {
                "country": "IT",
                "featureCode": fcode,
                "maxRows": max_rows,
                "startRow": start_row,
                "username": self.username,
                "style": "FULL",
            }
            if self.region:
                params["adminCode1"] = self.region.iso_code.split("-")[-1]
            url = f"{GEONAMES_API}?{urllib.parse.urlencode(params)}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Huntix-POI-Fusion/1.0"})
                with urllib.request.urlopen(req, timeout=30) as resp:
                    data = json.loads(resp.read())
                for entry in data.get("geonames", []):
                    poi = self._entry_to_poi(entry, cat)
                    if poi:
                        yield poi
                total = data.get("totalResultsCount", 0)
                start_row += max_rows
                if start_row >= total:
                    break
                time.sleep(1)
            except Exception as e:
                print(f"  [WARN] GeoNames query failed for {cat} at row {start_row}: {e}")
                break

    def _entry_to_poi(self, entry: dict, cat: str) -> UnifiedPoi | None:
        lat = entry.get("lat")
        lng = entry.get("lng")
        if lat is None or lng is None:
            return None
        lat = float(lat)
        lng = float(lng)

        poi = UnifiedPoi(
            id=f"gn_{entry.get('geonameId', '')}_{cat}_{lat:.4f}_{lng:.4f}",
            category=cat,
            geoname_id=str(entry.get("geonameId", "")),
            name=entry.get("name", "") or entry.get("toponymName", ""),
            name_en=entry.get("name", ""),
            lat=lat,
            lng=lng,
            street=entry.get("street", ""),
            city=entry.get("adminName2", "") or entry.get("adminName1", ""),
            postcode=entry.get("postcode", ""),
            country="IT",
        )
        poi.provenance = {
            "name": self.source, "name_en": self.source,
            "lat": self.source, "lng": self.source,
            "city": self.source, "postcode": self.source,
            "geoname_id": self.source,
        }
        return poi
