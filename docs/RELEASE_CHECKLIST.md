# SCHT release checklist

Use this checklist on the `dev` branch before promoting a tested version to `main`.

## Automated validation

- [ ] Confirm the **Tests** workflow passes on `dev`.
- [ ] Run the **Build SCHT Windows release** workflow manually from `dev`.
- [ ] Download the `SCHT-windows-release` artifact.
- [ ] Confirm it contains `SCHT.exe` and `SCHT-Setup-1.6.0.exe`.
- [ ] Confirm both files show product version 1.6.0 in Windows file properties.

## Portable application test

- [ ] Start `SCHT.exe` on a Windows account without Python on `PATH`.
- [ ] Confirm the header shows version 1.6.0.
- [ ] Select a sanitized test `Game.log`, scan it, and start/stop live watching.
- [ ] Exercise the Contract Log, Logistics Board, overlay, checklist, filters, timer, and contract editor.
- [ ] Test CSV and HTML exports.
- [ ] Test manual screenshot OCR and, where practical, automatic OCR with Star Citizen running.
- [ ] Close and reopen SCHT; confirm intended settings and session state persist.

## Installer test

- [ ] Install `SCHT-Setup-1.6.0.exe` as a standard user.
- [ ] Confirm Start Menu and optional desktop shortcuts launch the installed copy.
- [ ] Upgrade over an earlier SCHT installation and confirm legacy AppData migration preserves existing settings.
- [ ] Confirm only one desktop instance can run at a time.
- [ ] Uninstall SCHT and confirm program files, shortcuts, `%LOCALAPPDATA%\SCHT`, and the legacy `%LOCALAPPDATA%\SC Hauling Log Tracker` folder are removed.
- [ ] Confirm shared Microsoft Edge WebView2 remains installed.

## Privacy and publication

- [ ] Review the complete `dev` to `main` diff.
- [ ] Confirm no real logs, OCR captures/reports, AppData, local paths, usernames, credentials, build caches, or signing files are tracked.
- [ ] Confirm generated executables and installers are release artifacts, not source commits.
- [ ] Merge `dev` into `main` without rewriting history or force-pushing.
- [ ] Tag the tested commit only after the final merge; the tag triggers a fresh release build.
- [ ] Publish the release notes and tested installer/executable from that tagged build.
