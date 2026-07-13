import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sc_hauling_tracker as tracker  # noqa: E402


class ParserRegressionTest(unittest.TestCase):
    def setUp(self):
        text = (ROOT / "test_data" / "Debug_Game.log").read_text(encoding="utf-8", errors="replace")
        self.missions, self.events = tracker.parse_log_data(text)
        self.groups = tracker.contract_groups(self.missions)

    def test_debug_log_contract_counts(self):
        accepted = sum(1 for group in self.groups if tracker.group_active(group))
        completed = sum(1 for group in self.groups if tracker.group_completed(group))
        abandoned = sum(1 for group in self.groups if tracker.group_abandoned(group))
        payout = sum(tracker.group_payout(group) or 0 for group in self.groups if tracker.group_completed(group))

        self.assertEqual(len(self.missions), 19)
        self.assertEqual(len(self.groups), 9)
        self.assertEqual(len(self.events), 6)
        self.assertEqual((accepted, completed, abandoned), (3, 3, 3))
        self.assertEqual(payout, 383750)

    def test_logistics_sections_stay_grouped(self):
        sections = tracker.logistics_sections(self.missions)

        self.assertEqual(len(sections), 2)
        self.assertEqual(sum(section["objective_count"] for section in sections), 7)
        self.assertTrue(all(section["columns"] for section in sections))



class StackedContracts48RegressionTest(unittest.TestCase):
    def setUp(self):
        text = (ROOT / "test_data" / "Game_4_8_five_stacked_contracts.log").read_text(
            encoding="utf-8", errors="replace"
        )
        self.missions, self.events = tracker.parse_log_data(text)
        self.groups = tracker.contract_groups(self.missions)

    def test_five_stacked_contracts_keep_their_own_mission_ids(self):
        self.assertEqual(len(self.groups), 5)
        self.assertEqual(len({group[0].mission_id for group in self.groups}), 5)
        self.assertEqual(len(self.missions), 15)
        self.assertEqual(len(self.events), 0)

    def test_five_stacked_contracts_match_real_48_manifest(self):
        quartz = self.groups[0]
        self.assertEqual(
            [(m.dropoff, m.scu, m.scu_provenance) for m in quartz],
            [
                ("Teasa Spaceport", "9", "exact_log"),
                ("HDPC-Cassillo", "4", "exact_log"),
                ("HDPC-Farnesway", "8", "exact_log"),
            ],
        )
        marker_only = [mission for group in self.groups[1:] for mission in group]
        self.assertTrue(all(m.pickup == "Everus Harbor" for m in self.missions))
        self.assertTrue(all(m.scu == "" for m in marker_only))
        self.assertTrue(all(m.scu_provenance == "unknown" for m in marker_only))
        self.assertTrue(all(tracker.group_payout(group) is None for group in self.groups))
        self.assertEqual(sum(int(m.scu) for m in self.missions if m.scu), 21)

    def test_previous_quartz_notifications_do_not_leak_into_later_contracts(self):
        for group in self.groups[1:]:
            self.assertFalse(any(mission.commodity == "Quartz" for mission in group))
            self.assertEqual(len(group), 3)


class SequentialContracts48RegressionTest(unittest.TestCase):
    def setUp(self):
        text = (ROOT / "test_data" / "Game_4_8_seven_sequential_contracts.log").read_text(
            encoding="utf-8", errors="replace"
        )
        self.missions, self.events = tracker.parse_log_data(text)
        self.groups = tracker.contract_groups(self.missions)

    def test_seven_contract_capture_uses_only_game_log_authority(self):
        self.assertEqual(
            [(m.dropoff, m.scu, m.scu_provenance) for m in self.groups[0]],
            [
                ("Teasa Spaceport", "5", "exact_log"),
                ("HDPC-Farnesway", "5", "exact_log"),
                ("Sakura Sun Magnolia Workcenter", "9", "exact_log"),
            ],
        )
        for group in self.groups[1:]:
            self.assertTrue(all(m.scu == "" for m in group))
            self.assertTrue(all(m.scu_provenance == "unknown" for m in group))
            self.assertIsNone(tracker.group_payout(group))
        self.assertEqual(len(self.groups), 7)
        self.assertEqual(len(self.missions), 22)
        self.assertEqual(sum(int(m.scu) for m in self.missions if m.scu), 19)
        self.assertEqual(len({g[0].mission_id for g in self.groups}), 7)

    def test_same_definition_can_have_different_corundum_routes(self):
        corundum = [g for g in self.groups if g[0].commodity == "Corundum"]
        self.assertEqual(len(corundum), 2)
        self.assertEqual([len(g) for g in corundum], [4, 3])
        self.assertNotEqual([(m.dropoff, m.objective_id) for m in corundum[0]], [(m.dropoff, m.objective_id) for m in corundum[1]])


class MarkerFallbackRegressionTest(unittest.TestCase):
    def test_unknown_mission_infers_commodity_and_destinations_without_inventing_scu(self):
        mission_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        lines = [
            f'<2026-07-11T15:00:00.000Z> [Notice] <CLocalMissionPhaseMarker::CreateMarker> Creating objective marker: missionId [{mission_id}], generator name [Covalex_Hauling], contract [HaulCargo_SingleToMulti3_RefinedOre_Beryl_Stanton1_SmallGrade], objectiveId [dropoff_test_0], position [x: 129223.337423, y: 63887.560398, z: 989574.572256]',
            f'<2026-07-11T15:00:00.000Z> [Notice] <CLocalMissionPhaseMarker::CreateMarker> Creating objective marker: missionId [{mission_id}], generator name [Covalex_Hauling], contract [HaulCargo_SingleToMulti3_RefinedOre_Beryl_Stanton1_SmallGrade], objectiveId [dropoff_test_1], position [x: -789715.940114, y: 615354.400685, z: -2353.089599]',
            f'<2026-07-11T15:00:00.000Z> [Notice] <CLocalMissionPhaseMarker::CreateMarker> Creating objective marker: missionId [{mission_id}], generator name [Covalex_Hauling], contract [HaulCargo_SingleToMulti3_RefinedOre_Beryl_Stanton1_SmallGrade], objectiveId [dropoff_test_2], position [x: -328668.005842, y: -756979.728559, z: 566539.556724]',
            f'<2026-07-11T15:00:00.010Z> [Notice] <SHUDEvent_OnNotification> Added notification "Contract Accepted: Member | Small Haul | from Everus Harbor <EM4>[BP]*</EM4>: " to queue. MissionId: [{mission_id}], ObjectiveId: []',
        ]
        missions = tracker.parse_block(4, lines)
        self.assertEqual([(m.commodity, m.dropoff) for m in missions], [
            ("Beryl", "HDPC-Farnesway"),
            ("Beryl", "HDPC-Cassillo"),
            ("Beryl", "Teasa Spaceport"),
        ])
        self.assertTrue(all(m.scu == "" for m in missions))
        self.assertTrue(all(m.payout_auec is None for m in missions))
        self.assertTrue(all("not emitted by Game.log" in m.notes for m in missions))

    def test_manual_override_replaces_only_exact_mission_id(self):
        mission = tracker.CargoMission(
            title="Member | Small Haul | from Everus Harbor", rank="Member", pickup="Everus Harbor",
            dropoff="HDPC-Farnesway", commodity="Beryl", scu="", confidence=65, notes="needs review",
            raw="", mission_id="mission-one", timestamp="2026-07-11T15:00:00Z", source_line=1, contract_uid="uid-one"
        )
        other = tracker.CargoMission(
            title="Member | Small Haul | from Everus Harbor", rank="Member", pickup="Everus Harbor",
            dropoff="HDPC-Cassillo", commodity="Beryl", scu="", confidence=65, notes="needs review",
            raw="", mission_id="mission-two", timestamp="2026-07-11T15:01:00Z", source_line=2, contract_uid="uid-two"
        )
        overridden = tracker.apply_contract_overrides([mission, other], {
            "mission-one": {"payout": 12345, "objectives": [("Everus Harbor", "Teasa Spaceport", "Beryl", "7")]}
        })
        groups = tracker.contract_groups(overridden)
        first = next(g for g in groups if g[0].mission_id == "mission-one")
        second = next(g for g in groups if g[0].mission_id == "mission-two")
        self.assertEqual((first[0].dropoff, first[0].scu, tracker.group_payout(first)), ("Teasa Spaceport", "7", 12345))
        self.assertEqual((second[0].dropoff, second[0].scu), ("HDPC-Cassillo", ""))


class MissionFirstParsingRegressionTest(unittest.TestCase):
    def parse_lines(self, lines):
        return tracker.parse_log_data("\n".join(lines))[0]

    def accepted(self, mission_id, contract="HaulCargo_SingleToMulti2_Processed_Stims_Stanton1_SmallGrade1", rank="Rookie"):
        return f'<2026-07-11T15:00:00.010Z> [Notice] <SHUDEvent_OnNotification> Added notification "Contract Accepted:  {rank} | Small Haul | from Everus Harbor <EM4>[BP]*</EM4>: " to queue. MissionId: [{mission_id}], ObjectiveId: [] [Team_CoreGameplayFeatures][Missions][Comms]'

    def marker(self, mission_id, objective_id, x, y, z, contract="HaulCargo_SingleToMulti2_Processed_Stims_Stanton1_SmallGrade1"):
        return f'<2026-07-11T15:00:00.000Z> [Notice] <CLocalMissionPhaseMarker::CreateMarker> Creating objective marker: missionId [{mission_id}], generator name [Covalex_Hauling], contract [{contract}], objectiveId [{objective_id}], position [x: {x}, y: {y}, z: {z}]'

    def exact(self, mission_id, objective_id, text):
        return f'<2026-07-11T15:00:00.020Z> [Notice] <SHUDEvent_OnNotification> Added notification "{text}" to queue. MissionId: [{mission_id}], ObjectiveId: [{objective_id}]'

    def test_mission_and_objective_ids_isolate_exact_objectives(self):
        mission_a = "716e3719-73b2-42b4-bd18-4d02844ef18c"
        mission_b = "aaaaaaaa-73b2-42b4-bd18-4d02844ef18c"
        missions = self.parse_lines([
            self.accepted(mission_a, "HaulCargo_SingleToMulti3_RefinedOre_Quartz_Stanton1_SmallGrade", "Member"),
            self.exact(mission_a, "dropoff_q_0", "New Objective: Deliver 0/5 SCU of Quartz to Teasa Spaceport: "),
            '   "New Objective: Deliver 0/99 SCU of Quartz to Teasa Spaceport: " [queue echo]',
            self.exact(mission_a, "dropoff_q_1", "New Objective: Deliver 0/7 SCU of Quartz to HDPC-Farnesway: "),
            self.exact(mission_a, "dropoff_q_2", "New Objective: Deliver 0/10 SCU of Quartz to Sakura Sun Magnolia Workcenter: "),
            self.accepted(mission_b, "HaulCargo_SingleToMulti3_RefinedOre_Quartz_Stanton1_SmallGrade", "Member"),
            self.exact(mission_b, "dropoff_q_0", "New Objective: Deliver 0/9 SCU of Quartz to HDPC-Cassillo: "),
        ])
        group = next(g for g in tracker.contract_groups(missions) if g[0].mission_id == mission_a)
        self.assertEqual([(m.dropoff, m.scu, m.objective_id) for m in group], [
            ("Teasa Spaceport", "5", "dropoff_q_0"),
            ("HDPC-Farnesway", "7", "dropoff_q_1"),
            ("Sakura Sun Magnolia Workcenter", "10", "dropoff_q_2"),
        ])
        self.assertEqual(sum(int(m.scu) for m in group), 22)
        self.assertTrue(all(m.data_provenance == "exact_log" for m in group))

    def test_notification_deduplicates_by_mission_objective_and_content(self):
        mission_id = "bbbbbbbb-73b2-42b4-bd18-4d02844ef18c"
        missions = self.parse_lines([
            self.accepted(mission_id, "HaulCargo_SingleToMulti2_RefinedOre_Quartz_Stanton1_SmallGrade", "Member"),
            self.exact(mission_id, "dropoff_q_0", "New Objective: Deliver 0/5 SCU of Quartz to Teasa Spaceport: "),
            self.exact(mission_id, "dropoff_q_0", "New Objective: Deliver 0/5 SCU of Quartz to Teasa Spaceport: "),
        ])
        self.assertEqual(len(missions), 1)
        self.assertEqual((missions[0].scu, missions[0].objective_id), ("5", "dropoff_q_0"))

    def test_endmission_lifecycle_marks_contract_complete_by_mission_id(self):
        mission_id = "dddddddd-73b2-42b4-bd18-4d02844ef18c"
        missions, events = tracker.parse_log_data("\n".join([
            self.accepted(mission_id, "HaulCargo_SingleToMulti2_RefinedOre_Quartz_Stanton1_SmallGrade", "Member"),
            self.exact(mission_id, "dropoff_q_0", "New Objective: Deliver 0/5 SCU of Quartz to Teasa Spaceport: "),
            f"<2026-07-11T15:05:00.000Z> [Notice] <EndMission> MissionId[{mission_id}] CompletionType[Complete] Reason[ObjectiveComplete]",
        ]))
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].is_completion)
        self.assertEqual(events[0].mission_id, mission_id)
        self.assertTrue(tracker.group_completed(tracker.contract_groups(missions)[0]))
        self.assertIsNone(tracker.group_payout(tracker.contract_groups(missions)[0]))

    def test_same_millisecond_endmission_stack_keeps_every_mission_id(self):
        mission_ids = [
            f"{index:08d}-1111-4222-8333-444444444444"
            for index in range(1, 7)
        ]
        lines = []
        for mission_id in mission_ids:
            lines.extend([
                f"<2026-07-13T06:53:15.249Z> [Notice] <MissionEnded> Received MissionEnded push message for: mission_id {mission_id} - mission_state MISSION_STATE_COMPLETED",
                f"<2026-07-13T06:53:15.249Z> [Notice] <EndMission> Ending mission for player. MissionId[{mission_id}] CompletionType[Complete] Reason[Mission Ended]",
            ])

        events = tracker.parse_completion_events(lines)

        self.assertEqual([event.mission_id for event in events], mission_ids)
        self.assertTrue(all(event.is_completion for event in events))

    def test_marker_only_stims_keeps_scu_and_payout_unknown(self):
        mission_id = "cccccccc-73b2-42b4-bd18-4d02844ef18c"
        missions = self.parse_lines([
            self.marker(mission_id, "dropoff_0", "129223.337423", "63887.560398", "989574.572256"),
            self.marker(mission_id, "dropoff_1", "-789715.940114", "615354.400685", "-2353.089599"),
            self.marker(mission_id, "pickup_0", "-507742.312500", "-903464.437500", "496489.062500"),
            self.accepted(mission_id),
        ])
        self.assertEqual([(m.pickup, m.dropoff, m.commodity, m.scu) for m in missions], [
            ("Everus Harbor", "HDPC-Farnesway", "Stims", ""),
            ("Everus Harbor", "HDPC-Cassillo", "Stims", ""),
        ])
        self.assertTrue(all(m.scu_provenance == "unknown" for m in missions))
        self.assertIsNone(tracker.group_payout(tracker.contract_groups(missions)[0]))
        self.assertEqual(tracker.logistics_sections(missions), [])

    def test_waste_aggregate_quantity_not_multiplied_across_pickups(self):
        mission_id = "456a6b4d-8093-4796-8058-3b0aeb33772d"
        contract = "HaulCargo_Multi4ToSingle_Waste_Waste_Stanton1_SmallGrade1"
        missions = self.parse_lines([
            self.marker(mission_id, "pickup_0", "-229373.108770", "-864792.873355", "-446960.041887", contract),
            self.marker(mission_id, "pickup_1", "742846.530000", "15480.080000", "671073.620000", contract),
            self.marker(mission_id, "pickup_2", "-789715.940114", "615354.400685", "-2353.089599", contract),
            self.marker(mission_id, "pickup_3", "129223.337423", "63887.560398", "989574.572256", contract),
            self.marker(mission_id, "dropoff_0", "-507742.312500", "-903464.437500", "496489.062500", contract),
            self.accepted(mission_id, contract, "Member"),
            self.exact(mission_id, "dropoff_0", "New Objective: Deliver 0/15 SCU of Waste to Everus Harbor: "),
        ])
        self.assertEqual(len(missions), 4)
        self.assertEqual([m.scu for m in missions], ["15", "", "", ""])
        self.assertEqual(sum(int(m.scu) for m in missions if m.scu), 15)
        self.assertTrue(all(m.quantity_scope == "aggregate" for m in missions))
        sections = tracker.logistics_sections(missions)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["mode"], "aggregate_pickups")
        self.assertEqual(sections[0]["fixed_location"], "Everus Harbor")
        self.assertEqual(sections[0]["total"], "15")
        self.assertEqual(sections[0]["objective_count"], 4)
        self.assertEqual(len(sections[0]["pickup_options"]), 4)
        self.assertEqual(len(sections[0]["columns"]), 4)
        self.assertTrue(all(len(column["items"]) == 1 for column in sections[0]["columns"]))
        self.assertTrue(all(column["items"][0]["scu"] == "" for column in sections[0]["columns"]))
        self.assertEqual(sections[0]["shared_scu"], "15")

    def test_mixed_and_iron_contract_tokens_decode_without_quantities(self):
        mixed_id = "1ebe87bf-1707-4aea-87bd-46af16a7310a"
        mixed_contract = "HaulCargo_SingleToMulti2_Processed_Mixed_PressIceProcFood_Stanton1_SmallGrade"
        iron_id = "0874d0a2-824f-4873-a565-20ea45576d78"
        iron_contract = "HaulCargo_Multi2ToSingle_RawOre_Iron_Stanton1_SmallGrade1"
        missions = self.parse_lines([
            self.marker(mixed_id, "dropoff_0", "742846.530000", "15480.080000", "671073.620000", mixed_contract),
            self.marker(mixed_id, "dropoff_1", "-229373.108770", "-864792.873355", "-446960.041887", mixed_contract),
            self.marker(mixed_id, "pickup_0", "-507742.312500", "-903464.437500", "496489.062500", mixed_contract),
            self.accepted(mixed_id, mixed_contract, "Member"),
            self.marker(iron_id, "pickup_0", "129223.337423", "63887.560398", "989574.572256", iron_contract),
            self.marker(iron_id, "pickup_1", "-789715.940114", "615354.400685", "-2353.089599", iron_contract),
            self.marker(iron_id, "dropoff_0", "-507742.312500", "-903464.437500", "496489.062500", iron_contract),
            self.accepted(iron_id, iron_contract, "Junior"),
        ])
        groups = {g[0].mission_id: g for g in tracker.contract_groups(missions)}
        self.assertEqual({m.commodity for m in groups[mixed_id]}, {"Pressurized Ice", "Processed Food"})
        self.assertEqual(len(groups[mixed_id]), 4)
        self.assertTrue(all(m.scu == "" for m in groups[mixed_id]))
        self.assertEqual({m.commodity for m in groups[iron_id]}, {"Iron (Ore)"})
        self.assertEqual({m.pickup for m in groups[iron_id]}, {"HDPC-Farnesway", "HDPC-Cassillo"})
        self.assertTrue(all(m.scu == "" for m in groups[iron_id]))

    def test_ocr_text_parser_extracts_review_candidates(self):
        parsed = tracker.parse_contract_details_text(
            """
            Reward: 65,250 aUEC
            Pressurized Ice 6 SCU to Covalex Distribution Center S1DC06
            Processed Food 4 SCU to Sakura Sun Magnolia Workcenter
            """,
            [],
        )
        self.assertEqual(parsed["payout"], 65250)
        self.assertEqual(parsed["objectives"], [
            {
                "pickup": "Everus Harbor",
                "dropoff": "Covalex Distribution Center S1DC06",
                "commodity": "Pressurized Ice",
                "scu": "6",
            },
            {
                "pickup": "Everus Harbor",
                "dropoff": "Sakura Sun Magnolia Workcenter",
                "commodity": "Processed Food",
                "scu": "4",
            },
        ])



    def test_ocr_parser_handles_two_stims_routes_and_letter_digits(self):
        parsed = tracker.parse_contract_details_text(
            """
            PRIMARY OBJECTIVES
            Deliver O/4 SCU of Stims to HDMS-Norgaard on Aberdeen.
            Collect Stims from Everus Harbor.
            Deliver 0/S SCU of Stims to HDMS-Anderson on Aberdeen.
            Collect Stims from Everus Harbor.
            """,
            [],
        )
        self.assertEqual(parsed["objectives"], [
            {"pickup": "Everus Harbor", "dropoff": "HDMS-Norgaard", "commodity": "Stims", "scu": "4"},
            {"pickup": "Everus Harbor", "dropoff": "HDMS-Anderson", "commodity": "Stims", "scu": "5"},
        ])

    def test_ocr_parser_keeps_every_pickup_for_one_shared_delivery_quantity(self):
        parsed = tracker.parse_contract_details_text(
            """
            PRIMARY OBJECTIVES
            Deliver 0/6 SCU of Iron (Ore) to Everus Harbor above Hurston.
            Collect Iron (Ore) from HDMS-Hahn.
            Collect Iron (Ore) from HDMS-Perlman.
            """,
            [],
        )
        self.assertEqual(parsed["objectives"], [
            {
                "pickup": "HDMS-Hahn",
                "dropoff": "Everus Harbor",
                "commodity": "Iron (Ore)",
                "scu": "6",
                "quantity_scope": "aggregate",
            },
            {
                "pickup": "HDMS-Perlman",
                "dropoff": "Everus Harbor",
                "commodity": "Iron (Ore)",
                "scu": "",
                "quantity_scope": "aggregate",
            },
        ])

    def test_reward_parser_reads_s_as_five_in_targeted_crop(self):
        self.assertEqual(tracker.parse_reward_amount("Reward 48,S00"), 48500)

    def test_reward_parser_accepts_ocr_zero_substitutions(self):
        self.assertEqual(tracker.parse_reward_amount("Reward 65,25O aUEC"), 65250)
        self.assertEqual(tracker.parse_reward_amount("Reward Contract Deadline 99.5OO N/A"), 99500)

    def test_targeted_reward_pass_fills_missing_full_screen_payout(self):
        parsed = tracker.merge_contract_ocr_passes(
            "PRIMARY OBJECTIVES Deliver 0/7 SCU of Pressurized Ice to Covalex Distribution Center S1DC06. Collect Pressurized Ice from Everus Harbor.",
            "Reward Contract Deadline Contracted By 65,250 N/A Covalex Independent Contractors",
            "",
            [],
        )
        self.assertEqual(parsed["payout"], 65250)
        self.assertEqual(len(parsed["objectives"]), 1)

    def test_ocr_text_parser_filters_contract_screen_noise(self):
        parsed = tracker.parse_contract_details_text(
            """
            MARK ALL READ & MERCENARY HAULING - PLANETARY MEMBER I SMALL HAUL 1 FROM EVERUS HARBOR
            COVALEX INDEPENDENT CONTRACTORS Ž 6,714,891 EUGENESW OFFERS ACCEPTED (2/10) HISTORY BEACONS
            Reward Contract Deadline Contracted By Ž 99.500 N/A Covalex Independent Contractors A 99k lh 4m
            Member I Small Haul I from Everus Harbor DETAILS Greetings, Seems like Everus Harbor above Hurston currently has some
            4 SCU or smaller cargo that needs to be separated and delivered to a few different spots.
            PRIMARY OBJECTIVES O O O ASSETS
            Deliver 0/5 SCU of Quartz to HDPC-Farnesway on Hurston. O Collect Quartz from Everus Harbor.
            Deliver 0/7 SCU of Quartz to Teasa Spaceport in Lorville. o Collect Quartz from Everus Harbor.
            Deliver 0/7 SCU of Quartz to HDPC-CassiIIo on Hurston. O Collect Quartz from Everus Harbor.
            SHARE TRACK HOME HEALTH COMMS CONTRACTS MAPS JOURNAL REP WALLET LANDING VEHICLES
            """,
            [],
        )
        self.assertEqual(parsed["payout"], 99500)
        self.assertEqual(parsed["contracted_by"], "Covalex Independent Contractors")
        self.assertEqual(parsed["objectives"], [
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Farnesway", "commodity": "Quartz", "scu": "5"},
            {"pickup": "Everus Harbor", "dropoff": "Teasa Spaceport", "commodity": "Quartz", "scu": "7"},
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Cassillo", "commodity": "Quartz", "scu": "7"},
        ])

    def test_ocr_parser_prefers_leading_partial_facility_over_later_prose_location(self):
        parsed = tracker.parse_contract_details_text(
            """
            PRIMARY OBJECTIVES
            Deliver 0/4 SCU of Aluminum to Sakura Sun Magnolia
            Seems like Everus Harbor above Hurston currently has some 1 SCU or smaller cargo.
            DROP OFF LOCATIONS (ANY ORDER)
            - Freight elevator at Sakura Sun Magnolia Workcenter on Hurston
            - Freight elevator at HDPC-Cassillo on Hurston
            Deliver 0/5 SCU of Aluminum to HDPC-Cassillo on Hurston.
            Collect Aluminum from Everus Harbor.
            """,
            [],
        )
        self.assertEqual(parsed["objectives"], [
            {"pickup": "Everus Harbor", "dropoff": "Sakura Sun Magnolia Workcenter", "commodity": "Aluminum", "scu": "4"},
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Cassillo", "commodity": "Aluminum", "scu": "5"},
        ])

    def test_contract_override_stores_contractor_metadata(self):
        mission = tracker.CargoMission(
            title="Member Small Haul",
            rank="Member",
            pickup="Everus Harbor",
            dropoff="Unknown drop-off",
            commodity="Quartz",
            scu="",
            mission_id="mission-1",
        )
        updated = tracker.apply_contract_overrides([mission], {
            "mission-1": {
                "payout": 99500,
                "contracted_by": "Covalex Independent Contractors",
                "objectives": [
                    {"pickup": "Everus Harbor", "dropoff": "HDPC-Farnesway", "commodity": "Quartz", "scu": "5"},
                ],
            }
        })
        self.assertEqual(updated[0].contracted_by, "Covalex Independent Contractors")
        self.assertEqual(updated[0].payout_auec, 99500)

    def test_ocr_text_parser_can_apply_amounts_to_existing_unknown_rows(self):
        parsed = tracker.parse_contract_details_text(
            "5 SCU\n7 SCU",
            [
                {"pickup": "Everus Harbor", "dropoff": "HDPC-Farnesway", "commodity": "Stims", "scu": ""},
                {"pickup": "Everus Harbor", "dropoff": "HDPC-Cassillo", "commodity": "Stims", "scu": ""},
            ],
        )
        self.assertEqual([row["scu"] for row in parsed["objectives"]], ["5", "7"])
        self.assertEqual([row["dropoff"] for row in parsed["objectives"]], ["HDPC-Farnesway", "HDPC-Cassillo"])


class AutomaticOcrParsingRegressionTest(unittest.TestCase):
    def test_clipped_auto_ocr_quantities_map_to_marker_route_order(self):
        hints = [
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Farnesway", "commodity": "Aluminum", "scu": "", "objective_id": "dropoff_route_1", "provenance": "marker_resolved"},
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Cassillo", "commodity": "Aluminum", "scu": "", "objective_id": "dropoff_route_2", "provenance": "marker_resolved"},
            {"pickup": "Everus Harbor", "dropoff": "Sakura Sun Magnolia Workcenter", "commodity": "Aluminum", "scu": "", "objective_id": "dropoff_route_0", "provenance": "marker_resolved"},
            {"pickup": "Everus Harbor", "dropoff": "Teasa Spaceport", "commodity": "Aluminum", "scu": "", "objective_id": "dropoff_route_3", "provenance": "marker_resolved"},
        ]
        text = (
            "PRIMARY OBJECTIVE "
            "O Deliver 0/4 SCU of Aluminu Workcenter on Hurston. o Collect Aluminum from E "
            "O Deliver 0/7 SCU of Aluminul Hurston. o Collect Aluminum from E "
            "O Deliver 0/4 SCU of Aluminu Hurston. o Collect Aluminum from "
            "O Deliver 0/5 SCU of Aluminu Lorville. o Collect Aluminum from"
        )
        parsed = tracker.parse_contract_details_text(text, hints)
        self.assertEqual(parsed["objectives"], [
            {"pickup": "Everus Harbor", "dropoff": "Sakura Sun Magnolia Workcenter", "commodity": "Aluminum", "scu": "4"},
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Farnesway", "commodity": "Aluminum", "scu": "7"},
            {"pickup": "Everus Harbor", "dropoff": "HDPC-Cassillo", "commodity": "Aluminum", "scu": "4"},
            {"pickup": "Everus Harbor", "dropoff": "Teasa Spaceport", "commodity": "Aluminum", "scu": "5"},
        ])

    def test_recent_star_citizen_screenshot_only_uses_current_job_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            screenshots = root / "screenshots"
            screenshots.mkdir()
            log = root / "Game.log"
            log.write_text("", encoding="utf-8")
            old = screenshots / "ScreenShot-old.jpg"
            old.write_bytes(b"old")
            fresh = screenshots / "ScreenShot-fresh.jpg"
            fresh.write_bytes(b"fresh")
            now = time.time()
            old_time = now - 120
            fresh_time = now - 1
            old.touch()
            fresh.touch()
            import os
            os.utime(old, (old_time, old_time))
            os.utime(fresh, (fresh_time, fresh_time))

            found = tracker.recent_star_citizen_screenshot(str(log), now - 5)
            self.assertEqual(found, fresh)
            skipped = tracker.recent_star_citizen_screenshot(str(log), now - 5, {str(fresh)})
            self.assertIsNone(skipped)

    def test_contract_page_readiness_requires_objective_panel(self):
        self.assertTrue(tracker.ocr_contract_page_ready("PRIMARY OBJECTIVES Deliver 0/5 SCU of Quartz to Teasa Spaceport"))
        self.assertFalse(tracker.ocr_contract_page_ready("Contract Accepted Member Small Haul"))

    def test_validation_rejects_wrong_visible_commodity(self):
        group = [tracker.CargoMission(
            title="Rookie Small Haul", rank="Rookie", pickup="Everus Harbor",
            dropoff="HDMS-Hahn", commodity="Stims", scu="", mission_id="m1"
        )]
        result = tracker.validate_ocr_contract_details({
            "payout": 99500,
            "objectives": [{"pickup": "Everus Harbor", "dropoff": "Teasa Spaceport", "commodity": "Quartz", "scu": "5"}],
        }, group)
        self.assertFalse(result["ok"])
        self.assertIn("commodity", result["reason"].lower())


    def test_validation_rejects_incomplete_multi_drop_ocr(self):
        raw = "contract [HaulCargo_SingleToMulti2_Processed_Stims_Stanton1_SmallGrade1]"
        group = [
            tracker.CargoMission(
                title="Rookie Small Haul", rank="Rookie", pickup="Everus Harbor",
                dropoff="Unknown drop-off", commodity="Stims", scu="", mission_id="m3",
                objective_id="dropoff_test_0", raw=raw,
            ),
            tracker.CargoMission(
                title="Rookie Small Haul", rank="Rookie", pickup="Everus Harbor",
                dropoff="Unknown drop-off", commodity="Stims", scu="", mission_id="m3",
                objective_id="dropoff_test_1", raw=raw,
            ),
        ]
        result = tracker.validate_ocr_contract_details({
            "objectives": [{"pickup": "Everus Harbor", "dropoff": "HDMS-Norgaard", "commodity": "Stims", "scu": "4"}]
        }, group)
        self.assertFalse(result["ok"])
        self.assertIn("1 of 2", result["reason"])

    def test_validation_rejects_prose_derived_ocr_routes_when_markers_are_known(self):
        raw = "contract [HaulCargo_SingleToMulti2_RefinedOre_Tungsten_Stanton1_ExtraSmallGrade]"
        group = [
            tracker.CargoMission(
                title="Rookie Extra Small Haul", rank="Rookie", pickup="Everus Harbor",
                dropoff="HDPC-Farnesway", commodity="Tungsten", scu="", mission_id="m5",
                objective_id="dropoff_tungsten_1", raw=raw, data_provenance="marker_resolved",
            ),
            tracker.CargoMission(
                title="Rookie Extra Small Haul", rank="Rookie", pickup="Everus Harbor",
                dropoff="HDPC-Cassillo", commodity="Tungsten", scu="", mission_id="m5",
                objective_id="dropoff_tungsten_0", raw=raw, data_provenance="marker_resolved",
            ),
        ]
        bad = tracker.validate_ocr_contract_details({
            "source": "ocr",
            "objectives": [
                {
                    "pickup": "above Hurston currently has some 1 needs to be separated and delivered",
                    "dropoff": "be separated and delivered to ORDER) Cassillo",
                    "commodity": "Tungst Hurston. o",
                    "scu": "5",
                },
                {
                    "pickup": "HDPC-Farnesway",
                    "dropoff": "HDPC-Cassillo",
                    "commodity": "Tungsten",
                    "scu": "1",
                },
            ],
        }, group)
        self.assertFalse(bad["ok"])
        self.assertIn("drop-off", bad["reason"])

        good = tracker.validate_ocr_contract_details({
            "source": "ocr",
            "objectives": [
                {"pickup": "Everus Harbor", "dropoff": "HDPC-Cassillo", "commodity": "Tungsten", "scu": "5"},
                {"pickup": "Everus Harbor", "dropoff": "HDPC-Farnesway", "commodity": "Tungsten", "scu": "5"},
            ],
        }, group)
        self.assertTrue(good["ok"], good.get("reason"))

    def test_validation_rejects_same_pickup_and_dropoff(self):
        group = [tracker.CargoMission(
            title="Rookie Small Haul", rank="Rookie", pickup="Everus Harbor",
            dropoff="Unknown drop-off", commodity="Stims", scu="", mission_id="m4"
        )]
        result = tracker.validate_ocr_contract_details({
            "objectives": [{"pickup": "Everus Harbor", "dropoff": "Everus Harbor", "commodity": "Stims", "scu": "4"}]
        }, group)
        self.assertFalse(result["ok"])
        self.assertIn("same pickup", result["reason"].lower())

    def test_validation_repairs_same_location_ocr_for_known_single_route(self):
        group = [tracker.CargoMission(
            title="Rookie Direct Extra Small Haul", rank="Rookie", pickup="Everus Harbor",
            dropoff="HDPC-Farnesway", commodity="Tungsten", scu="", mission_id="m6",
            raw="contract [HaulCargo_AToB_RefinedOre_Tungsten_Stanton1_SmallGrade]",
            data_provenance="marker_resolved",
        )]
        result = tracker.validate_ocr_contract_details({
            "objectives": [{
                "pickup": "Everus Harbor",
                "dropoff": "Everus Harbor",
                "commodity": "Tungsten",
                "scu": "10",
            }],
            "payout": 50250,
        }, group)
        self.assertTrue(result["ok"], result.get("reason"))
        self.assertEqual(result["objectives"][0]["pickup"], "Everus Harbor")
        self.assertEqual(result["objectives"][0]["dropoff"], "HDPC-Farnesway")
        self.assertEqual(result["objectives"][0]["scu"], "10")

    def test_validation_preserves_exact_log_authority(self):
        group = [tracker.CargoMission(
            title="Member Small Haul", rank="Member", pickup="Everus Harbor",
            dropoff="Teasa Spaceport", commodity="Quartz", scu="5", mission_id="m2",
            scu_provenance="exact_log", data_provenance="exact_log"
        )]
        bad = tracker.validate_ocr_contract_details({
            "objectives": [{"pickup": "Everus Harbor", "dropoff": "Teasa Spaceport", "commodity": "Quartz", "scu": "8"}]
        }, group)
        self.assertFalse(bad["ok"])
        self.assertIn("exact", bad["reason"].lower())

    def test_ocr_override_is_plannable_and_keeps_provenance(self):
        mission = tracker.CargoMission(
            title="Rookie Small Haul", rank="Rookie", pickup="Everus Harbor",
            dropoff="HDMS-Hahn", commodity="Stims", scu="", mission_id="m3"
        )
        updated = tracker.apply_contract_overrides([mission], {
            "m3": {
                "source": "ocr",
                "payout": 48500,
                "objectives": [{
                    "pickup": "Everus Harbor", "dropoff": "HDMS-Hahn",
                    "commodity": "Stims", "scu": "5", "provenance": "ocr"
                }],
            }
        })
        self.assertEqual(updated[0].scu_provenance, "ocr")
        self.assertEqual(updated[0].payout_provenance, "ocr")
        self.assertTrue(updated[0].is_load_plannable())

    def test_aggregate_ocr_rows_are_not_multiplied(self):
        base = [
            tracker.CargoMission(title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Hahn", dropoff="Everus Harbor", commodity="Iron (Ore)", scu="", mission_id="m4"),
            tracker.CargoMission(title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Perlman", dropoff="Everus Harbor", commodity="Iron (Ore)", scu="", mission_id="m4"),
        ]
        updated = tracker.apply_contract_overrides(base, {
            "m4": {
                "source": "ocr",
                "objectives": [
                    {"pickup": "HDMS-Hahn", "dropoff": "Everus Harbor", "commodity": "Iron (Ore)", "scu": "6", "provenance": "ocr", "quantity_scope": "aggregate"},
                    {"pickup": "HDMS-Perlman", "dropoff": "Everus Harbor", "commodity": "Iron (Ore)", "scu": "", "provenance": "marker_resolved", "quantity_scope": "aggregate"},
                ],
            }
        })
        self.assertEqual(sum(float(m.scu or 0) for m in updated), 6)
        self.assertTrue(all(m.quantity_scope == "aggregate" for m in updated))
        self.assertTrue(all(not m.is_load_plannable() for m in updated))
        self.assertEqual(sum(m.is_aggregate_load_plannable() for m in updated), 1)
        sections = tracker.logistics_sections(updated)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["mode"], "aggregate_pickups")
        self.assertEqual(sections[0]["pickup_options"], ["HDMS-Hahn", "HDMS-Perlman"])
        self.assertEqual([column["location"] for column in sections[0]["columns"]], ["HDMS-Hahn", "HDMS-Perlman"])
        self.assertEqual([column["items"][0]["scu"] for column in sections[0]["columns"]], ["", ""])
        self.assertEqual(sections[0]["shared_scu"], "6")

    def test_manual_editor_rows_infer_shared_quantity_scope(self):
        normalized = tracker.normalize_contract_overrides({
            "m-shared": {
                "source": "manual",
                "objectives": [
                    {"pickup": "HDMS-Hahn", "dropoff": "Everus Harbor", "commodity": "Iron (Ore)", "scu": "6"},
                    {"pickup": "HDMS-Perlman", "dropoff": "Everus Harbor", "commodity": "Iron (Ore)", "scu": ""},
                ],
            }
        })
        rows = normalized["m-shared"]["objectives"]
        self.assertEqual([row["quantity_scope"] for row in rows], ["aggregate", "aggregate"])

    def test_aggregate_contracts_with_same_dropoff_share_one_logistics_section(self):
        missions = [
            tracker.CargoMission(
                title="Experienced Cargo Haul", rank="Experienced", pickup="HDPC-Cassillo",
                dropoff="Everus Harbor", commodity="Waste", scu="14", mission_id="shared-a",
                objective_id="a-0", scu_provenance="ocr", quantity_scope="aggregate",
            ),
            tracker.CargoMission(
                title="Experienced Cargo Haul", rank="Experienced", pickup="HDPC-Farnesway",
                dropoff="Everus Harbor", commodity="Waste", scu="", mission_id="shared-a",
                objective_id="a-1", quantity_scope="aggregate",
            ),
            tracker.CargoMission(
                title="Experienced Cargo Haul", rank="Experienced", pickup="HDPC-Cassillo",
                dropoff="Everus Harbor", commodity="Waste", scu="20", mission_id="shared-b",
                objective_id="b-0", scu_provenance="ocr", quantity_scope="aggregate",
            ),
            tracker.CargoMission(
                title="Experienced Cargo Haul", rank="Experienced", pickup="Covalex Distribution Center S1DC06",
                dropoff="Everus Harbor", commodity="Waste", scu="", mission_id="shared-b",
                objective_id="b-1", quantity_scope="aggregate",
            ),
        ]

        sections = tracker.logistics_sections(missions)

        self.assertEqual(len(sections), 1)
        section = sections[0]
        self.assertEqual(section["mode"], "aggregate_pickups")
        self.assertEqual(section["fixed_location"], "Everus Harbor")
        self.assertEqual(section["total"], "34")
        self.assertEqual([load["scu_value"] for load in section["shared_loads"]], [14.0, 20.0])
        self.assertEqual(
            [column["location"] for column in section["columns"]],
            ["HDPC-Cassillo", "HDPC-Farnesway", "Covalex Distribution Center S1DC06"],
        )
        self.assertEqual(len(section["columns"][0]["items"]), 2)

    def test_aggregate_ocr_validation_accepts_an_additional_visible_pickup(self):
        group = [
            tracker.CargoMission(
                title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Hahn",
                dropoff="Everus Harbor", commodity="Iron (Ore)", scu="",
                mission_id="m-visible-pickup",
            )
        ]
        result = tracker.validate_ocr_contract_details({
            "objectives": [
                {"pickup": "HDMS-Hahn", "dropoff": "Everus Harbor", "commodity": "Iron (Ore)", "scu": "6", "quantity_scope": "aggregate"},
                {"pickup": "HDMS-Perlman", "dropoff": "Everus Harbor", "commodity": "Iron (Ore)", "scu": "", "quantity_scope": "aggregate"},
            ]
        }, group)
        self.assertTrue(result["ok"], result.get("reason"))
        self.assertEqual(result["found_objectives"], 1)
        self.assertEqual(result["route_row_count"], 2)

    def test_shared_quantity_summary_does_not_call_blank_pickup_rows_unknown(self):
        missions = [
            tracker.CargoMission(
                title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Hahn",
                dropoff="Everus Harbor", commodity="Iron (Ore)", scu="6",
                mission_id="m-summary", scu_provenance="ocr", quantity_scope="aggregate",
            ),
            tracker.CargoMission(
                title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Perlman",
                dropoff="Everus Harbor", commodity="Iron (Ore)", scu="",
                mission_id="m-summary", scu_provenance="unknown", quantity_scope="aggregate",
            ),
        ]
        summary = tracker.active_quantity_summary(missions)
        self.assertEqual(summary["known_scu"], 6)
        self.assertEqual(summary["unknown_objectives"], 0)
        self.assertEqual(summary["aggregate_rows"], 1)

    def test_explicit_multi_pickup_quantities_remain_per_route(self):
        missions = [
            tracker.CargoMission(
                title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Hahn",
                dropoff="Everus Harbor", commodity="Iron (Ore)", scu="4",
                mission_id="m5", objective_id="pickup_0", data_provenance="ocr",
                scu_provenance="ocr", quantity_scope="per_route",
            ),
            tracker.CargoMission(
                title="Junior Cargo Haul", rank="Junior", pickup="HDMS-Perlman",
                dropoff="Everus Harbor", commodity="Iron (Ore)", scu="2",
                mission_id="m5", objective_id="pickup_1", data_provenance="ocr",
                scu_provenance="ocr", quantity_scope="per_route",
            ),
        ]
        sections = tracker.logistics_sections(missions)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0]["mode"], "single_dropoff")
        self.assertEqual([column["location"] for column in sections[0]["columns"]], ["HDMS-Hahn", "HDMS-Perlman"])
        self.assertEqual([column["items"][0]["scu"] for column in sections[0]["columns"]], ["4", "2"])


class AutomaticOcrAcceptanceTriggerRegressionTest(unittest.TestCase):
    def test_extracts_only_real_added_hauling_acceptance_events(self):
        mission_id = "f8cf28ef-2e48-41bf-bdd3-acab67539a9c"
        text = "\n".join([
            f'<2026-07-11T19:52:07.733Z> [Notice] <SHUDEvent_OnNotification> Added notification "Contract Accepted:  Member | Small Haul | from Everus Harbor <EM4>[BP]*</EM4>: " [7] to queue. MissionId: [{mission_id}], ObjectiveId: []',
            f'   "Contract Accepted: Member | Small Haul | from Everus Harbor: " [7] MissionId: [{mission_id}]',
            f'<2026-07-11T19:52:23.850Z> [Notice] <UpdateNotificationItem> Notification "Contract Accepted: Member | Small Haul | from Everus Harbor: " [7], Action: Next MissionId: [{mission_id}]',
            '<2026-07-11T19:52:24.000Z> [Notice] <SHUDEvent_OnNotification> Added notification "Contract Accepted: Eliminate target: " to queue. MissionId: [aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee]',
        ])
        self.assertEqual(tracker.accepted_hauling_mission_ids(text), [mission_id])

    def test_acceptance_detection_survives_rolling_buffer_reparse(self):
        mission_id = "716e3719-73b2-42b4-bd18-4d02844ef18c"
        line = f'<SHUDEvent_OnNotification> Added notification "Contract Accepted: Rookie | Small Haul | from Everus Harbor: " to queue. MissionId: [{mission_id}], ObjectiveId: []'
        first = set(tracker.accepted_hauling_mission_ids(line))
        seen = set()
        new_first = first - seen
        seen.update(first)
        new_second = set(tracker.accepted_hauling_mission_ids(line)) - seen
        self.assertEqual(new_first, {mission_id})
        self.assertEqual(new_second, set())


class CommodityLabelNormalizationRegressionTest(unittest.TestCase):
    def test_incomplete_iron_ore_parenthesis_is_repaired_everywhere(self):
        self.assertEqual(tracker.normalize_commodity_name("Iron (Ore"), "Iron (Ore)")
        self.assertEqual(tracker.normalize_commodity_name("Iron Ore"), "Iron (Ore)")
        mission = tracker.CargoMission(
            title="Junior Rank - Small Cargo Haul", rank="Junior",
            pickup="HDMS-Hahn", dropoff="Everus Harbor", commodity="Iron (Ore", scu="6",
        )
        self.assertEqual(mission.commodity, "Iron (Ore)")

    def test_contract_ocr_returns_canonical_iron_ore_label(self):
        parsed = tracker.parse_contract_details_text(
            "PRIMARY OBJECTIVES\n"
            "Deliver 0/6 SCU of Iron (Ore to Everus Harbor.\n"
            "Collect Iron (Ore) from HDMS-Hahn.\n"
            "Collect Iron (Ore) from HDMS-Perlman.\n"
            "TRACK"
        )
        self.assertEqual(len(parsed["objectives"]), 2)
        self.assertTrue(all(row["commodity"] == "Iron (Ore)" for row in parsed["objectives"]))


if __name__ == "__main__":
    unittest.main()
