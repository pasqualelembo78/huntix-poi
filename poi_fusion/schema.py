from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Source(Enum):
    OSM = "osm"
    OVERTURE = "overture"
    WIKIDATA = "wikidata"
    GEONAMES = "geonames"
    OPENADDRESSES = "openaddresses"
    OPENDATA = "opendata"


SOURCE_RANK = {
    Source.WIKIDATA: 0,
    Source.OSM: 1,
    Source.GEONAMES: 2,
    Source.OVERTURE: 3,
    Source.OPENADDRESSES: 4,
    Source.OPENDATA: 5,
}


CATEGORY_MAP = {
    "hospital": {"osm": {"amenity": "hospital"}, "wikidata": "Q16917", "overture": "hospital"},
    "restaurant": {"osm": {"amenity": ["restaurant", "fast_food", "pizzeria"]}, "wikidata": "Q11707", "overture": ["restaurant", "fast_food_restaurant"]},
    "bar_cafe": {"osm": {"amenity": ["bar", "cafe", "pub"]}, "wikidata": ["Q187456", "Q30022"], "overture": ["bar", "cafe", "pub"]},
    "gym": {"osm": {"leisure": "fitness_centre"}, "wikidata": "Q214400", "overture": ["gym", "fitness_studio"]},
    "monument": {"osm": {"tourism": ["attraction", "museum", "castle"], "historic": ["monument", "castle", "archaeological_site", "memorial"]}, "wikidata": ["Q33506", "Q4989906"], "overture": ["museum", "monument", "castle"]},
    "government": {"osm": [{"amenity": ["townhall", "courthouse"]}, {"office": "government"}], "wikidata": ["Q207129", "Q105543609"], "overture": ["government", "courthouse", "town_hall"]},
    "bank": {"osm": {"amenity": "bank"}, "wikidata": "Q41187", "overture": ["bank", "financial_institution"]},
    "post_office": {"osm": {"amenity": "post_office"}, "wikidata": "Q28564", "overture": "post_office"},
    "library": {"osm": {"amenity": "library"}, "wikidata": "Q7078", "overture": "library"},
}

BUILDING_TYPE_MAP = {
    "hospital": "HOSPITAL",
    "restaurant": "RESTAURANT",
    "bar_cafe": "RESTAURANT",
    "gym": "GYM",
    "monument": "MONUMENT",
    "government": "GOVERNMENT",
    "bank": "BANK",
    "post_office": "POST_OFFICE",
    "library": "LIBRARY",
}


@dataclass
class Provenance:
    source: Source
    field: str
    raw_value: str = ""
    confidence: float = 1.0


@dataclass
class UnifiedPoi:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    category: str = ""  # Italian key: hospital, restaurant, bar_cafe, gym, monument, government, bank, post_office, library

    osm_id: Optional[str] = None
    wikidata_id: Optional[str] = None
    geoname_id: Optional[str] = None
    overture_id: Optional[str] = None

    name: str = ""
    name_it: str = ""
    name_en: str = ""

    lat: float = 0.0
    lng: float = 0.0

    street: str = ""
    housenumber: str = ""
    city: str = ""
    postcode: str = ""
    country: str = "IT"

    phone: str = ""
    email: str = ""
    website: str = ""
    hours: str = ""

    description: str = ""
    wikipedia_url: str = ""

    # Source provenance per field
    provenance: dict[str, Source] = field(default_factory=dict)

    json_page_url: str = ""
    page_type: str = "custom"

    def source_guess(self) -> Source:
        if self.osm_id:
            return Source.OSM
        if self.wikidata_id:
            return Source.WIKIDATA
        if self.geoname_id:
            return Source.GEONAMES
        if self.overture_id:
            return Source.OVERTURE
        return Source.OPENDATA

    def effective_name(self) -> str:
        return self.name_it or self.name_en or self.name

    @property
    def building_type(self) -> str:
        return BUILDING_TYPE_MAP.get(self.category, "")

    @property
    def poi_type(self) -> str:
        return self.category

    def to_csv_tuple(self) -> tuple:
        return (
            f"{self.lat:.6f}",
            f"{self.lng:.6f}",
            self.id,
            self.effective_name(),
            self.building_type,
            self.poi_type,
            self.json_page_url,
            self.page_type,
        )

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.effective_name(),
            "name_it": self.name_it,
            "name_en": self.name_en,
            "lat": self.lat,
            "lng": self.lng,
            "category": self.category,
            "building_type": self.building_type,
            "poi_type": self.poi_type,
            "address": {
                "street": self.street,
                "housenumber": self.housenumber,
                "city": self.city,
                "postcode": self.postcode,
                "country": self.country,
            },
            "contact": {
                "phone": self.phone,
                "email": self.email,
                "website": self.website,
            },
            "hours": self.hours,
            "description": self.description,
            "wikipedia_url": self.wikipedia_url,
            "ids": {
                "osm": self.osm_id,
                "wikidata": self.wikidata_id,
                "geoname": self.geoname_id,
                "overture": self.overture_id,
            },
            "provenance": {
                k: v.value for k, v in self.provenance.items()
            },
        }
