# SC Hauling Log Tracker v1.5.66

A local, offline-first Windows desktop application for Star Citizen Covalex cargo hauling. It reads `Game.log`, detects accepted/completed/abandoned contracts, tracks profit and duration, provides a loading checklist, and opens a compact Logistics Overlay.

> **Public test software:** version 1.5.66 may contain defects. Keep normal backups of data you care about and review exported manifests before sharing them.

## Highlights

- Runs locally on Windows; SCHT does not require a cloud account or modify Star Citizen files.
- Watches `Game.log` for hauling contract events and keeps a session dashboard with payout, duration, and status.
- Provides a loading checklist, compact overlay, CSV/HTML exports, and OCR-assisted recovery for details omitted from the log.
- Ships as a standalone `SCHT.exe` and as a per-user Windows installer; players do not need Python.

## Quick start

1. Download the latest Windows installer from the repository's Releases page, when published.
2. Install and launch SCHT.
3. Choose your Star Citizen `Game.log`, for example `C:\Program Files\Roberts Space Industries\StarCitizen\LIVE\Game.log`.
4. Select **Scan Log**, then **Start Watch** before accepting new hauling contracts.

For source development, packaging, data locations, troubleshooting, and command-line use, see the sections below. Contributors should also read [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

## v1.5.66 First public test-release packaging

- Rebases the public version line from the internal 3.x development series to 1.5.66.
- Opens the desktop dashboard wider and keeps the primary toolbar beside the Game.log field at normal desktop sizes.
- Stores app-owned data under `%LOCALAPPDATA%\SCHT\` and migrates the former folder automatically.
- Adds a per-user Windows installer and uninstaller that remove SCHT program files, shortcuts, current AppData, and the legacy AppData folder.
- Keeps `SCHT.exe` fully standalone: end users do not need Python.

## v3.5.66 Full-height Help navigation rail

- Extends the darker User Guide navigation background through the full scrollable manual height instead of ending below the section links.
- Keeps the section links sticky at the top while the guide content scrolls.
- Preserves the compact horizontal navigation layout on narrow windows.

## v3.5.65 Illustrated in-app user guide

- Replaces the placeholder Help window with a complete, scrollable quick-start manual.
- Covers log selection, scanning, live Watch, Automatic OCR, the session timer, Contract Log, Logistics Board, overlay, contract corrections, exports, Reset session, and troubleshooting.
- Uses seven focused screenshot crops supplied from the current interface; each image can be enlarged without leaving the app.
- Bundles every guide image into the portable one-file build and serves it only from the local SCHT server.
- Adds `docs/HELP_MANUAL_MAINTENANCE.md`, a source marker, and regression coverage so future user-facing features include a matching manual update.

## v3.5.64 Simplified toolbar and reliable exports

- Replaces separate Watch and Stop Watch controls with one state-aware **Start Watch / Stop Watch** button.
- Keeps only the everyday workflow actions in the primary toolbar: **Choose Log**, **Scan Log**, and **Start Watch**.
- Makes Share an icon-only control while preserving the CSV and HTML export choices in its drop-down.
- Routes desktop exports through the local desktop bridge, provides visible progress/success/error feedback, and keeps a browser-download fallback for diagnostic mode.
- Adds an icon-only Settings menu containing the persistent **Automatic OCR** toggle and a clearly explained, confirmed **Reset session** action.
- Keeps Automatic OCR enabled by default for new installations while retaining a troubleshooting/manual-workflow toggle.

## v3.5.63 Share menu, help window, and commodity labels

- Repairs OCR/manual values such as `Iron (Ore` or `Iron Ore` to the canonical `Iron (Ore)` label throughout the Contract Log, Logistics Board, overlay, and exports.
- Replaces the separate CSV and HTML buttons with one **Share** button and a clear export drop-down.
- Adds a **Help & Information** button and an in-app instruction window ready for the final guide content.
- Removes the redundant `desktop app` suffix from the version label in the desktop build.
- Keeps the Auto OCR control unchanged in this patch while the broader menu workflow is reviewed.

## v3.5.62 Consistent Logistics Board card widths

- Keeps the right-side pickup/drop-off area on a four-column grid.
- Route groups with one, two, or three locations retain the same card width as a four-location group instead of stretching across the unused space.
- Direct-route cards use the same grid sizing as all other location cards.
- Falls back to two columns only at phone-sized window widths.

## v3.5.61 Shared pickup route fixes

- Displays aggregate contract quantities as `14 SCU` with `shared` on a second line in the Contract Log.
- Gives every possible pickup location its own Logistics Board and overlay card while leaving per-location SCU blank.
- Reads every visible `Collect` pickup attached to one shared `Deliver` objective, including manual screenshot imports.
- Preserves aggregate quantity scope through contract editing without inventing a per-location split.
- Keeps contracts with explicit quantities at each pickup in the normal per-route workflow.

## v3.5.60 Shared multi-pickup quantities

- Uses the same borderless SVG close-button style on the contract editor and delete confirmation windows.
- Replaces the objective-row text delete button with the existing trash SVG.

## v3.5.58 OCR notification guidance

- Renames the review state to `Contract needs review`.
- Clarifies that field verification happens in SCHT.
- Adds a visible instruction line that tells the user to keep the contract open while OCR is running and confirms when they can continue.

## v3.5.57 OCR notification progress card

- Replaces the staged Auto OCR notification with a compact percentage progress bar.
- Removes the loading dot spinner and uses the same borderless vector close icon language as the app.
- Uses blue while OCR is in progress, green when imported, yellow when review is needed, and red when failed.
- Auto-dismisses final OCR notifications after 8 seconds.

## v3.5.56 OCR notification polish

- Gives the staged Auto OCR notification more vertical room so stage labels render cleanly.
- Fixes the notification close button in the packaged native Windows notification path.
- Keeps the compact SCHT-styled `Detect`, `Capture`, `Recognition`, and `Import` flow.

## v3.5.55 OCR notification UI

- Replaces debug-looking OCR alerts with a compact SCHT-styled staged card.
- Shows the contract handling stages as `Detect`, `Capture`, `Recognition`, and `Import`.
- Adds `Ctrl+Shift+D` to run a local OCR notification debug sequence with success and review outcomes.

## v3.5.54 DPI-aware live capture

- Makes the Auto OCR Star Citizen capture helper DPI-aware before it reads window bounds.
- Prevents scaled displays from returning logical dimensions that crop the right side of the live capture.
- Adds capture DPI to OCR diagnostics so `ocr-last-failure.json` can confirm the real captured size.

## v3.5.53 Auto OCR live-capture diagnostics

- Keeps the last failed live Auto OCR capture path in `ocr-last-failure.json` so the exact PNG can be inspected.
- Tightens the objectives crop around the Primary Objectives panel instead of mixing it with DETAILS/reward text.
- Recovers clipped live OCR when all Deliver quantities are visible and Game.log already has marker-resolved route order.

## v3.5.52 Auto OCR screenshot fallback

- Auto OCR still captures a fresh Star Citizen window image on every retry.
- If live capture OCR is clipped or incomplete, SCHT can validate a very recent Star Citizen screenshot from the `LIVE/screenshots` folder before failing.
- Fresh screenshot fallback is validated against the pending MissionId and is not deleted unless a future opt-in flow creates it itself.

## v3.5.51 OCR screenshot corpus tuning

- Parses the supplied 34 contract screenshot corpus with no suspicious same-location/prose-leak rows.
- Recovers wrapped partial facility names such as `Sakura Sun Magnolia` when OCR drops the trailing `Workcenter`.
- Prefers strong leading partial location matches over later incidental prose locations like pickup names in the contract details paragraph.

## v3.5.50 OCR route repair diagnostics

- Repairs single direct-route OCR when Windows OCR reads the quantity/commodity but turns pickup and drop-off into the same location; the known marker-resolved Game.log route is used for pickup/drop-off.
- Keeps multi-route contracts conservative: they still fail instead of guessing when route locations are unknown.
- Writes the last failed OCR parse to `ocr-last-failure.json` in SCHT AppData with parsed rows and OCR text excerpts for faster follow-up debugging.

## v3.5.49 packaged OCR notifications

- Restores Auto OCR popup notifications in packaged builds even when Python's tkinter runtime is unavailable.
- Uses a small Windows-native non-activating topmost notification fallback for OCR detected, reading, imported, partial, and failed states.
- Keeps the OCR attempt notice visible before Star Citizen capture starts, so slow capture no longer leaves a silent gap.

## v3.5.48 Auto OCR trigger recovery

- Queues Auto OCR for recent active contracts that still need cargo quantities or payout, even if their accept event was already in the watch buffer.
- Shows the current Auto OCR status directly in the Live feed panel instead of hiding it behind the toggle tooltip.
- Improves diagnostics for cases where Auto OCR is disabled, waiting for parser details, unavailable, queued, imported, or failed.

## v3.5.47 OCR stale-route cleanup

- Rejects OCR cargo rows whose pickups or drop-offs do not match marker-resolved Game.log routes.
- Automatically discards stale invalid OCR overrides on refresh while preserving manual corrections.
- Fixes bad persisted rows created from contract prose such as `1 SCU or smaller cargo` when the visible objective list was not parsed cleanly.

## v3.5.46 OCR route-completeness safety

- Automatic OCR will not replace a multi-route contract unless every expected Deliver objective is captured.
- Handles common Windows OCR errors such as `O/5`, `0/S`, and moon suffixes after facility names.
- Adds a dedicated far-right reward-value crop and more tolerant payout normalization.
- Manual OCR reports `found X of Y expected objectives` before the user saves.
- Rejects impossible same-location pickup/drop-off results instead of presenting them as valid.

## v3.5.45 OCR reliability and notification timing

- Automatic and manual screenshot OCR use targeted, upscaled reward and Primary Objectives crops when the full-screen pass is incomplete.
- Parsed cargo objectives can confirm page readiness even when Windows OCR misses the PRIMARY OBJECTIVES heading.
- Existing v3.5.44 OCR settings migrate to a 2.8-second initial wait, four attempts, and 1.4-second retries.
- Final success, partial, and error notices stay visible longer; a newer notice still replaces the previous one immediately.
- Automatic OCR failures show the last concrete capture, OCR, or validation reason.

## v3.5.44 automatic OCR trigger diagnostics

- Drives OCR from the actual live `Contract Accepted` log event rather than relying only on a newly merged table group.
- Keeps split/partial log writes safe by scanning the rolling live buffer and deduplicating MissionIds.
- Shows whether OCR was queued, disabled, waiting for parser data, or unavailable in desktop mode.
- The builder now prints and verifies the source and executable version, preventing an older `dist\SCHT.exe` from being mistaken for the new build.

## v3.5.43 automatic contract OCR

- Detects each newly accepted hauling contract from the live `Game.log` stream and queues OCR against that exact `MissionId`.
- Waits for the accepted-contract page to open, captures only the foreground Star Citizen client area, retries up to three times, and deletes every temporary capture after OCR.
- Shows non-activating, always-on-top notifications for detection, reading, success, partial import, mismatch, and failure without stealing focus from the game.
- Validates OCR commodity, locations, objective structure, and any exact `Game.log` objectives before applying results, preventing one contract from leaking into another.
- Keeps exact log data authoritative, marks OCR data with its own provenance, never overwrites manual corrections, and preserves aggregate multi-pickup quantities without multiplying them.
- Adds an **Auto OCR on/off** dashboard control. When automatic capture fails, the existing **Edit → Read screenshot** workflow remains available before manual entry is required.
- Downscales captures larger than 2400 px for Windows OCR compatibility while retaining the original aspect ratio.

## v3.5.42 timer-only Start from now

- Fixes **Start from now** clearing the current contract table and Logistics board.
- The button now restarts only the session timer from zero.
- Existing contracts, completion events, checklist selections, manual corrections, deleted-contract filters, live-watch buffers, and Game.log session boundaries remain unchanged.
- Session clearing remains exclusive to the main **Reset** control.

## v3.5.41 status spacing and payout label

- Adds a little more left padding before the contract status icon so it no longer sits against the panel edge.
- Shortens the payout card unit label from `AUEC PAYOUT` to `AUEC`.
- Preserves the compact no-horizontal-scroll table layout.

## v3.5.40 responsive contract table

- Removed the fixed 1235 px table minimum width that forced horizontal scrolling.
- Rebalanced all eight columns as percentages of the available contract panel.
- Reduced excess cell, icon, route, commodity, metric, and rank padding while preserving ellipsis and tooltips.
- Kept the SCU column wide enough for four-digit values such as `9999 SCU`.

## v3.5.39 in-app delete confirmation

- Replaces the browser-native `127.0.0.1 says` confirmation with a compact SCHT-styled modal.
- Clearly explains that deleting only removes the item from the tracker view and does not alter the in-game contract.
- Adds safe Cancel-first focus, Escape/backdrop dismissal, and focus restoration to the delete icon.

## v3.5.38 inline borderless contract controls

- Places the edit and delete SVG icons on the same baseline as the ACCEPTED, COMPLETED, or ABANDONED label.
- Removes the button backgrounds, borders, and rounded boxes while retaining hover colors, keyboard focus visibility, tooltips, and existing actions.
- Keeps the status subline underneath without changing grouped contract-row behavior.

## v3.5.37 status-adjacent contract controls

- Moved the per-contract edit and delete controls into the Status cell, directly beside ACCEPTED, COMPLETED, or ABANDONED.
- Removed the separate Actions column while preserving the overall table width and grouped-row layout.

## v3.5.36 compact notification refinement

- Reduces notification padding and minimum width so short messages no longer look oversized.
- Vertically centers single-line notification text.
- Replaces the boxed close button with a small borderless SVG icon.
- Keeps the close icon aligned with the first line when a notification wraps onto multiple lines.
- Preserves the MissionId-first parser, OCR-assisted contract corrections, and one-file `SCHT.exe` packaging.

## v3.5.35 procedural-contract parsing fix

- Removes unsafe contract-definition-wide SCU templates. In Star Citizen 4.8, two missions using the same generated contract definition can have different destinations and quantities.
- Uses each unique `MissionId` as the contract identity.
- Infers commodity and known drop-off locations from the current mission's marker data when objective notifications are missing.
- Leaves unknown SCU and payout blank instead of inventing values.
- Adds an **Edit contract details** control so missing SCU, payout, commodity, pickup, or drop-off data can be corrected and stored locally for that exact `MissionId`.
- Includes regression coverage for the supplied seven-contract sequential test: 7 contracts, 22 cargo rows, 101 SCU.

## v3.5.34 stacked-contract parser fix

- Fixes the parser selecting a previous mission's `MissionId` when several contracts are accepted within the same short log window.
- Scopes objective notifications and contract-definition markers to the current `MissionId`, preventing Quartz objectives from leaking into later contracts.
- Adds verified 4.8 templates for Quartz, Stims, Silicon, Carbon, and Aluminum contracts from Everus Harbor.
- Adds a regression fixture for five stacked contracts: 5 contracts, 15 objectives, and 73 SCU total.
- Keeps the single-file Windows output name as `SCHT.exe`.

## v3.5.33 button typography refinement

- Changes ordinary button labels from heavy all-caps to clearer sentence case.
- Uses a semibold control weight instead of the previous extra-bold treatment.
- Removes excessive letter spacing and adds slightly more horizontal breathing room.
- Uses Segoe UI Variable Text first on supported Windows versions, with Segoe UI fallback.
- Keeps status badges, table headings, and technical metadata uppercase where that hierarchy is useful.
- Applies the same lighter label treatment to overlay controls.

## v3.5.32 typography cleanup and SCHT branding

- Standardizes dashboard and overlay text around three shared UI sizes: metadata, controls/body, and headings.
- Standardizes normal and strong text to two font weights.
- Makes all dashboard action, filter, checklist, and overlay buttons use matching label size and weight.
- Changes the visible title block to `SCHT`, with `SC Hauling Tracker` shown underneath in smaller text.
- Keeps large timers, profit values, and location highlights intentionally larger for hierarchy.

## v3.5.31 compact overlay and taskbar-safe maximize

- Keeps the overlay cargo rows permanently in the compact density.
- Removes the overlay Compact toggle.
- Renames the loaded-item filter to Hide loaded / Show loaded.
- Changes the custom main-window maximize button to fill the monitor work area instead of covering the Windows taskbar.
- Preserves the transparent, tightly cropped Windows application icon introduced in v3.5.30.

## v3.5.30 UI and application icon cleanup

- Removes the dashboard Layout preset toolbar (Compact, Balanced, Log focus, Logistics, and Reset).
- Keeps the manual Contract log and Logistics board splitters for direct height adjustment.
- Rebuilds the Windows EXE icon from the transparent cargo mark with a much tighter crop and larger visual scale.
- Uses a fully transparent icon background at all embedded Windows icon sizes.

## v3.5.29 Workflow polish

- Adds Contract log status filters for all, active, completed, and closed contracts.
- Adds layout presets for compact, balanced, Contract log focus, and Logistics focus.
- Adds first-run log suggestions when the dashboard has no useful log data yet.
- Adds a next-action strip and Hide loaded view to the Logistics board.
- Adds Hide loaded and Compact row controls to the overlay.
- Adds a parser regression test for the synthetic debug log.

## v3.5.28 Splitter polish

- Squares the Contract log table header corners.
- Makes the bottom drag strip solid so it does not overlay table rows.
- Adds the same draggable saved-height control to the Logistics board.

## v3.5.27 Contract log edge alignment

- Removes the left and right inset around the Contract log table.

## v3.5.26 Browse dialog fix

- Fixes the native Browse dialog filter so selecting `Game.log` opens correctly.

## v3.5.25 Contract log splitter

- Matches the main-window control top spacing to the right spacing.
- Adds a draggable bottom splitter to resize the Contract log panel.
- Remembers the Contract log height between launches.

## v3.5.24 main-window chrome spacing

- Adds a little top and right margin around the custom main-window controls.
- Keeps the title strip visually transparent.

## v3.5.23 overlay lock movement fix

- Restores overlay header dragging after size-lock changes.
- Keeps position lock as the only setting that disables header movement.
- Replaces pywebview drag-region movement with an explicit native cursor-driven move loop.

## v3.5.22 dashboard and movement regression fix

- Fixes the dashboard refresh crash caused by an optional version label that was no longer present in the DOM.
- Routes Browse through the desktop controller fallback so the native file picker remains available in the packaged app.
- Replaces the main-window non-client move message with a cursor-driven native move loop.

## v3.5.21 main-window movement fix

- Restores main-window dragging from the empty custom title strip.
- Uses the same top-level native window targeting as the borderless resize path.
- Keeps the title strip visually transparent and preserves the existing custom window controls.

## v3.5.20 borderless resizing and chrome refinement

- Restores main-window edge and corner resizing with invisible HTML handles.
- Replaces the overlay's temporary `WS_THICKFRAME` / `WM_NCLBUTTONDOWN` path with a dedicated native cursor-driven `SetWindowPos` loop.
- Uses no custom WndProc hook and no JavaScript mouse-move resize calls.
- Keeps the main title strip visually transparent with only window controls on the right.
- Removes the overlay title logo.
- Enlarges the dashboard logo and removes its surrounding card/border.
- Preserves the separate overlay companion process and all parser, session, checklist, API, dashboard, and export behavior.

## v3.5.19 custom desktop chrome update

- Added themed main-window minimize, maximize/restore, and close controls.
- Added the supplied cargo logo and Windows build icon.
- Restored overlay movement through pywebview's drag-region mechanism.
- Attempted temporary native-frame overlay resizing; v3.5.20 replaces that path.

## v3.5.18 overlay resize and position-lock fix

This update keeps the separate v3.5.13+ companion-process architecture and the safe frameless approach restored in v3.5.17.

- Invisible HTML edge and corner handles now invoke Windows' normal `SC_SIZE` loop for all eight directions.
- `WS_THICKFRAME` is enabled only while the native sizing loop is active and is removed immediately afterwards.
- The overlay remains visually frameless at rest; no WebView2 WndProc subclass is used.
- Header dragging now invokes Windows' normal `SC_MOVE` loop instead of relying on a pywebview drag region bound at page startup.
- **Lock position** prevents the move command before a drag starts, and unlocking restores dragging immediately.
- **Lock size** hides the resize handles and the native command also rejects resizing while locked.
- The isolated overlay process, settings, checklist synchronization, parser, and exports are unchanged.

## Desktop-first application

- The main dashboard opens in its own centered application window.
- The Logistics Overlay is a separate frameless Windows companion process, isolated from the main dashboard.
- Browse, CSV export, and HTML export use native Windows dialogs.
- The selected `Game.log` path, overlay size, opacity, and window-behavior settings are remembered.
- A second copy of the desktop app is blocked to avoid duplicate watchers and overlays.
- Browser mode remains available only for diagnostics.
- Parser, checklist, session calculations, exports, and route grouping remain fully local.

## Build the standalone executable

1. Extract this project to a normal folder.
2. Install a current 64-bit Python 3 release from python.org and enable **Add Python to PATH**.
3. Double-click `build_exe.bat`.
4. The release file is created at:

```text
dist\SCHT.exe
```

`SCHT.exe` is a PyInstaller one-file Windows application. It includes the Python runtime, SCHT code, UI assets, and pywebview dependencies. **Players do not need Python or the source project.** Python is required only on the developer/build machine. The executable extracts its internal runtime to a temporary directory while running, and permanent application settings remain under `%LOCALAPPDATA%\SCHT\`.

`build_single_exe.bat` remains as a compatibility shortcut and runs the same one-file builder.

## Recommended release: Windows installer

1. Build `dist\SCHT.exe` with `build_exe.bat`.
2. Install Inno Setup 6 on the build PC.
3. Run `build_installer.bat`.
4. Distribute `dist\SCHT-Setup-1.5.66.exe`.

The installer is per-user and normally needs no administrator permission. It installs SCHT under `%LOCALAPPDATA%\Programs\SCHT`, creates Start Menu integration, and offers an optional desktop shortcut. Uninstalling SCHT removes the installed files, shortcuts, `%LOCALAPPDATA%\SCHT`, and the former `%LOCALAPPDATA%\SC Hauling Log Tracker` folder. It does not remove Microsoft Edge WebView2 because that is a shared Windows component.

The portable `SCHT.exe` remains useful for internal testing. Deleting only a portable EXE does not delete its AppData; use the installer for normal public distribution and clean uninstall behavior.

When the project is hosted on GitHub, the included **Build SCHT Windows release** workflow creates both the portable executable and installer on a `windows-latest` runner. Download the `SCHT-windows-release` artifact.

## WebView2

The desktop interface uses Microsoft Edge WebView2. It is normally already installed on Windows 10 and Windows 11. Install or repair the WebView2 Runtime if the EXE opens without a usable window.

## Compact frameless overlay

- No Windows title bar or utility-window chrome.
- Drag the custom **Hauling loadout** header while position lock is disabled.
- Resize from the window edges while size lock is disabled.
- Checklist rows and header controls remain clickable.
- The cargo list scrolls independently while the header, progress area, and footer remain fixed.
- Windows 11 rounded corners are requested where supported.
- Native transparent-background mode remains disabled; opacity uses the normal Windows window-opacity property.

## Logistics Overlay

Open it from **Logistics Board → Open overlay**.

- Use the gear button to open overlay settings.
- Use the minimize button to send the overlay to the taskbar.
- Use the close button to destroy the current overlay window; opening it again creates a fresh centered window.
- Click cargo rows to mark them loaded.
- Resize from any window edge unless **Lock size** is enabled.
- Drag the header unless **Lock position** is enabled.

### Global shortcuts

- `Ctrl + Shift + O` — show/hide overlay
- `Ctrl + Shift + R` — close and reopen the overlay centered

Use Star Citizen in **Borderless** or **Windowed** mode. A normal Windows topmost overlay is not guaranteed above exclusive fullscreen.

## Local data

App-owned settings and session data are stored under:

```text
%LOCALAPPDATA%\SCHT\
```

This includes:

- `app-settings.json` — remembered Game.log path
- `main-window.json` — main application geometry
- `overlay-window.json` — overlay size, opacity, and window-behavior settings
- `loading-checklist.json` — checklist state shared by the dashboard and overlay processes
- `webview\` — main-dashboard WebView storage
- `overlay-webview\` — isolated overlay WebView storage
- `overlay-process.log` — companion-process startup and exit diagnostics

No external account or cloud connection is used.

## Diagnostic browser mode

Browser mode is retained for troubleshooting the parser/server only:

```bat
run_browser_mode.bat
```

or:

```bat
py -3 sc_hauling_tracker.py --browser
```

The native Logistics Overlay is intentionally disabled in browser mode.

## Synthetic test log

`test_data\Debug_Game.log` contains completed, abandoned, and active contracts with direct, shared-pickup, and shared-drop-off layouts. Use **Browse** to select it when testing the dashboard or overlay without changing your live Star Citizen log.

## Development launch

Install the packages in `requirements-build.txt`, then run:

```bat
run_app.bat
```

## Command-line parsing and exports

```bat
py -3 sc_hauling_tracker.py --no-gui --log "D:\StarCitizen\Game\StarCitizen\LIVE\Game.log" --csv manifest.csv --html manifest.html
```

## Project files

- `sc_hauling_tracker.py` — parser, session state, server, dashboard, and native overlay
- `build_exe.bat` — standard portable one-file `SCHT.exe` build
- `build_single_exe.bat` — compatibility shortcut to the standard builder
- `run_app.bat` — development/source desktop launch
- `run_browser_mode.bat` — diagnostic browser launch
- `run_tests.bat` — parser regression test runner
- `requirements-build.txt` — pywebview and PyInstaller dependencies
- `installer/SCHT.iss` — Inno Setup per-user installer/uninstaller definition
- `build_installer.bat` — verified Windows installer builder
- `SCHT.spec` — PyInstaller one-file packaging definition
- `version_info.txt` — Windows `SCHT.exe` metadata
- `assets/sc_hauling_logo.png` / `sc_hauling_logo_mark.png` — dashboard artwork
- `assets/sc_hauling_app_icon.png` / `sc_hauling_logo.ico` — transparent, tightly cropped Windows application icon
