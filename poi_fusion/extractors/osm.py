from __future__ import annotations
import json
import time
import re
import urllib.request
import urllib.parse
import urllib.error
from typing import Iterator

from poi_fusion.schema import UnifiedPoi, Source, CATEGORY_MAP
from poi_fusion.extractors.base import BaseExtractor


OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "Huntix-POI-Fusion/1.0"


def _build_osm_query(categories: list[str], bbox: str | None = None) -> str:
    sets = []
    for cat in categories:
        rules = CATEGORY_MAP[cat]["osm"]
        parts = []
        for key, val in rules.items():
            if isinstance(val, list):
                vals = "|".join(v.replace("_", r"[ _]") for v in val)
                parts.append(f'[{key}~"{vals}"]')
            else:
                parts.append(f'[{key}="{val}"]')
        tag_str = "".join(parts)
        sets.append(f'  node{tag_str}({bbox});\n  way{tag_str}({bbox});\n  relation{tag_str}({bbox});')
    body = "\n".join(sets)
    return f"""
[out:json][timeout:180];
({body});
out center 25;
""".strip()


def _run_overpass(query: str) -> list[dict]:
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=200) as resp:
        return json.loads(resp.read()).get("elements", [])


def _category_from_tags(tags: dict, categories: list[str]) -> str | None:
    for cat in categories:
        rules = CATEGORY_MAP[cat]["osm"]
        match = True
        for key, val in rules.items():
            actual = tags.get(key, "")
            if isinstance(val, list):
                if not any(actual == v or actual.startswith(v) for v in val if v):
                    match = False
                    break
            else:
                if actual != val and not actual.startswith(val) and not (key == "amenity" and val == "hospital" and tags.get("healthcare") == "hospital"):
                    match = False
                    break
        if match:
            return cat
    return None


def _clean_name(tags: dict) -> tuple[str, str, str]:
    name = tags.get("name", "")
    name_it = tags.get("name:it", "")
    name_en = tags.get("name:en", "")
    if not name_it and name:
        name_it = name
    if not name_en and name:
        name_en = name
    return name, name_it, name_en


def _osm_id_str(el: dict) -> str:
    return f"{'node' if el['type'] == 'node' else 'way'}/{el['id']}"


class OsmExtractor(BaseExtractor):
    source = Source.OSM

    def __init__(self, bbox: str | None = None):
        self.bbox = bbox

    def extract(self, categories: list[str]) -> Iterator[UnifiedPoi]:
        bbox = self.bbox or "41.5,12,47.5,19"  # default Italy
        query = _build_osm_query(categories, bbox)
        elements = _run_overpass(query)
        time.sleep(2)

        for el in elements:
            tags = el.get("tags", {})
            cat = _category_from_tags(tags, categories)
            if not cat:
                continue

            lat = el.get("lat") or el.get("center", {}).get("lat")
            lng = el.get("lon") or el.get("center", {}).get("lon")
            if lat is None or lng is None:
                continue

            name, name_it, name_en = _clean_name(tags)

            poi = UnifiedPoi(
                id=f"osm_{_osm_id_str(el).replace('/', '_')}_{lat:.4f}_{lng:.4f}",
                category=cat,
                osm_id=_osm_id_str(el),
                wikidata_id=tags.get("wikidata"),
                name=name,
                name_it=name_it,
                name_en=name_en,
                lat=lat,
                lng=lng,
                street=tags.get("addr:street", ""),
                housenumber=tags.get("addr:housenumber", ""),
                city=tags.get("addr:city", "") or tags.get("addr:town", "") or tags.get("addr:village", ""),
                postcode=tags.get("addr:postcode", ""),
                phone=_clean_phone(tags.get("phone", "") or tags.get("contact:phone", "")),
                email=tags.get("email", "") or tags.get("contact:email", ""),
                website=tags.get("website", "") or tags.get("contact:website", ""),
                hours=tags.get("opening_hours", ""),
                description=tags.get("description", ""),
            )
            poi.provenance = {f: self.source for f in [
                "name", "name_it", "name_en", "lat", "lng",
                "street", "housenumber", "city", "postcode",
                "phone", "email", "website", "hours", "description",
            ]}
            if tags.get("wikidata"):
                poi.provenance["wikidata_id"] = self.source
            yield poi


def _clean_phone(p: str) -> str:
    if not p:
        return ""
    p = re.sub(r"[^\d+]", "", p)
    if p.startswith("+39") and len(p) >= 12:
        return p
    if p.startswith("0") and len(p) >= 9:
        return "+39" + p
    return p
