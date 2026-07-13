#!/usr/bin/env python3
"""
SC Hauling Log Tracker 1.5.66
----------------------------
Offline parser/GUI for Star Citizen hauling missions in Game.log.

Reads accepted hauling/cargo contracts and builds a LOAD/OFFLOAD manifest.
Also attempts to detect mission completion/reward lines and track session
profit, elapsed timers, mission profit/hr, and session profit/hr.

No internet connection is required at runtime. Source desktop mode uses pywebview; packaged builds include it.

1.5.66 prepares the first public test release with a wider desktop layout, SCHT AppData migration, a clean Windows installer, and standalone packaging that requires no end-user Python installation.
3.5.66 extends the Help guide navigation rail to the full guide height so its darker background remains visually continuous while the manual scrolls.
3.5.65 replaces the placeholder Help window with an illustrated offline user guide and adds a manual-maintenance contract for future features.
3.5.64 simplifies the primary toolbar with combined watch control, icon-only Share and Settings menus, and reliable desktop/browser exports.
3.5.63 repairs malformed Iron (Ore) labels and consolidates CSV/HTML export into a Share menu with a new Help & Information window.
3.5.62 keeps every right-side Logistics Board location card on the same four-column grid, so shorter route groups no longer stretch their cards.
3.5.61 separates shared-quantity pickup locations, preserves blank per-location SCU values, and reads every visible pickup from aggregate contract screenshots.
3.5.60 supports shared multi-pickup contract quantities in the table, OCR validation, logistics board, and overlay.
3.5.54 fixes live Auto OCR capture on scaled displays by making the capture helper DPI-aware before reading Star Citizen window bounds.
3.5.53 recovers clipped automatic OCR when marker-resolved routes are known and the live capture still reads all SCU quantities in objective order.
3.5.52 lets automatic OCR fall back to a very recent Star Citizen screenshot when the live window capture is clipped or incomplete.
3.5.51 improves OCR canonicalization for wrapped partial facility names such as Sakura Sun Magnolia missing Workcenter.
3.5.50 repairs same-location OCR for known direct routes and records the last failed OCR parse for diagnosis.
3.5.49 restores OCR popup notifications in packaged builds by adding a Windows-native fallback when tkinter is unavailable.
3.5.48 adds recent-contract Auto OCR recovery and surfaces OCR queue/status details in the live feed.
3.5.47 rejects OCR rows that do not match marker-resolved pickups/drop-offs and discards stale invalid OCR overrides on refresh.
3.5.46 prevents incomplete OCR from replacing multi-objective contracts, hardens OCR parsing for O/5-style quantity errors and moon suffixes, adds dedicated reward-value crops, and reports objective coverage honestly.
3.5.45 strengthens automatic and manual contract OCR with targeted reward/objective crops, more tolerant readiness checks, explicit failure diagnostics, longer notifications, and a migrated retry window.
3.5.44 hardens the automatic OCR trigger by detecting the actual live Contract Accepted event directly, adds explicit OCR queue diagnostics, and prevents stale-build confusion with verified versioned packaging.
3.5.43 adds automatic, MissionId-correlated OCR capture after a live hauling-contract acceptance, with non-activating topmost progress notifications, retries, validation, and safe fallback to manual review.
3.5.42 fixes Start from now so it restarts only the session timer and keeps the current contracts, logistics checklist, and live parsing state.
3.5.41 adds breathing room before the status icon and simplifies payout cards to show only AUEC.
3.5.40 compacts the contract table into the available panel width so desktop layouts no longer require horizontal scrolling.
3.5.39 replaces the browser-native delete confirmation with a compact in-app confirmation dialog that matches the SCHT interface.
3.5.38 aligns borderless edit and delete SVG controls on the same line as the contract status label while preserving MissionId-first parsing and compact notifications.
3.5.34 fixes stacked 4.8 hauling-contract parsing by scoping objectives and contract definitions to the current MissionId.
3.5.33 refines dashboard and overlay control labels with sentence case, semibold weight, cleaner spacing, and a Windows-native Segoe UI Variable text stack.
3.5.31 keeps the overlay permanently compact, renames its loaded-item filter, and maximizes the main window inside the Windows work area so the taskbar remains visible.
3.5.30 removes the dashboard layout-preset toolbar and refreshes the Windows app icon with a larger transparent mark.
3.5.29 adds workflow filters, layout presets, first-run guidance, and checklist view controls.
3.5.26 fixes the native Browse dialog file filter.
3.5.25 aligns main control spacing and adds a draggable Contract log splitter.
3.5.24 adds breathing room around the main-window control buttons.
3.5.23 restores overlay movement after lock toggles by using an explicit native move loop.
3.5.22 fixes dashboard refresh, Browse, and main-window movement regressions.
3.5.21 restores main-window movement for the custom frameless title strip.
3.5.20 restores borderless native resizing and simplifies the desktop chrome:
- main and overlay edge handles use a dedicated native SetWindowPos drag loop
- no WndProc subclass, visible sizing frame, or JavaScript mousemove resize calls are used
- the main title strip is visually merged into the app background and contains controls only
- the overlay title logo is removed and the dashboard logo is larger and borderless
- parser/session/export, checklist synchronization, and route-grouping behavior are unchanged
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import difflib
import html
import hashlib
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

APP_NAME = "SC Hauling Log Tracker"
APP_VERSION = "1.5.66"
APP_DATA_FOLDER = "SCHT"
LEGACY_APP_DATA_FOLDERS = ("SC Hauling Log Tracker",)
MAIN_WINDOW_LAYOUT_VERSION = 4
MAIN_WINDOW_DEFAULT_WIDTH = 1460
MAIN_WINDOW_PREFERRED_MIN_WIDTH = 1320
MAIN_WINDOW_HARD_MIN_WIDTH = MAIN_WINDOW_PREFERRED_MIN_WIDTH
MAIN_WINDOW_MIN_HEIGHT = 720

HELP_IMAGE_ASSETS = frozenset({
    "toolbar.jpg",
    "dashboard.jpg",
    "logistics_board.jpg",
    "overlay.jpg",
    "settings_menu.jpg",
    "share_menu.jpg",
    "contract_editor.jpg",
})


COMMODITY_LABEL_ALIASES = {
    # Contract OCR may lose one or both parentheses, while Game.log contract
    # definitions use the canonical player-facing label below.
    "ironore": "Iron (Ore)",
}


def normalize_commodity_name(value: str) -> str:
    """Return a stable player-facing commodity label.

    OCR/manual corrections are allowed to omit punctuation. Normalizing before
    mission keys and UI payloads are built prevents ``Iron (Ore`` from leaking
    into the Contract Log, Logistics Board, overlay, and exports.
    """
    cleaned = html.unescape(str(value or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    compact = re.sub(r"[^a-z0-9]", "", cleaned.lower())
    return COMMODITY_LABEL_ALIASES.get(compact, cleaned)


def bundled_resource_path(*parts: str) -> Path:
    """Resolve source and PyInstaller bundled assets without network access."""
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return root.joinpath(*parts)

RANK_WORDS = ["trainee", "rookie", "junior", "member", "experienced", "senior", "master"]

KNOWN_LOCATION_HINTS = [
    "Everus Harbor", "Teasa Spaceport", "Lorville", "Baijini Point", "Riker Memorial Spaceport",
    "Area18", "Port Tressler", "New Babbage", "Seraphim Station", "Orison", "August Dunlow Spaceport",
    "Grim HEX", "Pyro Gateway", "Stanton Gateway",
    "HDPC-Farnesway", "HDPC-Cassillo", "Sakura Sun Magnolia Workcenter",
    "Covalex Distribution Center S1DC06", "Shubin Mining Facility SMO-10",
    "HDMS-Hahn", "HDMS-Perlman", "HDMS-Bezdek", "HDMS-Lathan",
    "HDMS-Norgaard", "HDMS-Anderson",
    "HUR-L1", "HUR-L2", "HUR-L3", "HUR-L4", "HUR-L5",
    "ARC-L1", "ARC-L2", "ARC-L3", "ARC-L4", "ARC-L5",
    "MIC-L1", "MIC-L2", "MIC-L3", "MIC-L4", "MIC-L5",
    "CRU-L1", "CRU-L2", "CRU-L3", "CRU-L4", "CRU-L5",
]

# Mission objective notifications are not guaranteed for every stacked hauling contract in 4.8.
# Contract-definition names reveal structure and commodity tokens, and marker coordinates reveal
# selected locations, but SCU and payout may remain absent from Game.log. Never reuse a generic
# template for randomized quantities, routes, or rewards: the current MissionId is authoritative.
KNOWN_MARKER_LOCATIONS = [
    ("Everus Harbor", (-507742.312500, -903464.437500, 496489.062500)),
    ("HDPC-Farnesway", (129223.337423, 63887.560398, 989574.572256)),
    ("HDPC-Cassillo", (-789715.940114, 615354.400685, -2353.089599)),
    ("Sakura Sun Magnolia Workcenter", (-229373.108770, -864792.873355, -446960.041887)),
    ("Teasa Spaceport", (-328668.005842, -756979.728559, 566539.556724)),
    ("Covalex Distribution Center S1DC06", (742846.530000, 15480.080000, 671073.620000)),
]

KNOWN_CONTRACTORS = [
    "Covalex Independent Contractors",
    "Covalex Shipping",
]

VERIFIED_MISSION_OVERRIDES = {}

def get_contract_defs(text: str) -> List[str]:
    defs = []
    for m in re.finditer(r"contract \[([^\]]*HaulCargo_[^\]]+)\]", text, re.I):
        val = m.group(1).strip()
        if val and val not in defs:
            defs.append(val)
    return defs


def contract_definition_for(raw: str, mission_id: str = "") -> str:
    defs = get_contract_defs(raw)
    if mission_id:
        same: List[str] = []
        for line in raw.splitlines():
            if mission_id.lower() in line.lower():
                same.extend(get_contract_defs(line))
        defs = same or defs
    return defs[0] if defs else ""


def split_camel_tokens(value: str) -> List[str]:
    value = re.sub(r"([a-z])([A-Z])", r"\1 \2", value or "")
    return [part for part in re.split(r"[\s\-]+", value) if part]


def decode_commodity_token(token: str, family: str = "") -> List[str]:
    """Decode only commodity names explicitly represented in a contract id."""
    token = (token or "").strip()
    family = (family or "").strip().lower()
    aliases = {
        "aluminium": ["Aluminum"],
        "aluminum": ["Aluminum"],
        "agricultural": ["Agricultural Supplies"],
        "medical": ["Medical Supplies"],
        "stims": ["Stims"],
        "stim": ["Stims"],
        "waste": ["Waste"],
        "scrap": ["Scrap"],
        "processedfood": ["Processed Food"],
        "procfood": ["Processed Food"],
        "pressice": ["Pressurized Ice"],
        "pressurizedice": ["Pressurized Ice"],
        "pressiceprocfood": ["Pressurized Ice", "Processed Food"],
        "iron": ["Iron (Ore)"] if family == "rawore" else ["Iron"],
    }
    compact = re.sub(r"[^a-z0-9]", "", token.lower())
    if compact in aliases:
        return aliases[compact]
    words = split_camel_tokens(token.replace("_", " "))
    return [" ".join(words).title()] if words else []


def commodities_from_contract_definition(contract_def: str) -> List[str]:
    """Extract user-facing commodity names from a Covalex hauling definition."""
    parts = [part for part in (contract_def or "").split("_") if part]
    family = ""
    for part in parts:
        if part.lower() in {"processed", "rawore", "refinedore", "nonmetal", "mixed"}:
            family = part
        if part.lower() == "mixed":
            break
    for index, part in enumerate(parts):
        if re.fullmatch(r"Stanton\d+", part, re.I) and index:
            commodities = decode_commodity_token(parts[index - 1], family)
            return commodities or ["Unknown commodity"]
    return ["Unknown commodity"]


def commodity_from_contract_definition(contract_def: str) -> str:
    commodities = commodities_from_contract_definition(contract_def)
    return commodities[0] if commodities else "Unknown commodity"


def contract_route_shape(contract_def: str) -> Tuple[int, int]:
    name = contract_def or ""
    m = re.search(r"HaulCargo_(Single|Multi(?P<from>\d+))To(Single|Multi(?P<to>\d+))", name, re.I)
    if not m:
        return 1, 1
    pickups = int(m.group("from") or "1")
    dropoffs = int(m.group("to") or "1")
    return pickups, dropoffs


def marker_location_for_position(x: float, y: float, z: float, tolerance: float = 5000.0) -> str:
    best_name = ""
    best_distance = None
    for name, (mx, my, mz) in KNOWN_MARKER_LOCATIONS:
        distance = (x - mx) ** 2 + (y - my) ** 2 + (z - mz) ** 2
        if best_distance is None or distance < best_distance:
            best_name, best_distance = name, distance
    if best_distance is not None and best_distance <= tolerance ** 2:
        return best_name
    return ""


def parse_objective_markers(text: str, mission_id: str = "") -> List["ObjectiveMarker"]:
    """Parse mission markers, scoped by MissionId and resolved by coordinates."""
    pattern = re.compile(
        r"missionId\s*\[(?P<mission>[^\]]+)\].*?contract\s*\[(?P<contract>[^\]]*HaulCargo_[^\]]+)\].*?"
        r"objectiveId\s*\[(?P<objective>(?P<kind>pickup|dropoff)_[^\]]+)\].*?position\s*\[x:\s*(?P<x>-?\d+(?:\.\d+)?),\s*"
        r"y:\s*(?P<y>-?\d+(?:\.\d+)?),\s*z:\s*(?P<z>-?\d+(?:\.\d+)?)\]",
        re.I,
    )
    wanted = (mission_id or "").strip().lower()
    markers: List[ObjectiveMarker] = []
    seen = set()
    for line in text.splitlines():
        match = pattern.search(line)
        if not match:
            continue
        marker_mission_id = match.group("mission").strip()
        if wanted and marker_mission_id.lower() != wanted:
            continue
        location = marker_location_for_position(float(match.group("x")), float(match.group("y")), float(match.group("z")))
        objective_id = match.group("objective").strip()
        key = (marker_mission_id.lower(), objective_id.lower(), location)
        if not location or key in seen:
            continue
        seen.add(key)
        markers.append(ObjectiveMarker(
            mission_id=marker_mission_id,
            objective_id=objective_id,
            kind=match.group("kind").lower(),
            location=location,
            contract_def=match.group("contract").strip(),
            x=float(match.group("x")),
            y=float(match.group("y")),
            z=float(match.group("z")),
        ))
    return markers


def parse_marker_objectives(text: str, contract_def: str = "", mission_id: str = "") -> List["ParsedObjective"]:
    """Infer contract-token commodities and marker-resolved routes for one MissionId.

    Marker fallback never supplies SCU or payout. It only exposes structure that is
    present in the current mission's marker records.
    """
    markers = parse_objective_markers(text, mission_id)
    commodities = commodities_from_contract_definition(contract_def)
    pickups = [m for m in markers if m.kind == "pickup"]
    dropoffs = [m for m in markers if m.kind == "dropoff"]
    shape_pickups, shape_dropoffs = contract_route_shape(contract_def)
    if not pickups and shape_pickups == 1:
        route_pickup, _drop, _conf = get_route(text)
        if route_pickup and route_pickup != "Unknown pickup":
            pickups = [ObjectiveMarker(mission_id, "pickup_from_title", "pickup", route_pickup, contract_def)]
    if not dropoffs:
        return []

    out: List[ParsedObjective] = []
    if len(pickups) <= 1:
        pickup_location = pickups[0].location if pickups else "Unknown pickup"
        for drop_marker in dropoffs:
            for commodity in commodities:
                out.append(ParsedObjective(
                    commodity=commodity,
                    scu="",
                    dropoff=drop_marker.location,
                    confidence=30,
                    pickup=pickup_location,
                    mission_id=mission_id,
                    objective_id=drop_marker.objective_id,
                    provenance="marker_resolved",
                    quantity_scope="unknown",
                ))
        return out

    if len(dropoffs) == 1:
        drop_location = dropoffs[0].location
        for pickup_marker in pickups:
            for commodity in commodities:
                out.append(ParsedObjective(
                    commodity=commodity,
                    scu="",
                    dropoff=drop_location,
                    confidence=30,
                    pickup=pickup_marker.location,
                    mission_id=mission_id,
                    objective_id=pickup_marker.objective_id,
                    provenance="marker_resolved",
                    quantity_scope="unknown",
                ))
        return out

    for drop_marker in dropoffs:
        for commodity in commodities:
            out.append(ParsedObjective(
                commodity=commodity,
                scu="",
                dropoff=drop_marker.location,
                confidence=25,
                pickup=pickups[0].location if pickups else "",
                mission_id=mission_id,
                objective_id=drop_marker.objective_id,
                provenance="marker_resolved",
                quantity_scope="unknown",
            ))
    return out


def strip_markup(s: str) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", s).strip()


def clean(s: str, max_words: int = 12) -> str:
    s = strip_markup(s)
    s = re.sub(r"^[\s\"'\[\]{}()]+|[\s\"'\[\]{}(),.;:]+$", "", s)
    s = re.sub(r"\s*\[[^\]]+\]\s*$", "", s)  # remove [BP], [9], etc.
    s = re.sub(r"\b(?:New Objective|MissionId|ObjectiveId).*$", "", s, flags=re.I)
    words = s.split()
    if len(words) > max_words:
        s = " ".join(words[:max_words])
    return s.strip(" ,.;:-")


def extract_timestamp(line: str) -> str:
    m = re.search(r"<([^>]{8,80})>", line)
    return m.group(1) if m else ""


def parse_money_amount(text: str) -> Optional[int]:
    """Best-effort aUEC/UEC reward parser.

    This intentionally requires a money-like keyword or aUEC/UEC marker to avoid
    treating mission SCU, timestamps, IDs, etc. as income.
    """
    p = strip_markup(text)
    patterns = [
        r"(?P<amt>[+-]?\d{1,3}(?:[,\s]\d{3})+|[+-]?\d+)\s*(?:aUEC|UEC|credits?)\b",
        r"\b(?:reward|payout|payment|paid|awarded|award|earned|credited|credit|profit)\D{0,50}(?P<amt>[+-]?\d{1,3}(?:[,\s]\d{3})+|[+-]?\d+)\b",
        r"\b(?P<amt>[+-]?\d{1,3}(?:[,\s]\d{3})+|[+-]?\d+)\D{0,30}(?:reward|payout|payment|paid|awarded|earned|credited)\b",
    ]
    for pat in patterns:
        m = re.search(pat, p, re.I)
        if not m:
            continue
        raw = m.group("amt")
        sign = -1 if raw.strip().startswith("-") else 1
        digits = re.sub(r"\D", "", raw)
        if not digits:
            continue
        value = int(digits) * sign
        # Mission payouts should not be tiny one-digit UI counters or absurd values.
        if abs(value) >= 100:
            return value
    return None


def format_auec(value: Optional[int]) -> str:
    if value is None:
        return ""
    return f"{value:,}"


def parse_log_timestamp_to_epoch(value: str) -> Optional[float]:
    """Parse SC ISO-ish timestamps like 2026-07-10T08:16:09.567Z to epoch seconds.

    Returns None if the timestamp is absent or not parseable.
    """
    value = (value or "").strip()
    if not value:
        return None
    # Many SC log timestamps are UTC with a trailing Z. Python wants +00:00.
    iso = value.replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(iso)
        if d.tzinfo is None:
            # Treat naive log timestamps as local time. This is only used for durations,
            # so consistent local timestamps are still useful.
            return d.timestamp()
        return d.timestamp()
    except Exception:
        return None


def format_duration(seconds: float) -> str:
    seconds = max(0, int(seconds or 0))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def normalize_contract_title(value: str) -> str:
    """Normalize visible mission titles enough for duplicate/stat grouping.

    Keeps the meaningful contract name, but removes volatile UI markers such as [BP]
    and collapses whitespace/markup. This is intentionally conservative: it does
    not try to merge different ranks/routes.
    """
    v = clean(value or "", max_words=24).lower()
    v = re.sub(r"\s*\[[^\]]+\]\s*$", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v


@dataclass
class CompletionEvent:
    mission_id: str = ""
    title: str = ""
    amount_auec: Optional[int] = None
    timestamp: str = ""
    raw: str = ""
    source_line: int = 0
    confidence: int = 0
    is_completion: bool = False
    is_abandoned: bool = False

    def key(self) -> Tuple[str, ...]:
        kind = "abandoned" if self.is_abandoned else ("completed" if self.is_completion else "reward")
        if self.mission_id:
            return ("id", self.mission_id.lower(), kind, str(self.amount_auec or ""))
        return ("visible", self.title.lower(), kind, str(self.amount_auec or ""), self.timestamp)


@dataclass
class ParsedObjective:
    commodity: str
    scu: str
    dropoff: str
    confidence: int
    pickup: str = ""
    mission_id: str = ""
    objective_id: str = ""
    provenance: str = "unknown"
    quantity_scope: str = "per_route"

    def __post_init__(self) -> None:
        self.commodity = normalize_commodity_name(self.commodity)


@dataclass
class ObjectiveMarker:
    mission_id: str
    objective_id: str
    kind: str
    location: str
    contract_def: str = ""
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class CargoMission:
    title: str
    rank: str
    pickup: str
    dropoff: str
    commodity: str
    scu: str
    container: str = ""
    confidence: int = 0
    notes: str = ""
    raw: str = ""
    mission_id: str = ""
    timestamp: str = ""
    source_line: int = 0
    contract_uid: str = ""
    status: str = "ACCEPTED"
    payout_auec: Optional[int] = None
    completed_timestamp: str = ""
    objective_id: str = ""
    contracted_by: str = ""
    data_provenance: str = "unknown"
    scu_provenance: str = "unknown"
    payout_provenance: str = "unknown"
    quantity_scope: str = "per_route"

    def __post_init__(self) -> None:
        self.commodity = normalize_commodity_name(self.commodity)

    def stable_key(self) -> Tuple[str, ...]:
        # Stable row key. MissionId is ideal; otherwise use the accepted-contract UID
        # plus objective details so two identical-looking contracts accepted at
        # different times do not collapse into one another.
        if self.mission_id:
            objective_part = self.objective_id.lower() if self.objective_id else "|".join([
                self.pickup.lower(), self.dropoff.lower(), self.commodity.lower(), self.scu
            ])
            return ("idobj", self.mission_id.lower(), objective_part, self.pickup.lower(), self.dropoff.lower(), self.commodity.lower(), self.scu)
        if self.contract_uid:
            return ("uidobj", self.contract_uid.lower(), self.pickup.lower(), self.dropoff.lower(), self.commodity.lower(), self.scu)
        return ("visible", self.title.lower(), self.pickup.lower(), self.dropoff.lower(), self.commodity.lower(), self.scu, str(self.source_line))

    def merge_key(self) -> Tuple[str, ...]:
        # Merge exact duplicate objective rows only. Older versions merged by route,
        # which destroyed multi-drop missions and identical stacked contracts.
        return self.stable_key()

    def route_key(self) -> Tuple[str, ...]:
        return ("route", self.title.lower(), self.rank.lower(), self.pickup.lower(), self.dropoff.lower())

    def contract_key(self) -> Tuple[str, ...]:
        """Key for counting/settling one accepted contract once.

        A multi-drop contract creates several CargoMission objective rows, but it
        must count as exactly one accepted mission, one completion, and one payout.
        MissionId is ideal. If the log omits it, use the visible title + rank +
        pickup + accepted timestamp/source line, so multiple objectives from the
        same accepted block group together while later identical contracts remain
        separate.
        """
        if self.mission_id:
            return ("id", self.mission_id.lower())
        if self.contract_uid:
            return ("uid", self.contract_uid.lower())
        accepted_marker = self.timestamp or str(self.source_line or "")
        return (
            "visible",
            normalize_contract_title(self.title),
            self.rank.lower(),
            self.pickup.lower(),
            accepted_marker,
        )

    def title_key(self) -> str:
        return normalize_contract_title(self.title)

    def is_placeholder(self) -> bool:
        if self.quantity_scope == "aggregate" and self.commodity and self.commodity.lower() != "unknown commodity":
            return False
        return not self.scu or not self.commodity or self.commodity.lower() == "unknown commodity"

    def has_known_scu(self) -> bool:
        return bool(str(self.scu or "").strip() and re.fullmatch(r"\d+(?:\.\d+)?", str(self.scu).strip()))

    def is_load_plannable(self) -> bool:
        return self.has_known_scu() and self.quantity_scope == "per_route" and self.scu_provenance in ("exact_log", "manual", "ocr")

    def is_aggregate_load_plannable(self) -> bool:
        """True for the one row that owns a shared multi-pickup quantity."""
        return self.has_known_scu() and self.quantity_scope == "aggregate" and self.scu_provenance in ("exact_log", "manual", "ocr")

    def score(self) -> Tuple[int, int, int, int, int]:
        known = 1 if self.commodity and self.commodity.lower() != "unknown commodity" else 0
        has_scu = 1 if self.scu else 0
        completed = 1 if self.status.upper() == "COMPLETED" else 0
        paid = 1 if self.payout_auec is not None else 0
        return (completed, paid, known, has_scu, self.confidence)

    def merge_runtime_fields_from(self, other: "CargoMission") -> None:
        """Keep completion/payment info when replacing duplicate/placeholder mission rows."""
        if other.status.upper() == "ABANDONED" and self.status.upper() != "ABANDONED":
            self.status = other.status
            self.completed_timestamp = other.completed_timestamp
        if other.status.upper() == "COMPLETED" and self.status.upper() not in ("COMPLETED", "ABANDONED"):
            self.status = other.status
            self.completed_timestamp = other.completed_timestamp
        if self.payout_auec is None and other.payout_auec is not None:
            self.payout_auec = other.payout_auec
        if not self.contracted_by and other.contracted_by:
            self.contracted_by = other.contracted_by
        if not self.completed_timestamp and other.completed_timestamp:
            self.completed_timestamp = other.completed_timestamp

    def accepted_epoch(self) -> Optional[float]:
        return parse_log_timestamp_to_epoch(self.timestamp)

    def completed_epoch(self) -> Optional[float]:
        return parse_log_timestamp_to_epoch(self.completed_timestamp)

    def elapsed_seconds(self, now_epoch: Optional[float] = None) -> Optional[float]:
        start = self.accepted_epoch()
        if start is None:
            return None
        end = self.completed_epoch() if self.status.upper() in ("COMPLETED", "ABANDONED") else None
        if end is None:
            end = now_epoch if now_epoch is not None else time.time()
        return max(0.0, end - start)

    def elapsed_label(self, now_epoch: Optional[float] = None) -> str:
        elapsed = self.elapsed_seconds(now_epoch)
        return format_duration(elapsed) if elapsed is not None else ""

    def rows(self) -> List[dict]:
        """Return one operational objective row.

        Older versions expanded each objective into LOAD and OFFLOAD rows, which
        made multi-drop contracts noisy and also caused stat confusion. From v0.9
        each cargo objective is a single row: pickup -> drop-off.
        """
        return [{
            "Status": self.status,
            "Pick up location": self.pickup,
            "Drop off location": self.dropoff,
            "Commodity": self.commodity,
            "SCU": self.scu if self.scu else "Unknown",
            "Payout": format_auec(self.payout_auec) if self.payout_auec is not None else "Unknown",
            "Duration": self.elapsed_label(),
            "Rank": self.rank,
            "Confidence": self.confidence,
            "Notes": self.notes,
            "Mission": self.title,
            "Accepted At": self.timestamp,
            "Completed At": self.completed_timestamp,
        }]


def normalize_contract_overrides(payload: Optional[dict]) -> dict:
    normalized = {}
    for mission_id, raw in (payload or {}).items():
        mission_id = str(mission_id or "").strip().lower()
        if not mission_id or not isinstance(raw, dict):
            continue
        payout = raw.get("payout")
        try:
            payout = int(str(payout).replace(",", "")) if str(payout or "").strip() else None
        except Exception:
            payout = None
        contracted_by = clean(str(raw.get("contracted_by") or ""), 8)
        source = str(raw.get("source") or "manual").strip().lower()
        if source not in {"manual", "ocr"}:
            source = "manual"
        objectives = []
        for item in raw.get("objectives") or []:
            if isinstance(item, dict):
                pickup = clean(str(item.get("pickup") or "Everus Harbor"), 12)
                dropoff = clean(str(item.get("dropoff") or ""), 14)
                commodity = clean(str(item.get("commodity") or ""), 8)
                scu = clean(str(item.get("scu") or ""), 3)
            elif isinstance(item, (list, tuple)) and len(item) >= 4:
                pickup, dropoff, commodity, scu = item[:4]
                pickup = clean(str(pickup), 12)
                dropoff = clean(str(dropoff), 14)
                commodity = clean(str(commodity), 8)
                scu = clean(str(scu), 3)
            else:
                continue
            if not pickup or not dropoff or not commodity:
                continue
            if scu and not re.fullmatch(r"\d+(?:\.\d+)?", scu):
                continue
            provenance = str(item.get("provenance") or source).strip().lower() if isinstance(item, dict) else source
            if provenance not in {"manual", "ocr", "exact_log"}:
                provenance = source
            quantity_scope = str(item.get("quantity_scope") or "per_route").strip().lower() if isinstance(item, dict) else "per_route"
            if quantity_scope not in {"per_route", "aggregate"}:
                quantity_scope = "per_route"
            objectives.append({
                "pickup": pickup,
                "dropoff": dropoff,
                "commodity": commodity,
                "scu": scu,
                "provenance": provenance,
                "quantity_scope": quantity_scope,
            })

        # The editor can represent a shared quantity without exposing a separate
        # scope control: several pickup rows with the same commodity/drop-off,
        # exactly one known total, and blank SCU on the remaining rows. Preserve
        # that intent for manually added rows as well as OCR-populated rows.
        objective_groups: dict[Tuple[str, str], List[dict]] = {}
        for objective in objectives:
            objective_groups.setdefault((
                ocr_compact(objective.get("dropoff") or ""),
                ocr_compact(objective.get("commodity") or ""),
            ), []).append(objective)
        for objective_group in objective_groups.values():
            distinct_pickups = {
                ocr_compact(objective.get("pickup") or "")
                for objective in objective_group
                if objective.get("pickup")
            }
            known_quantity_count = sum(1 for objective in objective_group if objective.get("scu"))
            explicit_aggregate = any(objective.get("quantity_scope") == "aggregate" for objective in objective_group)
            if len(objective_group) > 1 and len(distinct_pickups) > 1 and (explicit_aggregate or known_quantity_count == 1):
                for objective in objective_group:
                    objective["quantity_scope"] = "aggregate"
        if objectives or payout is not None or contracted_by:
            normalized[mission_id] = {"payout": payout, "objectives": objectives, "source": source}
            if contracted_by:
                normalized[mission_id]["contracted_by"] = contracted_by
    return normalized


def merged_contract_overrides(user_overrides: Optional[dict] = None) -> dict:
    # Built-in screenshot/template values are intentionally not merged here.
    # Only explicit user corrections should override parser output.
    return normalize_contract_overrides(user_overrides)


def apply_contract_overrides(missions: Sequence[CargoMission], overrides: Optional[dict] = None) -> List[CargoMission]:
    """Replace one mission group's rows with exact per-MissionId details.

    This is intentionally MissionId-specific. Contract definitions are procedural and
    cannot safely provide SCU/payout values for a different mission instance.
    """
    normalized = normalize_contract_overrides(overrides)
    if not missions or not normalized:
        return list(missions)
    groups = contract_groups(missions)
    output: List[CargoMission] = []
    for group in groups:
        first = group[0]
        override = normalized.get((first.mission_id or "").lower())
        if not override:
            output.extend(group)
            continue
        payout = override.get("payout")
        source = str(override.get("source") or "manual").lower()
        contracted_by = override.get("contracted_by") or first.contracted_by
        objective_rows = override.get("objectives") or []
        if not objective_rows:
            for mission in group:
                mission.payout_auec = payout if payout is not None else mission.payout_auec
                if payout is not None:
                    mission.payout_provenance = source
                if contracted_by:
                    mission.contracted_by = contracted_by
            output.extend(group)
            continue
        for item in objective_rows:
            provenance = str(item.get("provenance") or source).lower()
            if provenance not in {"manual", "ocr", "exact_log"}:
                provenance = source
            row = replace(
                first,
                pickup=item["pickup"],
                dropoff=item["dropoff"],
                commodity=item["commodity"],
                scu=item["scu"],
                payout_auec=payout if payout is not None else first.payout_auec,
                contracted_by=contracted_by,
                confidence=100 if source == "manual" else 92,
                notes="Manual per-MissionId correction" if source == "manual" else "Automatic OCR capture",
                data_provenance=provenance,
                scu_provenance=provenance if item["scu"] else "unknown",
                payout_provenance=source if payout is not None else first.payout_provenance,
                quantity_scope=str(item.get("quantity_scope") or "per_route"),
            )
            output.append(row)
    return merge_missions(output)


def known_location_names(extra: Optional[Sequence[str]] = None) -> List[str]:
    out: List[str] = []
    for loc in KNOWN_LOCATION_HINTS + [name for name, _coords in KNOWN_MARKER_LOCATIONS] + list(extra or []):
        loc = clean(str(loc or ""), 16)
        if loc and loc not in out and not loc.lower().startswith("unknown"):
            out.append(loc)
    return sorted(out, key=len, reverse=True)


def known_commodity_names(extra: Optional[Sequence[str]] = None) -> List[str]:
    base = [
        "Hydrogen", "Quartz", "Stims", "Silicon", "Carbon", "Aluminum", "Aluminium",
        "Corundum", "Tin", "Titanium", "Tungsten", "Copper", "Iron (Ore)", "Iron",
        "Waste", "Scrap", "Beryl", "Agricium", "Gold", "Diamond", "Processed Food",
        "Pressurized Ice", "Distilled Spirits", "Medical Supplies", "Agricultural Supplies",
    ]
    out: List[str] = []
    for commodity in base + list(extra or []):
        commodity = strip_markup(str(commodity or ""))
        commodity = re.sub(r"^[\s\"'\[\]{}]+|[\s\"'\[\]{},.;:]+$", "", commodity)
        words = commodity.split()
        if len(words) > 8:
            commodity = " ".join(words[:8])
        commodity = commodity.strip(" ,.;:-")
        if commodity and commodity not in out and commodity.lower() != "unknown commodity":
            out.append(commodity)
    return sorted(out, key=len, reverse=True)


def ocr_compact(value: str) -> str:
    value = html.unescape(value or "").lower()
    value = value.translate(str.maketrans({"1": "i", "l": "i", "|": "i"}))
    return re.sub(r"[^a-z0-9]", "", value)


def canonical_ocr_name(value: str, names: Sequence[str]) -> str:
    cleaned = clean(value, 16)
    compact = ocr_compact(cleaned)
    leading_compact = ocr_compact(" ".join(cleaned.split()[:6]))
    for name in names:
        words = [part for part in re.split(r"\s+", name.strip()) if part]
        if len(words) < 3:
            continue
        prefixes = [" ".join(words[:-1])]
        if len(words) >= 4:
            prefixes.append(" ".join(words[:3]))
        for prefix in prefixes:
            prefix_compact = ocr_compact(prefix)
            if len(prefix_compact) >= 10 and (
                leading_compact.startswith(prefix_compact)
                or compact.startswith(prefix_compact)
            ):
                return name
    for name in names:
        name_compact = ocr_compact(name)
        if name_compact and (name_compact in compact or compact in name_compact):
            return name
    for name in names:
        if name.lower() in cleaned.lower():
            return name
    # Permit one or two OCR substitutions in a controlled known-name list, but
    # never fuzzy-match very short tokens because that can turn an unknown route
    # into a plausible-looking wrong destination.
    if len(compact) >= 7:
        best_name = ""
        best_ratio = 0.0
        for name in names:
            name_compact = ocr_compact(name)
            if len(name_compact) < 7:
                continue
            ratio = difflib.SequenceMatcher(None, compact, name_compact).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_name = name
        if best_ratio >= 0.84:
            return best_name
    return cleaned


def _ocr_scu_value(token: str) -> Optional[str]:
    token = str(token or "").translate(str.maketrans({
        "O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "s": "5",
    }))
    digits = re.sub(r"\D", "", token)
    if not digits:
        return None
    value = int(digits)
    if value < 0 or value > 9999:
        return None
    return str(value)


def _clean_ocr_location_candidate(value: str, names: Sequence[str]) -> str:
    value = html.unescape(str(value or ""))
    value = re.split(r"(?i)\b(?:Collect|Deliver|SHARE|TRACK|HOME|HEALTH|COMMS|CONTRACTS)\b", value, maxsplit=1)[0]
    value = re.sub(r"^[^A-Za-z0-9]+", "", value)
    value = re.sub(
        r"(?i)\s+(?:on|in|above)\s+(?:Hurston|Aberdeen|Magda|Arial|Daymar|Wala|Lyria|microTech|ArcCorp|Crusader|Lorville)\b.*$",
        "",
        value,
    )
    value = re.sub(r"(?i)\s+[Oo0◇◆•]+\s*$", "", value)
    value = re.sub(r"[\s\.,;:]+$", "", value)
    value = clean(value, 16)
    return canonical_ocr_name(value, names) if value else ""


def _clean_ocr_commodity_candidate(value: str, names: Sequence[str]) -> str:
    value = html.unescape(str(value or ""))
    value = re.split(r"(?i)\b(?:to|Collect|Deliver|SHARE|TRACK)\b", value, maxsplit=1)[0]
    value = re.sub(r"^[^A-Za-z0-9]+", "", value)
    value = re.sub(r"[\s\.,;:]+$", "", value)
    value = clean(value, 8)
    return canonical_ocr_name(value, names) if value else ""

def primary_objectives_section(raw: str) -> str:
    m = re.search(r"\bPRIMARY\s+OBJECTIVES\b", raw, re.I)
    if not m:
        return raw
    section = raw[m.end():]
    end = re.search(r"\b(?:SHARE|TRACK|HOME|HEALTH|COMMS|CONTRACTS|MAPS|JOURNAL|REP|WALLET|LANDING|VEHICLES)\b", section, re.I)
    return section[:end.start()] if end else section


def _ocr_amount_value(token: str) -> Optional[int]:
    """Normalize a payout token commonly distorted by game-screen OCR."""
    token = str(token or "").translate(str.maketrans({
        "O": "0", "o": "0", "I": "1", "l": "1", "|": "1", "S": "5", "s": "5", "B": "8",
    }))
    digits = re.sub(r"\D", "", token)
    if not digits:
        return None
    value = int(digits)
    return value if 100 <= value <= 100_000_000 else None


def parse_reward_amount(raw: str) -> Optional[int]:
    raw = html.unescape(raw or "")
    candidate_pattern = re.compile(
        r"(?P<amt>[+-]?[0-9OoIlSsB]{1,3}(?:[,\.\s][0-9OoIlSsB]{3})+|[+-]?[0-9OoIlSsB]{4,8})"
    )
    reward = re.search(r"\bReward\b", raw, re.I)
    windows: List[str] = []
    if reward:
        windows.append(raw[reward.start():reward.start() + 900])
    # Targeted reward crops are prefixed with Reward by the caller. If OCR omitted
    # the label, still permit a short crop to be interpreted as a payout panel.
    if len(raw) <= 500:
        windows.append(raw)
    for window in windows:
        for match in candidate_pattern.finditer(window):
            value = _ocr_amount_value(match.group("amt"))
            if value is not None and value >= 1000:
                return value
    return parse_money_amount(raw)

def parse_contracted_by(raw: str) -> str:
    compact = ocr_compact(raw)
    for name in KNOWN_CONTRACTORS:
        name_compact = ocr_compact(name)
        if name.lower() in raw.lower() or (name_compact and name_compact in compact):
            return name
    m = re.search(r"\bContracted\s+By\b(?P<tail>.{0,160})", raw, re.I | re.S)
    if not m:
        return ""
    tail = re.sub(r"(?i)\b(?:Reward|Contract Deadline|N/?A)\b", " ", m.group("tail"))
    tail = re.sub(r"[^\w\s&.'-]+", " ", tail)
    tail = re.sub(r"\b\d[\dkm,.\s]*\b", " ", tail, flags=re.I)
    tail = clean(tail, 8)
    return tail if len(tail.split()) >= 2 else ""


def parse_primary_objective_rows(section: str, locations: Sequence[str], commodities: Sequence[str], hints: Sequence[dict]) -> List[dict]:
    """Parse every visible Deliver objective independently.

    Windows OCR commonly emits ``O/5`` or ``0/S`` and flattens multiple bullets
    into one line. Segmenting on each Deliver anchor prevents the first route from
    swallowing the second route and keeps destination names attached to the right
    quantity.
    """
    rows: List[dict] = []
    seen = set()
    raw = html.unescape(section or "")
    anchors = list(re.finditer(r"(?i)\bDeliver\b", raw))
    hint_pickups = [str(h.get("pickup") or "") for h in hints if isinstance(h, dict)]
    single_hint_pickup = next((p for p in hint_pickups if p), "") if len({ocr_compact(p) for p in hint_pickups if p and not p.lower().startswith("unknown")}) == 1 else ""
    objective_pat = re.compile(
        r"(?i)\bDeliver\s+"
        r"(?:(?:[0OoIl|]+)\s*/\s*)?"
        r"(?P<scu>[0-9OoIl|Ss]{1,4})\s*(?:SCU|5CU|S\.?C\.?U\.?)\s+of\s+"
        r"(?P<commodity>.+?)\s+to\s+(?P<drop>.+?)"
        r"(?=(?:[\.\r\n]\s*)?(?:[Oo0◇◆\-•]\s*)?\bCollect\b|\bDeliver\b|\bSHARE\b|\bTRACK\b|$)",
        re.S,
    )
    for index, anchor in enumerate(anchors):
        end = anchors[index + 1].start() if index + 1 < len(anchors) else len(raw)
        segment = raw[anchor.start():end]
        match = objective_pat.search(segment)
        if not match:
            continue
        scu = _ocr_scu_value(match.group("scu"))
        if scu is None:
            continue
        commodity = _clean_ocr_commodity_candidate(match.group("commodity"), commodities)
        dropoff = _clean_ocr_location_candidate(match.group("drop"), locations)
        pickup_candidates: List[str] = []
        for collect in re.finditer(
            r"(?i)\bCollect\s+.+?\s+from\s+(?P<pickup>.+?)(?=(?:[\.\r\n]|\bDeliver\b|\bSHARE\b|\bTRACK\b|$))",
            segment,
            re.S,
        ):
            pickup = _clean_ocr_location_candidate(collect.group("pickup"), locations)
            pickup_key = ocr_compact(pickup)
            if pickup and pickup_key and pickup_key not in {ocr_compact(value) for value in pickup_candidates}:
                pickup_candidates.append(pickup)
        if not pickup_candidates and single_hint_pickup:
            pickup_candidates.append(single_hint_pickup)
        if not pickup_candidates:
            pickup_candidates.append("")

        # One Deliver objective followed by several Collect bullets is a shared
        # contract quantity. Keep the total on the first route row only while
        # preserving every visible pickup location for the table and checklist.
        aggregate_pickups = len(pickup_candidates) > 1
        for pickup_index, pickup in enumerate(pickup_candidates):
            row_scu = scu if not aggregate_pickups or pickup_index == 0 else ""
            key = (ocr_compact(pickup), ocr_compact(dropoff), ocr_compact(commodity), row_scu)
            if not dropoff or not commodity or key in seen:
                continue
            seen.add(key)
            row = {
                "pickup": pickup or "Everus Harbor",
                "dropoff": dropoff,
                "commodity": commodity,
                "scu": row_scu,
            }
            if aggregate_pickups:
                row["quantity_scope"] = "aggregate"
            rows.append(row)
    return rows


def _hint_objective_order_key(index_hint: Tuple[int, dict]) -> Tuple[int, int]:
    index, hint = index_hint
    objective_id = str((hint or {}).get("objective_id") or "")
    match = re.search(r"_(\d+)$", objective_id)
    if match:
        return (0, int(match.group(1)))
    return (1, index)


def marker_hint_rows_from_amounts(hints: Sequence[dict], amounts: Sequence[str]) -> List[dict]:
    """Map visible SCU quantities onto marker-resolved routes in objective order."""
    clean_amounts = [str(value) for value in amounts if value is not None and str(value) != ""]
    if not hints or not clean_amounts:
        return []
    usable_hints = [
        h for h in hints
        if isinstance(h, dict)
        and h.get("dropoff") and h.get("commodity")
        and not str(h.get("dropoff")).lower().startswith("unknown")
        and not str(h.get("commodity")).lower().startswith("unknown")
        and ocr_compact(str(h.get("pickup") or "")) != ocr_compact(str(h.get("dropoff") or ""))
    ]
    if len(usable_hints) != len(clean_amounts):
        return []
    pickups = {ocr_compact(str(h.get("pickup") or "")) for h in usable_hints if h.get("pickup")}
    pickups.discard("")
    if len(pickups) > 1:
        return []
    objective_ids = [str(h.get("objective_id") or "").lower() for h in usable_hints if h.get("objective_id")]
    if objective_ids and not all(value.startswith("dropoff") for value in objective_ids):
        return []
    ordered_hints = [hint for _, hint in sorted(enumerate(usable_hints), key=_hint_objective_order_key)]
    rows: List[dict] = []
    for hint, scu in zip(ordered_hints, clean_amounts):
        rows.append({
            "pickup": clean(str(hint.get("pickup") or "Everus Harbor"), 12),
            "dropoff": clean(str(hint.get("dropoff") or ""), 14),
            "commodity": clean(str(hint.get("commodity") or ""), 8),
            "scu": clean(str(scu), 3),
        })
    return rows


def parse_contract_details_text(text: str, hints: Optional[Sequence[dict]] = None) -> dict:
    """Parse OCR/pasted contract text into editable correction fields.

    This is deliberately conservative: it returns candidate rows for user review,
    not authoritative parser output.
    """
    raw = html.unescape(text or "")
    raw = re.sub(r"<[^>]+>", "", raw)
    raw = re.sub(r"[ \t]+", " ", raw).strip()
    raw = raw.replace("->", " -> ").replace("→", " -> ").replace("—", "-")
    hints = list(hints or [])
    hint_pickups = [str(h.get("pickup") or "") for h in hints if isinstance(h, dict)]
    hint_dropoffs = [str(h.get("dropoff") or "") for h in hints if isinstance(h, dict)]
    hint_commodities = [str(h.get("commodity") or "") for h in hints if isinstance(h, dict)]
    locations = known_location_names([*hint_pickups, *hint_dropoffs])
    commodities = known_commodity_names(hint_commodities)
    payout = parse_reward_amount(raw)
    contracted_by = parse_contracted_by(raw)
    objective_text = primary_objectives_section(raw)

    def find_name(line: str, names: Sequence[str]) -> str:
        compact_line = re.sub(r"\s+", " ", line).lower()
        for name in names:
            if name.lower() in compact_line:
                return name
        compact = ocr_compact(line)
        for name in names:
            name_compact = ocr_compact(name)
            if name_compact and name_compact in compact:
                return name
        return ""

    rows: List[dict] = parse_primary_objective_rows(objective_text, locations, commodities, hints)
    seen = set()
    lines = [ln.strip() for ln in re.split(r"[\r\n]+", objective_text) if ln.strip()]
    amount_pat = re.compile(r"\b(?P<scu>\d+(?:\.\d+)?)\s*(?:SCU|5CU|S\.?C\.?U\.?)\b", re.I)
    deliver_amount_pat = re.compile(
        r"(?i)\bDeliver\s+(?:(?:[0OoIl|]+)\s*/\s*)?"
        r"(?P<scu>[0-9OoIl|Ss]{1,4})\s*(?:SCU|5CU|S\.?C\.?U\.?)\b"
    )
    for row in rows:
        seen.add((row.get("pickup", "").lower(), row.get("dropoff", "").lower(), row.get("commodity", "").lower(), row.get("scu", "")))
    for line in (lines if not rows else []):
        amount = amount_pat.search(line)
        if not amount:
            continue
        scu = amount.group("scu")
        commodity = find_name(line, commodities)
        line_locations = [loc for loc in locations if loc.lower() in line.lower()]
        dropoff = line_locations[-1] if line_locations else ""
        pickup = line_locations[0] if len(line_locations) > 1 else ""
        if not pickup and len(set(hint_pickups)) == 1:
            pickup = next((p for p in hint_pickups if p), "")
        if not commodity and len(set(c for c in hint_commodities if c and c.lower() != "unknown commodity")) == 1:
            commodity = next((c for c in hint_commodities if c and c.lower() != "unknown commodity"), "")
        if not dropoff or not commodity:
            continue
        key = (pickup.lower(), dropoff.lower(), commodity.lower(), scu)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "pickup": pickup or "Everus Harbor",
            "dropoff": dropoff,
            "commodity": commodity,
            "scu": scu,
        })

    # If OCR saw every Deliver quantity but clipped route names, map quantities
    # onto marker-resolved routes in objective order. This is intentionally only
    # allowed when the counts match exactly.
    if hints:
        raw_deliver_amounts = [m.group("scu") for m in deliver_amount_pat.finditer(objective_text)]
        deliver_amounts = [value for value in (_ocr_scu_value(token) for token in raw_deliver_amounts) if value is not None]
        mapped_rows = marker_hint_rows_from_amounts(hints, deliver_amounts)
        if mapped_rows and len(rows) < len(mapped_rows):
            rows = mapped_rows

    # Plain pasted quantities without Deliver anchors can still fill known rows.
    if not rows and hints:
        raw_amounts = [m.group("scu") for m in amount_pat.finditer(objective_text)]
        amounts = [value for value in (_ocr_scu_value(token) for token in raw_amounts) if value is not None]
        mapped_rows = marker_hint_rows_from_amounts(hints, amounts)
        if mapped_rows:
            rows = mapped_rows

    return {"payout": payout, "contracted_by": contracted_by, "objectives": rows, "text": raw}


def windows_ocr_image(image_path: Path, timeout_seconds: int = 25) -> str:
    """Read text from an image using Windows' built-in OCR engine when available."""
    if os.name != "nt":
        raise RuntimeError("Windows OCR is available only in the Windows desktop app.")
    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Screenshot not found: {image_path}")
    script = r'''
param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Runtime.WindowsRuntime
[Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime] > $null
[Windows.Storage.FileAccessMode, Windows.Storage, ContentType = WindowsRuntime] > $null
[Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime] > $null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime] > $null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType = WindowsRuntime] > $null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime] > $null
[Windows.Media.Ocr.OcrResult, Windows.Media.Ocr, ContentType = WindowsRuntime] > $null

function Await-Operation($Operation, [Type]$ResultType) {
  $methods = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq "AsTask" -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1
  }
  $method = @($methods)[0].MakeGenericMethod($ResultType)
  $task = $method.Invoke($null, @($Operation))
  $task.Wait()
  return $task.Result
}

$file = Await-Operation ([Windows.Storage.StorageFile]::GetFileFromPathAsync($Path)) ([Windows.Storage.StorageFile])
$stream = Await-Operation ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-Operation ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-Operation ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) { throw "Windows OCR engine is unavailable for the current user language." }
$result = Await-Operation ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
$result.Text
'''
    import tempfile
    script_path = Path(tempfile.gettempdir()) / f"scht_ocr_{os.getpid()}_{int(time.time() * 1000)}.ps1"
    script_path.write_text(script, encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-Path",
                str(image_path),
            ],
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    finally:
        try:
            script_path.unlink()
        except Exception:
            pass
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "Windows OCR failed.").strip()
        raise RuntimeError(detail)
    return completed.stdout.strip()


def _create_contract_ocr_crops(image_path: Path) -> dict:
    """Create upscaled relative crops for the reward header and objectives panel."""
    if os.name != "nt":
        return {}
    image_path = Path(image_path)
    temp_dir = image_path.parent
    stem = f"{image_path.stem}-{int(time.time() * 1000)}"
    reward_path = temp_dir / f"{stem}-reward.png"
    reward_value_path = temp_dir / f"{stem}-reward-value.png"
    objectives_path = temp_dir / f"{stem}-objectives.png"
    script = r'''
param(
  [Parameter(Mandatory=$true)][string]$Path,
  [Parameter(Mandatory=$true)][string]$RewardPath,
  [Parameter(Mandatory=$true)][string]$RewardValuePath,
  [Parameter(Mandatory=$true)][string]$ObjectivesPath
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
function Save-RelativeCrop($Source, [string]$Destination, [double]$X, [double]$Y, [double]$W, [double]$H, [double]$Scale) {
  $sx = [Math]::Max(0, [int]($Source.Width * $X))
  $sy = [Math]::Max(0, [int]($Source.Height * $Y))
  $sw = [Math]::Min($Source.Width - $sx, [Math]::Max(1, [int]($Source.Width * $W)))
  $sh = [Math]::Min($Source.Height - $sy, [Math]::Max(1, [int]($Source.Height * $H)))
  $dw = [Math]::Max(1, [int]($sw * $Scale))
  $dh = [Math]::Max(1, [int]($sh * $Scale))
  $target = New-Object System.Drawing.Bitmap($dw, $dh, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
  $graphics = [System.Drawing.Graphics]::FromImage($target)
  try {
    $graphics.Clear([System.Drawing.Color]::Black)
    $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $destRect = New-Object System.Drawing.Rectangle(0, 0, $dw, $dh)
    $srcRect = New-Object System.Drawing.Rectangle($sx, $sy, $sw, $sh)
    $graphics.DrawImage($Source, $destRect, $srcRect, [System.Drawing.GraphicsUnit]::Pixel)
    $target.Save($Destination, [System.Drawing.Imaging.ImageFormat]::Png)
  } finally {
    $graphics.Dispose(); $target.Dispose()
  }
}
$source = [System.Drawing.Bitmap]::FromFile($Path)
try {
  # Broad crops deliberately include labels as anchors. Relative coordinates
  # cover 16:9, 16:10 and ultrawide mobiGlas layouts without assuming pixels.
  Save-RelativeCrop $source $RewardPath 0.61 0.07 0.38 0.24 3.0
  # A second narrow crop isolates the large value at the far-right edge. This is
  # intentionally redundant because Windows OCR often reads the Reward label but
  # drops the digits from the broader translucent panel.
  Save-RelativeCrop $source $RewardValuePath 0.81 0.09 0.18 0.17 5.0
  Save-RelativeCrop $source $ObjectivesPath 0.62 0.25 0.37 0.57 2.4
} finally {
  $source.Dispose()
}
'''
    import tempfile
    script_path = Path(tempfile.gettempdir()) / f"scht_crop_{os.getpid()}_{int(time.time() * 1000)}.ps1"
    script_path.write_text(script, encoding="utf-8")
    try:
        completed = subprocess.run(
            [
                "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                "-File", str(script_path), "-Path", str(image_path),
                "-RewardPath", str(reward_path), "-RewardValuePath", str(reward_value_path),
                "-ObjectivesPath", str(objectives_path),
            ],
            text=True,
            capture_output=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        if completed.returncode != 0:
            return {}
        return {
            "reward_value": reward_value_path if reward_value_path.exists() else None,
            "reward": reward_path if reward_path.exists() else None,
            "objectives": objectives_path if objectives_path.exists() else None,
        }
    finally:
        try:
            script_path.unlink()
        except Exception:
            pass


def merge_contract_ocr_passes(
    full_text: str,
    reward_text: str,
    objectives_text: str,
    hints: Optional[Sequence[dict]] = None,
) -> dict:
    """Merge whole-screen and targeted OCR passes without inventing values."""
    hints = list(hints or [])
    full_parsed = parse_contract_details_text(full_text, hints)
    crop_parsed = (
        parse_contract_details_text("PRIMARY OBJECTIVES\n" + (objectives_text or ""), hints)
        if objectives_text
        else {"objectives": []}
    )
    rows: List[dict] = []
    seen = set()
    for item in [*(crop_parsed.get("objectives") or []), *(full_parsed.get("objectives") or [])]:
        if not isinstance(item, dict):
            continue
        key = (
            ocr_compact(str(item.get("pickup") or "")),
            ocr_compact(str(item.get("dropoff") or "")),
            ocr_compact(str(item.get("commodity") or "")),
            re.sub(r"[^0-9.]", "", str(item.get("scu") or "")),
        )
        if key in seen:
            continue
        seen.add(key)
        rows.append(dict(item))
    payout = full_parsed.get("payout")
    if payout is None and reward_text:
        payout = parse_reward_amount("Reward " + reward_text)
    contracted_by = full_parsed.get("contracted_by") or (
        parse_contracted_by(reward_text) if reward_text else ""
    )
    review_text = full_text or ""
    if reward_text and payout is not None and parse_reward_amount(full_text or "") is None:
        review_text += "\n\n[Reward crop]\n" + reward_text
    if objectives_text and len(rows) > len(full_parsed.get("objectives") or []):
        review_text += "\n\n[Objectives crop]\n" + objectives_text
    return {
        "payout": payout,
        "contracted_by": contracted_by,
        "objectives": rows,
        "text": review_text.strip(),
    }


def read_contract_image_ocr(
    image_path: Path,
    hints: Optional[Sequence[dict]] = None,
    expected_objectives: Optional[int] = None,
) -> dict:
    """Run full-image OCR plus targeted enlarged crops for fragile UI fields."""
    image_path = Path(image_path)
    full_text = windows_ocr_image(image_path)
    initial = parse_contract_details_text(full_text, hints)
    expected_rows = int(expected_objectives or 0)
    if expected_rows <= 0:
        expected_rows = len([
            item
            for item in (hints or [])
            if isinstance(item, dict) and item.get("dropoff") and item.get("commodity")
        ])
    need_objectives = not initial.get("objectives") or (
        expected_rows and len(initial.get("objectives") or []) < expected_rows
    )
    need_reward = initial.get("payout") is None
    crops = _create_contract_ocr_crops(image_path) if (need_objectives or need_reward) else {}
    reward_text = ""
    objectives_text = ""
    try:
        reward_paths = [crops.get("reward_value"), crops.get("reward")]
        objectives_path = crops.get("objectives")
        if need_reward:
            reward_parts = []
            for reward_path in reward_paths:
                if not reward_path:
                    continue
                try:
                    part = windows_ocr_image(Path(reward_path))
                    if part:
                        reward_parts.append(part)
                except Exception:
                    pass
            reward_text = "\n".join(reward_parts)
        if need_objectives and objectives_path:
            try:
                objectives_text = windows_ocr_image(Path(objectives_path))
            except Exception:
                objectives_text = ""
    finally:
        for crop_path in crops.values():
            if crop_path:
                try:
                    Path(crop_path).unlink()
                except Exception:
                    pass
    parsed = merge_contract_ocr_passes(full_text, reward_text, objectives_text, hints)
    return {
        "full_text": full_text,
        "reward_text": reward_text,
        "objectives_text": objectives_text,
        "parsed": parsed,
    }


def recent_star_citizen_screenshot(log_path: str, since_epoch: float, tried_paths: Optional[set] = None) -> Optional[Path]:
    """Return a very recent SC screenshot created during the current OCR job."""
    tried = {str(Path(p)).lower() for p in (tried_paths or set())}
    try:
        log = Path(str(log_path or "").strip().strip('"'))
    except Exception:
        return None
    if not log.name:
        return None
    screenshot_dirs = [
        log.parent / "screenshots",
        log.parent / "Screenshots",
    ]
    min_mtime = max(0.0, float(since_epoch or 0) - 3.0)
    max_mtime = time.time() + 5.0
    newest: Optional[Path] = None
    newest_mtime = 0.0
    for directory in screenshot_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        try:
            entries = list(directory.iterdir())
        except Exception:
            continue
        for path in entries:
            if not path.is_file() or path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".bmp"}:
                continue
            if str(path).lower() in tried:
                continue
            try:
                mtime = path.stat().st_mtime
            except Exception:
                continue
            if mtime < min_mtime or mtime > max_mtime:
                continue
            if mtime >= newest_mtime:
                newest = path
                newest_mtime = mtime
    return newest


def preserve_ocr_debug_capture(image_path: Path, mission_id: str, attempt: int) -> str:
    """Keep a failed live capture so capture quality can be inspected later."""
    try:
        source = Path(image_path)
        if not source.exists():
            return ""
        debug_dir = app_data_directory() / "ocr-debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        safe_mission = re.sub(r"[^0-9a-zA-Z-]+", "", str(mission_id or "mission"))[:64] or "mission"
        target = debug_dir / f"failed-live-{safe_mission}-attempt-{int(attempt)}.png"
        import shutil
        shutil.copy2(source, target)
        return str(target)
    except Exception:
        return ""


def ocr_contract_page_ready(text: str) -> bool:
    """Return True only when OCR appears to contain a fully opened contract page."""
    raw = html.unescape(text or "")
    compact = re.sub(r"\s+", " ", raw).strip().lower()
    primary = bool(re.search(r"\bprimary\s+[o0]bjectives?\b", compact)) or "primaryobjectives" in re.sub(r"[^a-z]", "", compact)
    objective_words = "deliver" in compact or "collect" in compact
    quantity = bool(re.search(r"\b(?:scu|5cu|s\.?c\.?u\.?)\b", compact, re.I))
    return primary and objective_words and quantity


def _objective_signature(item: dict) -> Tuple[str, str, str]:
    return (
        ocr_compact(str(item.get("dropoff") or "")),
        ocr_compact(str(item.get("commodity") or "")),
        re.sub(r"[^0-9.]", "", str(item.get("scu") or "")),
    )


def ocr_objective_expectation(group: Sequence[CargoMission]) -> dict:
    """Describe how many visible Deliver objectives the current mission should have."""
    group = list(group or [])
    if not group:
        return {"confident": False, "objective_count": 0, "pickup_count": 0, "dropoff_count": 0, "commodity_count": 0, "scope": "unknown"}
    mission_id = group[0].mission_id or ""
    raw = "\n".join(m.raw or "" for m in group)
    contract_def = contract_definition_for(raw, mission_id)
    if contract_def:
        pickup_count, dropoff_count = contract_route_shape(contract_def)
        commodities = [c for c in commodities_from_contract_definition(contract_def) if c and c.lower() != "unknown commodity"]
        commodity_count = max(1, len(commodities))
        if pickup_count > 1 and dropoff_count == 1:
            # This route shape is ambiguous by itself. Some contracts expose one
            # aggregate delivery quantity shared by every pickup, while others
            # explicitly list one quantity per pickup. OCR validation therefore
            # accepts either shape and the visible objective count decides scope.
            return {
                "confident": True,
                "objective_count": 1,
                "max_objective_count": max(1, pickup_count * commodity_count),
                "pickup_count": pickup_count,
                "dropoff_count": 1,
                "commodity_count": commodity_count,
                "scope": "multi_pickup_flexible",
            }
        return {
            "confident": True,
            "objective_count": max(1, dropoff_count * commodity_count),
            "pickup_count": pickup_count,
            "dropoff_count": dropoff_count,
            "commodity_count": commodity_count,
            "scope": "per_route",
        }
    drop_ids = {m.objective_id.lower() for m in group if (m.objective_id or "").lower().startswith("dropoff")}
    pickup_ids = {m.objective_id.lower() for m in group if (m.objective_id or "").lower().startswith("pickup")}
    if len(drop_ids) > 1:
        return {"confident": True, "objective_count": len(group), "pickup_count": 1, "dropoff_count": len(drop_ids), "commodity_count": max(1, len({ocr_compact(m.commodity) for m in group if m.commodity})), "scope": "per_route"}
    if len(pickup_ids) > 1 and len(drop_ids) <= 1:
        return {
            "confident": True,
            "objective_count": 1,
            "max_objective_count": len(pickup_ids),
            "pickup_count": len(pickup_ids),
            "dropoff_count": 1,
            "commodity_count": 1,
            "scope": "multi_pickup_flexible",
        }
    return {"confident": False, "objective_count": max(1, len(group)), "pickup_count": 0, "dropoff_count": 0, "commodity_count": 0, "scope": "unknown"}


def validate_ocr_contract_details(parsed: dict, group: Sequence[CargoMission]) -> dict:
    """Validate OCR candidates against the pending MissionId before applying them."""
    objectives = [dict(item) for item in (parsed or {}).get("objectives") or [] if isinstance(item, dict)]
    normalized_objectives: List[dict] = []
    for item in objectives:
        scope = str(item.get("quantity_scope") or "per_route").strip().lower()
        if scope not in {"per_route", "aggregate"}:
            scope = "per_route"
        item["quantity_scope"] = scope
        has_route = bool(item.get("dropoff") and item.get("commodity"))
        scu = str(item.get("scu") or "").strip()
        has_quantity = bool(re.fullmatch(r"\d+(?:\.\d+)?", scu))
        if has_route and (has_quantity or (scope == "aggregate" and not scu)):
            normalized_objectives.append(item)
    objectives = normalized_objectives
    quantity_objectives = [item for item in objectives if re.fullmatch(r"\d+(?:\.\d+)?", str(item.get("scu") or ""))]
    if not quantity_objectives:
        return {"ok": False, "reason": "No complete cargo objectives were read.", "score": 0}
    expectation = ocr_objective_expectation(group)
    expected_count = int(expectation.get("objective_count") or 0)
    found_quantity_count = len(quantity_objectives)
    if expectation.get("confident") and found_quantity_count < expected_count:
        return {
            "ok": False,
            "reason": f"OCR read only {found_quantity_count} of {expected_count} expected cargo objectives; no partial route data was saved.",
            "score": 5,
            "expected_objectives": expected_count,
            "found_objectives": found_quantity_count,
        }
    max_expected_count = int(expectation.get("max_objective_count") or expected_count or 0)
    if expectation.get("confident") and expectation.get("scope") == "multi_pickup_flexible" and max_expected_count and found_quantity_count not in (1, max_expected_count):
        return {
            "ok": False,
            "reason": f"OCR read {found_quantity_count} quantities; this multi-pickup contract must show either one shared quantity or {max_expected_count} explicit pickup quantities.",
            "score": 5,
            "expected_objectives": max_expected_count,
            "found_objectives": found_quantity_count,
        }
    if expectation.get("confident") and expectation.get("scope") == "per_route" and found_quantity_count > expected_count:
        return {
            "ok": False,
            "reason": f"OCR read {found_quantity_count} objectives but this mission expects {expected_count}; the visible page may not match the pending contract.",
            "score": 5,
        }
    for item in objectives:
        pickup = ocr_compact(str(item.get("pickup") or ""))
        dropoff = ocr_compact(str(item.get("dropoff") or ""))
        if pickup and dropoff and pickup == dropoff:
            if expectation.get("confident") and int(expectation.get("objective_count") or 0) == 1 and len(objectives) == 1 and len(group) == 1:
                mission = group[0]
                known_pickup = mission.pickup if mission.pickup and not str(mission.pickup).lower().startswith("unknown") else ""
                known_dropoff = mission.dropoff if mission.dropoff and not str(mission.dropoff).lower().startswith("unknown") else ""
                known_commodity = mission.commodity if mission.commodity and mission.commodity.lower() != "unknown commodity" else ""
                parsed_commodity = str(item.get("commodity") or "")
                commodity_matches = (
                    not known_commodity
                    or ocr_compact(parsed_commodity) == ocr_compact(known_commodity)
                    or ocr_compact(parsed_commodity) in ocr_compact(known_commodity)
                    or ocr_compact(known_commodity) in ocr_compact(parsed_commodity)
                )
                if known_pickup and known_dropoff and ocr_compact(known_pickup) != ocr_compact(known_dropoff) and commodity_matches:
                    repaired = dict(item)
                    repaired["pickup"] = known_pickup
                    repaired["dropoff"] = known_dropoff
                    if known_commodity:
                        repaired["commodity"] = known_commodity
                    objectives = [repaired]
                    break
            return {"ok": False, "reason": "OCR produced the same pickup and drop-off location, so the route was rejected as unsafe.", "score": 5}
    parsed_dropoffs = {ocr_compact(item.get("dropoff") or "") for item in objectives}
    parsed_commodities = {ocr_compact(item.get("commodity") or "") for item in objectives}
    parsed_dropoffs.discard(""); parsed_commodities.discard("")
    expected_dropoffs = int(expectation.get("dropoff_count") or 0)
    expected_commodities = int(expectation.get("commodity_count") or 0)
    if expectation.get("confident") and expected_dropoffs > 1 and len(parsed_dropoffs) < expected_dropoffs:
        return {"ok": False, "reason": f"OCR found only {len(parsed_dropoffs)} of {expected_dropoffs} distinct drop-off locations.", "score": 5}
    if expectation.get("confident") and expected_commodities > 1 and len(parsed_commodities) < expected_commodities:
        return {"ok": False, "reason": f"OCR found only {len(parsed_commodities)} of {expected_commodities} commodities.", "score": 5}
    known_commodities = {ocr_compact(m.commodity) for m in group if m.commodity and m.commodity.lower() != "unknown commodity"}
    known_commodities.discard("")
    if known_commodities and not (known_commodities & parsed_commodities):
        return {"ok": False, "reason": "The visible contract commodity does not match the newly accepted mission.", "score": 10}
    known_locations = {ocr_compact(v) for m in group for v in (m.pickup, m.dropoff) if v and not str(v).lower().startswith("unknown")}
    parsed_locations = {ocr_compact(v) for item in objectives for v in (item.get("pickup"), item.get("dropoff")) if v}
    known_locations.discard(""); parsed_locations.discard("")
    if len(known_locations) >= 2 and parsed_locations and not (known_locations & parsed_locations):
        return {"ok": False, "reason": "The visible contract locations do not match the newly accepted mission.", "score": 15}
    known_pickups = {ocr_compact(m.pickup) for m in group if m.pickup and not str(m.pickup).lower().startswith("unknown")}
    known_dropoffs = {ocr_compact(m.dropoff) for m in group if m.dropoff and not str(m.dropoff).lower().startswith("unknown")}
    known_pickups.discard(""); known_dropoffs.discard("")
    parsed_pickups = {ocr_compact(item.get("pickup") or "") for item in objectives if item.get("pickup")}
    parsed_dropoff_values = {ocr_compact(item.get("dropoff") or "") for item in objectives if item.get("dropoff")}
    parsed_pickups.discard(""); parsed_dropoff_values.discard("")
    if expectation.get("confident") and len(known_dropoffs) >= expected_dropoffs > 0:
        missing_dropoffs = known_dropoffs - parsed_dropoff_values
        if missing_dropoffs:
            return {"ok": False, "reason": "OCR drop-off locations do not match the marker-resolved mission routes.", "score": 15}
    aggregate_ocr = any(item.get("quantity_scope") == "aggregate" for item in objectives)
    if expectation.get("confident") and len(known_pickups) == 1 and parsed_pickups:
        expected_pickup = next(iter(known_pickups))
        if aggregate_ocr:
            if expected_pickup not in parsed_pickups:
                return {"ok": False, "reason": "OCR pickup locations do not include the marker-resolved mission pickup.", "score": 15}
        elif any(pickup != expected_pickup for pickup in parsed_pickups):
            return {"ok": False, "reason": "OCR pickup locations do not match the marker-resolved mission pickup.", "score": 15}
    exact = [m for m in group if m.scu_provenance == "exact_log" and m.has_known_scu()]
    parsed_signatures = {_objective_signature(item) for item in objectives}
    for mission in exact:
        signature = _objective_signature({"dropoff": mission.dropoff, "commodity": mission.commodity, "scu": mission.scu})
        if signature not in parsed_signatures:
            return {"ok": False, "reason": "OCR conflicts with an exact objective already emitted by Game.log.", "score": 20}
    score = 55
    if known_commodities & parsed_commodities:
        score += 20
    if known_locations & parsed_locations:
        score += 15
    if (parsed or {}).get("payout") is not None:
        score += 10
    return {
        "ok": True,
        "reason": "Validated against the pending mission.",
        "score": min(score, 100),
        "objectives": objectives,
        "expected_objectives": expected_count,
        "found_objectives": found_quantity_count,
        "route_row_count": len(objectives),
        "expectation": expectation,
    }

def looks_like_accepted_hauling(line: str) -> bool:
    p = strip_markup(line).lower()
    if "contract accepted" not in p and "mission accepted" not in p:
        return False
    return any(w in p for w in ["haul", "cargo", "scu", "covalex", "freight", "deliver"])


def is_primary_accepted_hauling_line(line: str) -> bool:
    """True only for the real log event, not repeated queued notification text.

    SC echoes notifications several times as indented quote lines and UpdateNotificationItem
    lines. Older versions treated those echoes as new accepted contracts, which inflated
    accepted count and duplicated cargo.
    """
    p = strip_markup(line).lower()
    if "<shudevent_onnotification>" not in line.lower():
        return False
    if 'added notification "contract accepted:' not in p and 'added notification "mission accepted:' not in p:
        return False
    return looks_like_accepted_hauling(line)


def looks_like_completion_or_reward(line: str) -> bool:
    p = strip_markup(line).lower()
    if "<endmission>" in line.lower():
        return True
    completion_hit = any(w in p for w in [
        "contract completed", "mission completed", "objective completed", "mission succeeded",
        "contract succeeded", "mission success", "contract fulfilled", "completed contract",
        "contract abandoned", "mission abandoned", "contract failed", "mission failed",
        "contract cancelled", "mission cancelled", "contract canceled", "mission canceled",
    ])
    money_hit = ("auec" in p or " uec" in p or any(w in p for w in ["reward", "payout", "payment", "credited", "awarded", "earned"]))
    mission_context = any(w in p for w in ["mission", "contract", "objective", "covalex", "haul", "cargo", "missionid"])
    return completion_hit or (money_hit and mission_context)


def get_rank(text: str) -> str:
    p = strip_markup(text).lower()
    for r in RANK_WORDS:
        if re.search(rf"\b{re.escape(r)}\b", p):
            return r.title()
    return ""


def get_mission_id(text: str) -> str:
    m = re.search(r"MissionId\s*:\s*\[?([0-9a-fA-F-]{16,64})\]?", text)
    if m:
        return m.group(1)
    m = re.search(r"MissionId\s*\[?([0-9a-fA-F-]{16,64})\]?", text)
    return m.group(1) if m else ""


def accepted_hauling_mission_ids(text: str) -> List[str]:
    """Return unique MissionIds from real live hauling acceptance events.

    This deliberately ignores notification queue echoes and UpdateNotificationItem
    lines. Automatic OCR must be driven by the actual ``Added notification`` event,
    not merely by whether a parser merge happened to create a new table group.
    """
    found: List[str] = []
    seen = set()
    for line in (text or "").splitlines():
        if not is_primary_accepted_hauling_line(line):
            continue
        mission_id = get_mission_id(line).strip().lower()
        if mission_id and mission_id not in seen:
            seen.add(mission_id)
            found.append(mission_id)
    return found


def mission_scoped_text(block_lines: Sequence[str], mission_id: str, accepted_line: str = "") -> str:
    """Return only lines that belong to one accepted mission.

    Stacked contract acceptances can be only a few lines apart. ``build_blocks``
    intentionally looks backwards for the current contract-definition markers,
    which means a block may also contain notifications from the previous mission
    and marker lines for the next mission. Parsing the whole block caused the
    previous Quartz objectives and MissionId to be assigned to later contracts.
    """
    mission_id = (mission_id or "").strip().lower()
    scoped: List[str] = []
    for line in block_lines:
        if mission_id and mission_id in line.lower():
            scoped.append(line)
    if accepted_line and accepted_line not in scoped:
        scoped.append(accepted_line)
    return "\n".join(scoped) if scoped else "\n".join(block_lines)


def get_title(text: str) -> str:
    p = strip_markup(text)
    patterns = [
        r"\b(?:Contract|Mission)\s+Accepted\s*:\s*\"?([^\n\r\"]{4,180})",
        r"\b(?:Contract|Mission)\s+(?:Completed|Succeeded|Success|Fulfilled|Abandoned|Failed|Canceled|Cancelled)\s*:\s*\"?([^\n\r\"]{4,180})",
    ]
    for pat in patterns:
        m = re.search(pat, p, re.I)
        if m:
            return clean(m.group(1), max_words=18)
    return "Hauling mission"


def get_route(text: str) -> Tuple[str, str, int]:
    p = strip_markup(text)
    patterns = [
        r"\b(?:Contract|Mission)\s+Accepted[^\n\r\"]*?\|\s*[^|\n\r]{2,90}\|\s*(?P<pickup>[A-Z][A-Za-z0-9 .\-'&]{2,70})\s*(?:>|->|→)\s*(?P<drop>[A-Z][A-Za-z0-9 .\-'&]{2,70})",
        r"\|\s*(?P<pickup>[A-Z][A-Za-z0-9 .\-'&]{2,70})\s*(?:>|->|→)\s*(?P<drop>[A-Z][A-Za-z0-9 .\-'&]{2,70})",
        r"\bfrom\s+(?P<pickup>[A-Z][A-Za-z0-9 .\-'&]{2,70})\s+(?:to|and deliver to)\s+(?P<drop>[A-Z][A-Za-z0-9 .\-'&]{2,70})",
    ]
    for pat in patterns:
        m = re.search(pat, p, re.I)
        if m:
            pickup = clean(m.group("pickup"), 10)
            drop = clean(m.group("drop"), 10)
            if pickup and drop and "scu" not in pickup.lower():
                return pickup, drop, 45

    locs = []
    for loc in KNOWN_LOCATION_HINTS:
        for m in re.finditer(rf"\b{re.escape(loc)}\b", p, re.I):
            locs.append((m.start(), loc))
    ordered = []
    for _, loc in sorted(locs):
        if loc not in ordered:
            ordered.append(loc)
    if len(ordered) >= 2:
        return ordered[0], ordered[1], 20
    if len(ordered) == 1:
        return ordered[0], "Unknown drop-off", 8
    return "Unknown pickup", "Unknown drop-off", 0


def get_objective_id(text: str) -> str:
    m = re.search(r"ObjectiveId\s*:\s*\[?([^\]\s,]+)\]?", text, re.I)
    return m.group(1) if m else ""


def is_primary_objective_notification_line(line: str) -> bool:
    lower = line.lower()
    if "<shudevent_onnotification>" not in lower or "added notification" not in lower:
        return False
    if "new objective:" not in strip_markup(line).lower():
        return False
    if any(blocked in lower for blocked in ["remove notification", "update notification", "startfade", "next "]):
        return False
    return True


def parse_objectives(text: str) -> List[ParsedObjective]:
    """Return exact objectives emitted by real Added notification events.

    SC commonly writes objective notifications as:
    New Objective: Deliver 0/8 SCU of Quartz to Sakura Sun Magnolia Workcenter:
    Repeated queue dumps and indented notification echoes are deliberately ignored.
    """
    out: List[ParsedObjective] = []
    seen = set()

    line_pat = re.compile(
        r"New Objective:\s*Deliver\s+\d+(?:\.\d+)?\s*/\s*(?P<scu>\d+(?:\.\d+)?)\s*SCU\s+(?:of\s+)?"
        r"(?P<commodity>[A-Za-z][A-Za-z0-9 /\-'&]{1,60}?)\s+to\s+"
        r"(?P<drop>.*?)(?::\s*\"|:\s*\[|\"\s*\[|$)",
        re.I,
    )
    for line in text.splitlines():
        if not is_primary_objective_notification_line(line):
            continue
        s = strip_markup(line)
        m = line_pat.search(s)
        if not m:
            continue
        mission_id = get_mission_id(line)
        objective_id = get_objective_id(line)
        commodity = clean(m.group("commodity"), 8)
        drop = clean(m.group("drop"), 14)
        drop = re.sub(r"\s+in\s+(?:Lorville|Area18|New Babbage|Orison)\b.*$", "", drop, flags=re.I)
        scu = clean(m.group("scu"), 2)
        content_key = re.sub(r"\s+", " ", f"{commodity}|{scu}|{drop}".lower()).strip()
        key = (mission_id.lower(), objective_id.lower(), content_key)
        if commodity and scu and drop and key not in seen:
            seen.add(key)
            out.append(ParsedObjective(
                commodity=commodity,
                scu=scu,
                dropoff=drop,
                confidence=50,
                mission_id=mission_id,
                objective_id=objective_id,
                provenance="exact_log",
                quantity_scope="per_route",
            ))
    return out


def get_pickup_from_collect(text: str, commodity: str = "") -> str:
    """Extract pickup from objective text like 'Collect Quartz from Everus Harbor'."""
    p = strip_markup(text)
    if commodity:
        pat = rf"\bCollect\s+{re.escape(commodity)}\s+from\s+(?P<pickup>[^.\n\r\"]{{3,90}}?)(?=\.|\s+Deliver\b|\s+New Objective\b|$)"
        m = re.search(pat, p, re.I)
        if m:
            return clean(m.group("pickup"), 12)
    m = re.search(r"\bCollect\s+[A-Za-z][A-Za-z0-9 /\-'&]{1,60}?\s+from\s+(?P<pickup>[^.\n\r\"]{3,90}?)(?=\.|\s+Deliver\b|\s+New Objective\b|$)", p, re.I)
    if m:
        return clean(m.group("pickup"), 12)
    return ""


def make_contract_uid(mission_id: str, title: str, timestamp: str, source_line: int) -> str:
    if mission_id:
        return f"id:{mission_id.lower()}"
    marker = timestamp or f"line:{source_line}"
    return f"{marker}|{normalize_contract_title(title)}"


def build_blocks(lines: Sequence[str], context_before: int = 80, context_after: int = 160) -> List[Tuple[int, List[str]]]:
    # Start only on the actual Added notification event. Do not start blocks from
    # echoed quote lines or UpdateNotificationItem lines. Include a short look-back
    # because SC often writes objective marker/contract-definition lines immediately
    # before the accepted notification, and for some multi-drop contracts it never
    # emits individual New Objective text.
    starts = [i for i, line in enumerate(lines) if is_primary_accepted_hauling_line(line)]
    blocks: List[Tuple[int, List[str]]] = []
    for idx, start in enumerate(starts):
        next_start = starts[idx + 1] if idx + 1 < len(starts) else len(lines)
        s = max(0, start - context_before)
        e = min(len(lines), start + context_after, next_start)
        blocks.append((start + 1, lines[s:e]))
    return blocks


def build_completion_blocks(lines: Sequence[str], context_before: int = 5, context_after: int = 8) -> List[Tuple[int, List[str]]]:
    starts = [i for i, line in enumerate(lines) if looks_like_completion_or_reward(line)]
    blocks: List[Tuple[int, List[str]]] = []
    for start in starts:
        s = max(0, start - context_before)
        e = min(len(lines), start + context_after)
        blocks.append((start + 1, lines[s:e]))
    return blocks


def parse_block(source_line: int, block_lines: Sequence[str]) -> List[CargoMission]:
    raw = "\n".join(block_lines)
    plain = strip_markup(raw)
    if not re.search(r"\b(?:haul|cargo|SCU|Covalex|Deliver)\b", plain, re.I):
        return []

    # The current accepted event is the last primary accepted line in this block.
    # The look-back context may contain one or more earlier stacked acceptances.
    accepted_line = next((l for l in reversed(block_lines) if is_primary_accepted_hauling_line(l)), "")
    title_source = accepted_line or raw
    title = get_title(title_source)
    rank = get_rank(title_source) or get_rank(raw)
    mission_id = get_mission_id(accepted_line) or get_mission_id(raw)
    scoped_raw = mission_scoped_text(block_lines, mission_id, accepted_line)
    pickup, route_dropoff, route_conf = get_route(title_source)
    timestamp = extract_timestamp(accepted_line) or next((extract_timestamp(l) for l in reversed(block_lines) if extract_timestamp(l)), "")
    contract_uid = make_contract_uid(mission_id, title, timestamp, source_line)
    contract_def = contract_definition_for(scoped_raw, mission_id)
    markers = parse_objective_markers(scoped_raw, mission_id)
    pickup_markers = [m for m in markers if m.kind == "pickup"]
    dropoff_markers = [m for m in markers if m.kind == "dropoff"]
    objectives = parse_objectives(scoped_raw)
    marker_inferred = False
    if not objectives and contract_def:
        objectives = parse_marker_objectives(scoped_raw, contract_def, mission_id)
        marker_inferred = bool(objectives)
    elif len(objectives) == 1 and len(pickup_markers) > 1:
        # Some multi-pickup contracts emit one aggregate delivery objective.
        # Keep the total once, then show the remaining pickup rows without
        # multiplying the quantity across every source marker.
        aggregate = objectives[0]
        expanded: List[ParsedObjective] = []
        for index, pickup_marker in enumerate(pickup_markers):
            expanded.append(ParsedObjective(
                commodity=aggregate.commodity,
                scu=aggregate.scu if index == 0 else "",
                dropoff=aggregate.dropoff,
                confidence=aggregate.confidence,
                pickup=pickup_marker.location,
                mission_id=aggregate.mission_id,
                objective_id=pickup_marker.objective_id,
                provenance=aggregate.provenance,
                quantity_scope="aggregate",
            ))
        objectives = expanded

    base_conf = route_conf
    if rank:
        base_conf += 5
    if "covalex" in plain.lower():
        base_conf += 10
    if mission_id:
        base_conf += 10

    missions: List[CargoMission] = []
    if objectives:
        for objective in objectives:
            commodity = objective.commodity
            dropoff = objective.dropoff or route_dropoff
            marker_pickup = objective.pickup
            if not marker_pickup and len(pickup_markers) == 1:
                marker_pickup = pickup_markers[0].location
            obj_pickup = marker_pickup or get_pickup_from_collect(scoped_raw, commodity) or pickup
            confidence = min(100, base_conf + objective.confidence + (10 if obj_pickup and obj_pickup != "Unknown pickup" else 0))
            note = "Parsed from accepted contract + objective" if confidence >= 70 else "Check raw log block"
            if marker_inferred:
                note = "Marker/token data only; SCU and payout not emitted by Game.log"
                confidence = max(confidence, 65)
            elif objective.quantity_scope == "aggregate":
                note = "Aggregate SCU from Game.log; pickup distribution not emitted"
            payout = None
            missions.append(CargoMission(
                title=title,
                rank=rank,
                pickup=obj_pickup,
                dropoff=dropoff or route_dropoff,
                commodity=commodity,
                scu=objective.scu,
                confidence=confidence,
                notes=note,
                raw=raw,
                mission_id=mission_id,
                timestamp=timestamp,
                source_line=source_line,
                contract_uid=contract_uid,
                payout_auec=payout,
                objective_id=objective.objective_id,
                data_provenance=objective.provenance,
                scu_provenance=objective.provenance if objective.scu else "unknown",
                payout_provenance="unknown",
                quantity_scope=objective.quantity_scope,
            ))
    else:
        missions.append(CargoMission(
            title=title,
            rank=rank,
            pickup=pickup,
            dropoff=route_dropoff,
            commodity="Unknown commodity",
            scu="",
            confidence=min(100, base_conf),
            notes="Hauling contract detected, but objective/SCU text not visible in log",
            raw=raw,
            mission_id=mission_id,
            timestamp=timestamp,
            source_line=source_line,
            contract_uid=contract_uid,
            payout_auec=None,
            data_provenance="unknown",
            scu_provenance="unknown",
            payout_provenance="unknown",
            quantity_scope="unknown",
        ))
    return missions


def parse_completion_block(
    source_line: int,
    block_lines: Sequence[str],
    trigger_line: str = "",
) -> Optional[CompletionEvent]:
    raw = "\n".join(block_lines)
    plain = strip_markup(raw)
    lower = plain.lower()
    # Completion events can arrive as a same-millisecond stack. The surrounding
    # context may therefore contain several EndMission records; anchor an exact
    # lifecycle event to the line that caused this block to be created.
    end_line = trigger_line if "<endmission>" in trigger_line.lower() else ""
    end_match = re.search(
        r"<EndMission>.*?MissionId\s*\[([^\]]+)\].*?CompletionType\s*\[([^\]]+)\].*?Reason\s*\[([^\]]*)\]",
        end_line or raw,
        re.I | re.S,
    )
    if end_match:
        mission_id = end_match.group(1).strip()
        completion_type = end_match.group(2).strip()
        reason = end_match.group(3).strip()
        timestamp = extract_timestamp(end_line) or next((extract_timestamp(l) for l in block_lines if "<EndMission>" in l and extract_timestamp(l)), "")
        return CompletionEvent(
            mission_id=mission_id,
            title="",
            amount_auec=None,
            timestamp=timestamp,
            raw=end_line or raw,
            source_line=source_line,
            confidence=95 if mission_id else 45,
            is_completion=completion_type.lower() == "complete",
            is_abandoned=completion_type.lower() != "complete",
        )
    if not looks_like_completion_or_reward(plain):
        # line-level helper can work on a whole block too.
        if not any(w in lower for w in ["mission", "contract", "covalex", "hauling", "cargo", "missionid"]):
            return None
    amount = parse_money_amount(raw)
    mission_id = get_mission_id(raw)
    title = get_title(raw)
    timestamp = next((extract_timestamp(l) for l in block_lines if looks_like_completion_or_reward(l) and extract_timestamp(l)), "")
    if not timestamp:
        timestamp = next((extract_timestamp(l) for l in block_lines if extract_timestamp(l)), "")
    completion_words = any(w in lower for w in ["completed", "succeeded", "success", "fulfilled"])
    abandoned_words = any(w in lower for w in ["abandoned", "failed", "cancelled", "canceled"])
    reward_words = any(w in lower for w in ["reward", "payout", "payment", "paid", "awarded", "earned", "credited", "auec", "uec"])
    if not (mission_id or title != "Hauling mission" or completion_words or abandoned_words or (amount is not None and reward_words)):
        return None
    conf = 0
    if mission_id:
        conf += 55
    if title != "Hauling mission":
        conf += 20
    if completion_words or abandoned_words:
        conf += 20
    if amount is not None:
        conf += 25
    return CompletionEvent(
        mission_id=mission_id,
        title=title if title != "Hauling mission" else "",
        amount_auec=amount,
        timestamp=timestamp,
        raw=raw,
        source_line=source_line,
        confidence=min(100, conf),
        is_completion=completion_words,
        is_abandoned=abandoned_words,
    )


def merge_missions(items: Sequence[CargoMission]) -> List[CargoMission]:
    if not items:
        return []

    best_by_merge: dict[Tuple[str, ...], CargoMission] = {}
    order: List[Tuple[str, ...]] = []
    for m in items:
        key = m.merge_key()
        old = best_by_merge.get(key)
        if old is None:
            best_by_merge[key] = m
            order.append(key)
            continue
        if m.score() > old.score():
            m.merge_runtime_fields_from(old)
            if old.raw and old.raw not in m.raw:
                m.raw = old.raw + "\n--- merged with later/better block ---\n" + m.raw
            best_by_merge[key] = m
        else:
            old.merge_runtime_fields_from(m)
            if m.raw and m.raw not in old.raw:
                old.raw = old.raw + "\n--- duplicate block suppressed ---\n" + m.raw

    candidates = [best_by_merge[key] for key in order]

    # Drop placeholders when the same accepted contract UID already has real
    # objective rows. This fixes "Unknown commodity" rows that arrive before or
    # after the detailed objective notification.
    known_uids = {m.contract_key() for m in candidates if not m.is_placeholder()}
    filtered: List[CargoMission] = []
    runtime_by_uid: dict[Tuple[str, ...], CargoMission] = {}
    for m in candidates:
        if m.contract_key() in known_uids and not m.is_placeholder():
            runtime_by_uid[m.contract_key()] = m
    for m in candidates:
        if m.is_placeholder() and m.contract_key() in known_uids:
            runtime_by_uid[m.contract_key()].merge_runtime_fields_from(m)
            continue
        filtered.append(m)

    # Also remove placeholders for the same title/pickup if detailed objectives
    # exist in the same tiny time window but the log omitted MissionId.
    detailed_markers = {(m.title_key(), m.pickup.lower(), m.timestamp) for m in filtered if not m.is_placeholder()}
    filtered2: List[CargoMission] = []
    for m in filtered:
        if m.is_placeholder() and (m.title_key(), m.pickup.lower(), m.timestamp) in detailed_markers:
            continue
        filtered2.append(m)
    filtered = filtered2

    id_visible_keys = {
        (m.title.lower(), m.rank.lower(), m.pickup.lower(), m.dropoff.lower(), m.commodity.lower(), m.scu)
        for m in filtered if m.mission_id
    }

    out: List[CargoMission] = []
    seen_stable = set()
    for m in filtered:
        visible_key = (m.title.lower(), m.rank.lower(), m.pickup.lower(), m.dropoff.lower(), m.commodity.lower(), m.scu)
        if not m.mission_id and visible_key in id_visible_keys:
            # Preserve completion/payment state by merging into id-backed twin.
            for keep in out:
                keep_key = (keep.title.lower(), keep.rank.lower(), keep.pickup.lower(), keep.dropoff.lower(), keep.commodity.lower(), keep.scu)
                if keep_key == visible_key and keep.mission_id:
                    keep.merge_runtime_fields_from(m)
                    break
            continue
        skey = m.stable_key()
        if skey not in seen_stable:
            seen_stable.add(skey)
            out.append(m)
    return out


def parse_completion_events(lines: Sequence[str]) -> List[CompletionEvent]:
    events: List[CompletionEvent] = []
    seen = set()
    for source_line, block in build_completion_blocks(lines):
        trigger_line = lines[source_line - 1] if 0 < source_line <= len(lines) else ""
        event = parse_completion_block(source_line, block, trigger_line)
        if not event:
            continue
        key = event.key()
        if key not in seen:
            seen.add(key)
            events.append(event)
    return events


def contract_groups(missions: Sequence[CargoMission]) -> List[List[CargoMission]]:
    """Return objective rows grouped into unique accepted contracts."""
    groups: dict[Tuple[str, ...], List[CargoMission]] = {}
    order: List[Tuple[str, ...]] = []
    for m in missions:
        key = m.contract_key()
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(m)
    return [groups[k] for k in order]


def group_start_epoch(group: Sequence[CargoMission]) -> Optional[float]:
    vals = [m.accepted_epoch() for m in group]
    vals = [v for v in vals if v is not None]
    return min(vals) if vals else None


def group_completed_epoch(group: Sequence[CargoMission]) -> Optional[float]:
    vals = [m.completed_epoch() for m in group]
    vals = [v for v in vals if v is not None]
    return max(vals) if vals else None


def group_payout(group: Sequence[CargoMission]) -> Optional[int]:
    vals = [m.payout_auec for m in group if m.payout_auec is not None]
    return vals[0] if vals else None


def group_completed(group: Sequence[CargoMission]) -> bool:
    return any(m.status.upper() == "COMPLETED" for m in group)


def group_abandoned(group: Sequence[CargoMission]) -> bool:
    return any(m.status.upper() == "ABANDONED" for m in group)


def group_active(group: Sequence[CargoMission]) -> bool:
    return not group_completed(group) and not group_abandoned(group)


def apply_event_to_group(group: Sequence[CargoMission], ev: CompletionEvent, mark_completed: bool, mark_abandoned: bool = False) -> None:
    for m in group:
        if mark_abandoned:
            m.status = "ABANDONED"
            if not m.completed_timestamp:
                m.completed_timestamp = ev.timestamp
        elif mark_completed:
            m.status = "COMPLETED"
            if not m.completed_timestamp:
                m.completed_timestamp = ev.timestamp
        if ev.amount_auec is not None and not mark_abandoned:
            m.payout_auec = ev.amount_auec
        if ev.raw and ev.raw not in m.raw:
            m.raw = m.raw + "\n--- completion/reward event ---\n" + ev.raw
        if m.status.upper() == "COMPLETED":
            if m.payout_auec is not None:
                m.notes = "Completed; payout detected from log (counted once per contract)"
            else:
                m.notes = "Completed; payout not visible in parsed log"
        elif m.status.upper() == "ABANDONED":
            m.notes = "Abandoned/failed; excluded from completed profit"


def select_best_group(candidates: Sequence[Sequence[CargoMission]], ev: CompletionEvent) -> Optional[List[CargoMission]]:
    """Pick the most likely contract group for a completion/reward event.

    Completion events are intentionally matched only by MissionId or by a visible
    contract title. The older route/commodity fallback was too aggressive and could
    mark a new active mission as completed just because it shared a destination.
    """
    if not candidates:
        return None
    ev_epoch = parse_log_timestamp_to_epoch(ev.timestamp)

    def accepted_before_event(g: Sequence[CargoMission]) -> bool:
        start = group_start_epoch(g)
        return ev_epoch is None or start is None or start <= ev_epoch + 5

    filtered = [list(g) for g in candidates if accepted_before_event(g)] or [list(g) for g in candidates]

    if ev.is_completion or ev.is_abandoned:
        incomplete = [g for g in filtered if group_active(g)]
        pool = incomplete or filtered
        # Oldest incomplete contract with that title/id is normally the one that just completed/ended.
        return sorted(pool, key=lambda g: (group_start_epoch(g) or 0, min((m.source_line for m in g), default=0)))[0]

    # Reward-only line: attach it to a completed contract missing payout.
    completed_missing_pay = [g for g in filtered if group_completed(g) and group_payout(g) is None]
    if completed_missing_pay:
        return sorted(completed_missing_pay, key=lambda g: (group_completed_epoch(g) or 0), reverse=True)[0]
    return None


def apply_completion_events(missions: Sequence[CargoMission], events: Sequence[CompletionEvent]) -> None:
    if not missions or not events:
        return

    for ev in events:
        groups = contract_groups(missions)
        candidates: List[List[CargoMission]] = []

        if ev.mission_id:
            ev_id = ev.mission_id.lower()
            candidates = [g for g in groups if any(m.mission_id and m.mission_id.lower() == ev_id for m in g)]
        elif ev.title:
            ev_title = normalize_contract_title(ev.title)
            if ev_title:
                # Prefer exact normalized title matches. Allow one-way containment only
                # when the string is long enough to avoid matching generic text.
                exact = [g for g in groups if any(m.title_key() == ev_title for m in g)]
                if exact:
                    candidates = exact
                elif len(ev_title) >= 18:
                    candidates = [g for g in groups if any((m.title_key() in ev_title or ev_title in m.title_key()) for m in g)]

        # Ignore route/commodity-only completion guesses. They caused false positives
        # with multi-drop contracts and repeated destinations.
        if not candidates:
            continue

        target = select_best_group(candidates, ev)
        if not target:
            continue

        if ev.is_abandoned:
            apply_event_to_group(target, ev, mark_completed=False, mark_abandoned=True)
        elif ev.is_completion:
            apply_event_to_group(target, ev, mark_completed=True)
        elif ev.amount_auec is not None:
            # Reward-only line: never mark a contract completed by money text alone.
            apply_event_to_group(target, ev, mark_completed=False)


def parse_log_data(text: str) -> Tuple[List[CargoMission], List[CompletionEvent]]:
    lines = text.splitlines()
    parsed: List[CargoMission] = []
    for source_line, block in build_blocks(lines):
        parsed.extend(parse_block(source_line, block))
    missions = merge_missions(parsed)
    missions = apply_contract_overrides(missions, VERIFIED_MISSION_OVERRIDES)
    events = parse_completion_events(lines)
    apply_completion_events(missions, events)
    return missions, events


def parse_log_text(text: str) -> List[CargoMission]:
    missions, _events = parse_log_data(text)
    return missions


def read_tail(path: Path, max_bytes: int = 2_000_000) -> str:
    with path.open("rb") as f:
        f.seek(0, os.SEEK_END)
        size = f.tell()
        f.seek(max(0, size - max_bytes), os.SEEK_SET)
        return f.read().decode("utf-8", errors="replace")


def guess_sc_log_paths() -> List[Path]:
    candidates: List[Path] = []
    roots = [
        Path(r"C:\Program Files\Roberts Space Industries\StarCitizen"),
        Path(r"C:\Program Files (x86)\Roberts Space Industries\StarCitizen"),
        Path(r"D:\StarCitizen\Game\StarCitizen"),
        Path(r"D:\Roberts Space Industries\StarCitizen"),
    ]
    for env in ["ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA", "USERPROFILE"]:
        if os.environ.get(env):
            roots.append(Path(os.environ[env]) / "Roberts Space Industries" / "StarCitizen")
    for root in roots:
        for branch in ["LIVE", "PTU", "EPTU", "TECH-PREVIEW"]:
            candidates.append(root / branch / "Game.log")
    out, seen = [], set()
    for p in candidates:
        key = str(p).lower()
        if key not in seen and p.exists():
            seen.add(key)
            out.append(p)
    return out


def manifest_rows(missions: Sequence[CargoMission]) -> List[dict]:
    """Full objective rows for exports/CLI. One row = one cargo objective."""
    rows = []
    for m in missions:
        rows.extend(m.rows())
    return rows


def grouped_manifest_rows(missions: Sequence[CargoMission], display_merge: bool = False) -> List[Tuple[dict, CargoMission]]:
    """Rows ordered/grouped by accepted contract.

    Tk's Treeview cannot truly merge cells. When display_merge=True, repeated
    contract-level cells are blanked after the first objective in a contract,
    which gives a merged-cell visual while keeping each pickup/drop-off row clear.
    HTML export uses real rowspans.
    """
    rows: List[Tuple[dict, CargoMission]] = []
    group_fields = ["Status", "Payout", "Duration", "Rank", "Confidence", "Notes"]
    for group in contract_groups(missions):
        for i, m in enumerate(group):
            row = m.rows()[0]
            if display_merge and i > 0:
                row = dict(row)
                for field in group_fields:
                    row[field] = ""
            rows.append((row, m))
    return rows


def logistics_matrix(missions: Sequence[CargoMission]) -> Tuple[List[str], List[str], dict[Tuple[str, str], float]]:
    """Build accepted-only cargo sorting matrix.

    Columns are route pairs: "Pickup → Drop-off". Rows are commodities.
    Cell values are total SCU that should be loaded/sorted for that route.
    Completed and abandoned contracts are excluded.
    """
    routes: List[str] = []
    commodities: List[str] = []
    totals: dict[Tuple[str, str], float] = {}
    for group in contract_groups(missions):
        if not group_active(group):
            continue
        for m in group:
            commodity = (m.commodity or "Unknown commodity").strip()
            if not commodity or commodity.lower() == "unknown commodity":
                continue
            route = f"{m.pickup} → {m.dropoff}"
            if not m.is_load_plannable():
                continue
            scu_val = float(str(m.scu).strip())
            if route not in routes:
                routes.append(route)
            if commodity not in commodities:
                commodities.append(commodity)
            totals[(commodity, route)] = totals.get((commodity, route), 0.0) + scu_val
    return commodities, routes, totals


def logistics_board(missions: Sequence[CargoMission]) -> Tuple[str, str, str, List[str], List[str], dict[Tuple[str, str], float]]:
    """Build an adaptive accepted-only logistics board.

    Returns: mode, fixed_text, axis_label, commodities, columns, totals.

    It avoids repeating the same pickup/drop-off in every column:
    - one pickup and multiple drop-offs -> fixed text is "Pickup: X", columns are drop-offs
    - multiple pickups and one drop-off -> fixed text is "Drop-off: Y", columns are pickups
    - many-to-many -> columns are full route strings
    """
    active_rows: List[CargoMission] = []
    for group in contract_groups(missions):
        if not group_active(group):
            continue
        for m in group:
            commodity = (m.commodity or "").strip()
            if not commodity or commodity.lower() == "unknown commodity":
                continue
            if not m.is_load_plannable():
                continue
            active_rows.append(m)

    if not active_rows:
        return "empty", "No active accepted cargo objectives", "routes", [], [], {}

    pickups: List[str] = []
    dropoffs: List[str] = []
    commodities: List[str] = []
    for m in active_rows:
        if m.pickup not in pickups:
            pickups.append(m.pickup)
        if m.dropoff not in dropoffs:
            dropoffs.append(m.dropoff)
        if m.commodity not in commodities:
            commodities.append(m.commodity)

    if len(pickups) == 1 and len(dropoffs) >= 1:
        mode = "single_pickup"
        fixed_text = f"Pickup: {pickups[0]}"
        axis_label = "drop-off locations"
        columns = dropoffs
        def col_for(m: CargoMission) -> str:
            return m.dropoff
    elif len(dropoffs) == 1 and len(pickups) >= 1:
        mode = "single_dropoff"
        fixed_text = f"Drop-off: {dropoffs[0]}"
        axis_label = "pickup locations"
        columns = pickups
        def col_for(m: CargoMission) -> str:
            return m.pickup
    else:
        mode = "routes"
        fixed_text = "Multiple pickup/drop-off routes"
        axis_label = "pickup → drop-off routes"
        columns = []
        def col_for(m: CargoMission) -> str:
            return f"{m.pickup} → {m.dropoff}"
        for m in active_rows:
            col = col_for(m)
            if col not in columns:
                columns.append(col)

    totals: dict[Tuple[str, str], float] = {}
    for m in active_rows:
        col = col_for(m)
        try:
            scu_val = float(str(m.scu).strip())
        except Exception:
            continue
        totals[(m.commodity, col)] = totals.get((m.commodity, col), 0.0) + scu_val

    return mode, fixed_text, axis_label, commodities, columns, totals


def logistics_sections(missions: Sequence[CargoMission]) -> List[dict]:
    """Build separate accepted-only route groups around repeated locations.

    The previous web board collapsed every many-to-many result into one generic
    "Multiple pickup/drop-off routes" block. This version keeps useful repeated
    locations visible:

    - one pickup used by several drop-offs -> one shared-pickup section
    - several pickups feeding one drop-off -> one shared-drop-off section
    - an unmatched one-pickup/one-drop-off route -> its own direct-route section

    Each objective is assigned once. When a dense route network could qualify for
    both orientations, the largest currently unassigned star is selected first.
    This prevents duplicate cargo while preserving the strongest location grouping.
    """
    active_rows: List[CargoMission] = []
    aggregate_sections: List[dict] = []
    for group in contract_groups(missions):
        if not group_active(group):
            continue

        aggregate_rows = [mission for mission in group if mission.quantity_scope == "aggregate"]
        aggregate_owner = next((mission for mission in aggregate_rows if mission.is_aggregate_load_plannable()), None)
        if aggregate_owner is not None:
            pickup_rows: List[Tuple[str, CargoMission]] = []
            for mission in aggregate_rows:
                pickup = (mission.pickup or "").strip()
                if pickup and pickup not in [location for location, _mission in pickup_rows]:
                    pickup_rows.append((pickup, mission))
            pickups = [location for location, _mission in pickup_rows]
            dropoffs = []
            for mission in aggregate_rows:
                dropoff = (mission.dropoff or "").strip()
                if dropoff and dropoff not in dropoffs:
                    dropoffs.append(dropoff)
            commodity = (aggregate_owner.commodity or "").strip()
            if commodity and commodity.lower() != "unknown commodity" and pickups and len(dropoffs) == 1:
                value = float(str(aggregate_owner.scu).strip())
                columns_payload = []
                for pickup, mission in pickup_rows:
                    member_identity = "\x1f".join(mission.stable_key())
                    checklist_id = hashlib.sha1(
                        ("aggregate-pickup\n" + member_identity).encode("utf-8", errors="replace")
                    ).hexdigest()[:20]
                    columns_payload.append({
                        "location": pickup,
                        "items": [{
                            "id": checklist_id,
                            "commodity": commodity,
                            "scu": "",
                            "scu_value": 0.0,
                            "status": "ACCEPTED",
                            "shared_quantity": True,
                            "shared_scu": format_scu(value),
                            "shared_scu_value": value,
                        }],
                        "total": "",
                        "shared_quantity": True,
                    })
                aggregate_sections.append({
                    "mode": "aggregate_pickups",
                    "fixed_location": dropoffs[0],
                    "pickup_options": pickups,
                    "columns": columns_payload,
                    "total": format_scu(value),
                    "shared_scu": format_scu(value),
                    "shared_scu_value": value,
                    "shared_loads": [{
                        "scu": format_scu(value),
                        "scu_value": value,
                        "item_ids": [item["id"] for column in columns_payload for item in column["items"]],
                    }],
                    "objective_count": len(columns_payload),
                    "route_row_count": len(aggregate_rows),
                })
            # Aggregate route rows must never fall through into per-location totals.
            continue

        for mission in group:
            commodity = (mission.commodity or "").strip()
            if not commodity or commodity.lower() == "unknown commodity":
                continue
            if not mission.is_load_plannable():
                continue
            active_rows.append(mission)

    # Merge aggregate contracts that converge on the same drop-off while
    # retaining each contract's own shared quantity/checklist membership.
    merged_aggregate_sections: List[dict] = []
    aggregate_by_dropoff: dict[str, dict] = {}
    for section in aggregate_sections:
        dropoff_key = str(section.get("fixed_location") or "").strip().casefold()
        existing = aggregate_by_dropoff.get(dropoff_key)
        if existing is None:
            aggregate_by_dropoff[dropoff_key] = section
            merged_aggregate_sections.append(section)
            continue
        columns_by_location = {
            str(column.get("location") or "").strip().casefold(): column
            for column in existing["columns"]
        }
        for column in section["columns"]:
            location_key = str(column.get("location") or "").strip().casefold()
            current = columns_by_location.get(location_key)
            if current is None:
                existing["columns"].append(column)
                columns_by_location[location_key] = column
            else:
                current["items"].extend(column.get("items") or [])
        known_pickups = {str(location).strip().casefold() for location in existing["pickup_options"]}
        for pickup in section["pickup_options"]:
            pickup_key = str(pickup).strip().casefold()
            if pickup_key not in known_pickups:
                existing["pickup_options"].append(pickup)
                known_pickups.add(pickup_key)
        existing["shared_loads"].extend(section.get("shared_loads") or [])
        combined_value = float(existing.get("shared_scu_value") or 0) + float(section.get("shared_scu_value") or 0)
        existing["total"] = format_scu(combined_value)
        existing["shared_scu"] = format_scu(combined_value)
        existing["shared_scu_value"] = combined_value
        existing["objective_count"] += int(section.get("objective_count") or 0)
        existing["route_row_count"] += int(section.get("route_row_count") or 0)
    aggregate_sections = merged_aggregate_sections

    if not active_rows:
        return aggregate_sections

    unassigned = set(range(len(active_rows)))
    selected: List[Tuple[str, str, List[int]]] = []

    # Greedily extract the strongest repeated-location stars. A candidate must
    # connect to at least two distinct opposite locations; multiple commodities
    # on one exact route remain a single direct route rather than a false group.
    while unassigned:
        candidates: List[Tuple[int, int, int, int, str, str, List[int]]] = []

        pickup_order: List[str] = []
        dropoff_order: List[str] = []
        for index in sorted(unassigned):
            mission = active_rows[index]
            if mission.pickup not in pickup_order:
                pickup_order.append(mission.pickup)
            if mission.dropoff not in dropoff_order:
                dropoff_order.append(mission.dropoff)

        for order, pickup in enumerate(pickup_order):
            indices = [i for i in sorted(unassigned) if active_rows[i].pickup == pickup]
            opposite = {active_rows[i].dropoff for i in indices}
            if len(opposite) >= 2:
                # tuple fields: distinct opposite locations, row count, pickup
                # preference for deterministic ties, inverse order, mode/location/data
                candidates.append((len(opposite), len(indices), 1, -order, "single_pickup", pickup, indices))

        for order, dropoff in enumerate(dropoff_order):
            indices = [i for i in sorted(unassigned) if active_rows[i].dropoff == dropoff]
            opposite = {active_rows[i].pickup for i in indices}
            if len(opposite) >= 2:
                candidates.append((len(opposite), len(indices), 0, -order, "single_dropoff", dropoff, indices))

        if not candidates:
            break

        _opposite_count, _row_count, _pickup_preference, _order, mode, location, indices = max(candidates)
        selected.append((mode, location, indices))
        unassigned.difference_update(indices)

    # Any remaining objectives are grouped only by their exact route. Each route
    # gets its own section, so unrelated direct routes are never put in a mixed box.
    direct_routes: dict[Tuple[str, str], List[int]] = {}
    for index in sorted(unassigned):
        mission = active_rows[index]
        direct_routes.setdefault((mission.pickup, mission.dropoff), []).append(index)
    for (pickup, _dropoff), indices in direct_routes.items():
        selected.append(("direct", pickup, indices))

    sections: List[dict] = []
    for mode, fixed_location, indices in selected:
        column_order: List[str] = []
        aggregate: dict[Tuple[str, str], float] = {}
        aggregate_members: dict[Tuple[str, str], List[str]] = {}
        commodity_order: dict[str, List[str]] = {}

        for index in indices:
            mission = active_rows[index]
            column = mission.dropoff if mode in ("single_pickup", "direct") else mission.pickup
            if column not in column_order:
                column_order.append(column)
                commodity_order[column] = []
            commodity = mission.commodity
            if commodity not in commodity_order[column]:
                commodity_order[column].append(commodity)
            value = float(str(mission.scu).strip())
            item_axis = (column, commodity)
            aggregate[item_axis] = aggregate.get(item_axis, 0.0) + value
            # A stable checklist identity follows the actual active objective(s),
            # not only the visible route text. This prevents a later identical
            # contract from inheriting an old checked state after the first one closes.
            aggregate_members.setdefault(item_axis, []).append("\x1f".join(mission.stable_key()))

        columns_payload = []
        section_total = 0.0
        for column in column_order:
            items = []
            column_total = 0.0
            for commodity in commodity_order[column]:
                value = aggregate.get((column, commodity), 0.0)
                if not value:
                    continue
                column_total += value
                member_identity = "\n".join(sorted(aggregate_members.get((column, commodity), [])))
                checklist_id = hashlib.sha1(member_identity.encode("utf-8", errors="replace")).hexdigest()[:20]
                items.append({
                    "id": checklist_id,
                    "commodity": commodity,
                    "scu": format_scu(value),
                    "scu_value": value,
                    "status": "ACCEPTED",
                })
            section_total += column_total
            columns_payload.append({
                "location": column,
                "items": items,
                "total": format_scu(column_total),
            })

        sections.append({
            "mode": mode,
            "fixed_location": fixed_location,
            "columns": columns_payload,
            "total": format_scu(section_total),
            "objective_count": len(indices),
        })

    return aggregate_sections + sections


def format_scu(value: float) -> str:
    if abs(value - int(value)) < 0.001:
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def active_quantity_summary(missions: Sequence[CargoMission]) -> dict:
    known = 0.0
    unknown = 0
    aggregate = 0
    for group in contract_groups(missions):
        if not group_active(group):
            continue
        aggregate_owner = next((mission for mission in group if mission.is_aggregate_load_plannable()), None)
        if aggregate_owner is not None:
            known += float(str(aggregate_owner.scu).strip())
            aggregate += 1
            # Blank aggregate rows are pickup-location placeholders, not missing
            # quantities. The one shared owner already represents the contract total.
            continue
        for mission in group:
            if not mission.commodity or mission.commodity.lower() == "unknown commodity":
                continue
            if mission.has_known_scu():
                known += float(str(mission.scu).strip())
            else:
                unknown += 1
    parts = [f"{format_scu(known)} SCU known"]
    if unknown:
        parts.append(f"{unknown} objective{'s' if unknown != 1 else ''} with unknown quantity")
    if aggregate:
        parts.append(f"{aggregate} shared-quantity contract{'s' if aggregate != 1 else ''}")
    return {
        "known_scu": known,
        "unknown_objectives": unknown,
        "aggregate_rows": aggregate,
        "summary": " + ".join(parts[:2]) + (f" · {parts[2]}" if len(parts) > 2 else ""),
    }


def session_stats(missions: Sequence[CargoMission], started_at: float, session_elapsed_override: Optional[float] = None) -> Tuple[int, int, int, float, float, float, float]:
    """Return accepted, completed, total, mission_elapsed_sec, mission_profit/hr, session_elapsed_sec, session_profit/hr.

    Stats are contract-based, not row-based. A multi-drop mission may produce 6
    manifest rows, but it is still one accepted mission and one payout.

    Mission profit/hr uses only completed contracts: first accepted timestamp of
    completed contracts -> latest completion timestamp. Active/incomplete contracts
    do not dilute this metric. Session profit/hr uses Reset Session -> now, so it
    includes planning, loading, bugs, idle time, and active unfinished work.
    """
    now = time.time()
    groups = contract_groups(missions)
    accepted_count = len(groups)
    completed_groups = [g for g in groups if group_completed(g)]
    completed_count = len(completed_groups)
    total = sum(group_payout(g) or 0 for g in completed_groups)

    session_elapsed_sec = max(0.0, float(session_elapsed_override)) if session_elapsed_override is not None else max(0.0, now - started_at)
    session_elapsed_hr = session_elapsed_sec / 3600.0 if session_elapsed_sec > 0 else 0.0
    session_profit_hr = total / session_elapsed_hr if session_elapsed_hr > 0 else 0.0

    starts = [group_start_epoch(g) for g in completed_groups]
    starts = [x for x in starts if x is not None]
    ends = [group_completed_epoch(g) for g in completed_groups]
    ends = [x for x in ends if x is not None]
    if starts and ends:
        mission_elapsed_sec = max(0.0, max(ends) - min(starts))
    elif completed_groups:
        # Fallback if SC log timestamps are missing.
        mission_elapsed_sec = session_elapsed_sec
    else:
        mission_elapsed_sec = 0.0

    mission_elapsed_hr = mission_elapsed_sec / 3600.0 if mission_elapsed_sec > 0 else 0.0
    mission_profit_hr = total / mission_elapsed_hr if mission_elapsed_hr > 0 else 0.0

    return accepted_count, completed_count, total, mission_elapsed_sec, mission_profit_hr, session_elapsed_sec, session_profit_hr


def export_csv(missions: Sequence[CargoMission], path: Path) -> None:
    fields = ["Status", "Pick up location", "Drop off location", "Commodity", "SCU", "Payout", "Duration", "Rank", "Confidence", "Notes", "Mission", "Accepted At", "Completed At"]
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in manifest_rows(missions):
            w.writerow({k: row.get(k, "") for k in fields})


def export_html(missions: Sequence[CargoMission], path: Path, started_at: Optional[float] = None, session_elapsed_override: Optional[float] = None) -> None:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    accepted, completed, total, mission_elapsed, mission_profit_hr, session_elapsed, session_profit_hr = session_stats(missions, started_at or time.time(), session_elapsed_override=session_elapsed_override)
    css = """
body{font-family:Segoe UI,Arial,sans-serif;margin:24px;background:#111;color:#eee}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:16px 0}.card{background:#181818;border:1px solid #333;border-radius:10px;padding:14px}.label{color:#aaa;font-size:12px;text-transform:uppercase;letter-spacing:.04em}.value{font-size:24px;font-weight:700;margin-top:4px}.sub{color:#aaa;font-size:12px;margin-top:4px}table{border-collapse:collapse;width:100%;background:#181818}th,td{border:1px solid #333;padding:8px;text-align:left;vertical-align:top}th{background:#242424;position:sticky;top:0}.low{color:#ffcf70}.accepted{color:#7ab0ff;font-weight:600}.done{color:#9dffa9;font-weight:600}.abandoned{color:#ff8888;font-weight:600}.muted{color:#aaa;font-size:12px}tr:nth-child(even){background:#151515}
"""
    cols = ["Status", "Pick up location", "Drop off location", "Commodity", "SCU", "Payout", "Duration", "Rank", "Confidence", "Notes"]
    group_fields = ["Status", "Payout", "Duration", "Rank", "Confidence", "Notes"]
    trs = []
    for group in contract_groups(missions):
        rowspan = max(1, len(group))
        for i, m in enumerate(group):
            r = m.rows()[0]
            cells = []
            for k in cols:
                if k in group_fields:
                    if i > 0:
                        continue
                    attrs = f" rowspan='{rowspan}'" if rowspan > 1 else ""
                else:
                    attrs = ""
                cls = ""
                if k == "Confidence" and int(r.get("Confidence") or 0) < 70:
                    cls = "low"
                if k == "Status":
                    status = str(r.get(k, "")).upper()
                    if status == "COMPLETED":
                        cls = "done"
                    elif status == "ACCEPTED":
                        cls = "accepted"
                    elif status == "ABANDONED":
                        cls = "abandoned"
                cls_attr = f" class='{cls}'" if cls else ""
                cells.append(f"<td{attrs}{cls_attr}>{html.escape(str(r.get(k, '')))}</td>")
            trs.append("<tr>%s</tr>" % "".join(cells))
    doc = f"""<!doctype html><html><head><meta charset='utf-8'><title>SC Hauling Manifest</title><style>{css}</style></head><body>
<h1>SC Hauling Manifest</h1><div class='muted'>Generated {html.escape(now)} · {APP_NAME} {APP_VERSION}</div>
<div class='cards'>
<div class='card'><div class='label'>Missions accepted</div><div class='value'>{accepted}</div></div>
<div class='card'><div class='label'>Missions completed</div><div class='value'>{completed}</div></div>
<div class='card'><div class='label'>Total profit</div><div class='value'>{format_auec(total)}</div><div class='sub'>aUEC</div></div>
<div class='card'><div class='label'>Mission profit/hr</div><div class='value'>{format_auec(int(mission_profit_hr))}</div><div class='sub'>aUEC/hr · elapsed {format_duration(mission_elapsed)}</div></div>
<div class='card'><div class='label'>Session profit/hr</div><div class='value'>{format_auec(int(session_profit_hr))}</div><div class='sub'>aUEC/hr · elapsed {format_duration(session_elapsed)}</div></div>
</div>
<table><thead><tr>{''.join('<th>'+h+'</th>' for h in cols)}</tr></thead><tbody>{''.join(trs)}</tbody></table>
</body></html>"""
    path.write_text(doc, encoding="utf-8")


# ---------------- GUI ----------------

def run_gui(default_log: Optional[str] = None) -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except Exception as e:
        print("Tkinter GUI is unavailable:", e, file=sys.stderr)
        sys.exit(1)

    class App:
        def __init__(self, root: "tk.Tk"):
            self.root = root
            self.root.title(f"{APP_NAME} {APP_VERSION}")
            self.missions: List[CargoMission] = []
            self.events: List[CompletionEvent] = []
            self.watch_stop = threading.Event()
            self.watch_thread: Optional[threading.Thread] = None
            self.last_size = 0
            self.watch_buffer = ""
            # Session-profit timer. This is intentionally separate from Reset Session:
            # Reset controls which missions are tracked; timer controls how session/hr is measured.
            self.session_started = time.time()
            self.timer_state = "stopped"  # stopped, running, paused, armed_first
            self.timer_start_epoch: Optional[float] = None
            self.timer_elapsed_before = 0.0
            self.logistics_window = None
            self.logistics_frame = None
            self.logistics_tree = None
            self.value_widgets: dict[str, object] = {}
            guessed = guess_sc_log_paths()
            self.log_var = tk.StringVar(value=default_log or (str(guessed[0]) if guessed else ""))
            self.status_var = tk.StringVar(value="Ready")
            self.card_vars: dict[str, tk.StringVar] = {}
            self.display_refs: List[CargoMission] = []
            self.build_ui()
            self.root.after(2000, self.tick_stats)

        def setup_theme(self):
            """Dark sci-fi theme used by the Tkinter UI.

            Tkinter is not a web renderer, so this is an approximation of the
            concept art using native widgets: dark panels, cyan outlines, green/
            blue/red status colors, and a more dashboard-like layout.
            """
            self.colors = {
                "bg": "#02070f",
                "bg2": "#04101b",
                "panel": "#061522",
                "panel2": "#0a1d2c",
                "panel3": "#0d2d42",
                "line": "#123e54",
                "line2": "#10a5c8",
                "cyan": "#6beaff",
                "cyan2": "#00b7ff",
                "blue": "#2c9bff",
                "green": "#35f281",
                "red": "#ff4f5f",
                "amber": "#ffc247",
                "text": "#d8edf6",
                "muted": "#7e9baa",
                "dark_text": "#06111c",
            }
            c = self.colors
            self.root.configure(bg=c["bg"])
            try:
                style = ttk.Style(self.root)
                style.theme_use("clam")
                style.configure("Sci.TFrame", background=c["bg"])
                style.configure("Sci.Panel.TFrame", background=c["panel"])
                style.configure("Sci.TLabel", background=c["bg"], foreground=c["text"], font=("Segoe UI", 9))
                style.configure("Sci.Panel.TLabel", background=c["panel"], foreground=c["text"], font=("Segoe UI", 9))
                style.configure("Sci.Treeview", background=c["panel"], fieldbackground=c["panel"], foreground=c["text"], borderwidth=0, rowheight=32, font=("Segoe UI", 9))
                style.configure("Sci.Treeview.Heading", background="#071927", foreground="#b7eaff", relief="flat", font=("Segoe UI", 8, "bold"))
                style.map("Sci.Treeview", background=[("selected", "#06374a")], foreground=[("selected", "#ffffff")])
                style.configure("Sci.Vertical.TScrollbar", background=c["panel2"], troughcolor=c["bg"], arrowcolor=c["cyan"], bordercolor=c["line"])
                style.configure("Sci.Horizontal.TScrollbar", background=c["panel2"], troughcolor=c["bg"], arrowcolor=c["cyan"], bordercolor=c["line"])
            except Exception:
                pass

        def panel(self, parent, bg=None, border=None, pad=0):
            c = self.colors
            return tk.Frame(parent, bg=bg or c["panel"], bd=0, highlightthickness=1, highlightbackground=border or c["line"], highlightcolor=border or c["line"], padx=pad, pady=pad)

        def sci_button(self, parent, text, command=None, variant="default", width=None):
            c = self.colors
            palette = {
                "default": (c["panel2"], c["text"], c["line"]),
                "primary": ("#092b3b", c["cyan"], c["cyan2"]),
                "green": ("#0b3226", c["green"], c["green"]),
                "red": ("#2d1117", c["red"], c["red"]),
                "amber": ("#2e2410", c["amber"], c["amber"]),
            }
            bg, fg, line = palette.get(variant, palette["default"])
            btn = tk.Button(
                parent,
                text=text,
                command=command,
                bg=bg,
                fg=fg,
                activebackground="#0c3447",
                activeforeground="#ffffff",
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=line,
                padx=10,
                pady=6,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2",
                width=width or 0,
            )
            return btn

        def section_title(self, parent, text, subtext=None):
            c = self.colors
            row = tk.Frame(parent, bg=parent.cget("bg"))
            row.pack(fill="x", padx=10, pady=(8, 4))
            tk.Label(row, text=text.upper(), bg=row.cget("bg"), fg=c["cyan"], font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left")
            if subtext:
                tk.Label(row, text="  " + subtext, bg=row.cget("bg"), fg=c["muted"], font=("Segoe UI", 8), anchor="w").pack(side="left")
            return row


        def _color_for_status(self, status: str) -> str:
            c = self.colors
            s = (status or "").upper()
            if s == "COMPLETED":
                return c["green"]
            if s == "ABANDONED" or s == "FAILED" or s == "CANCELLED":
                return c["red"]
            if s == "ACCEPTED":
                return c["blue"]
            if s == "IN PROGRESS":
                return c["cyan"]
            return c["muted"]

        def _row_bg_for_status(self, status: str, fallback: str = None) -> str:
            c = self.colors
            s = (status or "").upper()
            if s == "COMPLETED":
                return "#062416"
            if s == "ABANDONED" or s == "FAILED" or s == "CANCELLED":
                return "#22090f"
            if s == "ACCEPTED":
                return "#061522"
            return fallback or c["panel"]

        def _ellipsize(self, value, limit: int) -> str:
            value = str(value or "")
            if len(value) <= limit:
                return value
            return value[: max(0, limit - 1)] + "…"

        def _make_cell(self, parent, text, color=None, bg=None, font=None, anchor="w", padx=8, pady=7, wrap=0):
            c = self.colors
            lbl = tk.Label(
                parent,
                text=str(text or ""),
                bg=bg or parent.cget("bg"),
                fg=color or c["text"],
                font=font or ("Segoe UI", 9),
                anchor=anchor,
                justify="left",
                padx=padx,
                pady=pady,
                wraplength=wrap,
            )
            lbl.pack(fill="both", expand=True)
            return lbl

        def _bind_row(self, widget, row_index: int):
            def _click(_evt=None, idx=row_index):
                self.select_display_ref(idx)
            widget.bind("<Button-1>", _click)
            for child in widget.winfo_children():
                child.bind("<Button-1>", _click)

        def select_display_ref(self, idx: int):
            try:
                mission = self.display_refs[idx]
            except Exception:
                return
            self.status_var.set(f"Selected: {mission.status} · {mission.pickup} → {mission.dropoff} · {mission.commodity} {mission.scu} SCU")

        def render_contract_table(self):
            """Render the contract log as custom dark cells instead of Treeview.

            The native Treeview/Scrollbar looked like a test prototype on Windows.
            A custom grid keeps the selected concept style: dark body, neon text,
            no white scrollbars, and merged-looking contract fields.
            """
            if not hasattr(self, "contract_body") or self.contract_body is None:
                return
            c = self.colors
            for child in self.contract_body.winfo_children():
                child.destroy()
            self.display_refs = []
            rows = grouped_manifest_rows(self.missions, display_merge=True)
            if not rows:
                empty = tk.Frame(self.contract_body, bg=c["panel"], height=260)
                empty.pack(fill="both", expand=True)
                tk.Label(empty, text="NO HAULING CONTRACTS DETECTED", bg=c["panel"], fg=c["muted"], font=("Segoe UI", 12, "bold")).pack(expand=True)
                return

            # Column definitions: key, width, stretch weight, text length cap, wrap pixels.
            cols = [
                ("Status", 120, 0, 16, 105),
                ("Pick up location", 185, 1, 26, 170),
                ("Drop off location", 250, 2, 32, 230),
                ("Commodity", 125, 0, 18, 120),
                ("SCU", 70, 0, 8, 60),
                ("Payout", 120, 0, 16, 100),
                ("Duration", 95, 0, 12, 85),
                ("Rank", 110, 0, 16, 100),
                ("Confidence", 95, 0, 10, 80),
                ("Notes", 300, 2, 58, 285),
            ]
            table = tk.Frame(self.contract_body, bg=c["panel"], highlightthickness=1, highlightbackground=c["line"])
            table.pack(fill="both", expand=True)
            for i, (_key, width, weight, _cap, _wrap) in enumerate(cols):
                table.columnconfigure(i, minsize=width, weight=weight)

            # Header row.
            header = tk.Frame(table, bg="#081e2f", height=31)
            header.grid(row=0, column=0, columnspan=len(cols), sticky="ew")
            for i, (key, _width, _weight, _cap, _wrap) in enumerate(cols):
                cell = tk.Frame(table, bg="#081e2f", highlightthickness=1, highlightbackground="#11364c")
                cell.grid(row=0, column=i, sticky="nsew")
                self._make_cell(cell, key.upper(), color="#b7eaff", bg="#081e2f", font=("Segoe UI", 8, "bold"), anchor="center", pady=7)

            max_rows = 18
            for row_idx, (row, mission) in enumerate(rows[:max_rows], start=1):
                self.display_refs.append(mission)
                status = row.get("Status") or mission.status
                fg = self._color_for_status(status or mission.status)
                bg = self._row_bg_for_status(status or mission.status)
                if not row.get("Status"):
                    # Continuation rows inherit the status color but use normal body bg.
                    bg = c["panel"]
                for col_idx, (key, _width, _weight, cap, wrap) in enumerate(cols):
                    val = row.get(key, "")
                    cell = tk.Frame(table, bg=bg, highlightthickness=1, highlightbackground="#0b293a")
                    cell.grid(row=row_idx, column=col_idx, sticky="nsew")
                    color = c["text"]
                    if key == "Status" and val:
                        icon = {"COMPLETED": "✓", "ACCEPTED": "●", "ABANDONED": "✕"}.get(val.upper(), "•")
                        val = f"{icon}  {val}"
                        color = fg
                    elif key in ("Payout", "Duration", "Rank", "Confidence") and val:
                        color = fg if (status or mission.status).upper() == "COMPLETED" else self._color_for_status(mission.status)
                    elif key == "Commodity" and val:
                        color = c["cyan"] if str(val).lower() in ("hydrogen", "carbon") else c["blue"]
                    elif key in ("Pick up location", "Drop off location") and val:
                        color = c["text"] if (status or mission.status).upper() == "COMPLETED" else c["blue"]
                    elif key == "Notes" and val:
                        color = fg if (status or mission.status).upper() in ("COMPLETED", "ABANDONED") else c["blue"]
                    elif not val:
                        color = c["muted"]
                    val = self._ellipsize(val, cap)
                    anchor = "center" if key in ("SCU", "Duration", "Confidence") else "w"
                    font = ("Segoe UI", 9, "bold") if key in ("Status", "Payout") and val else ("Segoe UI", 9)
                    self._make_cell(cell, val, color=color, bg=bg, font=font, anchor=anchor, wrap=wrap)
                    self._bind_row(cell, row_idx - 1)
            if len(rows) > max_rows:
                notice = tk.Frame(table, bg=c["panel2"], highlightthickness=1, highlightbackground=c["line"])
                notice.grid(row=max_rows + 1, column=0, columnspan=len(cols), sticky="ew")
                self._make_cell(notice, f"… {len(rows) - max_rows} more rows hidden in dashboard view. Export CSV/HTML for full manifest.", color=c["amber"], bg=c["panel2"], font=("Segoe UI", 9, "bold"), anchor="w")

        def build_ui(self):
            self.setup_theme()
            c = self.colors
            self.root.geometry("1680x940")
            self.root.minsize(1450, 820)

            outer = tk.Frame(self.root, bg=c["bg"])
            outer.pack(fill="both", expand=True, padx=12, pady=10)

            # Header / command bar: close to the selected concept, but still pure Tkinter.
            header = tk.Frame(outer, bg=c["bg"])
            header.pack(fill="x", pady=(0, 8))
            title_box = self.panel(header, bg=c["bg"], border="#0e455c", pad=8)
            title_box.pack(side="left", fill="y", padx=(0, 12))
            tk.Label(title_box, text="◇", bg=c["bg"], fg=c["cyan"], font=("Segoe UI Symbol", 26, "bold")).pack(side="left", padx=(0, 10))
            title_text = tk.Frame(title_box, bg=c["bg"])
            title_text.pack(side="left")
            tk.Label(title_text, text="SC HAULING LOG TRACKER", bg=c["bg"], fg=c["text"], font=("Segoe UI", 14, "bold"), anchor="w").pack(anchor="w")
            tk.Label(title_text, text=f"v{APP_VERSION}  •  OPS CONSOLE", bg=c["bg"], fg=c["cyan"], font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")

            log_box = self.panel(header, bg=c["bg2"], border="#0e3b50", pad=5)
            log_box.pack(side="left", fill="x", expand=True, padx=(0, 10))
            tk.Label(log_box, text="GAME LOG:", bg=c["bg2"], fg=c["muted"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=(6, 8))
            log_entry = tk.Entry(log_box, textvariable=self.log_var, bg="#030a12", fg=c["text"], insertbackground=c["cyan"], relief="flat", bd=0, font=("Segoe UI", 9))
            log_entry.pack(side="left", fill="x", expand=True, ipady=6)

            actions = tk.Frame(header, bg=c["bg"])
            actions.pack(side="right")
            for text, cmd, variant in [
                ("BROWSE", self.browse, "default"),
                ("SCAN", self.scan, "default"),
                ("WATCHING", self.start_watch, "primary"),
                ("STOP WATCH", self.stop_watch, "red"),
                ("RESET SESSION", self.reset_session, "default"),
                ("EXPORT CSV", self.export_csv_gui, "default"),
                ("EXPORT HTML", self.export_html_gui, "default"),
            ]:
                self.sci_button(actions, text, cmd, variant=variant).pack(side="left", padx=3)

            stats_frame = tk.Frame(outer, bg=c["bg"])
            stats_frame.pack(fill="x", pady=(0, 10))
            self.build_stats_cards(stats_frame)

            middle = tk.Frame(outer, bg=c["bg"])
            middle.pack(fill="both", expand=True, pady=(0, 10))
            middle.columnconfigure(0, weight=1)
            middle.columnconfigure(1, weight=0)
            middle.rowconfigure(0, weight=1)

            # Contract log panel. Custom grid avoids native white Treeview scrollbars.
            contract_panel = self.panel(middle, bg=c["panel"], border=c["line2"], pad=0)
            contract_panel.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
            contract_header = tk.Frame(contract_panel, bg=c["panel"])
            contract_header.pack(fill="x", padx=14, pady=(10, 5))
            tk.Label(contract_header, text="CONTRACT LOG", bg=c["panel"], fg=c["cyan"], font=("Segoe UI", 11, "bold")).pack(side="left")
            tk.Label(contract_header, text="  active manifest", bg=c["panel"], fg=c["muted"], font=("Segoe UI", 8)).pack(side="left")
            tk.Label(contract_header, text="Sort by:  STATUS", bg="#061421", fg=c["muted"], font=("Segoe UI", 8), padx=10, pady=5, highlightthickness=1, highlightbackground=c["line"]).pack(side="right", padx=(8, 0))
            search = tk.Entry(contract_header, bg="#030a12", fg=c["muted"], insertbackground=c["cyan"], relief="flat", bd=0, font=("Segoe UI", 9), width=24)
            search.insert(0, "Search contracts…")
            search.pack(side="right", ipady=5, ipadx=8)
            self.contract_body = tk.Frame(contract_panel, bg=c["panel"])
            self.contract_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
            self.tree = None

            # Right sidebar.
            sidebar = tk.Frame(middle, bg=c["bg"], width=320)
            sidebar.grid(row=0, column=1, sticky="nsew")
            sidebar.grid_propagate(False)

            timer_panel = self.panel(sidebar, bg=c["panel"], border=c["line2"], pad=12)
            timer_panel.pack(fill="x", pady=(0, 10))
            tk.Label(timer_panel, text="SESSION TIMER", bg=c["panel"], fg=c["cyan"], font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
            self.timer_display_var = tk.StringVar(value="00:00")
            self.timer_state_var = tk.StringVar(value="STOPPED")
            tk.Label(timer_panel, textvariable=self.timer_display_var, bg=c["panel"], fg=c["cyan"], font=("Consolas", 26, "bold"), anchor="w").pack(anchor="w", pady=(12, 0))
            tk.Label(timer_panel, textvariable=self.timer_state_var, bg=c["panel"], fg=c["amber"], font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w", pady=(0, 9))
            self.sci_button(timer_panel, "START FROM FIRST", self.start_timer_from_first_mission, variant="green").pack(fill="x", pady=3)
            self.sci_button(timer_panel, "START FROM NOW", self.start_timer_now, variant="primary").pack(fill="x", pady=3)
            self.sci_button(timer_panel, "PAUSE / PLAY", self.toggle_pause_play_timer, variant="default").pack(fill="x", pady=3)

            status_panel = self.panel(sidebar, bg=c["panel"], border=c["line"], pad=12)
            status_panel.pack(fill="x", pady=(0, 10))
            tk.Label(status_panel, text="SESSION STATUS", bg=c["panel"], fg=c["cyan"], font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
            self.side_status_vars = {
                "completed": tk.StringVar(value="0 completed"),
                "accepted": tk.StringVar(value="0 accepted"),
                "profit": tk.StringVar(value="0 aUEC"),
                "rate": tk.StringVar(value="0 aUEC/hr"),
            }
            for key, label, color in [
                ("completed", "✓", c["green"]),
                ("accepted", "●", c["blue"]),
                ("profit", "¤", c["amber"]),
                ("rate", "↗", c["cyan"]),
            ]:
                row = tk.Frame(status_panel, bg=c["panel"])
                row.pack(fill="x", pady=5)
                tk.Label(row, text=label, bg=c["panel"], fg=color, font=("Segoe UI Symbol", 12, "bold"), width=3, anchor="w").pack(side="left")
                tk.Label(row, textvariable=self.side_status_vars[key], bg=c["panel"], fg=color, font=("Segoe UI", 9, "bold"), anchor="w").pack(side="left")

            legend_panel = self.panel(sidebar, bg=c["panel"], border=c["line"], pad=12)
            legend_panel.pack(fill="both", expand=True)
            tk.Label(legend_panel, text="STATUS LEGEND", bg=c["panel"], fg=c["cyan"], font=("Segoe UI", 10, "bold"), anchor="w").pack(anchor="w")
            for name, desc, color in [
                ("COMPLETED", "payout detected", c["green"]),
                ("ACCEPTED", "contract accepted", c["blue"]),
                ("IN PROGRESS", "timer running", c["cyan"]),
                ("ABANDONED", "failed/cancelled", c["red"]),
            ]:
                row = tk.Frame(legend_panel, bg=c["panel"])
                row.pack(fill="x", pady=6)
                tk.Label(row, text=name, bg=c["panel"], fg=color, font=("Segoe UI", 8, "bold"), width=12, anchor="w").pack(side="left")
                tk.Label(row, text=desc, bg=c["panel"], fg=c["muted"], font=("Segoe UI", 8), anchor="w").pack(side="left")

            # Bottom logistics board.
            bottom = self.panel(outer, bg=c["panel"], border=c["line2"], pad=0)
            bottom.pack(fill="x", expand=False)
            bottom.configure(height=258)
            bottom.pack_propagate(False)
            title = tk.Frame(bottom, bg=c["panel"])
            title.pack(fill="x", padx=14, pady=(10, 4))
            tk.Label(title, text="LOGISTICS BOARD", bg=c["panel"], fg=c["cyan"], font=("Segoe UI", 11, "bold"), anchor="w").pack(side="left")
            self.logistics_info_var = tk.StringVar(value="Accepted contracts only · planned cargo distribution")
            tk.Label(title, textvariable=self.logistics_info_var, bg=c["panel"], fg=c["muted"], font=("Segoe UI", 8), anchor="w").pack(side="left", padx=(14, 0))
            self.logistics_frame = tk.Frame(bottom, bg=c["panel"])
            self.logistics_frame.pack(fill="both", expand=True, padx=14, pady=(0, 12))
            self.logistics_tree = None
            self.raw = None

            footer = tk.Frame(outer, bg=c["bg2"], highlightthickness=1, highlightbackground=c["line"])
            footer.pack(fill="x", pady=(6, 0))
            tk.Label(footer, textvariable=self.status_var, bg=c["bg2"], fg=c["cyan"], font=("Segoe UI", 8, "bold"), anchor="w").pack(side="left", padx=10, pady=7)
            tk.Label(footer, text="● ONLINE", bg=c["bg2"], fg=c["green"], font=("Segoe UI", 8, "bold"), anchor="e").pack(side="right", padx=10)
        def browse(self):
            fn = filedialog.askopenfilename(title="Select Game.log", filetypes=[("Game.log", "Game.log"), ("Log files", "*.log"), ("All files", "*.*")])
            if fn:
                self.log_var.set(fn)

        def path(self) -> Optional[Path]:
            p = Path(self.log_var.get().strip().strip('"'))
            if not p.exists():
                messagebox.showerror(APP_NAME, f"Log file not found:\n{p}")
                return None
            return p

        def build_stats_cards(self, parent):
            c = self.colors
            specs = [
                ("accepted", "MISSIONS ACCEPTED", "unique contracts", "▤", c["blue"]),
                ("completed", "MISSIONS COMPLETED", "paid / completed contracts", "✓", c["green"]),
                ("profit", "TOTAL PROFIT", "completed payouts only", "▦", c["green"]),
                ("mission_rate", "MISSION PROFIT / HR", "mission elapsed 0:00", "◷", c["cyan"]),
                ("session_rate", "SESSION PROFIT / HR", "session timer stopped", "◴", c["amber"]),
            ]
            for key, label, sub_default, icon, accent in specs:
                frame = self.panel(parent, bg=c["panel"], border="#123e52", pad=0)
                frame.pack(side="left", fill="x", expand=True, padx=5)
                inner = tk.Frame(frame, bg=c["panel"], padx=16, pady=12)
                inner.pack(fill="both", expand=True)
                icon_box = tk.Frame(inner, bg="#061b2b", width=54, height=54, highlightthickness=1, highlightbackground=accent)
                icon_box.pack(side="left", padx=(0, 14))
                icon_box.pack_propagate(False)
                tk.Label(icon_box, text=icon, bg="#061b2b", fg=accent, font=("Segoe UI Symbol", 24, "bold")).pack(expand=True)
                text_box = tk.Frame(inner, bg=c["panel"])
                text_box.pack(side="left", fill="x", expand=True)
                tk.Label(text_box, text=label, bg=c["panel"], fg=c["muted"], font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")
                value = tk.StringVar(value="0")
                sub = tk.StringVar(value=sub_default)
                self.card_vars[key] = value
                self.card_vars[key + "_sub"] = sub
                value_label = tk.Label(text_box, textvariable=value, bg=c["panel"], fg=accent, font=("Segoe UI", 18, "bold"), anchor="w")
                sub_label = tk.Label(text_box, textvariable=sub, bg=c["panel"], fg=c["muted"], font=("Segoe UI", 8), anchor="w")
                value_label.pack(anchor="w", pady=(2, 0))
                sub_label.pack(anchor="w")
                self.value_widgets[key] = value_label
                self.value_widgets[key + "_sub"] = sub_label
                self.value_widgets[key + "_card"] = frame

        def earliest_accepted_epoch(self) -> Optional[float]:
            starts = [m.accepted_epoch() for m in self.missions]
            starts = [v for v in starts if v is not None]
            return min(starts) if starts else None

        def maybe_start_armed_first_timer(self):
            if self.timer_state != "armed_first":
                return
            first = self.earliest_accepted_epoch()
            if first is not None:
                self.timer_start_epoch = first
                self.timer_elapsed_before = 0.0
                self.timer_state = "running"
                self.status_var.set("Session timer started from first accepted mission.")

        def session_timer_elapsed(self) -> float:
            self.maybe_start_armed_first_timer()
            if self.timer_state == "running" and self.timer_start_epoch is not None:
                return max(0.0, self.timer_elapsed_before + (time.time() - self.timer_start_epoch))
            return max(0.0, self.timer_elapsed_before)

        def start_timer_from_first_mission(self):
            first = self.earliest_accepted_epoch()
            self.timer_elapsed_before = 0.0
            if first is None:
                self.timer_state = "armed_first"
                self.timer_start_epoch = None
                self.status_var.set("Session timer armed: it will start when the first mission is accepted.")
            else:
                self.timer_state = "running"
                self.timer_start_epoch = first
                self.status_var.set("Session timer started from the first accepted mission in the current table.")
            self.update_stats_label()

        def start_timer_now(self):
            self.timer_elapsed_before = 0.0
            self.timer_start_epoch = time.time()
            self.timer_state = "running"
            self.status_var.set("Session timer started from now.")
            self.update_stats_label()

        def toggle_pause_play_timer(self):
            if self.timer_state == "running" and self.timer_start_epoch is not None:
                self.timer_elapsed_before += max(0.0, time.time() - self.timer_start_epoch)
                self.timer_start_epoch = None
                self.timer_state = "paused"
                self.status_var.set("Session timer paused.")
            elif self.timer_state == "paused":
                self.timer_start_epoch = time.time()
                self.timer_state = "running"
                self.status_var.set("Session timer resumed.")
            elif self.timer_state == "armed_first":
                self.status_var.set("Timer is waiting for first accepted mission; accept a mission or start from now.")
            else:
                # Play from a stopped state starts from now without clearing tracked missions.
                self.timer_elapsed_before = 0.0
                self.timer_start_epoch = time.time()
                self.timer_state = "running"
                self.status_var.set("Session timer started from now.")
            self.update_stats_label()

        def update_stats_label(self):
            session_elapsed_override = self.session_timer_elapsed()
            accepted, completed, total, mission_elapsed, mission_profit_hr, session_elapsed, session_profit_hr = session_stats(
                self.missions, self.session_started, session_elapsed_override=session_elapsed_override
            )
            if not self.card_vars:
                return
            self.card_vars["accepted"].set(str(accepted))
            self.card_vars["accepted_sub"].set("unique contracts")
            self.card_vars["completed"].set(str(completed))
            self.card_vars["completed_sub"].set("paid / completed contracts")
            self.card_vars["profit"].set(f"{format_auec(total)} aUEC")
            self.card_vars["profit_sub"].set("completed payouts only")
            self.card_vars["mission_rate"].set(f"{format_auec(int(mission_profit_hr))} aUEC/hr")
            self.card_vars["mission_rate_sub"].set(f"mission elapsed {format_duration(mission_elapsed)}")
            self.card_vars["session_rate"].set(f"{format_auec(int(session_profit_hr))} aUEC/hr")
            timer_note = {
                "running": "timer running",
                "paused": "timer paused",
                "stopped": "timer stopped",
                "armed_first": "waiting for first accepted mission",
            }.get(self.timer_state, self.timer_state)
            self.card_vars["session_rate_sub"].set(f"session elapsed {format_duration(session_elapsed)} · {timer_note}")

            c = self.colors
            colors = {
                "accepted": c["blue"] if accepted else c["muted"],
                "completed": c["green"] if completed else c["muted"],
                "profit": c["green"] if total > 0 else c["muted"],
                "mission_rate": c["green"] if completed else (c["blue"] if accepted else c["muted"]),
                "session_rate": c["blue"] if self.timer_state in ("running", "armed_first") else (c["amber"] if self.timer_state == "paused" else (c["green"] if total > 0 else c["muted"])),
            }
            for key, color in colors.items():
                widget = self.value_widgets.get(key)
                if widget is not None:
                    try:
                        widget.configure(fg=color)
                    except Exception:
                        pass
            if hasattr(self, "timer_display_var"):
                self.timer_display_var.set(format_duration(session_elapsed))
            if hasattr(self, "timer_state_var"):
                state_label = {
                    "running": "RUNNING",
                    "paused": "PAUSED",
                    "stopped": "STOPPED",
                    "armed_first": "WAITING FOR FIRST ACCEPTED MISSION",
                }.get(self.timer_state, self.timer_state.upper())
                self.timer_state_var.set(state_label)
            if hasattr(self, "side_status_vars"):
                self.side_status_vars["completed"].set(f"{completed} completed")
                self.side_status_vars["accepted"].set(f"{accepted} accepted")
                self.side_status_vars["profit"].set(f"{format_auec(total)} aUEC")
                self.side_status_vars["rate"].set(f"{format_auec(int(session_profit_hr))} aUEC/hr")

        def tick_stats(self):
            # Re-render while contracts are active so accepted-row duration timers keep running.
            if self.missions and any(group_active(g) for g in contract_groups(self.missions)):
                self.refresh()
            else:
                self.update_stats_label()
            self.root.after(1000, self.tick_stats)

        def add_update(self, new_missions: Sequence[CargoMission], new_events: Sequence[CompletionEvent]) -> int:
            before = [(m.stable_key(), m.score(), m.status, m.payout_auec) for m in self.missions]
            existing_event_keys = {e.key() for e in self.events}
            for e in new_events:
                if e.key() not in existing_event_keys:
                    self.events.append(e)
                    existing_event_keys.add(e.key())
            self.missions = merge_missions([*self.missions, *new_missions])
            apply_completion_events(self.missions, self.events)
            self.missions = merge_missions(self.missions)
            after = [(m.stable_key(), m.score(), m.status, m.payout_auec) for m in self.missions]
            return 1 if before != after else 0

        def scan(self):
            p = self.path()
            if not p:
                return
            try:
                tail_text = read_tail(p)
                self.missions, self.events = parse_log_data(tail_text)
                self.watch_buffer = tail_text[-300000:]
                self.last_size = p.stat().st_size
                self.refresh()
                self.status_var.set(f"Scanned {p.name}: {len(self.missions)} hauling mission(s), {len(manifest_rows(self.missions))} table row(s), {len(self.events)} completion/reward event(s).")
            except Exception as e:
                messagebox.showerror(APP_NAME, f"Scan failed:\n{e}")

        def refresh(self):
            apply_completion_events(self.missions, self.events)
            self.missions = merge_missions(self.missions)
            self.render_contract_table()
            self.update_stats_label()
            self.refresh_logistics_window()

        def refresh_logistics_window(self):
            """Refresh the embedded logistics cargo deck.

            Destination cards are intentionally used instead of a spreadsheet-style
            Treeview. This matches the selected concept more closely and is easier
            to use while physically sorting boxes on a cargo deck.
            """
            if self.logistics_frame is None:
                return
            c = self.colors
            try:
                for child in self.logistics_frame.winfo_children():
                    child.destroy()
                mode, fixed_text, axis_label, commodities, columns, totals = logistics_board(self.missions)
                if hasattr(self, "logistics_info_var"):
                    if commodities and columns:
                        self.logistics_info_var.set(f"{fixed_text} · accepted contracts only · destination cards show total SCU")
                    else:
                        self.logistics_info_var.set("No active accepted cargo objectives detected.")
                if not commodities or not columns:
                    empty = self.panel(self.logistics_frame, bg=c["panel2"], border=c["line"], pad=18)
                    empty.pack(fill="both", expand=True)
                    tk.Label(empty, text="NO ACTIVE ACCEPTED CARGO OBJECTIVES", bg=c["panel2"], fg=c["muted"], font=("Segoe UI", 11, "bold")).pack(expand=True)
                    return

                board = tk.Frame(self.logistics_frame, bg=c["panel"])
                board.pack(fill="both", expand=True)
                board.columnconfigure(0, weight=0)
                board.columnconfigure(1, weight=1)

                fixed_card = self.panel(board, bg="#061927", border=c["line2"], pad=14)
                fixed_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
                fixed_card.configure(width=240)
                fixed_card.grid_propagate(False)
                if mode == "single_pickup":
                    title = "PICK UP LOCATION (SHARED)"
                    location = fixed_text.replace("Pickup:", "").strip()
                    desc = "All active contracts originate here"
                    icon = "⌖"
                elif mode == "single_dropoff":
                    title = "DROP OFF LOCATION (SHARED)"
                    location = fixed_text.replace("Drop-off:", "").strip()
                    desc = "All active contracts deliver here"
                    icon = "◇"
                else:
                    title = "MIXED ROUTES"
                    location = "MULTIPLE ROUTES"
                    desc = "Cards show pickup → drop-off routes"
                    icon = "⇄"
                tk.Label(fixed_card, text=f"{icon} {title}", bg="#061927", fg=c["cyan"], font=("Segoe UI", 8, "bold"), anchor="w").pack(anchor="w")
                tk.Label(fixed_card, text=location.upper(), bg="#061927", fg=c["cyan"], font=("Segoe UI", 16, "bold"), anchor="w", wraplength=205).pack(anchor="w", pady=(26, 8))
                tk.Label(fixed_card, text=desc, bg="#061927", fg=c["muted"], font=("Segoe UI", 9), anchor="w", wraplength=205).pack(anchor="w")

                deck = tk.Frame(board, bg=c["panel"])
                deck.grid(row=0, column=1, sticky="nsew")
                # Fit the common 4-column case like the concept. Wrap additional cards.
                cards_per_row = 4 if len(columns) <= 4 else 5
                for j in range(cards_per_row):
                    deck.columnconfigure(j, weight=1, uniform="destcard")

                for j, col in enumerate(columns):
                    r = j // cards_per_row
                    cc = j % cards_per_row
                    card = self.panel(deck, bg="#071b2a", border=c["line"], pad=0)
                    card.grid(row=r, column=cc, sticky="nsew", padx=(0 if cc == 0 else 8, 0), pady=(0 if r == 0 else 8, 0))
                    card.configure(height=196)
                    card.grid_propagate(False)
                    head = tk.Frame(card, bg="#082235", highlightthickness=1, highlightbackground=c["line"])
                    head.pack(fill="x")
                    tk.Label(head, text="▧", bg="#082235", fg=c["cyan"], font=("Segoe UI Symbol", 14, "bold")).pack(side="left", padx=(10, 6), pady=9)
                    tk.Label(head, text=str(col).upper(), bg="#082235", fg=c["text"], font=("Segoe UI", 9, "bold"), anchor="w", justify="left", wraplength=210).pack(side="left", fill="x", expand=True, pady=9)

                    body = tk.Frame(card, bg="#071b2a")
                    body.pack(fill="both", expand=True, padx=11, pady=7)
                    total = 0.0
                    used = False
                    for commodity in commodities:
                        value = totals.get((commodity, col), 0.0)
                        if not value:
                            continue
                        used = True
                        total += value
                        row = tk.Frame(body, bg="#071b2a")
                        row.pack(fill="x", pady=4)
                        color = c["green"] if commodity.lower() == "hydrogen" else (c["blue"] if commodity.lower() == "quartz" else c["cyan"])
                        tk.Label(row, text="▣", bg="#071b2a", fg=color, font=("Segoe UI Symbol", 11, "bold"), width=2, anchor="w").pack(side="left")
                        tk.Label(row, text=commodity, bg="#071b2a", fg=color, font=("Segoe UI", 10, "bold"), anchor="w").pack(side="left", fill="x", expand=True)
                        tk.Label(row, text=f"{format_scu(value)} SCU", bg="#071b2a", fg=c["text"], font=("Segoe UI", 10, "bold"), anchor="e").pack(side="right")
                    if not used:
                        tk.Label(body, text="—", bg="#071b2a", fg=c["muted"], font=("Segoe UI", 16, "bold")).pack(expand=True)
                    foot = tk.Frame(card, bg="#061522", highlightthickness=1, highlightbackground=c["line"])
                    foot.pack(fill="x", side="bottom")
                    tk.Label(foot, text="TOTAL", bg="#061522", fg=c["muted"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=10, pady=7)
                    tk.Label(foot, text=f"{format_scu(total)} SCU" if total else "—", bg="#061522", fg=c["cyan"] if total else c["muted"], font=("Segoe UI", 10, "bold")).pack(side="right", padx=10, pady=7)
                self.logistics_tree = None
            except Exception as e:
                err = self.panel(self.logistics_frame, bg=c["panel2"], border=c["red"], pad=12)
                err.pack(fill="x")
                tk.Label(err, text=f"Logistics board error: {e}", bg=c["panel2"], fg=c["red"], font=("Segoe UI", 9, "bold")).pack(anchor="w")

        def on_select(self, _evt=None):
            # Kept for compatibility with older Treeview builds. v1.5 uses custom rows.
            return

        def start_watch(self):
            p = self.path()
            if not p:
                return
            if self.watch_thread and self.watch_thread.is_alive():
                self.status_var.set("Already watching")
                return
            if not self.missions:
                self.scan()
            self.last_size = p.stat().st_size
            self.watch_stop.clear()
            self.watch_thread = threading.Thread(target=self.watch_loop, args=(p,), daemon=True)
            self.watch_thread.start()
            self.status_var.set(f"Watching {p}")

        def stop_watch(self):
            self.watch_stop.set()
            self.status_var.set("Watch stopped")

        def reset_session(self):
            p = Path(self.log_var.get().strip().strip('"'))
            self.missions = []
            self.events = []
            self.watch_buffer = ""
            self.session_started = time.time()
            self.timer_state = "stopped"
            self.timer_start_epoch = None
            self.timer_elapsed_before = 0.0
            if p.exists():
                try:
                    self.last_size = p.stat().st_size
                except Exception:
                    pass
            self.refresh()
            if self.raw is not None:
                self.raw.delete("1.0", "end")
            self.status_var.set("Session reset. Start Watch to track only new contracts/completions from this point.")

        def watch_loop(self, p: Path):
            while not self.watch_stop.is_set():
                try:
                    size = p.stat().st_size
                    if size < self.last_size:
                        self.missions = []
                        self.events = []
                        self.watch_buffer = ""
                        self.session_started = time.time()
                        self.last_size = 0
                        self.root.after(0, self.refresh)
                        self.root.after(0, lambda: self.status_var.set("New Game.log session detected; cleared current session state."))
                    if size > self.last_size:
                        with p.open("rb") as f:
                            f.seek(self.last_size)
                            new_text = f.read().decode("utf-8", errors="replace")
                        self.last_size = size
                        # Parse a rolling buffer, not only the last chunk. SC often logs
                        # accepted-contract and objective lines in separate bursts;
                        # parsing only the newest chunk misses stacked contracts.
                        self.watch_buffer = (self.watch_buffer + new_text)[-300000:]
                        new_missions, new_events = parse_log_data(self.watch_buffer)
                        if new_missions or new_events:
                            changed = self.add_update(new_missions, new_events)
                            if changed:
                                self.root.after(0, self.refresh)
                                self.root.after(0, lambda nm=len(new_missions), ne=len(new_events): self.status_var.set(f"Detected {nm} mission update(s), {ne} completion/reward event(s)."))
                            else:
                                self.root.after(0, lambda: self.status_var.set("Ignored duplicate mission/reward notification."))
                except Exception as e:
                    self.root.after(0, lambda e=e: self.status_var.set(f"Watch error: {e}"))
                time.sleep(1.5)

        def export_csv_gui(self):
            if not self.missions:
                messagebox.showinfo(APP_NAME, "No rows to export.")
                return
            fn = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="sc_hauling_manifest.csv")
            if fn:
                export_csv(self.missions, Path(fn))
                self.status_var.set(f"Exported CSV: {fn}")

        def export_html_gui(self):
            if not self.missions:
                messagebox.showinfo(APP_NAME, "No rows to export.")
                return
            fn = filedialog.asksaveasfilename(defaultextension=".html", filetypes=[("HTML", "*.html")], initialfile="sc_hauling_manifest.html")
            if fn:
                export_html(self.missions, Path(fn), self.session_started, self.session_timer_elapsed())
                self.status_var.set(f"Exported HTML: {fn}")

    root = tk.Tk()
    App(root)
    root.mainloop()


# ---------------- Local Web Dashboard ----------------

def _migrate_legacy_app_data(root: Path, path: Path) -> None:
    """Move data from former Windows folder names into ``path`` once."""
    if path.exists():
        return
    for legacy_name in LEGACY_APP_DATA_FOLDERS:
        legacy = root / legacy_name
        if not legacy.exists() or legacy == path:
            continue
        try:
            legacy.replace(path)
        except Exception:
            try:
                shutil.copytree(legacy, path, dirs_exist_ok=True)
                shutil.rmtree(legacy, ignore_errors=True)
            except Exception:
                # Never prevent startup because a legacy directory could not be
                # migrated. New data can still be written to the SCHT folder.
                pass
        break


def app_data_directory() -> Path:
    r"""Return SCHT's writable per-user data directory.

    Windows builds now use ``%LOCALAPPDATA%\SCHT``. The first launch after
    upgrading moves the former ``SC Hauling Log Tracker`` directory so existing
    settings, corrections, checklist state, and WebView storage are preserved.
    """
    if os.name == "nt":
        root = Path(os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or str(Path.home()))
        path = root / APP_DATA_FOLDER
        _migrate_legacy_app_data(root, path)
    else:
        path = Path.home() / ".scht"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json_object(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json_object(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


def load_app_settings() -> dict:
    return _read_json_object(app_data_directory() / "app-settings.json")


def update_app_settings(**changes) -> None:
    path = app_data_directory() / "app-settings.json"
    data = _read_json_object(path)
    data.update(changes)
    _write_json_object(path, data)


def show_native_message(title: str, message: str, error: bool = False) -> None:
    """Show a useful startup message even in a windowed PyInstaller build."""
    if os.name == "nt":
        try:
            import ctypes
            flags = 0x00000010 if error else 0x00000040
            ctypes.windll.user32.MessageBoxW(None, str(message), str(title), flags)
            return
        except Exception:
            pass
    print(f"{title}: {message}", file=sys.stderr if error else sys.stdout)


def overlay_diagnostic_log(message: str) -> None:
    """Append overlay companion diagnostics without requiring a console window."""
    try:
        path = app_data_directory() / "overlay-process.log"
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(f"[{stamp}] pid={os.getpid()} {message}\n")
    except Exception:
        pass


def main_window_diagnostic_log(message: str) -> None:
    """Append main desktop-window diagnostics without requiring a console window."""
    try:
        path = app_data_directory() / "main-window.log"
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8", errors="replace") as handle:
            handle.write(f"[{stamp}] pid={os.getpid()} {message}\n")
    except Exception:
        pass


def process_is_running(pid: Optional[int]) -> bool:
    """Check process liveness without sending a signal that can kill it on Windows.

    Python's os.kill(pid, 0) is a harmless existence check on POSIX, but on
    Windows non-console signals are implemented with TerminateProcess. Passing
    zero can therefore terminate the parent application instead of probing it.
    """
    try:
        pid_value = int(pid or 0)
    except Exception:
        return False
    if pid_value <= 0:
        return False

    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            SYNCHRONIZE = 0x00100000
            WAIT_TIMEOUT = 0x00000102

            kernel32 = ctypes.windll.kernel32
            kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle.restype = wintypes.BOOL

            handle = kernel32.OpenProcess(
                PROCESS_QUERY_LIMITED_INFORMATION | SYNCHRONIZE,
                False,
                pid_value,
            )
            if not handle:
                # Access denied does not mean the process has exited. Avoid
                # closing the overlay on an inconclusive liveness probe.
                try:
                    return int(kernel32.GetLastError()) == 5
                except Exception:
                    return False
            try:
                wait_result = int(kernel32.WaitForSingleObject(handle, 0))
                if wait_result == 0:  # WAIT_OBJECT_0: process has exited
                    return False
                if wait_result == WAIT_TIMEOUT:
                    return True
                # WAIT_FAILED or another unexpected result is inconclusive.
                return True
            finally:
                kernel32.CloseHandle(handle)
        except Exception:
            # A failed check must not close a valid overlay. The main process
            # explicitly terminates the child during normal shutdown anyway.
            return True

    try:
        os.kill(pid_value, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False


class SingleInstanceGuard:
    """Keep the normal desktop application to one process per Windows user."""

    def __init__(self) -> None:
        self.handle = None
        self.acquired = True
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes
            kernel32 = ctypes.windll.kernel32
            kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            self.handle = kernel32.CreateMutexW(None, False, "Local\\SC_Hauling_Log_Tracker_Desktop")
            self.acquired = bool(self.handle) and int(kernel32.GetLastError()) != 183
        except Exception:
            self.handle = None
            self.acquired = True

    def close(self) -> None:
        if self.handle and os.name == "nt":
            try:
                import ctypes
                ctypes.windll.kernel32.CloseHandle(self.handle)
            except Exception:
                pass
        self.handle = None


OVERLAY_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SC Hauling Overlay</title>
<link rel="icon" type="image/png" href="/assets/sc_hauling_logo.png">
<style>
:root{--blue:#5aa7ff;--green:#49eda0;--red:#ff6476;--purple:#8f76ff;--text:#f4f5ff;--soft:#c8cbe0;--muted:#8e93aa;--line:rgba(154,147,203,.22);--type-meta:9px;--type-ui:10px;--type-control:9.5px;--type-heading:12px;--weight-body:700;--weight-control:700;--weight-strong:900}
*{box-sizing:border-box}html,body{position:fixed;inset:0;width:100%;height:100%;margin:0;background:#0b0b12;color:var(--text);font-family:"Segoe UI Variable Text","Segoe UI",Arial,sans-serif;overflow:hidden;overscroll-behavior:none;scroll-behavior:auto}button,input{font:inherit}
.shell{position:absolute;inset:0;min-width:0;min-height:0;display:grid;grid-template-rows:44px auto minmax(0,1fr) 25px;background:#0c0c13;border:1px solid rgba(151,137,235,.34);border-radius:12px;overflow:hidden;box-shadow:0 14px 38px rgba(0,0,0,.48)}
.titlebar{position:relative;z-index:20;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 7px 0 8px;background:linear-gradient(180deg,#232134,#15141f);border-bottom:1px solid var(--line)}.title-zone{position:relative;min-width:0;flex:1;height:100%}.titlecopy{min-width:0;width:100%;height:100%;display:flex;align-items:center;cursor:move;user-select:none}.titletext{min-width:0;display:flex;flex-direction:column;justify-content:center}.position-locked .titlecopy{cursor:default}.titlecopy strong{display:block;font-size:11px;font-weight:950;letter-spacing:.15px}.titlecopy small{display:block;margin-top:2px;color:var(--muted);font-size:8px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.position-lock-shield{display:none;position:absolute;inset:0;z-index:5;cursor:default;background:transparent}.position-locked .position-lock-shield{display:block}.window-actions{display:flex;align-items:center;gap:4px}.icon-btn{width:29px;height:29px;padding:0;border:1px solid rgba(255,255,255,.09);border-radius:9px;background:rgba(255,255,255,.035);color:#dfe2f6;display:grid;place-items:center;cursor:pointer;transition:.14s}.icon-btn svg{width:14px;height:14px;fill:currentColor;pointer-events:none}.icon-btn:hover,.icon-btn[aria-expanded="true"]{border-color:rgba(90,167,255,.48);background:rgba(90,167,255,.10)}.icon-btn.danger:hover{border-color:rgba(255,100,118,.5);color:var(--red)}
.settings-menu{position:absolute;z-index:40;top:39px;right:7px;width:230px;padding:10px;border:1px solid rgba(151,137,235,.34);border-radius:11px;background:#171622;box-shadow:0 16px 34px rgba(0,0,0,.58);transform-origin:top right}.settings-menu[hidden]{display:none}.settings-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:9px}.settings-head strong{font-size:10px;font-weight:950}.settings-head small{color:var(--muted);font-size:7px;text-transform:uppercase;letter-spacing:.4px}.setting-row{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:10px;align-items:center;min-height:36px;padding:6px 1px;border-top:1px solid rgba(255,255,255,.055)}.setting-row:first-of-type{border-top:0}.setting-copy strong{display:block;font-size:9px;font-weight:850}.setting-copy small{display:block;margin-top:2px;color:var(--muted);font-size:7.5px;line-height:1.25}.opacity-control{display:flex;align-items:center;gap:7px}.opacity-control input{width:82px;accent-color:var(--purple)}.opacity-value{width:31px;text-align:right;color:#dfe2f6;font:800 8px Consolas,monospace}.switch{position:relative;width:34px;height:19px;padding:0;border:1px solid #4b4960;border-radius:99px;background:#11111a;cursor:pointer;transition:.15s}.switch:after{content:"";position:absolute;top:2px;left:2px;width:13px;height:13px;border-radius:50%;background:#9297aa;transition:.15s}.switch[aria-pressed="true"]{border-color:rgba(73,237,160,.55);background:rgba(73,237,160,.16)}.switch[aria-pressed="true"]:after{left:17px;background:var(--green);box-shadow:0 0 8px rgba(73,237,160,.25)}
.summary{position:relative;z-index:4;display:grid;grid-template-columns:1fr auto;gap:9px;align-items:center;padding:8px 11px;border-bottom:1px solid rgba(255,255,255,.055);background:rgba(255,255,255,.018)}.progress-copy strong{display:block;color:var(--blue);font:900 15px Consolas,monospace}.progress-copy small{display:block;margin-top:2px;color:var(--muted);font-size:8px;font-weight:900;text-transform:uppercase;letter-spacing:.45px}.summary.complete .progress-copy strong,.summary.complete .progress-copy small{color:var(--green)}.summary-actions{display:flex;align-items:center;gap:6px}.small-btn{height:27px;border:1px solid rgba(255,255,255,.10);border-radius:8px;background:#151520;color:#c7cbdf;padding:0 9px;font-family:"Segoe UI Variable Text","Segoe UI",Arial,sans-serif;font-size:var(--type-control);font-weight:var(--weight-control);line-height:1;text-transform:none;letter-spacing:.01em;font-kerning:normal;-webkit-font-smoothing:antialiased;cursor:pointer}.small-btn:hover,.small-btn.active{border-color:rgba(143,118,255,.52);color:#fff}.small-btn.active{background:rgba(90,167,255,.11)}.small-btn:disabled{opacity:.38;cursor:default}
.board{min-height:0;overflow:auto;padding:8px;scrollbar-width:thin;scrollbar-color:#45405e transparent;overscroll-behavior:contain;overflow-anchor:none;scroll-behavior:auto}.empty{padding:28px 16px;text-align:center;color:var(--muted);font-size:10px;line-height:1.45;border:1px dashed var(--line);border-radius:11px}.group{border:1px solid var(--line);border-radius:11px;overflow:hidden;background:rgba(23,22,34,.70)}.group+.group{margin-top:9px}.group-head{padding:9px 10px;background:rgba(143,118,255,.065);border-bottom:1px solid var(--line)}.group-head small{display:block;color:#ad96ff;font-size:7.5px;font-weight:950;text-transform:uppercase;letter-spacing:.55px}.group-head strong{display:block;margin-top:3px;font-size:12px;font-weight:950;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.group-head span{display:block;margin-top:3px;color:var(--muted);font-size:8px}.route{padding:8px 9px}.route.empty-route{display:none}.route+.route{border-top:1px solid rgba(255,255,255,.055)}.route-title{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:4px}.route-title strong{font-size:8.5px;text-transform:uppercase;letter-spacing:.28px;color:#dfe2f4;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.route-title span{font:800 8px Consolas,monospace;color:var(--muted);white-space:nowrap}.cargo-row{display:grid;grid-template-columns:18px 18px minmax(0,1fr) auto;gap:7px;align-items:center;min-height:34px;padding:5px 4px;border-radius:8px;cursor:pointer;user-select:none}.cargo-row:hover{background:rgba(90,167,255,.055)}.cargo-row.loaded{color:var(--green);background:rgba(73,237,160,.04)}.cargo-row.loaded .cargo-name,.cargo-row.loaded .scu{opacity:.56}.cargo-row.loaded .cargo-name{text-decoration:line-through}.compact .cargo-row{min-height:28px;padding:3px 4px}.compact .route{padding:6px 8px}.compact .group-head{padding:7px 9px}.box{width:17px;height:17px;border:1px solid #514d69;border-radius:5px;background:#101018;display:grid;place-items:center}.box:after{content:"";width:8px;height:4px;border-left:2px solid #07120d;border-bottom:2px solid #07120d;transform:rotate(-45deg) scale(0)}.cargo-row.loaded .box{background:var(--green);border-color:var(--green);box-shadow:0 0 10px rgba(73,237,160,.22)}.cargo-row.loaded .box:after{transform:rotate(-45deg) scale(1)}.cargo-icon{width:16px;height:16px;fill:currentColor;filter:drop-shadow(0 0 3px currentColor)}.cargo-name{font-size:10px;font-weight:800;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.scu{font:900 10px Consolas,monospace;color:var(--blue);white-space:nowrap}.cargo-row.loaded .scu{color:var(--green)}
.overlay-location{display:flex!important;align-items:center;gap:7px;min-width:0}.overlay-location .route-icon{display:block;width:10px;height:10px;flex:0 0 10px;fill:currentColor;opacity:.92}.overlay-location.pickup-route .route-icon{color:#6f9bd1}.overlay-location.dropoff-route .route-icon{color:#8979d8}.overlay-location .location-text{display:block;min-width:0;margin-top:0!important;color:inherit!important;font:inherit!important;letter-spacing:inherit;overflow:hidden;text-overflow:ellipsis}
.footer{position:relative;z-index:4;display:flex;align-items:center;justify-content:space-between;gap:8px;padding:0 9px;border-top:1px solid var(--line);background:rgba(15,15,23,.96);color:var(--muted);font-size:7.5px;font-weight:800}.footer .live{color:var(--green)}.resize-note{display:none}.size-unlocked .resize-note{display:inline}.size-unlocked .default-note{display:none}.shell:after{content:"";display:none;position:absolute;right:2px;bottom:2px;width:9px;height:9px;border-right:2px solid rgba(143,118,255,.55);border-bottom:2px solid rgba(143,118,255,.55);pointer-events:none}.size-unlocked .shell:after{display:block}
.resize-handle{display:none;position:fixed;z-index:90;background:transparent;touch-action:none}.size-unlocked .resize-handle{display:block}.resize-handle[data-resize="n"]{left:10px;right:10px;top:0;height:7px;cursor:ns-resize}.resize-handle[data-resize="s"]{left:10px;right:10px;bottom:0;height:7px;cursor:ns-resize}.resize-handle[data-resize="w"]{left:0;top:10px;bottom:10px;width:7px;cursor:ew-resize}.resize-handle[data-resize="e"]{right:0;top:10px;bottom:10px;width:7px;cursor:ew-resize}.resize-handle[data-resize="nw"]{left:0;top:0;width:14px;height:14px;cursor:nwse-resize}.resize-handle[data-resize="ne"]{right:0;top:0;width:14px;height:14px;cursor:nesw-resize}.resize-handle[data-resize="sw"]{left:0;bottom:0;width:14px;height:14px;cursor:nesw-resize}.resize-handle[data-resize="se"]{right:0;bottom:0;width:14px;height:14px;cursor:nwse-resize}
/* Unified overlay typography: three text sizes and two weights. */
.titlecopy strong,.settings-head strong,.group-head strong{font-size:var(--type-heading);font-weight:var(--weight-strong)}
.titlecopy small,.settings-head small,.setting-copy small,.progress-copy small,.group-head small,.group-head span,.route-title span,.footer{font-size:var(--type-meta);font-weight:var(--weight-body)}
.setting-copy strong,.route-title strong,.cargo-name,.empty{font-size:var(--type-ui);font-weight:var(--weight-strong)}.small-btn{font-size:var(--type-control);font-weight:var(--weight-control)}
.opacity-value{font:var(--weight-strong) var(--type-meta) Consolas,monospace}
.route-title span{font-family:Consolas,monospace}
.scu{font:var(--weight-strong) var(--type-ui) Consolas,monospace}
.progress-copy strong{font:var(--weight-strong) 15px Consolas,monospace}
@media(max-width:360px){.summary{grid-template-columns:1fr}.summary-actions{justify-content:flex-start}.titlecopy small{display:none}.settings-menu{width:210px}}
</style>
</head>
<body class="size-unlocked compact">
<div class="shell" id="shell">
  <header class="titlebar">
    <div class="title-zone">
      <div class="titlecopy" id="dragRegion" aria-disabled="false"><span class="titletext"><strong>Hauling loadout</strong><small id="subtitle">Waiting for active cargo</small></span></div>
      <div class="position-lock-shield" id="positionLockShield" aria-hidden="true"></div>
    </div>
    <div class="window-actions pywebview-drag-region-exclude">
      <button class="icon-btn" id="settingsBtn" type="button" title="Overlay settings" aria-expanded="false" onmousedown="event.stopPropagation()"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M259.1 73.5C262.1 58.7 275.2 48 290.4 48L350.2 48C365.4 48 378.5 58.7 381.5 73.5L396 143.5C410.1 149.5 423.3 157.2 435.3 166.3L503.1 143.8C517.5 139 533.3 145 540.9 158.2L570.8 210C578.4 223.2 575.7 239.8 564.3 249.9L511 297.3C511.9 304.7 512.3 312.3 512.3 320C512.3 327.7 511.8 335.3 511 342.7L564.4 390.2C575.8 400.3 578.4 417 570.9 430.1L541 481.9C533.4 495 517.6 501.1 503.2 496.3L435.4 473.8C423.3 482.9 410.1 490.5 396.1 496.6L381.7 566.5C378.6 581.4 365.5 592 350.4 592L290.6 592C275.4 592 262.3 581.3 259.3 566.5L244.9 496.6C230.8 490.6 217.7 482.9 205.6 473.8L137.5 496.3C123.1 501.1 107.3 495.1 99.7 481.9L69.8 430.1C62.2 416.9 64.9 400.3 76.3 390.2L129.7 342.7C128.8 335.3 128.4 327.7 128.4 320C128.4 312.3 128.9 304.7 129.7 297.3L76.3 249.8C64.9 239.7 62.3 223 69.8 209.9L99.7 158.1C107.3 144.9 123.1 138.9 137.5 143.7L205.3 166.2C217.4 157.1 230.6 149.5 244.6 143.4L259.1 73.5zM320.3 400C364.5 399.8 400.2 363.9 400 319.7C399.8 275.5 363.9 239.8 319.7 240C275.5 240.2 239.8 276.1 240 320.3C240.2 364.5 276.1 400.2 320.3 400z"/></svg></button>
      <button class="icon-btn" id="minBtn" type="button" title="Minimize" onmousedown="event.stopPropagation()"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M64 480C64 462.3 78.3 448 96 448L544 448C561.7 448 576 462.3 576 480C576 497.7 561.7 512 544 512L96 512C78.3 512 64 497.7 64 480z"/></svg></button>
      <button class="icon-btn danger" id="closeBtn" type="button" title="Close overlay" onmousedown="event.stopPropagation()"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M183.1 137.4C170.6 124.9 150.3 124.9 137.8 137.4C125.3 149.9 125.3 170.2 137.8 182.7L275.2 320L137.9 457.4C125.4 469.9 125.4 490.2 137.9 502.7C150.4 515.2 170.7 515.2 183.2 502.7L320.5 365.3L457.9 502.6C470.4 515.1 490.7 515.1 503.2 502.6C515.7 490.1 515.7 469.8 503.2 457.3L365.8 320L503.1 182.6C515.6 170.1 515.6 149.8 503.1 137.3C490.6 124.8 470.3 124.8 457.8 137.3L320.5 274.7L183.1 137.4z"/></svg></button>
    </div>
    <section class="settings-menu" id="settingsMenu" hidden onmousedown="event.stopPropagation()">
      <div class="settings-head"><strong>Overlay settings</strong><small>Window</small></div>
      <div class="setting-row">
        <div class="setting-copy"><strong>Opacity</strong><small>Adjust the whole overlay window.</small></div>
        <div class="opacity-control"><input id="opacityRange" type="range" min="50" max="100" step="5" value="95"><span class="opacity-value" id="opacityValue">95%</span></div>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>Lock size</strong><small>Prevent edge resizing.</small></div>
        <button class="switch" id="sizeLockSwitch" type="button" role="switch" aria-pressed="false" title="Lock overlay size"></button>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>Lock position</strong><small>Disable dragging the header.</small></div>
        <button class="switch" id="positionLockSwitch" type="button" role="switch" aria-pressed="false" title="Lock overlay position"></button>
      </div>
      <div class="setting-row">
        <div class="setting-copy"><strong>Always on top</strong><small>Keep the overlay above the game.</small></div>
        <button class="switch" id="onTopSwitch" type="button" role="switch" aria-pressed="true" title="Keep overlay always on top"></button>
      </div>
    </section>
  </header>
  <section class="summary" id="summary">
    <div class="progress-copy"><strong id="progress">0 / 0 loaded</strong><small id="scuProgress">0 / 0 SCU</small></div>
    <div class="summary-actions"><button class="small-btn" id="overlayHideLoadedBtn" type="button">Hide loaded</button><button class="small-btn" id="clearBtn" type="button">Clear</button></div>
  </section>
  <main class="board" id="board"><div class="empty">No active cargo objectives.</div></main>
  <footer class="footer"><span class="default-note">Drag header · size locked</span><span class="resize-note">Drag header · resize from window edges</span><span id="liveState">Connecting…</span></footer>
</div>
<div class="resize-handle" data-resize="n" aria-hidden="true"></div>
<div class="resize-handle" data-resize="s" aria-hidden="true"></div>
<div class="resize-handle" data-resize="e" aria-hidden="true"></div>
<div class="resize-handle" data-resize="w" aria-hidden="true"></div>
<div class="resize-handle" data-resize="ne" aria-hidden="true"></div>
<div class="resize-handle" data-resize="nw" aria-hidden="true"></div>
<div class="resize-handle" data-resize="se" aria-hidden="true"></div>
<div class="resize-handle" data-resize="sw" aria-hidden="true"></div>
<script>
const $=id=>document.getElementById(id);const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CHECKLIST_STORAGE_KEY='sc-hauling-loading-checklist-v1',OVERLAY_VIEW_KEY='sc-hauling-overlay-view-v1';let checklist=loadChecklist(),cache=null,boardMarkup='',pointerScrollTop=0,overlaySettings={opacity:.95,size_locked:false,position_locked:false,on_top:true},overlayView=loadOverlayView();
function loadChecklist(){try{const v=JSON.parse(localStorage.getItem(CHECKLIST_STORAGE_KEY)||'{}');return v&&typeof v==='object'?v:{}}catch(_e){return{}}}
function saveChecklist(){try{localStorage.setItem(CHECKLIST_STORAGE_KEY,JSON.stringify(checklist))}catch(_e){}}
function loadOverlayView(){try{const v=JSON.parse(localStorage.getItem(OVERLAY_VIEW_KEY)||'{}');return v&&typeof v==='object'?{hide_loaded:!!v.hide_loaded}:{hide_loaded:false}}catch(_e){return{hide_loaded:false}}}
function saveOverlayView(){try{localStorage.setItem(OVERLAY_VIEW_KEY,JSON.stringify(overlayView))}catch(_e){}}
async function syncChecklist(action,id='',checked=false){try{const payload={action};if(id)payload.id=id;if(action==='set')payload.checked=!!checked;await fetch('/api/checklist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})}catch(_e){}}
const COLORS=Object.freeze({'hydrogen':'#8fd9f2','quartz':'#6f78c9','carbon':'#6d727c','aluminum':'#aeb7c3','aluminium':'#aeb7c3','copper':'#bd7048','iron':'#8a9099','iron (ore)':'#8a9099','titanium':'#c8ced8','tungsten':'#626975','beryl':'#69b98d','gold':'#d3ab43','diamond':'#c8edf5','agricium':'#72bd83','laranite':'#7664bd','taranite':'#bd5964','medical supplies':'#d85b69','agricultural supplies':'#77ad63','processed food':'#c99954','distilled spirits':'#9760ae','scrap':'#866654','waste':'#726451'});
function color(name){return COLORS[String(name||'').trim().toLowerCase()]||'#8b90a5'}
const LOCATION_SVGS=Object.freeze({
  pickup:`<svg class="route-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M342.6 73.4C330.1 60.9 309.8 60.9 297.3 73.4L137.3 233.4C124.8 245.9 124.8 266.2 137.3 278.7C149.8 291.2 170.1 291.2 182.6 278.7L288 173.3L288 544C288 561.7 302.3 576 320 576C337.7 576 352 561.7 352 544L352 173.3L457.4 278.7C469.9 291.2 490.2 291.2 502.7 278.7C515.2 266.2 515.2 245.9 502.7 233.4L342.7 73.4z"/></svg>`,
  dropoff:`<svg class="route-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M297.4 566.6C309.9 579.1 330.2 579.1 342.7 566.6L502.7 406.6C515.2 394.1 515.2 373.8 502.7 361.3C490.2 348.8 469.9 348.8 457.4 361.3L352 466.7L352 96C352 78.3 337.7 64 320 64C302.3 64 288 78.3 288 96L288 466.7L182.6 361.3C170.1 348.8 149.8 348.8 137.3 361.3C124.8 373.8 124.8 394.1 137.3 406.6L297.3 566.6z"/></svg>`
});
const BOX=`<svg class="cargo-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M431.1 80C451.8 80 471.2 90 483.2 106.8L532.1 175.3C539.8 186.1 544 199.2 544 212.5L544 480C544 515.3 515.3 544 480 544L160 544L153.5 543.7C121.2 540.4 96 513.1 96 480L96 212.5C96 200.8 99.2 189.4 105.2 179.5L107.9 175.3L156.8 106.8C167.3 92.1 183.5 82.6 201.2 80.5L208.9 80L431 80zM344 192L465.3 192L431 144L343.9 144L343.9 192zM174.7 192L296 192L296 144L208.9 144L174.6 192z"/></svg>`;
function idFor(it,mode,fixed,column){return String(it.id||[mode,fixed,column,it.commodity,it.scu].join('|'))}function fmt(n){n=Number(n||0);return Number.isInteger(n)?String(n):n.toFixed(1).replace(/\.0$/,'')}
function collect(sections){const out=[];(sections||[]).forEach(s=>(s.columns||[]).forEach(c=>(c.items||[]).forEach(it=>out.push({id:idFor(it,s.mode||'direct',s.fixed_location||'—',c.location||'—'),scu:Number(it.scu_value??it.scu??0)}))));return out}
function stats(items){const loaded=items.filter(x=>checklist[x.id]);return{total:items.length,loaded:loaded.length,totalScu:items.reduce((n,x)=>n+x.scu,0),loadedScu:loaded.reduce((n,x)=>n+x.scu,0)}}
function sharedStats(sections){let total=0,loaded=0;(sections||[]).forEach(section=>{if((section.mode||'')!=='aggregate_pickups')return;let loads=Array.isArray(section.shared_loads)?section.shared_loads:[];if(!loads.length){const ids=[];(section.columns||[]).forEach(col=>(col.items||[]).forEach(it=>ids.push(idFor(it,section.mode||'direct',section.fixed_location||'—',col.location||'—'))));loads=[{scu_value:Number(section.shared_scu_value??section.shared_scu??section.total??0),item_ids:ids}]}loads.forEach(load=>{const value=Number(load.scu_value??load.scu??0),ids=load.item_ids||[];if(!value)return;total+=value;if(ids.length&&ids.every(id=>checklist[id]))loaded+=value})});return{total,loaded}}
function applyOverlayView(){document.body.classList.add('compact');$('overlayHideLoadedBtn').classList.toggle('active',!!overlayView.hide_loaded);$('overlayHideLoadedBtn').textContent=overlayView.hide_loaded?'Show loaded':'Hide loaded'}
function resetDocumentViewport(){try{window.scrollTo(0,0)}catch(_e){}document.documentElement.scrollTop=0;document.body.scrollTop=0}
function syncChecklistRows(){document.querySelectorAll('.cargo-row[data-id]').forEach(row=>{const loaded=!!checklist[row.dataset.id];row.classList.toggle('loaded',loaded);row.setAttribute('aria-checked',loaded?'true':'false')})}
function buildBoardMarkup(sections){
  if(!sections.length)return '<div class="empty">No active accepted cargo.<br>Accept or scan a hauling contract to populate this overlay.</div>';
  const markup=sections.map(section=>{
    const mode=section.mode||'direct',fixed=section.fixed_location||'—';
    const fixedKind=(mode==='single_dropoff'||mode==='aggregate_pickups')?'dropoff':'pickup';
    const columnKind=fixedKind==='pickup'?'dropoff':'pickup';
    const shared=mode==='single_pickup'||mode==='single_dropoff'||mode==='aggregate_pickups';
    const label=`${fixedKind==='pickup'?'PICK UP LOCATION':'DROP OFF LOCATION'}${shared?' (SHARED)':''}`;
    const routes=(section.columns||[]).map(col=>{
      const all=(col.items||[]).map(it=>({it,id:idFor(it,mode,fixed,col.location||'—'),scu:Number(it.scu_value??it.scu??0)}));
      const routeStats=stats(all);
      const visible=overlayView.hide_loaded?all.filter(entry=>!checklist[entry.id]):all;
      const rows=visible.map(entry=>{const amount=String(entry.it.scu||'').trim();return `<div class="cargo-row" data-id="${esc(entry.id)}" role="checkbox" aria-checked="false"><span class="box" aria-hidden="true"></span><span style="color:${color(entry.it.commodity)}">${BOX}</span><span class="cargo-name">${esc(entry.it.commodity)}</span><span class="scu">${amount?`${esc(amount)} SCU`:''}</span></div>`}).join('');
      const progress=mode==='aggregate_pickups'?`${routeStats.loaded}/${routeStats.total} loaded`:`${routeStats.loaded}/${routeStats.total} · ${fmt(routeStats.loadedScu)}/${fmt(routeStats.totalScu)} SCU`;
      return `<section class="route${overlayView.hide_loaded&&routeStats.total>0&&routeStats.loaded===routeStats.total?' empty-route':''}"><div class="route-title"><strong class="overlay-location ${columnKind}-route" title="${esc(col.location)}">${LOCATION_SVGS[columnKind]}<span class="location-text">${esc(col.location)}</span></strong><span>${esc(progress)}</span></div>${rows||'<div class="empty">Loaded</div>'}</section>`;
    }).join('');
    const totalLabel=mode==='aggregate_pickups'?`${section.total} SCU shared total`:`${section.total} SCU total`;
    return `<article class="group"><div class="group-head"><small>${esc(label)}</small><strong class="overlay-location ${fixedKind}-route" title="${esc(fixed)}">${LOCATION_SVGS[fixedKind]}<span class="location-text">${esc(fixed)}</span></strong><span>${esc(totalLabel)}</span></div>${routes}</article>`;
  }).join('');
  return markup||'<div class="empty">All loaded cargo is hidden.</div>';
}
function render(data){cache=data;if(data?.checklist&&typeof data.checklist==='object'){checklist={...data.checklist};saveChecklist()}const sections=data?.logistics?.sections||[],items=collect(sections),valid=new Set(items.map(x=>x.id));let dirty=false;Object.keys(checklist).forEach(id=>{if(!valid.has(id)){delete checklist[id];dirty=true}});if(dirty)saveChecklist();const st=stats(items),shared=sharedStats(sections),complete=st.total>0&&st.loaded===st.total;applyOverlayView();$('progress').textContent=`${st.loaded} / ${st.total} loaded`;$('scuProgress').textContent=`${fmt(st.loadedScu+shared.loaded)} / ${fmt(st.totalScu+shared.total)} SCU`;$('summary').classList.toggle('complete',complete);$('subtitle').textContent=sections.length?`${sections.length} route ${sections.length===1?'group':'groups'} · ${items.length} cargo items`:'No active accepted cargo';$('clearBtn').disabled=st.loaded===0;$('liveState').innerHTML=data.watching?'<span class="live">● LIVE</span>':'IDLE';const board=$('board'),scrollTop=board.scrollTop,markup=buildBoardMarkup(sections);if(markup!==boardMarkup){boardMarkup=markup;board.innerHTML=markup;board.scrollTop=scrollTop}syncChecklistRows();resetDocumentViewport()}
async function refresh(){try{const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw new Error(r.status);render(await r.json())}catch(e){$('liveState').textContent='OFFLINE'}}
$('board').addEventListener('pointerdown',e=>{if(e.target.closest('.cargo-row[data-id]'))pointerScrollTop=$('board').scrollTop});
$('board').addEventListener('click',e=>{const row=e.target.closest('.cargo-row[data-id]');if(!row)return;e.preventDefault();e.stopPropagation();const scrollTop=pointerScrollTop||$('board').scrollTop,id=row.dataset.id;if(checklist[id])delete checklist[id];else checklist[id]=true;saveChecklist();syncChecklist('set',id,!!checklist[id]);if(cache){cache.checklist={...checklist};render(cache)};const restore=()=>{$('board').scrollTop=scrollTop;resetDocumentViewport()};requestAnimationFrame(restore);setTimeout(restore,0);setTimeout(restore,80)});
$('clearBtn').addEventListener('click',()=>{const scrollTop=$('board').scrollTop;checklist={};saveChecklist();syncChecklist('clear');if(cache){cache.checklist={};render(cache)};requestAnimationFrame(()=>{$('board').scrollTop=scrollTop;resetDocumentViewport()})});
$('overlayHideLoadedBtn').addEventListener('click',()=>{overlayView.hide_loaded=!overlayView.hide_loaded;saveOverlayView();boardMarkup='';if(cache)render(cache)});
window.addEventListener('storage',e=>{if(e.key===CHECKLIST_STORAGE_KEY){const scrollTop=$('board').scrollTop;checklist=loadChecklist();if(cache){cache.checklist={...checklist};render(cache)};requestAnimationFrame(()=>{$('board').scrollTop=scrollTop;resetDocumentViewport()})}});
const CONTROL_PARAMS=new URLSearchParams(window.location.search);
const CONTROL_PORT=Number(CONTROL_PARAMS.get('overlay_control_port')||0);
const CONTROL_TOKEN=CONTROL_PARAMS.get('overlay_control_token')||'';
let controlErrorTimer=null;
function controlMessage(message,isError=false){const el=$('liveState');if(!el)return;el.textContent=message;el.classList.toggle('live',!isError);clearTimeout(controlErrorTimer);controlErrorTimer=setTimeout(()=>{if(cache)el.innerHTML=cache.watching?'<span class="live">● LIVE</span>':'IDLE'},2600)}
function withTimeout(promise,ms){return Promise.race([promise,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Native bridge timeout')),ms))])}
async function nativeHttp(name,args){if(!CONTROL_PORT||!CONTROL_TOKEN)throw new Error('Overlay control channel unavailable');const response=await fetch(`http://127.0.0.1:${CONTROL_PORT}/command`,{method:'POST',mode:'cors',cache:'no-store',headers:{'Content-Type':'application/json','X-SC-Overlay-Token':CONTROL_TOKEN},body:JSON.stringify({name,args})});let payload=null;try{payload=await response.json()}catch(_e){}if(!response.ok||!payload?.ok)throw new Error(payload?.error||`Overlay control failed (${response.status})`);return payload.result}
async function native(name,...args){let httpError=null;if(CONTROL_PORT&&CONTROL_TOKEN){try{return await nativeHttp(name,args)}catch(error){httpError=error}}let bridgeError=null;try{const fn=window.pywebview?.api?.[name];if(typeof fn==='function'){const result=await withTimeout(fn(...args),900);if(result!==undefined&&result!==null)return result}}catch(error){bridgeError=error}const detail=httpError?.message||bridgeError?.message||'Native control unavailable';console.error(`Overlay command ${name} failed`,httpError,bridgeError);controlMessage(detail,true);return null}
function setSwitch(id,value){$(id).setAttribute('aria-pressed',value?'true':'false')}
window.applyNativeSettings=function(status){if(!status)return;overlaySettings={...overlaySettings,...status};const opacity=Math.max(.5,Math.min(1,Number(overlaySettings.opacity||.95)));$('opacityRange').value=String(Math.round(opacity*100));$('opacityValue').textContent=`${Math.round(opacity*100)}%`;setSwitch('sizeLockSwitch',!!overlaySettings.size_locked);setSwitch('positionLockSwitch',!!overlaySettings.position_locked);setSwitch('onTopSwitch',overlaySettings.on_top!==false);document.body.classList.toggle('size-unlocked',!overlaySettings.size_locked);document.body.classList.toggle('position-locked',!!overlaySettings.position_locked);$('dragRegion').setAttribute('aria-disabled',overlaySettings.position_locked?'true':'false');$('positionLockShield').setAttribute('aria-hidden',overlaySettings.position_locked?'false':'true')};
function toggleSettings(force){const menu=$('settingsMenu'),open=typeof force==='boolean'?force:menu.hidden;menu.hidden=!open;$('settingsBtn').setAttribute('aria-expanded',open?'true':'false');if(open)native('get_overlay_status').then(window.applyNativeSettings)}
$('settingsBtn').addEventListener('click',e=>{e.stopPropagation();toggleSettings()});
document.addEventListener('pointerdown',e=>{if(!$('settingsMenu').hidden&&!e.target.closest('#settingsMenu')&&!e.target.closest('#settingsBtn'))toggleSettings(false)});document.addEventListener('keydown',e=>{if(e.key==='Escape')toggleSettings(false)});
let opacityTimer=null;$('opacityRange').addEventListener('input',e=>{const pct=Number(e.target.value);$('opacityValue').textContent=`${pct}%`;clearTimeout(opacityTimer);opacityTimer=setTimeout(async()=>window.applyNativeSettings(await native('set_overlay_opacity',pct/100)),45)});
$('sizeLockSwitch').addEventListener('click',async()=>window.applyNativeSettings(await native('set_overlay_size_locked',!overlaySettings.size_locked)));
$('positionLockSwitch').addEventListener('click',async()=>window.applyNativeSettings(await native('set_overlay_position_locked',!overlaySettings.position_locked)));
$('onTopSwitch').addEventListener('click',async()=>window.applyNativeSettings(await native('set_overlay_on_top',overlaySettings.on_top===false)));
$('closeBtn').addEventListener('click',async e=>{e.preventDefault();e.stopPropagation();const result=await native('hide_overlay');if(result===null)controlMessage('Close command failed',true)});$('minBtn').addEventListener('click',async e=>{e.preventDefault();e.stopPropagation();const result=await native('minimize_overlay');if(result===null)controlMessage('Minimize command failed',true)});
['pointerdown','mousedown','dblclick'].forEach(type=>$('positionLockShield').addEventListener(type,event=>{event.preventDefault();event.stopImmediatePropagation()}));
$('dragRegion').addEventListener('pointerdown',event=>{if(event.button!==0||overlaySettings.position_locked||event.detail>1)return;event.preventDefault();event.stopPropagation();native('begin_overlay_move').then(status=>{if(status)window.applyNativeSettings(status)})});
document.querySelectorAll('.resize-handle[data-resize]').forEach(handle=>{handle.addEventListener('pointerdown',event=>{if(event.button!==0||overlaySettings.size_locked)return;event.preventDefault();event.stopPropagation();native('begin_overlay_resize',handle.dataset.resize).then(status=>{if(status)window.applyNativeSettings(status)})})});
async function loadNativeSettings(){const status=await native('get_overlay_status');if(status)window.applyNativeSettings(status)}
window.addEventListener('pywebviewready',loadNativeSettings);setTimeout(loadNativeSettings,120);setTimeout(loadNativeSettings,900);
refresh();setInterval(refresh,900);
</script>
</body>
</html>'''


class OcrNotificationWindow:
    # Small topmost Windows notification that never activates over Star Citizen.

    STAGES = ("Detect", "Capture", "Recognition", "Import")

    def __init__(self):
        self.commands: "queue.Queue[tuple]" = queue.Queue()
        self.thread = threading.Thread(target=self._run, daemon=True, name="scht-ocr-notification")
        self.thread.start()

    def show(self, title: str, message: str, tone: str = "info", duration: float = 0.0) -> None:
        self.commands.put(("show", str(title or "SCHT"), str(message or ""), str(tone or "info"), float(duration or 0.0)))

    def hide(self) -> None:
        self.commands.put(("hide",))

    def shutdown(self) -> None:
        self.commands.put(("shutdown",))

    @staticmethod
    def model(title: str, message: str, tone: str = "info") -> dict:
        title = str(title or "SCHT")
        message = str(message or "")
        tone = str(tone or "info").lower()
        haystack = f"{title} {message}".lower()
        stage = 0
        status = title
        detail = message
        note = "Keep this contract open in Star Citizen until import finishes."
        terminal = False
        if "captur" in haystack and "dpi" in haystack:
            stage = 1
            status = "Capturing screen"
            detail = message or "DPI-aware live capture in progress"
        elif "reading" in haystack or "recogn" in haystack or "ocr attempt" in haystack:
            stage = 2
            status = "Reading contract"
            detail = "DPI-aware capture in progress" if "attempt" in haystack else (message or "Recognition in progress")
        elif "imported" in haystack or "saved" in haystack:
            stage = 3
            status = "Contract imported"
            detail = message or "Contract data captured successfully"
            note = "Import complete. You can continue in Star Citizen."
            tone = "success"
            terminal = True
        elif "partial" in haystack or "review" in haystack or "skipped" in haystack:
            stage = 3
            status = "Contract needs review"
            detail = message or "Review the contract details in SCHT"
            clean_detail = detail.strip().rstrip(".")
            if "scht" not in clean_detail.lower():
                if "verification" in clean_detail.lower():
                    detail = f"{clean_detail} in SCHT."
                else:
                    detail = f"{clean_detail}. Review in SCHT."
            note = "Open SCHT and verify the contract details."
            tone = "warning"
            terminal = True
        elif "failed" in haystack or "error" in haystack:
            stage = 2
            status = "OCR failed"
            detail = message or "Recognition failed"
            note = "Open SCHT and use Edit > Read screenshot."
            tone = "error"
            terminal = True
        elif "detected" in haystack or "queued" in haystack:
            stage = 0
            status = "Contract detected"
            detail = message or "Accepted hauling contract identified"
        progress = {0: 12, 1: 42, 2: 72, 3: 100}.get(stage, 12)
        if terminal:
            progress = 100
        return {
            "label": "SCHT CONTRACT HANDLING",
            "status": status,
            "detail": re.sub(r"\s+", " ", detail).strip(),
            "note": re.sub(r"\s+", " ", note).strip(),
            "tone": tone if tone in {"info", "success", "warning", "error"} else "info",
            "stage": max(0, min(3, int(stage))),
            "progress": progress,
            "terminal": bool(terminal),
            "spinning": False,
        }

    def _run(self) -> None:
        try:
            import tkinter as tk
            root = tk.Tk()
            root.withdraw()
            win = tk.Toplevel(root)
            win.withdraw()
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg="#08080e")
            width, height = 500, 148
            canvas = tk.Canvas(win, width=width, height=height, bg="#08080e", bd=0, highlightthickness=0)
            canvas.pack(fill="both", expand=True)
            hide_token = {"value": 0}
            current_model = {"value": self.model("SCHT", "", "info")}

            def apply_no_activate() -> None:
                if os.name != "nt":
                    return
                try:
                    import ctypes
                    hwnd = int(win.winfo_id())
                    GWL_EXSTYLE = -20
                    WS_EX_TOOLWINDOW = 0x00000080
                    WS_EX_NOACTIVATE = 0x08000000
                    get_style = getattr(ctypes.windll.user32, "GetWindowLongPtrW", ctypes.windll.user32.GetWindowLongW)
                    set_style = getattr(ctypes.windll.user32, "SetWindowLongPtrW", ctypes.windll.user32.SetWindowLongW)
                    style = int(get_style(hwnd, GWL_EXSTYLE)) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                    set_style(hwnd, GWL_EXSTYLE, style)
                    ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)
                except Exception:
                    pass

            def hide_now() -> None:
                hide_token["value"] += 1
                win.withdraw()

            def close_hit(x: int, y: int) -> bool:
                return width - 44 <= int(x) <= width - 10 and 8 <= int(y) <= 38

            def rounded_rect(x1: int, y1: int, x2: int, y2: int, radius: int, **kwargs) -> None:
                radius = max(1, min(radius, (x2 - x1) // 2, (y2 - y1) // 2))
                canvas.create_rectangle(x1 + radius, y1, x2 - radius, y2, **kwargs)
                canvas.create_rectangle(x1, y1 + radius, x2, y2 - radius, **kwargs)
                canvas.create_arc(x1, y1, x1 + radius * 2, y1 + radius * 2, start=90, extent=90, style="pieslice", **kwargs)
                canvas.create_arc(x2 - radius * 2, y1, x2, y1 + radius * 2, start=0, extent=90, style="pieslice", **kwargs)
                canvas.create_arc(x2 - radius * 2, y2 - radius * 2, x2, y2, start=270, extent=90, style="pieslice", **kwargs)
                canvas.create_arc(x1, y2 - radius * 2, x1 + radius * 2, y2, start=180, extent=90, style="pieslice", **kwargs)

            def draw_card() -> None:
                data = current_model["value"]
                canvas.delete("all")
                bg = "#151522"
                border = "#3b375f"
                label = "#a8add0"
                title_color = "#f5f6ff"
                detail_color = "#a7a4c9"
                note_color = "#cfd3e8"
                blue = "#4f9bff"
                cyan = "#53ddff"
                green = "#62e381"
                amber = "#ffc857"
                red = "#ff6678"
                inactive = "#55566a"
                progress_color = {"success": green, "warning": amber, "error": red}.get(data["tone"], blue) if data["terminal"] else blue
                try:
                    rounded_rect(1, 1, width - 1, height - 1, 18, fill=bg, outline=border, width=1)
                    canvas.create_text(20, 18, anchor="w", text=data["label"], fill=label, font=("Segoe UI", 8, "bold"))
                    canvas.create_text(20, 43, anchor="w", text=data["status"], fill=title_color, font=("Segoe UI", 13, "bold"))
                    canvas.create_text(20, 66, anchor="w", text=data["detail"][:76], fill=detail_color, font=("Segoe UI", 9))
                    cx, cy = width - 24, 20
                    canvas.create_line(cx - 5, cy - 5, cx + 5, cy + 5, fill=label, width=2)
                    canvas.create_line(cx + 5, cy - 5, cx - 5, cy + 5, fill=label, width=2)
                    left, top, right, bottom = 20, 91, width - 82, 99
                    progress = max(0, min(100, int(data.get("progress") or 0)))
                    rounded_rect(left, top, right, bottom, 4, fill=inactive, outline=inactive)
                    if progress > 0:
                        fill_right = left + int((right - left) * (progress / 100.0))
                        rounded_rect(left, top, max(left + 8, fill_right), bottom, 4, fill=progress_color, outline=progress_color)
                    canvas.create_text(width - 38, 95, anchor="center", text=f"{progress}%", fill=progress_color, font=("Segoe UI", 9, "bold"))
                    canvas.create_text(
                        20,
                        121,
                        anchor="w",
                        text=data["note"],
                        width=width - 42,
                        justify="left",
                        fill=note_color,
                        font=("Segoe UI", 9, "bold"),
                    )
                except Exception:
                    pass

            def on_click(event) -> None:
                if close_hit(getattr(event, "x", 0), getattr(event, "y", 0)):
                    hide_now()

            def show_now(title: str, message: str, tone: str, duration: float) -> None:
                hide_token["value"] += 1
                token = hide_token["value"]
                current_model["value"] = self.model(title, message, tone)
                if current_model["value"].get("terminal"):
                    duration = 8.0
                draw_card()
                win.update_idletasks()
                try:
                    import ctypes
                    from ctypes import wintypes
                    class RECT(ctypes.Structure):
                        _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
                    rect = RECT()
                    if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                        x = int(rect.right - width - 22); y = int(rect.top + 22)
                    else:
                        x = int(win.winfo_screenwidth() - width - 22); y = 22
                except Exception:
                    x = int(win.winfo_screenwidth() - width - 22); y = 22
                win.geometry(f"{width}x{height}+{x}+{y}")
                apply_no_activate()
                win.deiconify()
                apply_no_activate()
                if duration > 0:
                    root.after(int(duration * 1000), lambda: hide_now() if hide_token["value"] == token else None)

            def poll() -> None:
                try:
                    while True:
                        command = self.commands.get_nowait()
                        if command[0] == "show":
                            show_now(command[1], command[2], command[3], command[4])
                        elif command[0] == "hide":
                            hide_now()
                        elif command[0] == "shutdown":
                            root.destroy(); return
                except queue.Empty:
                    pass
                root.after(60, poll)

            canvas.bind("<ButtonRelease-1>", on_click)
            root.after(60, poll)
            root.mainloop()
        except Exception:
            self._run_native_windows()

    def _run_native_windows(self) -> None:
        """Fallback notification window for packaged builds without tkinter."""
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            gdi32 = ctypes.windll.gdi32
            kernel32 = ctypes.windll.kernel32
            LRESULT = ctypes.c_ssize_t
            WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

            class RECT(ctypes.Structure):
                _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]

            class PAINTSTRUCT(ctypes.Structure):
                _fields_ = [
                    ("hdc", wintypes.HDC),
                    ("fErase", wintypes.BOOL),
                    ("rcPaint", RECT),
                    ("fRestore", wintypes.BOOL),
                    ("fIncUpdate", wintypes.BOOL),
                    ("rgbReserved", wintypes.BYTE * 32),
                ]

            class WNDCLASS(ctypes.Structure):
                _fields_ = [
                    ("style", wintypes.UINT),
                    ("lpfnWndProc", WNDPROC),
                    ("cbClsExtra", ctypes.c_int),
                    ("cbWndExtra", ctypes.c_int),
                    ("hInstance", wintypes.HINSTANCE),
                    ("hIcon", wintypes.HICON),
                    ("hCursor", wintypes.HCURSOR),
                    ("hbrBackground", wintypes.HBRUSH),
                    ("lpszMenuName", wintypes.LPCWSTR),
                    ("lpszClassName", wintypes.LPCWSTR),
                ]

            WM_DESTROY, WM_PAINT, WM_TIMER = 0x0002, 0x000F, 0x0113
            WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202
            WS_POPUP = 0x80000000
            WS_EX_TOPMOST, WS_EX_TOOLWINDOW, WS_EX_NOACTIVATE = 0x00000008, 0x00000080, 0x08000000
            SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0040
            DT_LEFT, DT_CENTER, DT_WORDBREAK, DT_END_ELLIPSIS, DT_SINGLELINE = 0x0000, 0x0001, 0x0010, 0x8000, 0x0020
            TRANSPARENT = 1

            def colorref(hex_color: str) -> int:
                value = hex_color.lstrip("#")
                r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
                return r | (g << 8) | (b << 16)

            colors = {
                "bg": "#151522",
                "border": "#3b375f",
                "label": "#a8add0",
                "title": "#f5f6ff",
                "detail": "#a7a4c9",
                "note": "#cfd3e8",
                "blue": "#4f9bff",
                "cyan": "#53ddff",
                "green": "#62e381",
                "amber": "#ffc857",
                "red": "#ff6678",
                "inactive": "#55566a",
            }
            state = {
                "model": self.model("SCHT", "", "info"),
                "hide_at": 0.0,
                "visible": False,
                "shutdown": False,
            }
            width, height = 500, 148
            hinst = kernel32.GetModuleHandleW(None)
            class_name = f"SCHT_OCR_NOTIFICATION_{os.getpid()}"
            fonts = {"label": None, "title": None, "detail": None, "stage": None, "close": None, "percent": None, "note": None}

            def workarea_position() -> Tuple[int, int]:
                rect = RECT()
                if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    return int(rect.right - width - 22), int(rect.top + 22)
                return int(user32.GetSystemMetrics(0) - width - 22), 22

            def signed_loword(value) -> int:
                raw = int(value) & 0xFFFF
                return raw - 0x10000 if raw & 0x8000 else raw

            def signed_hiword(value) -> int:
                raw = (int(value) >> 16) & 0xFFFF
                return raw - 0x10000 if raw & 0x8000 else raw

            def close_hit(x: int, y: int) -> bool:
                return width - 44 <= int(x) <= width - 10 and 8 <= int(y) <= 38

            def drain_commands(hwnd) -> None:
                while True:
                    try:
                        command = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if command[0] == "show":
                        state["model"] = self.model(command[1], command[2], command[3])
                        duration = float(command[4] or 0.0)
                        if state["model"].get("terminal"):
                            duration = 8.0
                        state["hide_at"] = time.time() + duration if duration > 0 else 0.0
                        state["visible"] = True
                        x, y = workarea_position()
                        user32.SetWindowPos(hwnd, -1, x, y, width, height, SWP_NOACTIVATE | SWP_SHOWWINDOW)
                        user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                        user32.InvalidateRect(hwnd, None, True)
                    elif command[0] == "hide":
                        state["visible"] = False
                        state["hide_at"] = 0.0
                        user32.ShowWindow(hwnd, SW_HIDE)
                    elif command[0] == "shutdown":
                        state["shutdown"] = True
                        user32.DestroyWindow(hwnd)
                        return
                if state["visible"] and state["hide_at"] and time.time() >= state["hide_at"]:
                    state["visible"] = False
                    state["hide_at"] = 0.0
                    user32.ShowWindow(hwnd, SW_HIDE)

            def draw_text(hdc, text: str, rect: RECT, color: str, font, flags: int) -> None:
                old_font = gdi32.SelectObject(hdc, font) if font else None
                gdi32.SetTextColor(hdc, colorref(color))
                gdi32.SetBkMode(hdc, TRANSPARENT)
                user32.DrawTextW(hdc, str(text or ""), -1, ctypes.byref(rect), flags)
                if old_font:
                    gdi32.SelectObject(hdc, old_font)

            def draw_line(hdc, x1: int, y1: int, x2: int, y2: int, color: str, width_px: int = 3) -> None:
                pen = gdi32.CreatePen(0, int(width_px), colorref(color))
                old_pen = gdi32.SelectObject(hdc, pen)
                try:
                    gdi32.MoveToEx(hdc, int(x1), int(y1), None)
                    gdi32.LineTo(hdc, int(x2), int(y2))
                finally:
                    if old_pen:
                        gdi32.SelectObject(hdc, old_pen)
                    gdi32.DeleteObject(pen)

            def fill_round_rect(hdc, left: int, top: int, right: int, bottom: int, fill: str, outline: str = "", radius: int = 8, width_px: int = 1) -> None:
                brush = gdi32.CreateSolidBrush(colorref(fill))
                pen = gdi32.CreatePen(0, int(width_px), colorref(outline or fill))
                old_brush = gdi32.SelectObject(hdc, brush)
                old_pen = gdi32.SelectObject(hdc, pen)
                try:
                    gdi32.RoundRect(hdc, int(left), int(top), int(right), int(bottom), int(radius), int(radius))
                finally:
                    if old_brush:
                        gdi32.SelectObject(hdc, old_brush)
                    if old_pen:
                        gdi32.SelectObject(hdc, old_pen)
                    gdi32.DeleteObject(brush)
                    gdi32.DeleteObject(pen)

            def draw_circle(hdc, x: int, y: int, radius: int, fill: str, outline: str = "", width_px: int = 1) -> None:
                brush = gdi32.CreateSolidBrush(colorref(fill))
                pen = gdi32.CreatePen(0, int(width_px), colorref(outline or fill))
                old_brush = gdi32.SelectObject(hdc, brush)
                old_pen = gdi32.SelectObject(hdc, pen)
                try:
                    gdi32.Ellipse(hdc, int(x - radius), int(y - radius), int(x + radius), int(y + radius))
                finally:
                    if old_brush:
                        gdi32.SelectObject(hdc, old_brush)
                    if old_pen:
                        gdi32.SelectObject(hdc, old_pen)
                    gdi32.DeleteObject(brush)
                    gdi32.DeleteObject(pen)

            def tone_color(model: dict) -> str:
                if model.get("terminal"):
                    if model.get("tone") == "success":
                        return colors["green"]
                    if model.get("tone") == "warning":
                        return colors["amber"]
                    if model.get("tone") == "error":
                        return colors["red"]
                return colors["blue"]

            @WNDPROC
            def wndproc(hwnd, msg, wparam, lparam):
                if msg == WM_TIMER:
                    drain_commands(hwnd)
                    return 0
                if msg == WM_LBUTTONDOWN:
                    return 0
                if msg == WM_LBUTTONUP:
                    if close_hit(signed_loword(lparam), signed_hiword(lparam)):
                        state["visible"] = False
                        state["hide_at"] = 0.0
                        user32.ShowWindow(hwnd, SW_HIDE)
                        return 0
                if msg == WM_PAINT:
                    ps = PAINTSTRUCT()
                    hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
                    model = state.get("model") or self.model("SCHT", "", "info")
                    client = RECT(0, 0, width, height)
                    bg_brush = gdi32.CreateSolidBrush(colorref(colors["bg"]))
                    try:
                        user32.FillRect(hdc, ctypes.byref(client), bg_brush)
                        fill_round_rect(hdc, 0, 0, width - 1, height - 1, colors["bg"], colors["border"], 22, 1)
                        label_rect = RECT(20, 14, width - 56, 32)
                        status_rect = RECT(20, 39, width - 62, 64)
                        detail_rect = RECT(20, 65, width - 62, 85)
                        draw_text(hdc, model.get("label") or "SCHT CONTRACT HANDLING", label_rect, colors["label"], fonts["label"], DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS)
                        draw_text(hdc, model.get("status") or "", status_rect, colors["title"], fonts["title"], DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS)
                        draw_text(hdc, model.get("detail") or "", detail_rect, colors["detail"], fonts["detail"], DT_LEFT | DT_SINGLELINE | DT_END_ELLIPSIS)
                        close_x, close_y = width - 24, 20
                        draw_line(hdc, close_x - 5, close_y - 5, close_x + 5, close_y + 5, colors["label"], 2)
                        draw_line(hdc, close_x + 5, close_y - 5, close_x - 5, close_y + 5, colors["label"], 2)
                        active_color = tone_color(model)
                        progress = max(0, min(100, int(model.get("progress") or 0)))
                        bar_left, bar_top, bar_right, bar_bottom = 20, 91, width - 82, 99
                        fill_round_rect(hdc, bar_left, bar_top, bar_right, bar_bottom, colors["inactive"], colors["inactive"], 8, 1)
                        if progress > 0:
                            fill_right = bar_left + int((bar_right - bar_left) * (progress / 100.0))
                            fill_round_rect(hdc, bar_left, bar_top, max(bar_left + 8, fill_right), bar_bottom, active_color, active_color, 8, 1)
                        percent_rect = RECT(width - 72, 84, width - 18, 105)
                        draw_text(hdc, f"{progress}%", percent_rect, active_color, fonts["percent"], DT_CENTER | DT_SINGLELINE)
                        note_rect = RECT(20, 108, width - 20, 140)
                        draw_text(hdc, model.get("note") or "", note_rect, colors["note"], fonts["note"], DT_LEFT | DT_WORDBREAK | DT_END_ELLIPSIS)
                    finally:
                        gdi32.DeleteObject(bg_brush)
                        user32.EndPaint(hwnd, ctypes.byref(ps))
                    return 0
                if msg == WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
                return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

            fonts["label"] = gdi32.CreateFontW(-11, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            fonts["title"] = gdi32.CreateFontW(-18, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            fonts["detail"] = gdi32.CreateFontW(-13, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            fonts["stage"] = gdi32.CreateFontW(-13, 0, 0, 0, 600, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            fonts["close"] = gdi32.CreateFontW(-20, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            fonts["percent"] = gdi32.CreateFontW(-13, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            fonts["note"] = gdi32.CreateFontW(-12, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, "Segoe UI")
            wc = WNDCLASS()
            wc.lpfnWndProc = wndproc
            wc.hInstance = hinst
            wc.hCursor = user32.LoadCursorW(None, 32512)
            wc.lpszClassName = class_name
            user32.RegisterClassW(ctypes.byref(wc))
            x, y = workarea_position()
            hwnd = user32.CreateWindowExW(
                WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                class_name,
                "SCHT OCR",
                WS_POPUP,
                x,
                y,
                width,
                height,
                None,
                None,
                hinst,
                None,
            )
            if not hwnd:
                return
            try:
                region = gdi32.CreateRoundRectRgn(0, 0, width + 1, height + 1, 22, 22)
                if region:
                    user32.SetWindowRgn(hwnd, region, True)
            except Exception:
                pass
            user32.SetTimer(hwnd, 1, 60, None)
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
            for font in fonts.values():
                if font:
                    gdi32.DeleteObject(font)
        except Exception:
            return


class OverlayController:
    """Own the desktop window integration and always-on-top Logistics Overlay."""

    MOD_CONTROL = 0x0002
    MOD_SHIFT = 0x0004
    WM_HOTKEY = 0x0312
    WM_QUIT = 0x0012

    def __init__(self, webview_module, base_url: str):
        self.webview = webview_module
        self.base_url = base_url.rstrip("/")
        self.overlay_window = None
        self.main_window = None
        self._lock = threading.RLock()
        self._visible = False
        self._locked = False  # legacy click-through state (hotkey compatibility)
        self._expanded = False  # legacy compact/expanded preset compatibility
        self._size_locked = False
        self._position_locked = False
        self._on_top = True
        self._opacity = 1.0
        self._position_anchor: Optional[Tuple[int, int]] = None
        self._size_anchor: Optional[Tuple[int, int]] = None
        self._save_timer: Optional[threading.Timer] = None
        self._main_save_timer: Optional[threading.Timer] = None
        self._main_move_lock = threading.Lock()
        self._main_move_active = False
        self._main_resize_lock = threading.Lock()
        self._main_resize_active = False
        # The custom frameless dashboard uses a work-area maximize state rather
        # than native SW_MAXIMIZE. Native maximize can cover the Windows taskbar
        # for popup-style WebView2 windows.
        self._main_workarea_maximized = False
        self._main_restore_rect: Optional[Tuple[int, int, int, int]] = None
        self._hotkey_thread: Optional[threading.Thread] = None
        self._hotkey_thread_id: Optional[int] = None
        self._hotkeys_registered: List[int] = []
        self._shutting_down = False
        self._ocr_notifier: Optional[OcrNotificationWindow] = None
        self.settings_path = app_data_directory() / "overlay-window.json"
        self.main_settings_path = app_data_directory() / "main-window.json"
        self.settings = self._load_settings()
        self.main_settings = _read_json_object(self.main_settings_path)
        # Main-window position is deliberately not restored. Previous desktop
        # builds could save a DPI-scaled/off-screen coordinate and reopen the app
        # against the far edge of the display. Keep only the user's preferred size
        # and center the dashboard on every launch.
        self.main_settings.pop("x", None)
        self.main_settings.pop("y", None)
        try:
            previous_main_layout = int(self.main_settings.get("layout_version", 0) or 0)
        except Exception:
            previous_main_layout = 0
        if previous_main_layout < MAIN_WINDOW_LAYOUT_VERSION:
            try:
                saved_width = int(self.main_settings.get("width", 0) or 0)
            except Exception:
                saved_width = 0
            # Older builds could persist the former 1180 px minimum, which forces
            # the primary toolbar below the Game.log field on common DPI scales.
            self.main_settings["width"] = max(saved_width, MAIN_WINDOW_PREFERRED_MIN_WIDTH)
            self.main_settings["layout_version"] = MAIN_WINDOW_LAYOUT_VERSION
            _write_json_object(self.main_settings_path, self.main_settings)
        # Never restore click-through across launches. A stale WS_EX_TRANSPARENT /
        # WS_EX_NOACTIVATE state can leave the next overlay visible but unusable.
        self._locked = False
        self._expanded = bool(self.settings.get("expanded", False))
        try:
            self._opacity = max(0.50, min(1.0, float(self.settings.get("opacity", 1.0))))
        except Exception:
            self._opacity = 1.0
        self._size_locked = bool(self.settings.get("size_locked", False))
        previous_layout = int(self.settings.get("layout_version", 0) or 0)
        # v3.5.11 enforced position lock by moving the HWND back during every
        # move event. That feedback loop could freeze WebView2 and the entire
        # application. Reset the old setting once; from v3.5.12 onward position
        # lock is implemented only by disabling the custom drag region.
        self._position_locked = False if previous_layout < 7 else bool(self.settings.get("position_locked", False))
        self._on_top = bool(self.settings.get("on_top", True))

        # Overlay position is deliberately not restored: every opening is centred
        # in the current primary work area. The user's size and window behaviour
        # preferences are retained.
        self.settings.pop("x", None)
        self.settings.pop("y", None)
        default_w, default_h = ((560, 720) if self._expanded else (430, 620))
        try:
            width = int(self.settings.get("width", default_w))
            height = int(self.settings.get("height", default_h))
        except Exception:
            width, height = default_w, default_h
        self.settings.update({
            "width": max(380, width),
            "height": max(360, height),
            "opacity": self._opacity,
            "size_locked": self._size_locked,
            "position_locked": self._position_locked,
            "on_top": self._on_top,
            "expanded": bool(self._expanded),
            "locked": False,
            "layout_version": 7,
        })
        _write_json_object(self.settings_path, self.settings)

    def _primary_work_area(self) -> Tuple[int, int, int, int]:
        """Return primary-monitor work area as left, top, width, height.

        Using the Windows work area (rather than only GetSystemMetrics) keeps both
        windows clear of the taskbar and uses the same coordinate space as the
        native HWND positioning APIs. The fallback remains suitable for tests and
        non-Windows source runs.
        """
        left, top, width, height = 0, 0, 1920, 1080
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                rect = RECT()
                SPI_GETWORKAREA = 0x0030
                if ctypes.windll.user32.SystemParametersInfoW(
                    SPI_GETWORKAREA, 0, ctypes.byref(rect), 0
                ):
                    candidate_w = int(rect.right - rect.left)
                    candidate_h = int(rect.bottom - rect.top)
                    if candidate_w > 0 and candidate_h > 0:
                        return int(rect.left), int(rect.top), candidate_w, candidate_h
                width = int(ctypes.windll.user32.GetSystemMetrics(0)) or width
                height = int(ctypes.windll.user32.GetSystemMetrics(1)) or height
            except Exception:
                pass
        return left, top, width, height

    def _screen_size(self) -> Tuple[int, int]:
        _left, _top, width, height = self._primary_work_area()
        return width, height

    def _centered_geometry(self, width: int, height: int) -> dict:
        left, top, work_w, work_h = self._primary_work_area()
        width = max(1, min(int(width), work_w))
        height = max(1, min(int(height), work_h))
        return {
            "x": int(left + max(0, (work_w - width) // 2)),
            "y": int(top + max(0, (work_h - height) // 2)),
            "width": width,
            "height": height,
        }

    def main_window_geometry(self) -> dict:
        """Return a centered main-window rectangle with a one-line toolbar."""
        _left, _top, work_w, work_h = self._primary_work_area()
        width = min(MAIN_WINDOW_DEFAULT_WIDTH, max(1, work_w - 40))
        height = max(MAIN_WINDOW_MIN_HEIGHT, min(950, work_h - 60))
        for key in ("width", "height"):
            try:
                if key in self.main_settings:
                    if key == "width":
                        width = int(self.main_settings[key])
                    else:
                        height = int(self.main_settings[key])
            except Exception:
                pass
        preferred_min = min(MAIN_WINDOW_PREFERRED_MIN_WIDTH, work_w)
        width = max(preferred_min, min(work_w, width))
        height = max(min(MAIN_WINDOW_MIN_HEIGHT, work_h), min(work_h, height))
        return self._centered_geometry(width, height)

    def _save_main_settings_now(self) -> None:
        with self._lock:
            # Persist size only. Position is centered at the next launch.
            payload = {
                "width": int(self.main_settings.get("width", 0) or 0),
                "height": int(self.main_settings.get("height", 0) or 0),
                "layout_version": MAIN_WINDOW_LAYOUT_VERSION,
            }
        payload = {k: v for k, v in payload.items() if k == "layout_version" or v > 0}
        _write_json_object(self.main_settings_path, payload)

    def _schedule_main_save(self) -> None:
        with self._lock:
            if self._main_save_timer:
                self._main_save_timer.cancel()
            self._main_save_timer = threading.Timer(0.25, self._save_main_settings_now)
            self._main_save_timer.daemon = True
            self._main_save_timer.start()

    def _default_geometry(self) -> dict:
        # Restore the user's preferred size, but always centre the overlay when it
        # is created. This stays reliable across monitor and DPI changes.
        _left, _top, work_w, work_h = self._primary_work_area()
        try:
            target_width = int(self.settings.get("width", 430))
            target_height = int(self.settings.get("height", 620))
        except Exception:
            target_width, target_height = 430, 620
        width = max(min(380, work_w), min(target_width, max(380, work_w - 40)))
        height = max(min(360, work_h), min(target_height, max(360, work_h - 40)))
        return self._centered_geometry(width, height)

    def _load_settings(self) -> dict:
        try:
            data = json.loads(self.settings_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_settings_now(self) -> None:
        with self._lock:
            payload = {
                "locked": False,
                "expanded": bool(self._expanded),
                "width": int(self.settings.get("width", 430) or 430),
                "height": int(self.settings.get("height", 620) or 620),
                "opacity": float(self._opacity),
                "size_locked": bool(self._size_locked),
                "position_locked": bool(self._position_locked),
                "on_top": bool(self._on_top),
                "layout_version": 7,
            }
        try:
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            self.settings_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _schedule_save(self) -> None:
        with self._lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.25, self._save_settings_now)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _geometry(self) -> dict:
        # Never restore an old position. Centering on every creation is the most
        # reliable behavior across monitor, taskbar, resolution, and DPI changes.
        return self._default_geometry()

    def attach_main_window(self, window) -> None:
        self.main_window = window
        window.events.shown += self._on_main_shown
        window.events.resized += self._on_main_resized
        window.events.closed += self.shutdown

    def _window_hwnd(self, window) -> Optional[int]:
        if os.name != "nt" or window is None:
            return None
        try:
            handle = window.native.Handle
            try:
                hwnd = int(handle.ToInt64())
            except Exception:
                hwnd = int(handle.ToInt32())
            try:
                import ctypes
                root = int(ctypes.windll.user32.GetAncestor(hwnd, 2))  # GA_ROOT
                if root:
                    hwnd = root
            except Exception:
                pass
            return hwnd or None
        except Exception:
            return None

    def _center_native_window(self, window, geometry: dict, *, topmost: bool = False, activate: bool = False, resize: bool = True) -> None:
        """Center a pywebview window using both public and native APIs.

        The public move call covers normal backends. SetWindowPos is a Windows
        fallback for dynamic WebView2 windows that exist in the taskbar but retain
        an off-screen rectangle. It applies one deterministic rectangle only; there
        is no repeated resize/recovery loop.
        """
        if window is None:
            return
        if resize:
            try:
                window.resize(int(geometry["width"]), int(geometry["height"]))
            except Exception:
                pass
        try:
            window.move(int(geometry["x"]), int(geometry["y"]))
        except Exception:
            pass
        hwnd = self._window_hwnd(window)
        if hwnd is None:
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            SWP_NOSIZE = 0x0001
            SWP_SHOWWINDOW = 0x0040
            SWP_NOACTIVATE = 0x0010
            insert_after = HWND_TOPMOST if topmost else HWND_NOTOPMOST
            flags = SWP_SHOWWINDOW | (0 if activate else SWP_NOACTIVATE)
            width = int(geometry["width"])
            height = int(geometry["height"])
            if not resize:
                flags |= SWP_NOSIZE
                width = height = 0
            user32.ShowWindow(hwnd, SW_RESTORE)
            user32.SetWindowPos(
                hwnd,
                insert_after,
                int(geometry["x"]),
                int(geometry["y"]),
                width,
                height,
                flags,
            )
            user32.EnableWindow(hwnd, True)
            if activate:
                user32.BringWindowToTop(hwnd)
                user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _center_main_window(self) -> None:
        if not self.main_window:
            return
        self._center_native_window(
            self.main_window,
            self.main_window_geometry(),
            topmost=False,
            activate=False,
        )

    def _center_overlay_window(self, *, activate: bool = True) -> None:
        if not self._overlay_alive():
            return
        geometry = self._default_geometry()
        self._center_native_window(
            self.overlay_window,
            geometry,
            topmost=bool(self._on_top),
            activate=activate,
            resize=False,
        )

    def _schedule_center_overlay(self) -> None:
        # Dynamic WebView2 windows may not expose their HWND immediately. Two
        # harmless move-only follow-ups center the same fixed rectangle once the
        # native host exists.
        for delay in (0.20, 0.75):
            timer = threading.Timer(delay, self._center_overlay_window)
            timer.daemon = True
            timer.start()

    def _apply_main_chrome(self) -> None:
        """Apply dark rounded DWM chrome while retaining the native resize frame."""
        hwnd = self._window_hwnd(self.main_window)
        if hwnd is None or os.name != "nt":
            return
        try:
            import ctypes
            dark = ctypes.c_int(1)
            rounded = ctypes.c_int(2)
            border_none = ctypes.c_uint(0xFFFFFFFE)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_none), ctypes.sizeof(border_none))
        except Exception:
            pass

    def _on_main_shown(self) -> None:
        self._center_main_window()
        self._apply_main_chrome()
        timer = threading.Timer(0.30, self._center_main_window)
        timer.daemon = True
        timer.start()
        chrome_timer = threading.Timer(0.35, self._apply_main_chrome)
        chrome_timer.daemon = True
        chrome_timer.start()
        self.start_hotkeys()

    def _on_main_moved(self, x: int, y: int) -> None:
        # Position is intentionally not persisted; the app always opens centered.
        return

    def _on_main_resized(self, width: int, height: int) -> None:
        if self.get_main_window_status().get("maximized"):
            return
        with self._lock:
            self.main_settings["width"], self.main_settings["height"] = int(width), int(height)
        self._schedule_main_save()

    def _dialog_path(self, result) -> Optional[Path]:
        if not result:
            return None
        if isinstance(result, (list, tuple)):
            result = result[0] if result else None
        return Path(str(result)) if result else None

    def get_main_window_status(self) -> dict:
        hwnd = self._window_hwnd(self.main_window)
        native_maximized = False
        minimized = False
        if hwnd is not None and os.name == "nt":
            try:
                import ctypes
                native_maximized = bool(ctypes.windll.user32.IsZoomed(hwnd))
                minimized = bool(ctypes.windll.user32.IsIconic(hwnd))
            except Exception:
                pass
        return {
            "available": self.main_window is not None,
            "maximized": bool(self._main_workarea_maximized or native_maximized),
            "minimized": minimized,
            "frameless": True,
            "uses_work_area": bool(self._main_workarea_maximized),
        }

    def _finish_main_native_resize(self, width: int, height: int) -> None:
        if self.get_main_window_status().get("maximized"):
            return
        with self._lock:
            self.main_settings["width"] = max(MAIN_WINDOW_PREFERRED_MIN_WIDTH, int(width))
            self.main_settings["height"] = max(720, int(height))
        self._schedule_main_save()

    def begin_main_move(self) -> dict:
        """Start one borderless native move drag from the custom main title strip."""
        status = self.get_main_window_status()
        hwnd = self._window_hwnd(self.main_window)
        if hwnd is None or os.name != "nt" or status.get("maximized"):
            main_window_diagnostic_log(
                f"main move rejected; hwnd={hwnd!r}; platform={os.name!r}; "
                f"maximized={status.get('maximized')}"
            )
            status["command_ok"] = False
            return status
        with self._main_move_lock:
            if self._main_move_active:
                main_window_diagnostic_log("main move rejected because another move drag is active")
                status["command_ok"] = False
                return status
            self._main_move_active = True

        def worker() -> None:
            try:
                run_borderless_move_loop(hwnd, diagnostic=main_window_diagnostic_log)
            finally:
                with self._main_move_lock:
                    self._main_move_active = False

        threading.Thread(target=worker, daemon=True, name="sc-main-borderless-move").start()
        main_window_diagnostic_log(f"main move worker launched; hwnd=0x{hwnd:X}; thread={threading.get_ident()}")
        status["command_ok"] = True
        status["move_started"] = True
        return status

    def begin_main_resize(self, direction: str) -> dict:
        """Start one borderless native resize drag from a main-window edge."""
        status = self.get_main_window_status()
        direction_key = str(direction or "").lower()
        hwnd = self._window_hwnd(self.main_window)
        if (
            os.name != "nt"
            or hwnd is None
            or direction_key not in NATIVE_RESIZE_DIRECTION_CODES
            or status.get("maximized")
        ):
            status["command_ok"] = False
            return status
        with self._main_resize_lock:
            if self._main_resize_active:
                status["command_ok"] = False
                return status
            self._main_resize_active = True

        def worker() -> None:
            try:
                run_borderless_resize_loop(
                    hwnd,
                    direction_key,
                    MAIN_WINDOW_PREFERRED_MIN_WIDTH,
                    720,
                    on_complete=self._finish_main_native_resize,
                )
            finally:
                with self._main_resize_lock:
                    self._main_resize_active = False

        thread = threading.Thread(target=worker, daemon=True, name="sc-main-borderless-resize")
        thread.start()
        status["command_ok"] = True
        status["resize_started"] = True
        return status

    def minimize_main_window(self) -> dict:
        if self.main_window is not None:
            try:
                self.main_window.minimize()
            except Exception:
                hwnd = self._window_hwnd(self.main_window)
                if hwnd is not None and os.name == "nt":
                    try:
                        import ctypes
                        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                    except Exception:
                        pass
        status = self.get_main_window_status()
        status["command_ok"] = True
        return status

    def _main_window_rect(self) -> Optional[Tuple[int, int, int, int]]:
        hwnd = self._window_hwnd(self.main_window)
        if hwnd is None or os.name != "nt":
            return None
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return (
                    int(rect.left),
                    int(rect.top),
                    max(1, int(rect.right - rect.left)),
                    max(1, int(rect.bottom - rect.top)),
                )
        except Exception:
            pass
        return None

    def _main_monitor_work_area(self, hwnd: int) -> Tuple[int, int, int, int]:
        """Return the work area for the monitor containing the main window."""
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                class MONITORINFO(ctypes.Structure):
                    _fields_ = [
                        ("cbSize", wintypes.DWORD),
                        ("rcMonitor", RECT),
                        ("rcWork", RECT),
                        ("dwFlags", wintypes.DWORD),
                    ]

                MONITOR_DEFAULTTONEAREST = 2
                monitor = ctypes.windll.user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
                info = MONITORINFO()
                info.cbSize = ctypes.sizeof(MONITORINFO)
                if monitor and ctypes.windll.user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
                    rect = info.rcWork
                    width = int(rect.right - rect.left)
                    height = int(rect.bottom - rect.top)
                    if width > 0 and height > 0:
                        return int(rect.left), int(rect.top), width, height
            except Exception:
                pass
        return self._primary_work_area()

    def toggle_main_maximize(self) -> dict:
        """Toggle a taskbar-safe work-area maximize for the frameless dashboard."""
        if self.main_window is None:
            return {**self.get_main_window_status(), "command_ok": False}
        hwnd = self._window_hwnd(self.main_window)
        if hwnd is None or os.name != "nt":
            return {**self.get_main_window_status(), "command_ok": False}

        try:
            import ctypes

            user32 = ctypes.windll.user32
            SW_RESTORE = 9
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_SHOWWINDOW = 0x0040

            # Clear a native zoom state first. The custom window should never use
            # SW_MAXIMIZE because popup-style WebView2 windows may cover the taskbar.
            if user32.IsZoomed(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)

            if self._main_workarea_maximized:
                geometry = self._main_restore_rect
                if geometry is None:
                    fallback = self.main_window_geometry()
                    geometry = (
                        int(fallback["x"]),
                        int(fallback["y"]),
                        int(fallback["width"]),
                        int(fallback["height"]),
                    )
                self._main_workarea_maximized = False
                x, y, width, height = geometry
                ok = bool(user32.SetWindowPos(
                    hwnd, 0, int(x), int(y), int(width), int(height),
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                ))
                if ok:
                    self._main_restore_rect = None
            else:
                self._main_restore_rect = self._main_window_rect()
                left, top, width, height = self._main_monitor_work_area(hwnd)
                # Set the state before SetWindowPos so resize callbacks do not save
                # the work-area dimensions as the user's normal window size.
                self._main_workarea_maximized = True
                ok = bool(user32.SetWindowPos(
                    hwnd, 0, int(left), int(top), int(width), int(height),
                    SWP_NOZORDER | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                ))
                if not ok:
                    self._main_workarea_maximized = False

            if not ok:
                status = self.get_main_window_status()
                status["command_ok"] = False
                return status
        except Exception as exc:
            main_window_diagnostic_log(f"work-area maximize failed: {exc!r}")
            self._main_workarea_maximized = False
            status = self.get_main_window_status()
            status["command_ok"] = False
            return status

        self._apply_main_chrome()
        status = self.get_main_window_status()
        status["command_ok"] = True
        return status

    def close_main_window(self) -> dict:
        status = self.get_main_window_status()
        status.update({"command_ok": True, "closing": True})
        window = self.main_window
        if window is not None:
            def close_window() -> None:
                try:
                    window.destroy()
                except Exception:
                    hwnd = self._window_hwnd(window)
                    if hwnd is not None and os.name == "nt":
                        try:
                            import ctypes
                            ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
                        except Exception:
                            pass
            timer = threading.Timer(0.08, close_window)
            timer.daemon = True
            timer.start()
        return status

    def browse_log(self) -> dict:
        if not self.main_window:
            return {"ok": False, "error": "Main application window is unavailable."}
        try:
            result = self.main_window.create_file_dialog(
                self.webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Log files (*.log)", "All files (*.*)"),
            )
            path = self._dialog_path(result)
            return {"ok": True, "path": str(path) if path else ""}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _notification_window(self) -> OcrNotificationWindow:
        with self._lock:
            if self._ocr_notifier is None:
                self._ocr_notifier = OcrNotificationWindow()
            return self._ocr_notifier

    def show_ocr_notification(self, title: str, message: str, tone: str = "info", duration: float = 0.0) -> dict:
        self._notification_window().show(title, message, tone, duration)
        return {"ok": True}

    def hide_ocr_notification(self) -> dict:
        if self._ocr_notifier is not None:
            self._ocr_notifier.hide()
        return {"ok": True}

    def debug_ocr_notification_sequence(self) -> dict:
        notifier = self._notification_window()

        def run_sequence() -> None:
            steps = [
                ("Contract detected", "Accepted hauling contract identified", "info", 0.75),
                ("Capturing screen", "DPI-aware live capture in progress", "info", 0.85),
                ("Reading contract", "Recognition in progress", "info", 1.0),
                ("Contract imported", "4 objectives · 101,000 aUEC", "success", 1.35),
                ("Contract detected", "Accepted hauling contract identified", "info", 0.7),
                ("Capturing screen", "DPI-aware live capture in progress", "info", 0.8),
                ("Reading contract", "Recognition in progress", "info", 0.95),
                ("Contract needs review", "2 fields need verification in SCHT.", "warning", 3.5),
            ]
            for title, message, tone, pause in steps:
                notifier.show(title, message, tone, 0.0)
                time.sleep(float(pause))

        thread = threading.Thread(target=run_sequence, daemon=True, name="scht-ocr-notification-debug")
        thread.start()
        return {"ok": True}

    def capture_star_citizen_window(self) -> dict:
        # Capture the foreground Star Citizen client area to a temporary PNG.
        if os.name != "nt":
            return {"ok": False, "error": "Automatic capture is available only in the Windows desktop app."}
        temp_dir = app_data_directory() / "ocr-temp"
        temp_dir.mkdir(parents=True, exist_ok=True)
        image_path = temp_dir / f"contract-{os.getpid()}-{int(time.time() * 1000)}.png"
        script = r'''
param([Parameter(Mandatory=$true)][string]$Path)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing
Add-Type @"
using System;
using System.Runtime.InteropServices;
public static class SCHTCapture {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left; public int Top; public int Right; public int Bottom; }
  [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X; public int Y; }
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetProcessDpiAwarenessContext(IntPtr dpiContext);
  [DllImport("user32.dll")] public static extern uint GetDpiForWindow(IntPtr hWnd);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);
  [DllImport("user32.dll")] public static extern bool GetClientRect(IntPtr hWnd, out RECT rect);
  [DllImport("user32.dll")] public static extern bool ClientToScreen(IntPtr hWnd, ref POINT point);
}
"@
try {
  # Without this, Windows may virtualize Star Citizen dimensions on scaled
  # displays (for example 2048 logical px for a 2560 physical px client), which
  # crops the right side of the live capture before OCR sees it.
  if (-not [SCHTCapture]::SetProcessDpiAwarenessContext([IntPtr]::new(-4))) {
    [SCHTCapture]::SetProcessDPIAware() | Out-Null
  }
} catch {
  try { [SCHTCapture]::SetProcessDPIAware() | Out-Null } catch {}
}
$hwnd = [SCHTCapture]::GetForegroundWindow()
if ($hwnd -eq [IntPtr]::Zero) { throw "No foreground window is available." }
[uint32]$pidValue = 0
[SCHTCapture]::GetWindowThreadProcessId($hwnd, [ref]$pidValue) | Out-Null
$process = Get-Process -Id $pidValue -ErrorAction Stop
if ($process.ProcessName -notmatch "StarCitizen") { throw "Star Citizen is not the foreground application. Keep the accepted contract page open in game." }
$rect = New-Object SCHTCapture+RECT
if (-not [SCHTCapture]::GetClientRect($hwnd, [ref]$rect)) { throw "Could not read the Star Citizen window bounds." }
$point = New-Object SCHTCapture+POINT
$point.X = 0; $point.Y = 0
if (-not [SCHTCapture]::ClientToScreen($hwnd, [ref]$point)) { throw "Could not translate the Star Citizen client coordinates." }
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -lt 640 -or $height -lt 480) { throw "The Star Citizen window is minimized or too small to read." }
$dpi = 0
try { $dpi = [SCHTCapture]::GetDpiForWindow($hwnd) } catch {}
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
try {
  $graphics.CopyFromScreen($point.X, $point.Y, 0, 0, $bitmap.Size, [System.Drawing.CopyPixelOperation]::SourceCopy)
  $maxDimension = 2400
  if ($width -gt $maxDimension -or $height -gt $maxDimension) {
    $scale = [Math]::Min($maxDimension / [double]$width, $maxDimension / [double]$height)
    $scaledWidth = [Math]::Max(1, [int]($width * $scale))
    $scaledHeight = [Math]::Max(1, [int]($height * $scale))
    $scaled = New-Object System.Drawing.Bitmap($scaledWidth, $scaledHeight)
    $scaledGraphics = [System.Drawing.Graphics]::FromImage($scaled)
    try {
      $scaledGraphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
      $scaledGraphics.DrawImage($bitmap, 0, 0, $scaledWidth, $scaledHeight)
      $scaled.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
      $scaledGraphics.Dispose(); $scaled.Dispose()
    }
  } else {
    $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
  }
} finally {
  $graphics.Dispose(); $bitmap.Dispose()
}
Write-Output ($process.ProcessName + "|" + $width + "|" + $height + "|" + $dpi)
'''
        script_path = temp_dir / f"capture-{os.getpid()}-{int(time.time() * 1000)}.ps1"
        script_path.write_text(script, encoding="utf-8")
        try:
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path), "-Path", str(image_path)],
                text=True, capture_output=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except Exception as exc:
            try: image_path.unlink()
            except Exception: pass
            return {"ok": False, "error": str(exc)}
        finally:
            try: script_path.unlink()
            except Exception: pass
        if completed.returncode != 0 or not image_path.exists():
            try: image_path.unlink()
            except Exception: pass
            detail = (completed.stderr or completed.stdout or "Star Citizen capture failed.").strip()
            return {"ok": False, "error": detail}
        return {"ok": True, "path": str(image_path), "window": completed.stdout.strip()}

    def browse_ocr_image(self) -> dict:
        if not self.main_window:
            return {"ok": False, "error": "Main application window is unavailable."}
        try:
            result = self.main_window.create_file_dialog(
                self.webview.OPEN_DIALOG,
                allow_multiple=False,
                file_types=("Image files (*.png;*.jpg;*.jpeg;*.bmp)", "All files (*.*)"),
            )
            path = self._dialog_path(result)
            return {"ok": True, "path": str(path) if path else ""}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _export_via_dialog(self, endpoint: str, filename: str, file_types: Tuple[str, ...]) -> dict:
        if not self.main_window:
            return {"ok": False, "error": "Main application window is unavailable."}
        try:
            result = self.main_window.create_file_dialog(
                self.webview.SAVE_DIALOG,
                save_filename=filename,
                file_types=file_types,
            )
            path = self._dialog_path(result)
            if not path:
                return {"ok": True, "cancelled": True}
            expected_suffix = Path(filename).suffix
            if expected_suffix and not path.suffix:
                path = path.with_suffix(expected_suffix)
            import urllib.request
            with urllib.request.urlopen(f"{self.base_url}{endpoint}", timeout=15) as response:
                data = response.read()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return {"ok": True, "path": str(path)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def export_csv_file(self) -> dict:
        return self._export_via_dialog("/export.csv", "sc_hauling_manifest.csv", ("CSV files (*.csv)", "All files (*.*)"))

    def export_html_file(self) -> dict:
        return self._export_via_dialog("/export.html", "sc_hauling_manifest.html", ("HTML files (*.html)", "All files (*.*)"))

    def _overlay_alive(self) -> bool:
        return bool(self.overlay_window and not self.overlay_window.events.closed.is_set())

    def _ensure_overlay(self):
        with self._lock:
            if self._overlay_alive():
                return self.overlay_window
            geometry = self._geometry()
            # Frameless is safe as long as the native window remains opaque and
            # focusable. The earlier interaction failure came from the transparent /
            # no-activate path, not from removing the Windows frame itself.
            kwargs = dict(
                title="SC Hauling Overlay",
                url=f"{self.base_url}/overlay",
                js_api=self,
                width=geometry["width"],
                height=geometry["height"],
                x=geometry["x"],
                y=geometry["y"],
                min_size=(380, 360),
                resizable=not self._size_locked,
                # Create the overlay as a visible dynamic window. The hidden→show
                # lifecycle was the source of taskbar-only invisible windows on the
                # target WebView2 installation.
                hidden=False,
                frameless=True,
                easy_drag=False,
                shadow=True,
                focus=True,
                on_top=bool(self._on_top),
                transparent=False,
                background_color="#0c0c13",
                text_select=False,
            )
            try:
                window = self.webview.create_window(**kwargs)
            except TypeError:
                # Compatibility with older pywebview builds.
                kwargs.pop("transparent", None)
                kwargs.pop("focus", None)
                window = self.webview.create_window(**kwargs)
            self.overlay_window = window
            window.events.shown += self._on_overlay_shown
            window.events.closed += lambda: self._on_overlay_closed(window)
            # Do not subscribe to moved events. WebView2 can emit them for every
            # pixel of a drag, and routing that stream through Python can stall the
            # GUI. Position lock is enforced entirely by the drag-region class.
            window.events.resized += self._on_overlay_resized
            return window

    def _apply_frameless_chrome(self) -> None:
        """Ask Windows 11 for rounded corners/dark chrome without transparency."""
        if os.name != "nt" or not self._overlay_alive():
            return
        try:
            import ctypes
            native = self.overlay_window.native
            handle = native.Handle
            try:
                hwnd = int(handle.ToInt64())
            except Exception:
                hwnd = int(handle.ToInt32())
            dwmapi = ctypes.windll.dwmapi
            # DWMWA_USE_IMMERSIVE_DARK_MODE = 20, DWMWA_WINDOW_CORNER_PREFERENCE = 33
            dark = ctypes.c_int(1)
            rounded = ctypes.c_int(2)  # DWMWCP_ROUND
            dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
        except Exception:
            pass

    def _current_overlay_rect(self) -> Optional[Tuple[int, int, int, int]]:
        if not self._overlay_alive():
            return None
        hwnd = self._window_hwnd(self.overlay_window)
        if hwnd is not None:
            try:
                import ctypes
                from ctypes import wintypes

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                rect = RECT()
                if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return (
                        int(rect.left),
                        int(rect.top),
                        max(1, int(rect.right - rect.left)),
                        max(1, int(rect.bottom - rect.top)),
                    )
            except Exception:
                pass
        geometry = self._default_geometry()
        try:
            x = int(getattr(self.overlay_window, "x", geometry["x"]))
            y = int(getattr(self.overlay_window, "y", geometry["y"]))
            width = int(getattr(self.overlay_window, "width", geometry["width"]))
            height = int(getattr(self.overlay_window, "height", geometry["height"]))
            return x, y, width, height
        except Exception:
            return geometry["x"], geometry["y"], geometry["width"], geometry["height"]

    def _capture_position_anchor(self) -> None:
        rect = self._current_overlay_rect()
        if rect:
            self._position_anchor = (int(rect[0]), int(rect[1]))

    def _capture_size_anchor(self) -> None:
        rect = self._current_overlay_rect()
        if rect:
            self._size_anchor = (int(rect[2]), int(rect[3]))

    def _apply_size_lock(self, locked: Optional[bool] = None) -> bool:
        """Enable or remove the native resize frame without adding a title bar."""
        if locked is not None:
            self._size_locked = bool(locked)
        if not self._overlay_alive():
            return False
        if self._size_locked:
            self._capture_size_anchor()
        else:
            self._size_anchor = None
        if os.name != "nt":
            self._notify_overlay_settings()
            return False
        hwnd = self._window_hwnd(self.overlay_window)
        if hwnd is None:
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_style.restype = ctypes.c_ssize_t
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            WS_MAXIMIZEBOX = 0x00010000
            style = int(get_style(hwnd, GWL_STYLE))
            if self._size_locked:
                style &= ~(WS_THICKFRAME | WS_MAXIMIZEBOX)
            else:
                style |= WS_THICKFRAME | WS_MAXIMIZEBOX
            set_style(hwnd, GWL_STYLE, style)
            SWP_NOSIZE = 0x0001
            SWP_NOMOVE = 0x0002
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
            user32.SetWindowPos(
                hwnd, 0, 0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
            )
            return True
        except Exception:
            return False

    def _apply_overlay_opacity(self) -> bool:
        if not self._overlay_alive():
            return False
        value = max(0.50, min(1.0, float(self._opacity)))
        try:
            native = self.overlay_window.native
            native.Opacity = value
            return True
        except Exception:
            return False

    def _apply_topmost(self) -> bool:
        if not self._overlay_alive():
            return False
        applied = False
        try:
            self.overlay_window.on_top = bool(self._on_top)
        except Exception:
            pass
        try:
            self.overlay_window.native.TopMost = bool(self._on_top)
            applied = True
        except Exception:
            pass
        if os.name == "nt":
            hwnd = self._window_hwnd(self.overlay_window)
            if hwnd is not None:
                try:
                    import ctypes
                    user32 = ctypes.windll.user32
                    HWND_TOPMOST = -1
                    HWND_NOTOPMOST = -2
                    SWP_NOSIZE = 0x0001
                    SWP_NOMOVE = 0x0002
                    SWP_NOACTIVATE = 0x0010
                    SWP_SHOWWINDOW = 0x0040
                    user32.SetWindowPos(
                        hwnd,
                        HWND_TOPMOST if self._on_top else HWND_NOTOPMOST,
                        0, 0, 0, 0,
                        SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW,
                    )
                    applied = True
                except Exception:
                    pass
        return applied

    def set_overlay_opacity(self, opacity: float) -> dict:
        with self._lock:
            try:
                self._opacity = max(0.50, min(1.0, float(opacity)))
            except Exception:
                self._opacity = 1.0
            self.settings["opacity"] = self._opacity
            self._apply_overlay_opacity()
            self._schedule_save()
            result = self.get_overlay_status()
        self._notify_overlay_settings()
        return result

    def set_overlay_size_locked(self, locked: bool) -> dict:
        with self._lock:
            self._size_locked = bool(locked)
            self.settings["size_locked"] = self._size_locked
            self._apply_size_lock(self._size_locked)
            self._schedule_save()
            result = self.get_overlay_status()
        self._notify_overlay_settings()
        return result

    def set_overlay_position_locked(self, locked: bool) -> dict:
        """Enable/disable header dragging without moving the native window.

        The previous implementation listened for every move event and immediately
        moved the HWND back to an anchor. On WebView2 this could create a recursive
        move-event storm and freeze both windows. A frameless overlay can only be
        moved through the custom drag region, so removing that region is sufficient
        to lock its position safely.
        """
        with self._lock:
            self._position_locked = bool(locked)
            self.settings["position_locked"] = self._position_locked
            self._position_anchor = None
            self._schedule_save()
            result = self.get_overlay_status()
        self._notify_overlay_settings()
        return result

    def set_overlay_on_top(self, on_top: bool) -> dict:
        with self._lock:
            self._on_top = bool(on_top)
            self.settings["on_top"] = self._on_top
            self._apply_topmost()
            self._schedule_save()
            result = self.get_overlay_status()
        self._notify_overlay_settings()
        return result

    def fit_overlay_height(self, requested_height: int) -> dict:
        """Compatibility no-op: the overlay uses a stable native viewport."""
        return self.get_overlay_status()

    def _on_overlay_shown(self) -> None:
        self._visible = True
        self._locked = False
        self._apply_click_through(False)
        self._apply_frameless_chrome()
        self._apply_size_lock(self._size_locked)
        self._apply_overlay_opacity()
        self._apply_topmost()
        self._center_overlay_window(activate=True)
        # Do not schedule delayed recentering: a timer firing while the user starts
        # dragging can fight the native move loop and freeze WebView2.
        self._focus_overlay()
        self._notify_overlay_settings()

    def _on_overlay_closed(self, closed_window=None) -> None:
        with self._lock:
            if closed_window is None or self.overlay_window is closed_window:
                self.overlay_window = None
                self._visible = False
                self._position_anchor = None
                self._size_anchor = None

    def _on_overlay_moved(self, x: int, y: int) -> None:
        """Observe movement without issuing any native move calls.

        Position is intentionally not persisted between openings because each new
        overlay is centered. Most importantly, this callback must never fight an
        in-progress drag with window.move(), which can deadlock the WebView2 UI
        thread.
        """
        return

    def _on_overlay_resized(self, width: int, height: int) -> None:
        """Persist a completed resize without issuing a compensating resize.

        Native size locking is handled by removing the resize frame. Calling
        resize() from inside a resize event can recursively generate more events
        and freeze WebView2, so this handler is deliberately passive.
        """
        width, height = int(width), int(height)
        if width <= 0 or height <= 0 or self._size_locked:
            return
        with self._lock:
            self.settings["width"] = max(380, width)
            self.settings["height"] = max(360, height)
            self._expanded = width >= 500 or height >= 680
        self._schedule_save()

    def _notify_overlay_settings(self) -> None:
        window = self.overlay_window
        if not window:
            return
        try:
            payload = json.dumps(self.get_overlay_status())
            window.evaluate_js(f"window.applyNativeSettings && window.applyNativeSettings({payload});")
        except Exception:
            pass

    def _notify_lock_state(self) -> None:
        # Kept for the legacy click-through hotkey; the settings UI consumes the
        # complete status object instead of a separate lock-only callback.
        self._notify_overlay_settings()

    def _focus_overlay(self) -> None:
        """Return the unlocked overlay to normal interactive foreground use."""
        if not self._overlay_alive():
            return
        try:
            self.overlay_window.focus()
        except Exception:
            pass
        if os.name != "nt":
            return
        try:
            import ctypes
            native = self.overlay_window.native
            handle = native.Handle
            try:
                hwnd = int(handle.ToInt64())
            except Exception:
                hwnd = int(handle.ToInt32())
            user32 = ctypes.windll.user32
            try:
                native.Enabled = True
                native.Show()
                native.Activate()
                native.Focus()
                if getattr(native, "webview", None) is not None:
                    native.webview.Enabled = True
                    native.webview.Focus()
            except Exception:
                pass
            user32.EnableWindow(hwnd, True)
            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
            user32.SetActiveWindow(hwnd)
            user32.SetFocus(hwnd)
        except Exception:
            pass

    def _apply_click_through(self, locked: bool) -> bool:
        """Apply click-through only while locked; unlocked mode stays fully interactive."""
        if os.name != "nt" or not self._overlay_alive():
            self._notify_lock_state()
            return False
        try:
            import ctypes
            from ctypes import wintypes
            native = self.overlay_window.native
            handle = native.Handle
            try:
                hwnd = int(handle.ToInt64())
            except Exception:
                hwnd = int(handle.ToInt32())
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_style.restype = ctypes.c_ssize_t
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_LAYERED = 0x00080000
            style = int(get_style(hwnd, GWL_EXSTYLE))
            if locked:
                style |= WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_LAYERED
            else:
                # Remove every style introduced by click-through. WS_EX_LAYERED is
                # also cleared because a layered parent around WebView2 can remain
                # visible while swallowing mouse input on some Windows systems.
                style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_LAYERED)
            set_style(hwnd, GWL_EXSTYLE, style)
            if not locked:
                try:
                    native.Enabled = True
                    if getattr(native, "webview", None) is not None:
                        native.webview.Enabled = True
                except Exception:
                    pass
                user32.EnableWindow(hwnd, True)
            SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x0001, 0x0002, 0x0010, 0x0020, 0x0040
            flags = SWP_NOSIZE | SWP_NOMOVE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
            if locked:
                flags |= SWP_NOACTIVATE
            insert_after = -1 if self._on_top else -2
            user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags)
            if not locked:
                self._apply_overlay_opacity()
                self._apply_topmost()
            self._notify_lock_state()
            return True
        except Exception:
            self._notify_lock_state()
            return False

    def _show_overlay(self, unlock: bool) -> dict:
        """Create/show a fresh centered overlay in normal interactive mode."""
        with self._lock:
            window = self._ensure_overlay()
            if unlock:
                self._locked = False
            self._visible = True
            try:
                window.restore()
            except Exception:
                pass
            try:
                window.show()
            except Exception:
                pass
            self._apply_click_through(False)
            self._locked = False
            self._apply_size_lock(self._size_locked)
            self._apply_overlay_opacity()
            self._apply_topmost()
            self._center_overlay_window(activate=True)
            self._focus_overlay()
            self._notify_overlay_settings()
            self._schedule_save()
            return self.get_overlay_status()

    def open_overlay(self) -> dict:
        # Opening from the dashboard always starts a fresh centered interactive
        # window. If an old hidden/minimized instance survives, destroy it first.
        with self._lock:
            old = self.overlay_window if self._overlay_alive() else None
            if old is not None and not self._visible:
                try:
                    old.destroy()
                except Exception:
                    pass
                if self.overlay_window is old:
                    self.overlay_window = None
        return self._show_overlay(unlock=True)

    def hide_overlay(self) -> dict:
        # Destroy instead of retaining a hidden WebView. Reopening creates a fresh
        # visible centered window and cannot inherit an off-screen native rectangle.
        with self._lock:
            window = self.overlay_window if self._overlay_alive() else None
            self.overlay_window = None
            self._visible = False
            self._locked = False
        if window is not None:
            try:
                window.destroy()
            except Exception:
                try:
                    window.hide()
                except Exception:
                    pass
        return self.get_overlay_status()

    def toggle_overlay(self) -> dict:
        if self._visible and self._overlay_alive():
            return self.hide_overlay()
        return self._show_overlay(unlock=False)

    def minimize_overlay(self) -> dict:
        with self._lock:
            if self._overlay_alive():
                self.overlay_window.minimize()
            return self.get_overlay_status()

    def set_overlay_locked(self, locked: bool) -> dict:
        with self._lock:
            self._ensure_overlay()
            self._locked = bool(locked)
            applied = self._apply_click_through(self._locked)
            if not self._locked:
                self._focus_overlay()
            self._schedule_save()
            result = self.get_overlay_status()
            result["native_click_through"] = applied if self._locked else True
            return result

    def toggle_overlay_locked(self) -> dict:
        return self.set_overlay_locked(not self._locked)

    def toggle_overlay_size(self) -> dict:
        # Legacy compact/expanded API retained for old dashboard bundles. The new
        # overlay is freely resizable from its edges when size lock is disabled.
        with self._lock:
            old = self.overlay_window if self._overlay_alive() else None
            self.overlay_window = None
            self._visible = False
            self._locked = False
            self._expanded = not self._expanded
            width, height = ((560, 720) if self._expanded else (430, 620))
            self.settings.update({
                "expanded": self._expanded,
                "width": width,
                "height": height,
                "layout_version": 7,
            })
        if old is not None:
            try:
                old.destroy()
            except Exception:
                pass
        self._schedule_save()
        return self._show_overlay(unlock=True)

    def reset_overlay_position(self) -> dict:
        with self._lock:
            self.settings.pop("x", None)
            self.settings.pop("y", None)
            window = self._ensure_overlay()
            self._position_anchor = None
            self._center_overlay_window(activate=True)
            self._schedule_save()
            result = self.get_overlay_status()
        self._notify_overlay_settings()
        return result

    def get_overlay_status(self) -> dict:
        rect = self._current_overlay_rect()
        width = int(rect[2]) if rect else int(self.settings.get("width", 430) or 430)
        height = int(rect[3]) if rect else int(self.settings.get("height", 620) or 620)
        return {
            "available": True,
            "visible": bool(self._visible),
            "locked": bool(self._locked),
            "expanded": bool(self._expanded),
            "opacity": float(self._opacity),
            "size_locked": bool(self._size_locked),
            "position_locked": bool(self._position_locked),
            "on_top": bool(self._on_top),
            "resizable": not bool(self._size_locked),
            "width": width,
            "height": height,
            "hotkeys": {
                "toggle": "Ctrl+Shift+O",
                "lock": "Ctrl+Shift+L",
                "reset": "Ctrl+Shift+R",
                "unlock": "Ctrl+Shift+U",
                "ocr_debug": "Ctrl+Shift+D",
            },
            "hotkeys_registered": len(self._hotkeys_registered),
        }

    def start_hotkeys(self) -> None:
        if os.name != "nt" or self._hotkey_thread and self._hotkey_thread.is_alive():
            return
        self._hotkey_thread = threading.Thread(target=self._hotkey_loop, daemon=True, name="sc-hauling-overlay-hotkeys")
        self._hotkey_thread.start()

    def _hotkey_loop(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            class MSG(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", POINT), ("lPrivate", wintypes.DWORD)]

            self._hotkey_thread_id = int(kernel32.GetCurrentThreadId())
            bindings = [(1, ord("O")), (2, ord("L")), (3, ord("R")), (4, ord("U")), (5, ord("D"))]
            for hotkey_id, key in bindings:
                if user32.RegisterHotKey(None, hotkey_id, self.MOD_CONTROL | self.MOD_SHIFT, key):
                    self._hotkeys_registered.append(hotkey_id)
            msg = MSG()
            while not self._shutting_down and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != self.WM_HOTKEY:
                    continue
                hotkey_id = int(msg.wParam)
                if hotkey_id == 1:
                    self.toggle_overlay()
                elif hotkey_id == 2:
                    self.toggle_overlay_locked()
                elif hotkey_id == 3:
                    self.reset_overlay_position()
                elif hotkey_id == 4:
                    # Emergency interaction reset: always show, strip click-through
                    # styles and focus the native window.
                    self._show_overlay(unlock=True)
                elif hotkey_id == 5:
                    self.debug_ocr_notification_sequence()
            for hotkey_id in list(self._hotkeys_registered):
                user32.UnregisterHotKey(None, hotkey_id)
            self._hotkeys_registered.clear()
        except Exception:
            self._hotkeys_registered.clear()

    def start_hotkeys(self) -> None:
        if os.name != "nt" or self._hotkey_thread and self._hotkey_thread.is_alive():
            return
        self._hotkey_thread = threading.Thread(target=self._process_hotkey_loop, daemon=True, name="sc-hauling-overlay-process-hotkeys")
        self._hotkey_thread.start()

    def _process_hotkey_loop(self) -> None:
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            class MSG(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT), ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM), ("time", wintypes.DWORD), ("pt", POINT), ("lPrivate", wintypes.DWORD)]

            self._hotkey_thread_id = int(kernel32.GetCurrentThreadId())
            for hotkey_id, key in ((1, ord("O")), (3, ord("R")), (5, ord("D"))):
                if user32.RegisterHotKey(None, hotkey_id, self.MOD_CONTROL | self.MOD_SHIFT, key):
                    self._hotkeys_registered.append(hotkey_id)
            msg = MSG()
            while not self._shutting_down and user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                if msg.message != self.WM_HOTKEY:
                    continue
                hotkey_id = int(msg.wParam)
                if hotkey_id == 1:
                    self.toggle_overlay()
                elif hotkey_id == 3:
                    self.reset_overlay_position()
                elif hotkey_id == 5:
                    self.debug_ocr_notification_sequence()
            for hotkey_id in list(self._hotkeys_registered):
                user32.UnregisterHotKey(None, hotkey_id)
            self._hotkeys_registered.clear()
        except Exception:
            self._hotkeys_registered.clear()

    def shutdown(self) -> None:
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
            self._save_settings_now()
            self._save_main_settings_now()
            if self._ocr_notifier is not None:
                self._ocr_notifier.shutdown()
            if self._overlay_alive():
                try:
                    self.overlay_window.destroy()
                except Exception:
                    pass
        if os.name == "nt" and self._hotkey_thread_id:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(int(self._hotkey_thread_id), self.WM_QUIT, 0, 0)
            except Exception:
                pass


NATIVE_RESIZE_DIRECTION_CODES = frozenset({"n", "s", "e", "w", "ne", "nw", "se", "sw"})


def calculate_borderless_resize_rect(
    start_rect: Tuple[int, int, int, int],
    dx: int,
    dy: int,
    direction: str,
    min_width: int,
    min_height: int,
) -> Tuple[int, int, int, int]:
    """Return ``left, top, width, height`` for one borderless resize step."""
    start_left, start_top, start_right, start_bottom = (int(v) for v in start_rect)
    direction = str(direction or "").lower()
    if direction not in NATIVE_RESIZE_DIRECTION_CODES:
        raise ValueError(f"Unsupported resize direction: {direction!r}")
    left, top, right, bottom = start_left, start_top, start_right, start_bottom
    min_width = max(1, int(min_width))
    min_height = max(1, int(min_height))
    if "w" in direction:
        left = min(start_left + int(dx), start_right - min_width)
    if "e" in direction:
        right = max(start_right + int(dx), start_left + min_width)
    if "n" in direction:
        top = min(start_top + int(dy), start_bottom - min_height)
    if "s" in direction:
        bottom = max(start_bottom + int(dy), start_top + min_height)
    return left, top, max(min_width, right - left), max(min_height, bottom - top)


def run_borderless_resize_loop(
    hwnd: int,
    direction: str,
    min_width: int,
    min_height: int,
    on_complete=None,
    diagnostic=None,
) -> bool:
    """Resize a frameless Windows HWND while the physical left button is held.

    The HTML layer sends one pointer-down command only. This worker then polls the
    native cursor and updates the HWND with SetWindowPos. It does not install a
    WndProc hook, add WS_THICKFRAME, or receive JavaScript mouse-move callbacks.
    """
    direction = str(direction or "").lower()
    if os.name != "nt" or not hwnd or direction not in NATIVE_RESIZE_DIRECTION_CODES:
        return False

    def log(message: str) -> None:
        if diagnostic:
            try:
                diagnostic(message)
            except Exception:
                pass

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        rect = RECT()
        point = POINT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            log(f"borderless resize failed: GetWindowRect hwnd=0x{hwnd:X}")
            return False
        if not user32.GetCursorPos(ctypes.byref(point)):
            log(f"borderless resize failed: GetCursorPos hwnd=0x{hwnd:X}")
            return False

        dpi = 96
        try:
            get_dpi = getattr(user32, "GetDpiForWindow", None)
            if get_dpi:
                get_dpi.argtypes = [wintypes.HWND]
                get_dpi.restype = wintypes.UINT
                dpi = max(96, int(get_dpi(hwnd) or 96))
        except Exception:
            dpi = 96
        native_min_width = max(1, int(round(int(min_width) * dpi / 96.0)))
        native_min_height = max(1, int(round(int(min_height) * dpi / 96.0)))

        start_left = int(rect.left)
        start_top = int(rect.top)
        start_right = int(rect.right)
        start_bottom = int(rect.bottom)
        start_x = int(point.x)
        start_y = int(point.y)

        # The loop is started from pointerdown, but the local bridge can add a few
        # milliseconds of latency. Briefly wait for the physical button state.
        deadline = time.monotonic() + 0.35
        while not (int(user32.GetAsyncKeyState(0x01)) & 0x8000):  # VK_LBUTTON
            if time.monotonic() >= deadline:
                log(f"borderless resize cancelled before drag: hwnd=0x{hwnd:X}; direction={direction}")
                return False
            time.sleep(0.004)

        log(
            f"borderless resize started: hwnd=0x{hwnd:X}; direction={direction}; "
            f"rect=({start_left},{start_top},{start_right},{start_bottom}); dpi={dpi}"
        )

        flags = 0x0004 | 0x0010  # SWP_NOZORDER | SWP_NOACTIVATE
        last_rect = None
        while int(user32.GetAsyncKeyState(0x01)) & 0x8000:
            if not user32.GetCursorPos(ctypes.byref(point)):
                break
            dx = int(point.x) - start_x
            dy = int(point.y) - start_y
            candidate = calculate_borderless_resize_rect(
                (start_left, start_top, start_right, start_bottom),
                dx,
                dy,
                direction,
                native_min_width,
                native_min_height,
            )
            left, top, width, height = candidate
            if candidate != last_rect:
                user32.SetWindowPos(hwnd, 0, left, top, width, height, flags)
                last_rect = candidate
            time.sleep(0.012)

        final_rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(final_rect)):
            final_width = max(1, int(final_rect.right - final_rect.left))
            final_height = max(1, int(final_rect.bottom - final_rect.top))
            log(
                f"borderless resize completed: hwnd=0x{hwnd:X}; direction={direction}; "
                f"size=({final_width},{final_height})"
            )
            if on_complete:
                try:
                    logical_width = max(1, int(round(final_width * 96.0 / dpi)))
                    logical_height = max(1, int(round(final_height * 96.0 / dpi)))
                    on_complete(logical_width, logical_height)
                except Exception as exc:
                    log(f"borderless resize completion callback failed: {exc!r}")
        return True
    except Exception as exc:
        log(f"borderless resize failed: {exc!r}")
        return False


def run_borderless_move_loop(hwnd: int, diagnostic=None) -> bool:
    """Move a frameless Windows HWND while the physical left button is held."""
    if os.name != "nt" or not hwnd:
        return False

    def log(message: str) -> None:
        if diagnostic:
            try:
                diagnostic(message)
            except Exception:
                pass

    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32

        class POINT(ctypes.Structure):
            _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

        class RECT(ctypes.Structure):
            _fields_ = [
                ("left", wintypes.LONG),
                ("top", wintypes.LONG),
                ("right", wintypes.LONG),
                ("bottom", wintypes.LONG),
            ]

        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
        user32.GetCursorPos.restype = wintypes.BOOL
        user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        user32.GetAsyncKeyState.restype = ctypes.c_short
        user32.SetWindowPos.argtypes = [
            wintypes.HWND,
            wintypes.HWND,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.SetWindowPos.restype = wintypes.BOOL

        rect = RECT()
        point = POINT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            log(f"borderless move failed: GetWindowRect hwnd=0x{hwnd:X}")
            return False
        if not user32.GetCursorPos(ctypes.byref(point)):
            log(f"borderless move failed: GetCursorPos hwnd=0x{hwnd:X}")
            return False

        try:
            user32.ReleaseCapture()
        except Exception:
            pass

        start_left = int(rect.left)
        start_top = int(rect.top)
        start_x = int(point.x)
        start_y = int(point.y)
        width = max(1, int(rect.right - rect.left))
        height = max(1, int(rect.bottom - rect.top))

        deadline = time.monotonic() + 0.35
        while not (int(user32.GetAsyncKeyState(0x01)) & 0x8000):  # VK_LBUTTON
            if time.monotonic() >= deadline:
                log(f"borderless move cancelled before drag: hwnd=0x{hwnd:X}")
                return False
            time.sleep(0.004)

        log(
            f"borderless move started: hwnd=0x{hwnd:X}; "
            f"rect=({int(rect.left)},{int(rect.top)},{int(rect.right)},{int(rect.bottom)})"
        )

        flags = 0x0001 | 0x0004 | 0x0010  # SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE
        last_pos = None
        while int(user32.GetAsyncKeyState(0x01)) & 0x8000:
            if not user32.GetCursorPos(ctypes.byref(point)):
                break
            left = start_left + int(point.x) - start_x
            top = start_top + int(point.y) - start_y
            if (left, top) != last_pos:
                user32.SetWindowPos(hwnd, 0, left, top, 0, 0, flags)
                last_pos = (left, top)
            time.sleep(0.012)

        final_rect = RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(final_rect)):
            log(
                f"borderless move completed: hwnd=0x{hwnd:X}; "
                f"rect=({int(final_rect.left)},{int(final_rect.top)},"
                f"{int(final_rect.left) + width},{int(final_rect.top) + height})"
            )
        return True
    except Exception as exc:
        log(f"borderless move failed: {exc!r}")
        return False


class OverlayChildApi:
    """Native API exposed only inside the isolated overlay process.

    Keeping the overlay in its own process avoids pywebview/WebView2 multi-window
    deadlocks. The child owns exactly one webview window and communicates with the
    tracker only through the existing localhost HTTP server.
    """

    WM_CANCELMODE = 0x001F
    WM_NCLBUTTONDOWN = 0x00A1
    WM_SYSCOMMAND = 0x0112
    SC_SIZE = 0xF000
    SC_MOVE = 0xF010
    HTCAPTION = 2
    GWL_STYLE = -16
    WS_THICKFRAME = 0x00040000
    WS_MAXIMIZEBOX = 0x00010000
    SWP_FRAMECHANGED = 0x0020
    SWP_NOMOVE = 0x0002
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    RESIZE_DIRECTION_CODES = {
        "w": 10,   # HTLEFT
        "e": 11,   # HTRIGHT
        "n": 12,   # HTTOP
        "nw": 13,  # HTTOPLEFT
        "ne": 14,  # HTTOPRIGHT
        "s": 15,   # HTBOTTOM
        "sw": 16,  # HTBOTTOMLEFT
        "se": 17,  # HTBOTTOMRIGHT
    }

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.window = None
        self.settings_path = app_data_directory() / "overlay-window.json"
        self._lock = threading.RLock()
        self._save_timer: Optional[threading.Timer] = None
        self._last_logged_hwnd: Optional[int] = None
        self._move_lock = threading.Lock()
        self._move_active = False
        self._resize_lock = threading.Lock()
        self._resize_active = False
        self.settings = _read_json_object(self.settings_path)
        try:
            self.opacity = max(0.50, min(1.0, float(self.settings.get("opacity", 1.0))))
        except Exception:
            self.opacity = 1.0
        self.size_locked = bool(self.settings.get("size_locked", False))
        self.position_locked = bool(self.settings.get("position_locked", False))
        self.on_top = bool(self.settings.get("on_top", True))
        try:
            self.width = max(380, int(self.settings.get("width", 430) or 430))
            self.height = max(360, int(self.settings.get("height", 620) or 620))
        except Exception:
            self.width, self.height = 430, 620
        self.visible = True

    @staticmethod
    def primary_work_area() -> Tuple[int, int, int, int]:
        left, top, width, height = 0, 0, 1920, 1080
        if os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes

                class RECT(ctypes.Structure):
                    _fields_ = [
                        ("left", wintypes.LONG),
                        ("top", wintypes.LONG),
                        ("right", wintypes.LONG),
                        ("bottom", wintypes.LONG),
                    ]

                rect = RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    candidate_w = int(rect.right - rect.left)
                    candidate_h = int(rect.bottom - rect.top)
                    if candidate_w > 0 and candidate_h > 0:
                        return int(rect.left), int(rect.top), candidate_w, candidate_h
                width = int(ctypes.windll.user32.GetSystemMetrics(0)) or width
                height = int(ctypes.windll.user32.GetSystemMetrics(1)) or height
            except Exception:
                pass
        return left, top, width, height

    def geometry(self) -> dict:
        left, top, work_w, work_h = self.primary_work_area()
        width = min(max(380, self.width), max(380, work_w - 40))
        height = min(max(360, self.height), max(360, work_h - 40))
        return {
            "x": int(left + max(0, (work_w - width) // 2)),
            "y": int(top + max(0, (work_h - height) // 2)),
            "width": int(width),
            "height": int(height),
        }

    def attach_window(self, window) -> None:
        self.window = window
        window.events.shown += self._on_shown
        window.events.resized += self._on_resized
        window.events.closed += self._on_closed

    def _window_hwnd(self) -> Optional[int]:
        if os.name != "nt" or self.window is None:
            return None
        try:
            handle = self.window.native.Handle
            try:
                hwnd = int(handle.ToInt64())
            except Exception:
                hwnd = int(handle.ToInt32())
            # pywebview can expose either the top-level Form or a hosted child
            # control depending on the WebView2 backend. Native window commands
            # must target the root window, never the WebView child.
            try:
                import ctypes
                root = int(ctypes.windll.user32.GetAncestor(hwnd, 2))  # GA_ROOT
                if root:
                    hwnd = root
            except Exception:
                pass
            if hwnd and hwnd != self._last_logged_hwnd:
                self._last_logged_hwnd = hwnd
                overlay_diagnostic_log(f"overlay HWND resolved: 0x{hwnd:X}")
            return hwnd
        except Exception:
            return None

    def _save_now(self) -> None:
        with self._lock:
            payload = {
                "width": int(self.width),
                "height": int(self.height),
                "opacity": float(self.opacity),
                "size_locked": bool(self.size_locked),
                "position_locked": bool(self.position_locked),
                "on_top": bool(self.on_top),
                "locked": False,
                "layout_version": 10,
            }
        _write_json_object(self.settings_path, payload)

    def _schedule_save(self) -> None:
        with self._lock:
            if self._save_timer:
                self._save_timer.cancel()
            self._save_timer = threading.Timer(0.25, self._save_now)
            self._save_timer.daemon = True
            self._save_timer.start()

    def _notify(self) -> None:
        if not self.window:
            return
        try:
            payload = json.dumps(self.get_overlay_status())
            self.window.evaluate_js(f"window.applyNativeSettings && window.applyNativeSettings({payload});")
        except Exception:
            pass

    def _apply_rounded_chrome(self) -> None:
        hwnd = self._window_hwnd()
        if hwnd is None:
            return
        try:
            import ctypes
            dark = ctypes.c_int(1)
            rounded = ctypes.c_int(2)
            # Windows 11 can otherwise paint a one-pixel accent border around a
            # resizable popup. COLOR_NONE keeps the custom overlay edge clean.
            border_none = ctypes.c_uint(0xFFFFFFFE)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(dark), ctypes.sizeof(dark))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(rounded), ctypes.sizeof(rounded))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(border_none), ctypes.sizeof(border_none))
        except Exception:
            pass

    def _apply_size_lock(self) -> bool:
        """Keep the overlay permanently frameless.

        Edge resizing is initiated only by the explicit HTML resize handles.
        No WndProc subclass or persistent WS_THICKFRAME style is installed.
        """
        hwnd = self._window_hwnd()
        if hwnd is None:
            return False
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
            set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
            get_style.argtypes = [wintypes.HWND, ctypes.c_int]
            get_style.restype = ctypes.c_ssize_t
            set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
            set_style.restype = ctypes.c_ssize_t
            style = int(get_style(hwnd, self.GWL_STYLE))
            style &= ~self.WS_THICKFRAME
            style &= ~self.WS_MAXIMIZEBOX
            set_style(hwnd, self.GWL_STYLE, style)
            user32.SetWindowPos(
                hwnd,
                0,
                0,
                0,
                0,
                0,
                self.SWP_NOSIZE | self.SWP_NOMOVE | self.SWP_NOZORDER |
                self.SWP_NOACTIVATE | self.SWP_FRAMECHANGED,
            )
            self._apply_rounded_chrome()
            return True
        except Exception as exc:
            overlay_diagnostic_log(f"size-lock style apply failed: {exc!r}")
            return False

    @staticmethod
    def _read_native_window_size(user32, hwnd: int) -> Optional[Tuple[int, int]]:
        try:
            import ctypes
            from ctypes import wintypes

            class RECT(ctypes.Structure):
                _fields_ = [
                    ("left", wintypes.LONG),
                    ("top", wintypes.LONG),
                    ("right", wintypes.LONG),
                    ("bottom", wintypes.LONG),
                ]

            rect = RECT()
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 0 or height <= 0:
                return None
            return width, height
        except Exception:
            return None

    def _release_native_mouse_capture(self, user32, hwnd: int) -> None:
        """Release WebView mouse capture without cancelling the physical drag."""
        try:
            user32.ReleaseCapture()
        except Exception:
            pass

    @staticmethod
    def _cursor_lparam(user32) -> int:
        """Pack the current screen cursor position for WM_NCLBUTTONDOWN."""
        try:
            import ctypes
            from ctypes import wintypes

            class POINT(ctypes.Structure):
                _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

            point = POINT()
            if user32.GetCursorPos(ctypes.byref(point)):
                return (int(point.x) & 0xFFFF) | ((int(point.y) & 0xFFFF) << 16)
        except Exception:
            pass
        return 0

    def _finish_native_resize(self, width: int, height: int) -> None:
        with self._lock:
            self.width = max(380, int(width))
            self.height = max(360, int(height))
        self._schedule_save()

    def begin_overlay_resize(self, direction: str) -> dict:
        """Start one borderless native resize drag from an HTML edge handle.

        The resize itself runs in the companion process and polls the native cursor.
        This avoids the unreliable temporary-frame/WM_NCLBUTTONDOWN path while
        keeping the overlay visually frameless at all times.
        """
        status = self.get_overlay_status()
        direction_key = str(direction or "").lower()
        hwnd = self._window_hwnd()
        if (
            self.size_locked
            or os.name != "nt"
            or hwnd is None
            or direction_key not in NATIVE_RESIZE_DIRECTION_CODES
        ):
            overlay_diagnostic_log(
                f"overlay resize rejected; direction={direction_key!r}; hwnd={hwnd!r}; "
                f"platform={os.name!r}; size_locked={self.size_locked}"
            )
            status["command_ok"] = False
            return status
        with self._resize_lock:
            if self._resize_active:
                overlay_diagnostic_log("overlay resize rejected because another resize drag is active")
                status["command_ok"] = False
                return status
            self._resize_active = True

        def worker() -> None:
            try:
                run_borderless_resize_loop(
                    hwnd,
                    direction_key,
                    380,
                    360,
                    on_complete=self._finish_native_resize,
                    diagnostic=overlay_diagnostic_log,
                )
            finally:
                with self._resize_lock:
                    self._resize_active = False

        threading.Thread(
            target=worker,
            daemon=True,
            name="sc-overlay-borderless-resize",
        ).start()
        overlay_diagnostic_log(
            f"overlay resize worker launched; hwnd=0x{hwnd:X}; direction={direction_key}"
        )
        status["command_ok"] = True
        status["resize_started"] = True
        return status

    def begin_overlay_move(self) -> dict:
        """Start one borderless native move drag from the custom HTML header."""
        status = self.get_overlay_status()
        if self.position_locked:
            overlay_diagnostic_log("native move blocked because position lock is enabled")
            status["command_ok"] = False
            return status
        hwnd = self._window_hwnd()
        if hwnd is None or os.name != "nt":
            overlay_diagnostic_log(f"overlay move rejected; hwnd={hwnd!r}; platform={os.name!r}")
            status["command_ok"] = False
            return status
        with self._move_lock:
            if self._move_active:
                overlay_diagnostic_log("overlay move rejected because another move drag is active")
                status["command_ok"] = False
                return status
            self._move_active = True

        def worker() -> None:
            try:
                run_borderless_move_loop(hwnd, diagnostic=overlay_diagnostic_log)
            finally:
                with self._move_lock:
                    self._move_active = False

        threading.Thread(
            target=worker,
            daemon=True,
            name="sc-overlay-borderless-move",
        ).start()
        overlay_diagnostic_log(f"overlay move worker launched; hwnd=0x{hwnd:X}")
        status["command_ok"] = True
        status["move_started"] = True
        return status

    def _apply_opacity(self) -> bool:
        if not self.window:
            return False
        opacity = max(0.50, min(1.0, float(self.opacity)))
        applied = False
        try:
            self.window.native.Opacity = opacity
            applied = True
        except Exception:
            pass
        hwnd = self._window_hwnd()
        if hwnd is not None and os.name == "nt":
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                get_style = getattr(user32, "GetWindowLongPtrW", user32.GetWindowLongW)
                set_style = getattr(user32, "SetWindowLongPtrW", user32.SetWindowLongW)
                get_style.argtypes = [wintypes.HWND, ctypes.c_int]
                get_style.restype = ctypes.c_ssize_t
                set_style.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
                set_style.restype = ctypes.c_ssize_t
                ex_style = int(get_style(hwnd, -20)) | 0x00080000  # WS_EX_LAYERED
                set_style(hwnd, -20, ex_style)
                user32.SetLayeredWindowAttributes(hwnd, 0, int(round(opacity * 255)), 0x00000002)
                applied = True
            except Exception as exc:
                overlay_diagnostic_log(f"opacity apply failed: {exc!r}")
        return applied

    def _apply_topmost(self) -> bool:
        if not self.window:
            return False
        applied = False
        try:
            self.window.on_top = bool(self.on_top)
        except Exception:
            pass
        try:
            self.window.native.TopMost = bool(self.on_top)
            applied = True
        except Exception:
            pass
        hwnd = self._window_hwnd()
        if hwnd is not None:
            try:
                import ctypes
                ctypes.windll.user32.SetWindowPos(
                    hwnd,
                    -1 if self.on_top else -2,
                    0, 0, 0, 0,
                    0x0001 | 0x0002 | 0x0010 | 0x0040,
                )
                applied = True
            except Exception:
                pass
        return applied

    def _on_shown(self, *args) -> None:
        self.visible = True
        self._apply_rounded_chrome()
        self._apply_size_lock()
        self._apply_opacity()
        self._apply_topmost()
        self._notify()

    def _on_resized(self, width: int, height: int) -> None:
        if self.size_locked:
            return
        try:
            width, height = int(width), int(height)
        except Exception:
            return
        if width <= 0 or height <= 0:
            return
        with self._lock:
            self.width = max(380, width)
            self.height = max(360, height)
        self._schedule_save()

    def _on_closed(self, *args) -> None:
        self.visible = False
        self._save_now()

    def get_overlay_status(self) -> dict:
        return {
            "available": True,
            "visible": bool(self.visible),
            "locked": False,
            "expanded": bool(self.width >= 500 or self.height >= 680),
            "opacity": float(self.opacity),
            "size_locked": bool(self.size_locked),
            "position_locked": bool(self.position_locked),
            "on_top": bool(self.on_top),
            "resizable": not bool(self.size_locked),
            "width": int(self.width),
            "height": int(self.height),
            "isolated_process": True,
        }

    def set_overlay_opacity(self, opacity: float) -> dict:
        try:
            self.opacity = max(0.50, min(1.0, float(opacity)))
        except Exception:
            self.opacity = 1.0
        self._apply_opacity()
        self._schedule_save()
        status = self.get_overlay_status()
        self._notify()
        return status

    def set_overlay_size_locked(self, locked: bool) -> dict:
        self.size_locked = bool(locked)
        self._apply_size_lock()
        overlay_diagnostic_log(f"size lock changed: {self.size_locked}")
        self._schedule_save()
        status = self.get_overlay_status()
        self._notify()
        return status

    def set_overlay_position_locked(self, locked: bool) -> dict:
        # No move-event listener is installed. The HTML header checks this state
        # before initiating SC_MOVE, and this native method checks it again.
        self.position_locked = bool(locked)
        overlay_diagnostic_log(f"position lock changed: {self.position_locked}")
        self._schedule_save()
        status = self.get_overlay_status()
        self._notify()
        return status

    def set_overlay_on_top(self, on_top: bool) -> dict:
        self.on_top = bool(on_top)
        self._apply_topmost()
        self._schedule_save()
        status = self.get_overlay_status()
        self._notify()
        return status

    def minimize_overlay(self) -> dict:
        applied = False
        try:
            if self.window:
                self.window.minimize()
                applied = True
        except Exception as exc:
            overlay_diagnostic_log(f"pywebview minimize failed: {exc!r}")
        hwnd = self._window_hwnd()
        if not applied and hwnd is not None and os.name == "nt":
            try:
                import ctypes
                ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                applied = True
            except Exception as exc:
                overlay_diagnostic_log(f"native minimize failed: {exc!r}")
        status = self.get_overlay_status()
        status["command_ok"] = bool(applied)
        return status

    def hide_overlay(self) -> dict:
        self.visible = False
        self._save_now()
        window = self.window
        hwnd = self._window_hwnd()
        if window is not None:
            def close_window():
                try:
                    window.destroy()
                    return
                except Exception as exc:
                    overlay_diagnostic_log(f"pywebview destroy failed: {exc!r}")
                if hwnd is not None and os.name == "nt":
                    try:
                        import ctypes
                        ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                        return
                    except Exception as exc:
                        overlay_diagnostic_log(f"native close failed: {exc!r}")
                try:
                    window.hide()
                except Exception as exc:
                    overlay_diagnostic_log(f"pywebview hide failed: {exc!r}")
            timer = threading.Timer(0.15, close_window)
            timer.daemon = True
            timer.start()
        return self.get_overlay_status()

    def fit_overlay_height(self, requested_height: int) -> dict:
        return self.get_overlay_status()

    def toggle_overlay_size(self) -> dict:
        return self.get_overlay_status()

    def set_overlay_locked(self, locked: bool) -> dict:
        return self.get_overlay_status()

    def toggle_overlay_locked(self) -> dict:
        return self.get_overlay_status()


class OverlayCommandServer:
    """Token-protected localhost fallback for the isolated overlay controls.

    pywebview normally exposes ``window.pywebview.api``. Some packaged WebView2
    launches can render the page before the bridge is injected, so the overlay
    also owns this tiny loopback-only command endpoint. No internet connection is
    used and only a random per-process token can invoke the allow-listed methods.
    """

    ALLOWED_COMMANDS = {
        "get_overlay_status",
        "set_overlay_opacity",
        "set_overlay_size_locked",
        "set_overlay_position_locked",
        "set_overlay_on_top",
        "begin_overlay_resize",
        "begin_overlay_move",
        "minimize_overlay",
        "hide_overlay",
    }

    def __init__(self, api: OverlayChildApi):
        import secrets
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        self.api = api
        self.token = secrets.token_urlsafe(32)
        parent = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "SCHaulingOverlayControl/1.0"

            def log_message(self, format, *args):
                return

            def _cors(self):
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, X-SC-Overlay-Token")
                self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
                self.send_header("Cache-Control", "no-store")

            def _json(self, status: int, payload: dict):
                body = json.dumps(payload).encode("utf-8")
                self.send_response(status)
                self._cors()
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_OPTIONS(self):
                self.send_response(204)
                self._cors()
                self.send_header("Content-Length", "0")
                self.end_headers()

            def do_POST(self):
                if self.path.split("?", 1)[0] != "/command":
                    self._json(404, {"ok": False, "error": "Not found"})
                    return
                supplied = self.headers.get("X-SC-Overlay-Token", "")
                if not supplied or supplied != parent.token:
                    self._json(403, {"ok": False, "error": "Invalid overlay control token"})
                    return
                try:
                    length = min(65536, max(0, int(self.headers.get("Content-Length", "0") or 0)))
                    payload = json.loads(self.rfile.read(length).decode("utf-8")) if length else {}
                    name = str(payload.get("name") or "")
                    args = payload.get("args") or []
                    if name not in parent.ALLOWED_COMMANDS:
                        raise ValueError(f"Unsupported overlay command: {name}")
                    if not isinstance(args, list):
                        raise ValueError("Command arguments must be a list")
                    method = getattr(parent.api, name, None)
                    if not callable(method):
                        raise ValueError(f"Overlay command is unavailable: {name}")
                    overlay_diagnostic_log(f"overlay control command: {name}; args={args!r}")
                    result = method(*args)
                    self._json(200, {"ok": True, "result": result})
                except Exception as exc:
                    overlay_diagnostic_log(f"overlay control command failed: {exc!r}")
                    self._json(500, {"ok": False, "error": str(exc)})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
            name="sc-hauling-overlay-control",
        )

    def start(self) -> None:
        self.thread.start()
        overlay_diagnostic_log(f"overlay control server listening on 127.0.0.1:{self.port}")

    def stop(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass


class OverlayProcessController(OverlayController):
    """Dashboard controller that launches the overlay as a separate process."""

    def __init__(self, webview_module, base_url: str):
        super().__init__(webview_module, base_url)
        self._overlay_process: Optional[subprocess.Popen] = None
        self.overlay_window = None

    def _overlay_process_alive(self) -> bool:
        process = self._overlay_process
        return bool(process is not None and process.poll() is None)

    @staticmethod
    def _self_launch_command() -> List[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable]
        return [sys.executable, str(Path(__file__).resolve())]

    def _terminate_overlay_process(self) -> None:
        process = self._overlay_process
        self._overlay_process = None
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except Exception:
            try:
                process.kill()
            except Exception:
                pass

    def _spawn_overlay_process(self) -> dict:
        self._terminate_overlay_process()
        command = self._self_launch_command() + [
            "--overlay-child",
            "--base-url",
            self.base_url,
            "--parent-pid",
            str(os.getpid()),
        ]
        creationflags = 0
        if os.name == "nt":
            creationflags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        overlay_diagnostic_log(f"launching overlay companion: {command!r}")
        try:
            process = subprocess.Popen(
                command,
                cwd=str(Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                creationflags=creationflags,
            )
        except Exception as exc:
            overlay_diagnostic_log(f"overlay companion launch failed: {exc!r}")
            return {**self.get_overlay_status(), "error": str(exc)}
        self._overlay_process = process
        # Popen returns immediately; a short poll catches only immediate startup
        # failures without blocking the dashboard while WebView2 initializes.
        time.sleep(0.04)
        if process.poll() is not None:
            code = process.returncode
            overlay_diagnostic_log(f"overlay companion exited during startup with code={code}")
            return {**self.get_overlay_status(), "error": f"The isolated overlay process exited during startup (code {code})."}
        return self.get_overlay_status()

    def open_overlay(self) -> dict:
        with self._lock:
            return self._spawn_overlay_process()

    def hide_overlay(self) -> dict:
        with self._lock:
            self._terminate_overlay_process()
            return self.get_overlay_status()

    def toggle_overlay(self) -> dict:
        with self._lock:
            if self._overlay_process_alive():
                self._terminate_overlay_process()
                return self.get_overlay_status()
            return self._spawn_overlay_process()

    def minimize_overlay(self) -> dict:
        # Minimize is handled directly by the child window's JS bridge.
        return self.get_overlay_status()

    def reset_overlay_position(self) -> dict:
        with self._lock:
            return self._spawn_overlay_process()

    def set_overlay_locked(self, locked: bool) -> dict:
        return self.get_overlay_status()

    def toggle_overlay_locked(self) -> dict:
        return self.get_overlay_status()

    def set_overlay_opacity(self, opacity: float) -> dict:
        data = _read_json_object(self.settings_path)
        try:
            data["opacity"] = max(0.50, min(1.0, float(opacity)))
        except Exception:
            data["opacity"] = 1.0
        _write_json_object(self.settings_path, data)
        return self.get_overlay_status()

    def set_overlay_size_locked(self, locked: bool) -> dict:
        data = _read_json_object(self.settings_path)
        data["size_locked"] = bool(locked)
        _write_json_object(self.settings_path, data)
        return self.get_overlay_status()

    def set_overlay_position_locked(self, locked: bool) -> dict:
        data = _read_json_object(self.settings_path)
        data["position_locked"] = bool(locked)
        _write_json_object(self.settings_path, data)
        return self.get_overlay_status()

    def set_overlay_on_top(self, on_top: bool) -> dict:
        data = _read_json_object(self.settings_path)
        data["on_top"] = bool(on_top)
        _write_json_object(self.settings_path, data)
        return self.get_overlay_status()

    def get_overlay_status(self) -> dict:
        data = _read_json_object(self.settings_path)
        return {
            "available": True,
            "visible": self._overlay_process_alive(),
            "locked": False,
            "opacity": float(data.get("opacity", 1.0) or 1.0),
            "size_locked": bool(data.get("size_locked", False)),
            "position_locked": bool(data.get("position_locked", False)),
            "on_top": bool(data.get("on_top", True)),
            "width": int(data.get("width", 430) or 430),
            "height": int(data.get("height", 620) or 620),
            "isolated_process": True,
            "hotkeys": {
                "toggle": "Ctrl+Shift+O",
                "reset": "Ctrl+Shift+R",
                "ocr_debug": "Ctrl+Shift+D",
            },
            "hotkeys_registered": len(self._hotkeys_registered),
        }

    def shutdown(self) -> None:
        with self._lock:
            if self._shutting_down:
                return
            self._shutting_down = True
        self._terminate_overlay_process()
        if self._ocr_notifier is not None:
            self._ocr_notifier.shutdown()
        self._save_main_settings_now()
        if os.name == "nt" and self._hotkey_thread_id:
            try:
                import ctypes
                ctypes.windll.user32.PostThreadMessageW(int(self._hotkey_thread_id), self.WM_QUIT, 0, 0)
            except Exception:
                pass


def run_overlay_child(base_url: str, parent_pid: Optional[int] = None) -> int:
    """Run the compact Logistics Overlay in a dedicated pywebview process."""
    overlay_diagnostic_log(f"overlay child starting; base_url={base_url!r}; parent_pid={parent_pid!r}")
    try:
        import webview  # type: ignore
    except Exception as exc:
        overlay_diagnostic_log(f"pywebview import failed: {exc!r}")
        show_native_message("SC Hauling Overlay startup error", str(exc), error=True)
        return 1

    api = OverlayChildApi(base_url)
    control_server = OverlayCommandServer(api)
    control_server.start()
    geometry = api.geometry()
    from urllib.parse import urlencode
    overlay_query = urlencode({
        "overlay_control_port": control_server.port,
        "overlay_control_token": control_server.token,
    })
    kwargs = dict(
        title="SC Hauling Overlay",
        url=base_url.rstrip("/") + "/overlay?" + overlay_query,
        js_api=api,
        width=geometry["width"],
        height=geometry["height"],
        x=geometry["x"],
        y=geometry["y"],
        min_size=(380, 360),
        resizable=False,
        hidden=False,
        frameless=True,
        easy_drag=False,
        shadow=True,
        focus=True,
        on_top=bool(api.on_top),
        transparent=False,
        background_color="#0c0c13",
        text_select=False,
    )
    try:
        window = webview.create_window(**kwargs)
    except TypeError:
        kwargs.pop("transparent", None)
        kwargs.pop("focus", None)
        window = webview.create_window(**kwargs)
    except Exception as exc:
        control_server.stop()
        overlay_diagnostic_log(f"create_window failed: {exc!r}")
        show_native_message("SC Hauling Overlay startup error", str(exc), error=True)
        return 1
    api.attach_window(window)
    overlay_diagnostic_log(
        f"overlay window created at {geometry['x']},{geometry['y']} "
        f"size={geometry['width']}x{geometry['height']}"
    )

    if parent_pid:
        def parent_watch() -> None:
            overlay_diagnostic_log(f"parent watcher started for pid={int(parent_pid)}")
            while api.visible:
                time.sleep(1.0)
                if process_is_running(parent_pid):
                    continue
                overlay_diagnostic_log(f"parent pid={int(parent_pid)} is no longer running; closing overlay")
                try:
                    window.destroy()
                except Exception as exc:
                    overlay_diagnostic_log(f"overlay destroy after parent exit failed: {exc!r}")
                return
        watcher = threading.Thread(target=parent_watch, daemon=True, name="sc-hauling-overlay-parent-watch")
        watcher.start()

    storage_path = app_data_directory() / "overlay-webview"
    storage_path.mkdir(parents=True, exist_ok=True)
    exit_code = 0
    try:
        overlay_diagnostic_log("starting pywebview event loop")
        try:
            webview.start(debug=False, private_mode=False, storage_path=str(storage_path))
        except TypeError:
            webview.start(debug=False)
    except Exception as exc:
        exit_code = 1
        overlay_diagnostic_log(f"pywebview event loop failed: {exc!r}")
        show_native_message("SC Hauling Overlay error", str(exc), error=True)
    finally:
        control_server.stop()
    overlay_diagnostic_log("overlay child exited normally" if exit_code == 0 else "overlay child exited with error")
    return exit_code


def run_web_dashboard(default_log: Optional[str] = None, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True, port_callback=None, desktop_bridge=None) -> None:
    """Run the production-style local web dashboard.

    The older Tkinter UI cannot closely match the selected sci-fi concept render.
    This local browser UI uses built-in Python HTTPServer only, so it stays offline
    and dependency-free while allowing proper CSS layout, cards, and panels.
    """
    import json
    import mimetypes
    import socket
    import tempfile
    import urllib.parse
    import webbrowser
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    # Mutable holder populated by run_app_window after the native controller is
    # created. Keeping this separate from window.pywebview.api makes the desktop
    # overlay control reliable even when WebView2 delays or omits JS API binding.
    desktop_bridge = desktop_bridge if isinstance(desktop_bridge, dict) else {}

    def desktop_controller():
        controller = desktop_bridge.get("controller")
        return controller if controller is not None else None

    class WebState:
        def __init__(self):
            guessed = guess_sc_log_paths()
            saved_log = str(load_app_settings().get("log_path") or "").strip()
            self.guessed_log_paths = [str(p) for p in guessed]
            self.log_path = default_log or saved_log or (str(guessed[0]) if guessed else "")
            self.missions: List[CargoMission] = []
            self.base_missions: List[CargoMission] = []
            self.events: List[CompletionEvent] = []
            self.watch_stop = threading.Event()
            self.watch_thread: Optional[threading.Thread] = None
            self.watch_buffer = ""
            self.last_size = 0
            self.status = "Ready"
            self.last_scan = "—"
            self.session_started = time.time()
            self.timer_state = "stopped"  # stopped, running, paused, armed_first
            self.timer_start_epoch: Optional[float] = None
            self.timer_elapsed_before = 0.0
            # After Reset Session, Watch must begin at the current EOF instead of
            # rescanning the old log tail and restoring the cleared contracts.
            self.watch_from_current = False
            self.session_boundary_offset = 0
            self.session_boundary_timestamp = time.time()
            self.lock = threading.RLock()
            self.checklist_path = app_data_directory() / "loading-checklist.json"
            raw_checklist = _read_json_object(self.checklist_path)
            self.checklist = {str(k): True for k, v in raw_checklist.items() if v}
            self.contract_overrides_path = app_data_directory() / "contract-overrides.json"
            self.contract_overrides = normalize_contract_overrides(_read_json_object(self.contract_overrides_path))
            self.deleted_contracts_path = app_data_directory() / "deleted-contracts.json"
            raw_deleted = _read_json_object(self.deleted_contracts_path)
            self.deleted_contract_ids = {
                str(item or "").strip().lower()
                for item in (raw_deleted.get("mission_ids") or [])
                if str(item or "").strip()
            }
            self.ocr_settings_path = app_data_directory() / "ocr-settings.json"
            raw_ocr_settings = _read_json_object(self.ocr_settings_path)
            self.auto_ocr_enabled = bool(raw_ocr_settings.get("auto_enabled", True))
            ocr_pipeline_version = int(raw_ocr_settings.get("pipeline_version", 1) or 1)
            if ocr_pipeline_version < 2:
                # Migrate v3.5.44's optimistic timing so existing settings do not
                # keep the old two-second / three-attempt capture window.
                self.ocr_initial_delay = 2.8
                self.ocr_max_attempts = 4
                self.ocr_retry_delay = 1.4
            else:
                self.ocr_initial_delay = max(1.5, min(6.0, float(raw_ocr_settings.get("initial_delay", 2.8) or 2.8)))
                self.ocr_max_attempts = max(2, min(6, int(raw_ocr_settings.get("max_attempts", 4) or 4)))
                self.ocr_retry_delay = max(0.8, min(4.0, float(raw_ocr_settings.get("retry_delay", 1.4) or 1.4)))
            self.ocr_queue: "queue.Queue[tuple]" = queue.Queue()
            self.ocr_pending_ids = set()
            self.ocr_seen_accept_ids = set()
            self.ocr_waiting_accept_ids = set()
            self.ocr_attempted_ids = set()
            self.ocr_worker_thread: Optional[threading.Thread] = None
            self.ocr_generation = 0
            self.ocr_last_status = "Auto OCR ready" if self.auto_ocr_enabled else "Auto OCR disabled"

        def _save_checklist(self) -> None:
            _write_json_object(self.checklist_path, dict(self.checklist))

        def checklist_snapshot(self) -> dict:
            with self.lock:
                return dict(self.checklist)

        def set_checklist_item(self, item_id: str, checked: bool) -> dict:
            item_id = str(item_id or "").strip()
            if not item_id:
                raise ValueError("Checklist item id is required.")
            with self.lock:
                if checked:
                    self.checklist[item_id] = True
                else:
                    self.checklist.pop(item_id, None)
                self._save_checklist()
                return dict(self.checklist)

        def clear_checklist(self) -> dict:
            with self.lock:
                self.checklist = {}
                self._save_checklist()
                return {}

        def replace_checklist(self, payload: dict) -> dict:
            with self.lock:
                self.checklist = {str(k): True for k, v in (payload or {}).items() if v}
                self._save_checklist()
                return dict(self.checklist)

        def _save_contract_overrides(self) -> None:
            _write_json_object(self.contract_overrides_path, dict(self.contract_overrides))

        def _save_deleted_contracts(self) -> None:
            _write_json_object(self.deleted_contracts_path, {"mission_ids": sorted(self.deleted_contract_ids)})

        def _visible_base_missions(self) -> List[CargoMission]:
            if not self.deleted_contract_ids:
                return list(self.base_missions)
            return [mission for mission in self.base_missions if (mission.mission_id or "").lower() not in self.deleted_contract_ids]

        def _validated_contract_overrides(self, base_missions: Sequence[CargoMission]) -> dict:
            groups_by_id = {
                (group[0].mission_id or "").lower(): group
                for group in contract_groups(base_missions)
                if group and group[0].mission_id
            }
            valid = {}
            changed = False
            for mission_id, override in self.contract_overrides.items():
                if str((override or {}).get("source") or "manual").lower() == "ocr" and (override or {}).get("objectives"):
                    group = groups_by_id.get(str(mission_id or "").lower())
                    if group:
                        validation = validate_ocr_contract_details(override, group)
                        if not validation.get("ok"):
                            changed = True
                            continue
                valid[mission_id] = override
            if changed:
                self.contract_overrides = valid
                self._save_contract_overrides()
            return valid

        def _refresh_contract_overrides(self) -> None:
            base_missions = self._visible_base_missions()
            combined = merged_contract_overrides(self._validated_contract_overrides(base_missions))
            self.missions = apply_contract_overrides(base_missions, combined)
            apply_completion_events(self.missions, self.events)
            self.missions = merge_missions(self.missions)

        def save_contract_override(self, mission_id: str, payout, objectives, contracted_by: str = "", source: str = "manual") -> dict:
            mission_id = str(mission_id or "").strip().lower()
            normalized = normalize_contract_overrides({mission_id: {"payout": payout, "objectives": objectives, "contracted_by": contracted_by, "source": source}})
            if not mission_id or mission_id not in normalized:
                raise ValueError("A MissionId and contract details are required.")
            with self.lock:
                self.contract_overrides[mission_id] = normalized[mission_id]
                self._save_contract_overrides()
                self._refresh_contract_overrides()
                self.status = "Contract details saved."
                return normalized[mission_id]

        def _save_ocr_settings(self) -> None:
            _write_json_object(self.ocr_settings_path, {
                "auto_enabled": bool(self.auto_ocr_enabled),
                "initial_delay": float(self.ocr_initial_delay),
                "max_attempts": int(self.ocr_max_attempts),
                "retry_delay": float(self.ocr_retry_delay),
                "pipeline_version": 2,
            })

        def toggle_auto_ocr(self) -> None:
            with self.lock:
                self.auto_ocr_enabled = not self.auto_ocr_enabled
                self._save_ocr_settings()
                self.ocr_last_status = "Auto OCR enabled" if self.auto_ocr_enabled else "Auto OCR disabled"
                self.status = self.ocr_last_status + "."

        def _group_for_mission_id(self, mission_id: str) -> List[CargoMission]:
            key = str(mission_id or "").strip().lower()
            for group in contract_groups(self.missions):
                if group and (group[0].mission_id or "").lower() == key:
                    return list(group)
            return []

        def _recent_auto_ocr_candidate_ids(self, max_age_seconds: float = 300.0) -> List[str]:
            now = time.time()
            candidates: List[str] = []
            for group in contract_groups(self.missions):
                if not group:
                    continue
                first = group[0]
                mission_id = (first.mission_id or "").strip().lower()
                if not mission_id or mission_id in self.ocr_pending_ids or mission_id in self.ocr_attempted_ids:
                    continue
                if first.status.upper() != "ACCEPTED":
                    continue
                existing = self.contract_overrides.get(mission_id) or {}
                if existing and str(existing.get("source") or "manual").lower() == "manual":
                    continue
                accepted_epoch = first.accepted_epoch()
                if accepted_epoch is None or now - accepted_epoch > max_age_seconds:
                    continue
                needs_cargo = any(not m.is_load_plannable() for m in group)
                needs_payout = all(m.payout_auec is None for m in group)
                if needs_cargo or needs_payout:
                    candidates.append(mission_id)
            return candidates

        def _queue_recent_auto_ocr_candidates(self) -> None:
            for mission_id in self._recent_auto_ocr_candidate_ids():
                self._queue_auto_ocr(mission_id)

        def _queue_auto_ocr(self, mission_id: str) -> bool:
            mission_id = str(mission_id or "").strip().lower()
            if not mission_id:
                return False
            if not self.auto_ocr_enabled:
                self.ocr_last_status = "Contract detected; Auto OCR is disabled"
                self.status = self.ocr_last_status + "."
                return False
            if mission_id in self.ocr_pending_ids:
                return False
            if not self._group_for_mission_id(mission_id):
                self.ocr_waiting_accept_ids.add(mission_id)
                self.ocr_last_status = "Contract detected; waiting for parser details"
                self.status = self.ocr_last_status + "."
                return False
            controller = desktop_controller()
            if controller is None:
                self.ocr_last_status = "Contract detected; Auto OCR desktop controller is unavailable"
                self.status = self.ocr_last_status + "."
                return False
            self.ocr_waiting_accept_ids.discard(mission_id)
            self.ocr_pending_ids.add(mission_id)
            self.ocr_attempted_ids.add(mission_id)
            self.ocr_queue.put((self.ocr_generation, mission_id))
            self.ocr_last_status = f"Contract detected; OCR queued for {mission_id[:8]}"
            self.status = self.ocr_last_status + "."
            if not self.ocr_worker_thread or not self.ocr_worker_thread.is_alive():
                self.ocr_worker_thread = threading.Thread(target=self._ocr_worker_loop, daemon=True, name="scht-auto-ocr")
                self.ocr_worker_thread.start()
            return True

        def _ocr_worker_loop(self) -> None:
            while True:
                try:
                    generation, mission_id = self.ocr_queue.get(timeout=0.5)
                except queue.Empty:
                    with self.lock:
                        if self.ocr_queue.empty():
                            self.ocr_worker_thread = None
                            return
                    continue
                try:
                    if generation != self.ocr_generation:
                        continue
                    self._run_auto_ocr_job(mission_id, generation)
                except Exception as exc:
                    with self.lock:
                        self.ocr_last_status = "Automatic OCR error"
                        self.status = f"Automatic OCR error: {exc}"
                    controller = desktop_controller()
                    if controller is not None:
                        controller.show_ocr_notification(
                            "Contract OCR error",
                            "SCHT could not finish automatic OCR. Use Edit → Read screenshot or enter the values manually.",
                            "error", 8,
                        )
                finally:
                    with self.lock:
                        self.ocr_pending_ids.discard(mission_id)
                    self.ocr_queue.task_done()

        def _run_auto_ocr_job(self, mission_id: str, generation: int) -> None:
            controller = desktop_controller()
            if controller is None:
                return
            with self.lock:
                group = self._group_for_mission_id(mission_id)
                if not group or generation != self.ocr_generation:
                    return
                existing = self.contract_overrides.get(mission_id) or {}
                if str(existing.get("source") or "manual").lower() == "manual" and existing:
                    self.ocr_last_status = "Skipped OCR because this contract already has manual details"
                    return
                title = group[0].title or "New hauling contract"
                expectation = ocr_objective_expectation(group)
                log_path = self.log_path
                hints = [{
                    "pickup": m.pickup, "dropoff": m.dropoff, "commodity": m.commodity, "scu": m.scu,
                    "objective_id": m.objective_id, "provenance": m.data_provenance,
                } for m in group]
            controller.show_ocr_notification(
                "Hauling contract detected",
                "Keep the newly accepted contract page open while SCHT reads it.",
                "info", 0,
            )
            self.ocr_last_status = f"Waiting to read {title}"
            time.sleep(self.ocr_initial_delay)
            last_failure = "The accepted contract page was not ready."
            last_ocr_debug = {}
            job_started_at = time.time()
            tried_recent_screenshots: set = set()
            for attempt in range(1, self.ocr_max_attempts + 1):
                if generation != self.ocr_generation or not self.auto_ocr_enabled:
                    controller.hide_ocr_notification(); return
                controller.show_ocr_notification(
                    "Reading contract",
                    f"OCR attempt {attempt} of {self.ocr_max_attempts}. Keep the contract page open.",
                    "info", 0,
                )
                self.ocr_last_status = f"OCR attempt {attempt} of {self.ocr_max_attempts}"
                time.sleep(0.16)
                capture = controller.capture_star_citizen_window()
                if not capture.get("ok"):
                    last_failure = str(capture.get("error") or "Star Citizen window capture failed.")
                    if attempt < self.ocr_max_attempts:
                        time.sleep(self.ocr_retry_delay)
                    continue
                image_path = Path(str(capture.get("path") or ""))
                try:
                    ocr_result = read_contract_image_ocr(
                        image_path, hints, int(expectation.get("objective_count") or 0) or None
                    )
                    text = str(ocr_result.get("full_text") or "")
                    parsed = ocr_result.get("parsed") or {}
                    last_ocr_debug = {
                        "mission_id": mission_id,
                        "title": title,
                        "attempt": attempt,
                        "window": capture.get("window") or "",
                        "expectation": expectation,
                        "hints": hints,
                        "parsed": parsed,
                        "full_text_excerpt": text[:5000],
                        "objectives_text_excerpt": str(ocr_result.get("objectives_text") or "")[:3000],
                        "reward_text_excerpt": str(ocr_result.get("reward_text") or "")[:1000],
                    }
                except Exception as exc:
                    text = ""
                    parsed = {}
                    last_failure = f"Windows OCR failed: {exc}"
                finally:
                    keep_debug_capture = bool(last_ocr_debug)
                    if keep_debug_capture:
                        debug_capture = preserve_ocr_debug_capture(image_path, mission_id, attempt)
                        if debug_capture:
                            last_ocr_debug["live_capture_path"] = debug_capture
                    try: image_path.unlink()
                    except Exception: pass
                # Parsed objectives are stronger readiness evidence than a section
                # heading which Windows OCR may miss on the translucent mobiGlas UI.
                if not ocr_contract_page_ready(text) and not (parsed.get("objectives") or []):
                    last_failure = "No complete cargo objectives were recognized from the visible contract page."
                    if attempt < self.ocr_max_attempts:
                        time.sleep(self.ocr_retry_delay)
                    continue
                with self.lock:
                    group = self._group_for_mission_id(mission_id)
                    if not group or generation != self.ocr_generation:
                        controller.hide_ocr_notification(); return
                    expectation = ocr_objective_expectation(group)
                    log_path = self.log_path
                    hints = [{
                        "pickup": m.pickup, "dropoff": m.dropoff, "commodity": m.commodity, "scu": m.scu,
                        "objective_id": m.objective_id, "provenance": m.data_provenance,
                    } for m in group]
                validation = validate_ocr_contract_details(parsed, group)
                if not validation.get("ok"):
                    recent_path = recent_star_citizen_screenshot(log_path, job_started_at, tried_recent_screenshots)
                    if recent_path is not None:
                        tried_recent_screenshots.add(str(recent_path))
                        try:
                            fallback_result = read_contract_image_ocr(
                                recent_path, hints, int(expectation.get("objective_count") or 0) or None
                            )
                            fallback_text = str(fallback_result.get("full_text") or "")
                            fallback_parsed = fallback_result.get("parsed") or {}
                            fallback_validation = validate_ocr_contract_details(fallback_parsed, group)
                            fallback_debug = {
                                "mission_id": mission_id,
                                "title": title,
                                "attempt": attempt,
                                "source": "recent_star_citizen_screenshot",
                                "screenshot": str(recent_path),
                                "window": capture.get("window") or "",
                                "expectation": expectation,
                                "hints": hints,
                                "parsed": fallback_parsed,
                                "validation": fallback_validation,
                                "full_text_excerpt": fallback_text[:5000],
                                "objectives_text_excerpt": str(fallback_result.get("objectives_text") or "")[:3000],
                                "reward_text_excerpt": str(fallback_result.get("reward_text") or "")[:1000],
                            }
                            if fallback_validation.get("ok"):
                                parsed = fallback_parsed
                                validation = fallback_validation
                                last_ocr_debug = fallback_debug
                            else:
                                last_ocr_debug = fallback_debug
                        except Exception as exc:
                            last_failure = f"Recent Star Citizen screenshot OCR failed: {exc}"
                if not validation.get("ok"):
                    last_failure = str(validation.get("reason") or "OCR result did not match the pending contract.")
                    if last_ocr_debug:
                        last_ocr_debug["validation"] = validation
                        last_ocr_debug["failure"] = last_failure
                    if attempt < self.ocr_max_attempts:
                        time.sleep(self.ocr_retry_delay)
                    continue
                parsed_rows = validation.get("objectives") or []
                exact_signatures = {
                    _objective_signature({"dropoff": m.dropoff, "commodity": m.commodity, "scu": m.scu})
                    for m in group if m.scu_provenance == "exact_log" and m.has_known_scu()
                }
                objectives = []
                all_exact = bool(group) and all(m.scu_provenance == "exact_log" and m.has_known_scu() for m in group)
                unique_pickups = {ocr_compact(m.pickup) for m in group if m.pickup and not m.pickup.lower().startswith("unknown")}
                unique_dropoffs = {ocr_compact(m.dropoff) for m in group if m.dropoff and not m.dropoff.lower().startswith("unknown")}
                parsed_aggregate = any(str(item.get("quantity_scope") or "").lower() == "aggregate" for item in parsed_rows)
                aggregate_shape = parsed_aggregate or (len(parsed_rows) == 1 and len(unique_pickups) > 1 and len(unique_dropoffs) == 1)
                if parsed_aggregate:
                    for item in parsed_rows:
                        row = dict(item)
                        row["provenance"] = "exact_log" if _objective_signature(item) in exact_signatures else "ocr"
                        row["quantity_scope"] = "aggregate"
                        objectives.append(row)
                elif aggregate_shape:
                    parsed_item = parsed_rows[0]
                    parsed_signature = _objective_signature(parsed_item)
                    for index, mission in enumerate(group):
                        existing_known = mission.has_known_scu() and mission.scu_provenance == "exact_log"
                        objectives.append({
                            "pickup": mission.pickup,
                            "dropoff": mission.dropoff,
                            "commodity": parsed_item.get("commodity") or mission.commodity,
                            "scu": mission.scu if existing_known else (parsed_item.get("scu") if index == 0 else ""),
                            "provenance": "exact_log" if existing_known or parsed_signature in exact_signatures else ("ocr" if index == 0 else mission.data_provenance),
                            "quantity_scope": "aggregate",
                        })
                elif not all_exact:
                    for item in parsed_rows:
                        row = dict(item)
                        row["provenance"] = "exact_log" if _objective_signature(item) in exact_signatures else "ocr"
                        row["quantity_scope"] = "per_route"
                        objectives.append(row)
                with self.lock:
                    current = self.contract_overrides.get(mission_id) or {}
                    if current and str(current.get("source") or "manual").lower() == "manual":
                        controller.show_ocr_notification("Contract OCR skipped", "Manual details were saved before OCR completed.", "info", 8)
                        return
                    if not objectives and parsed.get("payout") is None:
                        self.ocr_last_status = "Contract cargo verified; payout was not read"
                        self.status = self.ocr_last_status + "."
                        controller.show_ocr_notification(
                            "Contract partially verified",
                            "Cargo objectives match Game.log, but the payout could not be read. Review it in the edit form.",
                            "warning", 8,
                        )
                        return
                    self.save_contract_override(
                        mission_id, parsed.get("payout"), objectives, parsed.get("contracted_by") or "", source="ocr"
                    )
                    missing = []
                    if parsed.get("payout") is None:
                        missing.append("payout")
                    if not parsed_rows:
                        missing.append("cargo objectives")
                    self.ocr_last_status = "Contract OCR imported" if not missing else "Contract OCR partially imported"
                    self.status = self.ocr_last_status + "."
                total_scu = sum(float(item.get("scu") or 0) for item in parsed_rows)
                total_label = str(int(total_scu)) if float(total_scu).is_integer() else str(total_scu)
                if missing:
                    controller.show_ocr_notification(
                        "Contract partially imported",
                        f"Read {len(parsed_rows)} objective(s), {total_label} SCU. Missing {', '.join(missing)}; review the edit form.",
                        "warning", 8,
                    )
                else:
                    controller.show_ocr_notification(
                        "Contract imported",
                        f"{len(parsed_rows)} objective(s) · {total_label} SCU · {format_auec(parsed.get('payout'))} aUEC",
                        "success", 8,
                    )
                return
            with self.lock:
                self.ocr_last_status = "Automatic OCR failed"
                self.status = "Automatic OCR failed; use Edit → Read screenshot or enter the missing fields manually."
            if last_ocr_debug:
                last_ocr_debug["failure"] = last_failure
                last_ocr_debug["recorded_at"] = dt.datetime.now().isoformat(timespec="seconds")
                _write_json_object(app_data_directory() / "ocr-last-failure.json", last_ocr_debug)
            reason = re.sub(r"\s+", " ", str(last_failure or "Unknown OCR failure.")).strip()
            if len(reason) > 155:
                reason = reason[:152] + "..."
            controller.show_ocr_notification(
                "Contract OCR failed",
                f"{reason} Open the correct contract page and use Edit → Read screenshot. If retry still fails, enter the missing values manually.",
                "error", 8,
            )

        def clear_contract_override(self, mission_id: str) -> None:
            mission_id = str(mission_id or "").strip().lower()
            if not mission_id:
                raise ValueError("MissionId is required.")
            with self.lock:
                self.contract_overrides.pop(mission_id, None)
                self._save_contract_overrides()
                self._refresh_contract_overrides()
                self.status = "Manual contract details cleared."

        def delete_contract(self, mission_id: str) -> None:
            mission_id = str(mission_id or "").strip().lower()
            if not mission_id:
                raise ValueError("MissionId is required.")
            with self.lock:
                self.deleted_contract_ids.add(mission_id)
                self.contract_overrides.pop(mission_id, None)
                self.events = [event for event in self.events if (event.mission_id or "").lower() != mission_id]
                self._save_deleted_contracts()
                self._save_contract_overrides()
                self._refresh_contract_overrides()
                self.status = "Contract deleted."

        def path(self) -> Optional[Path]:
            txt = (self.log_path or "").strip().strip('"')
            if not txt:
                return None
            return Path(txt)

        def set_log_path(self, value: str):
            with self.lock:
                new_path = (value or "").strip().strip('"')
                changed = new_path != self.log_path
                if changed and self.is_watching():
                    self.watch_stop.set()
                self.log_path = new_path
                if changed:
                    self.watch_from_current = False
                    update_app_settings(log_path=self.log_path)
                self.status = f"Game.log set to {self.log_path}" if self.log_path else "Game.log path cleared"

        def earliest_accepted_epoch(self) -> Optional[float]:
            starts = [m.accepted_epoch() for m in self.missions]
            starts = [v for v in starts if v is not None]
            return min(starts) if starts else None

        def maybe_start_armed_first_timer(self):
            if self.timer_state != "armed_first":
                return
            first = self.earliest_accepted_epoch()
            if first is not None:
                self.timer_start_epoch = first
                self.timer_elapsed_before = 0.0
                self.timer_state = "running"
                self.status = "Session timer started from first accepted mission."

        def session_timer_elapsed(self) -> float:
            self.maybe_start_armed_first_timer()
            if self.timer_state == "running" and self.timer_start_epoch is not None:
                return max(0.0, self.timer_elapsed_before + (time.time() - self.timer_start_epoch))
            return max(0.0, self.timer_elapsed_before)

        def start_timer_first(self):
            with self.lock:
                first = self.earliest_accepted_epoch()
                self.timer_elapsed_before = 0.0
                if first is None:
                    self.timer_state = "armed_first"
                    self.timer_start_epoch = None
                    self.status = "Timer armed: it will start when the first mission is accepted."
                else:
                    self.timer_state = "running"
                    self.timer_start_epoch = first
                    self.status = "Timer started from first accepted mission."

        def start_timer_now(self):
            """Restart only the session timer without changing tracker contents.

            Timer controls must be independent from Reset Session. Existing
            contracts, completion events, checklist state, manual corrections,
            deleted-contract filters, watch buffers, and Game.log boundaries all
            remain untouched when the user presses Start from now.
            """
            with self.lock:
                now = time.time()
                self.session_started = now
                self.timer_elapsed_before = 0.0
                self.timer_start_epoch = now
                self.timer_state = "running"
                self.status = "Session timer started from now. Existing contracts were kept."

        def toggle_timer(self):
            with self.lock:
                if self.timer_state == "running" and self.timer_start_epoch is not None:
                    self.timer_elapsed_before += max(0.0, time.time() - self.timer_start_epoch)
                    self.timer_start_epoch = None
                    self.timer_state = "paused"
                    self.status = "Session timer paused."
                elif self.timer_state == "paused":
                    self.timer_start_epoch = time.time()
                    self.timer_state = "running"
                    self.status = "Session timer resumed."
                elif self.timer_state == "armed_first":
                    self.status = "Timer is waiting for the first accepted mission."
                else:
                    self.timer_elapsed_before = 0.0
                    self.timer_start_epoch = time.time()
                    self.timer_state = "running"
                    self.status = "Session timer started from now."

        def add_update(self, new_missions: Sequence[CargoMission], new_events: Sequence[CompletionEvent]) -> int:
            before = [(m.stable_key(), m.score(), m.status, m.payout_auec) for m in self.missions]
            existing_event_keys = {e.key() for e in self.events}
            for e in new_events:
                if e.key() not in existing_event_keys:
                    self.events.append(e)
                    existing_event_keys.add(e.key())
            self.base_missions = merge_missions([*self.base_missions, *new_missions])
            apply_completion_events(self.base_missions, self.events)
            self.base_missions = merge_missions(self.base_missions)
            self._refresh_contract_overrides()
            after = [(m.stable_key(), m.score(), m.status, m.payout_auec) for m in self.missions]
            return 1 if before != after else 0

        def scan(self):
            p = self.path()
            if not p or not p.exists():
                raise FileNotFoundError(f"Game.log not found: {p or '(empty path)'}")
            tail_text = read_tail(p)
            with self.lock:
                self.base_missions, self.events = parse_log_data(tail_text)
                self._refresh_contract_overrides()
                self.watch_buffer = tail_text[-300000:]
                # Existing contracts loaded by Scan are historical context, not
                # fresh live acceptances. Mark their acceptance events as seen so
                # the next appended log line does not OCR every old contract.
                self.ocr_seen_accept_ids = set(accepted_hauling_mission_ids(self.watch_buffer))
                self.ocr_waiting_accept_ids.clear()
                self.ocr_attempted_ids.clear()
                self.last_size = p.stat().st_size
                self.watch_from_current = False
                self.last_scan = dt.datetime.now().strftime("%H:%M:%S")
                self.status = f"Scanned {p.name}: {len(contract_groups(self.missions))} contract(s), {len(manifest_rows(self.missions))} cargo row(s)."

        def reset_session(self):
            with self.lock:
                self.missions = []
                self.base_missions = []
                self.events = []
                self.watch_buffer = ""
                self.checklist = {}
                self._save_checklist()
                self.contract_overrides = {}
                self._save_contract_overrides()
                self.deleted_contract_ids = set()
                self._save_deleted_contracts()
                self.session_started = time.time()
                self.session_boundary_timestamp = self.session_started
                self.timer_state = "stopped"
                self.timer_start_epoch = None
                self.timer_elapsed_before = 0.0
                self.ocr_generation += 1
                self.ocr_pending_ids.clear()
                self.ocr_seen_accept_ids.clear()
                self.ocr_waiting_accept_ids.clear()
                self.ocr_attempted_ids.clear()
                controller = desktop_controller()
                if controller is not None:
                    controller.hide_ocr_notification()
                self.watch_from_current = True
                p = self.path()
                if p and p.exists():
                    try:
                        self.last_size = p.stat().st_size
                        self.session_boundary_offset = self.last_size
                    except Exception:
                        pass
                self.status = ("Session reset. Live watch continues from the current end of Game.log." if self.is_watching() else "Session reset. Start Watch to track only new contracts from this point.")

        def start_watch(self):
            p = self.path()
            if not p or not p.exists():
                raise FileNotFoundError(f"Game.log not found: {p or '(empty path)'}")
            with self.lock:
                if self.watch_thread and self.watch_thread.is_alive():
                    self.status = "Already watching."
                    return
                if not self.missions and not self.watch_from_current:
                    # Normal startup: scan current tail once for context. After an
                    # explicit Reset Session, keep the EOF baseline and wait only
                    # for newly appended log lines.
                    tail_text = read_tail(p)
                    self.base_missions, self.events = parse_log_data(tail_text)
                    self._refresh_contract_overrides()
                    self.watch_buffer = tail_text[-300000:]
                elif self.watch_from_current:
                    self.watch_buffer = ""
                if not self.watch_from_current:
                    self.ocr_seen_accept_ids.update(accepted_hauling_mission_ids(self.watch_buffer))
                    self.ocr_waiting_accept_ids.clear()
                    self._queue_recent_auto_ocr_candidates()
                self.last_size = p.stat().st_size
                self.watch_stop.clear()
                self.watch_thread = threading.Thread(target=self.watch_loop, args=(p,), daemon=True)
                self.watch_thread.start()
                self.status = f"Watching {p}"

        def stop_watch(self):
            with self.lock:
                self.watch_stop.set()
                thread = self.watch_thread
                self.status = "Watch stopped."
            # Let the polling loop finish before the UI enables Watch again. This
            # avoids a brief "Already watching" race after Stop -> Watch.
            if thread and thread is not threading.current_thread():
                thread.join(timeout=1.5)
            with self.lock:
                if thread and not thread.is_alive() and self.watch_thread is thread:
                    self.watch_thread = None

        def watch_loop(self, p: Path):
            while not self.watch_stop.is_set():
                try:
                    size = p.stat().st_size
                    if size < self.last_size:
                        with self.lock:
                            self.missions = []
                            self.base_missions = []
                            self.events = []
                            self.watch_buffer = ""
                            self.checklist = {}
                            self._save_checklist()
                            self.contract_overrides = {}
                            self._save_contract_overrides()
                            self.deleted_contract_ids = set()
                            self._save_deleted_contracts()
                            self.session_started = time.time()
                            self.session_boundary_timestamp = self.session_started
                            self.session_boundary_offset = 0
                            self.ocr_generation += 1
                            self.ocr_pending_ids.clear()
                            self.ocr_seen_accept_ids.clear()
                            self.ocr_waiting_accept_ids.clear()
                            self.ocr_attempted_ids.clear()
                            self.last_size = 0
                            self.watch_from_current = False
                            self.status = "New Game.log session detected; cleared current session state."
                    if size > self.last_size:
                        with p.open("rb") as f:
                            f.seek(self.last_size)
                            new_text = f.read().decode("utf-8", errors="replace")
                        self.last_size = size
                        with self.lock:
                            self.watch_buffer = (self.watch_buffer + new_text)[-300000:]
                            accepted_ids = set(accepted_hauling_mission_ids(self.watch_buffer))
                            newly_accepted_ids = accepted_ids - self.ocr_seen_accept_ids
                            self.ocr_seen_accept_ids.update(accepted_ids)
                            self.ocr_waiting_accept_ids.update(newly_accepted_ids)
                            new_missions, new_events = parse_log_data(self.watch_buffer)
                            if new_missions or new_events:
                                changed = self.add_update(new_missions, new_events)
                                self.last_scan = dt.datetime.now().strftime("%H:%M:%S")
                                if changed:
                                    self.status = f"Detected {len(new_missions)} mission update(s), {len(new_events)} reward/completion event(s)."
                                else:
                                    self.status = "Ignored duplicate mission/reward notification."
                            ready_ocr_ids = sorted(
                                mission_id for mission_id in self.ocr_waiting_accept_ids
                                if self._group_for_mission_id(mission_id)
                            )
                            for mission_id in ready_ocr_ids:
                                self._queue_auto_ocr(mission_id)
                            self._queue_recent_auto_ocr_candidates()
                except Exception as e:
                    with self.lock:
                        self.status = f"Watch error: {e}"
                time.sleep(1.2)

        def is_watching(self) -> bool:
            return bool(self.watch_thread and self.watch_thread.is_alive() and not self.watch_stop.is_set())

        def to_state(self) -> dict:
            with self.lock:
                apply_completion_events(self.missions, self.events)
                self.missions = merge_missions(self.missions)
                session_elapsed_override = self.session_timer_elapsed()
                accepted, completed, total, mission_elapsed, mission_profit_hr, session_elapsed, session_profit_hr = session_stats(
                    self.missions, self.session_started, session_elapsed_override=session_elapsed_override
                )
                rows = []
                groups_payload = []
                now_epoch = time.time()
                for group_index, group in enumerate(contract_groups(self.missions)):
                    if not group:
                        continue
                    first = group[0]
                    status = "COMPLETED" if group_completed(group) else ("ABANDONED" if group_abandoned(group) else "ACCEPTED")
                    payout_known = group_payout(group)
                    payout_value = payout_known or 0
                    start_epoch = group_start_epoch(group)
                    end_epoch = group_completed_epoch(group) if status in ("COMPLETED", "ABANDONED") else now_epoch
                    duration_seconds = max(0.0, end_epoch - start_epoch) if start_epoch is not None and end_epoch is not None else 0.0
                    objectives = []
                    for mission in group:
                        objective = {
                            "pickup": mission.pickup,
                            "dropoff": mission.dropoff,
                            "commodity": mission.commodity,
                            "scu": mission.scu,
                            "provenance": mission.data_provenance,
                            "scu_provenance": mission.scu_provenance,
                            "quantity_scope": mission.quantity_scope,
                        }
                        objectives.append(objective)
                        row = mission.rows()[0]
                        row = dict(row)
                        row["Status"] = status
                        row["Payout"] = format_auec(payout_known) if payout_known is not None else "Unknown"
                        row["Duration"] = format_duration(duration_seconds) if start_epoch is not None else ""
                        rows.append(row)
                    aggregate_owner = next((mission for mission in group if mission.is_aggregate_load_plannable()), None)
                    groups_payload.append({
                        "id": group_index,
                        "mission_id": first.mission_id,
                        "needs_review": any(mission.is_placeholder() for mission in group),
                        "aggregate_quantity": aggregate_owner is not None and len(group) > 1,
                        "aggregate_scu": aggregate_owner.scu if aggregate_owner is not None else "",
                        "status": status,
                        "payout": format_auec(payout_known) if payout_known is not None else "",
                        "payout_known": payout_known is not None,
                        "payout_value": payout_value,
                        "contracted_by": first.contracted_by,
                        "duration": format_duration(duration_seconds) if start_epoch is not None else "",
                        "duration_seconds": int(duration_seconds),
                        "rank": first.rank,
                        "confidence": first.confidence,
                        "notes": first.notes,
                        "mission": first.title,
                        "accepted_at": first.timestamp,
                        "completed_at": first.completed_timestamp,
                        "accepted_epoch": start_epoch or 0,
                        "objectives": objectives,
                    })
                logistics_groups = logistics_sections(self.missions)
                active_objective_count = sum(section.get("objective_count", 0) for section in logistics_groups)
                quantity_summary = active_quantity_summary(self.missions)
                # Keep checklist persistence independent from the initial empty
                # dashboard state. The UI ignores ids that are not present in the
                # current active objectives, while newly loaded objectives retain
                # their checked state across dashboard/overlay process refreshes.
                checklist_snapshot = dict(self.checklist)
                timer_label = {
                    "running": "RUNNING",
                    "paused": "PAUSED",
                    "stopped": "STOPPED",
                    "armed_first": "WAITING",
                }.get(self.timer_state, self.timer_state.upper())
                return {
                    "app": APP_NAME,
                    "version": APP_VERSION,
                    "log_path": self.log_path,
                    "guessed_log_paths": list(self.guessed_log_paths),
                    "watching": self.is_watching(),
                    "status": self.status,
                    "last_scan": self.last_scan,
                    "timer_state": self.timer_state,
                    "timer_label": timer_label,
                    "timer_elapsed": format_duration(session_elapsed),
                    "stats": {
                        "accepted": accepted,
                        "completed": completed,
                        "profit": format_auec(total),
                        "mission_rate": format_auec(int(mission_profit_hr)),
                        "session_rate": format_auec(int(session_profit_hr)),
                        "mission_elapsed": format_duration(mission_elapsed),
                        "session_elapsed": format_duration(session_elapsed),
                    },
                    "rows": rows,
                    "groups": groups_payload,
                    "row_count": len(rows),
                    "logistics": {
                        "sections": logistics_groups,
                        "active_objectives": active_objective_count,
                        "quantity_summary": quantity_summary,
                    },
                    "checklist": checklist_snapshot,
                    "ocr": {
                        "auto_enabled": bool(self.auto_ocr_enabled),
                        "pending": len(self.ocr_pending_ids),
                        "waiting": len(self.ocr_waiting_accept_ids),
                        "status": self.ocr_last_status,
                    },
                }

    def commodity_status(missions: Sequence[CargoMission], commodity: str, col: str) -> str:
        status = "ACCEPTED"
        for m in missions:
            if (m.commodity or "").lower() != (commodity or "").lower():
                continue
            if m.dropoff == col or m.pickup == col or f"{m.pickup} → {m.dropoff}" == col:
                if m.status.upper() == "COMPLETED":
                    return "COMPLETED"
                if m.status.upper() in ("ABANDONED", "FAILED", "CANCELLED"):
                    status = "ABANDONED"
        return status

    state = WebState()

    def preload_current_log() -> None:
        """Populate the dashboard after the local server is already responsive."""
        try:
            path = state.path()
            if path and path.exists():
                with state.lock:
                    state.status = f"Loading {path.name}…"
                state.scan()
        except Exception as preload_error:
            with state.lock:
                state.status = f"Preload scan skipped: {preload_error}"

    WEB_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SCHT — SC Hauling Tracker</title>
<link rel="icon" type="image/png" href="/assets/sc_hauling_logo.png">
<style>
:root{
  --bg:#07070c;--surface:#14141e;--surface2:#1b1a27;--surface3:#222033;
  --line:#2a293d;--line2:#3a3653;--purple:#7c63ff;--purple2:#a78cff;
  --cyan:#55d9ff;--blue:#5aa7ff;--green:#49eda0;--red:#ff6476;--amber:#ffc24d;
  --text:#f4f5ff;--soft:#c2c6df;--muted:#858aa3;--shadow:rgba(0,0,0,.48);--radius:15px;
  --type-meta:9px;--type-ui:10px;--type-control:10.5px;--type-heading:12px;--weight-body:700;--weight-control:700;--weight-strong:900;
}
*{box-sizing:border-box;scrollbar-width:thin;scrollbar-color:#4c4768 #0b0b12}
*::-webkit-scrollbar{width:10px;height:10px}*::-webkit-scrollbar-track{background:#0b0b12;border-radius:10px}*::-webkit-scrollbar-thumb{background:linear-gradient(180deg,#4a4566,#312e46);border:2px solid #0b0b12;border-radius:10px}*::-webkit-scrollbar-thumb:hover{background:linear-gradient(180deg,#655d87,#443e61)}*::-webkit-scrollbar-corner{background:#0b0b12}
html,body{height:100%;min-height:0;overflow:hidden}
body{
  margin:0;color:var(--text);font-family:"Segoe UI Variable Text","Segoe UI",Inter,Arial,sans-serif;
  background:
    radial-gradient(950px 500px at 68% -180px,rgba(124,99,255,.20),transparent 62%),
    radial-gradient(700px 540px at -8% 8%,rgba(85,217,255,.075),transparent 60%),
    linear-gradient(180deg,#0f0f18 0%,#08080e 58%,#050508 100%);
  overflow:hidden;
}
body:before{content:"";position:fixed;inset:0;pointer-events:none;background:linear-gradient(90deg,rgba(255,255,255,.012) 1px,transparent 1px),linear-gradient(rgba(255,255,255,.01) 1px,transparent 1px);background-size:46px 46px;mask-image:radial-gradient(circle at 50% 0%,black,transparent 78%)}
button,input,select{font:inherit}
.window-root{height:100vh;min-height:0;display:grid;grid-template-rows:48px minmax(0,1fr);overflow:hidden;background:#07070c}.main-titlebar{position:relative;z-index:100;display:flex;align-items:flex-start;justify-content:space-between;min-width:0;padding:12px 12px 0 6px;background:transparent;border:0;box-shadow:none;user-select:none}.main-drag{height:100%;min-width:0;flex:1;cursor:move}.main-window-actions{height:auto;display:flex;align-items:center;gap:5px}.main-window-btn{width:31px;height:30px;padding:0;border:1px solid rgba(255,255,255,.08);border-radius:8px;background:rgba(255,255,255,.028);color:#dfe2f6;display:grid;place-items:center;cursor:pointer;transition:.14s}.main-window-btn:disabled{opacity:.36;cursor:default}.main-window-btn svg{width:13px;height:13px;fill:currentColor;pointer-events:none}.main-window-btn:hover:not(:disabled){border-color:rgba(90,167,255,.48);background:rgba(90,167,255,.10)}.main-window-btn.danger:hover:not(:disabled){border-color:rgba(255,100,118,.5);color:var(--red);background:rgba(255,100,118,.08)}.maximize-icon,.restore-icon{display:grid;place-items:center}.restore-icon{display:none}.main-maximized .maximize-icon{display:none}.main-maximized .restore-icon{display:grid}.main-resize-handle{display:none;position:fixed;z-index:220;background:transparent;touch-action:none}.desktop-mode .main-resize-handle{display:block}.main-maximized .main-resize-handle{display:none}.main-resize-handle[data-resize="n"]{left:12px;right:12px;top:0;height:7px;cursor:ns-resize}.main-resize-handle[data-resize="s"]{left:12px;right:12px;bottom:0;height:7px;cursor:ns-resize}.main-resize-handle[data-resize="w"]{left:0;top:12px;bottom:12px;width:7px;cursor:ew-resize}.main-resize-handle[data-resize="e"]{right:0;top:12px;bottom:12px;width:7px;cursor:ew-resize}.main-resize-handle[data-resize="nw"]{left:0;top:0;width:14px;height:14px;cursor:nwse-resize}.main-resize-handle[data-resize="ne"]{right:0;top:0;width:14px;height:14px;cursor:nesw-resize}.main-resize-handle[data-resize="sw"]{left:0;bottom:0;width:14px;height:14px;cursor:nesw-resize}.main-resize-handle[data-resize="se"]{right:0;bottom:0;width:14px;height:14px;cursor:nwse-resize}.app-viewport{min-height:0;overflow:auto;overscroll-behavior:contain;background:transparent}.app{width:min(100%,1460px);margin:0 auto;padding:15px 16px 12px;display:grid;grid-template-rows:auto auto minmax(28px,1fr);gap:12px;min-height:100%;align-content:start}
.topbar{display:grid;grid-template-columns:200px minmax(190px,1fr) auto;gap:10px;align-items:center;min-height:56px;min-width:0}
.brand{display:flex;gap:12px;align-items:center;min-width:0}.mark{width:64px;height:64px;flex:0 0 64px;display:grid;place-items:center}.mark img{display:block;width:64px;height:64px;object-fit:contain}.brand-copy{min-width:0;display:flex;flex-direction:column;justify-content:center}
.brand h1{margin:0;font-size:18px;letter-spacing:.45px;line-height:1;font-weight:var(--weight-strong)}.brand-subtitle{margin-top:4px;color:#d8dbef;font-size:var(--type-heading);line-height:1.1;font-weight:var(--weight-body);white-space:nowrap}.brand small{display:block;margin-top:4px;color:#918fb3;font-weight:var(--weight-body);font-size:var(--type-meta);letter-spacing:.35px}
.pathline{height:39px;display:flex;align-items:center;gap:9px;background:rgba(20,20,31,.84);border:1px solid var(--line);border-radius:10px;padding:0 11px;min-width:0;box-shadow:inset 0 0 0 1px rgba(255,255,255,.01)}.pathline label{font-size:9px;text-transform:uppercase;letter-spacing:.8px;color:var(--muted);font-weight:900}.pathline input{flex:1;min-width:0;background:transparent;border:0;outline:0;color:#e1e4fa;font-weight:650;font-size:11.5px}.pathline:focus-within{border-color:rgba(124,99,255,.72);box-shadow:0 0 0 3px rgba(124,99,255,.10)}
.actions{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end;align-items:center;min-width:0}.btn{height:34px;border:1px solid var(--line);border-radius:9px;background:linear-gradient(180deg,#1a1a26,#111119);color:#d9dcf3;padding:0 12px;font-size:var(--type-control);font-weight:var(--weight-control);line-height:1;letter-spacing:.01em;text-transform:none;cursor:pointer;white-space:nowrap;box-shadow:inset 0 1px 0 rgba(255,255,255,.03);transition:border-color .15s,transform .15s,opacity .15s}.btn:hover:not(:disabled){border-color:rgba(124,99,255,.72);color:#fff;transform:translateY(-1px)}.btn:disabled{opacity:.42;cursor:not-allowed}.btn.primary{border-color:rgba(124,99,255,.72);background:linear-gradient(180deg,#312858,#1d1834);color:#f0edff}.btn.red{border-color:rgba(255,100,118,.55);background:linear-gradient(180deg,#371820,#1d0d12);color:#ffb7c0}.btn.active{box-shadow:0 0 0 3px rgba(124,99,255,.11),inset 0 1px 0 rgba(255,255,255,.04)}.menu-wrap{position:relative;display:inline-flex}.menu-trigger{display:inline-flex;align-items:center;gap:7px}.menu-trigger svg,.icon-btn svg{display:block;width:14px;height:14px;fill:currentColor;pointer-events:none}.menu-trigger[aria-expanded="true"]{border-color:rgba(124,99,255,.72);background:linear-gradient(180deg,#312858,#1d1834);color:#fff}.icon-btn{width:34px;padding:0;display:grid;place-items:center}.dropdown-menu{position:absolute;right:0;top:calc(100% + 7px);z-index:190;display:none;width:214px;padding:6px;border:1px solid var(--line2);border-radius:11px;background:linear-gradient(180deg,#1b1a29,#101018);box-shadow:0 18px 44px rgba(0,0,0,.56)}.dropdown-menu.open{display:grid;gap:4px}.dropdown-item{width:100%;min-height:44px;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:10px;padding:7px 9px;border:1px solid transparent;border-radius:8px;background:transparent;color:#dfe2f6;text-align:left;cursor:pointer}.dropdown-item:hover,.dropdown-item:focus-visible{outline:0;border-color:rgba(90,167,255,.26);background:rgba(90,167,255,.075)}.dropdown-item strong{font-size:10.5px;font-weight:850}.dropdown-item small{display:block;margin-top:3px;color:var(--muted);font-size:8.5px;font-weight:650}.dropdown-format{min-width:40px;padding:4px 5px;border:1px solid rgba(124,99,255,.20);border-radius:6px;background:rgba(124,99,255,.08);color:#bdb3ff;font-size:8px;font-weight:900;text-align:center;letter-spacing:.45px}.settings-menu{width:286px}.settings-menu .dropdown-item{min-height:54px}.dropdown-divider{height:1px;margin:3px 4px;background:rgba(255,255,255,.07)}.setting-toggle{position:relative;width:34px;height:18px;flex:0 0 34px;border:1px solid rgba(255,255,255,.14);border-radius:999px;background:#292838;box-shadow:inset 0 1px 3px rgba(0,0,0,.35);transition:.16s}.setting-toggle:after{content:"";position:absolute;left:2px;top:2px;width:12px;height:12px;border-radius:50%;background:#9a9db3;box-shadow:0 1px 3px rgba(0,0,0,.45);transition:.16s}.setting-toggle.on{border-color:rgba(73,237,160,.48);background:rgba(73,237,160,.18)}.setting-toggle.on:after{left:18px;background:var(--green)}.danger-item{color:#ffc4cc}.danger-item:hover,.danger-item:focus-visible{border-color:rgba(255,100,118,.30);background:rgba(255,100,118,.075)}.danger-item .dropdown-format{border-color:rgba(255,100,118,.23);background:rgba(255,100,118,.08);color:#ffadb8}.workspace-tools{display:flex;align-items:stretch;justify-content:space-between;gap:10px;min-width:0}.first-run{flex:1;min-width:0;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:9px 11px;border:1px solid rgba(90,167,255,.20);border-radius:10px;background:linear-gradient(180deg,rgba(25,31,45,.90),rgba(16,18,27,.94));color:#dfe5f9}.first-run[hidden]{display:none}.first-run strong{font-size:11px;font-weight:900}.first-run small{display:block;margin-top:2px;color:var(--muted);font-size:9.5px}.log-suggestions{display:flex;gap:6px;min-width:0;flex-wrap:wrap;justify-content:flex-end}.suggestion-btn,.view-toggle{height:28px;border:1px solid var(--line);border-radius:8px;background:#11111a;color:#cbd0e8;padding:0 10px;font-size:var(--type-control);font-weight:var(--weight-control);line-height:1;text-transform:none;letter-spacing:.01em;cursor:pointer;white-space:nowrap}.suggestion-btn:hover,.view-toggle:hover{border-color:rgba(90,167,255,.58);color:#fff}.view-toggle.active,.filter-btn.active{border-color:rgba(90,167,255,.66);background:rgba(90,167,255,.12);color:#fff}
.shell{display:grid;grid-template-columns:216px minmax(0,1fr);gap:14px;align-items:start;min-width:0}.side{display:grid;gap:11px;min-width:0}.panel{background:linear-gradient(180deg,rgba(26,26,39,.97),rgba(18,18,28,.985));border:1px solid var(--line);border-radius:var(--radius);box-shadow:0 16px 38px var(--shadow);position:relative;overflow:hidden}.panel:after{content:"";position:absolute;inset:0;border-radius:inherit;pointer-events:none;background:linear-gradient(135deg,rgba(255,255,255,.04),transparent 38%,rgba(124,99,255,.028))}
.side-panel{padding:14px}.side h3{margin:0 0 11px;font-size:11.5px;color:#e2e4fb;font-weight:900}.timer{font:900 29px Consolas,monospace;letter-spacing:.7px;color:var(--text);text-shadow:0 0 15px rgba(124,99,255,.18);line-height:1.08}.state{float:right;border:1px solid rgba(133,138,163,.36);background:rgba(133,138,163,.10);color:var(--muted);border-radius:8px;padding:5px 8px;font-size:9px;font-weight:900}.state.running{border-color:rgba(90,167,255,.42);background:rgba(90,167,255,.11);color:var(--blue)}.state.paused,.state.waiting{border-color:rgba(255,194,77,.40);background:rgba(255,194,77,.10);color:var(--amber)}.timer-sub{font-size:9px;text-transform:uppercase;color:var(--muted);font-weight:900;margin-top:3px;letter-spacing:.5px}.button-stack{display:grid;gap:7px;margin-top:12px}.button-stack .btn{width:100%;height:33px}
.stat-list{display:grid;gap:10px}.stat-row{display:flex;align-items:center;justify-content:space-between;gap:9px;font-size:11px;color:var(--soft)}.stat-row strong{color:var(--text);text-align:right}.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:7px;background:var(--muted)}.dot.green{background:var(--green)}.dot.blue{background:var(--blue)}.dot.red{background:var(--red)}.dot.amber{background:var(--amber)}
.main{display:grid;grid-template-rows:auto auto auto;gap:11px;min-width:0}.cards{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:9px}.card{padding:13px 14px;border-radius:14px;background:linear-gradient(180deg,rgba(30,30,45,.99),rgba(21,21,32,.99));border:1px solid var(--line);box-shadow:0 12px 26px rgba(0,0,0,.27);min-width:0}.card .k{font-size:8.5px;text-transform:uppercase;color:#898ea8;font-weight:900;letter-spacing:.78px}.card .v{font-size:clamp(17px,1.5vw,21px);line-height:1.12;font-weight:950;margin:7px 0 4px;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card .unit{font-size:.62em;color:inherit}.card .s{font-size:9.5px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card.blue .v{color:var(--blue)}.card.green .v{color:var(--green)}.card.amber .v{color:var(--amber)}
.content-panel{display:grid;grid-template-rows:52px minmax(0,1fr) 14px;height:var(--contract-log-height,398px);min-height:280px;max-height:min(760px,calc(100vh - 300px))}.contract-resizer,.logistics-resizer{position:relative;height:14px;z-index:12;cursor:ns-resize;touch-action:none;background:#151520;border-top:1px solid rgba(154,147,203,.30);box-shadow:inset 0 1px 0 rgba(255,255,255,.035)}.contract-resizer:after,.logistics-resizer:after{content:"";position:absolute;left:50%;top:6px;width:46px;height:2px;border-radius:99px;background:rgba(154,147,203,.58);transform:translateX(-50%);transition:background .15s}.contract-resizer:hover:after,.contract-resizer.active:after,.logistics-resizer:hover:after,.logistics-resizer.active:after{background:rgba(90,167,255,.82)}.resizing-contract-log,.resizing-logistics-board{cursor:ns-resize!important;user-select:none!important}.panel-head{display:flex;align-items:center;justify-content:space-between;gap:11px;padding:0 14px;border-bottom:1px solid var(--line);min-width:0}.title-row{display:flex;align-items:baseline;gap:10px;min-width:0}.title-row h2{font-size:14px;margin:0;font-weight:950;white-space:nowrap}.title-row small{color:var(--muted);font-size:10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tools{display:flex;align-items:center;gap:7px;min-width:0}.filterbar{display:flex;align-items:center;gap:5px;min-width:max-content}.filter-btn{height:27px;border:1px solid rgba(154,147,203,.18);border-radius:7px;background:#101018;color:#aeb4ce;padding:0 9px;font-size:var(--type-control);font-weight:var(--weight-control);line-height:1;text-transform:none;letter-spacing:.01em;cursor:pointer}.search,.select{height:32px;border:1px solid var(--line);border-radius:8px;background:#101018;color:#d9dcf3;padding:0 10px;font-size:10px;min-width:0;outline:0}.search:focus,.select:focus{border-color:rgba(124,99,255,.70);box-shadow:0 0 0 3px rgba(124,99,255,.09)}.search{width:min(235px,21vw)}.select{width:145px}
.table-wrap{min-height:0;overflow-y:auto;overflow-x:hidden;padding:0;background:transparent;scrollbar-color:#3b3756 #0b0b12}.table{width:100%;min-width:0;border-collapse:separate;border-spacing:0;table-layout:fixed;background:transparent}.table th{position:sticky;top:0;z-index:3;height:44px;background:#12121d;color:#969bb5;text-transform:uppercase;font-size:8.7px;letter-spacing:.72px;border-bottom:1px solid #343149;text-align:left;padding:0 8px;box-shadow:0 6px 14px rgba(0,0,0,.16)}.table th:first-child,.table th:last-child{border-radius:0}.table th:nth-child(5){text-align:center}.table tbody,.table tbody tr,.table tbody td{background:none!important;background-image:none!important}.table tbody tr{--contract-accent:#858aa3}.table tbody tr.accepted{--contract-accent:var(--blue)}.table tbody tr.completed{--contract-accent:var(--green)}.table tbody tr.abandoned{--contract-accent:var(--red)}.table td{height:45px;padding:8px;color:#cfd3e7;font-size:10.8px;line-height:1.22;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;border-bottom:1px solid rgba(255,255,255,.04)}.table tr.group-start td{border-top:1px solid rgba(255,255,255,.105)}.table tr.group-end td{border-bottom:1px solid rgba(255,255,255,.105)}.table td.contract-cell{vertical-align:middle;color:var(--contract-accent);box-shadow:none}.table td.status-cell{position:relative;padding-left:14px;padding-right:8px;border-left:3px solid var(--contract-accent);border-radius:0}.table td.rank-cell{border-radius:0}.table td.location-cell{font-weight:650;color:#d8dced}.table td.dropoff-cell{color:#eceeff}.route-location{display:flex;align-items:center;gap:7px;min-width:0}.route-icon{display:block;width:10px;height:10px;flex:0 0 10px;fill:currentColor;opacity:.92}.pickup-route .route-icon{color:#6f9bd1}.dropoff-route .route-icon{color:#8979d8}.location-text{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis}.commodity-cell{color:#e0e3f5}.commodity-chip{--commodity-color:#8b90a5;display:inline-flex;align-items:center;gap:5px;max-width:100%;padding:4px 6px;border:1px solid color-mix(in srgb,var(--commodity-color) 20%,rgba(255,255,255,.035));border-radius:8px;background:color-mix(in srgb,var(--commodity-color) 7%,rgba(255,255,255,.012));font-weight:720;overflow:hidden;text-overflow:ellipsis}.commodity-chip .cargo-icon{width:12px;height:12px;flex:0 0 12px;fill:var(--commodity-color);color:var(--commodity-color);filter:none}.commodity-name{display:block;overflow:hidden;text-overflow:ellipsis}.scu-cell{text-align:center}.scu-stack{display:inline-flex;align-items:baseline;justify-content:center;gap:4px;min-width:40px;padding:4px 5px;white-space:nowrap;border-radius:7px;background:rgba(124,99,255,.075);border:1px solid rgba(124,99,255,.14)}.scu-stack strong{font:850 10.8px Consolas,monospace;color:#ece9ff}.scu-stack small{font-size:7px;line-height:1;color:#817ba5;font-weight:900;letter-spacing:.35px}.shared-scu-stack{flex-direction:column;align-items:center;gap:2px;line-height:1.05}.shared-scu-stack strong{white-space:nowrap}.shared-scu-stack small{display:block}.status-pill{display:inline-flex;align-items:center;gap:7px;min-width:0;color:var(--contract-accent)}.status-icon{width:27px;height:27px;padding:5px;display:inline-grid;place-items:center;flex:0 0 27px;border-radius:8px;background:color-mix(in srgb,var(--contract-accent) 9%,rgba(255,255,255,.015));border:1px solid color-mix(in srgb,var(--contract-accent) 22%,transparent);filter:none}.status-icon svg{display:block;width:100%;height:100%;fill:currentColor}.status-copy{display:grid;gap:4px;min-width:0}.status-line{display:flex;align-items:center;gap:4px;min-width:0;line-height:1}.status-line strong{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:10.4px;letter-spacing:.22px;line-height:1;font-weight:920}.status-copy small{font-size:8.2px;color:#858aa3;line-height:1.1;font-weight:680}.metric-cell{text-align:left}.metric-card{display:inline-grid;gap:3px;width:100%;max-width:74px;min-width:0;box-sizing:border-box;padding:6px;border-radius:8px;background:color-mix(in srgb,var(--contract-accent) 5%,rgba(255,255,255,.012));border:1px solid color-mix(in srgb,var(--contract-accent) 11%,transparent)}.metric-main{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:900;color:var(--contract-accent);font-size:10.8px}.metric-unit{display:block;color:#777d95;font-size:7.3px;text-transform:uppercase;letter-spacing:.55px;font-weight:850}.duration-value{font:850 10.2px Consolas,monospace;color:var(--contract-accent)}.rank-chip{display:inline-flex;align-items:center;max-width:100%;min-height:23px;padding:0 6px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;border-radius:7px;border:1px solid color-mix(in srgb,var(--contract-accent) 18%,transparent);background:color-mix(in srgb,var(--contract-accent) 6%,transparent);color:var(--contract-accent);font-size:9.2px;font-weight:820}.contract-actions{display:inline-flex;align-items:center;justify-content:flex-start;gap:3px;flex:0 0 auto}.contract-action{width:16px;height:16px;padding:0;display:inline-grid;place-items:center;border:0;border-radius:0;background:transparent;color:#8990aa;cursor:pointer;opacity:.78;line-height:0;transition:color .14s,opacity .14s,transform .14s}.contract-action svg{display:block;width:12px;height:12px;fill:currentColor;pointer-events:none}.contract-action:hover{opacity:1;transform:translateY(-.5px)}.contract-action:focus-visible{outline:1px solid currentColor;outline-offset:2px;border-radius:2px}.contract-action.edit:hover{background:transparent;color:var(--blue)}.contract-action.delete:hover{background:transparent;color:var(--red)}.contract-action.review{color:var(--amber);opacity:.95;background:transparent}.empty-value{color:#5e6379}.empty-row td{text-align:center!important;color:var(--muted)!important;height:150px!important;background:none!important;border:0!important}
.logistics{display:grid;grid-template-rows:48px 36px minmax(0,1fr) 14px;height:var(--logistics-height,260px);min-height:212px;max-height:min(620px,calc(100vh - 260px))}.checklist-tools{display:flex;align-items:center;gap:8px;min-width:0}.checklist-summary{display:flex;align-items:baseline;gap:7px;white-space:nowrap}.checklist-summary strong{color:var(--blue);font-size:10px;font-weight:950}.checklist-summary small{color:var(--muted);font-size:8.5px;font-weight:800;text-transform:uppercase;letter-spacing:.35px}.checklist-summary.complete strong,.checklist-summary.complete small{color:var(--green)}.checklist-reset,.overlay-open{height:28px;border:1px solid var(--line);border-radius:8px;background:#11111a;color:#aeb3cc;padding:0 10px;font-size:var(--type-control);font-weight:var(--weight-control);line-height:1;letter-spacing:.01em;text-transform:none;cursor:pointer}.checklist-reset:hover:not(:disabled),.overlay-open:hover:not(:disabled){border-color:rgba(124,99,255,.68);color:#fff}.checklist-reset:disabled,.overlay-open:disabled{opacity:.38;cursor:not-allowed}.next-action{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:0 14px;border-bottom:1px solid rgba(255,255,255,.055);background:rgba(11,12,18,.48);color:#aeb4cc;font-size:10px;min-width:0}.next-action strong{color:#dfe6fb;font-weight:900}.next-action span{min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.next-action.complete strong{color:var(--green)}.logistics-groups{display:grid;gap:13px;padding:11px 13px 13px;min-width:0;min-height:0;overflow:auto;scrollbar-color:#3b3756 #0b0b12}.logistics-group{display:grid;grid-template-columns:180px minmax(0,1fr);gap:11px;min-width:0}.logistics-group+.logistics-group{border-top:1px solid rgba(255,255,255,.055);padding-top:13px}.pickup-card{border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg,#1d1e2b,#14141e);padding:14px;min-height:144px;display:flex;flex-direction:column}.pickup-card>small{font-size:8.5px;text-transform:uppercase;color:#9b9fc0;font-weight:950;letter-spacing:.35px}.pickup-card .loc{font-size:18px;color:var(--text);font-weight:950;margin:16px 0 7px;line-height:1.15}.pickup-card p{font-size:10px;color:var(--muted);margin:0;line-height:1.3}.section-check-progress{margin-top:auto;padding-top:12px}.check-progress-track{height:4px;border-radius:99px;background:#2a293a;overflow:hidden}.check-progress-fill{height:100%;width:var(--progress,0%);border-radius:inherit;background:linear-gradient(90deg,var(--blue),var(--purple2));transition:width .18s ease}.section-check-progress.complete .check-progress-fill{background:var(--green)}.section-check-progress small{display:block;margin-top:6px;color:#858aa3;font-size:8.5px;font-weight:800;text-transform:none;letter-spacing:0}.section-check-progress.complete small{color:var(--green)}.destinations{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;min-width:0}.dest-card{border:1px solid var(--line);border-radius:12px;background:linear-gradient(180deg,#1c1d29,#14141e);display:grid;grid-template-rows:42px minmax(60px,1fr) 34px;overflow:hidden;min-height:144px}.dest-card h4{margin:0;padding:11px 11px;border-bottom:1px solid var(--line);font-size:9px;text-transform:uppercase;color:#ececff;letter-spacing:.22px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;background:rgba(124,99,255,.04)}.items{padding:7px 8px;min-height:0}.item{display:flex;align-items:center;justify-content:space-between;gap:8px;margin:3px 0;color:var(--blue);font-size:10.8px;font-weight:800}.item.completed{color:var(--green)}.item.abandoned{color:var(--red)}.load-item{position:relative;min-height:34px;padding:6px 7px;border:1px solid transparent;border-radius:8px;cursor:pointer;user-select:none;transition:background .14s,border-color .14s,opacity .14s}.load-item:hover{background:rgba(90,167,255,.055);border-color:rgba(90,167,255,.16)}.load-item:focus-within{outline:2px solid rgba(90,167,255,.36);outline-offset:1px}.load-check{position:absolute;opacity:0;pointer-events:none}.check-box{width:17px;height:17px;flex:0 0 17px;border:1px solid #4a4961;border-radius:5px;background:#11111a;display:grid;place-items:center;transition:.14s}.check-box:after{content:"";width:8px;height:4px;border-left:2px solid #07120d;border-bottom:2px solid #07120d;transform:rotate(-45deg) scale(0);transition:transform .13s}.load-check:checked+.check-box{border-color:rgba(73,237,160,.78);background:var(--green);box-shadow:0 0 12px rgba(73,237,160,.20)}.load-check:checked+.check-box:after{transform:rotate(-45deg) scale(1)}.load-item.is-loaded{background:rgba(73,237,160,.045);border-color:rgba(73,237,160,.12);color:var(--green)}.load-item.is-loaded .commodity-label,.load-item.is-loaded>b{opacity:.56}.load-item.is-loaded .commodity-label>span:last-child{text-decoration:line-through;text-decoration-thickness:1px}.commodity-label{display:inline-flex;align-items:center;gap:7px;min-width:0;flex:1}.cargo-icon{width:15px;height:15px;flex:0 0 15px;fill:currentColor;filter:drop-shadow(0 0 3px currentColor)}.total{display:flex;align-items:center;justify-content:space-between;gap:8px;border-top:1px solid var(--line);padding:0 11px;color:#e0e3fb;font-weight:900;font-size:9.5px;background:rgba(255,255,255,.018)}.total .loaded-count{color:var(--muted)}.total.complete .loaded-count,.total.complete .loaded-scu{color:var(--green)}.logistics-empty{margin:11px 13px 13px;border:1px dashed var(--line2);border-radius:13px;padding:26px;text-align:center;color:var(--muted);font-size:11px}
.footer{height:28px;align-self:end;display:flex;align-items:center;justify-content:space-between;gap:12px;color:#777d97;font-size:9.5px;padding:0 2px;white-space:nowrap;overflow:hidden}.footer span{overflow:hidden;text-overflow:ellipsis}.greenText{color:var(--green)!important}.blueText{color:var(--blue)!important}.redText{color:var(--red)!important}.amberText{color:var(--amber)!important}
.toast{position:fixed;right:18px;bottom:18px;z-index:650;display:grid;grid-template-columns:minmax(0,1fr) 16px;gap:9px;align-items:center;max-width:min(430px,calc(100vw - 36px));min-width:min(300px,calc(100vw - 36px));min-height:34px;padding:8px 10px 8px 12px;border:1px solid rgba(90,167,255,.52);border-radius:8px;background:#101018;color:#dbe7ff;font-size:11px;line-height:1.3;box-shadow:0 14px 34px rgba(0,0,0,.38);opacity:0;transform:translateY(8px);pointer-events:none;transition:.18s}.toast.show{opacity:1;transform:translateY(0);pointer-events:auto}.toast-message{min-width:0;min-height:16px;display:flex;align-items:center;overflow-wrap:anywhere}.toast-close{align-self:start;width:16px;height:16px;padding:0;border:0;background:transparent;color:inherit;opacity:.68;cursor:pointer;display:grid;place-items:center;line-height:0;transition:opacity .14s,transform .14s}.toast-close svg{display:block;width:10px;height:10px;stroke:currentColor;stroke-width:2.25;stroke-linecap:round;pointer-events:none}.toast-close:hover{opacity:1;transform:scale(1.08)}.toast-success{border-color:rgba(73,237,160,.64);color:#d8ffe9;background:#0f1d18}.toast-info{border-color:rgba(90,167,255,.64);color:#dbe7ff;background:#101824}.toast-error{border-color:rgba(255,100,118,.68);color:#ffd1d7;background:#211014}.status-wrap{display:flex;align-items:center;gap:8px;min-width:0}.modal-backdrop{position:fixed;inset:0;z-index:300;display:none;align-items:center;justify-content:center;padding:24px;background:rgba(2,2,7,.78);backdrop-filter:blur(7px)}.modal-backdrop.open{display:flex}.editor-modal{width:min(900px,calc(100vw - 44px));max-height:min(760px,calc(100vh - 44px));display:grid;grid-template-rows:auto auto minmax(0,1fr) auto;overflow:hidden;border:1px solid var(--line2);border-radius:16px;background:linear-gradient(180deg,#1b1a29,#101018);box-shadow:0 28px 90px rgba(0,0,0,.72)}.editor-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:16px 18px;border-bottom:1px solid var(--line)}.editor-head h3{margin:0;font-size:15px}.editor-head small{display:block;margin-top:4px;color:var(--muted);font-size:9px}.editor-close{width:24px;height:24px;padding:0;border:0;background:transparent;color:var(--muted);display:grid;place-items:center;line-height:0;cursor:pointer;transition:color .14s,transform .14s}.editor-close svg{width:12px;height:12px;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;pointer-events:none}.editor-close:hover{color:#fff;transform:scale(1.08)}.editor-meta{display:grid;grid-template-columns:minmax(0,1fr) 180px;gap:12px;padding:13px 18px;border-bottom:1px solid rgba(255,255,255,.05)}.editor-field{display:grid;gap:6px}.editor-field label{font-size:8.5px;text-transform:uppercase;letter-spacing:.6px;color:var(--muted);font-weight:900}.editor-field input{height:34px;border:1px solid var(--line);border-radius:8px;background:#0d0d15;color:var(--text);padding:0 10px;outline:0}.editor-field input:focus,.editor-row input:focus,.ocr-panel textarea:focus{border-color:rgba(124,99,255,.72);box-shadow:0 0 0 3px rgba(124,99,255,.09)}.editor-body{min-height:0;overflow:auto;padding:12px 18px}.ocr-panel{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;margin-bottom:12px;padding:10px;border:1px solid rgba(124,99,255,.18);border-radius:10px;background:rgba(124,99,255,.045)}.ocr-panel textarea{min-height:58px;resize:vertical;border:1px solid var(--line);border-radius:8px;background:#0d0d15;color:var(--text);padding:8px 9px;outline:0;font-size:10px}.ocr-actions{display:grid;gap:7px;align-content:start}.editor-grid-head,.editor-row{display:grid;grid-template-columns:minmax(150px,1fr) minmax(180px,1.4fr) minmax(130px,.85fr) 80px 30px;gap:8px;align-items:center}.editor-grid-head{padding:0 2px 7px;color:var(--muted);font-size:8px;text-transform:uppercase;letter-spacing:.55px;font-weight:900}.editor-row{margin-bottom:8px}.editor-row input{height:34px;min-width:0;border:1px solid var(--line);border-radius:8px;background:#0d0d15;color:var(--text);padding:0 9px;outline:0}.editor-remove{height:30px;padding:0;border:1px solid rgba(255,100,118,.3);border-radius:7px;background:rgba(255,100,118,.06);color:var(--red);cursor:pointer;display:grid;place-items:center;line-height:0;transition:border-color .14s,background .14s,transform .14s}.editor-remove svg{width:13px;height:13px;fill:currentColor;pointer-events:none}.editor-remove:hover{border-color:rgba(255,100,118,.58);background:rgba(255,100,118,.11);transform:translateY(-.5px)}.editor-empty{padding:26px;text-align:center;color:var(--muted)}.editor-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:13px 18px;border-top:1px solid var(--line)}.editor-footer-group{display:flex;gap:8px}.editor-help{color:var(--muted);font-size:9px;max-width:390px;line-height:1.35}@media(max-width:760px){.editor-grid-head{display:none}.editor-row{grid-template-columns:1fr 1fr}.editor-row input:nth-child(3){grid-column:1}.editor-row input:nth-child(4){grid-column:2}.editor-remove{grid-column:2;justify-self:end;width:30px}.editor-meta{grid-template-columns:1fr}.editor-help{display:none}.ocr-panel{grid-template-columns:1fr}.toast{right:12px;bottom:12px;max-width:calc(100vw - 24px);min-width:0}}.confirm-modal{width:min(430px,calc(100vw - 40px));overflow:hidden;border:1px solid var(--line2);border-radius:15px;background:linear-gradient(180deg,#1b1a29,#101018);box-shadow:0 28px 90px rgba(0,0,0,.72)}.confirm-head{display:grid;grid-template-columns:36px minmax(0,1fr) 24px;gap:12px;align-items:start;padding:17px 18px 12px}.confirm-icon{width:36px;height:36px;display:grid;place-items:center;border:1px solid rgba(255,100,118,.26);border-radius:10px;background:rgba(255,100,118,.08);color:var(--red)}.confirm-icon svg{width:17px;height:17px;fill:currentColor}.confirm-copy{min-width:0}.confirm-copy h3{margin:1px 0 5px;font-size:15px;line-height:1.2}.confirm-copy p{margin:0;color:var(--soft);font-size:10.5px;line-height:1.45}.confirm-contract{margin:0 18px 14px;padding:10px 11px;border:1px solid rgba(255,255,255,.055);border-radius:9px;background:#0d0d15;color:#dfe2f6;font-size:10.5px;font-weight:700;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.confirm-close{width:24px;height:24px;padding:0;border:0;background:transparent;color:var(--muted);display:grid;place-items:center;line-height:0;cursor:pointer;transition:color .14s,transform .14s}.confirm-close svg{width:12px;height:12px;stroke:currentColor;stroke-width:2.2;stroke-linecap:round;pointer-events:none}.confirm-close:hover{color:#fff;transform:scale(1.08)}.confirm-footer{display:flex;justify-content:flex-end;gap:8px;padding:12px 18px 15px;border-top:1px solid var(--line)}.info-modal{position:relative;width:min(1040px,calc(100vw - 44px));max-height:min(840px,calc(100vh - 44px));display:grid;grid-template-rows:auto minmax(0,1fr) auto;overflow:hidden;border:1px solid var(--line2);border-radius:16px;background:linear-gradient(180deg,#1b1a29,#101018);box-shadow:0 28px 90px rgba(0,0,0,.72)}
.info-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:17px 18px;border-bottom:1px solid var(--line)}.info-title{display:flex;align-items:flex-start;gap:12px;min-width:0}.info-icon{width:38px;height:38px;flex:0 0 38px;display:grid;place-items:center;border:1px solid rgba(90,167,255,.28);border-radius:11px;background:rgba(90,167,255,.08);color:var(--blue)}.info-icon svg{width:18px;height:18px;fill:currentColor}.info-title h3{margin:1px 0 4px;font-size:15px}.info-title small{display:block;color:var(--muted);font-size:9px}.info-body{min-height:0;overflow:auto;padding:0;scroll-behavior:smooth}.info-footer{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 18px 15px;border-top:1px solid var(--line)}.info-footer small{color:var(--muted);font-size:9px}
.guide-shell{position:relative;display:grid;grid-template-columns:188px minmax(0,1fr);min-height:100%}.guide-shell:before{content:"";position:absolute;inset:0 auto 0 0;width:188px;z-index:0;border-right:1px solid rgba(255,255,255,.06);background:linear-gradient(180deg,rgba(13,13,21,.98),rgba(13,13,21,.92));pointer-events:none}.guide-nav{position:sticky;top:0;align-self:start;display:grid;gap:4px;padding:16px 12px;z-index:2}.guide-nav-title{padding:0 8px 8px;color:var(--muted);font-size:8px;font-weight:900;letter-spacing:.7px;text-transform:uppercase}.guide-nav a{display:grid;grid-template-columns:22px minmax(0,1fr);align-items:center;gap:8px;min-height:34px;padding:6px 8px;border:1px solid transparent;border-radius:8px;color:var(--soft);font-size:10px;font-weight:700;text-decoration:none;transition:background .14s,border-color .14s,color .14s}.guide-nav a span{width:22px;height:22px;display:grid;place-items:center;border:1px solid rgba(124,99,255,.24);border-radius:7px;background:rgba(124,99,255,.07);color:var(--purple2);font-size:9px;font-weight:900}.guide-nav a:hover,.guide-nav a:focus-visible{outline:0;border-color:rgba(124,99,255,.35);background:rgba(124,99,255,.08);color:#fff}.guide-content{min-width:0;padding:18px 20px 30px}.guide-hero{margin-bottom:18px;padding:16px 17px;border:1px solid rgba(85,217,255,.18);border-radius:12px;background:linear-gradient(135deg,rgba(85,217,255,.055),rgba(124,99,255,.055))}.guide-kicker{display:inline-flex;margin-bottom:7px;color:var(--cyan);font-size:8px;font-weight:900;letter-spacing:.7px;text-transform:uppercase}.guide-hero h4{margin:0;font-size:15px;line-height:1.35}.guide-hero p{margin:8px 0 0;color:var(--soft);font-size:10.5px;line-height:1.55}.guide-section{scroll-margin-top:16px;padding:19px 0;border-top:1px solid rgba(255,255,255,.065)}.guide-section:first-of-type{border-top:0}.guide-section-head{display:grid;grid-template-columns:30px minmax(0,1fr);gap:10px;align-items:start;margin-bottom:11px}.guide-section-number{width:30px;height:30px;display:grid;place-items:center;border:1px solid rgba(124,99,255,.32);border-radius:9px;background:rgba(124,99,255,.09);color:var(--purple2);font-size:11px;font-weight:900}.guide-section h4{margin:0 0 3px;font-size:13px}.guide-section-head p{margin:0;color:var(--muted);font-size:9.5px;line-height:1.4}.guide-steps{margin:0 0 12px;padding-left:20px;color:var(--soft);font-size:10.5px;line-height:1.55}.guide-steps li{padding:2px 0 5px 3px}.guide-steps strong{color:#fff}.guide-note{margin:10px 0 12px;padding:10px 11px;border-left:3px solid var(--blue);border-radius:0 8px 8px 0;background:rgba(90,167,255,.07);color:var(--soft);font-size:10px;line-height:1.5}.guide-note.warning{border-left-color:var(--amber);background:rgba(255,194,77,.065)}.guide-note.danger{border-left-color:var(--red);background:rgba(255,100,118,.06)}.guide-figure{margin:12px 0 0}.guide-figure.compact{max-width:540px}.guide-image-button{display:block;width:100%;padding:0;border:1px solid rgba(154,147,203,.25);border-radius:10px;background:#090910;overflow:hidden;cursor:zoom-in;line-height:0;box-shadow:0 12px 28px rgba(0,0,0,.22);transition:border-color .14s,transform .14s}.guide-image-button:hover,.guide-image-button:focus-visible{outline:0;border-color:rgba(90,167,255,.58);transform:translateY(-1px)}.guide-image-button img{display:block;width:100%;height:auto}.guide-figure figcaption{margin-top:6px;color:var(--muted);font-size:8.5px;line-height:1.35}.guide-media-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(210px,.65fr);gap:12px;align-items:start;margin-top:12px}.guide-media-grid.compact{grid-template-columns:repeat(2,minmax(0,1fr));max-width:620px}.guide-media-card{min-width:0}.guide-media-card h5{margin:0 0 6px;font-size:10px}.guide-media-card p{margin:7px 0 0;color:var(--muted);font-size:9px;line-height:1.4}.guide-action-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px;margin:10px 0 12px}.guide-action{padding:10px 11px;border:1px solid rgba(255,255,255,.07);border-radius:9px;background:rgba(255,255,255,.025)}.guide-action strong{display:block;margin-bottom:3px;color:#fff;font-size:10px}.guide-action span{display:block;color:var(--muted);font-size:9px;line-height:1.4}.guide-troubleshooting{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.guide-trouble{padding:10px 11px;border:1px solid rgba(255,255,255,.07);border-radius:9px;background:#0d0d15}.guide-trouble strong{display:block;margin-bottom:4px;font-size:10px}.guide-trouble p{margin:0;color:var(--muted);font-size:9px;line-height:1.45}.guide-lightbox{position:absolute;inset:0;z-index:20;display:none;align-items:center;justify-content:center;padding:22px;background:rgba(2,2,7,.9);backdrop-filter:blur(8px)}.guide-lightbox.open{display:flex}.guide-lightbox-frame{max-width:100%;max-height:100%;display:grid;grid-template-rows:minmax(0,1fr) auto;gap:8px}.guide-lightbox-frame img{display:block;max-width:100%;max-height:calc(100vh - 150px);margin:auto;border:1px solid var(--line2);border-radius:10px;box-shadow:0 24px 70px rgba(0,0,0,.58)}.guide-lightbox-frame p{margin:0;color:var(--soft);font-size:9.5px;text-align:center}.guide-lightbox-close{position:absolute;top:15px;right:15px;width:32px;height:32px;padding:0;border:1px solid rgba(255,255,255,.14);border-radius:9px;background:#171621;color:#fff;display:grid;place-items:center;cursor:pointer}.guide-lightbox-close svg{width:13px;height:13px;stroke:currentColor;stroke-width:2.2;stroke-linecap:round}.guide-lightbox-close:hover{border-color:rgba(90,167,255,.5);color:var(--cyan)}
@media(max-width:820px){.info-modal{width:min(760px,calc(100vw - 28px));max-height:calc(100vh - 28px)}.guide-shell{grid-template-columns:1fr}.guide-shell:before{display:none}.guide-nav{position:sticky;top:0;grid-auto-flow:column;grid-auto-columns:max-content;overflow-x:auto;border-right:0;border-bottom:1px solid rgba(255,255,255,.06);padding:9px 10px;background:linear-gradient(180deg,rgba(13,13,21,.98),rgba(13,13,21,.92))}.guide-nav-title{display:none}.guide-nav a{min-height:30px}.guide-content{padding:15px}.guide-media-grid,.guide-media-grid.compact{grid-template-columns:1fr;max-width:none}.guide-action-grid,.guide-troubleshooting{grid-template-columns:1fr}}
@media(max-width:520px){.modal-backdrop{padding:8px}.info-modal{width:calc(100vw - 16px);max-height:calc(100vh - 16px)}.info-head{padding:13px}.info-title small{display:none}.guide-content{padding:12px}.guide-hero{padding:13px}.guide-lightbox{padding:12px}.guide-action-grid{grid-template-columns:1fr}}
/* Unified dashboard typography: three UI sizes and two weights. Large numeric metrics remain intentionally larger. */
body{font-size:var(--type-ui);font-weight:var(--weight-body)}
.btn,.suggestion-btn,.view-toggle,.filter-btn,.checklist-reset,.overlay-open{font-family:"Segoe UI Variable Text","Segoe UI",Inter,Arial,sans-serif;font-size:var(--type-control);font-weight:var(--weight-control);line-height:1;letter-spacing:.01em;text-transform:none;font-kerning:normal;-webkit-font-smoothing:antialiased}.state{font-size:var(--type-ui);font-weight:var(--weight-strong);letter-spacing:.4px}
.pathline label,.timer-sub,.card .k,.table th,.metric-unit,.scu-stack small,.pickup-card>small,.dest-card h4{font-size:var(--type-meta);font-weight:var(--weight-strong)}
.brand small,.first-run small,.card .s,.title-row small,.status-copy small,.checklist-summary small,.section-check-progress small,.footer{font-size:var(--type-meta);font-weight:var(--weight-body)}
.pathline input,.search,.select,.stat-row,.table td,.commodity-chip,.status-copy strong,.metric-main,.duration-value,.rank-chip,.next-action,.pickup-card p,.item,.total,.logistics-empty,.toast{font-size:var(--type-ui);font-weight:var(--weight-body)}
.side h3,.title-row h2,.first-run strong{font-size:var(--type-heading);font-weight:var(--weight-strong)}
.status-copy strong,.metric-main,.duration-value,.rank-chip,.next-action strong,.item,.total{font-weight:var(--weight-strong)}
.scu-stack strong{font:var(--weight-strong) var(--type-ui) Consolas,monospace}
.duration-value{font-family:Consolas,monospace}
@media(max-width:1290px){.shell{grid-template-columns:205px minmax(0,1fr)}.app{padding-top:12px}.cards{gap:7px}.card{padding:12px}.main{grid-template-rows:auto auto auto}.content-panel{min-height:280px}}
@media(max-width:1120px){.topbar{grid-template-columns:200px minmax(190px,1fr)}.actions{grid-column:1/-1;justify-content:flex-start}}
@media(max-width:980px){.topbar{grid-template-columns:1fr}.actions{grid-column:auto}.workspace-tools{flex-direction:column}.shell{grid-template-columns:1fr}.side{grid-template-columns:repeat(2,minmax(0,1fr))}.cards{grid-template-columns:repeat(2,minmax(0,1fr))}.logistics-group{grid-template-columns:1fr}.pickup-card{min-height:auto}.search{width:210px}}
@media(max-width:660px){.app{padding:10px}.side{grid-template-columns:1fr}.cards{grid-template-columns:1fr}.first-run{align-items:flex-start;flex-direction:column}.log-suggestions{justify-content:flex-start}.panel-head{align-items:flex-start;flex-direction:column;padding:10px 12px}.content-panel{grid-template-rows:auto minmax(0,1fr) 14px}.tools{width:100%;flex-wrap:wrap}.filterbar{width:100%;flex-wrap:wrap}.search,.select{width:100%}.logistics{grid-template-rows:auto 36px minmax(0,1fr) 14px}.checklist-tools{flex-wrap:wrap}.destinations{grid-template-columns:repeat(2,minmax(0,1fr))}.footer{display:none}}
</style>
</head>
<body>
<div class="window-root">
  <header class="main-titlebar">
    <div class="main-drag pywebview-drag-region" id="mainDragRegion" aria-label="Drag window"></div>
    <div class="main-window-actions pywebview-drag-region-exclude">
      <button class="main-window-btn" id="mainMinBtn" type="button" title="Minimize" aria-label="Minimize"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M64 480C64 462.3 78.3 448 96 448L544 448C561.7 448 576 462.3 576 480C576 497.7 561.7 512 544 512L96 512C78.3 512 64 497.7 64 480z"/></svg></button>
      <button class="main-window-btn" id="mainMaxBtn" type="button" title="Maximize" aria-label="Maximize"><span class="maximize-icon"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M112 288L112 448C112 456.8 119.2 464 128 464L512 464C520.8 464 528 456.8 528 448L528 288L112 288zM64 192C64 156.7 92.7 128 128 128L512 128C547.3 128 576 156.7 576 192L576 448C576 483.3 547.3 512 512 512L128 512C92.7 512 64 483.3 64 448L64 192z"/></svg></span><span class="restore-icon"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M544 144L256 144C247.2 144 240 151.2 240 160L240 176L192 176L192 160C192 124.7 220.7 96 256 96L544 96C579.3 96 608 124.7 608 160L608 352C608 387.3 579.3 416 544 416L496 416L496 368L544 368C552.8 368 560 360.8 560 352L560 160C560 151.2 552.8 144 544 144zM400 352L80 352L80 480C80 488.8 87.2 496 96 496L384 496C392.8 496 400 488.8 400 480L400 352zM96 224L384 224C419.3 224 448 252.7 448 288L448 480C448 515.3 419.3 544 384 544L96 544C60.7 544 32 515.3 32 480L32 288C32 252.7 60.7 224 96 224z"/></svg></span></button>
      <button class="main-window-btn danger" id="mainCloseBtn" type="button" title="Close" aria-label="Close"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M183.1 137.4C170.6 124.9 150.3 124.9 137.8 137.4C125.3 149.9 125.3 170.2 137.8 182.7L275.2 320L137.9 457.4C125.4 469.9 125.4 490.2 137.9 502.7C150.4 515.2 170.7 515.2 183.2 502.7L320.5 365.3L457.9 502.6C470.4 515.1 490.7 515.1 503.2 502.6C515.7 490.1 515.7 469.8 503.2 457.3L365.8 320L503.1 182.6C515.6 170.1 515.6 149.8 503.1 137.3C490.6 124.8 470.3 124.8 457.8 137.3L320.5 274.7L183.1 137.4z"/></svg></button>
    </div>
  </header>
  <div class="app-viewport" id="appViewport">
<div class="app">
  <header class="topbar">
    <section class="brand"><div class="mark"><img src="/assets/sc_hauling_logo_mark.png" alt="SCHT logo"></div><div class="brand-copy"><h1>SCHT</h1><div class="brand-subtitle">SC Hauling Tracker</div><small id="version">v1.5.66</small></div></section>
    <div class="pathline"><label for="logPath">Game log</label><input id="logPath" spellcheck="false" autocomplete="off"></div>
    <nav class="actions" aria-label="App controls">
      <button class="btn" id="browseBtn" title="Choose a Star Citizen Game.log file">Choose Log</button><button class="btn" id="scanBtn" data-action="scan" title="Read the selected Game.log now">Scan Log</button><button class="btn primary" id="watchBtn" data-action="watch" title="Start monitoring Game.log for new contract events">Start Watch</button>
      <div class="menu-wrap" id="shareMenuWrap"><button class="btn icon-btn menu-trigger" id="shareBtn" type="button" aria-haspopup="menu" aria-expanded="false" title="Export contract data" aria-label="Share and export"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><path d="M342.6 73.4C330.1 60.9 309.8 60.9 297.3 73.4L169.3 201.4C156.8 213.9 156.8 234.2 169.3 246.7C181.8 259.2 202.1 259.2 214.6 246.7L288 173.3L288 384C288 401.7 302.3 416 320 416C337.7 416 352 401.7 352 384L352 173.3L425.4 246.7C437.9 259.2 458.2 259.2 470.7 246.7C483.2 234.2 483.2 213.9 470.7 201.4L342.7 73.4zM160 416C160 398.3 145.7 384 128 384C110.3 384 96 398.3 96 416L96 480C96 533 139 576 192 576L448 576C501 576 544 533 544 480L544 416C544 398.3 529.7 384 512 384C494.3 384 480 398.3 480 416L480 480C480 497.7 465.7 512 448 512L192 512C174.3 512 160 497.7 160 480L160 416z"/></svg></button><div class="dropdown-menu" id="shareMenu" role="menu" aria-label="Export options"><button class="dropdown-item" type="button" role="menuitem" data-export="csv"><span><strong>Export as CSV</strong><small>Spreadsheet-friendly contract data</small></span><span class="dropdown-format">CSV</span></button><button class="dropdown-item" type="button" role="menuitem" data-export="html"><span><strong>Export as HTML</strong><small>Formatted report for viewing or sharing</small></span><span class="dropdown-format">HTML</span></button></div></div>
      <div class="menu-wrap" id="settingsMenuWrap"><button class="btn icon-btn menu-trigger" id="settingsBtn" type="button" aria-haspopup="menu" aria-expanded="false" title="Tracker settings" aria-label="Tracker settings"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><path d="M259.1 73.5C262.1 58.7 275.2 48 290.4 48L350.2 48C365.4 48 378.5 58.7 381.5 73.5L396 143.5C410.1 149.5 423.3 157.2 435.3 166.3L503.1 143.8C517.5 139 533.3 145 540.9 158.2L570.8 210C578.4 223.2 575.7 239.8 564.3 249.9L511 297.3C511.9 304.7 512.3 312.3 512.3 320C512.3 327.7 511.8 335.3 511 342.7L564.4 390.2C575.8 400.3 578.4 417 570.9 430.1L541 481.9C533.4 495 517.6 501.1 503.2 496.3L435.4 473.8C423.3 482.9 410.1 490.5 396.1 496.6L381.7 566.5C378.6 581.4 365.5 592 350.4 592L290.6 592C275.4 592 262.3 581.3 259.3 566.5L244.9 496.6C230.8 490.6 217.7 482.9 205.6 473.8L137.5 496.3C123.1 501.1 107.3 495.1 99.7 481.9L69.8 430.1C62.2 416.9 64.9 400.3 76.3 390.2L129.7 342.7C128.8 335.3 128.4 327.7 128.4 320C128.4 312.3 128.9 304.7 129.7 297.3L76.3 249.8C64.9 239.7 62.3 223 69.8 209.9L99.7 158.1C107.3 144.9 123.1 138.9 137.5 143.7L205.3 166.2C217.4 157.1 230.6 149.5 244.6 143.4L259.1 73.5zM320.3 400C364.5 399.8 400.2 363.9 400 319.7C399.8 275.5 363.9 239.8 319.7 240C275.5 240.2 239.8 276.1 240 320.3C240.2 364.5 276.1 400.2 320.3 400z"/></svg></button><div class="dropdown-menu settings-menu" id="settingsMenu" role="menu" aria-label="Tracker settings"><button class="dropdown-item" id="autoOcrBtn" type="button" role="menuitem" data-action="toggle_auto_ocr" aria-pressed="true"><span><strong>Automatic OCR</strong><small id="autoOcrHelp">Capture newly accepted contracts automatically</small></span><span class="setting-toggle on" id="autoOcrToggle" aria-hidden="true"></span></button><div class="dropdown-divider" role="separator"></div><button class="dropdown-item danger-item" id="resetBtn" type="button" role="menuitem"><span><strong>Reset session</strong><small>Clears contracts, checklist, timer, and saved corrections for this session. Game.log is not changed.</small></span><span class="dropdown-format">RESET</span></button></div></div>
      <button class="btn icon-btn" id="infoBtn" type="button" title="Help and information" aria-label="Help and information"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true"><path d="M320 576C461.4 576 576 461.4 576 320C576 178.6 461.4 64 320 64C178.6 64 64 178.6 64 320C64 461.4 178.6 576 320 576zM320 240C302.3 240 288 254.3 288 272C288 285.3 277.3 296 264 296C250.7 296 240 285.3 240 272C240 227.8 275.8 192 320 192C364.2 192 400 227.8 400 272C400 319.2 364 339.2 344 346.5L344 350.3C344 363.6 333.3 374.3 320 374.3C306.7 374.3 296 363.6 296 350.3L296 342.2C296 321.7 310.8 307 326.1 302C332.5 299.9 339.3 296.5 344.3 291.7C348.6 287.5 352 281.7 352 272.1C352 254.4 337.7 240.1 320 240.1zM288 432C288 414.3 302.3 400 320 400C337.7 400 352 414.3 352 432C352 449.7 337.7 464 320 464C302.3 464 288 449.7 288 432z"/></svg></button>
    </nav>
  </header>
  <div class="shell">
    <aside class="side">
      <section class="side-panel panel"><h3>Session timer <span class="state" id="timerState">STOPPED</span></h3><div class="timer" id="timer">0:00</div><div class="timer-sub">Elapsed</div><div class="button-stack"><button class="btn primary" data-action="timer_first">Start from first mission</button><button class="btn" data-action="timer_now">Start from now</button><button class="btn" id="timerToggle" data-action="timer_toggle">Pause / Play</button></div></section>
      <section class="side-panel panel"><h3>Session status</h3><div class="stat-list"><div class="stat-row"><span><i class="dot green"></i>Completed</span><strong id="sCompleted">0 completed</strong></div><div class="stat-row"><span><i class="dot blue"></i>Accepted</span><strong id="sAccepted">0 accepted</strong></div><div class="stat-row"><span><i class="dot amber"></i>Profit</span><strong class="amberText" id="sProfit">0 aUEC</strong></div><div class="stat-row"><span><i class="dot blue"></i>Session/hr</span><strong class="blueText" id="sRate">0 aUEC/hr</strong></div></div></section>
      <section class="side-panel panel"><h3>Live feed</h3><div class="stat-list"><div class="stat-row"><span>Status</span><strong id="online">IDLE</strong></div><div class="stat-row"><span>Last scan</span><strong id="lastScan">—</strong></div><div class="stat-row"><span>OCR</span><strong id="ocrStatus">Auto OCR ready</strong></div></div></section>
    </aside>
    <main class="main">
      <section class="cards">
        <article class="card blue"><div class="k">Missions accepted</div><div class="v" id="accepted">0</div><div class="s">unique contracts</div></article>
        <article class="card green"><div class="k">Missions completed</div><div class="v" id="completed">0</div><div class="s">paid / completed</div></article>
        <article class="card green"><div class="k">Total profit</div><div class="v"><span id="profit">0</span> <span class="unit">aUEC</span></div><div class="s">completed payouts only</div></article>
        <article class="card blue"><div class="k">Mission profit / hr</div><div class="v"><span id="missionRate">0</span> <span class="unit">aUEC/hr</span></div><div class="s" id="missionElapsed">mission elapsed 0:00</div></article>
        <article class="card amber"><div class="k">Session profit / hr</div><div class="v"><span id="sessionRate">0</span> <span class="unit">aUEC/hr</span></div><div class="s" id="sessionElapsed">session elapsed 0:00</div></article>
      </section>
      <section class="content-panel panel" id="contractPanel">
        <div class="panel-head"><div class="title-row"><h2>Contract log</h2><small id="contractCount">0 contracts · 0 cargo rows</small></div><div class="tools"><div class="filterbar" id="contractFilters"><button class="filter-btn active" type="button" data-filter="all">All</button><button class="filter-btn" type="button" data-filter="active">Active</button><button class="filter-btn" type="button" data-filter="completed">Completed</button><button class="filter-btn" type="button" data-filter="closed">Closed</button></div><input class="search" id="search" placeholder="Search commodity, location, status…"><select class="select" id="sort"><option value="status">Active first</option><option value="accepted_new">Newest accepted</option><option value="accepted_old">Oldest accepted</option><option value="payout">Highest payout</option><option value="duration">Longest duration</option><option value="pickup">Pickup A–Z</option><option value="dropoff">Drop-off A–Z</option><option value="commodity">Commodity A–Z</option></select></div></div>
        <div class="table-wrap"><table class="table"><colgroup><col style="width:18%"><col style="width:15%"><col style="width:18%"><col style="width:13%"><col style="width:8%"><col style="width:10%"><col style="width:10%"><col style="width:8%"></colgroup><thead><tr><th>Status</th><th>Pick up</th><th>Drop off</th><th>Commodity</th><th>SCU</th><th>Payout</th><th>Duration</th><th>Rank</th></tr></thead><tbody id="rows"></tbody></table></div>
        <div class="contract-resizer" id="contractResizer" role="separator" aria-orientation="horizontal" aria-label="Resize contract log"></div>
      </section>
      <section class="logistics panel" id="logisticsPanel"><div class="panel-head"><div class="title-row"><h2>Logistics board</h2><small id="logisticsInfo">Accepted contracts only · grouped by repeated locations</small></div><div class="checklist-tools"><span class="checklist-summary" id="checklistSummary"><strong id="checklistProgress">0/0 loaded</strong><small id="checklistScu">0/0 SCU</small></span><button class="view-toggle" id="hideLoadedBtn" type="button">Hide loaded</button><button class="overlay-open" id="openOverlayBtn" type="button" title="Overlay requires the standalone desktop application" disabled>Desktop only</button><button class="checklist-reset" id="clearChecklistBtn" type="button">Clear checks</button></div></div><div class="next-action" id="nextAction"><span><strong>Next:</strong> no active cargo</span><small>0 SCU</small></div><div class="logistics-groups" id="logisticsGroups"></div><div class="logistics-resizer" id="logisticsResizer" role="separator" aria-orientation="horizontal" aria-label="Resize logistics board"></div></section>
    </main>
  </div>
  <footer class="footer"><span id="status">Ready</span><span id="footerRight">SCHT · SC Hauling Tracker</span></footer>
</div>
  </div>
</div>
<div class="main-resize-handle" data-resize="n" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="s" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="e" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="w" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="ne" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="nw" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="se" aria-hidden="true"></div>
<div class="main-resize-handle" data-resize="sw" aria-hidden="true"></div>
<div class="modal-backdrop" id="contractEditor" aria-hidden="true">
  <section class="editor-modal" role="dialog" aria-modal="true" aria-labelledby="contractEditorTitle">
    <header class="editor-head"><div><h3 id="contractEditorTitle">Edit contract details</h3><small id="contractEditorMission">MissionId</small></div><button class="editor-close" id="contractEditorClose" type="button" aria-label="Close editor"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg></button></header>
    <div class="editor-meta"><div class="editor-field"><label>Contract</label><input id="contractEditorName" readonly></div><div class="editor-field"><label>Payout (aUEC)</label><input id="contractEditorPayout" inputmode="numeric" placeholder="e.g. 99500"></div></div>
    <div class="editor-body"><div class="ocr-panel"><textarea id="contractOcrText" placeholder="Paste contract text here, or use Read screenshot in the desktop app. Review extracted rows before saving."></textarea><div class="ocr-actions"><button class="btn" id="contractOcrRead" type="button">Read screenshot</button><button class="btn" id="contractOcrParse" type="button">Parse text</button></div></div><div class="editor-grid-head"><span>Pick up</span><span>Drop off</span><span>Commodity</span><span>SCU</span><span></span></div><div id="contractEditorRows"></div><button class="btn" id="contractEditorAdd" type="button">Add objective</button></div>
    <footer class="editor-footer"><div class="editor-help">Use this only when Game.log omits objective quantities. Corrections are stored locally and tied to this exact MissionId.</div><div class="editor-footer-group"><button class="btn red" id="contractEditorClear" type="button">Clear saved</button><button class="btn" id="contractEditorCancel" type="button">Cancel</button><button class="btn primary" id="contractEditorSave" type="button">Save details</button></div></footer>
  </section>
</div>
<div class="modal-backdrop" id="contractDeleteConfirm" aria-hidden="true">
  <section class="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="contractDeleteTitle" aria-describedby="contractDeleteMessage">
    <header class="confirm-head">
      <span class="confirm-icon" aria-hidden="true"><svg viewBox="0 0 640 640" focusable="false"><path d="M232.7 69.9L224 96L128 96C110.3 96 96 110.3 96 128C96 145.7 110.3 160 128 160L512 160C529.7 160 544 145.7 544 128C544 110.3 529.7 96 512 96L416 96L407.3 69.9C402.9 56.8 390.7 48 376.9 48L263.1 48C249.3 48 237.1 56.8 232.7 69.9zM512 208L128 208L149.1 531.1C150.7 556.4 171.7 576 197 576L443 576C468.3 576 489.3 556.4 490.9 531.1L512 208z"/></svg></span>
      <div class="confirm-copy"><h3 id="contractDeleteTitle">Delete contract?</h3><p id="contractDeleteMessage">This removes the contract from the SCHT tracker view. It does not abandon or change the contract in Star Citizen.</p></div>
      <button class="confirm-close" id="contractDeleteClose" type="button" aria-label="Close confirmation"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg></button>
    </header>
    <div class="confirm-contract" id="contractDeleteName">Hauling contract</div>
    <footer class="confirm-footer"><button class="btn" id="contractDeleteCancel" type="button">Cancel</button><button class="btn red" id="contractDeleteConfirmBtn" type="button">Delete contract</button></footer>
  </section>
</div>
<div class="modal-backdrop" id="sessionResetConfirm" aria-hidden="true">
  <section class="confirm-modal" role="alertdialog" aria-modal="true" aria-labelledby="sessionResetTitle" aria-describedby="sessionResetMessage">
    <header class="confirm-head">
      <span class="confirm-icon" aria-hidden="true"><svg viewBox="0 0 640 640" focusable="false"><path d="M320 64C178.6 64 64 178.6 64 320C64 461.4 178.6 576 320 576C461.4 576 576 461.4 576 320C576 178.6 461.4 64 320 64zM296 184C296 170.7 306.7 160 320 160C333.3 160 344 170.7 344 184L344 344C344 357.3 333.3 368 320 368C306.7 368 296 357.3 296 344L296 184zM320 432C337.7 432 352 446.3 352 464C352 481.7 337.7 496 320 496C302.3 496 288 481.7 288 464C288 446.3 302.3 432 320 432z"/></svg></span>
      <div class="confirm-copy"><h3 id="sessionResetTitle">Reset this SCHT session?</h3><p id="sessionResetMessage">This clears tracked contracts, the loading checklist, the session timer, and saved contract corrections. The selected Game.log file is not changed.</p></div>
      <button class="confirm-close" id="sessionResetClose" type="button" aria-label="Close confirmation"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg></button>
    </header>
    <footer class="confirm-footer"><button class="btn" id="sessionResetCancel" type="button">Cancel</button><button class="btn red" id="sessionResetConfirmBtn" type="button">Reset session</button></footer>
  </section>
</div>
<!-- MANUAL_MAINTENANCE_REQUIRED: every user-facing feature or renamed control must update this guide, its screenshots when affected, docs/HELP_MANUAL_MAINTENANCE.md, and the manual regression test. -->
<div class="modal-backdrop" id="infoModal" aria-hidden="true">
  <section class="info-modal" role="dialog" aria-modal="true" aria-labelledby="infoTitle">
    <header class="info-head"><div class="info-title"><span class="info-icon" aria-hidden="true"><svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640"><path d="M320 576C461.4 576 576 461.4 576 320C576 178.6 461.4 64 320 64C178.6 64 64 178.6 64 320C64 461.4 178.6 576 320 576zM320 240C302.3 240 288 254.3 288 272C288 285.3 277.3 296 264 296C250.7 296 240 285.3 240 272C240 227.8 275.8 192 320 192C364.2 192 400 227.8 400 272C400 319.2 364 339.2 344 346.5L344 350.3C344 363.6 333.3 374.3 320 374.3C306.7 374.3 296 363.6 296 350.3L296 342.2C296 321.7 310.8 307 326.1 302C332.5 299.9 339.3 296.5 344.3 291.7C348.6 287.5 352 281.7 352 272.1C352 254.4 337.7 240.1 320 240.1zM288 432C288 414.3 302.3 400 320 400C337.7 400 352 414.3 352 432C352 449.7 337.7 464 320 464C302.3 464 288 449.7 288 432z"/></svg></span><div><h3 id="infoTitle">SCHT Help & User Guide</h3><small>Quick start, dashboard, loading board, OCR, corrections, and exports</small></div></div><button class="editor-close" id="infoClose" type="button" aria-label="Close help window"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg></button></header>
    <div class="info-body" id="infoBody">
      <div class="guide-shell">
        <nav class="guide-nav" aria-label="User guide sections">
          <div class="guide-nav-title">User guide</div>
          <a id="guideQuickStartLink" href="#guideQuickStart"><span>1</span>Quick start</a>
          <a href="#guideDashboard"><span>2</span>Dashboard</a>
          <a href="#guideLogistics"><span>3</span>Loading board</a>
          <a href="#guideCorrections"><span>4</span>OCR & corrections</a>
          <a href="#guideMenus"><span>5</span>Menus & data</a>
          <a href="#guideTroubleshooting"><span>6</span>Troubleshooting</a>
        </nav>
        <main class="guide-content">
          <article class="guide-hero">
            <span class="guide-kicker">Normal workflow</span>
            <h4>Choose the log once → Start Watch → keep a new contract open while OCR reads it → load cargo from the Logistics Board → complete the contract in Star Citizen.</h4>
            <p>SCHT reads the selected <strong>Game.log</strong>, keeps its own local checklist and corrections, and never changes the game log or your in-game contracts.</p>
          </article>

          <section class="guide-section" id="guideQuickStart">
            <div class="guide-section-head"><span class="guide-section-number">1</span><div><h4>Start tracking</h4><p>The three primary buttons cover the everyday workflow.</p></div></div>
            <div class="guide-note"><strong>Recommended installation:</strong> use <strong>SCHT-Setup</strong> so Windows can uninstall the app and remove its local SCHT data cleanly. The installed or portable SCHT.exe already includes Python; players do not install Python separately.</div>
            <ol class="guide-steps">
              <li><strong>Choose Log</strong> only when the displayed Game.log path is wrong or you use another Star Citizen installation.</li>
              <li><strong>Scan Log</strong> reads the selected file immediately and rebuilds the current tracker view.</li>
              <li><strong>Start Watch</strong> begins live monitoring. The same button becomes <strong>Stop Watch</strong> while monitoring is active.</li>
              <li>Leave <strong>Automatic OCR</strong> enabled in Settings. After accepting a hauling contract, keep its contract page open until the SCHT notification says the import finished or needs review.</li>
              <li>Start the session timer from the first accepted mission or from now. Use <strong>Pause / Play</strong> without clearing any contracts.</li>
            </ol>
            <div class="guide-note warning"><strong>Do not switch away from the newly accepted contract too early.</strong> OCR needs the contract details and Primary Objectives to remain visible during capture.</div>
            <figure class="guide-figure compact"><button class="guide-image-button" type="button" data-guide-image="/assets/help/toolbar.jpg" data-guide-caption="Primary toolbar: Choose Log, Scan Log, Start/Stop Watch, Share, Settings, and Help."><img src="/assets/help/toolbar.jpg" alt="SCHT primary toolbar controls" loading="lazy"></button><figcaption>Primary toolbar. Click any guide image to enlarge it.</figcaption></figure>
          </section>

          <section class="guide-section" id="guideDashboard">
            <div class="guide-section-head"><span class="guide-section-number">2</span><div><h4>Read the dashboard</h4><p>Session information stays on the left; contracts and profit metrics stay in the main area.</p></div></div>
            <div class="guide-action-grid">
              <div class="guide-action"><strong>Session cards</strong><span>Accepted and completed contracts, total profit, mission profit per hour, and session profit per hour.</span></div>
              <div class="guide-action"><strong>Contract Log</strong><span>Grouped pickup/drop-off rows with commodity, SCU, payout, elapsed duration, rank, and current status.</span></div>
              <div class="guide-action"><strong>Filters and search</strong><span>Show all, active, completed, or closed contracts; search by commodity, location, or status.</span></div>
              <div class="guide-action"><strong>Edit and delete icons</strong><span>Edit repairs tracker data. Delete only removes the contract from SCHT; it does not abandon or change it in Star Citizen.</span></div>
            </div>
            <figure class="guide-figure"><button class="guide-image-button" type="button" data-guide-image="/assets/help/dashboard.jpg" data-guide-caption="Dashboard overview with session timer, statistics, Contract Log, filters, and live status."><img src="/assets/help/dashboard.jpg" alt="SCHT dashboard overview" loading="lazy"></button><figcaption>Dashboard overview with live statistics and grouped contract rows.</figcaption></figure>
          </section>

          <section class="guide-section" id="guideLogistics">
            <div class="guide-section-head"><span class="guide-section-number">3</span><div><h4>Use the Logistics Board and overlay</h4><p>The board turns accepted cargo objectives into a practical loading checklist.</p></div></div>
            <ol class="guide-steps">
              <li>Follow the <strong>Next</strong> line for the suggested pickup, commodity, destination, and SCU.</li>
              <li>Check each cargo item after it is loaded. Progress synchronizes between the main board and the overlay.</li>
              <li><strong>Hide loaded</strong> removes completed checklist items from view; <strong>Clear checks</strong> resets only the checklist.</li>
              <li>For a shared multi-pickup contract, SCHT shows the shared total but leaves per-location SCU blank when the game does not split the quantity.</li>
              <li>Open the compact overlay for use over Star Citizen. Its gear menu controls opacity, resize lock, position lock, and always-on-top behavior.</li>
            </ol>
            <div class="guide-media-grid">
              <div class="guide-media-card"><h5>Logistics Board</h5><button class="guide-image-button" type="button" data-guide-image="/assets/help/logistics_board.jpg" data-guide-caption="Logistics Board with grouped pickup and drop-off cards, loaded checks, shared totals, and next-action guidance."><img src="/assets/help/logistics_board.jpg" alt="SCHT Logistics Board" loading="lazy"></button><p>Each location keeps a consistent card width; cargo checks are stored locally.</p></div>
              <div class="guide-media-card"><h5>Hauling overlay</h5><button class="guide-image-button" type="button" data-guide-image="/assets/help/overlay.jpg" data-guide-caption="Compact hauling overlay and its window settings."><img src="/assets/help/overlay.jpg" alt="SCHT hauling overlay with settings" loading="lazy"></button><p>Drag the header to move it. Resize from the edges unless size lock is enabled.</p></div>
            </div>
          </section>

          <section class="guide-section" id="guideCorrections">
            <div class="guide-section-head"><span class="guide-section-number">4</span><div><h4>Review OCR and correct a contract</h4><p>Game.log remains authoritative, but screenshots can fill details the log does not contain.</p></div></div>
            <ol class="guide-steps">
              <li>When SCHT reports <strong>Contract needs review</strong>, open the pencil icon beside that contract.</li>
              <li>Use <strong>Read screenshot</strong> and select a clear contract screenshot, or paste recognized contract text and choose <strong>Parse text</strong>.</li>
              <li>Verify payout, pickup, drop-off, commodity, and SCU before saving. Add or remove objective rows when needed.</li>
              <li>For a shared-total multi-pickup contract, keep the total on the existing shared row and leave the other pickup SCU fields blank; do not invent a split.</li>
              <li><strong>Clear saved</strong> removes only your local correction and lets SCHT return to parsed Game.log/OCR data.</li>
            </ol>
            <div class="guide-note">Manual corrections are tied to the exact MissionId, so two procedurally generated contracts with similar names remain separate.</div>
            <figure class="guide-figure"><button class="guide-image-button" type="button" data-guide-image="/assets/help/contract_editor.jpg" data-guide-caption="Contract editor with payout, screenshot OCR, text parsing, route rows, shared quantity handling, and save controls."><img src="/assets/help/contract_editor.jpg" alt="SCHT contract editor" loading="lazy"></button><figcaption>Contract editor for OCR review and MissionId-specific corrections.</figcaption></figure>
          </section>

          <section class="guide-section" id="guideMenus">
            <div class="guide-section-head"><span class="guide-section-number">5</span><div><h4>Share, settings, and data safety</h4><p>Secondary actions are grouped into the icon menus.</p></div></div>
            <div class="guide-action-grid">
              <div class="guide-action"><strong>Export as CSV</strong><span>Spreadsheet-friendly contract rows for sorting, calculation, or later analysis.</span></div>
              <div class="guide-action"><strong>Export as HTML</strong><span>A formatted standalone report suitable for viewing or sharing.</span></div>
              <div class="guide-action"><strong>Automatic OCR</strong><span>Keep enabled for normal use. Disable only for troubleshooting or a deliberate manual-entry workflow.</span></div>
              <div class="guide-action"><strong>Reset session</strong><span>Clears SCHT contracts, checklist, timer, and saved corrections for the session. The selected Game.log file is not changed.</span></div>
            </div>
            <div class="guide-note danger"><strong>Reset session is destructive inside SCHT.</strong> Use it only when you intentionally want a clean tracker session; a confirmation appears before anything is cleared.</div>
            <div class="guide-media-grid compact">
              <div class="guide-media-card"><h5>Settings</h5><button class="guide-image-button" type="button" data-guide-image="/assets/help/settings_menu.jpg" data-guide-caption="Settings menu with Automatic OCR and Reset session."><img src="/assets/help/settings_menu.jpg" alt="SCHT settings menu" loading="lazy"></button></div>
              <div class="guide-media-card"><h5>Share</h5><button class="guide-image-button" type="button" data-guide-image="/assets/help/share_menu.jpg" data-guide-caption="Share menu with CSV and HTML export choices."><img src="/assets/help/share_menu.jpg" alt="SCHT share menu" loading="lazy"></button></div>
            </div>
          </section>

          <section class="guide-section" id="guideTroubleshooting">
            <div class="guide-section-head"><span class="guide-section-number">6</span><div><h4>Quick troubleshooting</h4><p>Try the smallest corrective step before resetting the session.</p></div></div>
            <div class="guide-troubleshooting">
              <div class="guide-trouble"><strong>No contracts appear</strong><p>Verify the Game.log path, select the correct file with Choose Log, click Scan Log, then start live Watch.</p></div>
              <div class="guide-trouble"><strong>Automatic OCR did not run</strong><p>Confirm it is enabled, Star Citizen is the foreground app, and the accepted contract page stayed open during capture.</p></div>
              <div class="guide-trouble"><strong>OCR is incomplete or wrong</strong><p>Open the contract editor, use a clear full contract screenshot, review every route row, and save only verified values.</p></div>
              <div class="guide-trouble"><strong>Export seems inactive</strong><p>Choose CSV or HTML from Share, select a save location in the desktop dialog, and check the SCHT notification for success or an error.</p></div>
              <div class="guide-trouble"><strong>Overlay will not move or resize</strong><p>Open the overlay gear menu and turn off Lock size or Lock position as required.</p></div>
              <div class="guide-trouble"><strong>Tracker data looks stale</strong><p>Use Scan Log first. Reset session is the last resort because it clears local checklist and correction state.</p></div>
            </div>
          </section>
        </main>
      </div>
    </div>
    <footer class="info-footer"><small id="infoVersion">SCHT v1.5.66</small><button class="btn primary" id="infoDone" type="button">Close</button></footer>
    <div class="guide-lightbox" id="guideLightbox" aria-hidden="true"><button class="guide-lightbox-close" id="guideLightboxClose" type="button" aria-label="Close enlarged image"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg></button><div class="guide-lightbox-frame"><img id="guideLightboxImage" alt=""><p id="guideLightboxCaption"></p></div></div>
  </section>
</div>
<div class="toast toast-info" id="toast" role="alert" aria-live="polite"><span class="toast-message" id="toastMessage"></span><button class="toast-close" id="toastClose" type="button" aria-label="Close message"><svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg></button></div>
<script>
const $=id=>document.getElementById(id);
const esc=s=>(s??"").toString().replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const clsStatus=s=>{s=(s||'').toLowerCase();if(s.includes('complete'))return'completed';if(s.includes('abandon')||s.includes('fail')||s.includes('cancel'))return'abandoned';if(s.includes('accept'))return'accepted';return''};
const STATUS_SVGS=Object.freeze({
  completed:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M480 96C515.3 96 544 124.7 544 160L544 480C544 515.3 515.3 544 480 544L160 544C124.7 544 96 515.3 96 480L96 160C96 124.7 124.7 96 160 96L480 96zM438 209.7C427.3 201.9 412.3 204.3 404.5 215L285.1 379.2L233 327.1C223.6 317.7 208.4 317.7 199.1 327.1C189.8 336.5 189.7 351.7 199.1 361L271.1 433C276.1 438 283 440.5 289.9 440C296.8 439.5 303.3 435.9 307.4 430.2L443.3 243.2C451.1 232.5 448.7 217.5 438 209.7z"/></svg>`,
  accepted:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M160 96L480 96C515.3 96 544 124.7 544 160L544 480C544 515.3 515.3 544 480 544L160 544C124.7 544 96 515.3 96 480L96 160C96 124.7 124.7 96 160 96z"/></svg>`,
  denied:`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M160 96C124.7 96 96 124.7 96 160L96 480C96 515.3 124.7 544 160 544L480 544C515.3 544 544 515.3 544 480L544 160C544 124.7 515.3 96 480 96L160 96zM231 231C240.4 221.6 255.6 221.6 264.9 231L319.9 286L374.9 231C384.3 221.6 399.5 221.6 408.8 231C418.1 240.4 418.2 255.6 408.8 264.9L353.8 319.9L408.8 374.9C418.2 384.3 418.2 399.5 408.8 408.8C399.4 418.1 384.2 418.2 374.9 408.8L319.9 353.8L264.9 408.8C255.5 418.2 240.3 418.2 231 408.8C221.7 399.4 221.6 384.2 231 374.9L286 319.9L231 264.9C221.6 255.5 221.6 240.3 231 231z"/></svg>`
});
const LOCATION_SVGS=Object.freeze({
  pickup:`<svg class="route-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M342.6 73.4C330.1 60.9 309.8 60.9 297.3 73.4L137.3 233.4C124.8 245.9 124.8 266.2 137.3 278.7C149.8 291.2 170.1 291.2 182.6 278.7L288 173.3L288 544C288 561.7 302.3 576 320 576C337.7 576 352 561.7 352 544L352 173.3L457.4 278.7C469.9 291.2 490.2 291.2 502.7 278.7C515.2 266.2 515.2 245.9 502.7 233.4L342.7 73.4z"/></svg>`,
  dropoff:`<svg class="route-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M297.4 566.6C309.9 579.1 330.2 579.1 342.7 566.6L502.7 406.6C515.2 394.1 515.2 373.8 502.7 361.3C490.2 348.8 469.9 348.8 457.4 361.3L352 466.7L352 96C352 78.3 337.7 64 320 64C302.3 64 288 78.3 288 96L288 466.7L182.6 361.3C170.1 348.8 149.8 348.8 137.3 361.3C124.8 373.8 124.8 394.1 137.3 406.6L297.3 566.6z"/></svg>`
});
const EDIT_CONTRACT_SVG=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><path d="M535.6 85.7C513.7 63.8 478.3 63.8 456.4 85.7L432 110.1L529.9 208L554.3 183.6C576.2 161.7 576.2 126.3 554.3 104.4L535.6 85.7zM236.4 305.7C230.3 311.8 225.6 319.3 222.9 327.6L193.3 416.4C190.4 425 192.7 434.5 199.1 441C205.5 447.5 215 449.7 223.7 446.8L312.5 417.2C320.7 414.5 328.2 409.8 334.4 403.7L496 241.9L398.1 144L236.4 305.7zM160 128C107 128 64 171 64 224L64 480C64 533 107 576 160 576L416 576C469 576 512 533 512 480L512 384C512 366.3 497.7 352 480 352C462.3 352 448 366.3 448 384L448 480C448 497.7 433.7 512 416 512L160 512C142.3 512 128 497.7 128 480L128 224C128 206.3 142.3 192 160 192L256 192C273.7 192 288 177.7 288 160C288 142.3 273.7 128 256 128L160 128z"/></svg>`;
const DELETE_CONTRACT_SVG=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><path d="M232.7 69.9L224 96L128 96C110.3 96 96 110.3 96 128C96 145.7 110.3 160 128 160L512 160C529.7 160 544 145.7 544 128C544 110.3 529.7 96 512 96L416 96L407.3 69.9C402.9 56.8 390.7 48 376.9 48L263.1 48C249.3 48 237.1 56.8 232.7 69.9zM512 208L128 208L149.1 531.1C150.7 556.4 171.7 576 197 576L443 576C468.3 576 489.3 556.4 490.9 531.1L512 208z"/></svg>`;
const statusIcon=s=>{s=(s||'').toUpperCase();if(s==='COMPLETED')return STATUS_SVGS.completed;if(['ABANDONED','FAILED','CANCELLED','DENIED','REJECTED'].includes(s))return STATUS_SVGS.denied;if(s==='ACCEPTED')return STATUS_SVGS.accepted;return STATUS_SVGS.accepted};
const statusSubline=(status,count)=>{status=(status||'').toUpperCase();const cargo=count===1?'1 cargo row':count+' cargo rows';if(status==='COMPLETED')return cargo+' · paid';if(['ABANDONED','FAILED','CANCELLED','DENIED','REJECTED'].includes(status))return cargo+' · closed';return cargo+' · active'};
let cache=null,refreshing=false,busy=false,toastTimer=null,editorGroup=null,editorContractedBy='',deleteMissionId='',deleteReturnFocus=null,resetReturnFocus=null,infoReturnFocus=null,guideImageReturnFocus=null;
const CONTRACT_FILTER_KEY='sc-hauling-contract-filter-v1';
const HIDE_LOADED_KEY='sc-hauling-hide-loaded-v1';
let contractFilter=(()=>{try{return localStorage.getItem(CONTRACT_FILTER_KEY)||'all'}catch(_e){return'all'}})();
let hideLoaded=(()=>{try{return localStorage.getItem(HIDE_LOADED_KEY)==='true'}catch(_e){return false}})();
function hideToast(){const t=$('toast');t.classList.remove('show')}
function toastTone(message,tone){
  if(tone)return tone;
  const text=String(message||'').toLowerCase();
  if(text.includes('could not')||text.includes('cannot')||text.includes('failed')||text.includes('error')||text.includes('requires'))return'error';
  if(text.includes('review')||text.includes('paste')||text.includes('try ')||text.includes('waiting')||text.includes('select'))return'info';
  return'success';
}
function showToast(message,tone=''){const t=$('toast'),m=$('toastMessage');const kind=toastTone(message,tone);m.textContent=message||'Action failed';t.classList.remove('toast-success','toast-info','toast-error');t.classList.add('toast-'+kind,'show');clearTimeout(toastTimer);toastTimer=setTimeout(hideToast,12000)}
function setShareMenu(open,focusFirst=false){const menu=$('shareMenu'),button=$('shareBtn');const visible=!!open;if(visible)setSettingsMenu(false);menu.classList.toggle('open',visible);button.setAttribute('aria-expanded',visible?'true':'false');if(visible&&focusFirst)setTimeout(()=>menu.querySelector('[data-export]')?.focus(),0)}
function setSettingsMenu(open,focusFirst=false){const menu=$('settingsMenu'),button=$('settingsBtn');const visible=!!open;if(visible)setShareMenu(false);menu.classList.toggle('open',visible);button.setAttribute('aria-expanded',visible?'true':'false');if(visible&&focusFirst)setTimeout(()=>$('autoOcrBtn')?.focus(),0)}
function closeTopMenus(){setShareMenu(false);setSettingsMenu(false)}
function openGuideImage(button){if(!button)return;guideImageReturnFocus=button;const src=button.dataset.guideImage||button.querySelector('img')?.src||'';const caption=button.dataset.guideCaption||button.querySelector('img')?.alt||'SCHT guide image';$('guideLightboxImage').src=src;$('guideLightboxImage').alt=caption;$('guideLightboxCaption').textContent=caption;const viewer=$('guideLightbox');viewer.classList.add('open');viewer.setAttribute('aria-hidden','false');setTimeout(()=>$('guideLightboxClose').focus(),0)}
function closeGuideImage(restoreFocus=true){const viewer=$('guideLightbox');viewer.classList.remove('open');viewer.setAttribute('aria-hidden','true');$('guideLightboxImage').removeAttribute('src');const focusTarget=guideImageReturnFocus;guideImageReturnFocus=null;if(restoreFocus&&focusTarget&&document.contains(focusTarget))setTimeout(()=>focusTarget.focus(),0)}
function openInfoWindow(){closeTopMenus();infoReturnFocus=document.activeElement;const version=cache?.version||'1.5.66';$('infoVersion').textContent='SCHT v'+version;const modal=$('infoModal');modal.classList.add('open');modal.setAttribute('aria-hidden','false');$('infoBody').scrollTop=0;setTimeout(()=>$('guideQuickStartLink').focus(),0)}
function closeInfoWindow(){if($('guideLightbox').classList.contains('open'))closeGuideImage(false);const modal=$('infoModal');modal.classList.remove('open');modal.setAttribute('aria-hidden','true');const focusTarget=infoReturnFocus;infoReturnFocus=null;if(focusTarget&&document.contains(focusTarget))setTimeout(()=>focusTarget.focus(),0)}
function setBusy(value){busy=value;document.querySelectorAll('[data-action]').forEach(b=>b.disabled=value)}
async function action(name){if(busy)return;setBusy(true);try{const path=$('logPath').value;const r=await fetch('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:name,log_path:path})});const j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||'Action failed');render(j.state||await fetchState())}catch(e){showToast(e.message||String(e),'error')}finally{setBusy(false);if(cache)updateControls(cache)}}
async function fetchState(){const r=await fetch('/api/state',{cache:'no-store'});if(!r.ok)throw new Error('Local server returned '+r.status);return r.json()}
document.querySelectorAll('[data-action]').forEach(b=>b.addEventListener('click',()=>action(b.dataset.action)));
let desktopBridgeReady=false,desktopBridgeMode='none';
function applyMainWindowStatus(status){if(!status)return;const maximized=!!status.maximized;document.body.classList.toggle('main-maximized',maximized);const button=$('mainMaxBtn');button.title=maximized?'Restore':'Maximize';button.setAttribute('aria-label',button.title)}
async function mainWindowCommand(apiName,actionName){
  try{
    let result=null;
    if(typeof window.pywebview?.api?.[apiName]==='function')result=await window.pywebview.api[apiName]();
    else if(desktopBridgeReady){const r=await fetch('/api/desktop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:actionName})});const j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||'Window command failed');result=j.status}
    else throw new Error('Desktop window controls are available only in the standalone app.');
    applyMainWindowStatus(result);return result;
  }catch(error){showToast(error.message||String(error),'error');return null}
}
async function refreshMainWindowStatus(){if(!desktopBridgeReady)return;await mainWindowCommand('get_main_window_status','main_window_status')}
function setDesktopBridgeReady(ready,mode='none'){
  desktopBridgeReady=!!ready;desktopBridgeMode=desktopBridgeReady?mode:'none';
  document.body.classList.toggle('desktop-mode',desktopBridgeReady);
  const overlay=$('openOverlayBtn');
  overlay.disabled=!desktopBridgeReady;
  overlay.textContent=desktopBridgeReady?'Open overlay':'Desktop only';
  overlay.title=desktopBridgeReady?'Open the always-on-top loading overlay':'Start the standalone desktop app to use the overlay';
  document.querySelectorAll('.main-window-btn').forEach(button=>button.disabled=!desktopBridgeReady);
  if(cache)$('version').textContent='v'+cache.version+(desktopBridgeReady?'':' · diagnostic browser');
  if(desktopBridgeReady)setTimeout(refreshMainWindowStatus,0);
}
async function probeDesktopBridge(){
  if(window.pywebview?.api?.open_overlay){setDesktopBridgeReady(true,'native');return true}
  try{
    const r=await fetch('/api/runtime',{cache:'no-store'});
    const j=await r.json();
    setDesktopBridgeReady(!!j.desktop,j.desktop?'loopback':'none');
    return !!j.desktop;
  }catch(_e){setDesktopBridgeReady(false,'none');return false}
}
$('mainMinBtn').addEventListener('click',event=>{event.preventDefault();event.stopPropagation();mainWindowCommand('minimize_main_window','minimize_main_window')});
$('mainMaxBtn').addEventListener('click',event=>{event.preventDefault();event.stopPropagation();mainWindowCommand('toggle_main_maximize','toggle_main_maximize')});
$('mainCloseBtn').addEventListener('click',event=>{event.preventDefault();event.stopPropagation();mainWindowCommand('close_main_window','close_main_window')});
$('mainDragRegion').addEventListener('pointerdown',event=>{if(event.button!==0||!desktopBridgeReady||event.detail>1)return;event.preventDefault();event.stopPropagation();if(typeof window.pywebview?.api?.begin_main_move==='function'){window.pywebview.api.begin_main_move().then(applyMainWindowStatus).catch(error=>showToast(error.message||String(error),'error'))}else{fetch('/api/desktop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'begin_main_move'})}).then(r=>r.json()).then(j=>{if(!j.ok)throw new Error(j.error||'Move failed');applyMainWindowStatus(j.status)}).catch(error=>showToast(error.message||String(error),'error'))}});
$('mainDragRegion').addEventListener('dblclick',event=>{event.preventDefault();mainWindowCommand('toggle_main_maximize','toggle_main_maximize')});
document.querySelectorAll('.main-resize-handle[data-resize]').forEach(handle=>{handle.addEventListener('pointerdown',event=>{if(event.button!==0||document.body.classList.contains('main-maximized')||!desktopBridgeReady)return;event.preventDefault();event.stopPropagation();const direction=handle.dataset.resize;if(typeof window.pywebview?.api?.begin_main_resize==='function'){window.pywebview.api.begin_main_resize(direction).then(applyMainWindowStatus).catch(error=>showToast(error.message||String(error),'error'))}else{fetch('/api/desktop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'begin_main_resize',value:direction})}).then(r=>r.json()).then(j=>{if(!j.ok)throw new Error(j.error||'Resize failed');applyMainWindowStatus(j.status)}).catch(error=>showToast(error.message||String(error),'error'))}})});
window.addEventListener('pywebviewready',probeDesktopBridge);
setTimeout(probeDesktopBridge,250);
setTimeout(probeDesktopBridge,1200);
$('browseBtn').addEventListener('click',async()=>{
  const button=$('browseBtn');button.disabled=true;
  try{
    if(window.pywebview?.api?.browse_log){
      const result=await window.pywebview.api.browse_log();
      if(!result?.ok)throw new Error(result?.error||'Browse dialog failed');
      if(result.path){$('logPath').value=result.path;await action('set_path')}
    }else if(desktopBridgeReady){
      const r=await fetch('/api/desktop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'browse_log'})});
      const j=await r.json();
      if(!r.ok||!j.ok)throw new Error(j.error||'Browse dialog failed');
      const result=j.status;
      if(!result?.ok)throw new Error(result?.error||'Browse dialog failed');
      if(result.path){$('logPath').value=result.path;await action('set_path')}
    }else{
      await action('browse');
    }
  }catch(e){showToast(e.message||String(e),'error')}finally{button.disabled=false}
});
async function browserExport(kind){
  const endpoint=kind==='csv'?'/export.csv':'/export.html';
  const filename=kind==='csv'?'sc_hauling_manifest.csv':'sc_hauling_manifest.html';
  const response=await fetch(endpoint,{cache:'no-store'});
  if(!response.ok)throw new Error('Export failed with status '+response.status);
  const blob=await response.blob();
  const url=URL.createObjectURL(blob);const link=document.createElement('a');link.href=url;link.download=filename;link.style.display='none';document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1200);
  return{ok:true,path:filename,browser_download:true};
}
async function nativeExport(kind,button=null){
  const apiName=kind==='csv'?'export_csv_file':'export_html_file';
  const label=kind.toUpperCase();
  if(button)button.disabled=true;
  showToast('Preparing '+label+' export…','info');
  try{
    let result;
    if(desktopBridgeReady){
      const response=await fetch('/api/desktop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:apiName})});
      const payload=await response.json();
      if(!response.ok||!payload.ok)throw new Error(payload.error||'Export dialog failed');
      result=payload.status;
    }else if(window.pywebview?.api?.[apiName]){
      result=await window.pywebview.api[apiName]();
    }else{
      result=await browserExport(kind);
    }
    if(!result?.ok)throw new Error(result?.error||'Export failed');
    if(result.cancelled)showToast(label+' export cancelled.','info');
    else if(result.browser_download)showToast(label+' download started.','success');
    else showToast(label+' saved to '+result.path,'success');
  }finally{if(button)button.disabled=false}
}
$('shareBtn').addEventListener('click',event=>{event.preventDefault();event.stopPropagation();setShareMenu(!$('shareMenu').classList.contains('open'),true)});
$('settingsBtn').addEventListener('click',event=>{event.preventDefault();event.stopPropagation();setSettingsMenu(!$('settingsMenu').classList.contains('open'),true)});
document.querySelectorAll('#shareMenu [data-export]').forEach(button=>button.addEventListener('click',event=>{event.preventDefault();event.stopPropagation();setShareMenu(false);nativeExport(button.dataset.export,button).catch(e=>showToast(e.message||String(e),'error'))}));
function openSessionResetConfirm(){setSettingsMenu(false);resetReturnFocus=$('resetBtn');const modal=$('sessionResetConfirm');modal.classList.add('open');modal.setAttribute('aria-hidden','false');setTimeout(()=>$('sessionResetCancel').focus(),0)}
function closeSessionResetConfirm(){const modal=$('sessionResetConfirm');modal.classList.remove('open');modal.setAttribute('aria-hidden','true');const focusTarget=resetReturnFocus;resetReturnFocus=null;if(focusTarget&&document.contains(focusTarget))setTimeout(()=>focusTarget.focus(),0)}
async function confirmSessionReset(){closeSessionResetConfirm();await action('reset')}
$('resetBtn').addEventListener('click',openSessionResetConfirm);
$('sessionResetClose').addEventListener('click',closeSessionResetConfirm);$('sessionResetCancel').addEventListener('click',closeSessionResetConfirm);$('sessionResetConfirmBtn').addEventListener('click',confirmSessionReset);
$('sessionResetConfirm').addEventListener('pointerdown',event=>{if(event.target===$('sessionResetConfirm'))closeSessionResetConfirm()});
$('infoBtn').addEventListener('click',openInfoWindow);
document.addEventListener('pointerdown',event=>{if($('shareMenu').classList.contains('open')&&!$('shareMenuWrap').contains(event.target))setShareMenu(false);if($('settingsMenu').classList.contains('open')&&!$('settingsMenuWrap').contains(event.target))setSettingsMenu(false)});
$('logPath').addEventListener('change',()=>action('set_path'));
$('search').addEventListener('input',()=>cache&&renderContracts(cache));
$('sort').addEventListener('change',()=>cache&&renderContracts(cache));
$('contractFilters').addEventListener('click',event=>{const button=event.target.closest('.filter-btn[data-filter]');if(!button)return;contractFilter=button.dataset.filter||'all';try{localStorage.setItem(CONTRACT_FILTER_KEY,contractFilter)}catch(_e){}if(cache)renderContracts(cache)});
const CONTRACT_LOG_HEIGHT_KEY='sc-hauling-contract-log-height-v1';
function contractLogMaxHeight(){const viewport=$('appViewport')?.clientHeight||window.innerHeight||720;return Math.max(340,Math.min(760,viewport-250))}
function applyContractLogHeight(value){const panel=$('contractPanel');if(!panel)return 398;const height=Math.round(Math.max(280,Math.min(contractLogMaxHeight(),Number(value)||398)));panel.style.setProperty('--contract-log-height',height+'px');return height}
function storedContractLogHeight(){try{return Number(localStorage.getItem(CONTRACT_LOG_HEIGHT_KEY)||398)}catch(_e){return 398}}
applyContractLogHeight(storedContractLogHeight());
const contractResizer=$('contractResizer');
if(contractResizer){let startY=null,startHeight=0;const finish=event=>{if(startY===null)return;const height=applyContractLogHeight(startHeight+event.clientY-startY);try{localStorage.setItem(CONTRACT_LOG_HEIGHT_KEY,String(height))}catch(_e){}startY=null;contractResizer.classList.remove('active');document.body.classList.remove('resizing-contract-log')};contractResizer.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();event.stopPropagation();startY=event.clientY;startHeight=$('contractPanel').getBoundingClientRect().height;contractResizer.classList.add('active');document.body.classList.add('resizing-contract-log');contractResizer.setPointerCapture(event.pointerId)});contractResizer.addEventListener('pointermove',event=>{if(startY===null)return;event.preventDefault();applyContractLogHeight(startHeight+event.clientY-startY)});contractResizer.addEventListener('pointerup',finish);contractResizer.addEventListener('pointercancel',finish)}
const LOGISTICS_HEIGHT_KEY='sc-hauling-logistics-height-v1';
function logisticsMaxHeight(){const viewport=$('appViewport')?.clientHeight||window.innerHeight||720;return Math.max(240,Math.min(620,viewport-220))}
function applyLogisticsHeight(value){const panel=$('logisticsPanel');if(!panel)return 260;const height=Math.round(Math.max(190,Math.min(logisticsMaxHeight(),Number(value)||260)));panel.style.setProperty('--logistics-height',height+'px');return height}
function storedLogisticsHeight(){try{return Number(localStorage.getItem(LOGISTICS_HEIGHT_KEY)||260)}catch(_e){return 260}}
applyLogisticsHeight(storedLogisticsHeight());
const logisticsResizer=$('logisticsResizer');
if(logisticsResizer){let startY=null,startHeight=0;const finish=event=>{if(startY===null)return;const height=applyLogisticsHeight(startHeight+event.clientY-startY);try{localStorage.setItem(LOGISTICS_HEIGHT_KEY,String(height))}catch(_e){}startY=null;logisticsResizer.classList.remove('active');document.body.classList.remove('resizing-logistics-board')};logisticsResizer.addEventListener('pointerdown',event=>{if(event.button!==0)return;event.preventDefault();event.stopPropagation();startY=event.clientY;startHeight=$('logisticsPanel').getBoundingClientRect().height;logisticsResizer.classList.add('active');document.body.classList.add('resizing-logistics-board');logisticsResizer.setPointerCapture(event.pointerId)});logisticsResizer.addEventListener('pointermove',event=>{if(startY===null)return;event.preventDefault();applyLogisticsHeight(startHeight+event.clientY-startY)});logisticsResizer.addEventListener('pointerup',finish);logisticsResizer.addEventListener('pointercancel',finish)}
window.addEventListener('resize',()=>{applyContractLogHeight($('contractPanel')?.getBoundingClientRect().height||storedContractLogHeight());applyLogisticsHeight($('logisticsPanel')?.getBoundingClientRect().height||storedLogisticsHeight())});
function statusMatchesFilter(group){const status=String(group.status||'').toUpperCase();if(contractFilter==='active')return status==='ACCEPTED';if(contractFilter==='completed')return status==='COMPLETED';if(contractFilter==='closed')return ['ABANDONED','FAILED','CANCELLED','DENIED','REJECTED'].includes(status);return true}
function updateFilterButtons(){document.querySelectorAll('.filter-btn[data-filter]').forEach(button=>button.classList.toggle('active',(button.dataset.filter||'all')===contractFilter))}
function updateControls(data){if(busy)return;const watching=!!data.watching;const watch=$('watchBtn');watch.disabled=false;watch.dataset.action=watching?'stop_watch':'watch';watch.textContent=watching?'Stop Watch':'Start Watch';watch.title=watching?'Stop monitoring Game.log':'Start monitoring Game.log for new contract events';watch.classList.toggle('primary',!watching);watch.classList.toggle('red',watching);watch.classList.toggle('active',watching);const auto=!!data.ocr?.auto_enabled;const autoButton=$('autoOcrBtn');autoButton.setAttribute('aria-pressed',auto?'true':'false');autoButton.title='Auto OCR '+(auto?'on':'off')+' · '+(data.ocr?.status||'');$('autoOcrToggle').classList.toggle('on',auto);$('autoOcrHelp').textContent=auto?'Enabled · capture newly accepted contracts automatically':'Disabled · add screenshots from the contract editor when needed';$('timerToggle').textContent=data.timer_state==='running'?'Pause':data.timer_state==='paused'?'Resume':'Pause / Play'}
function groupText(g){return JSON.stringify(g).toLowerCase()}
function firstObjective(g){return(g.objectives&&g.objectives[0])||{pickup:'',dropoff:'',commodity:'',scu:''}}
function sortedGroups(groups){const mode=$('sort').value;const statusRank={ACCEPTED:0,COMPLETED:1,ABANDONED:2,FAILED:2,CANCELLED:2};const text=(v)=>String(v||'').toLowerCase();return groups.slice().sort((a,b)=>{const ao=firstObjective(a),bo=firstObjective(b);if(mode==='accepted_new')return(b.accepted_epoch||0)-(a.accepted_epoch||0);if(mode==='accepted_old')return(a.accepted_epoch||0)-(b.accepted_epoch||0);if(mode==='payout')return(b.payout_value||0)-(a.payout_value||0);if(mode==='duration')return(b.duration_seconds||0)-(a.duration_seconds||0);if(mode==='pickup')return text(ao.pickup).localeCompare(text(bo.pickup));if(mode==='dropoff')return text(ao.dropoff).localeCompare(text(bo.dropoff));if(mode==='commodity')return text(ao.commodity).localeCompare(text(bo.commodity));return(statusRank[a.status]??9)-(statusRank[b.status]??9)||(b.accepted_epoch||0)-(a.accepted_epoch||0)})}
function renderContracts(data){
  const all=data.groups||[];
  const filter=($('search').value||'').trim().toLowerCase();
  updateFilterButtons();
  const groups=sortedGroups(all.filter(g=>statusMatchesFilter(g)).filter(g=>!filter||groupText(g).includes(filter)));
  const cargoRows=groups.reduce((n,g)=>n+Math.max(1,(g.objectives||[]).length),0);
  const filtered=filter||contractFilter!=='all';
  $('contractCount').textContent=groups.length+(groups.length===1?' contract':' contracts')+' · '+cargoRows+' cargo '+(cargoRows===1?'row':'rows')+(filtered?' filtered':'');
  const html=[];
  for(const g of groups){
    const objectives=(g.objectives&&g.objectives.length?g.objectives:[{pickup:'',dropoff:'',commodity:'',scu:''}]);
    const n=objectives.length;
    objectives.forEach((o,i)=>{
      const first=i===0,last=i===n-1;
      const cl=[clsStatus(g.status),first?'group-start':'',last?'group-end':''].filter(Boolean).join(' ');
      const span=` rowspan="${n}"`;
      const payout=g.payout?`<span class="metric-card"><span class="metric-main">${esc(g.payout)}</span><span class="metric-unit">AUEC</span></span>`:'<span class="empty-value" title="Not emitted by Game.log">Unknown</span>';
      const duration=g.duration?`<span class="metric-card"><span class="duration-value">${esc(g.duration)}</span><span class="metric-unit">elapsed</span></span>`:'<span class="empty-value">—</span>';
      const rank=g.rank?`<span class="rank-chip">${esc(g.rank)}</span>`:'<span class="empty-value">—</span>';
      const commodity=o.commodity||'—';
      const scu=o.scu||'Unknown';
      const aggregateScu=!!g.aggregate_quantity;
      const scuCell=aggregateScu
        ?(first?`<td${span} class="scu-cell contract-cell"><span class="scu-stack shared-scu-stack"><strong>${esc(g.aggregate_scu||'Unknown')}${g.aggregate_scu?` SCU`:''}</strong>${g.aggregate_scu?`<small>shared</small>`:''}</span></td>`:'')
        :`<td class="scu-cell"><span class="scu-stack"><strong>${esc(scu)}</strong>${scu==='Unknown'?'':`<small>SCU</small>`}</span></td>`;
      const actions=g.mission_id?`<span class="contract-actions"><button class="contract-action edit${g.needs_review?' review':''}" type="button" data-contract-action="edit" data-mission-id="${esc(g.mission_id)}" title="${g.needs_review?'Enter missing contract details':'Edit contract details'}" aria-label="Edit contract details">${EDIT_CONTRACT_SVG}</button><button class="contract-action delete" type="button" data-contract-action="delete" data-mission-id="${esc(g.mission_id)}" title="Delete contract" aria-label="Delete contract">${DELETE_CONTRACT_SVG}</button></span>`:'';
      html.push(`<tr class="${cl}">${first?`<td${span} class="contract-cell status-cell"><span class="status-wrap"><span class="status-pill"><span class="status-icon">${statusIcon(g.status)}</span><span class="status-copy"><span class="status-line"><strong>${esc(g.status)}</strong>${actions}</span><small>${esc(statusSubline(g.status,n))}</small></span></span></span></td>`:''}<td class="location-cell pickup-cell" title="${esc(o.pickup)}"><span class="route-location pickup-route">${LOCATION_SVGS.pickup}<span class="location-text">${esc(o.pickup)||'—'}</span></span></td><td class="location-cell dropoff-cell" title="${esc(o.dropoff)}"><span class="route-location dropoff-route">${LOCATION_SVGS.dropoff}<span class="location-text">${esc(o.dropoff)||'—'}</span></span></td><td class="commodity-cell" title="${esc(o.commodity)}"><span class="commodity-chip" style="--commodity-color:${commodityBoxColor(o.commodity)}">${CARGO_BOX_SVG}<span class="commodity-name">${esc(commodity)}</span></span></td>${scuCell}${first?`<td${span} class="contract-cell metric-cell payout-cell">${payout}</td><td${span} class="contract-cell metric-cell duration-cell">${duration}</td><td${span} class="contract-cell rank-cell">${rank}</td>`:''}</tr>`);
    });
  }
  $('rows').innerHTML=html.join('')||'<tr class="empty-row"><td colspan="8">No hauling contracts match the current view</td></tr>';
}
function editorRowHtml(objective={}){
  const scope=objective.quantity_scope==='aggregate'?'aggregate':'per_route';
  return `<div class="editor-row" data-quantity-scope="${scope}"><input data-field="pickup" value="${esc(objective.pickup||'Everus Harbor')}" placeholder="Pick up"><input data-field="dropoff" value="${esc(objective.dropoff||'')}" placeholder="Drop off"><input data-field="commodity" value="${esc(objective.commodity||'')}" placeholder="Commodity"><input data-field="scu" inputmode="decimal" value="${esc(objective.scu||'')}" placeholder="SCU"><button class="editor-remove" type="button" title="Remove objective" aria-label="Remove objective">${DELETE_CONTRACT_SVG}</button></div>`;
}
function openContractEditor(group){
  if(!group||!group.mission_id){showToast('This contract has no MissionId and cannot be edited safely.','error');return}
  editorGroup=group;
  editorContractedBy=group.contracted_by||'';
  $('contractEditorTitle').textContent=group.needs_review?'Complete missing contract details':'Edit contract details';
  $('contractEditorMission').textContent='MissionId · '+group.mission_id;
  $('contractEditorName').value=group.mission||'Hauling contract';
  $('contractEditorPayout').value=group.payout_value?String(group.payout_value):'';
  $('contractOcrText').value='';
  $('contractEditorRows').innerHTML=(group.objectives&&group.objectives.length?group.objectives:[{}]).map(editorRowHtml).join('');
  $('contractEditor').classList.add('open');$('contractEditor').setAttribute('aria-hidden','false');
  setTimeout(()=>$('contractEditorPayout').focus(),0);
}
function closeContractEditor(){editorGroup=null;editorContractedBy='';$('contractEditor').classList.remove('open');$('contractEditor').setAttribute('aria-hidden','true')}
function contractEditorObjectives(){return [...$('contractEditorRows').querySelectorAll('.editor-row')].map(row=>({pickup:row.querySelector('[data-field="pickup"]').value.trim(),dropoff:row.querySelector('[data-field="dropoff"]').value.trim(),commodity:row.querySelector('[data-field="commodity"]').value.trim(),scu:row.querySelector('[data-field="scu"]').value.trim(),quantity_scope:row.dataset.quantityScope==='aggregate'?'aggregate':'per_route'})).filter(o=>o.pickup||o.dropoff||o.commodity||o.scu)}
function applyOcrParsed(parsed){
  if(!parsed)return;
  if(parsed.text&&$('contractOcrText'))$('contractOcrText').value=parsed.text;
  if(parsed.payout&&(!$('contractEditorPayout').value||$('contractEditorPayout').value==='0'))$('contractEditorPayout').value=String(parsed.payout);
  if(parsed.contracted_by)editorContractedBy=parsed.contracted_by;
  const rows=parsed.objectives||[];
  if(rows.length){
    $('contractEditorRows').innerHTML=rows.map(editorRowHtml).join('');
    const expected=Number(parsed.expected_objectives||0);
    const aggregateRows=rows.filter(row=>row.quantity_scope==='aggregate');
    const found=Number(parsed.found_objectives||rows.filter(row=>row.scu).length||rows.length);
    const coverage=aggregateRows.length>1
      ?` OCR found one shared quantity across ${aggregateRows.length} pickup locations.`
      :(expected&&found<expected?` OCR found only ${found} of ${expected} expected objectives; do not save until ${expected-found===1?'the missing route is':'all missing routes are'} added.`:`OCR found ${found} objective${found===1?'':'s'}.`);
    const payoutNote=parsed.payout?` Payout ${Number(parsed.payout).toLocaleString()} aUEC was also read.`:' Payout was not recognized; enter it manually if the field stays empty.';
    showToast(`${coverage}${payoutNote} Review before saving.`,expected&&rows.length<expected?'error':'info');
  }else{
    showToast('No objective rows found. Try cropping the contract panel or paste the text manually.','info');
  }
}
async function runContractOcr(actionName){
  if(!editorGroup?.mission_id)return;
  const payload={action:actionName,mission_id:editorGroup.mission_id,objectives:contractEditorObjectives()};
  if(actionName==='parse_text')payload.text=$('contractOcrText').value.trim();
  if(actionName==='parse_text'&&!payload.text){showToast('Paste contract text first.','info');return}
  setBusy(true);
  try{
    const r=await fetch('/api/ocr',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const j=await r.json();
    if(j.cancelled)return;
    if(!r.ok||!j.ok)throw new Error(j.error||'OCR failed');
    applyOcrParsed(j.parsed);
  }catch(e){showToast(e.message||String(e),'error')}finally{setBusy(false)}
}
async function submitContractEditor(actionName){
  if(!editorGroup?.mission_id)return;
  const payload={action:actionName,mission_id:editorGroup.mission_id};
  if(actionName==='save'){payload.payout=$('contractEditorPayout').value.trim();payload.objectives=contractEditorObjectives();payload.contracted_by=editorContractedBy}
  setBusy(true);
  try{const r=await fetch('/api/contracts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||'Could not save contract details');closeContractEditor();render(j.state||await fetchState());showToast(actionName==='clear'?'Saved correction cleared':'Contract details saved','success')}
  catch(e){showToast(e.message||String(e),'error')}finally{setBusy(false)}
}
function openDeleteConfirm(missionId,group,trigger){
  if(!missionId)return;
  deleteMissionId=missionId;deleteReturnFocus=trigger||document.activeElement;
  $('contractDeleteName').textContent=group?.mission||'Hauling contract';
  const modal=$('contractDeleteConfirm');modal.classList.add('open');modal.setAttribute('aria-hidden','false');
  setTimeout(()=>$('contractDeleteCancel').focus(),0);
}
function closeDeleteConfirm(){
  const modal=$('contractDeleteConfirm');modal.classList.remove('open');modal.setAttribute('aria-hidden','true');
  deleteMissionId='';const focusTarget=deleteReturnFocus;deleteReturnFocus=null;
  if(focusTarget&&document.contains(focusTarget))setTimeout(()=>focusTarget.focus(),0);
}
async function confirmDeleteContract(){
  if(busy)return;const missionId=deleteMissionId;if(!missionId)return;
  closeDeleteConfirm();setBusy(true);
  try{
    const r=await fetch('/api/contracts',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',mission_id:missionId})});
    const j=await r.json();
    if(!r.ok||!j.ok)throw new Error(j.error||'Could not delete contract');
    render(j.state||await fetchState());
    showToast('Contract deleted','success');
  }catch(e){showToast(e.message||String(e),'error')}finally{setBusy(false)}
}
$('rows').addEventListener('click',event=>{const button=event.target.closest('.contract-action[data-contract-action][data-mission-id]');if(!button||!cache)return;const group=(cache.groups||[]).find(g=>g.mission_id===button.dataset.missionId);if(button.dataset.contractAction==='edit'){if(group)openContractEditor(group);return}if(button.dataset.contractAction==='delete')openDeleteConfirm(button.dataset.missionId,group,button)});
$('contractEditorRows').addEventListener('click',event=>{const button=event.target.closest('.editor-remove');if(!button)return;button.closest('.editor-row')?.remove();if(!$('contractEditorRows').children.length)$('contractEditorRows').innerHTML=editorRowHtml({})});
$('contractEditorAdd').addEventListener('click',()=>{$('contractEditorRows').insertAdjacentHTML('beforeend',editorRowHtml({pickup:'Everus Harbor',quantity_scope:editorGroup?.aggregate_quantity?'aggregate':'per_route'}))});
$('contractOcrRead').addEventListener('click',()=>runContractOcr('read_screenshot'));
$('contractOcrParse').addEventListener('click',()=>runContractOcr('parse_text'));
$('contractEditorClose').addEventListener('click',closeContractEditor);$('contractEditorCancel').addEventListener('click',closeContractEditor);$('contractEditorSave').addEventListener('click',()=>submitContractEditor('save'));$('contractEditorClear').addEventListener('click',()=>submitContractEditor('clear'));
$('toastClose').addEventListener('click',hideToast);
$('infoClose').addEventListener('click',closeInfoWindow);$('infoDone').addEventListener('click',closeInfoWindow);$('infoBody').addEventListener('click',event=>{const button=event.target.closest('.guide-image-button[data-guide-image]');if(button){event.preventDefault();openGuideImage(button)}});$('guideLightboxClose').addEventListener('click',()=>closeGuideImage());$('guideLightbox').addEventListener('pointerdown',event=>{if(event.target===$('guideLightbox'))closeGuideImage()});
$('contractDeleteClose').addEventListener('click',closeDeleteConfirm);$('contractDeleteCancel').addEventListener('click',closeDeleteConfirm);$('contractDeleteConfirmBtn').addEventListener('click',confirmDeleteContract);
$('infoModal').addEventListener('pointerdown',event=>{if(event.target===$('infoModal'))closeInfoWindow()});
$('contractDeleteConfirm').addEventListener('pointerdown',event=>{if(event.target===$('contractDeleteConfirm'))closeDeleteConfirm()});
$('contractEditor').addEventListener('pointerdown',event=>{if(event.target===$('contractEditor'))closeContractEditor()});window.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if($('shareMenu').classList.contains('open')){setShareMenu(false);$('shareBtn').focus();return}if($('settingsMenu').classList.contains('open')){setSettingsMenu(false);$('settingsBtn').focus();return}if($('guideLightbox').classList.contains('open')){closeGuideImage();return}if($('infoModal').classList.contains('open')){closeInfoWindow();return}if($('sessionResetConfirm').classList.contains('open')){closeSessionResetConfirm();return}if($('contractDeleteConfirm').classList.contains('open')){closeDeleteConfirm();return}if($('contractEditor').classList.contains('open'))closeContractEditor()});
// Editable Star Citizen commodity cargo-box palette. Values represent the visible crate/body colour in game.
// Keep commodity keys lower-case; aliases can be added without touching the renderer.
const COMMODITY_BOX_COLORS=Object.freeze({
  'hydrogen':'#8fd9f2',
  'quartz':'#6f78c9',
  'carbon':'#6d727c',
  'aluminum':'#aeb7c3','aluminium':'#aeb7c3',
  'copper':'#bd7048','iron':'#8a9099','titanium':'#c8ced8','tungsten':'#626975',
  'beryl':'#69b98d','gold':'#d3ab43','diamond':'#c8edf5',
  'agricium':'#72bd83','laranite':'#7664bd','taranite':'#bd5964',
  'medical supplies':'#d85b69','agricultural supplies':'#77ad63',
  'processed food':'#c99954','distilled spirits':'#9760ae',
  'scrap':'#866654','waste':'#726451'
});
function commodityBoxColor(name){return COMMODITY_BOX_COLORS[String(name||'').trim().toLowerCase()]||'#8b90a5'}
const CARGO_BOX_SVG=`<svg class="cargo-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 640 640" aria-hidden="true" focusable="false"><!--!Font Awesome Free v7.3.0 by @fontawesome - https://fontawesome.com License - https://fontawesome.com/license/free Copyright 2026 Fonticons, Inc.--><path d="M431.1 80C451.8 80 471.2 90 483.2 106.8L532.1 175.3C539.8 186.1 544 199.2 544 212.5L544 480C544 515.3 515.3 544 480 544L160 544L153.5 543.7C121.2 540.4 96 513.1 96 480L96 212.5C96 200.8 99.2 189.4 105.2 179.5L107.9 175.3L156.8 106.8C167.3 92.1 183.5 82.6 201.2 80.5L208.9 80L431 80zM344 192L465.3 192L431 144L343.9 144L343.9 192zM174.7 192L296 192L296 144L208.9 144L174.6 192z"/></svg>`;
const CHECKLIST_STORAGE_KEY='sc-hauling-loading-checklist-v1';
function loadChecklist(){try{const parsed=JSON.parse(localStorage.getItem(CHECKLIST_STORAGE_KEY)||'{}');return parsed&&typeof parsed==='object'?parsed:{}}catch(_e){return{}}}
let loadingChecklist=loadChecklist();
function saveChecklist(){try{localStorage.setItem(CHECKLIST_STORAGE_KEY,JSON.stringify(loadingChecklist))}catch(_e){}}
async function syncChecklist(action,id='',checked=false){try{const payload={action};if(id)payload.id=id;if(action==='set')payload.checked=!!checked;await fetch('/api/checklist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})}catch(_e){}}
function formatChecklistScu(value){value=Number(value||0);return Number.isInteger(value)?String(value):value.toFixed(1).replace(/\.0$/,'')}
function logisticsItemId(it,mode,fixed,column){return String(it.id||[mode,fixed,column,it.commodity,it.scu].join('|'))}
function checklistStats(items){const loaded=items.filter(it=>loadingChecklist[it.id]);return{total:items.length,loaded:loaded.length,totalScu:items.reduce((n,it)=>n+Number(it.scu||0),0),loadedScu:loaded.reduce((n,it)=>n+Number(it.scu||0),0)}}
function sharedChecklistStats(sections){let total=0,loaded=0;(sections||[]).forEach(section=>{if((section.mode||'')!=='aggregate_pickups')return;let loads=Array.isArray(section.shared_loads)?section.shared_loads:[];if(!loads.length){const ids=[];(section.columns||[]).forEach(col=>(col.items||[]).forEach(it=>ids.push(logisticsItemId(it,section.mode||'direct',section.fixed_location||'—',col.location||'—'))));loads=[{scu_value:Number(section.shared_scu_value??section.shared_scu??section.total??0),item_ids:ids}]}loads.forEach(load=>{const value=Number(load.scu_value??load.scu??0),ids=load.item_ids||[];if(!value)return;total+=value;if(ids.length&&ids.every(id=>loadingChecklist[id]))loaded+=value})});return{total,loaded}}
function updateChecklistHeader(items,sections){
  const stats=checklistStats(items),shared=sharedChecklistStats(sections),complete=stats.total>0&&stats.loaded===stats.total;
  $('checklistProgress').textContent=`${stats.loaded}/${stats.total} loaded`;
  $('checklistScu').textContent=`${formatChecklistScu(stats.loadedScu+shared.loaded)}/${formatChecklistScu(stats.totalScu+shared.total)} SCU`;
  $('checklistSummary').classList.toggle('complete',complete);
  $('clearChecklistBtn').disabled=stats.loaded===0;
  $('hideLoadedBtn').classList.toggle('active',hideLoaded);
  $('hideLoadedBtn').textContent=hideLoaded?'Show loaded':'Hide loaded';
}
function nextLogisticsItem(sections){for(const section of sections||[]){const mode=section.mode||'direct',fixed=section.fixed_location||'—';for(const col of section.columns||[]){for(const it of col.items||[]){const id=logisticsItemId(it,mode,fixed,col.location||'—');if(!loadingChecklist[id])return{section,mode,fixed,column:col,item:it,id}}}}return null}
function updateNextAction(sections){const el=$('nextAction');if(!(sections||[]).length){el.classList.remove('complete');el.innerHTML='<span><strong>Next:</strong> no active cargo</span><small>0 SCU</small>';return}const next=nextLogisticsItem(sections);if(!next){el.classList.add('complete');el.innerHTML='<span><strong>Next:</strong> all visible cargo is loaded</span><small>clear</small>';return}el.classList.remove('complete');if(next.mode==='aggregate_pickups'){const shared=next.section.shared_scu||next.section.total||'';el.innerHTML=`<span><strong>Next:</strong> collect ${esc(next.item.commodity)} at ${esc(next.column.location)} → ${esc(next.fixed)}</span><small>${esc(shared)} SCU shared</small>`;return}const label=next.mode==='single_dropoff'?'Pick up':'Load at';const destination=next.mode==='single_pickup'?` → ${next.column.location}`:next.mode==='single_dropoff'?` → ${next.fixed}`:` → ${next.column.location}`;el.innerHTML=`<span><strong>Next:</strong> ${esc(label)} ${esc(next.mode==='single_dropoff'?next.column.location:next.fixed)} · ${esc(next.item.commodity)}${esc(destination)}</span><small>${esc(next.item.scu)} SCU</small>`}
function renderLogistics(data){
  if(data?.checklist&&typeof data.checklist==='object'){loadingChecklist={...data.checklist};saveChecklist()}
  const lg=data.logistics||{};
  const sections=lg.sections||[];
  const count=Number(lg.active_objectives||0);
  const quantitySummary=lg.quantity_summary?.summary||'0 SCU known';
  const activeItems=[];
  sections.forEach(section=>(section.columns||[]).forEach(col=>(col.items||[]).forEach(it=>activeItems.push({id:logisticsItemId(it,section.mode||'direct',section.fixed_location||'—',col.location||'—'),scu:Number(it.scu_value??it.scu??0)}))));
  const validIds=new Set(activeItems.map(it=>it.id));
  let pruned=false;
  Object.keys(loadingChecklist).forEach(id=>{if(!validIds.has(id)){delete loadingChecklist[id];pruned=true}});
  if(pruned)saveChecklist();
  updateChecklistHeader(activeItems,sections);
  updateNextAction(sections);
  $('logisticsInfo').textContent=sections.length
    ? `${sections.length} ${sections.length===1?'route group':'route groups'} · ${count} active cargo ${count===1?'objective':'objectives'} · ${quantitySummary} · accepted only`
    : `No plannable cargo · ${quantitySummary}`;
  if(!sections.length){
    $('logisticsGroups').innerHTML='<div class="logistics-empty">No active cargo. Scan or accept a hauling contract to build the board.</div>';
    return;
  }
  $('logisticsGroups').innerHTML=sections.map(section=>{
    const mode=section.mode||'direct';
    const fixed=section.fixed_location||'—';
    let title='Pick up location';
    let desc='Direct route';
    if(mode==='single_pickup'){
      title='Pick up location (shared)';
      desc='Load outgoing cargo here, then sort it by destination';
    }else if(mode==='single_dropoff'){
      title='Drop off location (shared)';
      desc='Cargo from these pickups converges here';
    }else if(mode==='aggregate_pickups'){
      title='Drop off location (shared)';
      desc='Collect this commodity at the listed pickup locations';
    }
    const sectionItems=[];
    (section.columns||[]).forEach(col=>(col.items||[]).forEach(it=>sectionItems.push({id:logisticsItemId(it,mode,fixed,col.location||'—'),scu:Number(it.scu_value??it.scu??0)})));
    const sectionStats=checklistStats(sectionItems);
    const sectionComplete=sectionStats.total>0&&sectionStats.loaded===sectionStats.total;
    const sectionPercent=sectionStats.total?Math.round(sectionStats.loaded/sectionStats.total*100):0;
    const cards=(section.columns||[]).map(col=>{
      const allCardItems=(col.items||[]).map(it=>({raw:it,id:logisticsItemId(it,mode,fixed,col.location||'—'),scu:Number(it.scu_value??it.scu??0)}));
      const cardItems=hideLoaded?allCardItems.filter(entry=>!loadingChecklist[entry.id]):allCardItems;
      const cardStats=checklistStats(allCardItems);
      const cardComplete=cardStats.total>0&&cardStats.loaded===cardStats.total;
      const items=cardItems.map(entry=>{
        const it=entry.raw,checked=!!loadingChecklist[entry.id];
        const amount=String(it.scu||'').trim();
        const aria=amount?`Mark ${it.commodity} ${amount} SCU as loaded`:`Mark ${it.commodity} at ${col.location} as loaded`;
        return `<label class="item load-item ${clsStatus(it.status)}${checked?' is-loaded':''}" data-check-id="${esc(entry.id)}"><input class="load-check" type="checkbox" data-check-id="${esc(entry.id)}"${checked?' checked':''} aria-label="${esc(aria)}"><span class="check-box" aria-hidden="true"></span><span class="commodity-label"><span style="color:${commodityBoxColor(it.commodity)}">${CARGO_BOX_SVG}</span><span>${esc(it.commodity)}</span></span>${amount?`<b>${esc(amount)} SCU</b>`:''}</label>`;
      }).join('')||(hideLoaded&&cardComplete?'<div class="item" style="color:var(--muted);justify-content:center;margin-top:26px">Loaded</div>':'<div class="item" style="color:var(--muted);justify-content:center;margin-top:26px">—</div>');
      const cardQuantity=mode==='aggregate_pickups'?'SCU not split':`${formatChecklistScu(cardStats.loadedScu)} / ${formatChecklistScu(cardStats.totalScu)} SCU`;
      return `<article class="dest-card"><h4 title="${esc(col.location)}">${esc(col.location)}</h4><div class="items">${items}</div><div class="total${cardComplete?' complete':''}"><span class="loaded-count">${cardStats.loaded}/${cardStats.total} loaded</span><span class="loaded-scu">${esc(cardQuantity)}</span></div></article>`;
    }).join('');
    const totalCopy=mode==='aggregate_pickups'?`${section.total} SCU shared total`:`${section.total} SCU total`;
    const progressCopy=mode==='aggregate_pickups'?`${sectionStats.loaded}/${sectionStats.total} pickup locations loaded`:`${sectionStats.loaded}/${sectionStats.total} loaded · ${formatChecklistScu(sectionStats.loadedScu)}/${formatChecklistScu(sectionStats.totalScu)} SCU`;
    return `<div class="logistics-group ${esc(mode)}"><div class="pickup-card"><small>${esc(title)}</small><div class="loc">${esc(fixed)}</div><p>${esc(desc)} · ${esc(totalCopy)}</p><div class="section-check-progress${sectionComplete?' complete':''}"><div class="check-progress-track"><div class="check-progress-fill" style="--progress:${sectionPercent}%"></div></div><small>${esc(progressCopy)}</small></div></div><div class="destinations">${cards}</div></div>`;
  }).join('');
}
$('logisticsGroups').addEventListener('change',event=>{
  const input=event.target.closest('.load-check');
  if(!input)return;
  const id=input.dataset.checkId;
  if(!id)return;
  if(input.checked)loadingChecklist[id]=true;else delete loadingChecklist[id];
  saveChecklist();
  syncChecklist('set',id,!!loadingChecklist[id]);
  if(cache){cache.checklist={...loadingChecklist};renderLogistics(cache)};
});
$('clearChecklistBtn').addEventListener('click',()=>{
  loadingChecklist={};
  saveChecklist();
  syncChecklist('clear');
  if(cache){cache.checklist={};renderLogistics(cache)};
});
$('hideLoadedBtn').addEventListener('click',()=>{hideLoaded=!hideLoaded;try{localStorage.setItem(HIDE_LOADED_KEY,String(hideLoaded))}catch(_e){}if(cache)renderLogistics(cache)});
window.addEventListener('storage',event=>{
  if(event.key!==CHECKLIST_STORAGE_KEY)return;
  loadingChecklist=loadChecklist();
  if(cache){cache.checklist={...loadingChecklist};renderLogistics(cache)};
});
$('openOverlayBtn').addEventListener('click',async()=>{
  const button=$('openOverlayBtn');button.disabled=true;
  try{
    let status=null;
    if(window.pywebview?.api?.open_overlay){
      status=await window.pywebview.api.open_overlay();
      desktopBridgeMode='native';
    }else{
      const r=await fetch('/api/desktop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'open_overlay'})});
      const j=await r.json();
      if(!r.ok||!j.ok)throw new Error(j.error||'Native desktop controller is unavailable.');
      status=j.status;desktopBridgeMode='loopback';setDesktopBridgeReady(true,'loopback');
    }
    if(status?.error)throw new Error(status.error);showToast('Overlay opened in isolated process · Ctrl+Shift+O toggles it','success');
  }catch(e){
    await probeDesktopBridge();
    showToast('Could not open overlay: '+(e.message||e),'error');
  }finally{button.disabled=!desktopBridgeReady}
});
function render(data){cache=data;const versionText='v'+data.version+(desktopBridgeReady?'':' · diagnostic browser');$('version').textContent=versionText;const windowVersion=$('windowVersion');if(windowVersion)windowVersion.textContent='v'+data.version+' · cargo operations console';if(document.activeElement!==$('logPath'))$('logPath').value=data.log_path||'';$('accepted').textContent=data.stats.accepted;$('completed').textContent=data.stats.completed;$('profit').textContent=data.stats.profit;$('missionRate').textContent=data.stats.mission_rate;$('sessionRate').textContent=data.stats.session_rate;$('missionElapsed').textContent='mission elapsed '+data.stats.mission_elapsed;$('sessionElapsed').textContent='session elapsed '+data.stats.session_elapsed+' · '+data.timer_label.toLowerCase();$('timer').textContent=data.timer_elapsed;const stateClass=(data.timer_state||'stopped').replace('armed_first','waiting');$('timerState').textContent=data.timer_label;$('timerState').className='state '+stateClass;$('sCompleted').textContent=data.stats.completed+' completed';$('sAccepted').textContent=data.stats.accepted+' accepted';$('sProfit').textContent=data.stats.profit+' aUEC';$('sRate').textContent=data.stats.session_rate+' aUEC/hr';$('status').textContent=data.status||'Ready';$('lastScan').textContent=data.last_scan||'—';$('ocrStatus').textContent=data.ocr?.status||'Auto OCR ready';$('online').textContent=data.watching?'ONLINE':'IDLE';$('online').className=data.watching?'greenText':'blueText';$('footerRight').innerHTML=(data.watching?'<span class="greenText">● live feed active</span>':'<span>idle</span>')+' · '+esc(data.last_scan||'—');renderContracts(data);renderLogistics(data);updateControls(data)}
async function refresh(){if(refreshing||busy)return;refreshing=true;try{render(await fetchState())}catch(e){showToast('Cannot reach local tracker server: '+(e.message||e),'error')}finally{refreshing=false}}
refresh();setInterval(refresh,1000);
</script>
</body>
</html>'''


    class Handler(BaseHTTPRequestHandler):
        server_version = "SCHaulingWeb/1.5.66"

        def log_message(self, fmt, *args):
            # Keep terminal clean unless there is a debugging need.
            return

        def send_json(self, obj, code: int = 200):
            data = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/" or parsed.path == "/index.html":
                data = WEB_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path.startswith("/assets/help/"):
                asset_name = Path(urllib.parse.unquote(parsed.path)).name
                if asset_name not in HELP_IMAGE_ASSETS:
                    self.send_error(404)
                    return
                asset = bundled_resource_path("assets", "help", asset_name)
                if not asset.exists():
                    self.send_error(404)
                    return
                data = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path in ("/assets/sc_hauling_logo.png", "/assets/sc_hauling_logo_mark.png", "/favicon.png"):
                asset_name = "sc_hauling_logo_mark.png" if parsed.path.endswith("sc_hauling_logo_mark.png") else "sc_hauling_logo.png"
                asset = bundled_resource_path("assets", asset_name)
                if not asset.exists():
                    self.send_error(404)
                    return
                data = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path == "/overlay":
                data = OVERLAY_HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)
                return
            if parsed.path == "/api/runtime":
                controller = desktop_controller()
                self.send_json({
                    "desktop": controller is not None,
                    "overlay": controller is not None,
                    "version": APP_VERSION,
                })
                return
            if parsed.path == "/api/state":
                self.send_json(state.to_state())
                return
            if parsed.path == "/api/checklist":
                self.send_json({"ok": True, "checklist": state.checklist_snapshot()})
                return
            if parsed.path == "/export.csv":
                with state.lock:
                    import io
                    buf = io.StringIO()
                    writer = csv.DictWriter(buf, fieldnames=["Status", "Pick up location", "Drop off location", "Commodity", "SCU", "Payout", "Duration", "Rank", "Confidence", "Notes", "Mission", "Accepted At", "Completed At"])
                    writer.writeheader()
                    for row, _m in grouped_manifest_rows(state.missions, display_merge=True):
                        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
                    data = buf.getvalue().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=sc_hauling_manifest.csv")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data); return
            if parsed.path == "/export.html":
                with state.lock:
                    tmp = Path(tempfile.gettempdir()) / f"sc_hauling_manifest_{os.getpid()}.html"
                    export_html(state.missions, tmp, state.session_started, state.session_timer_elapsed())
                    data = tmp.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=sc_hauling_manifest.html")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers(); self.wfile.write(data); return
            self.send_error(404)

        def do_POST(self):
            if self.path not in ("/api/action", "/api/desktop", "/api/checklist", "/api/contracts", "/api/ocr"):
                self.send_error(404); return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                payload = json.loads(body or "{}")
                action = payload.get("action")
                if self.path == "/api/checklist":
                    if action == "set":
                        snapshot = state.set_checklist_item(payload.get("id") or "", bool(payload.get("checked")))
                    elif action == "clear":
                        snapshot = state.clear_checklist()
                    elif action == "replace":
                        snapshot = state.replace_checklist(payload.get("checklist") or {})
                    else:
                        raise ValueError(f"Unknown checklist action: {action}")
                    self.send_json({"ok": True, "checklist": snapshot})
                    return
                if self.path == "/api/contracts":
                    mission_id = payload.get("mission_id") or ""
                    if action == "save":
                        state.save_contract_override(
                            mission_id,
                            payload.get("payout"),
                            payload.get("objectives") or [],
                            payload.get("contracted_by") or "",
                        )
                    elif action == "clear":
                        state.clear_contract_override(mission_id)
                    elif action == "delete":
                        state.delete_contract(mission_id)
                    else:
                        raise ValueError(f"Unknown contract action: {action}")
                    self.send_json({"ok": True, "state": state.to_state()})
                    return
                if self.path == "/api/ocr":
                    hints = payload.get("objectives") or []
                    if action == "parse_text":
                        parsed = parse_contract_details_text(payload.get("text") or "", hints)
                        self.send_json({"ok": True, "parsed": parsed})
                        return
                    if action == "read_screenshot":
                        controller = desktop_controller()
                        if controller is None:
                            self.send_json({"ok": False, "error": "Screenshot OCR requires the standalone desktop app."}, code=409)
                            return
                        picked = controller.browse_ocr_image()
                        if not picked.get("ok"):
                            self.send_json({"ok": False, "error": picked.get("error") or "Could not select screenshot."}, code=500)
                            return
                        image_path = picked.get("path") or ""
                        if not image_path:
                            self.send_json({"ok": True, "cancelled": True})
                            return
                        with state.lock:
                            group = state._group_for_mission_id(payload.get("mission_id") or "")
                            expectation = ocr_objective_expectation(group) if group else {"confident": False, "objective_count": 0}
                        ocr_result = read_contract_image_ocr(
                            Path(image_path), hints, int(expectation.get("objective_count") or 0) or None
                        )
                        parsed = ocr_result.get("parsed") or {}
                        found = len(parsed.get("objectives") or [])
                        parsed["expected_objectives"] = int(expectation.get("objective_count") or 0)
                        parsed["objectives_complete"] = not expectation.get("confident") or found >= int(expectation.get("objective_count") or 0)
                        self.send_json({"ok": True, "parsed": parsed, "path": image_path})
                        return
                    raise ValueError(f"Unknown OCR action: {action}")
                if self.path == "/api/desktop":
                    controller = desktop_controller()
                    if controller is None:
                        self.send_json({"ok": False, "error": "The standalone desktop controller is not running."}, code=409)
                        return
                    actions = {
                        "open_overlay": controller.open_overlay,
                        "hide_overlay": controller.hide_overlay,
                        "toggle_overlay": controller.toggle_overlay,
                        "overlay_status": controller.get_overlay_status,
                        "set_overlay_opacity": lambda: controller.set_overlay_opacity(payload.get("value", 1.0)),
                        "set_overlay_size_locked": lambda: controller.set_overlay_size_locked(bool(payload.get("value"))),
                        "set_overlay_position_locked": lambda: controller.set_overlay_position_locked(bool(payload.get("value"))),
                        "set_overlay_on_top": lambda: controller.set_overlay_on_top(bool(payload.get("value"))),
                        "main_window_status": controller.get_main_window_status,
                        "begin_main_move": controller.begin_main_move,
                        "begin_main_resize": lambda: controller.begin_main_resize(payload.get("value", "")),
                        "minimize_main_window": controller.minimize_main_window,
                        "toggle_main_maximize": controller.toggle_main_maximize,
                        "close_main_window": controller.close_main_window,
                        "browse_log": controller.browse_log,
                        "browse_ocr_image": controller.browse_ocr_image,
                        "export_csv_file": controller.export_csv_file,
                        "export_html_file": controller.export_html_file,
                    }
                    handler = actions.get(action)
                    if handler is None:
                        raise ValueError(f"Unknown desktop action: {action}")
                    self.send_json({"ok": True, "status": handler()})
                    return
                if payload.get("log_path") is not None:
                    state.set_log_path(payload.get("log_path") or "")
                if action == "browse":
                    try:
                        import tkinter as tk
                        from tkinter import filedialog
                        root = tk.Tk(); root.withdraw(); root.attributes('-topmost', True)
                        fn = filedialog.askopenfilename(title="Select Game.log", filetypes=[("Game.log", "Game.log"), ("Log files", "*.log"), ("All files", "*.*")])
                        root.destroy()
                        if fn: state.set_log_path(fn)
                    except Exception as e:
                        raise RuntimeError(f"Browse dialog failed: {e}")
                elif action == "set_path":
                    pass
                elif action == "scan":
                    state.scan()
                elif action == "watch":
                    state.start_watch()
                elif action == "stop_watch":
                    state.stop_watch()
                elif action == "reset":
                    state.reset_session()
                elif action == "timer_first":
                    state.start_timer_first()
                elif action == "timer_now":
                    state.start_timer_now()
                elif action == "timer_toggle":
                    state.toggle_timer()
                elif action == "toggle_auto_ocr":
                    state.toggle_auto_ocr()
                else:
                    if action:
                        raise ValueError(f"Unknown action: {action}")
                self.send_json({"ok": True, "state": state.to_state()})
            except Exception as e:
                state.status = str(e)
                self.send_json({"ok": False, "error": str(e)}, code=400)

    # Bind to requested or next free port.
    last_err = None
    httpd = None
    chosen_port = port
    for candidate in range(port, port + 30):
        try:
            httpd = ThreadingHTTPServer((host, candidate), Handler)
            chosen_port = candidate
            break
        except OSError as e:
            last_err = e
    if httpd is None:
        raise RuntimeError(f"Could not bind local server: {last_err}")
    url = f"http://{host}:{chosen_port}/"
    print(f"{APP_NAME} {APP_VERSION} running at {url}")
    if port_callback is not None:
        port_callback(chosen_port)
    # Do not make desktop startup wait for parsing an existing (possibly very
    # large) Game.log. The first UI frame can render immediately and will refresh
    # automatically when this background preload completes.
    preload_thread = threading.Thread(
        target=preload_current_log,
        daemon=True,
        name="sc-hauling-preload",
    )
    preload_thread.start()
    print("Press Ctrl+C in this terminal to stop the local dashboard.")
    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard...")
    finally:
        state.stop_watch()
        httpd.server_close()





def run_app_window(default_log: Optional[str] = None, port: int = 8765) -> None:
    """Run the desktop dashboard; the Logistics Overlay is spawned separately."""
    try:
        import webview  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "The desktop runtime is not installed. Run build_exe.bat to create the standalone app, "
            "or install requirements-build.txt when launching from source."
        ) from exc

    import queue

    port_result = queue.Queue(maxsize=1)
    desktop_bridge = {}

    def server_target():
        try:
            run_web_dashboard(
                default_log,
                "127.0.0.1",
                port,
                False,
                port_callback=lambda chosen: port_result.put(("ok", chosen)),
                desktop_bridge=desktop_bridge,
            )
        except Exception as exc:
            try:
                port_result.put(("error", exc), block=False)
            except Exception:
                pass

    server_thread = threading.Thread(target=server_target, daemon=True, name="sc-hauling-local-server")
    server_thread.start()

    try:
        result, payload = port_result.get(timeout=12)
    except queue.Empty as exc:
        raise RuntimeError("Local dashboard did not start within 12 seconds.") from exc
    if result != "ok":
        raise RuntimeError(f"Local dashboard failed to start: {payload}")

    url = f"http://127.0.0.1:{int(payload)}"
    controller = OverlayProcessController(webview, url)
    desktop_bridge["controller"] = controller
    geometry = controller.main_window_geometry()
    _work_left, _work_top, work_w, work_h = controller._primary_work_area()
    min_window_size = (min(MAIN_WINDOW_HARD_MIN_WIDTH, work_w), min(MAIN_WINDOW_MIN_HEIGHT, work_h))
    window_kwargs = dict(
        title=APP_NAME,
        url=url + "/",
        js_api=controller,
        width=geometry["width"],
        height=geometry["height"],
        x=geometry["x"],
        y=geometry["y"],
        min_size=min_window_size,
        text_select=True,
        frameless=True,
        resizable=True,
        easy_drag=False,
        shadow=True,
        background_color="#0b0b12",
    )
    try:
        window = webview.create_window(**window_kwargs)
    except TypeError:
        window_kwargs.pop("x", None)
        window_kwargs.pop("y", None)
        window = webview.create_window(**window_kwargs)
    controller.attach_main_window(window)
    # The overlay is intentionally lazy-created by Open overlay. Creating a second
    # hidden WebView here made startup slow and could leave an invisible overlay
    # window/taskbar entry before the user requested it.
    storage_path = app_data_directory() / "webview"
    storage_path.mkdir(parents=True, exist_ok=True)
    try:
        webview.start(debug=False, private_mode=False, storage_path=str(storage_path))
    except TypeError:
        webview.start(debug=False)

# ---------------- CLI ----------------

def print_manifest(missions: Sequence[CargoMission]) -> None:
    rows = [r for r, _m in grouped_manifest_rows(missions, display_merge=True)]
    if not rows:
        print("No hauling rows detected.")
        return
    cols = ["Status", "Pick up location", "Drop off location", "Commodity", "SCU", "Payout", "Duration", "Rank", "Confidence", "Notes"]
    widths = {c: len(c) for c in cols}
    for row in rows:
        for c in cols:
            widths[c] = min(max(widths[c], len(str(row.get(c, "")))), 34)
    def fmt(row: dict) -> str:
        vals = []
        for c in cols:
            v = str(row.get(c, ""))
            if len(v) > widths[c]:
                v = v[: widths[c]-1] + "…"
            vals.append(v.ljust(widths[c]))
        return " | ".join(vals)
    print(fmt({c: c for c in cols}))
    print("-+-".join("-" * widths[c] for c in cols))
    for row in rows:
        print(fmt(row))


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=f"{APP_NAME} {APP_VERSION}")
    ap.add_argument("--version", action="version", version=f"SCHT {APP_VERSION}")
    ap.add_argument("--log", help="Path to Star Citizen Game.log")
    ap.add_argument("--no-gui", action="store_true", help="Run in terminal mode")
    ap.add_argument("--tk-gui", action="store_true", help="Use the legacy Tkinter GUI instead of the web/app dashboard")
    ap.add_argument("--browser", action="store_true", help="Diagnostic mode: open the local dashboard in the default browser (native overlay unavailable)")
    ap.add_argument("--port", type=int, default=8765, help="Local web dashboard port")
    ap.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically")
    ap.add_argument("--csv", help="Export CSV path")
    ap.add_argument("--html", help="Export HTML path")
    ap.add_argument("--tail-mb", type=int, default=2, help="How many MB from end of log to scan")
    ap.add_argument("--overlay-child", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--base-url", help=argparse.SUPPRESS)
    ap.add_argument("--parent-pid", type=int, help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.overlay_child:
        if not args.base_url:
            show_native_message("SC Hauling Overlay startup error", "Missing local tracker server URL.", error=True)
            return 2
        return run_overlay_child(args.base_url, args.parent_pid)

    if not args.no_gui:
        if args.tk_gui:
            run_gui(args.log)
        elif args.browser:
            run_web_dashboard(args.log, port=args.port, open_browser=not args.no_browser)
        else:
            guard = SingleInstanceGuard()
            if not guard.acquired:
                show_native_message(APP_NAME, "SC Hauling Log Tracker is already running.")
                guard.close()
                return 0
            try:
                run_app_window(args.log, port=args.port)
            except Exception as exc:
                show_native_message(f"{APP_NAME} startup error", str(exc), error=True)
                return 1
            finally:
                guard.close()
        return 0

    guessed = guess_sc_log_paths()
    p = Path(args.log) if args.log else (guessed[0] if guessed else None)
    if not p:
        ap.error("--log is required when Game.log cannot be auto-detected")
    if not p.exists():
        print(f"Log file not found: {p}", file=sys.stderr)
        return 2
    missions = parse_log_text(read_tail(p, max_bytes=args.tail_mb * 1024 * 1024))
    print_manifest(missions)
    cli_starts = [m.accepted_epoch() for m in missions]
    cli_starts = [x for x in cli_starts if x is not None]
    started_at_cli = min(cli_starts) if cli_starts else time.time()
    accepted, completed, total, mission_elapsed, mission_profit_hr, session_elapsed, session_profit_hr = session_stats(missions, started_at_cli)
    print(
        f"\nStats: {accepted} accepted; {completed} completed; "
        f"total profit {format_auec(total)} aUEC; "
        f"mission/hr {format_auec(int(mission_profit_hr))} aUEC/hr over {format_duration(mission_elapsed)}; "
        f"session/hr {format_auec(int(session_profit_hr))} aUEC/hr"
    )
    if args.csv:
        export_csv(missions, Path(args.csv))
        print(f"CSV exported: {args.csv}")
    if args.html:
        export_html(missions, Path(args.html), started_at_cli)
        print(f"HTML exported: {args.html}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
