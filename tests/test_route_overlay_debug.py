import json
import unittest
from pathlib import Path

import sc_hauling_tracker as tracker


class RouteOverlayDebugScenarioTest(unittest.TestCase):
    def setUp(self):
        self.scenarios = tracker.route_overlay_debug_scenarios()

    def test_scenario_matrix_is_complete_and_json_serializable(self):
        self.assertEqual(
            {
                "no-route", "outdated", "pickup", "pickup-overflow",
                "dropoff", "dropoff-overflow", "mixed", "mixed-overflow",
                "waypoint", "warning", "advanced", "final-stop", "complete",
            },
            set(self.scenarios),
        )
        json.dumps(self.scenarios)
        for scenario_id, scenario in self.scenarios.items():
            with self.subTest(scenario=scenario_id):
                self.assertTrue(scenario["title"])
                self.assertIn("route", scenario["state"])
                self.assertIn("checklist", scenario["state"])

    def test_action_and_overflow_fixtures_have_expected_cargo(self):
        def active(scenario_id):
            state = self.scenarios[scenario_id]["state"]
            return next(stop for stop in state["route"]["stops"] if not stop.get("historical"))

        pickup = active("pickup")
        dropoff = active("dropoff")
        mixed = active("mixed")
        mixed_overflow = active("mixed-overflow")
        self.assertTrue(pickup["pickups"])
        self.assertFalse(pickup["deliveries"])
        self.assertFalse(dropoff["pickups"])
        self.assertTrue(dropoff["deliveries"])
        self.assertTrue(mixed["pickups"] and mixed["deliveries"])
        self.assertGreater(len(mixed_overflow["pickups"]), len(mixed["pickups"]))
        self.assertGreater(len(mixed_overflow["deliveries"]), len(mixed["deliveries"]))

    def test_waypoint_warning_final_and_terminal_states_are_represented(self):
        waypoint = next(
            stop for stop in self.scenarios["waypoint"]["state"]["route"]["stops"]
            if stop.get("stop_id") == "waypoint"
        )
        warning = next(
            stop for stop in self.scenarios["warning"]["state"]["route"]["stops"]
            if stop.get("stop_id") == "warning"
        )
        final_stops = self.scenarios["final-stop"]["state"]["route"]["stops"]
        self.assertTrue(waypoint["user_waypoint"])
        self.assertFalse(waypoint["pickups"] or waypoint["deliveries"])
        self.assertTrue(warning["warnings"])
        self.assertEqual("final", final_stops[-1]["stop_id"])
        self.assertEqual(61000, final_stops[-1]["distance_from_previous"])
        self.assertEqual("Stanton system", final_stops[-1]["parent_body"])
        self.assertFalse(self.scenarios["no-route"]["state"]["route"]["valid"])
        self.assertTrue(self.scenarios["outdated"]["state"]["route"]["outdated"])
        self.assertTrue(all(
            stop.get("historical")
            for stop in self.scenarios["complete"]["state"]["route"]["stops"]
        ))

    def test_loaded_pickup_fixture_advances_to_dropoff(self):
        state = self.scenarios["advanced"]["state"]
        loaded_pickup, dropoff = state["route"]["stops"]
        expected_ids = {
            checklist_id
            for operation in loaded_pickup["pickups"]
            for checklist_id in operation["checklist_ids"]
        }
        self.assertEqual(expected_ids, set(state["checklist"]))
        self.assertTrue(all(state["checklist"].values()))
        self.assertTrue(dropoff["deliveries"])

    def test_debug_gallery_uses_the_real_overlay_and_is_cli_launchable(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn("ROUTE_OVERLAY_DEBUG_HTML", source)
        self.assertIn('src="/route-overlay?debug_scenario=', source)
        self.assertIn('parsed.path == "/route-overlay-debug"', source)
        self.assertIn('parsed.path == "/api/debug/route-overlay-state"', source)
        self.assertIn('"--debug-route-overlay"', source)
        self.assertIn("if(debugScenario){cache.checklist=checklist;render(cache);return}", source)


if __name__ == "__main__":
    unittest.main()
