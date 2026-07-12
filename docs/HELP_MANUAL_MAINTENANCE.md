# SCHT in-app manual maintenance

The Help & User Guide is part of the product, not optional release documentation. Every user-facing feature, renamed control, changed workflow, or new error state must be reviewed against the in-app guide before a patch is considered complete.

## Required checklist for every user-facing change

1. **Update the guide copy** in `WEB_HTML` inside `sc_hauling_tracker.py`.
   - Installer, uninstall behavior, runtime requirements, and data-folder changes are user-facing features and must be documented.
   - Add a new section when the feature introduces a new workflow.
   - Update the existing section when labels, behavior, limitations, or safety implications change.
   - Keep instructions task-oriented and describe what the user sees in the current build.
2. **Update screenshots when the visible UI changes.**
   - Crops live in `assets/help/`.
   - Prefer replacing an existing file with the same name when it illustrates the same concept.
   - Add a new file only for a genuinely new workflow, then add it to `HELP_IMAGE_ASSETS`, `SCHT.spec`, the guide markup, and packaging tests.
   - Remove personal paths, private data, usernames, or unrelated desktop content from new crops.
3. **Keep the guide offline.**
   - Do not link required instructions to external websites.
   - Guide images must be bundled and served by the local SCHT server.
4. **Update regression coverage.**
   - Add or change assertions in `tests/test_ui_regression.py` for the new guide text/section.
   - Add packaging assertions when guide assets change.
5. **Update release metadata.**
   - Bump `APP_VERSION`, `version_info.txt`, README release notes, and the Help footer.
6. **Verify the packaged build.**
   - Run `run_tests.bat` or `python -m unittest discover -s tests -p "test_*.py"`.
   - Build with `build_exe.bat`.
   - For installer releases, also run `build_installer.bat`, test installation, launch, upgrade, and uninstall on a clean Windows user account, and verify both current and legacy SCHT AppData folders are removed.
   - Open Help in the packaged EXE with the network disconnected.
   - Check every image, anchor, scroll area, close action, and Escape behavior.

## Source reminder

The guide markup is preceded by this marker:

`MANUAL_MAINTENANCE_REQUIRED`

Do not remove it. The UI regression test checks for the marker and for the maintenance document so the requirement remains visible during future work.
