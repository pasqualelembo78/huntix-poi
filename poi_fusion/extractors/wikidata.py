from __future__ import annotations
import json
import time
import urllib.parse
import urllib.request
from typing import Iterator

from poi_fusion.schema import UnifiedPoi, Source
from poi_fusion.extractors.base import BaseExtractor
from poi_fusion.regions import Region


SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "Huntix-POI-Fusion/1.0"


WD_CATEGORIES = {
    "hospital": ("wdt:P31/wdt:P279* wd:Q16917", "hospital"),
    "restaurant": ("wdt:P31/wdt:P279* wd:Q11707", "restaurant"),
    "bar_cafe": ("wdt:P31/wdt:P279* wd:Q187456", "bar_cafe"),
    "gym": ("wdt:P31/wdt:P279* wd:Q214400", "gym"),
    "monument": ("wdt:P31/wdt:P279* wd:Q4989906", "monument"),
    "museum": ("wdt:P31/wdt:P279* wd:Q33506", "monument"),
    "government": ("wdt:P31/wdt:P279* wd:Q207129", "government"),
    "bank": ("wdt:P31/wdt:P279* wd:Q41187", "bank"),
    "post_office": ("wdt:P31/wdt:P279* wd:Q28564", "post_office"),
    "library": ("wdt:P31/wdt:P279* wd:Q7078", "library"),
}


SPARQL_TEMPLATE = """
SELECT ?item ?itemLabel ?itemDescription ?coord ?website ?phone ?email ?street ?housenumber ?postcode ?city ?wikidata_id ?osm_id ?hours ?image WHERE {{
  VALUES (?type ?cat) {{
    {cat_values}
  }}
  ?item wdt:P31/wdt:P279* ?type ;
        wdt:P625 ?coord ;
        wdt:P17 wd:Q38 .
  {region_filter}
  OPTIONAL {{ ?item wdt:P856 ?website. }}
  OPTIONAL {{ ?item wdt:P1329 ?phone. }}
  OPTIONAL {{ ?item wdt:P968 ?email. }}
  OPTIONAL {{ ?item wdt:P6375 ?street. }}
  OPTIONAL {{ ?item wdt:P281 ?postcode. }}
  OPTIONAL {{ ?item wdt:P131 ?city_item. }}
  OPTIONAL {{ ?item wdt:P8462 ?osm_id. }}
  OPTIONAL {{ ?item wdt:P18 ?image. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "it,en". }}
}}
LIMIT 10000
""".strip()


def _build_sparql(categories: list[str], region: Region | None) -> str:
    cat_values = []
    for cat in categories:
        entry = WD_CATEGORIES.get(cat)
        if not entry:
            continue
        sparql_expr, _ = entry
        # extract Q ID from e.g. "wdt:P31/wdt:P279* wd:Q16917"
        qid = sparql_expr.split("wd:")[-1].split()[0]
        cat_values.append(f"(wd:{qid} \"{cat}\")")
    region_filter = ""
    if region:
        region_filter = f"?item wdt:P131/wdt:P131* wd:{region.wikidata_qid} ."
    return SPARQL_TEMPLATE.format(cat_values="\n    ".join(cat_values), region_filter=region_filter)


def _run_sparql(query: str) -> list[dict]:
    url = f"{SPARQL_ENDPOINT}?format=json&query={urllib.parse.quote(query)}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
        results = data.get("results", {}).get("bindings", [])
    return results


def _wikidata_id_from_uri(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri else ""


def _coord_from_wkt(wkt: str) -> tuple[float, float] | None:
    import re
    m = re.search(r"Point\(([\d.-]+)\s+([\d.-]+)\)", wkt)
    if m:
        return float(m.group(2)), float(m.group(1))
    return None


class WikidataExtractor(BaseExtractor):
    source = Source.WIKIDATA

    def __init__(self, region: Region | None = None):
        self.region = region

    def extract(self, categories: list[str]) -> Iterator[UnifiedPoi]:
        query = _build_sparql(categories, self.region)
        results = _run_sparql(query)
        time.sleep(1)

        for row in results:
            cat = row.get("cat", {}).get("value", "")
            item_id = _wikidata_id_from_uri(row.get("item", {}).get("value", ""))
            coord_wkt = row.get("coord", {}).get("value", "")
            coords = _coord_from_wkt(coord_wkt)
            if not coords:
                continue

            lat, lng = coords
            name = row.get("itemLabel", {}).get("value", "")
            desc = row.get("itemDescription", {}).get("value", "")

            poi = UnifiedPoi(
                id=f"wd_{item_id}",
                category=cat,
                wikidata_id=item_id,
                osm_id=_wikidata_id_from_uri(row.get("osm_id", {}).get("value", "")),
                name=name,
                name_it=name,
                lat=lat,
                lng=lng,
                street=row.get("street", {}).get("value", ""),
                postcode=row.get("postcode", {}).get("value", ""),
                phone=row.get("phone", {}).get("value", ""),
                email=row.get("email", {}).get("value", ""),
                website=row.get("website", {}).get("value", ""),
                description=desc,
                wikipedia_url=f"https://www.wikidata.org/wiki/{item_id}",
            )
            poi.provenance = {
                "name": self.source, "name_it": self.source,
                "lat": self.source, "lng": self.source,
                "street": self.source, "postcode": self.source,
                "phone": self.source, "email": self.source,
                "website": self.source, "description": self.source,
                "wikidata_id": self.source,
            }
            if poi.osm_id:
                poi.provenance["osm_id"] = self.source
            yield poi
