"""Operational contract locations and capacity-aware hauling route planning.

This module deliberately has no knowledge of the Star Citizen mission bug.  It
receives already-filtered cargo operations and solves their pickup/delivery order.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Protocol, Sequence, Tuple


def normalize_location_name(value: str) -> str:
    text = " ".join(str(value or "").casefold().replace("–", "-").replace("—", "-").split())
    return "".join(ch for ch in text if ch.isalnum())


class LocationRepository(Protocol):
    def names(self) -> Sequence[str]: ...


class LocationAliasRepository(Protocol):
    def canonical_for_alias(self, value: str) -> Optional[str]: ...


class DistanceProvider(Protocol):
    def distance(self, origin: str, destination: str) -> Optional[float]: ...


@dataclass(frozen=True)
class LocationResolution:
    captured_name: str
    canonical_name: str = ""
    status: str = "unresolved"
    confidence: float = 0.0


class LocationSearchService:
    def __init__(self, repository: LocationRepository, aliases: Optional[LocationAliasRepository] = None,
                 fuzzy_threshold: float = 0.88):
        self.repository = repository
        self.aliases = aliases
        self.fuzzy_threshold = fuzzy_threshold

    def resolve(self, value: str) -> LocationResolution:
        captured = " ".join(str(value or "").split())
        if not captured or captured.casefold().startswith("unknown"):
            return LocationResolution(captured)
        names = list(self.repository.names())
        exact = next((name for name in names if name.casefold() == captured.casefold()), None)
        if exact:
            return LocationResolution(captured, exact, "exact", 1.0)
        if self.aliases:
            alias = self.aliases.canonical_for_alias(captured)
            if alias:
                return LocationResolution(captured, alias, "alias", 1.0)
        compact = normalize_location_name(captured)
        normalized = [name for name in names if normalize_location_name(name) == compact]
        if len(normalized) == 1:
            return LocationResolution(captured, normalized[0], "normalized", 0.98)
        scored = sorted(
            ((SequenceMatcher(None, compact, normalize_location_name(name)).ratio(), name) for name in names),
            reverse=True,
        )
        if scored and scored[0][0] >= self.fuzzy_threshold and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.05):
            return LocationResolution(captured, scored[0][1], "fuzzy", scored[0][0])
        return LocationResolution(captured)


class StaticLocationRepository:
    def __init__(self, values: Iterable[str]):
        self._names = tuple(dict.fromkeys(" ".join(str(v or "").split()) for v in values if str(v or "").strip()))

    def names(self) -> Sequence[str]:
        return self._names


class DictAliasRepository:
    def __init__(self, aliases: Optional[dict] = None):
        self.aliases = {normalize_location_name(k): str(v) for k, v in (aliases or {}).items()}

    def canonical_for_alias(self, value: str) -> Optional[str]:
        return self.aliases.get(normalize_location_name(value))


class CachedDistanceProvider:
    """Versioned local pairwise cache with an optional provider adapter.

    Cache reads remain available when the adapter is offline. Missing distances
    return None; callers may still build a deterministic unweighted route while
    clearly labelling its distance as unavailable.
    """
    def __init__(self, path: Path, upstream: Optional[DistanceProvider] = None):
        self.path = Path(path)
        self.upstream = upstream
        self.values: Dict[str, float] = {}
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if int(raw.get("version", 0)) == 1:
                self.values = {str(k): float(v) for k, v in (raw.get("distances") or {}).items()}
        except Exception:
            pass

    @staticmethod
    def _key(a: str, b: str) -> str:
        return "|".join(sorted((normalize_location_name(a), normalize_location_name(b))))

    def distance(self, origin: str, destination: str) -> Optional[float]:
        if normalize_location_name(origin) == normalize_location_name(destination):
            return 0.0
        key = self._key(origin, destination)
        if key in self.values:
            return self.values[key]
        if self.upstream:
            try:
                value = self.upstream.distance(origin, destination)
            except Exception:
                value = None
            if value is not None and math.isfinite(float(value)) and float(value) >= 0:
                self.values[key] = float(value)
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    self.path.write_text(json.dumps({"version": 1, "distances": self.values}, indent=2), encoding="utf-8")
                except OSError:
                    # Caching is an optimization only. A read-only or temporarily
                    # locked AppData folder must never abort route calculation.
                    pass
                return float(value)
        return None


@dataclass(frozen=True)
class CargoOperation:
    id: str
    contract_id: str
    commodity: str
    quantity: float
    pickup: str
    dropoff: str
    completed_pickup: bool = False
    completed_delivery: bool = False
    already_onboard: bool = False


@dataclass
class RouteStop:
    location: str
    pickups: List[CargoOperation] = field(default_factory=list)
    deliveries: List[CargoOperation] = field(default_factory=list)
    load_before: float = 0.0
    load_after: float = 0.0
    distance_from_previous: Optional[float] = None
    cumulative_distance: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
    user_waypoint: bool = False


@dataclass
class RoutePlan:
    stops: List[RouteStop]
    exact: bool
    valid: bool
    warnings: List[str] = field(default_factory=list)
    error: str = ""
    total_distance: Optional[float] = None
    input_hash: str = ""


def route_input_hash(operations: Sequence[CargoOperation], start: str, capacity: float,
                     required_locations: Sequence[str] = ()) -> str:
    payload = [start, float(capacity), sorted(set(required_locations)),
               [op.__dict__ for op in sorted(operations, key=lambda item: item.id)]]
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:20]


def _distance(provider: DistanceProvider, a: str, b: str) -> Tuple[float, bool]:
    value = provider.distance(a, b)
    return (float(value), True) if value is not None else (1.0, False)


def optimize_route(operations: Sequence[CargoOperation], start: str, capacity: float,
                   distances: DistanceProvider, exact_location_limit: int = 9,
                   time_limit_seconds: float = 1.5,
                   required_locations: Sequence[str] = (), visit_start: bool = False,
                   fixed_end: str = "") -> RoutePlan:
    """Solve a grouped pickup-and-delivery route deterministically.

    Exact search is used for at most ``exact_location_limit`` physical locations.
    Larger inputs use deterministic nearest-valid-stop selection. Both variants
    enforce precedence and capacity and group all feasible work at a location.
    """
    operations = [op for op in operations if not op.completed_delivery]
    required = frozenset(str(value) for value in required_locations if str(value).strip())
    fixed_end = str(fixed_end or "").strip()
    plan_hash = route_input_hash(operations, start, capacity, tuple(required))
    if not start.strip():
        return RoutePlan([], True, False, error="Choose a current/start location.", input_hash=plan_hash)
    if capacity <= 0:
        return RoutePlan([], True, False, error="Ship cargo capacity must be greater than zero.", input_hash=plan_hash)
    if any(op.quantity < 0 for op in operations):
        return RoutePlan([], True, False, error="Cargo quantities cannot be negative.", input_hash=plan_hash)
    oversized = [op for op in operations if op.quantity > capacity and not (op.already_onboard or op.completed_pickup)]
    if oversized:
        largest = max(op.quantity for op in oversized)
        return RoutePlan(
            [], True, False,
            error=f"A {largest:g} SCU cargo item exceeds the {capacity:g} SCU ship capacity.",
            input_hash=plan_hash,
        )
    if not operations and not required:
        return RoutePlan([], True, True, input_hash=plan_hash)

    onboard0 = frozenset(i for i, op in enumerate(operations) if (op.already_onboard or op.completed_pickup) and not op.completed_delivery)
    delivered0 = frozenset(i for i, op in enumerate(operations) if op.completed_delivery)
    if sum(operations[i].quantity for i in onboard0) > capacity + 1e-9:
        return RoutePlan([], True, False, error="Cargo already onboard exceeds ship capacity.", input_hash=plan_hash)
    locations = sorted({op.pickup for op in operations if not op.completed_pickup and not op.already_onboard} |
                       {op.dropoff for op in operations if not op.completed_delivery} | set(required),
                       key=lambda x: (normalize_location_name(x), x))
    deadline = time.monotonic() + max(0.05, time_limit_seconds)

    def visit(location: str, onboard: frozenset, delivered: frozenset):
        deliveries = tuple(i for i in sorted(onboard) if operations[i].dropoff == location)
        next_onboard = set(onboard) - set(deliveries)
        next_delivered = set(delivered) | set(deliveries)
        load = sum(operations[i].quantity for i in next_onboard)
        pickups = []
        for i, op in enumerate(operations):
            if i in next_onboard or i in next_delivered or op.completed_pickup or op.already_onboard or op.pickup != location:
                continue
            if load + op.quantity <= capacity + 1e-9:
                pickups.append(i); next_onboard.add(i); load += op.quantity
        return frozenset(next_onboard), frozenset(next_delivered), tuple(deliveries), tuple(pickups)

    target = len(operations)
    visited0 = frozenset({start} & set(required))
    initial_path = ()
    if visit_start:
        onboard0, delivered0, start_deliveries, start_pickups = visit(start, onboard0, delivered0)
        if start_deliveries or start_pickups or start in required:
            initial_path = ((start, start_deliveries, start_pickups, 0.0, True),)
    exact = len(locations) <= exact_location_limit
    best = None
    if exact:
        timed_out = False
        memo: Dict[Tuple[str, frozenset, frozenset, frozenset], float] = {}
        def search(current: str, onboard: frozenset, delivered: frozenset, visited: frozenset, cost: float, path: tuple):
            nonlocal best, timed_out
            if time.monotonic() > deadline:
                timed_out = True
                return
            if len(delivered) == target and required.issubset(visited):
                candidate = (cost, tuple(normalize_location_name(x[0]) for x in path), path)
                if best is None or candidate[:2] < best[:2]: best = candidate
                return
            key = (current, onboard, delivered, visited)
            if cost >= memo.get(key, float("inf")) - 1e-9: return
            memo[key] = cost
            candidates = []
            for loc in locations:
                no, nd, ds, ps = visit(loc, onboard, delivered)
                if not ds and not ps and (loc not in required or loc in visited): continue
                nv = visited | ({loc} if loc in required else set())
                if fixed_end and loc == fixed_end and (len(nd) != target or not required.issubset(nv)):
                    continue
                travel, known = _distance(distances, current, loc)
                candidates.append((travel, normalize_location_name(loc), loc, no, nd, nv, ds, ps, known))
            for travel, _key, loc, no, nd, nv, ds, ps, known in sorted(candidates):
                search(loc, no, nd, nv, cost + travel, path + ((loc, ds, ps, travel, known),))
        search(start, onboard0, delivered0, visited0, 0.0, initial_path)
        if timed_out:
            exact = False

    if best is None:
        current, onboard, delivered, visited, path, total = start, onboard0, delivered0, visited0, list(initial_path), 0.0
        guard = len(operations) * 4 + len(locations) * 3
        while (len(delivered) < target or not required.issubset(visited)) and guard > 0:
            guard -= 1; candidates = []
            for loc in locations:
                no, nd, ds, ps = visit(loc, onboard, delivered)
                if not ds and not ps and (loc not in required or loc in visited): continue
                nv = visited | ({loc} if loc in required else set())
                if fixed_end and loc == fixed_end and (len(nd) != target or not required.issubset(nv)):
                    continue
                travel, known = _distance(distances, current, loc)
                candidates.append((travel, normalize_location_name(loc), loc, no, nd, nv, ds, ps, known))
            if not candidates: break
            travel, _key, loc, onboard, delivered, visited, ds, ps, known = min(candidates)
            total += travel; path.append((loc, ds, ps, travel, known)); current = loc
        if len(delivered) != target or not required.issubset(visited):
            return RoutePlan([], exact, False, error="No capacity-safe pickup and delivery route could be produced.", input_hash=plan_hash)
        best = (total, (), tuple(path))

    load = sum(operations[i].quantity for i in onboard0)
    cumulative = 0.0; all_known = True; stops = []
    for loc, delivery_ids, pickup_ids, travel, known in best[2]:
        before = load
        delivered_qty = sum(operations[i].quantity for i in delivery_ids)
        pickup_qty = sum(operations[i].quantity for i in pickup_ids)
        load = load - delivered_qty + pickup_qty
        cumulative += travel; all_known = all_known and known
        stops.append(RouteStop(loc, [operations[i] for i in pickup_ids], [operations[i] for i in delivery_ids],
                               before, load, round(travel, 1) if known else None, round(cumulative, 1) if all_known else None,
                               [] if known else ["Travel distance unavailable; stop order uses unit-cost fallback."],
                               loc in required))
    warnings = [] if all_known else ["Some travel distances are unavailable; the route is feasible but not distance-optimal."]
    return RoutePlan(stops, exact, True, warnings=warnings,
                     total_distance=round(cumulative, 1) if all_known else None, input_hash=plan_hash)


def optimize_open_route(operations: Sequence[CargoOperation], distances: DistanceProvider,
                        exact_location_limit: int = 9, time_limit_seconds: float = 1.5,
                        required_locations: Sequence[str] = (), fixed_start: str = "",
                        fixed_end: str = "") -> RoutePlan:
    """Minimize an open pickup/delivery route without start or capacity inputs.

    The first and last stops are selected by the solver. Capacity is deliberately
    unbounded for this planning mode, while every cargo delivery still requires
    its pickup to have occurred earlier. Repeated visits remain possible for
    crossed dependencies such as A→B and B→A.
    """
    remaining = [operation for operation in operations if not operation.completed_delivery]
    fixed_start = str(fixed_start or "").strip()
    fixed_end = str(fixed_end or "").strip()
    if fixed_start and fixed_end and fixed_start == fixed_end:
        return RoutePlan([], True, False, error="Start and final locations must be different.")
    required = tuple(dict.fromkeys([
        *(str(value) for value in required_locations if str(value).strip()),
        *([fixed_start] if fixed_start else []), *([fixed_end] if fixed_end else []),
    ]))
    plan_hash = route_input_hash(remaining, fixed_start or "<free-start>", 0.0, required)
    if not remaining and not required:
        return RoutePlan([], True, True, input_hash=plan_hash)

    # A zero-cost virtual origin lets the existing precedence solver choose the
    # first real stop itself. It is equivalent to evaluating every legal start,
    # but spends the entire search budget on one exact open-route search.
    virtual_origin = "\x00free-route-origin"

    class OpenRouteDistances:
        def distance(self, origin: str, destination: str) -> Optional[float]:
            if origin == virtual_origin or destination == virtual_origin:
                return 0.0
            return distances.distance(origin, destination)

    total_quantity = sum(max(0.0, operation.quantity) for operation in remaining)
    unlimited_capacity = max(1.0, total_quantity)
    route_origin = fixed_start or virtual_origin
    plan = optimize_route(
        remaining, route_origin, unlimited_capacity, OpenRouteDistances(),
        exact_location_limit=exact_location_limit,
        time_limit_seconds=time_limit_seconds,
        required_locations=required,
        visit_start=bool(fixed_start), fixed_end=fixed_end,
    )
    if not plan.valid and "capacity-safe" in plan.error:
        plan.error = "No pickup-before-delivery route could be produced."
    plan.input_hash = plan_hash
    return plan
