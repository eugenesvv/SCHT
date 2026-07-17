# Route Planner persistence test

Use the separate test build at `D:\Projects\SCHT\dist-next\SCHT.exe`. The normal `dist` build is not replaced.

## 1. Prepare a clean staged log

1. Close every older SCHT window.
2. In PowerShell run:

   ```powershell
   cd D:\Projects\SCHT
   .\tools\prepare_route_debug_log.ps1 reset
   ```

3. Start `D:\Projects\SCHT\dist-next\SCHT.exe`.
4. In Settings, use **Reset session** once.
5. Choose `D:\Projects\SCHT\test_data\Route_Planner_Persistence_Working.log` and press **Scan Log**.
6. Keep the multi-pickup workaround **off** for this route-editing test.

Expected baseline: **6 accepted contracts**, **9 cargo rows**, no completed contracts. The fixture includes a two-pickup contract, a three-pickup contract, and ordinary single-route contracts.

## 2. Test persistent presets

1. Press **All active** and note the first three stops.
2. Open **Contracts**, select only the Rustville and Endgame contracts, and close the picker.
3. Confirm a selected-contract route appears automatically.
4. Press **All active**. Its original order must return unchanged.
5. Open **Contracts** again. The selected-contract route and selection must return unchanged.
6. Do not expect a preset to be rebuilt merely because you switched to it.

## 3. Test Custom editing

1. Return to **All active**, then press **Edit**. The button must become highlighted and read **Custom**.
2. Drag unfinished cards into a different valid order. A drop-off cannot be placed before its required pickup.
3. Add a normal waypoint, for example **Nyx Gateway**.
4. Set a fixed start, for example **Everus Harbor**, and a fixed end, for example **Stanton Gateway**.
5. Change each endpoint once more. The old endpoint must disappear rather than remain as a duplicate waypoint.
6. Confirm **Reoptimize remaining route** appears after manual changes.
7. Press it. The fixed start and end must remain first and last; the ordinary custom waypoint remains in the route.
8. Switch to **All active**, then press **Edit** again. The same Custom route must return.
9. Close and reopen SCHT, select the same working log, and scan it. All three route workspaces must still be available.

## 4. Test progress without automatic reshuffling

1. In Custom mode, arrange **The Golden Riviera** first and **Rustville** second.
2. On the Logistics Board, check every cargo item at The Golden Riviera. Its route card becomes green only after every pickup shown on that card is checked.
3. With Watch enabled, run:

   ```powershell
   .\tools\prepare_route_debug_log.ps1 phase1
   ```

   If Watch is off, press **Scan Log** afterward.

4. The Rustville contract and route card must become completed/green. The remaining route must not silently reorder.
5. Press **Reoptimize remaining route**. The contiguous completed green prefix stays fixed; only unfinished stops are optimized.
6. Append the second completion stage:

   ```powershell
   .\tools\prepare_route_debug_log.ps1 phase2
   ```

   Endgame must become completed without clearing the saved route.

## 5. Test a combined pickup and drop-off stop

Gaslight contains both a Hydrogen drop-off and a Potassium pickup.

1. Check the Potassium pickup at Gaslight on the Logistics Board while the Gaslight delivery contract is still accepted.
2. Confirm the Gaslight route card is **not** green yet.
3. Run:

   ```powershell
   .\tools\prepare_route_debug_log.ps1 phase3
   ```

4. Gaslight turns green only when both conditions are true: its pickup is checked and its delivery contract is completed.

## 6. Test explicit clearing

1. Press the Route Planner trash button while Custom is active. Only the Custom workspace should be removed.
2. Press **All active**. Its preserved workspace should still exist.
3. Clear All active explicitly, then press **All active** again. Only now should SCHT calculate a fresh route.

When reporting a failure, include the step number, a screenshot, and the current `Route_Planner_Persistence_Working.log`.
