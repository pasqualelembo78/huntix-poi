from __future__ import annotations
from dataclasses import dataclass


@dataclass
class Region:
    name: str
    bbox: str  # lat_min,lon_min,lat_max,lon_max
    wikidata_qid: str
    iso_code: str  # IT-XX
    overture_region: str = ""


ITALIAN_REGIONS: list[Region] = [
    Region("Abruzzo", "41.7,13.0,42.9,14.8", "Q1284", "IT-65", "ABR"),
    Region("Basilicata", "39.9,15.5,41.0,16.8", "Q1432", "IT-77", "BAS"),
    Region("Calabria", "37.8,15.5,40.2,17.2", "Q1458", "IT-78", "CAL"),
    Region("Campania", "40.0,13.8,41.5,15.8", "Q1457", "IT-72", "CAM"),
    Region("Emilia-Romagna", "43.7,9.5,45.0,12.8", "Q1263", "IT-45", "EMR"),
    Region("Friuli-Venezia Giulia", "45.6,12.3,46.7,13.9", "Q1250", "IT-36", "FVG"),
    Region("Lazio", "41.2,11.5,42.9,14.2", "Q1282", "IT-62", "LAZ"),
    Region("Liguria", "43.8,7.5,44.7,10.0", "Q1256", "IT-42", "LIG"),
    Region("Lombardia", "44.8,8.5,46.6,11.6", "Q1210", "IT-25", "LOM"),
    Region("Marche", "42.8,12.3,44.0,14.0", "Q1303", "IT-57", "MAR"),
    Region("Molise", "41.3,13.8,42.1,15.3", "Q1431", "IT-67", "MOL"),
    Region("Piemonte", "44.6,6.5,46.5,9.3", "Q1216", "IT-21", "PIE"),
    Region("Puglia", "39.7,15.0,42.1,18.8", "Q1207", "IT-75", "PUG"),
    Region("Sardegna", "38.8,8.0,41.3,10.0", "Q1462", "IT-88", "SAR"),
    Region("Sicilia", "36.5,11.8,38.9,15.6", "Q1460", "IT-82", "SIC"),
    Region("Toscana", "42.3,9.6,44.5,12.5", "Q1279", "IT-52", "TOS"),
    Region("Trentino-Alto Adige", "45.6,10.4,47.1,12.8", "Q1237", "IT-32", "TAA"),
    Region("Umbria", "42.3,11.8,43.7,13.2", "Q1268", "IT-55", "UMB"),
    Region("Valle d'Aosta", "45.5,6.8,45.9,8.0", "Q1222", "IT-23", "VDA"),
    Region("Veneto", "44.8,10.6,46.7,13.1", "Q1243", "IT-34", "VEN"),
]


def prompt_region() -> Region | None:
    print("\n=== SELEZIONE REGIONE ===")
    print("  0) Tutta Italia")
    for i, r in enumerate(ITALIAN_REGIONS, 1):
        print(f"  {i:2d}) {r.name}")
    while True:
        try:
            choice = input("\nScegli regione [0-20]: ").strip()
            n = int(choice)
            if n == 0:
                return None
            if 1 <= n <= len(ITALIAN_REGIONS):
                return ITALIAN_REGIONS[n - 1]
        except (ValueError, EOFError):
            pass
        print("Scelta non valida.")
