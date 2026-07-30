from __future__ import annotations
import math
from collections import defaultdict
from typing import Callable

from poi_fusion.schema import UnifiedPoi


MAX_MERGE_DISTANCE_M = 80
MAX_FUZZY_DISTANCE_M = 200
MIN_NAME_SIMILARITY = 0.75


def _haversine_m(p1: UnifiedPoi, p2: UnifiedPoi) -> float:
    R = 6371000
    dlat = math.radians(p2.lat - p1.lat)
    dlng = math.radians(p2.lng - p1.lng)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(p1.lat)) * math.cos(math.radians(p2.lat)) * math.sin(dlng / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _name_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    a, b = a.lower().strip(), b.lower().strip()
    if a == b:
        return 1.0
    if a in b or b in a:
        return 0.9
    # Levenshtein ratio
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    dist = _levenshtein(a, b)
    return 1.0 - (dist / max_len)


def _levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = range(len(b) + 1)
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[-1] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


class PoiMatcher:
    def __init__(self, max_distance_m: float = MAX_MERGE_DISTANCE_M, fuzzy_distance_m: float = MAX_FUZZY_DISTANCE_M):
        self.max_distance = max_distance_m
        self.fuzzy_distance = fuzzy_distance_m

    def cluster(self, pois: list[UnifiedPoi]) -> list[list[UnifiedPoi]]:
        clusters: list[list[UnifiedPoi]] = []
        assigned: set[int] = set()

        for i, poi in enumerate(pois):
            if i in assigned:
                continue
            cluster = [poi]
            assigned.add(i)
            for j in range(i + 1, len(pois)):
                if j in assigned:
                    continue
                other = pois[j]
                if self._is_match(poi, other):
                    cluster.append(other)
                    assigned.add(j)
            clusters.append(cluster)
        return clusters

    def _is_match(self, a: UnifiedPoi, b: UnifiedPoi) -> bool:
        # Exact ID match
        if self._id_match(a, b):
            return True
        # Coordinate proximity + name similarity
        dist = _haversine_m(a, b)
        sim = _name_similarity(a.effective_name(), b.effective_name())
        if dist < self.max_distance and sim > MIN_NAME_SIMILARITY:
            return True
        if dist < self.fuzzy_distance and sim > 0.9:
            return True
        return False

    def _id_match(self, a: UnifiedPoi, b: UnifiedPoi) -> bool:
        for attr in ["osm_id", "wikidata_id", "geoname_id", "overture_id"]:
            va = getattr(a, attr, None)
            vb = getattr(b, attr, None)
            if va and vb and va == vb:
                return True
        return False
