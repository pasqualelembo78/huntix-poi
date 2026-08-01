import json
import math

REGION_SLUG = {
    "Abruzzo": "abruzzo",
    "Basilicata": "basilicata",
    "Calabria": "calabria",
    "Campania": "campania",
    "Emilia-Romagna": "emilia-romagna",
    "Friuli-Venezia Giulia": "friuli_vg",
    "Lazio": "lazio",
    "Liguria": "liguria",
    "Lombardia": "lombardia",
    "Marche": "marche",
    "Molise": "molise",
    "Piemonte": "piemonte",
    "Puglia": "puglia",
    "Sardegna": "sardegna",
    "Sicilia": "sicilia",
    "Toscana": "toscana",
    "Trentino-Alto Adige/S\u00fcdtirol": "trentino-aa",
    "Umbria": "umbria",
    "Valle d'Aosta/Vall\u00e9e d'Aoste": "valle_daosta",
    "Veneto": "veneto",
}


class RegionIndex:
    def __init__(self, geojson_path):
        with open(geojson_path, encoding="utf-8") as f:
            data = json.load(f)
        self.polys = []
        for feat in data["features"]:
            slug = REGION_SLUG[feat["properties"]["reg_name"]]
            g = feat["geometry"]
            polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
            polys = [[self._decimate(r) for r in p] for p in polys]
            minx = min(pt[0] for p in polys for r in p for pt in r)
            miny = min(pt[1] for p in polys for r in p for pt in r)
            maxx = max(pt[0] for p in polys for r in p for pt in r)
            maxy = max(pt[1] for p in polys for r in p for pt in r)
            self.polys.append((slug, polys, (minx, miny, maxx, maxy)))

    @staticmethod
    def _in_ring(lat, lng, ring):
        inside = False
        n = len(ring)
        j = n - 1
        for i in range(n):
            xi, yi = ring[i]
            xj, yj = ring[j]
            if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / (yj - yi) + xi):
                inside = not inside
            j = i
        return inside

    @staticmethod
    def _decimate(ring, step=4):
        if len(ring) <= 3:
            return ring
        return [ring[i] for i in range(0, len(ring), step)] + [ring[-1]]

    def find(self, lat, lng):
        for slug, polys, bbox in self.polys:
            if not (bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]):
                continue
            for p in polys:
                if self._in_ring(lat, lng, p[0]):
                    if not any(self._in_ring(lat, lng, h) for h in p[1:]):
                        return slug
        return None

    def nearest(self, lat, lng):
        best, best_d = None, None
        for slug, polys, bbox in self.polys:
            d = self._dist_to_polys(lat, lng, polys)
            if best_d is None or d < best_d:
                best_d, best = d, slug
        return best

    @staticmethod
    def _dist_seg(lat, lng, a, b):
        x, y = lng, lat
        ax, ay = a
        bx, by = b
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(x - ax, y - ay)
        t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        return math.hypot(x - (ax + t * dx), y - (ay + t * dy))

    def _dist_to_polys(self, lat, lng, polys):
        d = float("inf")
        for p in polys:
            ring = p[0]
            n = len(ring)
            for i in range(n):
                d = min(d, self._dist_seg(lat, lng, ring[i], ring[(i + 1) % n]))
        return d

    def region_of(self, lat, lng):
        r = self.find(lat, lng)
        if r is None:
            r = self.nearest(lat, lng)
        return r
