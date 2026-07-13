import tempfile
import unittest
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import sc_hauling_tracker as tracker  # noqa: E402


class PortableExePackagingRegressionTest(unittest.TestCase):
    def test_spec_builds_one_file_named_scht(self):
        spec = (ROOT / "SCHT.spec").read_text(encoding="utf-8")
        self.assertIn("name='SCHT'", spec)
        self.assertIn("a.binaries", spec)
        self.assertIn("a.datas", spec)
        self.assertNotIn("COLLECT(", spec)


    def test_help_manual_assets_are_bundled(self):
        spec = (ROOT / "SCHT.spec").read_text(encoding="utf-8")
        expected = {
            "toolbar.jpg",
            "dashboard.jpg",
            "logistics_board.jpg",
            "overlay.jpg",
            "settings_menu.jpg",
            "share_menu.jpg",
            "contract_editor.jpg",
        }
        self.assertEqual(expected, set(tracker.HELP_IMAGE_ASSETS))
        for name in expected:
            self.assertTrue((ROOT / "assets" / "help" / name).exists(), name)
            self.assertIn(rf"assets\\help\\{name}", spec)

    def test_default_builder_outputs_scht_exe(self):
        builder = (ROOT / "build_exe.bat").read_text(encoding="utf-8")
        self.assertIn("-m PyInstaller --noconfirm --clean SCHT.spec", builder)
        self.assertIn('dist\\SCHT.exe', builder)
        self.assertNotIn('SC Hauling Log Tracker.exe', builder)

    def test_windows_metadata_uses_scht_filename(self):
        metadata = (ROOT / "version_info.txt").read_text(encoding="utf-8")
        self.assertIn("StringStruct('InternalName', 'SCHT')", metadata)
        self.assertIn("StringStruct('OriginalFilename', 'SCHT.exe')", metadata)
        version_tuple = tuple(int(part) for part in tracker.APP_VERSION.split(".")) + (0,)
        self.assertIn(f"filevers={version_tuple}", metadata)
        self.assertIn(f"prodvers={version_tuple}", metadata)
        self.assertIn(f"StringStruct('FileVersion', '{tracker.APP_VERSION}')", metadata)
        self.assertIn(f"StringStruct('ProductVersion', '{tracker.APP_VERSION}')", metadata)


class FirstReleasePackagingRegressionTest(unittest.TestCase):
    def test_public_version_is_rebased_to_one(self):
        self.assertEqual("1.5.67", tracker.APP_VERSION)
        self.assertTrue(tracker.APP_VERSION.startswith("1."))

    def test_windows_appdata_uses_scht_and_migrates_legacy_folder(self):
        self.assertEqual("SCHT", tracker.APP_DATA_FOLDER)
        with tempfile.TemporaryDirectory() as temp_dir:
            local = Path(temp_dir)
            legacy = local / "SC Hauling Log Tracker"
            current = local / tracker.APP_DATA_FOLDER
            legacy.mkdir()
            (legacy / "app-settings.json").write_text('{"log_path":"Game.log"}', encoding="utf-8")
            tracker._migrate_legacy_app_data(local, current)
            self.assertTrue((current / "app-settings.json").exists())
            self.assertFalse(legacy.exists())

    def test_installer_is_per_user_and_removes_owned_data(self):
        installer = (ROOT / "installer" / "SCHT.iss").read_text(encoding="utf-8")
        self.assertIn("PrivilegesRequired=lowest", installer)
        self.assertIn(r"DefaultDirName={localappdata}\Programs\SCHT", installer)
        self.assertIn(r'Source: "..\dist\SCHT.exe"', installer)
        self.assertIn(r'Name: "{localappdata}\SCHT"', installer)
        self.assertIn(r'Name: "{localappdata}\SC Hauling Log Tracker"', installer)
        self.assertIn("AppMutex=Local\\SC_Hauling_Log_Tracker_Desktop", installer)

    def test_installer_builder_and_ci_publish_both_release_files(self):
        builder = (ROOT / "build_installer.bat").read_text(encoding="utf-8")
        workflow = (ROOT / ".github" / "workflows" / "build-scht-exe.yml").read_text(encoding="utf-8")
        self.assertIn("Inno Setup 6", builder)
        self.assertIn("SCHT-Setup-%SCHT_VERSION%.exe", builder)
        self.assertIn(r"%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe", builder)
        self.assertIn("--no-pause", (ROOT / "build_exe.bat").read_text(encoding="utf-8"))
        self.assertIn("choco install innosetup", workflow)
        self.assertIn("dist/SCHT.exe", workflow)
        self.assertIn("dist/SCHT-Setup-*.exe", workflow)
        self.assertIn("dist/SHA256SUMS.txt", workflow)
        self.assertIn("gh release create", workflow)
        self.assertIn("contents: write", workflow)

    def test_ci_test_cache_uses_the_repository_dependency_file(self):
        workflow = (ROOT / ".github" / "workflows" / "tests.yml").read_text(encoding="utf-8")
        self.assertIn("cache: pip", workflow)
        self.assertIn("cache-dependency-path: requirements-build.txt", workflow)
        self.assertIn("python -m pip install -r requirements-build.txt", workflow)

    def test_standalone_exe_bundles_python_for_players(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        spec = (ROOT / "SCHT.spec").read_text(encoding="utf-8")
        self.assertIn("Players do not need Python", readme)
        self.assertIn("a.binaries", spec)
        self.assertIn("a.datas", spec)
        self.assertNotIn("COLLECT(", spec)

    def test_main_window_reopens_wide_enough_for_primary_toolbar(self):
        controller = object.__new__(tracker.OverlayController)
        controller.main_settings = {"width": 1180, "height": 820, "layout_version": 2}
        controller._primary_work_area = lambda: (0, 0, 1920, 1040)
        geometry = tracker.OverlayController.main_window_geometry(controller)
        self.assertGreaterEqual(geometry["width"], tracker.MAIN_WINDOW_PREFERRED_MIN_WIDTH)
        self.assertLessEqual(geometry["width"], 1920)


if __name__ == "__main__":
    unittest.main()
