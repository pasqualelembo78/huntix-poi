from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Iterator
from poi_fusion.schema import UnifiedPoi, Source


class BaseExtractor(ABC):
    source: Source

    @abstractmethod
    def extract(self, categories: list[str], regions: list[str]) -> Iterator[UnifiedPoi]:
        ...
