from __future__ import annotations
import math
from collections import defaultdict

from poi_fusion.schema import UnifiedPoi


MAX_MERGE_DISTANCE_M = 80
MAX_FUZZY_DISTANCE_M = 200
MIN_NAME_SIMILARITY = 0.75
GRID_CELL_DEG = 0.002


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
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 1.0
    # Quick reject: length difference too large for similarity > 0.75
    if abs(len(a) - len(b)) > max_len * 0.25:
        return 0.0
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


def _grid_key(lat: float, lng: float) -> tuple[int, int]:
    return (int(lat / GRID_CELL_DEG), int(lng / GRID_CELL_DEG))


class PoiMatcher:
    def __init__(self, max_distance_m: float = MAX_MERGE_DISTANCE_M, fuzzy_distance_m: float = MAX_FUZZY_DISTANCE_M):
        self.max_distance = max_distance_m
        self.fuzzy_distance = fuzzy_distance_m

    def cluster(self, pois: list[UnifiedPoi]) -> list[list[UnifiedPoi]]:
        if len(pois) < 2:
            return [[p] for p in pois]

        n = len(pois)
        parent = list(range(n))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(x: int, y: int):
            rx, ry = find(x), find(y)
            if rx != ry:
                parent[ry] = rx

        # Phase 1: exact ID match
        id_map: dict[str, int] = {}
        for i, p in enumerate(pois):
            for attr in ["osm_id", "wikidata_id", "geoname_id", "overture_id"]:
                vid = getattr(p, attr, None)
                if vid:
                    key = f"{attr}:{vid}"
                    if key in id_map:
                        union(id_map[key], i)
                        break
                    id_map[key] = i

        # Phase 2: spatial + name match within same category
        by_cat: dict[str, list[int]] = defaultdict(list)
        for i, p in enumerate(pois):
            by_cat[p.category].append(i)

        for cat, indices in by_cat.items():
            cat_pois = [(i, pois[i]) for i in indices]
            grid: dict[tuple[int, int], list[int]] = defaultdict(list)
            for local_i, (global_i, p) in enumerate(cat_pois):
                grid[_grid_key(p.lat, p.lng)].append(local_i)

            for local_i, (gi, p) in enumerate(cat_pois):
                gk = _grid_key(p.lat, p.lng)
                for dlat in (-1, 0, 1):
                    for dlng in (-1, 0, 1):
                        for local_j in grid.get((gk[0] + dlat, gk[1] + dlng), []):
                            if local_j <= local_i:
                                continue
                            gj, other = cat_pois[local_j]
                            if find(gi) == find(gj):
                                continue
                            if self._is_match(p, other):
                                union(gi, gj)

        # Collect clusters
        cluster_map: dict[int, list[UnifiedPoi]] = defaultdict(list)
        for i, p in enumerate(pois):
            cluster_map[find(i)].append(p)

        return list(cluster_map.values())

    def _is_match(self, a: UnifiedPoi, b: UnifiedPoi) -> bool:
        if self._id_match(a, b):
            return True
        dist = _haversine_m(a, b)
        if dist > self.fuzzy_distance:
            return False
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
