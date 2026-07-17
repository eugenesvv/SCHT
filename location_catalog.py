"""Offline Star Citizen location catalog, normalization, and waypoint distances."""

from __future__ import annotations

import json
import math
import re
import sys
from difflib import SequenceMatcher
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, Optional, Sequence


def normalize_location_text(value: str) -> str:
    value = " ".join(str(value or "").split()).casefold()
    value = value.replace("harbour", "harbor")
    # OCR commonly reads the ampersand in this location as a lowercase "e".
    # Normalize the full name before punctuation is stripped so hierarchy text
    # such as "at the L4 Lagrange..." can still resolve by canonical prefix.
    value = re.sub(
        r"\bdudley\s+(?:e|and|&)\s+daughters\b",
        "dudley & daughters",
        value,
    )
    return re.sub(r"[^a-z0-9]+", "", value)


@dataclass(frozen=True)
class LocationRecord:
    id: str
    name: str
    system: str = ""
    parent: str = ""
    type: str = ""
    position: Optional[tuple[float, float, float]] = None
    aliases: tuple[str, ...] = ()
    qt_valid: bool = False

    @property
    def subtitle(self) -> str:
        parts = []
        parent_key = normalize_location_text(self.parent)
        system_key = normalize_location_text(self.system.removesuffix(" System").removesuffix(" system"))
        if self.parent and parent_key != normalize_location_text(self.name) and parent_key != system_key:
            parts.append(self.parent)
        if self.system:
            label = self.system if self.system.lower().endswith("system") else f"{self.system} system"
            if not parts or normalize_location_text(parts[-1]) != normalize_location_text(label):
                parts.append(label)
        return " · ".join(parts)

    @property
    def qualified_name(self) -> str:
        return f"{self.name} — {self.subtitle}" if self.subtitle else self.name

    def payload(self, original: str = "", match: str = "exact") -> dict:
        return {
            "id": self.id, "name": self.name, "subtitle": self.subtitle,
            "qualified_name": self.qualified_name,
            "system": self.system, "parent": self.parent, "type": self.type,
            "original": original or self.name, "match": match,
            "has_position": self.position is not None,
        }


@dataclass(frozen=True)
class LocationMatch:
    original: str
    record: Optional[LocationRecord] = None
    status: str = "unresolved"

    @property
    def resolved(self) -> bool:
        return self.record is not None


class LocationCatalog:
    def __init__(self, records: Iterable[LocationRecord], aliases: Optional[dict] = None):
        self.records = tuple(records)
        self.by_id = {record.id: record for record in self.records}
        self.by_name: Dict[str, list[LocationRecord]] = {}
        self.by_qualified: Dict[str, LocationRecord] = {}
        self.by_alias: Dict[str, LocationRecord] = {}
        for record in self.records:
            self.by_name.setdefault(normalize_location_text(record.name), []).append(record)
            self.by_qualified[normalize_location_text(record.qualified_name)] = record
            for alias in record.aliases:
                self.by_alias[normalize_location_text(alias)] = record
        for alias, target in (aliases or {}).items():
            record = self.by_id.get(str(target))
            if record is None:
                candidates = self.by_name.get(normalize_location_text(str(target)), [])
                record = candidates[0] if len(candidates) == 1 else None
            if record is None:
                record = self.by_alias.get(normalize_location_text(str(target)))
            if record:
                self.by_alias[normalize_location_text(alias)] = record

    @classmethod
    def load(cls, path: Optional[Path] = None, aliases: Optional[dict] = None) -> "LocationCatalog":
        if path is None:
            root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
            path = root / "assets" / "locations.json"
        try:
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            raw = {"locations": []}
        records = []
        for item in raw.get("locations") or []:
            coords = item.get("position_m")
            position = None
            if isinstance(coords, list) and len(coords) == 3:
                try:
                    position = tuple(float(value) for value in coords)
                except (TypeError, ValueError):
                    position = None
            records.append(LocationRecord(
                id=str(item.get("id") or "").strip(), name=str(item.get("name") or "").strip(),
                system=str(item.get("system") or "").strip().title(),
                parent=str(item.get("parent") or "").strip(), type=str(item.get("type") or "").strip(),
                position=position, aliases=tuple(str(value) for value in item.get("aliases") or []),
                qt_valid=bool(item.get("qt_valid")),
            ))
        return cls((record for record in records if record.id and record.name), aliases)

    def with_aliases(self, aliases: dict) -> "LocationCatalog":
        return LocationCatalog(self.records, aliases)

    @lru_cache(maxsize=4096)
    def resolve(self, value: str, system_hint: str = "") -> LocationMatch:
        original = " ".join(str(value or "").split())
        key = normalize_location_text(original)
        if not key or key.startswith("unknown") or key in {"destinationaddress", "pickupaddress"}:
            return LocationMatch(original)
        if key in self.by_qualified:
            return LocationMatch(original, self.by_qualified[key], "qualified")
        if key in self.by_alias:
            return LocationMatch(original, self.by_alias[key], "alias")
        candidates = self.by_name.get(key, [])
        if system_hint and len(candidates) > 1:
            hinted = [record for record in candidates if normalize_location_text(record.system) == normalize_location_text(system_hint)]
            if len(hinted) == 1:
                return LocationMatch(original, hinted[0], "exact")
        if len(candidates) == 1:
            return LocationMatch(original, candidates[0], "exact")
        # Mission text often appends hierarchy: "Ruin Station above Pyro VI".
        contained = [record for record in self.records if normalize_location_text(record.name) and key.startswith(normalize_location_text(record.name))]
        if system_hint:
            contained = [record for record in contained if normalize_location_text(record.system) == normalize_location_text(system_hint)] or contained
        if len(contained) == 1:
            return LocationMatch(original, contained[0], "hierarchy")
        if len(key) >= 6:
            pool = list(self.records)
            if system_hint:
                same_system = [record for record in pool if normalize_location_text(record.system) == normalize_location_text(system_hint)]
                pool = same_system or pool
            scored = sorted(
                ((SequenceMatcher(None, key, normalize_location_text(record.name)).ratio(), record) for record in pool),
                key=lambda item: (item[0], item[1].id), reverse=True,
            )
            if scored and scored[0][0] >= 0.92 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.04):
                return LocationMatch(original, scored[0][1], "fuzzy")
        return LocationMatch(original)

    def suggestions(self) -> list[dict]:
        return [record.payload() for record in sorted(self.records, key=lambda value: (value.name.casefold(), value.system.casefold()))]


class CatalogDistanceProvider:
    """Straight-line same-system distance using game system-space coordinates."""

    def __init__(self, catalog: LocationCatalog):
        self.catalog = catalog

    def distance(self, origin: str, destination: str) -> Optional[float]:
        left = self.catalog.by_id.get(origin)
        right = self.catalog.by_id.get(destination)
        if not left or not right or not left.position or not right.position:
            return None
        if normalize_location_text(left.system) != normalize_location_text(right.system):
            return None
        metres = math.dist(left.position, right.position)
        return round(metres / 1000.0, 1)
