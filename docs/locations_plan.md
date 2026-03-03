# Locations & Movement Investigation Plan

## Scope and call paths (UI → Controller → Model → comms)

### 1) Location definition and persistence
1. Locations are primarily defined in `FreeRTOS-interface/Presets/Locations.json` (`home`, `pause`, `plate`, `camera`, `balance`, rack anchors).
2. `Model.__init__` wires the path into `LocationModel(json_file_path=..., obstacle_path=...)` and calls `load_locations()`.
3. `LocationModel.load_locations()` deserializes JSON into `self.locations` and emits `locations_updated`.
4. Save/write path is `LocationModel.save_locations()` (atomic temp write + replace), invoked from UI flow when user confirms write.

### 2) Adding/updating locations
1. `View.add_new_location()` prompts for a name and calls `Controller.add_new_location(name)`.
2. `Controller.add_new_location()` writes current machine coordinates into `LocationModel.add_location(name, x, y, z)`.
3. `View.modify_location()` selects an existing name and calls `Controller.modify_location(name)`.
4. `Controller.modify_location()` calls `LocationModel.update_location(name, x, y, z)`.
5. Persistence is optional in both flows (`View` asks whether to write to file, then calls `Controller.save_locations()`).

### 3) Location presentation in the view
1. Movement target selection is on-demand: `View.move_to_location()` opens a popup with `LocationModel.get_location_names()`.
2. Current location shown in status box is `MachineModel.current_location`.
3. `LocationModel.current_location_updated` is connected to `MachineModel.update_current_location`, so location labels are mostly queue/command driven, not sensor-validated.

### 4) Movement to named locations
1. `View.move_to_location()` checks motor enabled/homed gates and calls `Controller.move_to_location(...)`.
2. `Controller.move_to_location()`:
   - chooses `safe_z` by profile,
   - determines `current_location` and `current_z` from **expected** state (`expected_location`, `expected_position`),
   - gets target coords from `LocationModel` or explicit `coords`,
   - applies guard rules (camera/slot/balance),
   - sends axis commands via `set_absolute_Z/Y/X` and final `set_absolute_coordinates(X, Y, Z)`.
3. `set_absolute_coordinates()` chooses ordering: if numerically lowering Z value (physically up in inverted axis), does Z first; else XY first then Z.
4. `Controller` sends machine commands (`Machine_FreeRTOS.set_absolute_*` / `set_relative_*`) into command queue.

### 5) Arbitrary position movement
1. Relative arbitrary moves: `Controller.set_relative_coordinates(x, y, z)`.
2. Absolute arbitrary moves: `Controller.set_absolute_coordinates(x, y, z)`.
3. Calibration pipeline path also sends arbitrary positions:
   - `CalibrationManager.moveRequested` → `Controller.handle_move_request` → `set_relative_coordinates`.
   - `CalibrationManager.moveAbsoluteRequested` → `Controller.handle_absolute_move_request` → `set_absolute_coordinates`.
4. Collision checks run against obstacle/boundary model before command dispatch (unless `override=True`).

---

## How locations are currently used (key information)

- Locations are free-form string keys mapped to `{X,Y,Z}` dicts; no schema validation or reserved-name protection.
- Rack slot movements (`Slot-1`, etc.) are usually synthetic names with coordinates from `RackModel.get_slot_coordinates`, not persisted named locations.
- Movement safety logic is context-name based (`camera`, `balance`, `'Slot' in name`) and not based on richer location metadata.
- Safe height constants are hardcoded in controller (`35000` current profile, `5000` legacy).
- The app tracks an `expected_position`/`expected_location` shadow state used for sequencing and safety decisions.

---

## Identified inconsistencies and vulnerabilities

## A) Safe-height logic / inverted Z handling
1. **Core bug:** `move_to_location` only auto-disables safe-height when **both** current and target are above safe height (`current_z < safe_z and target_z < safe_z`).
   - With inverted Z semantics (smaller Z = physically higher), this still triggers safe-height moves when starting above safe height but targeting below safe height.
   - Result: unnecessary/possibly risky intermediate Z move can be injected despite already being safely high.

2. Safe-height decision is tightly coupled to location-name transitions (camera/slot/balance) rather than physical path/risk model.

3. For balance moves, safe-height is always forced regardless of `ignore_safe_height` (commented conditional), creating policy inconsistency.

## B) State source / synchronization risks
4. `move_to_location` uses `expected_position` and `expected_location`, not actual machine telemetry at call time.
   - If queue history, missed status, or manual interventions desync expected state, safe logic may use stale data.

5. Command return values (`set_absolute_Z/Y/X/...`) are ignored in sequencing.
   - If any move is rejected (collision/bounds/check failure), follow-up moves may still queue, breaking intended safe path guarantees.

## C) Location identity and naming inconsistencies
6. Home naming mismatch: persisted location key is `home` while machine state sets location to `Home` after homing.
   - This can create UI/logic branching inconsistencies and brittle string comparisons.

7. Name matching is case-sensitive and substring-based:
   - `camera` and `balance` checks depend on exact lowercase names,
   - slot detection relies on `'Slot'` capitalization/prefix pattern.
   - User-created names can accidentally bypass or trigger guard behavior.

8. `direct` and `safe_y` parameters in `move_to_location` exist but are effectively unused in behavior.
   - Signals API drift and confuses callers about guarantees.

## D) Model robustness / validation gaps
9. `get_location_dict(name)` can return `None`; `move_to_location` then calls `.copy()` and can crash.

10. `LocationModel.update_current_location(name)` emits even when name is unknown.
   - UI can display non-existent locations as if valid state.

11. `LocationModel.add_location` / `update_location` do not validate coordinate types/ranges.
   - Invalid persisted coordinates can propagate to motion calls.

12. Obstacles/boundary loading fallback sets arrays (`[]`) on error, but `check_collision` expects boundary dict keys (`['min']['X']...`).
   - If obstacle config is missing/invalid, movement checks can throw runtime errors.

## E) Operational UX/safety concerns
13. Add/modify location flows can capture machine coordinates without requiring homed/enabled state in the add/modify handlers themselves.

14. Persist-to-file is optional prompt after add/modify; operators can assume save succeeded when data is only in-memory.

15. `coords` override path bypasses named-location provenance and can mix synthetic names with arbitrary coordinates without explicit validation policy.

---

## Tests to add (aligned to current pytest structure)

Use existing lightweight controller-construction pattern from `tests/test_controller_move_to_location.py` and model unit tests style.

### 1) Expand `tests/test_controller_move_to_location.py`
1. `test_move_to_location_when_start_above_safe_height_does_not_insert_safe_z_even_if_target_below_safe`
   - Parametrize for current + legacy safe thresholds.
   - Assert no intermediate `set_absolute_Z(safe_z)` when `current_z < safe_z`.

2. `test_move_to_location_aborts_sequence_when_safe_z_move_fails`
   - Stub `set_absolute_Z` to return `False`.
   - Assert no subsequent XY/XYZ commands are issued.

3. `test_move_to_location_missing_location_name_is_handled_without_crash`
   - `get_location_dict` returns `None`.
   - Expect graceful failure path (return False / emit error), not exception.

4. `test_move_to_location_name_matching_is_normalized`
   - Verify case-insensitive handling for `Camera`, `BALANCE`, `slot-1` (if that is selected policy).

5. `test_move_to_location_balance_respects_ignore_safe_height_policy`
   - Lock expected behavior explicitly (either always enforce for balance or respect flag consistently).

### 2) Add `tests/test_location_model_validation.py`
1. `test_add_location_rejects_non_numeric_coordinates`.
2. `test_add_location_rejects_out_of_bounds_coordinates` (or clamps if chosen policy).
3. `test_update_current_location_unknown_name_not_emitted_as_valid`.
4. `test_location_name_normalization_or_reserved_name_policy`.

### 3) Add/expand collision robustness tests
1. In controller safety tests, add `test_check_collision_handles_missing_boundaries_config_gracefully`.
2. Verify movement API returns safe failure (False + message) instead of throwing when obstacles config missing/corrupt.

### 4) Add integration-ish sequencing tests (controller level)
1. `test_move_to_location_uses_actual_position_source_when_required` (if adopting actual-vs-expected strategy).
2. `test_move_to_location_offsets_are_validated_before_dispatch`.

---

## Implementation plan (minimal, incremental)

1. **Define location semantics contract**
   - Normalize location naming policy (case handling, reserved names, slot naming expectations).
   - Document inverted Z policy and safe-height interpretation in comments/tests.

2. **Refactor `move_to_location` safety decision into a pure helper**
   - Extract decision logic into testable function (inputs: current/target pose + route context + profile).
   - Ensure rule: if already above safe height (current_z < safe_z), do not inject safe-height ascent.

3. **Harden command sequencing**
   - Check return values of each guard move; abort sequence on failure and emit a controller error signal.

4. **Unify name handling and transition categories**
   - Replace raw substring checks with normalized categorical helpers (`is_camera_location`, `is_slot_location`, `is_balance_location`).

5. **Handle missing/invalid location data defensively**
   - Guard `get_location_dict(name)` results.
   - Validate/normalize `coords` overrides before use.

6. **Harden collision-config fallback**
   - Make `check_collision` robust to missing/invalid boundaries/obstacles payloads with deterministic safe behavior.

7. **Address API drift**
   - Either implement `direct`/`safe_y` behavior or remove/deprecate them with clear call-site updates.

8. **Ship tests first for behavior lock, then small implementation slices**
   - Add failing tests for above-safe-height bug and failure-short-circuit behavior,
   - implement minimal fixes,
   - then add validation and naming robustness tests.

---

## Verification checklist for the implementation phase

1. Run Python unit tests: `python -m pytest -q`.
2. Run targeted location tests while iterating:
   - `python -m pytest -q tests/test_controller_move_to_location.py`
   - `python -m pytest -q tests/test_location_model_validation.py` (new)
3. Manual sanity checks (no hardware risk):
   - Simulate moves from camera→plate when already above safe height and verify no redundant safe-Z insertion.
   - Simulate balance route with selected policy and verify deterministic ordering.
   - Confirm status location updates are only from valid/normalized names.

---

## Rollback plan (for future implementation PR)

1. Revert controller movement logic changes only (`Controller.py`) if regressions appear.
2. Keep added tests; mark failing expectations as xfail temporarily only if policy is unsettled.
3. If location validation causes compatibility issues with legacy JSONs, gate strict validation behind warning mode, then tighten in follow-up.
