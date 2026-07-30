from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Region:
    name: str
    bbox: str  # lat_min,lon_min,lat_max,lon_max
    wikidata_qid: str
    iso_code: str  # IT-XX
    overture_region: str = ""
    cities: list[tuple[str, str]] = field(default_factory=list)  # [(nome, bbox), ...]


ITALIAN_REGIONS: list[Region] = [
    Region("Abruzzo", "41.7,13.0,42.9,14.8", "Q1284", "IT-65", "ABR", [
        ("L'Aquila", "42.3,13.4,42.5,13.7"),
        ("Pescara", "42.4,14.1,42.6,14.4"),
        ("Chieti", "42.3,14.1,42.6,14.4"),
        ("Teramo", "42.6,13.7,42.8,14.1"),
    ]),
    Region("Basilicata", "39.9,15.5,41.0,16.8", "Q1432", "IT-77", "BAS", [
        ("Potenza", "40.6,15.7,40.8,16.0"),
        ("Matera", "40.6,16.6,40.8,16.9"),
    ]),
    Region("Calabria", "37.8,15.5,40.2,17.2", "Q1458", "IT-78", "CAL", [
        ("Catanzaro", "38.8,16.5,39.1,16.8"),
        ("Reggio Calabria", "38.1,15.5,38.3,15.8"),
        ("Cosenza", "39.3,16.2,39.5,16.5"),
        ("Crotone", "39.0,17.0,39.2,17.3"),
        ("Vibo Valentia", "38.7,16.0,38.9,16.3"),
    ]),
    Region("Campania", "40.0,13.8,41.5,15.8", "Q1457", "IT-72", "CAM", [
        ("Napoli", "40.8,14.1,40.9,14.3"),
        ("Salerno", "40.6,14.7,40.8,15.0"),
        ("Caserta", "41.0,14.3,41.2,14.6"),
        ("Avellino", "40.9,14.7,41.1,15.0"),
        ("Benevento", "41.1,14.7,41.3,15.0"),
    ]),
    Region("Emilia-Romagna", "43.7,9.5,45.0,12.8", "Q1263", "IT-45", "EMR", [
        ("Bologna", "44.4,11.2,44.6,11.5"),
        ("Modena", "44.6,10.9,44.8,11.2"),
        ("Parma", "44.8,10.1,45.0,10.4"),
        ("Reggio Emilia", "44.7,10.6,44.9,10.9"),
        ("Rimini", "44.0,12.4,44.2,12.7"),
        ("Forlì", "44.2,12.0,44.4,12.3"),
        ("Ferrara", "44.8,11.5,45.0,11.8"),
        ("Piacenza", "45.0,9.6,45.2,9.9"),
    ]),
    Region("Friuli-Venezia Giulia", "45.6,12.3,46.7,13.9", "Q1250", "IT-36", "FVG", [
        ("Trieste", "45.6,13.6,45.8,13.8"),
        ("Udine", "46.0,13.2,46.2,13.5"),
        ("Pordenone", "45.9,12.6,46.1,12.9"),
        ("Gorizia", "45.9,13.5,46.1,13.7"),
    ]),
    Region("Lazio", "41.2,11.5,42.9,14.2", "Q1282", "IT-62", "LAZ", [
        ("Roma", "41.8,12.4,42.0,12.7"),
        ("Latina", "41.4,12.8,41.6,13.1"),
        ("Frosinone", "41.6,13.3,41.8,13.6"),
        ("Viterbo", "42.4,12.0,42.6,12.3"),
        ("Rieti", "42.4,12.8,42.6,13.1"),
    ]),
    Region("Liguria", "43.8,7.5,44.7,10.0", "Q1256", "IT-42", "LIG", [
        ("Genova", "44.4,8.9,44.6,9.2"),
        ("La Spezia", "44.1,9.8,44.3,10.1"),
        ("Savona", "44.3,8.4,44.5,8.7"),
        ("Imperia", "43.9,8.0,44.1,8.3"),
    ]),
    Region("Lombardia", "44.8,8.5,46.6,11.6", "Q1210", "IT-25", "LOM", [
        ("Milano", "45.4,9.1,45.6,9.4"),
        ("Brescia", "45.5,10.1,45.7,10.4"),
        ("Bergamo", "45.7,9.6,45.9,9.9"),
        ("Mantova", "45.1,10.9,45.3,11.2"),
        ("Padova", "45.4,11.8,45.6,12.1"),
        ("Verona", "45.4,10.9,45.6,11.2"),
        ("Varese", "45.8,8.5,46.0,8.8"),
    ]),
    Region("Marche", "42.8,12.3,44.0,14.0", "Q1303", "IT-57", "MAR", [
        ("Ancona", "43.6,13.4,43.8,13.7"),
        ("Pesaro", "43.9,12.8,44.1,13.1"),
        ("Urbino", "43.7,12.5,43.9,12.8"),
        ("Macerata", "43.2,13.4,13.7"),
        ("Ascoli Piceno", "42.8,13.5,43.0,13.8"),
    ]),
    Region("Molise", "41.3,13.8,42.1,15.3", "Q1431", "IT-67", "MOL", [
        ("Campobasso", "41.5,14.6,41.7,14.9"),
        ("Isernia", "41.6,14.1,41.8,14.4"),
    ]),
    Region("Piemonte", "44.6,6.5,46.5,9.3", "Q1216", "IT-21", "PIE", [
        ("Torino", "45.0,7.6,45.2,7.9"),
        ("Milano", "45.4,9.1,45.6,9.4"),
        ("Genova", "44.4,8.9,44.6,9.2"),
        ("Novara", "45.4,8.6,45.6,8.9"),
        ("Alessandria", "44.9,8.6,45.1,8.9"),
        ("Cuneo", "44.4,7.5,44.6,7.8"),
        ("Asti", "44.9,8.1,45.1,8.4"),
    ]),
    Region("Puglia", "39.7,15.0,42.1,18.8", "Q1207", "IT-75", "PUG", [
        ("Bari", "41.1,16.8,41.3,17.1"),
        ("Taranto", "40.4,17.0,40.6,17.3"),
        ("Foggia", "41.4,15.5,41.6,15.8"),
        ("Lecce", "40.3,18.2,40.5,18.4"),
        ("Brindisi", "40.6,17.6,40.8,17.9"),
        ("Barletta", "41.3,16.1,41.5,16.4"),
        ("Andria", "41.2,16.2,41.3,16.4"),
        ("Modugno", "41.0,16.8,41.1,17.0"),
    ]),
    Region("Sardegna", "38.8,8.0,41.3,10.0", "Q1462", "IT-88", "SAR", [
        ("Cagliari", "39.2,9.1,39.4,9.4"),
        ("Sassari", "40.7,8.5,40.9,8.8"),
    ]),
    Region("Sicilia", "36.5,11.8,38.9,15.6", "Q1460", "IT-82", "SIC", [
        ("Palermo", "38.1,13.3,38.3,13.6"),
        ("Catania", "37.5,15.0,15.3"),
        ("Messina", "38.2,15.5,15.8"),
        ("Siracusa", "37.0,15.2,15.5"),
        ("Trapani", "38.0,12.5,12.8"),
        ("Caltanissetta", "37.4,13.9,14.2"),
    ]),
    Region("Toscana", "42.3,9.6,44.5,12.5", "Q1279", "IT-52", "TOS", [
        ("Firenze", "43.7,11.2,11.5"),
        ("Siena", "43.3,11.3,11.6"),
        ("Pisa", "43.7,10.3,10.6"),
        ("Livorno", "43.5,10.3,10.6"),
        ("Lucca", "43.8,10.4,10.7"),
        ("Arezzo", "43.5,11.9,12.2"),
        ("Grosseto", "42.8,11.1,11.4"),
    ]),
    Region("Trentino-Alto Adige", "45.6,10.4,47.1,12.8", "Q1237", "IT-32", "TAA", [
        ("Trento", "46.0,11.1,11.4"),
        ("Bolzano", "46.5,11.3,11.6"),
    ]),
    Region("Umbria", "42.3,11.8,43.7,13.2", "Q1268", "IT-55", "UMB", [
        ("Perugia", "43.1,12.3,12.6"),
        ("Terni", "42.5,12.6,12.9"),
        ("Spoleto", "42.8,12.7,13.0"),
    ]),
    Region("Valle d'Aosta", "45.5,6.8,45.9,8.0", "Q1222", "IT-23", "VDA", [
        ("Aosta", "45.7,7.3,7.6"),
    ]),
    Region("Veneto", "44.8,10.6,46.7,13.1", "Q1243", "IT-34", "VEN", [
        ("Venezia", "45.4,12.3,12.6"),
        ("Verona", "45.4,10.9,11.2"),
        ("Padova", "45.4,11.8,12.1"),
        ("Vicenza", "45.5,11.5,11.8"),
        ("Treviso", "45.6,12.2,12.5"),
        ("Udine", "46.0,13.2,13.5"),
    ]),
]


def prompt_region() -> Region | None:
    print("\n=== SELEZIONE REGIONE ===")
    print("  0) Tutta Italia")
    for i, r in enumerate(ITALIAN_REGIONS, 1):
        has_cities = " [città]" if r.cities else ""
        print(f"  {i:2d}) {r.name}{has_cities}")
    while True:
        try:
            choice = input("\nScegli regione [0-20]: ").strip()
            n = int(choice)
            if n == 0:
                return None
            if 1 <= n <= len(ITALIAN_REGIONS):
                region = ITALIAN_REGIONS[n - 1]
                if region.cities:
                    print(f"\n  Regione: {region.name}")
                    print("  0) Tutta la regione")
                    for j, (city_name, _) in enumerate(region.cities, 1):
                        print(f"  {j:2d}) {city_name}")
                    while True:
                        try:
                            city_choice = input("\nScelta città [0-{}]: ".format(len(region.cities))).strip()
                            cn = int(city_choice)
                            if cn == 0:
                                return region
                            if 1 <= cn <= len(region.cities):
                                city_name, city_bbox = region.cities[cn - 1]
                                return Region(
                                    name=f"{region.name} - {city_name}",
                                    bbox=city_bbox,
                                    wikidata_qid=region.wikidata_qid,
                                    iso_code=region.iso_code,
                                    overture_region=region.overture_region,
                                )
                        except (ValueError, EOFError):
                            pass
                        print("Scelta non valida.")
                return region
        except (ValueError, EOFError):
            pass
        print("Scelta non valida.")
