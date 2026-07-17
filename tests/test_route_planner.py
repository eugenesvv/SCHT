import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sc_hauling_tracker as tracker
from hauling_route_planner import (
    CachedDistanceProvider, CargoOperation, DictAliasRepository,
    LocationSearchService, StaticLocationRepository, optimize_open_route, optimize_route,
)
from location_catalog import CatalogDistanceProvider, LocationCatalog


class RouteStalenessRegressionTest(unittest.TestCase):
    @staticmethod
    def mission(mission_id="contract-a", pickup="Ashland", status="ACCEPTED"):
        return tracker.CargoMission(
            title="Cargo Haul", rank="Junior", pickup=pickup,
            dropoff="Endgame", commodity="Copper", scu="7",
            mission_id=mission_id, objective_id="cargo-0", status=status,
            data_provenance="manual", scu_provenance="manual",
        )

    @staticmethod
    def plan_for(mission, scope="all"):
        operation_id = tracker.route_operation_identity(mission, 0)
        operation = {"id": operation_id, "contract_id": mission.mission_id}
        return {
            "valid": True, "outdated": False, "scope": scope,
            "selected_contracts": [mission.mission_id] if scope == "selected" else [],
            "included_contract_ids": [mission.mission_id],
            "stops": [
                {"pickups": [operation], "deliveries": []},
                {"pickups": [], "deliveries": [operation]},
            ],
        }

    def test_completion_progress_does_not_make_route_inputs_outdated(self):
        accepted = self.mission()
        plan = self.plan_for(accepted)
        completed = self.mission(status="COMPLETED")
        self.assertTrue(tracker.route_plan_contract_inputs_match(plan, [completed]))

    def test_new_active_contract_invalidates_all_active_route(self):
        original = self.mission()
        plan = self.plan_for(original)
        added = self.mission(mission_id="contract-b", pickup="Gaslight")
        self.assertFalse(tracker.route_plan_contract_inputs_match(plan, [original, added]))

    def test_unselected_contract_does_not_invalidate_selected_route(self):
        original = self.mission()
        plan = self.plan_for(original, scope="selected")
        unrelated = self.mission(mission_id="contract-b", pickup="Gaslight")
        self.assertTrue(tracker.route_plan_contract_inputs_match(plan, [original, unrelated]))

    def test_changed_route_objective_invalidates_route(self):
        original = self.mission()
        plan = self.plan_for(original)
        corrected = self.mission(pickup="Gaslight")
        self.assertFalse(tracker.route_plan_contract_inputs_match(plan, [corrected]))

    def test_only_current_successful_route_can_be_reused(self):
        mission = self.mission()
        plan = self.plan_for(mission)
        self.assertTrue(tracker.route_plan_can_be_reused(plan, [mission], "all"))
        self.assertFalse(tracker.route_plan_can_be_reused({**plan, "outdated": True}, [mission], "all"))
        self.assertFalse(tracker.route_plan_can_be_reused({**plan, "valid": False}, [mission], "all"))
        added = self.mission(mission_id="contract-b", pickup="Gaslight")
        self.assertFalse(tracker.route_plan_can_be_reused(plan, [mission, added], "all"))

    def test_selected_route_reuse_requires_the_same_contract_selection(self):
        mission = self.mission()
        plan = self.plan_for(mission, scope="selected")
        self.assertTrue(tracker.route_plan_can_be_reused(plan, [mission], "selected", [mission.mission_id]))
        self.assertFalse(tracker.route_plan_can_be_reused(plan, [mission], "selected", ["contract-b"]))

    def test_pickup_only_contract_stop_can_be_promoted_to_start(self):
        stops = [
            {"location_id": "pickup", "pickups": [{"id": "cargo"}], "deliveries": []},
            {"location_id": "dropoff", "pickups": [], "deliveries": [{"id": "cargo"}]},
        ]
        self.assertEqual(0, tracker.route_endpoint_promotion_index(stops, "pickup", "start"))
        self.assertIsNone(tracker.route_endpoint_promotion_index(stops, "dropoff", "start"))

    def test_mixed_or_completed_stop_is_not_promoted_to_start(self):
        mixed = {"location_id": "shared", "pickups": [{"id": "a"}], "deliveries": [{"id": "b"}]}
        completed = {
            "location_id": "pickup", "pickups": [{"id": "a"}], "deliveries": [],
            "completion_state": "complete",
        }
        self.assertIsNone(tracker.route_endpoint_promotion_index([mixed], "shared", "start"))
        self.assertIsNone(tracker.route_endpoint_promotion_index([completed], "pickup", "start"))


class MatrixDistances:
    def __init__(self, values=None):
        self.values = values or {}

    def distance(self, a, b):
        if a == b:
            return 0.0
        return self.values.get(tuple(sorted((a, b))), 1.0)


class LinearDistances:
    def __init__(self, positions):
        self.positions = positions

    def distance(self, a, b):
        return abs(self.positions[a] - self.positions[b])


def pyro_contract(details=True, repeated_primary=True):
    common = dict(
        title="Member Cargo Haul", rank="Member", dropoff="Endgame",
        commodity="Copper", mission_id="pyro-example", data_provenance="ocr",
        scu_provenance="ocr", quantity_scope="aggregate",
    )
    return [
        tracker.CargoMission(
            pickup="Fallow Field", scu="12", objective_id="pickup_0",
            pickup_source_section="details" if details else "objectives",
            primary_pickup_occurrences=(("The Golden Riviera", "The Golden Riviera") if repeated_primary else ("Fallow Field", "The Golden Riviera")) if details else (),
            pickup_source_order=1 if details else None, **common,
        ),
        tracker.CargoMission(
            pickup="The Golden Riviera", scu="", objective_id="pickup_1",
            pickup_source_section="details" if details else "objectives",
            primary_pickup_occurrences=(("The Golden Riviera", "The Golden Riviera") if repeated_primary else ("Fallow Field", "The Golden Riviera")) if details else (),
            pickup_source_order=2 if details else None, **common,
        ),
    ]


def enabled_store(group):
    assessment = tracker.multi_pickup_bug_assessment(group)
    return {"version": 1, "contracts": {"pyro-example": {
        "mode": "enabled", "selected_pickup_id": assessment["selected_pickup_id"],
        "selected_pickup_name": assessment["selected_pickup_name"], "changed_by": "automatic",
        "overrides": [],
    }}}


class MultiPickupWorkaroundTest(unittest.TestCase):
    def test_route_persistence_debug_fixture_preserves_contract_and_pickup_shapes(self):
        data_dir = Path(__file__).resolve().parents[1] / "test_data"
        fixture = data_dir / "Route_Planner_Persistence_Debug.log"
        missions, completions = tracker.parse_log_data(fixture.read_text(encoding="utf-8"))
        grouped = tracker.contract_groups(missions)
        self.assertEqual(len(missions), 9)
        self.assertEqual(len(grouped), 6)
        self.assertEqual(sorted(len(group) for group in grouped), [1, 1, 1, 1, 2, 3])
        self.assertFalse(completions)
        pickups = {
            group[0].mission_id: [mission.pickup for mission in group]
            for group in grouped
        }
        self.assertEqual(pickups["a1400001-0000-4000-8000-000000000001"], ["Fallow Field", "Ashland"])
        self.assertEqual(
            pickups["a1400003-0000-4000-8000-000000000003"],
            ["The Golden Riviera", "Fallow Field", "Ashland"],
        )
        self.assertEqual(
            [mission.scu for mission in next(group for group in grouped if len(group) == 3)],
            ["9", "", ""],
        )
        phase1 = (data_dir / "Route_Planner_Persistence_Phase_1.log").read_text(encoding="utf-8")
        phase2 = (data_dir / "Route_Planner_Persistence_Phase_2.log").read_text(encoding="utf-8")
        phase3 = (data_dir / "Route_Planner_Persistence_Phase_3.log").read_text(encoding="utf-8")
        phase1_missions, phase1_events = tracker.parse_log_data(fixture.read_text(encoding="utf-8") + "\n" + phase1)
        self.assertEqual(len(phase1_events), 1)
        self.assertEqual(sum(mission.status == "COMPLETED" for mission in phase1_missions), 1)
        phase2_missions, phase2_events = tracker.parse_log_data(
            fixture.read_text(encoding="utf-8") + "\n" + phase1 + "\n" + phase2
        )
        self.assertEqual(len(phase2_events), 2)
        self.assertEqual(sum(mission.status == "COMPLETED" for mission in phase2_missions), 2)
        phase3_missions, phase3_events = tracker.parse_log_data(
            fixture.read_text(encoding="utf-8") + "\n" + phase1 + "\n" + phase2 + "\n" + phase3
        )
        self.assertEqual(len(phase3_events), 3)
        self.assertEqual(sum(mission.status == "COMPLETED" for mission in phase3_missions), 5)

    def test_checked_logistics_rows_expand_to_stable_route_member_identities(self):
        sections = tracker.logistics_sections(pyro_contract(repeated_primary=False))
        item_ids = [
            item["id"]
            for section in sections
            for column in section["columns"]
            for item in column["items"]
        ]
        loaded = tracker.loaded_logistics_member_identities(sections, {item_ids[1]: True})
        expected = tracker.logistics_member_identity(pyro_contract(repeated_primary=False)[1])
        self.assertEqual(loaded, [expected])

    def test_qualified_editor_location_uses_same_member_identity_as_logistics(self):
        raw = pyro_contract(repeated_primary=False)[0]
        qualified = tracker.replace(raw, pickup="Fallow Field — Pyro IV · Pyro system")
        self.assertEqual(
            tracker.logistics_member_identity(raw),
            tracker.logistics_member_identity(qualified),
        )

    def test_unchecked_logistics_rows_do_not_complete_route_members(self):
        sections = tracker.logistics_sections(pyro_contract(repeated_primary=False))
        self.assertEqual(tracker.loaded_logistics_member_identities(sections, {}), [])

    def test_synthetic_debug_summary_restores_shared_quantity_layout(self):
        mission_id = "d06d0001-0000-4000-8000-000000000001"
        lines = [
            f'<2026-07-13T08:00:00.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "Contract Accepted: Junior | Small Haul | Fallow Field -> Endgame" to queue. MissionId: [{mission_id}], ObjectiveId: []',
            f'<2026-07-13T08:00:00.001Z> [Notice] <SHUDEvent_OnNotification> Added notification "New Objective: Collect Copper from Fallow Field." to queue. MissionId: [{mission_id}], ObjectiveId: [pickup_1]',
            f'<2026-07-13T08:00:00.001Z> [Notice] <SHUDEvent_OnNotification> Added notification "New Objective: Deliver 0/12 SCU of Copper to Endgame:" to queue. MissionId: [{mission_id}], ObjectiveId: [pickup_1]',
        ]
        lines.extend(f'<2026-07-13T08:00:00.{100+i:03d}Z> [Trace] separator {i}' for i in range(81))
        lines.extend([
            f'<2026-07-13T08:00:01.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "Contract Accepted: Junior | Small Haul | The Golden Riviera -> Endgame" to queue. MissionId: [{mission_id}], ObjectiveId: []',
            f'<2026-07-13T08:00:01.001Z> [Notice] <SHUDEvent_OnNotification> Added notification "New Objective: Collect Copper from The Golden Riviera." to queue. MissionId: [{mission_id}], ObjectiveId: [pickup_2]',
            f'<2026-07-13T08:00:01.001Z> [Notice] <SHUDEvent_OnNotification> Added notification "New Objective: Deliver 0/0 SCU of Copper to Endgame:" to queue. MissionId: [{mission_id}], ObjectiveId: [pickup_2]',
            f'<2026-07-13T08:00:02.000Z> [Notice] <DebugContractSummary> MissionId [{mission_id}] known shared total [12 SCU]; status intentionally remains ACCEPTED',
        ])
        missions, _ = tracker.parse_log_data("\n".join(lines))
        self.assertEqual([(m.pickup, m.scu, m.quantity_scope) for m in missions], [
            ("Fallow Field", "12", "aggregate"),
            ("The Golden Riviera", "", "aggregate"),
        ])
        assessment = tracker.multi_pickup_bug_assessment(missions)
        self.assertFalse(assessment["confident"])
        self.assertEqual(assessment["selected_pickup_name"], "The Golden Riviera")

    def test_distinct_primary_pickups_are_not_automatic_bug_matches(self):
        assessment = tracker.multi_pickup_bug_assessment(pyro_contract(repeated_primary=False))
        self.assertTrue(assessment["matches_shape"])
        self.assertFalse(assessment["confident"])
        self.assertEqual(assessment["selected_pickup_name"], "The Golden Riviera")

    def test_explicit_global_workaround_can_use_final_details_pickup_without_repeated_primary(self):
        group = pyro_contract(repeated_primary=False)
        assessment = tracker.multi_pickup_bug_assessment(group)
        store = {"version": 1, "contracts": {"pyro-example": {
            "mode": "enabled",
            "selected_pickup_id": assessment["selected_pickup_id"],
            "selected_pickup_name": assessment["selected_pickup_name"],
            "changed_by": "automatic",
            "overrides": [],
        }}}
        operational, _ = tracker.operational_contracts(group, store)
        self.assertEqual([(mission.pickup, mission.scu) for mission in operational], [("The Golden Riviera", "12")])

    def test_raw_contract_preserved_and_final_details_pickup_is_operational(self):
        raw = pyro_contract()
        operational, notices = tracker.operational_contracts(raw, enabled_store(raw))
        self.assertEqual([m.pickup for m in raw], ["Fallow Field", "The Golden Riviera"])
        self.assertEqual([m.pickup for m in operational], ["The Golden Riviera"])
        self.assertEqual(operational[0].scu, "12")
        self.assertEqual(notices["pyro-example"]["hidden_count"], 1)

    def test_disabling_restores_all_locations_without_changing_quantity(self):
        raw = pyro_contract()
        store = enabled_store(raw)
        store["contracts"]["pyro-example"]["mode"] = "disabled"
        operational, _ = tracker.operational_contracts(raw, store)
        self.assertEqual([m.pickup for m in operational], ["Fallow Field", "The Golden Riviera"])
        self.assertEqual(sum(float(m.scu or 0) for m in operational), 12)

    def test_logistics_groups_filtered_contracts_under_common_pickup_and_restores_when_off(self):
        first = pyro_contract()
        second = [
            tracker.replace(mission, mission_id="pyro-second", dropoff="Gaslight", commodity="Hydrogen", scu="3" if index == 0 else "")
            for index, mission in enumerate(pyro_contract())
        ]
        raw = [*first, *second]
        contracts = {}
        for group in tracker.contract_groups(raw):
            assessment = tracker.multi_pickup_bug_assessment(group)
            contracts[group[0].mission_id] = {
                "mode": "enabled", "selected_pickup_id": assessment["selected_pickup_id"],
                "selected_pickup_name": assessment["selected_pickup_name"], "changed_by": "automatic",
            }
        operational, _ = tracker.operational_contracts(raw, {"version": 1, "contracts": contracts})
        sections = tracker.logistics_sections(operational)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["mode"], "single_pickup")
        self.assertEqual(sections[0]["fixed_location"], "The Golden Riviera")
        self.assertEqual([column["location"] for column in sections[0]["columns"]], ["Endgame", "Gaslight"])

        for config in contracts.values():
            config["mode"] = "disabled"
        restored, _ = tracker.operational_contracts(raw, {"version": 1, "contracts": contracts})
        restored_sections = tracker.logistics_sections(restored)
        self.assertEqual(len(restored_sections), 2)
        self.assertTrue(all(section["mode"] == "aggregate_pickups" for section in restored_sections))

    def test_explicit_workaround_uses_final_available_pickup_when_details_order_is_missing(self):
        group = pyro_contract(details=False)
        assessment = tracker.multi_pickup_bug_assessment(group)
        self.assertTrue(assessment["matches_shape"])
        self.assertFalse(assessment["confident"])
        operational, notices = tracker.operational_contracts(group, {
            "version": 1, "contracts": {"pyro-example": {"mode": "enabled"}}
        })
        self.assertEqual([(mission.pickup, mission.scu) for mission in operational], [("The Golden Riviera", "12")])
        self.assertEqual(notices["pyro-example"]["hidden_count"], 1)

    def test_manual_selection_can_enable_ambiguous_contract(self):
        group = pyro_contract(details=False)
        chosen = group[1]
        store = {"version": 1, "contracts": {"pyro-example": {
            "mode": "enabled", "selected_pickup_id": tracker.contract_location_id(chosen, "pickup"),
            "selected_pickup_name": chosen.pickup, "changed_by": "user", "overrides": [],
        }}}
        operational, _ = tracker.operational_contracts(group, store)
        self.assertEqual([m.pickup for m in operational], ["The Golden Riviera"])
        self.assertEqual(operational[0].scu, "12")

    def test_ocr_parser_uses_details_order_not_objectives_order(self):
        parsed = tracker.parse_contract_details_text(
            "PICK UP LOCATIONS (ANY ORDER)\nFallow Field\nThe Golden Riviera\n"
            "PRIMARY OBJECTIVES\nDeliver 0/12 SCU of Copper to Endgame. "
            "Collect Copper from The Golden Riviera. Collect Copper from Fallow Field.",
            [{"pickup": "Fallow Field"}, {"pickup": "The Golden Riviera"}, {"dropoff": "Endgame"}],
        )
        self.assertEqual([x["name"] for x in parsed["details_pickups"]], ["Fallow Field", "The Golden Riviera"])

    def test_ocr_parser_preserves_repeated_primary_pickup_evidence(self):
        parsed = tracker.parse_contract_details_text(
            "PICK UP LOCATIONS (ANY ORDER)\nSacren's Plot\nCanard View\n"
            "PRIMARY OBJECTIVES\nDeliver amount/total SCU of item to Stanton Gateway.\n"
            "Collect item from Sacren's Plot.\nCollect item from Sacren's Plot.",
            [{"pickup": "Sacren's Plot"}, {"pickup": "Canard View"}, {"dropoff": "Stanton Gateway"}],
        )
        self.assertEqual(parsed["primary_pickup_occurrences"], ["Sacren's Plot", "Sacren's Plot"])

    def test_primary_pickup_evidence_survives_saved_override(self):
        normalized = tracker.normalize_contract_overrides({"mission": {"objectives": [{
            "pickup": "Sacren's Plot", "dropoff": "Stanton Gateway", "commodity": "Silicon", "scu": "7",
            "primary_pickup_occurrences": ["Sacren's Plot", "Sacren's Plot"],
        }]}})
        self.assertEqual(
            normalized["mission"]["objectives"][0]["primary_pickup_occurrences"],
            ["Sacren's Plot", "Sacren's Plot"],
        )

    def test_location_override_migration_safe_default(self):
        self.assertEqual(tracker.normalize_location_overrides({}), {"version": 1, "contracts": {}})
        raw = pyro_contract()
        operational, _ = tracker.operational_contracts(raw, {})
        self.assertEqual(len(operational), 2)

    def test_saved_contract_correction_preserves_details_order_metadata(self):
        normalized = tracker.normalize_contract_overrides({"mission": {"objectives": [{
            "pickup": "Fallow Field", "dropoff": "Endgame", "commodity": "Copper", "scu": "12",
            "quantity_scope": "aggregate", "pickup_source_section": "details", "pickup_source_order": 1,
            "pickup_raw_text": "Fallow Field on Pyro IV",
        }]}})
        objective = normalized["mission"]["objectives"][0]
        self.assertEqual(objective["pickup_source_section"], "details")
        self.assertEqual(objective["pickup_source_order"], 1)
        self.assertEqual(objective["pickup_raw_text"], "Fallow Field on Pyro IV")

    def test_editor_metadata_migration_restores_original_pickup_order(self):
        base = pyro_contract()
        saved = [{
            "pickup": "Fallow Field — Pyro IV · Pyro system", "dropoff": "Endgame",
            "commodity": "Copper", "scu": "12", "pickup_source_section": "other",
            "pickup_source_order": None,
        }, {
            "pickup": "The Golden Riviera — Bloom · Pyro system", "dropoff": "Endgame",
            "commodity": "Copper", "scu": "",
        }]
        restored = tracker.restore_contract_objective_metadata(saved, base)
        self.assertEqual([item["pickup_source_section"] for item in restored], ["details", "details"])
        self.assertEqual([item["pickup_source_order"] for item in restored], [1, 2])


class RoutePlannerTest(unittest.TestCase):
    def test_all_active_shared_pickup_routes_every_contract(self):
        catalog = LocationCatalog.load()
        pickup = catalog.resolve("The Golden Riviera").record.id
        destinations = [
            catalog.resolve(name).record.id
            for name in ("Endgame", "Gaslight", "Stanton Gateway", "Nyx Gateway — Pyro system", "Ruin Station")
        ]
        quantities = [12, 3, 11, 7, 7]
        operations = [
            CargoOperation(str(index), f"contract-{index}", "Cargo", quantity, pickup, destination)
            for index, (destination, quantity) in enumerate(zip(destinations, quantities), 1)
        ]
        plan = optimize_open_route(operations, CatalogDistanceProvider(catalog))
        self.assertTrue(plan.valid)
        self.assertEqual(len(plan.stops), 6)
        self.assertEqual(plan.stops[0].location, pickup)
        self.assertEqual(len(plan.stops[0].pickups), 5)
        self.assertEqual(plan.stops[0].load_after, 40)
        self.assertEqual(sum(len(stop.deliveries) for stop in plan.stops), 5)

    def test_open_route_single_pickup_multiple_dropoffs(self):
        operations = [
            CargoOperation("a", "A", "Copper", 12, "Pickup", "Drop 1"),
            CargoOperation("b", "B", "Silicon", 7, "Pickup", "Drop 2"),
        ]
        plan = optimize_open_route(operations, MatrixDistances())
        self.assertTrue(plan.valid)
        self.assertEqual(plan.stops[0].location, "Pickup")
        self.assertEqual(len(plan.stops[0].pickups), 2)
        self.assertEqual({stop.location for stop in plan.stops[1:]}, {"Drop 1", "Drop 2"})

    def test_open_route_multiple_pickups_single_dropoff(self):
        operations = [
            CargoOperation("a", "A", "Copper", 12, "Pickup 1", "Drop"),
            CargoOperation("b", "B", "Silicon", 7, "Pickup 2", "Drop"),
        ]
        plan = optimize_open_route(operations, MatrixDistances())
        self.assertTrue(plan.valid)
        self.assertEqual(plan.stops[-1].location, "Drop")
        self.assertEqual(len(plan.stops[-1].deliveries), 2)
        self.assertEqual({stop.location for stop in plan.stops[:-1]}, {"Pickup 1", "Pickup 2"})

    def test_open_route_single_pickup_single_dropoff(self):
        operation = CargoOperation("a", "A", "Copper", 12, "Pickup", "Drop")
        plan = optimize_open_route([operation], MatrixDistances())
        self.assertTrue(plan.valid)
        self.assertEqual([stop.location for stop in plan.stops], ["Pickup", "Drop"])

    def test_open_route_multiple_pickups_multiple_distinct_dropoffs(self):
        operations = [
            CargoOperation("a", "A", "Copper", 12, "Pickup 1", "Drop 1"),
            CargoOperation("b", "B", "Silicon", 7, "Pickup 2", "Drop 2"),
        ]
        plan = optimize_open_route(operations, MatrixDistances())
        self.assertTrue(plan.valid)
        visited = [stop.location for stop in plan.stops]
        self.assertLess(visited.index("Pickup 1"), visited.index("Drop 1"))
        self.assertLess(visited.index("Pickup 2"), visited.index("Drop 2"))
        self.assertEqual(set(visited), {"Pickup 1", "Pickup 2", "Drop 1", "Drop 2"})

    def test_open_route_shared_pickup_and_dropoff_can_be_one_stop(self):
        operations = [
            CargoOperation("a", "A", "Copper", 5, "A", "Hub"),
            CargoOperation("b", "B", "Food", 5, "Hub", "B"),
        ]
        plan = optimize_open_route(operations, MatrixDistances())
        self.assertTrue(plan.valid)
        self.assertEqual([stop.location for stop in plan.stops], ["A", "Hub", "B"])
        hub = plan.stops[1]
        self.assertEqual(len(hub.deliveries), 1)
        self.assertEqual(len(hub.pickups), 1)

    def test_open_route_crossed_contracts_revisit_a_location(self):
        operations = [
            CargoOperation("a", "A", "Copper", 5, "A", "B"),
            CargoOperation("b", "B", "Food", 5, "B", "A"),
        ]
        plan = optimize_open_route(operations, MatrixDistances())
        self.assertTrue(plan.valid)
        locations = [stop.location for stop in plan.stops]
        self.assertEqual(len(locations), 3)
        self.assertEqual(locations[0], locations[-1])
        self.assertEqual(set(locations), {"A", "B"})
        self.assertEqual(sum(len(stop.deliveries) for stop in plan.stops), 2)

    def test_open_route_chooses_shortest_first_and_last_stops(self):
        operations = [
            CargoOperation("a", "A", "Copper", 5, "P1", "D1"),
            CargoOperation("b", "B", "Food", 5, "P2", "D2"),
        ]
        distances = LinearDistances({"P1": 0, "D1": 1, "P2": 10, "D2": 11})
        plan = optimize_open_route(operations, distances)
        self.assertTrue(plan.valid)
        self.assertEqual([stop.location for stop in plan.stops], ["P1", "D1", "P2", "D2"])
        self.assertEqual(plan.total_distance, 11)

    def test_open_route_preserves_user_start_and_final_locations(self):
        operations = [
            CargoOperation("a", "A", "Copper", 5, "P1", "D1"),
            CargoOperation("b", "B", "Food", 5, "P2", "D2"),
        ]
        distances = LinearDistances({"Start": -10, "P1": 0, "D1": 1, "P2": 10, "D2": 11, "Final": 20})
        plan = optimize_open_route(operations, distances, fixed_start="Start", fixed_end="Final")
        self.assertTrue(plan.valid)
        self.assertEqual(plan.stops[0].location, "Start")
        self.assertEqual(plan.stops[-1].location, "Final")
        locations = [stop.location for stop in plan.stops]
        self.assertLess(locations.index("P1"), locations.index("D1"))
        self.assertLess(locations.index("P2"), locations.index("D2"))

    def test_fixed_start_executes_pickups_at_that_location(self):
        operation = CargoOperation("a", "A", "Copper", 5, "Start", "Drop")
        plan = optimize_open_route([operation], MatrixDistances(), fixed_start="Start")
        self.assertTrue(plan.valid)
        self.assertEqual([stop.location for stop in plan.stops], ["Start", "Drop"])
        self.assertEqual([item.id for item in plan.stops[0].pickups], ["a"])

    def test_fixed_final_cannot_be_visited_before_remaining_deliveries(self):
        operations = [
            CargoOperation("a", "A", "Copper", 5, "Pickup", "Final"),
            CargoOperation("b", "B", "Food", 5, "Pickup", "Other"),
        ]
        plan = optimize_open_route(operations, MatrixDistances(), fixed_end="Final")
        self.assertTrue(plan.valid)
        self.assertEqual(plan.stops[-1].location, "Final")

    def test_distance_cache_write_failure_does_not_abort_routing(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = CachedDistanceProvider(Path(tmp) / "cache.json", MatrixDistances({("A", "B"): 42}))
            with patch.object(Path, "write_text", side_effect=PermissionError("read only")):
                self.assertEqual(provider.distance("A", "B"), 42)

    def test_logistics_regroups_short_and_qualified_location_names(self):
        missions = [
            tracker.CargoMission(
                title="Haul A", rank="Junior", pickup="The Golden Riviera", dropoff="Endgame",
                commodity="Copper", scu="12", mission_id="a", scu_provenance="manual",
            ),
            tracker.CargoMission(
                title="Haul B", rank="Junior",
                pickup="The Golden Riviera — Bloom · Pyro system",
                dropoff="Nyx Gateway — Pyro system", commodity="Silicon", scu="7",
                mission_id="b", scu_provenance="manual",
            ),
        ]
        sections = tracker.logistics_sections(missions)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["mode"], "single_pickup")
        self.assertEqual(sections[0]["objective_count"], 2)
        self.assertEqual(len(sections[0]["columns"]), 2)
        for column in sections[0]["columns"]:
            for item in column["items"]:
                self.assertTrue(item["member_identities"])
        self.assertEqual(
            sections[0]["fixed_location"],
            "The Golden Riviera",
        )

    def test_editor_objective_locations_use_canonical_names_and_keep_unknowns(self):
        objectives = tracker.canonicalize_contract_objective_locations([{
            "pickup": "Everus Harbour", "dropoff": "Ruin Station above Pyro VI",
            "commodity": "Aluminum", "scu": "7",
        }, {
            "pickup": "Brand New Depot", "dropoff": "DestinationAddress",
            "commodity": "Silicon", "scu": "4",
        }])
        self.assertEqual(objectives[0]["pickup"], "Everus Harbor — Hurston · Stanton system")
        self.assertEqual(objectives[0]["dropoff"], "Ruin Station — Terminus · Pyro system")
        self.assertEqual(objectives[1]["pickup"], "Brand New Depot")
        self.assertEqual(objectives[1]["dropoff"], "DestinationAddress")

    def test_offline_catalog_normalizes_hierarchy_and_supplies_distances(self):
        catalog = LocationCatalog.load()
        ruin = catalog.resolve("Ruin Station above Pyro VI")
        golden = catalog.resolve("The Golden Riviera")
        everus = catalog.resolve("Everus Harbour")
        self.assertGreater(len(catalog.records), 1000)
        self.assertEqual(ruin.record.name, "Ruin Station")
        self.assertEqual(ruin.record.system, "Pyro")
        self.assertIn("Pyro system", ruin.record.subtitle)
        self.assertEqual(catalog.resolve("Endgame").record.subtitle, "Pyro system")
        self.assertEqual(everus.record.name, "Everus Harbor")
        self.assertEqual(catalog.resolve("Everus Harbr").record.name, "Everus Harbor")
        self.assertEqual(catalog.resolve("Nyx Gateway — Pyro system").record.system, "Pyro")
        self.assertEqual(catalog.resolve("Nyx Gateway — Stanton system").record.system, "Stanton")
        self.assertEqual(
            tracker.normalized_location_payload("DestinationAddress")["subtitle"],
            "Unknown location · needs mapping",
        )
        distances = CatalogDistanceProvider(catalog)
        self.assertGreater(distances.distance(ruin.record.id, golden.record.id), 0)
        self.assertIsNone(distances.distance(ruin.record.id, everus.record.id))

    def test_dudley_ocr_conjunction_and_truncated_hierarchy_resolve(self):
        catalog = LocationCatalog.load()
        for value in (
            "Dudley e Daughters at the L4 Lagrange of Pyro IV",
            "Dudley e Daughters at the L4 Lagra",
            "Dudley and Daughters at the L4 Lagrange of Pyro IV",
        ):
            with self.subTest(value=value):
                match = catalog.resolve(value)
                self.assertTrue(match.resolved)
                self.assertEqual("Dudley & Daughters", match.record.name)
                self.assertEqual("Pyro", match.record.system)

    def test_pyro_locations_resolve_and_short_ruin_station_alias_is_supported(self):
        resolver = LocationSearchService(
            StaticLocationRepository(tracker.known_location_names()),
            DictAliasRepository({"Ruin Station": "Ruin Station above Pyro VI"}),
        )
        for location in (
            "Endgame at the L3 Lagrange of Pyro VI",
            "Gaslight at the L2 Lagrange of Pyro V",
            "Ruin Station above Pyro VI",
        ):
            self.assertNotEqual(resolver.resolve(location).status, "unresolved")
        self.assertEqual(resolver.resolve("Ruin Station").canonical_name, "Ruin Station above Pyro VI")
        self.assertEqual(resolver.resolve("DestinationAddress").status, "unresolved")

    def test_pickup_precedes_delivery_and_capacity_is_never_exceeded(self):
        ops = [CargoOperation("a", "A", "Copper", 12, "Golden", "Endgame")]
        plan = optimize_route(ops, "Start", 12, MatrixDistances())
        self.assertTrue(plan.valid)
        self.assertEqual([s.location for s in plan.stops], ["Golden", "Endgame"])
        self.assertTrue(all(s.load_after <= 12 for s in plan.stops))

    def test_shared_physical_location_is_grouped_and_can_deliver_then_pickup(self):
        ops = [
            CargoOperation("a", "A", "Copper", 5, "Start", "Hub"),
            CargoOperation("b", "B", "Food", 5, "Hub", "End"),
        ]
        plan = optimize_route(ops, "Start", 5, MatrixDistances())
        hub = next(s for s in plan.stops if s.location == "Hub")
        self.assertEqual(len(hub.deliveries), 1)
        self.assertEqual(len(hub.pickups), 1)
        self.assertEqual([s.location for s in plan.stops].count("Hub"), 1)

    def test_user_waypoints_are_optimized_and_can_be_removed_from_inputs(self):
        ops = [CargoOperation("a", "A", "Copper", 4, "Pickup", "Dropoff")]
        with_waypoint = optimize_route(
            ops, "Start", 10, MatrixDistances(), required_locations=["Scenic Stop"],
        )
        without_waypoint = optimize_route(ops, "Start", 10, MatrixDistances())
        self.assertTrue(with_waypoint.valid)
        self.assertIn("Scenic Stop", [stop.location for stop in with_waypoint.stops])
        self.assertTrue(next(stop for stop in with_waypoint.stops if stop.location == "Scenic Stop").user_waypoint)
        self.assertNotIn("Scenic Stop", [stop.location for stop in without_waypoint.stops])
        self.assertNotEqual(with_waypoint.input_hash, without_waypoint.input_hash)

    def test_route_can_contain_only_user_added_locations(self):
        plan = optimize_route([], "Start", 10, MatrixDistances(), required_locations=["A", "B"])
        self.assertTrue(plan.valid)
        self.assertEqual({stop.location for stop in plan.stops}, {"A", "B"})

    def test_multiple_contracts_are_traceable_and_deterministic(self):
        ops = [
            CargoOperation("a", "Contract A", "Copper", 4, "P1", "D1"),
            CargoOperation("b", "Contract B", "Copper", 4, "P2", "D2"),
        ]
        first = optimize_route(ops, "Start", 8, MatrixDistances())
        second = optimize_route(ops, "Start", 8, MatrixDistances())
        self.assertEqual([s.location for s in first.stops], [s.location for s in second.stops])
        self.assertEqual({op.contract_id for s in first.stops for op in s.pickups}, {"Contract A", "Contract B"})

    def test_impossible_capacity_returns_reason(self):
        plan = optimize_route([CargoOperation("a", "A", "Copper", 13, "P", "D")], "Start", 12, MatrixDistances())
        self.assertFalse(plan.valid)
        self.assertEqual(plan.error, "A 13 SCU cargo item exceeds the 12 SCU ship capacity.")

    def test_completed_operations_are_excluded(self):
        plan = optimize_route([CargoOperation("a", "A", "Copper", 4, "P", "D", completed_delivery=True)], "Start", 10, MatrixDistances())
        self.assertTrue(plan.valid)
        self.assertEqual(plan.stops, [])

    def test_cached_distance_remains_available_without_upstream(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "distances.json"
            path.write_text(json.dumps({"version": 1, "distances": {"a|b": 42}}), encoding="utf-8")
            provider = CachedDistanceProvider(path)
            self.assertEqual(provider.distance("A", "B"), 42)

    def test_large_route_uses_bounded_heuristic(self):
        ops = [CargoOperation(str(i), str(i), "Cargo", 1, f"P{i}", f"D{i}") for i in range(12)]
        plan = optimize_route(ops, "Start", 12, MatrixDistances(), exact_location_limit=5, time_limit_seconds=.1)
        self.assertTrue(plan.valid)
        self.assertFalse(plan.exact)
        self.assertEqual(len(plan.stops), 24)

    def test_phantom_pickup_never_enters_route_input(self):
        raw = pyro_contract()
        operational, _ = tracker.operational_contracts(raw, enabled_store(raw))
        self.assertNotIn("Fallow Field", {m.pickup for m in operational})


class RoutePlannerUiContractTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = Path(tracker.__file__).read_text(encoding="utf-8")

    def test_settings_contract_editor_and_original_view_are_present(self):
        self.assertIn('id="multiPickupDefaultBtn"', self.source)
        self.assertIn('id="contractBugFixToggle"', self.source)
        self.assertIn('Show original contract', self.source)
        self.assertIn('phantom pickup hidden', self.source)

    def test_route_planner_and_overlay_next_route_are_present(self):
        self.assertIn('id="routePlannerPanel"', self.source)
        self.assertNotIn('id="optimizeRouteBtn"', self.source)
        self.assertIn("function renderRouteNext(data)", self.source)
        self.assertIn('Stop ${next.number} of ${route.stops.length}', self.source)
        self.assertIn("resolve_route_location", self.source)
        self.assertIn('data-route-resolve', self.source)
        self.assertIn('"unresolved_locations": unresolved', self.source)
        self.assertIn("function locationMarkup", self.source)
        self.assertIn("CatalogDistanceProvider", self.source)
        self.assertIn('data-route-scope="all"', self.source)
        self.assertIn('id="addRouteWaypointBtn"', self.source)
        self.assertIn("required_locations=self.route_waypoints", self.source)
        self.assertIn("optimize_open_route(", self.source)
        self.assertNotIn('id="routeStart"', self.source)
        self.assertNotIn('id="routeCapacity"', self.source)
        self.assertNotIn("start_location:$('routeStart')", self.source)
        self.assertNotIn("ship_capacity:$('routeCapacity')", self.source)

    def test_compact_route_planner_overlay_is_independent_and_state_driven(self):
        for marker in (
            "ROUTE_OVERLAY_HTML", 'id="openRouteOverlayBtn"', 'id="progress"',
            'id="stop"', 'id="nextName"', 'id="remaining"',
        ):
            self.assertIn(marker, self.source)
        self.assertIn('"route-overlay-window.json"', self.source)
        self.assertIn('"route-overlay-webview"', self.source)
        self.assertIn('"--overlay-kind"', self.source)
        self.assertIn('"open_route_overlay": controller.open_route_overlay', self.source)
        self.assertIn('if parsed.path == "/route-overlay":', self.source)
        self.assertIn("function stopComplete(stop,data,index=-1)", self.source)
        self.assertIn("stops.findIndex((stop,index)=>!stopComplete(stop,data,index))", self.source)
        self.assertIn("if(route.outdated)", self.source)
        self.assertIn("Route outdated. Recalculate it in SCHT.", self.source)
        self.assertNotIn("if(!route.valid||route.outdated||currentIndex<0)", self.source)
        self.assertIn("self.default_width, self.default_height = ((500, 160)", self.source)
        self.assertIn('class="pin-icon"', self.source)
        self.assertIn('class="unpin-icon"', self.source)
        self.assertIn("mixed=pickups.length>0&&deliveries.length>0", self.source)
        self.assertIn('class="action-item pickup-action">PICK UP', self.source)
        self.assertIn('class="action-item dropoff-action">DROP OFF', self.source)
        self.assertIn("index===0&&stop.user_waypoint&&noCargo", self.source)
        self.assertIn("data-next-waypoint", self.source)
        self.assertIn('class="next-wp-chevron"', self.source)
        self.assertNotIn("NEXT WP <b>→</b>", self.source)
        self.assertIn("data-mark-loaded", self.source)
        self.assertIn("MARK ALL LOADED", self.source)
        self.assertIn('class="stop-detail"', self.source)
        self.assertIn('class="stop-location-meta"', self.source)
        self.assertNotIn('<section class="settings" id="settingsMenu" hidden><h3>Route overlay</h3>', self.source)
        self.assertIn('.setting{display:grid;grid-template-columns:1fr auto;align-items:center;gap:9px;min-height:30px;border-top:1px solid rgba(255,255,255,.055);font-size:10px;font-weight:400}', self.source)
        self.assertIn('.stop-location-meta{display:block;min-width:0;margin-top:3px;color:#777d97;font-size:8.5px', self.source)
        self.assertIn("locationContext=current.parent_body||'Unknown system'", self.source)
        self.assertIn("· QT ${distance(activeLegDistance)}", self.source)
        self.assertIn("stops.slice(currentIndex).reduce", self.source)
        self.assertNotIn("stops.slice(currentIndex+(startWaypointSkipped?0:1))", self.source)
        self.assertIn("function cargoGroup(kind,ops,showIcon=false)", self.source)
        self.assertIn("function cargoLine(pickups,deliveries)", self.source)
        self.assertIn("cargoGroup('unload',deliveries,true)", self.source)
        self.assertIn("cargoGroup('load',pickups,true)", self.source)
        self.assertLess(
            self.source.index("cargoGroup('unload',deliveries,true)"),
            self.source.index("cargoGroup('load',pickups,true)"),
        )
        self.assertIn("pickups.length?cargoGroup('load',pickups):cargoGroup('unload',deliveries)", self.source)
        self.assertIn("PICKUP_CHEVRON_SVG", self.source)
        self.assertIn("DROPOFF_CHEVRON_SVG", self.source)
        self.assertIn("label=loading?'Load cargo':'Unload cargo'", self.source)
        self.assertIn('class="cargo-group-icon" role="img" aria-label="${label}"', self.source)
        self.assertIn('.cargo-group-icon svg{width:11px;height:11px;fill:currentColor', self.source)
        self.assertIn('.action-item .cargo-action-chevron{width:11px;height:11px', self.source)
        self.assertNotIn('class="lane-label"', self.source)
        self.assertNotIn("function cargoLane(kind,ops)", self.source)
        self.assertGreaterEqual(self.source.count("M342.6 105.4C330.1 92.9"), 3)
        self.assertGreaterEqual(self.source.count("M342.6 534.6C330.1 547.1"), 3)
        self.assertIn('font-size:10.5px;font-weight:750;line-height:1.35', self.source)
        self.assertNotIn("↑", self.source)
        self.assertNotIn("↓", self.source)
        self.assertIn("function initCargoTickers()", self.source)
        self.assertIn("prefers-reduced-motion:reduce", self.source)
        self.assertIn("stopMarkup!==lastStopMarkup", self.source)
        self.assertIn('class="stop-command load-command"', self.source)
        self.assertIn('class="stop-actions">${markLoaded}<span class="action-label"', self.source)
        self.assertIn(".stop-actions{align-self:center;display:flex;align-items:center", self.source)
        self.assertIn(".stop-command{font-size:9px}", self.source)
        self.assertNotIn('id="onboard"', self.source)
        self.assertNotIn("SCU onboard", self.source)
        self.assertIn("display:inline-flex;align-items:center;justify-content:center", self.source)
        self.assertIn("action:'replace',checklist", self.source)
        self.assertIn("font:800 9.5px Consolas", self.source)
        self.assertIn("fetch('/api/state'", self.source)
        self.assertIn("Compact Route Planner overlay opened.", self.source)
        self.assertIn("use <strong>Overlay</strong> in the Route Planner header", self.source)

    def test_route_planner_uses_progress_and_connected_stop_card_design(self):
        for element_id in (
            "routeContractsBtn", "editRouteBtn", "routeRemoveBtn",
            "routeWaypointLabel", "routeStops",
        ):
            self.assertIn(f'id="{element_id}"', self.source)
        self.assertNotIn('id="routeProgress"', self.source)
        for element_id in ("routeConfigWaypoints", "routeConfigDistance", "routeConfigCargo"):
            self.assertNotIn(f'id="{element_id}"', self.source)
        self.assertIn('class="panel-head route-planner-head"', self.source)
        self.assertIn('class="route-mode-tools" role="group"', self.source)
        self.assertNotIn('>Optimize route</button>', self.source)
        self.assertNotIn('class="route-mode-button active" type="button" data-route-scope="all"', self.source)
        self.assertIn("allButton.classList.toggle('active',route.valid&&preset==='all')", self.source)
        self.assertIn('.route-planner-head .title-row h2{color:inherit;font-size:var(--type-heading);font-weight:var(--weight-strong)}', self.source)
        self.assertIn('.route-planner-head .title-row small{max-width:none;color:var(--muted);font-size:var(--type-meta);font-weight:var(--weight-body)}', self.source)
        self.assertNotIn('id="routeMetricDistance"', self.source)
        self.assertNotIn('id="routeMetricCargo"', self.source)
        self.assertIn("' start-stop'", self.source)
        self.assertIn('class="route-stops route-timeline"', self.source)
        self.assertIn('class="route-stop-connector"', self.source)
        self.assertIn('class="route-connector-distance"', self.source)
        self.assertNotIn('M471.1 297.4C483.6 309.9 483.6 330.2 471.1 342.7', self.source)
        self.assertIn('.route-timeline .route-stop{display:grid;', self.source)
        self.assertIn('.route-timeline .route-stop-connector:before', self.source)
        self.assertIn('class="route-summary-box"', self.source)
        for summary_id in (
            "routeSummaryDistance", "routeSummaryCargo", "routeSummaryStops", "routeSummaryContracts",
            "routeSummaryStart", "routeSummaryFinal", "routeSummaryPayout", "routeSummaryPayoutNote",
        ):
            self.assertIn(f'id="{summary_id}"', self.source)
        self.assertIn('id="routeSummaryTitle">Summary</h3>', self.source)
        self.assertNotIn('id="routeSummaryTitle">Route Summary</h3>', self.source)
        self.assertNotIn('<section class="route-summary-primary"><span class="route-summary-icon"', self.source)
        self.assertIn("$('routeSummaryDistance').textContent=route.valid?quantumRouteDistance(route.total_distance):'—'", self.source)
        self.assertIn('.route-summary-box{position:sticky;top:12px;', self.source)
        self.assertIn('.route-summary-content{display:grid}', self.source)
        self.assertIn('.route-summary-stats{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));', self.source)
        self.assertIn('.route-summary-journey{position:relative;display:grid;', self.source)
        self.assertIn('.route-summary-payout{display:flex;', self.source)
        self.assertIn('.route-summary-primary{grid-template-columns:minmax(0,1fr) auto;min-height:72px;', self.source)
        self.assertIn('.route-summary-primary .route-summary-copy strong{font-size:12.5px}', self.source)
        self.assertIn('.route-summary-endpoint strong{font-size:11.5px}', self.source)
        self.assertIn('.route-summary-payout strong{font-size:15.5px}', self.source)
        self.assertIn('"expected_payout": sum(known_payouts)', self.source)
        self.assertIn('"unknown_payout_count": len(payout_values) - len(known_payouts)', self.source)
        self.assertIn("$('routeSummaryStart').textContent=route.valid&&stops.length?stops[0].location:'—'", self.source)
        self.assertIn("$('routeSummaryFinal').textContent=route.valid&&stops.length?stops[stops.length-1].location:'—'", self.source)
        self.assertIn('class="route-stop-action pickup"', self.source)
        self.assertIn('${LOCATION_SVGS.pickup}', self.source)
        self.assertIn('class="route-stop-action dropoff"', self.source)
        self.assertIn('${LOCATION_SVGS.dropoff}', self.source)
        self.assertIn('.route-stop-action{display:inline-flex;', self.source)
        self.assertIn("function compactRouteDistance", self.source)
        self.assertNotIn("function routeCargoRow", self.source)
        self.assertIn('class="route-stop-heading"', self.source)
        self.assertIn('class="route-stop-location"', self.source)
        self.assertIn('class="route-stop-distance"', self.source)
        self.assertIn('<small>QT</small><strong>${distance}</strong>', self.source)
        self.assertIn('function quantumRouteDistance(value)', self.source)
        self.assertIn("Math.ceil(distanceKm/1e6)} Gm", self.source)
        self.assertIn("Math.ceil(distanceKm/1e3)} Mm", self.source)
        self.assertIn("Math.ceil(distanceKm)} km", self.source)
        self.assertIn('class="route-stop-badges"', self.source)
        self.assertNotIn('<span class="route-stop-badge start">Start here</span>', self.source)
        self.assertNotIn('>Start here</span>', self.source)
        self.assertIn('class="route-stop-action waypoint"', self.source)
        self.assertIn('<svg class="route-icon" viewBox="0 0 640 640" aria-hidden="true"><path d="M128 252.6', self.source)
        self.assertNotIn('<span class="route-stop-action waypoint"><span>◆</span>', self.source)
        self.assertIn("stop.user_waypoint&&commodityCount===0?' waypoint-only':''", self.source)
        self.assertIn('.route-stop-commodities.waypoint-only{grid-template-columns:minmax(0,1fr);grid-template-rows:1fr;grid-auto-flow:row;align-content:center;align-items:center}', self.source)
        self.assertNotIn('data-route-stop-toggle role="button" tabindex="0"', self.source)
        self.assertNotIn('function routeStopDetailGroup', self.source)
        self.assertNotIn('function toggleRouteStopDetails', self.source)
        self.assertIn('function routeStopCommodity(op,kind)', self.source)
        self.assertIn('<i>${CARGO_BOX_SVG}</i>', self.source)
        self.assertIn('class="route-stop-commodities${commodityCount===1?', self.source)
        self.assertIn("pickups.map(op=>routeStopCommodity(op,'pickup'))", self.source)
        self.assertIn("deliveries.map(op=>routeStopCommodity(op,'dropoff'))", self.source)
        self.assertIn('grid-template-rows:repeat(2,minmax(18px,auto));grid-auto-flow:column', self.source)
        self.assertIn('.route-stop-commodity{display:grid;grid-template-columns:14px minmax(0,1fr) auto;', self.source)
        self.assertIn("commodityCount===1?' single':''", self.source)
        self.assertIn('.route-timeline .route-stop-badges{grid-column:2;justify-self:start;gap:10px;margin:0;padding:0;border:0}', self.source)
        self.assertIn('.route-timeline .route-stop{grid-template-columns:123px 88px minmax(0,1fr);column-gap:0}', self.source)
        self.assertIn('.route-timeline .route-stop-badges{width:88px;box-sizing:border-box;justify-content:flex-end;padding-right:15px}', self.source)
        self.assertIn('grid-template-columns:repeat(4,minmax(0,1fr));grid-template-rows:repeat(2,minmax(18px,auto));grid-auto-flow:column', self.source)
        self.assertIn('padding-left:12px;border-left:1px solid rgba(255,255,255,.075)', self.source)
        self.assertIn('function routeStopIsComplete(stop,data)', self.source)
        self.assertIn('loadedMembers=new Set(data.loaded_member_identities||[])', self.source)
        self.assertIn('member&&loadedMembers.has(member)', self.source)
        self.assertIn('ids.length>0&&ids.every(id=>!!checklist[id])', self.source)
        self.assertIn("deliveries.every(operation=>completedContracts.has(String(operation.contract_id||'').toLowerCase()))", self.source)
        self.assertIn("${stopComplete?' complete-stop':''}", self.source)
        self.assertIn('.route-timeline .route-stop.complete-stop,.route-timeline .route-stop.start-stop.complete-stop{', self.source)
        self.assertIn('renderLogistics(cache);renderRoutePlanner(cache)', self.source)
        self.assertIn('"checklist_ids": [value for value in checklist_ids_by_member', self.source)
        self.assertIn('"member_identity": member_identity', self.source)
        self.assertIn("op.shared_quantity&&kind==='pickup'?'SCU not split'", self.source)
        self.assertIn('.route-timeline .route-stop-number,.route-timeline .start-stop .route-stop-number{left:-18px;', self.source)
        self.assertNotIn('class="route-action-title"', self.source)
        self.assertNotIn('class="route-cargo-list"', self.source)
        self.assertNotIn('class="route-leg-note"', self.source)
        self.assertIn("Custom route unlocked. Drag unfinished stops or add route anchors.", self.source)
        self.assertIn("function reorderedRouteStopIds(cards,sourceId,targetId,after)", self.source)
        self.assertIn("function routeDropAfter(cards,sourceId,targetId)", self.source)
        self.assertIn("sourceIndex<targetIndex", self.source)
        self.assertIn("stopIds.splice(targetIndex+(after?1:0),0,sourceId)", self.source)
        self.assertNotIn("target.parentNode.insertBefore(source", self.source)
        self.assertNotIn("event.clientY>rect.top+rect.height/2", self.source)
        self.assertIn("route-drop-before", self.source)
        self.assertIn("route-drop-after", self.source)
        self.assertIn("routeReorderPending=true", self.source)
        self.assertIn('id="routeCustomTools"', self.source)
        self.assertIn('Add Start Waypoint', self.source)
        self.assertIn('Add Final Waypoint', self.source)
        self.assertIn("routeLocationPicker('between','Add Waypoint'", self.source)
        self.assertIn('class="route-inline-popover"', self.source)
        self.assertIn('data-route-picker-confirm', self.source)
        self.assertIn('id="routeReoptimizeBtn" disabled>Reoptimize route', self.source)
        self.assertIn('id="routeConfirmBtn" disabled>Confirm route', self.source)
        self.assertIn('id="routeCustomBtn" type="button" disabled>Custom', self.source)
        self.assertIn("const manuallyEdited=routeCustomMode&&!!route.dirty", self.source)
        self.assertIn("$('routeReoptimizeBtn').disabled=!manuallyEdited", self.source)
        self.assertIn("$('routeConfirmBtn').disabled=!manuallyEdited", self.source)
        self.assertIn("after_stop_id:afterStopId", self.source)
        self.assertIn("$('routeCustomTools').hidden=!routeCustomMode||!route.valid", self.source)
        self.assertIn("const ROUTE_PLUS_SVG=", self.source)
        self.assertIn(".route-inline-insert.editing .route-add-waypoint-button{display:none}", self.source)
        self.assertIn(".route-add-waypoint-button{height:28px;min-width:132px", self.source)
        self.assertIn(".route-inline-insert{min-height:40px;margin-left:0}", self.source)
        self.assertIn(".route-inline-insert.start,.route-inline-insert.final{margin-left:18px}", self.source)
        self.assertIn(".route-inline-insert.start .route-add-waypoint-button,.route-inline-insert.final .route-add-waypoint-button{min-width:132px;height:28px", self.source)
        self.assertIn('.route-inline-popover input{font-family:"Segoe UI Variable Text","Segoe UI",Inter,Arial,sans-serif;font-weight:500;letter-spacing:normal}', self.source)
        self.assertIn(".route-timeline .route-stop-connector{height:40px}", self.source)
        self.assertIn("if(!query){hideRouteLocationMenu(input);return}", self.source)
        self.assertIn("wrapper.classList.toggle('editing',opening)", self.source)
        self.assertIn(".route-inline-popover:not([hidden])", self.source)
        self.assertIn('"waypoint_uid": hashlib.sha1(', self.source)
        self.assertNotIn('if any(stop.get("location_id") == match.record.id for stop in stops):', self.source)
        reoptimize_block = self.source.split("        def reoptimize_custom_route", 1)[1].split(
            "        def add_custom_route_waypoint", 1
        )[0]
        self.assertIn("json.loads(json.dumps(stop)) for stop in custom.get(\"stops\") or []", reoptimize_block)
        self.assertIn("self._insert_custom_waypoints_optimally", reoptimize_block)
        self.assertIn('self.set_custom_route_endpoint("start", record.name)', reoptimize_block)
        self.assertIn('self.set_custom_route_endpoint("end", record.name)', reoptimize_block)
        self.assertNotIn('self.set_custom_route_endpoint("start", record.id)', reoptimize_block)
        self.assertNotIn('self.set_custom_route_endpoint("end", record.id)', reoptimize_block)
        self.assertIn("fixed_start=pending_start, fixed_end=pending_end, history_plan=custom", reoptimize_block)
        self.assertIn('raise ValueError(generated.get("error")', reoptimize_block)
        self.assertIn('completed_target["fixed_endpoint"] = endpoint', reoptimize_block)
        self.assertIn("original_workspaces = json.loads(json.dumps(self.route_workspaces))", reoptimize_block)
        self.assertIn("self.route_workspaces = original_workspaces", reoptimize_block)
        self.assertIn("except Exception:", reoptimize_block)
        self.assertNotIn("for waypoint_id in manual_waypoints", reoptimize_block)
        endpoint_block = self.source.split("        def set_custom_route_endpoint", 1)[1].split(
            "        def reoptimize_custom_route", 1
        )[0]
        self.assertIn("route_endpoint_promotion_index(stops, match.record.id, endpoint)", endpoint_block)
        self.assertIn("stop is target or not", endpoint_block)
        waypoint_insert_block = self.source.split("        def _insert_custom_waypoints_optimally", 1)[1].split(
            "        def optimize_active_route", 1
        )[0]
        self.assertIn('waypoint["user_waypoint"] = True', waypoint_insert_block)
        self.assertIn("ordered.insert(insert_index, waypoint)", waypoint_insert_block)
        self.assertNotIn('id="routeCustomStart"', self.source)
        self.assertNotIn('id="routeCustomEnd"', self.source)
        self.assertNotIn('id="routeCustomAddWaypoint"', self.source)
        self.assertIn("action:'reorder'", self.source)
        self.assertIn("action:'reoptimize_custom'", self.source)
        self.assertIn("action:'confirm_custom'", self.source)
        self.assertIn("action:'remove_custom_stop'", self.source)
        self.assertIn('data-route-stop-delete=', self.source)
        self.assertIn("preset==='custom_draft'", self.source)
        self.assertIn("customButton.disabled=!route.custom_available", self.source)
        self.assertIn("self.route_workspaces[\"custom\"] = confirmed", self.source)
        self.assertIn("self.route_workspaces.pop(\"custom_draft\", None)", self.source)
        self.assertIn('"confirmed": True, "dirty": False', self.source)
        self.assertIn('Personal stop', self.source)
        self.assertIn('No cargo action at this waypoint', self.source)
        self.assertIn("state.clear_active_route()", self.source)
        self.assertIn('action:\'clear\'', self.source)
        self.assertNotIn('id="routeContractLabel"', self.source)
        self.assertNotIn('Contracts · ${includedCount}', self.source)
        self.assertNotIn('class="route-body"', self.source)
        self.assertNotIn('class="route-sidebar"', self.source)

    def test_contract_editor_location_fields_use_catalog_autocomplete(self):
        self.assertIn('data-field="pickup" autocomplete="off" role="combobox"', self.source)
        self.assertIn('data-field="dropoff" autocomplete="off" role="combobox"', self.source)
        self.assertIn('class="location-autocomplete" role="listbox"', self.source)
        self.assertIn("ensureEditorLocationOptions", self.source)
        self.assertIn("option.subtitle||option.system||'Location'", self.source)
        self.assertIn("menu.classList.toggle('open-up',openUp)", self.source)
        self.assertIn("openUp?above:below", self.source)
        self.assertIn('parsed.path == "/api/locations"', self.source)
        self.assertIn("canonicalize_contract_objective_locations(objectives, self.location_catalog)", self.source)
        self.assertIn('data-pickup-source-section=', self.source)
        self.assertIn("self._sync_automatic_bug_overrides()", self.source)

    def test_route_input_changes_clear_stale_results_and_cannot_race_optimize(self):
        invalidate_block = self.source.split("        def invalidate_route_inputs", 1)[1].split(
            "        def _save_ocr_settings", 1
        )[0]
        self.assertIn("self.route_plan = self.route_workspaces.get(self.route_preset)", invalidate_block)
        self.assertIn("async function optimizeRoute(silent=false,force=false){clearTimeout(routeInvalidateTimer);routeInvalidateTimer=null;", self.source)
        self.assertNotIn("$('optimizeRouteBtn')", self.source)
        self.assertIn("await optimizeRoute(true)", self.source)
        self.assertIn("function scheduleRouteOptimization()", self.source)
        self.assertIn("scheduleRouteOptimization()", self.source)
        self.assertIn("if(r.ok&&j.ok)render(j.state)", self.source)
        self.assertNotIn("Route inputs changed · outdated", self.source)

    def test_reset_clears_saved_routes_and_all_active_recalculates_stale_results(self):
        reset_block = self.source.split("        def reset_session(self):", 2)[2].split(
            "        def start_watch", 1
        )[0]
        self.assertIn("self.route_workspaces = {}", reset_block)
        self.assertIn('self.route_preset = "all"', reset_block)
        self.assertIn("self.route_selected_contracts = []", reset_block)
        self.assertIn("self.route_waypoints = []", reset_block)
        self.assertIn("self._save_route_settings()", reset_block)
        self.assertIn("if(!j.route||!j.route.valid||j.route.outdated)await optimizeRoute(true)", self.source)


if __name__ == "__main__":
    unittest.main()
