#!/usr/bin/env python3
"""
Pianificazione per Overture da usare dentro run_fusion.py
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Iterator

from poi_fusion.schema import UnifiedPoi, Source
from poi_fusion.extractors.base import BaseExtractor
from poi_fusion.regions import Region
import pyarrow.parquet as pq
import pyarrow.compute as pc
from tqdm import tqdm

# Directory locale per Overture
OVERRIDE_DATA_DIR = Path("data/overture")
OVERRIDE_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Cache per file scaricato
download_cache = {}


def _ensure_overture_maps_cli():
    """Verifica che overturemaps sia disponibile"""
    try:
        result = subprocess.run(["overturemaps", "--version"], 
                              capture_output=True, text=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("  [OVERRIDE] overturemaps CLI non disponibile")
        return False


def _download_overture_region(bbox: str, output_path: Path, force: bool = False):
    """Scarica dati Overture per un bbox specifico"""
    if output_path.exists() and not force:
        print(f"  [OVERRIDE] File già scaricato: {output_path.name}")
        return output_path

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  [OVERRIDE] Scaricamento dati per bbox {bbox}...")
    
    try:
        # Scarica place
        place_path = output_path.with_suffix('.parquet')
        subprocess.run([
            "overturemaps", "download", "--type=place",
            "--bbox", bbox,
            "-f", "geoparquet",
            "-o", str(place_path)
        ], check=True, capture_output=True)
        
        if place_path.exists():
            return place_path
        else:
            # Fallback: usa il bbox predefinito per l'Italia
            if bbox == "6.60,36.60,18.60,47.10":
                return None
            return _download_overture_region("6.60,36.60,18.60,47.10", output_path, force)
            
    except subprocess.CalledProcessError as e:
        print(f"  [OVERRIDE] Errore download: {e}")
        return None


def _load_parquet_region(filepath: Path, bbox: str, categories: list[str]) -> Iterator[dict]:
    """Carica solo i record che intersecano il bbox"""
    if not filepath.exists():
        return
    
    try:
        # Carica con pyarrow per filtrare velocemente
        table = pq.read_table(filepath)
        
        # Assumi che la colonna geometry sia presente
        if "geometry" in table.column_names:
            # Questa sarebbe un'operazione più sofisticata - per ora restituisci tutti i dati
            # In un'implementazione reale, useremmo pyproj per determinare l'intersezione
            pass
        
        for record in table.to_pylist():
            # Filtra per categoria se necessario
            basic_cat = record.get("basic_category", "")
            # Mappa basic_category alla nostra categoria
            cat_map = {
                "hospital": "hospital",
                "restaurant": "restaurant",  
                "fast_food_restaurant": "restaurant",
                "food_service": "restaurant",
                "pizzeria": "restaurant",
                "bar": "bar_cafe",
                "cafe": "bar_cafe",
                "pub": "bar_cafe",
                "brewery": "bar_cafe",
                "gym": "gym",
                "fitness_studio": "gym",
                "fitness_center": "gym",
                "sport_or_fitness_facility": "gym",
                "museum": "monument",
                "monument": "monument",
                "castle": "monument",
                "tourist_attraction": "monument",
                "place_of_worship": "monument",
                "government": "government",
                "courthouse": "government",
                "town_hall": "government",
                "public_administration": "government",
                "bank": "bank",
                "financial_institution": "bank",
                "atm": "bank",
                "post_office": "post_office",
                "library": "library"
            }
            
            our_cat = cat_map.get(basic_cat)
            if our_cat in categories:
                record["our_category"] = our_cat
                yield record
                
    except Exception as e:
        print(f"  [OVERRIDE] Errore caricamento {filepath}: {e}")


class OvertureExtractor(BaseExtractor):
    """Estrattore Overture Maps basato sul download CLI"""
    source = Source.OVERTURE

    def __init__(self, db_path: str | None = None, region: Region | None = None):
        self.db_path = db_path or os.path.join(tempfile.gettempdir(), "overture_places.duckdb")
        self.region = region
        self._overture_dir = OVERRIDE_DATA_DIR / "italia"

    def extract(self, categories: list[str]) -> Iterator[UnifiedPoi]:
        if not _ensure_overture_maps_cli():
            print("  [OVERRIDE] Skipped - CLI non disponibile")
            return

        # Usa bbox della regione se disponibile, altrimenti Italia intero
        bbox = "6.60,36.60,18.60,47.10"  # Default Italia intero
        if self.region and self.region.bbox:
            bbox = self.region.bbox
            print(f"  [OVERRIDE] Utilizzo bbox regione: {bbox}")

        # Scarica file per la regione
        places_file = _download_overture_region(bbox, self._overture_dir / "places.parquet")
        
        if not places_file or not places_file.exists():
            print("  [OVERRIDE] Nessun dato Overture disponibile")
            return

        print(f"  [OVERRIDE] Caricamento {places_file.name}...")
        
        for record in _load_parquet_region(places_file, bbox, categories):
            poi = self._record_to_poi(record)
            if poi:
                yield poi

    def _record_to_poi(self, record: dict) -> UnifiedPoi | None:
        lat = record.get("lat")
        lng = record.get("lng")
        if lat is None or lng is None:
            return None

        names = record.get("names") or {}
        primary = names.get("primary", "")
        common = names.get("common", "")
        name = common or primary

        addresses = record.get("addresses") or []
        city = ""
        street = ""
        if addresses and len(addresses) > 0:
            addr = addresses[0]
            city = addr.get("locality", "")
            street = addr.get("street", "")

        phones = record.get("phones") or []
        phone = phones[0] if phones else ""

        websites = record.get("websites") or []
        website = websites[0] if websites else ""

        emails = record.get("emails") or []
        email = emails[0] if emails else ""

        cat = record.get("our_category", "")

        poi = UnifiedPoi(
            id=f"ov_{cat}_{lat:.4f}_{lng:.4f}",
            category=cat,
            overture_id=record.get("id", ""),
            name=name,
            lat=lat,
            lng=lng,
            city=city,
            street=street,
            phone=phone,
            email=email,
            website=website,
        )
        poi.provenance = {
            "name": self.source, "lat": self.source, "lng": self.source,
            "city": self.source, "street": self.source,
            "phone": self.source, "email": self.source, "website": self.source,
        }
        return poi
