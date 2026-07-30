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
MAX_TILE_DEG = 0.3  # max tile size in degrees (~30km) — guarantees no 504


def _rules_to_blocks(rules, bbox: str) -> list[str]:
    if isinstance(rules, list):
        blocks = []
        for rule_set in rules:
            parts = []
            for key, val in rule_set.items():
                if isinstance(val, list):
                    vals = "|".join(v.replace("_", r"[ _]") for v in val)
                    parts.append(f'[{key}~"{vals}"]')
                else:
                    parts.append(f'[{key}="{val}"]')
            tag_str = "".join(parts)
            blocks.append(f'  node{tag_str}({bbox});\n  way{tag_str}({bbox});\n  relation{tag_str}({bbox});')
        return blocks
    else:
        parts = []
        for key, val in rules.items():
            if isinstance(val, list):
                vals = "|".join(v.replace("_", r"[ _]") for v in val)
                parts.append(f'[{key}~"{vals}"]')
            else:
                parts.append(f'[{key}="{val}"]')
        tag_str = "".join(parts)
        return [f'  node{tag_str}({bbox});\n  way{tag_str}({bbox});\n  relation{tag_str}({bbox});']


def _build_osm_query(categories: list[str], bbox: str | None = None) -> str:
    sets = []
    for cat in categories:
        rules = CATEGORY_MAP[cat]["osm"]
        sets.extend(_rules_to_blocks(rules, bbox))
    body = "\n".join(sets)
    return f"[out:json][timeout:300];\n({body});\nout center;"


def _run_overpass(query: str) -> list[dict]:
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read()).get("elements", [])


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    parts = [float(x) for x in bbox.split(",")]
    return parts[0], parts[1], parts[2], parts[3]


def _split_bbox(bbox: str, n_lat: int, n_lon: int) -> list[str]:
    lat_min, lon_min, lat_max, lon_max = _parse_bbox(bbox)
    dlat = (lat_max - lat_min) / n_lat
    dlon = (lon_max - lon_min) / n_lon
    tiles = []
    for i in range(n_lat):
        for j in range(n_lon):
            tiles.append(f"{lat_min + i*dlat},{lon_min + j*dlon},{lat_min + (i+1)*dlat},{lon_min + (j+1)*dlon}")
    return tiles


def _tags_match_rules(tags: dict, rules) -> bool:
    if isinstance(rules, list):
        for rule_set in rules:
            for key, val in rule_set.items():
                actual = tags.get(key, "")
                if isinstance(val, list):
                    if not any(actual == v or actual.startswith(v) for v in val if v):
                        break
                else:
                    if actual != val and not actual.startswith(val):
                        break
            else:
                return True
        return False
    else:
        for key, val in rules.items():
            actual = tags.get(key, "")
            if isinstance(val, list):
                if not any(actual == v or actual.startswith(v) for v in val if v):
                    return False
            else:
                if actual != val and not actual.startswith(val) and not (key == "amenity" and val == "hospital" and tags.get("healthcare") == "hospital"):
                    return False
        return True


def _category_from_tags(tags: dict, categories: list[str]) -> str | None:
    for cat in categories:
        rules = CATEGORY_MAP[cat]["osm"]
        if _tags_match_rules(tags, rules):
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


def _clean_phone(p: str) -> str:
    if not p:
        return ""
    p = re.sub(r"[^\d+]", "", p)
    if p.startswith("+39") and len(p) >= 12:
        return p
    if p.startswith("0") and len(p) >= 9:
        return "+39" + p
    return p


class OsmExtractor(BaseExtractor):
    source = Source.OSM

    def __init__(self, bbox: str | None = None):
        self.bbox = bbox
        self._progress_cb = None

    def set_progress_callback(self, cb):
        self._progress_cb = cb

    def extract(self, categories: list[str]) -> Iterator[UnifiedPoi]:
        lat_min, lon_min, lat_max, lon_max = _parse_bbox(self.bbox or "41.5,12,47.5,19")
        n_lat = max(1, int((lat_max - lat_min) / MAX_TILE_DEG))
        n_lon = max(1, int((lon_max - lon_min) / MAX_TILE_DEG))
        tiles = _split_bbox(f"{lat_min},{lon_min},{lat_max},{lon_max}", n_lat, n_lon)
        n_tiles = len(tiles)

        for idx, bbox in enumerate(tiles):
            pct = (idx / n_tiles) * 100
            if self._progress_cb:
                self._progress_cb(pct)

            for attempt in range(5):
                    try:
                        query = _build_osm_query(categories, bbox)
                        elements = _run_overpass(query)
                        time.sleep(5)
                        for el in elements:
                            tags = el.get("tags", {})
                            cat = _category_from_tags(tags, categories)
                            if not cat:
                                continue
                            poi = self._el_to_poi(el, tags, cat)
                            if poi:
                                yield poi
                        break
                    except urllib.error.HTTPError as e:
                        if e.code == 429:
                            wait = 20 * (attempt + 1)
                            print(f"\n    [RETRY] tile {idx+1}/{n_tiles}: 429 → attesa {wait}s...")
                            time.sleep(wait)
                        elif e.code == 504:
                            if attempt < 3:
                                wait = 10 * (attempt + 1)
                                print(f"\n    [RETRY] tile {idx+1}/{n_tiles}: 504 → attesa {wait}s...")
                                time.sleep(wait)
                            else:
                                print(f"\n    [SKIP] tile {idx+1}/{n_tiles}: {e} (dopo {attempt+1} tentativi)")
                                break
                        else:
                            print(f"\n    [SKIP] tile {idx+1}/{n_tiles}: {e}")
                            break
                    except Exception as e:
                        print(f"\n    [SKIP] tile {idx+1}/{n_tiles}: {e}")
                        break

    def _el_to_poi(self, el: dict, tags: dict, cat: str) -> UnifiedPoi | None:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lng is None:
            return None

        name, name_it, name_en = _clean_name(tags)
        if not name:
            return None

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
        return poi
