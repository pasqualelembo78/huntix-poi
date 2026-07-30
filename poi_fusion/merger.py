from __future__ import annotations

from poi_fusion.schema import UnifiedPoi, Source


_EX = Source.EXISTING

FIELD_PRIORITY: dict[str, list[Source]] = {
    "name": [_EX, Source.WIKIDATA, Source.OSM, Source.GEONAMES, Source.OVERTURE],
    "name_it": [_EX, Source.OSM, Source.WIKIDATA],
    "name_en": [_EX, Source.OSM, Source.GEONAMES, Source.WIKIDATA],
    "lat": [_EX, Source.OSM, Source.WIKIDATA, Source.OVERTURE, Source.GEONAMES],
    "lng": [_EX, Source.OSM, Source.WIKIDATA, Source.OVERTURE, Source.GEONAMES],
    "street": [_EX, Source.OSM, Source.OPENADDRESSES, Source.WIKIDATA],
    "housenumber": [_EX, Source.OSM, Source.OPENADDRESSES],
    "city": [_EX, Source.OSM, Source.GEONAMES, Source.WIKIDATA, Source.OVERTURE],
    "postcode": [_EX, Source.OSM, Source.GEONAMES, Source.WIKIDATA],
    "phone": [_EX, Source.OSM, Source.WIKIDATA, Source.OVERTURE],
    "email": [_EX, Source.OSM, Source.WIKIDATA],
    "website": [_EX, Source.OSM, Source.WIKIDATA, Source.OVERTURE],
    "hours": [_EX, Source.OSM],
    "description": [_EX, Source.WIKIDATA, Source.OSM],
    "wikipedia_url": [_EX, Source.WIKIDATA],
}

SOURCE_WEIGHT: dict[Source, int] = {s: i for i, s in enumerate([
    _EX, Source.WIKIDATA, Source.OSM, Source.GEONAMES, Source.OVERTURE, Source.OPENADDRESSES, Source.OPENDATA,
])}

MERGE_FIELDS = [
    "name", "name_it", "name_en", "lat", "lng",
    "street", "housenumber", "city", "postcode",
    "phone", "email", "website", "hours", "description", "wikipedia_url",
]


class PoiMerger:
    def __init__(self, field_priority: dict[str, list[Source]] | None = None):
        self.field_priority = field_priority or FIELD_PRIORITY

    def merge_cluster(self, cluster: list[UnifiedPoi]) -> UnifiedPoi:
        if len(cluster) == 1:
            return cluster[0]

        # Start from the highest-ranked source POI
        base = min(cluster, key=lambda p: SOURCE_WEIGHT.get(p.source_guess(), 999))

        merged = UnifiedPoi(
            category=base.category,
            id=base.id,
            osm_id=base.osm_id or self._first_non_none(cluster, "osm_id"),
            wikidata_id=base.wikidata_id or self._first_non_none(cluster, "wikidata_id"),
            geoname_id=base.geoname_id or self._first_non_none(cluster, "geoname_id"),
            overture_id=base.overture_id or self._first_non_none(cluster, "overture_id"),
        )

        for field in MERGE_FIELDS:
            best_val, best_src = self._pick_best(cluster, field)
            if best_val:
                setattr(merged, field, best_val)
                merged.provenance[field] = best_src

        # Override lat/lng from highest-ranked source
        lat, lng, lat_src = self._pick_best_latlng(cluster)
        if lat is not None:
            merged.lat = lat
            merged.lng = lng
            merged.provenance["lat"] = lat_src
            merged.provenance["lng"] = lat_src

        # City fallback
        if not merged.city:
            for p in cluster:
                if p.city:
                    merged.city = p.city
                    merged.provenance["city"] = p.provenance.get("city", p.source_guess())
                    break

        return merged

    def _pick_best(self, cluster: list[UnifiedPoi], field: str) -> tuple:
        priority = self.field_priority.get(field, [])
        for src in priority:
            for poi in cluster:
                val = getattr(poi, field, "")
                if val and poi.provenance.get(field) == src:
                    return val, src
        # Fallback: any value
        for poi in cluster:
            val = getattr(poi, field, "")
            if val:
                src = poi.provenance.get(field, poi.source_guess())
                return val, src
        return "", None

    def _pick_best_latlng(self, cluster: list[UnifiedPoi]) -> tuple:
        priority = [_EX, Source.OSM, Source.WIKIDATA, Source.OVERTURE, Source.GEONAMES]
        for src in priority:
            for poi in cluster:
                if poi.provenance.get("lat") == src:
                    return poi.lat, poi.lng, src
        best = cluster[0]
        return best.lat, best.lng, best.provenance.get("lat", best.source_guess())

    def _first_non_none(self, cluster: list[UnifiedPoi], attr: str):
        for p in cluster:
            v = getattr(p, attr, None)
            if v:
                return v
        return None
