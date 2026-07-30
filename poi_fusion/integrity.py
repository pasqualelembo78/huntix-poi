from __future__ import annotations

from poi_fusion.schema import UnifiedPoi


class IntegrityReport:
    def __init__(self):
        self.total = 0
        self.missing_name = 0
        self.missing_latlng = 0
        self.missing_city = 0
        self.missing_category = 0
        self.duplicate_ids: list[str] = []
        self.empty_street_but_housenumber = 0
        self.issues: list[str] = []

    @property
    def ok(self) -> bool:
        if self.missing_latlng > 0:
            return False
        if self.missing_category > 0:
            return False
        if self.duplicate_ids:
            return False
        if self.total > 0 and self.missing_name > max(3, self.total * 0.1):
            return False
        return True

    def print_report(self):
        print("\n=== INTEGRITY CHECK ===")
        print(f"  Total POIs:        {self.total}")
        print(f"  Missing lat/lng:   {self.missing_latlng}")
        print(f"  Missing name:      {self.missing_name}")
        print(f"  Missing city:      {self.missing_city}")
        print(f"  Missing category:  {self.missing_category}")
        print(f"  Duplicate IDs:     {len(self.duplicate_ids)}")
        if self.duplicate_ids:
            print(f"    -> {self.duplicate_ids[:10]}")
        if self.issues:
            print(f"  Issues ({len(self.issues)}):")
            for issue in self.issues[:20]:
                print(f"    - {issue}")
        if self.ok:
            print("  RESULT: OK")
        else:
            print("  RESULT: FAIL")


def check_integrity(pois: list[UnifiedPoi]) -> IntegrityReport:
    report = IntegrityReport()
    report.total = len(pois)

    seen_ids: dict[str, int] = {}
    for poi in pois:
        if not poi.effective_name():
            report.missing_name += 1
        if not poi.lat or not poi.lng:
            report.missing_latlng += 1
        if not poi.category:
            report.missing_category += 1
        if not poi.city:
            report.missing_city += 1
        if poi.street and poi.housenumber and not poi.city:
            report.empty_street_but_housenumber += 1

        pid = poi.id
        if pid in seen_ids:
            report.duplicate_ids.append(pid)
        seen_ids[pid] = seen_ids.get(pid, 0) + 1

    if report.duplicate_ids:
        report.issues.append(f"{len(report.duplicate_ids)} duplicate POI IDs found")

    if report.total > 0 and report.missing_name > report.total * 0.15:
        report.issues.append(f"Too many missing names: {report.missing_name}/{report.total}")

    return report
