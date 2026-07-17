import ctypes
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sc_hauling_tracker as tracker  # noqa: E402


class OverlayUiRegressionTest(unittest.TestCase):
    def test_logistics_overlay_matches_route_overlay_chrome(self):
        html = tracker.OVERLAY_HTML
        self.assertIn("LOGISTICS BOARD", html)
        self.assertIn('class="loadout-mark"', html)
        self.assertIn('id="headerProgress"', html)
        self.assertIn('id="pinBtn"', html)
        self.assertIn("$('pinBtn').classList.toggle('active'", html)
        self.assertIn("linear-gradient(145deg,#171827,#0b0c14 72%)", html)
        self.assertIn("grid-template-rows:38px 46px minmax(0,1fr) 25px", html)
        self.assertIn('.window-actions{height:100%;display:flex;align-items:center;gap:2px;padding:0 4px;border:0}', html)
        self.assertIn('.icon-btn{width:28px;height:28px;padding:0;border:0;border-radius:7px;background:transparent;', html)
        self.assertIn('.icon-btn.danger:hover{color:#ff7181}', html)
        self.assertNotIn('border-left:1px solid rgba(255,255,255,.04)', html)
        route_html = tracker.ROUTE_OVERLAY_HTML
        self.assertIn('.actions{height:100%;display:flex;align-items:center;gap:2px;padding:0 4px;border:0}', route_html)
        self.assertIn('.action{width:28px;height:28px;padding:0;border:0;border-radius:7px;background:transparent;', route_html)
        self.assertIn('.action.danger:hover{color:#ff7181}', route_html)
        self.assertIn('.setting-copy strong{font-size:10px;font-weight:400}', html)
        self.assertNotIn('class="settings-head"', html)
        self.assertNotIn('id="opacityValue"', html)
        self.assertNotIn('id="positionLockSwitch"', html)
        self.assertIn('function sortSectionsByRoute(sections,route){if(!route?.valid||!(route.stops||[]).length)return sections;', html)
        self.assertNotIn('sortSectionsByRoute(sections,route){if(!route?.valid||route?.outdated', html)
        self.assertIn('sections=sortSectionsByRoute(sections,cache?.route);', html)
        self.assertIn('a.rank-b.rank||a.index-b.index', html)

    def test_overlay_is_permanently_compact(self):
        html = tracker.OVERLAY_HTML
        self.assertIn('<body class="size-unlocked compact">', html)
        self.assertNotIn('id="compactRowsBtn"', html)
        self.assertIn('id="overlayHideLoadedBtn"', html)
        self.assertIn('Hide loaded', html)
        self.assertIn('Show loaded', html)

    def test_overlay_labels_route_directions_and_reuses_contract_arrows(self):
        html = tracker.OVERLAY_HTML
        self.assertNotIn("let label='Direct route'", html)
        self.assertIn("fixedKind==='pickup'?'PICK UP':'DROP OFF'", html)
        self.assertIn("shared?' (SHARED)':''", html)
        self.assertIn("const columnKind=fixedKind==='pickup'?'dropoff':'pickup'", html)
        self.assertIn('const LOCATION_SVGS=Object.freeze({', html)
        self.assertIn('class="overlay-location ${fixedKind}-route"', html)
        self.assertIn('class="overlay-location ${columnKind}-route"', html)
        self.assertIn('.overlay-location.pickup-route .route-icon{color:#6f9bd1}', html)
        self.assertIn('.overlay-location.dropoff-route .route-icon{color:#8979d8}', html)
        self.assertIn('.overlay-location .location-text{display:block;min-width:0;margin-top:0!important;color:inherit!important;font:inherit!important;', html)
        self.assertNotIn('PICK UP LOCATION', html)
        self.assertNotIn('DROP OFF LOCATION', html)
        self.assertIn('class="group-action ${fixedKind}-action"', html)
        self.assertIn('class="group-total">${esc(totalLabel)}</span>', html)
        self.assertNotIn('class="group-total"><i', html)
        self.assertIn('.group-head .location-name{display:block;margin:0;color:#f1f3ff;font-size:15px;font-weight:900', html)
        self.assertIn('.group-head .group-location .location-subtitle{display:block;margin-top:3px;color:#777d97;font-size:8.5px;font-weight:650', html)
        self.assertIn('letter-spacing:normal;text-transform:none', html)
        self.assertIn('column-gap:12px}.compact .group-head{padding-left:16px}', html)
        self.assertIn("loadedSectionScu=mode==='aggregate_pickups'?sharedStats([section]).loaded:sectionProgress.loadedScu", html)
        self.assertIn('`${fmt(loadedSectionScu)} / ${fmt(Number(section.total||sectionProgress.totalScu))} SCU`', html)
        self.assertIn('.route-title .route-icon{width:11px;height:11px;flex:0 0 11px}', html)
        self.assertIn('.route-title .location-name{display:block;color:#f1f3ff;font-family:"Segoe UI Variable Text","Segoe UI",Arial,sans-serif;font-size:12px;font-weight:900', html)
        self.assertIn('.route-title .location-subtitle{display:block;margin-top:3px;color:#777d97;font-family:"Segoe UI Variable Text","Segoe UI",Arial,sans-serif;font-size:8.5px;font-weight:650', html)
        self.assertNotIn('<span>${esc(progress)}</span>', html)
        self.assertNotIn("const progress=mode==='aggregate_pickups'", html)
        self.assertNotIn('${LOCATION_SVGS[fixedKind]}<span class="location-text">', html)


class MainWindowMaximizeRegressionTest(unittest.TestCase):
    def test_maximize_uses_work_area_and_restores_previous_rect(self):
        class FakeUser32:
            def __init__(self):
                self.calls = []

            def IsZoomed(self, _hwnd):
                return 0

            def IsIconic(self, _hwnd):
                return 0

            def ShowWindow(self, *args):
                self.calls.append(("ShowWindow", args))
                return 1

            def SetWindowPos(self, *args):
                self.calls.append(("SetWindowPos", args))
                return 1

        fake = FakeUser32()
        old_name = tracker.os.name
        had_windll = hasattr(ctypes, "windll")
        old_windll = getattr(ctypes, "windll", None)
        try:
            tracker.os.name = "nt"
            ctypes.windll = SimpleNamespace(user32=fake)
            controller = object.__new__(tracker.OverlayController)
            controller.main_window = object()
            controller._main_workarea_maximized = False
            controller._main_restore_rect = None
            controller._window_hwnd = lambda _window: 77
            controller._main_window_rect = lambda: (120, 90, 1400, 820)
            controller._main_monitor_work_area = lambda _hwnd: (0, 0, 1920, 1040)
            controller._apply_main_chrome = lambda: None
            controller.main_window_geometry = lambda: {
                "x": 100,
                "y": 80,
                "width": 1400,
                "height": 820,
            }

            maximized = controller.toggle_main_maximize()
            self.assertTrue(maximized["command_ok"])
            self.assertTrue(maximized["maximized"])
            self.assertTrue(maximized["uses_work_area"])
            first = [call for name, call in fake.calls if name == "SetWindowPos"][-1]
            self.assertEqual(first[2:6], (0, 0, 1920, 1040))

            restored = controller.toggle_main_maximize()
            self.assertTrue(restored["command_ok"])
            self.assertFalse(restored["maximized"])
            self.assertFalse(restored["uses_work_area"])
            second = [call for name, call in fake.calls if name == "SetWindowPos"][-1]
            self.assertEqual(second[2:6], (120, 90, 1400, 820))
        finally:
            tracker.os.name = old_name
            if had_windll:
                ctypes.windll = old_windll
            else:
                delattr(ctypes, "windll")


class TypographyRegressionTest(unittest.TestCase):
    def test_dashboard_uses_shared_typography_and_new_branding(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn("--type-meta:9px;--type-ui:10px;--type-control:10.5px;--type-heading:12px", source)
        self.assertIn("--weight-body:700;--weight-control:700;--weight-strong:900", source)
        self.assertIn("<h1>SCHT</h1>", source)
        self.assertIn(f"SC Hauling Tracker</div><small id=\"version\">v{tracker.APP_VERSION}", source)
        self.assertIn(".btn,.suggestion-btn,.view-toggle,.filter-btn,.checklist-reset,.overlay-open{font-family", source)
        self.assertIn("--weight-control:700", source)
        self.assertIn("text-transform:none", source)

    def test_overlay_uses_shared_typography(self):
        html = tracker.OVERLAY_HTML
        self.assertIn("--type-meta:9px;--type-ui:10px;--type-control:9.5px;--type-heading:12px", html)
        self.assertIn("--weight-body:700;--weight-control:700;--weight-strong:900", html)
        self.assertIn(".small-btn{font-size:var(--type-control);font-weight:var(--weight-control)}", html)
        self.assertIn("text-transform:none", html)


class ContractTableScuColumnRegressionTest(unittest.TestCase):
    def test_scu_column_fits_four_digit_amounts(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.table{width:100%;min-width:0;', source)
        self.assertIn('.table-wrap{min-height:0;overflow-y:auto;overflow-x:hidden;', source)
        self.assertIn('.scu-stack{display:inline-flex;align-items:baseline;justify-content:center;gap:4px;min-width:40px;padding:4px 5px;white-space:nowrap;', source)
        self.assertIn('<col style="width:8%"><col style="width:10%">', source)

    def test_shared_scu_label_places_shared_on_its_own_line(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.shared-scu-stack{flex-direction:column;align-items:center;gap:2px;', source)
        self.assertIn("<small>shared</small>", source)
        self.assertNotIn("<small>SCU shared</small>", source)



class ContractStatusAndPayoutRegressionTest(unittest.TestCase):
    def test_status_icon_has_breathing_room_and_payout_uses_short_unit(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.table td.status-cell{position:relative;padding-left:14px;padding-right:8px;', source)
        self.assertIn('<span class="metric-unit">AUEC</span>', source)
        self.assertNotIn('<span class="metric-unit">aUEC payout</span>', source)


class ContractTableWidthRegressionTest(unittest.TestCase):
    def test_contract_table_fits_panel_without_horizontal_scroll(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.table-wrap{min-height:0;overflow-y:auto;overflow-x:hidden;', source)
        self.assertIn('.table{width:100%;min-width:0;', source)
        self.assertIn('<colgroup><col style="width:18%"><col style="width:15%"><col style="width:18%"><col style="width:13%"><col style="width:8%"><col style="width:10%"><col style="width:10%"><col style="width:8%"></colgroup>', source)
        self.assertIn('.table td{height:45px;padding:8px;', source)
        self.assertNotIn('min-width:1235px', source)



class ContractEditorRegressionTest(unittest.TestCase):
    def test_missing_contracts_can_be_corrected_per_mission_id(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="contractEditor"', source)
        self.assertIn('data-mission-id="${esc(g.mission_id)}"', source)
        self.assertIn("fetch('/api/contracts'", source)
        self.assertIn('state.save_contract_override', source)
        self.assertIn('state.clear_contract_override', source)
        self.assertIn('state.delete_contract', source)
        self.assertIn('contract-overrides.json', source)

    def test_contract_controls_are_inside_status_cell(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertNotIn('<th>Actions</th>', source)
        self.assertIn('<col style="width:18%"><col style="width:15%">', source)
        self.assertIn('<span class="status-wrap"><span class="status-pill">', source)
        self.assertIn('<span class="status-line"><strong>${esc(g.status)}</strong>${actions}</span>', source)
        self.assertNotIn('class="contract-cell actions-cell"', source)
        self.assertIn('EDIT_CONTRACT_SVG', source)
        self.assertIn('DELETE_CONTRACT_SVG', source)
        self.assertIn('data-contract-action="edit"', source)
        self.assertIn('data-contract-action="delete"', source)
        self.assertIn('.contract-action{width:16px;height:16px;padding:0;display:inline-grid;place-items:center;border:0;border-radius:0;background:transparent;', source)
        self.assertIn('.contract-action.edit:hover{background:transparent;color:var(--blue)}', source)
        self.assertIn('.contract-action.delete:hover{background:transparent;color:var(--red)}', source)
        self.assertIn('<span class="contract-actions">', source)
        self.assertNotIn('<div class="contract-actions">', source)
        self.assertIn("JSON.stringify({action:'delete',mission_id:missionId})", source)

    def test_delete_uses_styled_in_app_confirmation(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="contractDeleteConfirm"', source)
        self.assertIn('role="alertdialog"', source)
        self.assertIn('id="contractDeleteConfirmBtn"', source)
        self.assertIn('This removes the contract from the SCHT tracker view.', source)
        self.assertIn("openDeleteConfirm(button.dataset.missionId,group,button)", source)
        self.assertIn("$('contractDeleteCancel').focus()", source)
        self.assertIn("JSON.stringify({action:'delete',mission_id:missionId})", source)
        self.assertNotIn("window.confirm('Delete this contract from the tracker view?')", source)
        self.assertIn('.confirm-modal{width:min(430px,calc(100vw - 40px));', source)

    def test_contract_editor_has_ocr_assist_controls(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="contractOcrText"', source)
        self.assertIn('id="contractOcrRead"', source)
        self.assertIn('id="contractOcrParse"', source)
        self.assertIn("fetch('/api/ocr'", source)
        self.assertIn("windows_ocr_image", source)

    def test_contract_editor_preserves_hidden_shared_quantity_scope(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('data-quantity-scope="${scope}"', source)
        self.assertIn("quantity_scope:row.dataset.quantityScope==='aggregate'?'aggregate':'per_route'", source)
        self.assertIn("one shared quantity across ${aggregateRows.length} pickup locations", source)


class LogisticsBoardCardWidthRegressionTest(unittest.TestCase):
    def test_location_cards_keep_four_column_width_across_route_groups(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.destinations{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:9px;min-width:0}', source)
        self.assertNotIn('repeat(auto-fit,minmax(170px,1fr))', source)
        self.assertNotIn('.logistics-group.direct .destinations{grid-template-columns:minmax(220px,380px);justify-content:start}', source)
        self.assertIn('.destinations{grid-template-columns:repeat(2,minmax(0,1fr))}', source)


class SharedPickupLogisticsRegressionTest(unittest.TestCase):
    def test_shared_pickups_render_as_separate_cards_without_per_location_scu(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('"columns": columns_payload', source)
        self.assertIn('"scu": ""', source)
        self.assertIn("SCU not split", source)
        self.assertIn("collect ${esc(next.item.commodity)} at ${esc(columnName)}", source)
        self.assertIn("fixed_location_info", source)
        self.assertNotIn('"location": "Any listed pickup"', source)
        self.assertNotIn('Any pickup:', source)

    def test_shared_dropoff_labels_match_in_board_and_overlay(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn("title='Drop off location (shared)'", source)
        self.assertNotIn("Drop off location (shared total)", source)
        self.assertIn("mode==='single_dropoff'||mode==='aggregate_pickups'", source)
        self.assertNotIn("label='Shared quantity'", source)
        self.assertIn("section.shared_loads", source)

    def test_toast_stays_visible_above_contract_editor(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.modal-backdrop{position:fixed;inset:0;z-index:300;', source)
        self.assertIn('.toast{position:fixed;right:18px;bottom:18px;z-index:650;', source)
        self.assertIn('background:#101018', source)
        self.assertIn('id="toastClose"', source)
        self.assertIn("t.classList.remove('toast-success','toast-info','toast-error')", source)
        self.assertIn("setTimeout(hideToast,12000)", source)
        self.assertIn('Payout was not recognized; enter it manually if the field stays empty.', source)
        self.assertIn("showToast(actionName==='clear'?'Saved correction cleared':'Contract details saved','success')", source)
        self.assertIn("showToast(e.message||String(e),'error')", source)

    def test_toast_is_compact_and_uses_borderless_svg_close(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('grid-template-columns:minmax(0,1fr) 16px', source)
        self.assertIn('align-items:center', source)
        self.assertIn('min-height:34px;padding:8px 10px 8px 12px', source)
        self.assertIn('.toast-message{min-width:0;min-height:16px;display:flex;align-items:center;', source)
        self.assertIn('.toast-close{align-self:start;width:16px;height:16px;padding:0;border:0;background:transparent;', source)
        self.assertIn('.toast-close svg{display:block;width:10px;height:10px;stroke:currentColor;', source)
        self.assertIn('<svg viewBox="0 0 16 16" fill="none" aria-hidden="true" focusable="false"><path d="M3 3l10 10M13 3L3 13"/></svg>', source)
        self.assertNotIn('aria-label="Close message">×</button>', source)


    def test_contract_modals_use_svg_close_and_trash_row_delete(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.editor-close{width:24px;height:24px;padding:0;border:0;background:transparent;', source)
        self.assertIn('.editor-close svg{width:12px;height:12px;stroke:currentColor;', source)
        self.assertIn('.confirm-close{width:24px;height:24px;padding:0;border:0;background:transparent;', source)
        self.assertIn('.confirm-close svg{width:12px;height:12px;stroke:currentColor;', source)
        self.assertIn('.editor-close,.confirm-close{width:28px;height:28px;border-radius:7px;', source)
        self.assertIn('.editor-close:hover,.confirm-close:hover{background:rgba(90,167,255,.08);color:#ff7181;transform:none}', source)
        self.assertIn('.editor-head,.info-head,.confirm-head{position:relative}', source)
        self.assertIn('.editor-head>.editor-close,.info-head>.editor-close,.confirm-head>.confirm-close{position:absolute;right:4px;top:4px;transform:none}', source)
        self.assertIn('--radius:11px;', source)
        self.assertIn('.window-root,.editor-modal,.confirm-modal,.info-modal{border-radius:11px}', source)
        self.assertIn('.logistics-groups{align-content:start;gap:8px}.logistics-group+.logistics-group{padding-top:8px}', source)
        self.assertIn('@media(min-width:981px){.logistics-group .pickup-card,.logistics-group .destinations,.logistics-group .dest-card{height:168px;min-height:168px}', source)
        self.assertIn('.logistics-group.long-commodity-list .pickup-card,.logistics-group.long-commodity-list .destinations,.logistics-group.long-commodity-list .dest-card{height:auto}', source)
        self.assertIn('let hasLongCommodityList=false;', source)
        self.assertIn('if(cardItems.length>2)hasLongCommodityList=true;', source)
        self.assertIn("${hasLongCommodityList?' long-commodity-list':''}", source)
        self.assertIn('id="contractEditorClose" type="button" aria-label="Close editor"><svg viewBox="0 0 16 16"', source)
        self.assertIn('id="contractDeleteClose" type="button" aria-label="Close confirmation"><svg viewBox="0 0 16 16"', source)
        self.assertIn('class="editor-remove" type="button" title="Remove objective" aria-label="Remove objective">${DELETE_CONTRACT_SVG}</button>', source)
        self.assertIn('.editor-remove svg{width:13px;height:13px;fill:currentColor;', source)
        self.assertNotIn('id="contractEditorClose" type="button" aria-label="Close">×</button>', source)
        self.assertNotIn('title="Remove objective">×</button>', source)


class SessionTimerRegressionTest(unittest.TestCase):
    def test_start_from_now_keeps_current_tracker_state(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        web_state_source = source.split("    class WebState:", 1)[1]
        timer_block = web_state_source.split("        def start_timer_now(self):", 1)[1].split("        def toggle_timer(self):", 1)[0]
        self.assertIn('self.timer_elapsed_before = 0.0', timer_block)
        self.assertIn('self.timer_start_epoch = now', timer_block)
        self.assertIn('self.timer_state = "running"', timer_block)
        self.assertIn('Existing contracts were kept', timer_block)
        self.assertNotIn('self.missions = []', timer_block)
        self.assertNotIn('self.base_missions = []', timer_block)
        self.assertNotIn('self.events = []', timer_block)
        self.assertNotIn('self.checklist = {}', timer_block)
        self.assertNotIn('self.contract_overrides = {}', timer_block)
        self.assertNotIn('self.deleted_contract_ids = set()', timer_block)
        self.assertNotIn('self.watch_buffer = ""', timer_block)
        self.assertNotIn('self.watch_from_current = True', timer_block)
        self.assertNotIn('self.session_boundary_offset', timer_block)



class AutomaticOcrUiRegressionTest(unittest.TestCase):
    def test_dashboard_exposes_auto_ocr_toggle_and_status(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="autoOcrBtn"', source)
        self.assertIn('data-action="toggle_auto_ocr"', source)
        self.assertIn('id="autoOcrToggle"', source)
        self.assertIn('id="autoOcrHelp"', source)
        self.assertIn('id="ocrStatus"', source)
        self.assertIn("$('ocrStatus').textContent=data.ocr?.status", source)
        self.assertIn("autoButton.title='Auto OCR '+(auto?'on':'off')", source)
        self.assertIn('"ocr": {', source)
        self.assertIn('"auto_enabled": bool(self.auto_ocr_enabled)', source)

    def test_auto_ocr_uses_nonactivating_notification_and_temp_capture(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('class OcrNotificationWindow:', source)
        self.assertIn('SCHT CONTRACT HANDLING', source)
        self.assertIn('"progress": progress', source)
        self.assertIn('width, height = 500, 148', source)
        self.assertIn('"note": re.sub', source)
        self.assertIn('Keep this contract open in Star Citizen until import finishes.', source)
        self.assertIn('Import complete. You can continue in Star Citizen.', source)
        self.assertIn('Contract needs review', source)
        self.assertIn('2 fields need verification in SCHT.', source)
        self.assertIn('CreateRoundRectRgn', source)
        self.assertIn('fill_round_rect', source)
        self.assertIn('f"{progress}%"', source)
        self.assertIn('duration = 8.0', source)
        self.assertIn('WM_LBUTTONDOWN, WM_LBUTTONUP = 0x0201, 0x0202', source)
        self.assertIn('def close_hit(x: int, y: int) -> bool:', source)
        self.assertIn('WS_EX_NOACTIVATE = 0x08000000', source)
        self.assertIn('def _run_native_windows(self)', source)
        self.assertIn('CreateWindowExW', source)
        self.assertIn('def capture_star_citizen_window(self)', source)

    def test_ocr_notification_instruction_stays_inside_the_card(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('width=width - 42,', source)
        self.assertIn('font=("Segoe UI", 9, "bold")', source)
        self.assertIn('note_rect = RECT(20, 108, width - 20, 140)', source)
        self.assertIn('DT_LEFT | DT_WORDBREAK | DT_END_ELLIPSIS', source)
        self.assertIn('fonts["note"] = gdi32.CreateFontW(-12,', source)

    def test_ocr_notification_uses_compact_typography(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('font=("Segoe UI", 8, "bold")', source)
        self.assertIn('font=("Segoe UI", 13, "bold")', source)
        self.assertIn('font=("Segoe UI", 9)', source)
        self.assertIn('fonts["label"] = gdi32.CreateFontW(-11,', source)
        self.assertIn('fonts["title"] = gdi32.CreateFontW(-18,', source)
        self.assertIn('fonts["detail"] = gdi32.CreateFontW(-13,', source)
        self.assertIn('fonts["percent"] = gdi32.CreateFontW(-13,', source)
        self.assertIn('Star Citizen is not the foreground application', source)
        self.assertIn('SetProcessDpiAwarenessContext', source)
        self.assertIn('SetProcessDPIAware', source)
        self.assertIn('GetDpiForWindow', source)
        self.assertIn('$width + "|" + $height + "|" + $dpi', source)
        self.assertIn('debug_ocr_notification_sequence', source)
        self.assertIn('"ocr_debug": "Ctrl+Shift+D"', source)
        self.assertIn('(5, ord("D"))', source)
        self.assertIn('ocr-temp', source)
        self.assertIn('image_path.unlink()', source)


    def test_ocr_uses_targeted_crops_and_longer_terminal_notices(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn("def _create_contract_ocr_crops", source)
        self.assertIn("def read_contract_image_ocr", source)
        self.assertIn("0.61 0.07 0.38 0.24 3.0", source)
        self.assertIn("0.81 0.09 0.18 0.17 5.0", source)
        self.assertIn("0.62 0.25 0.37 0.57 2.4", source)
        self.assertIn('"success", 8', source)
        self.assertIn('"warning", 8', source)
        self.assertIn('"error", 8', source)
        self.assertIn('"pipeline_version": 2', source)
        self.assertIn("self.ocr_max_attempts = 4", source)
        self.assertIn("not (parsed.get(\"objectives\") or [])", source)
        self.assertIn("OCR read only", source)
        self.assertIn("no partial route data was saved", source)
        self.assertIn("ocr-last-failure.json", source)
        self.assertIn("full_text_excerpt", source)

    def test_live_watcher_queues_only_new_mission_ids(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('accepted_hauling_mission_ids(self.watch_buffer)', source)
        self.assertIn('self.ocr_seen_accept_ids.update(accepted_ids)', source)
        self.assertIn('self.ocr_seen_accept_ids = set(accepted_hauling_mission_ids(self.watch_buffer))', source)
        self.assertIn('self._queue_auto_ocr(mission_id)', source)
        self.assertIn('def _recent_auto_ocr_candidate_ids', source)
        self.assertIn('self._queue_recent_auto_ocr_candidates()', source)
        self.assertIn('Keep the newly accepted contract page open while SCHT reads it.', source)
        self.assertIn('Edit → Read screenshot', source)



class TopMenuRegressionTest(unittest.TestCase):
    def test_share_is_icon_only_and_exports_are_grouped(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('class="btn icon-btn menu-trigger" id="shareBtn"', source)
        self.assertIn('aria-label="Share and export"', source)
        self.assertIn('id="shareMenu" role="menu"', source)
        self.assertIn('data-export="csv"', source)
        self.assertIn('data-export="html"', source)
        self.assertIn('Export as CSV', source)
        self.assertIn('Export as HTML', source)
        self.assertNotIn('<span>Share</span>', source)
        self.assertNotIn('id="csvBtn"', source)
        self.assertNotIn('id="htmlBtn"', source)

    def test_export_uses_desktop_bridge_and_browser_download_fallback(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn("JSON.stringify({action:apiName})", source)
        self.assertIn('"export_csv_file": controller.export_csv_file', source)
        self.assertIn('"export_html_file": controller.export_html_file', source)
        self.assertIn("await browserExport(kind)", source)
        self.assertIn("URL.createObjectURL(blob)", source)
        self.assertIn("showToast('Preparing '+label+' export…','info')", source)
        self.assertIn("document.querySelectorAll('#shareMenu [data-export]')", source)
        self.assertIn("nativeExport(button.dataset.export,button)", source)

    def test_settings_menu_contains_auto_ocr_and_explained_reset(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="settingsBtn"', source)
        self.assertIn('id="settingsMenu" role="menu"', source)
        self.assertIn('id="autoOcrBtn"', source)
        self.assertIn('id="autoOcrToggle"', source)
        self.assertIn('Automatic OCR', source)
        self.assertIn('id="resetBtn"', source)
        self.assertIn('Clears contracts, checklist, timer, and saved corrections for this session. Game.log is not changed.', source)
        self.assertIn('id="sessionResetConfirm"', source)
        self.assertIn('id="sessionResetConfirmBtn"', source)
        self.assertIn("function openSessionResetConfirm()", source)
        self.assertIn("$('sessionResetCancel').focus()", source)
        self.assertNotIn("window.confirm('Reset this SCHT session?", source)
        self.assertNotIn('id="resetBtn" data-action="reset"', source)

    def test_watch_and_stop_are_one_stateful_control(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="watchBtn" data-action="watch"', source)
        self.assertIn("watch.dataset.action=watching?'stop_watch':'watch'", source)
        self.assertIn("watch.textContent=watching?'Stop Watch':'Start Watch'", source)
        self.assertIn("watch.classList.toggle('red',watching)", source)
        self.assertNotIn('id="stopBtn"', source)

    def test_primary_labels_are_clear_and_task_oriented(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('>Choose Log</button>', source)
        self.assertIn('>Scan Log</button>', source)
        self.assertIn('>Start Watch</button>', source)

    def test_help_button_opens_illustrated_user_guide(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('id="infoBtn"', source)
        self.assertIn('id="infoModal"', source)
        self.assertIn('SCHT Help & User Guide', source)
        self.assertIn('id="guideQuickStart"', source)
        self.assertIn('id="guideDashboard"', source)
        self.assertIn('id="guideLogistics"', source)
        self.assertIn('id="guideRoutePlanner"', source)
        self.assertIn('id="guideCorrections"', source)
        self.assertIn('id="guideMenus"', source)
        self.assertIn('id="guideTroubleshooting"', source)
        self.assertIn('Choose the log once → Start Watch', source)
        self.assertIn('shared-total multi-pickup contract', source)
        self.assertIn('The calculated route is the source order for both compact overlays.', source)
        self.assertIn('An <strong>outdated</strong> label means cargo or contract inputs changed after calculation.', source)
        self.assertIn('Use the titlebar pin to lock movement.', source)
        for image_name in tracker.HELP_IMAGE_ASSETS:
            self.assertIn(f'/assets/help/{image_name}', source)
        self.assertIn('Reset session is destructive inside SCHT.', source)
        self.assertIn('class="guide-image-button"', source)
        self.assertIn('id="guideLightbox"', source)
        self.assertIn("$('infoBtn').addEventListener('click',openInfoWindow)", source)
        self.assertIn("$('infoDone').addEventListener('click',closeInfoWindow)", source)
        self.assertIn("openGuideImage(button)", source)
        self.assertNotIn('Instructions are coming next', source)

    def test_help_navigation_rail_fills_the_guide_height(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.guide-shell{position:relative;display:grid;grid-template-columns:188px minmax(0,1fr);min-height:100%}', source)
        self.assertIn('.guide-shell:before{content:"";position:absolute;inset:0 auto 0 0;width:188px', source)
        self.assertIn('.guide-shell:before{display:none}', source)
        self.assertIn('background:linear-gradient(180deg,rgba(13,13,21,.98),rgba(13,13,21,.92))', source)

    def test_manual_maintenance_contract_is_present(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        maintenance = Path(tracker.__file__).resolve().parent / 'docs' / 'HELP_MANUAL_MAINTENANCE.md'
        self.assertIn('MANUAL_MAINTENANCE_REQUIRED', source)
        self.assertTrue(maintenance.exists())
        text = maintenance.read_text(encoding='utf-8')
        self.assertIn('Every user-facing feature', text)
        self.assertIn('Update screenshots when the visible UI changes', text)
        self.assertIn('Keep the guide offline', text)

    def test_desktop_brand_version_has_no_redundant_desktop_app_suffix(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn(f'<small id="version">v{tracker.APP_VERSION}</small>', source)
        self.assertNotIn(f'<small id="version">v{tracker.APP_VERSION} · desktop app</small>', source)
        self.assertIn("desktopBridgeReady?'':' · diagnostic browser'", source)


class ExportDialogRegressionTest(unittest.TestCase):
    def test_export_dialog_writes_payload_and_adds_missing_extension(self):
        class FakeDialog:
            def __init__(self, path):
                self.path = path
                self.calls = []

            def create_file_dialog(self, *args, **kwargs):
                self.calls.append((args, kwargs))
                return [str(self.path)]

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b"status,pickup\naccepted,Everus Harbor\n"

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "manifest"
            controller = object.__new__(tracker.OverlayController)
            controller.main_window = FakeDialog(target)
            controller.webview = SimpleNamespace(SAVE_DIALOG=7)
            controller.base_url = "http://127.0.0.1:9999"
            with patch("urllib.request.urlopen", return_value=FakeResponse()) as urlopen:
                result = controller._export_via_dialog(
                    "/export.csv",
                    "sc_hauling_manifest.csv",
                    ("CSV files (*.csv)", "All files (*.*)"),
                )
            self.assertTrue(result["ok"])
            saved = Path(result["path"])
            self.assertEqual(saved.suffix, ".csv")
            self.assertTrue(saved.exists())
            self.assertIn("Everus Harbor", saved.read_text(encoding="utf-8"))
            urlopen.assert_called_once_with("http://127.0.0.1:9999/export.csv", timeout=15)


class VerifiedBuildRegressionTest(unittest.TestCase):
    def test_builder_reads_current_version_without_fragile_metadata_gate(self):
        root = Path(tracker.__file__).resolve().parent
        builder = (root / "build_exe.bat").read_text(encoding="utf-8")
        self.assertIn("APP_VERSION", builder)
        self.assertIn("findstr", builder)
        self.assertIn("VENV_PYTHON", builder)
        self.assertIn("-m PyInstaller --noconfirm --clean SCHT.spec", builder)
        self.assertNotIn("re.search", builder)
        self.assertNotIn("does not match source version", builder)
        self.assertNotIn("SCHT v3.5.36", builder)


class FirstReleaseDesktopLayoutRegressionTest(unittest.TestCase):
    def test_primary_toolbar_stays_on_game_log_row_at_normal_width(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('.topbar{display:grid;grid-template-columns:200px minmax(190px,1fr) auto;gap:10px;', source)
        self.assertIn('@media(max-width:1120px){.topbar{grid-template-columns:200px minmax(190px,1fr)}', source)
        self.assertNotIn('@media(max-width:1290px){.topbar', source)

    def test_dashboard_starts_at_resize_minimum_without_stretched_top_gap(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertEqual(tracker.MAIN_WINDOW_PREFERRED_MIN_WIDTH, tracker.MAIN_WINDOW_HARD_MIN_WIDTH)
        self.assertIn("min_size=min_window_size", source)
        self.assertIn("grid-template-rows:auto auto minmax(28px,1fr)", source)
        self.assertIn("align-content:start", source)
        self.assertIn(".footer{height:28px;align-self:end", source)
        self.assertNotIn('<section class="workspace-tools">', source)

    def test_first_run_notification_is_not_rendered(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertNotIn('id="onboarding"', source)
        self.assertNotIn("function updateOnboarding", source)
        self.assertNotIn("updateOnboarding(data)", source)

    def test_help_explains_installer_and_no_python_requirement(self):
        source = Path(tracker.__file__).read_text(encoding="utf-8")
        self.assertIn('use <strong>SCHT-Setup</strong>', source)
        self.assertIn('players do not install Python separately', source)


if __name__ == "__main__":
    unittest.main()
