# Well Plate Handling Review and Remediation Plan

## Scope
This review covers well-plate handling in the Python app (`FreeRTOS-interface`) with emphasis on:
- plate definitions
- model lifecycle and reassignment behavior
- view presentation and plate switching UX
- reaction-to-well assignment (automatic + manual)
- progress/key file implications
- when/where plate format is set and changed
- inconsistencies and vulnerabilities
- tests to add (aligned with the current `pytest` structure)
- implementation plan

---

## 1) How well plates are currently defined

### Source of truth
- Plate definitions are loaded from `FreeRTOS-interface/Presets/Plates.json`.
- Current entries include:
  - `50well-5x10`
  - `96well-8x12`
  - `shallow-384_well_plate` (marked as default)
- Each plate entry contains:
  - `name`
  - `rows`
  - `columns`
  - `spacing`
  - `default`
  - `calibrations` (optionally pre-populated)

### In-memory representation
- `Model.__init__` loads all plates, then creates `WellPlate(all_plate_data, plates_path)`.
- `WellPlate` sets:
  - `current_plate_data` from `get_default_plate_data()`
  - `rows`, `cols`
  - `wells` via `create_wells()`
  - `excluded_wells` as an empty set
  - calibration state via `apply_calibration_data()`

### Well IDs
- Well IDs are generated as `f"{chr(row + 65)}{col + 1}"`.
- This is single-letter row naming (`A..Z`) + 1-based column index.

---

## 2) How plates get added to / changed in the model

### Initial selection
- Startup uses whichever plate in `Plates.json` has `"default": true`.

### Change path
- `WellPlate.set_plate_format(plate_name)`:
  - updates `current_plate_data`, `rows`, `cols`
  - recreates all wells (`create_wells`)
  - swaps calibrations for selected plate
  - reapplies calibration
  - emits `plate_format_changed_signal`

### Additional model-level flows that affect plate state
- `Model.load_experiment_from_model(plate_name=...)`:
  - clears experiment state
  - can set plate format before assigning reactions
  - assigns reactions (manual explicit wells or auto zig-zag)
  - writes progress/key/concentration-key
- `Model.update_well_plate()`:
  - triggered by `plate_format_changed_signal`
  - clears only reaction assignments
  - reassigns all reactions either manual or auto
  - emits `experiment_loaded`

---

## 3) How well plates are presented in the view

### Plate selection UI
- `WellPlateWidget` creates a `QComboBox` with all plate names from model.
- Current selection is initialized from model current plate.
- Changes call `on_plate_selection_changed()`.

### Plate switching behavior
- If a printer head is in gripper: switching is blocked and combobox reset.
- If reactions exist:
  - user is warned that changing plate format clears current experiment
  - if confirmed, app calls `model.load_experiment_from_model(plate_name=selected)`
- If no reactions exist:
  - app directly calls `model.well_plate.set_plate_format(selected)`

### Grid presentation
- `update_grid()` rebuilds `QLabel` matrix from `(rows, cols)`.
- `update_well_colors()` uses assigned reactions and selected stock to color cells.
- Indices rely on `well.row_num` and `well.col - 1`.

---

## 4) How reactions are assigned to wells

### Automatic assignment
- `WellPlate.assign_reactions_to_wells(reactions, fill_by="columns", start_row=0, start_col=0)`:
  - gets available wells from `get_available_wells(...)`
  - applies zig-zag ordering
  - assigns in sequence

### Manual explicit assignment
- `Model._get_manual_well_assignments()` reads explicit well IDs (primarily from `ExperimentModel._uploaded_well_ids`).
- `WellPlate.assign_reactions_to_specific_wells(reactions, well_ids)` validates:
  - count match
  - well exists
  - not in excluded wells
  - not already assigned

### Trigger points
- On initial experiment load (`load_experiment_from_model`).
- On plate format change (`update_well_plate`, connected to plate-format signal).

---

## 5) Key/progress file impacts

### Progress
- `ExperimentModel.create_progress_file()` snapshots assigned wells into `progress.json`.
- Structure keyed by `well_id`, includes `reaction_id` and per-stock droplet state.

### Keys
- `create_key_file()` generates `key.csv` from `progress_data`.
- `create_concentration_key_file()` generates `concentration_key.csv` similarly.

### Plate coupling in persisted files
- `progress.json` and key CSVs are keyed by well IDs only.
- There is no explicit, enforced plate-format identifier in progress/key payload.
- `load_progress()` skips entries where well IDs are missing or reaction IDs do not match current assignments.

---

## 6) Where plate format is set and when it can be changed

### Set locations
- Startup default selection from `Plates.json`.
- Directly via `WellPlate.set_plate_format(...)`.
- During load via `Model.load_experiment_from_model(plate_name=...)` and `load_experiment_from_file(plate_name=...)`.

### User-visible change windows
- In Well Plate tab combobox (`on_plate_selection_changed`).
- Allowed when gripper is empty.
- If experiment data exists, requires user confirmation and triggers full model reload path.

---

## 7) Inconsistencies and vulnerabilities identified

### Issue A — `excluded_wells` type inconsistency can silently disable exclusions
`WellPlate.exclude_well()` stores well IDs as strings, but `get_available_wells()` checks `well not in self.excluded_wells` where `well` is a `Well` object. This mismatched type means exclusions added as IDs are not honored by auto-assignment filtering.

Impact:
- Excluded wells may still be treated as available during automatic assignment.
- Behavior differs depending on whether callers inserted `Well` objects vs string IDs.

Risk:
- Reactions assigned to wells the user intended to block.

---

### Issue B — Well ID scheme breaks for >26 rows (critical for 1536 format)
Well IDs are generated with single-letter row IDs using `chr(row + 65)`. For 32-row plates (1536, 32x48), rows after `Z` become non-alphabetic ASCII (`[`, `\\`, ...), breaking naming assumptions across model/view.

Impact:
- Invalid/ambiguous well IDs for high-density plates.
- Sorting and indexing behavior relying on row letters degrades.
- Manual well assignment semantics become unreliable for 1536.

Risk:
- Incorrect assignments, unusable UI indexing, incompatible persisted well IDs.

---

### Issue C — Plate format change emits duplicate format-changed signals
`create_wells()` emits `plate_format_changed_signal`, and `set_plate_format()` emits it again after calling `create_wells()`. This double-emission can trigger duplicate `update_well_plate()` and UI refresh runs.

Impact:
- Redundant reassignment and repaint cycles.
- Harder-to-reason ordering/side effects around format change.

Risk:
- Subtle race/reentrancy-like behavior in signal-driven flows.

---

### Issue D — Plate identity is not persisted in progress/key artifacts
`progress.json`, `key.csv`, and `concentration_key.csv` encode well IDs but not plate identity (`name`, dimensions, or schema/version). If plate format changes between runs, `load_progress()` silently skips incompatible entries.

Impact:
- Hidden data mismatch when reopening/changing plate formats.
- User may believe progress resumed while partial/none was applied.

Risk:
- Silent data loss or misinterpretation of print progress.

---

### Issue E — No strict validation of start-row/start-col against selected plate
Assignment filters wells by `well.row_num >= start_row` and `well.col >= start_col+1` but does not validate that `start_row/start_col` are in-bounds for the current plate before assignment attempt.

Impact:
- Out-of-range offsets degrade into “not enough wells” later, not a precise validation error.

Risk:
- Poor operator feedback; easier to misconfigure larger/smaller plate transitions.

---

### Issue F — Preserved exclusions may become stale across plate changes
`load_experiment_from_model()` preserves and reapplies `excluded_wells` across `clear_experiment()` and optional plate change. No normalization/revalidation occurs against the new plate format.

Impact:
- Invalid exclusions can persist silently.
- Exclusions referencing nonexistent wells are not surfaced.

Risk:
- Inconsistent exclusion behavior and operator confusion.

---

### Issue G — Plate definition validation is weak
`load_all_plate_data()` accepts JSON content without schema checks (required fields, positive rows/cols, exactly one default, unique names, calibration key shape).

Impact:
- Corrupt/malformed `Plates.json` can fail late in runtime or produce undefined behavior.

Risk:
- Fragile startup and incorrect geometry/assignment behavior.

---

### Issue H — Experiment design metadata does not explicitly bind plate format
`ExperimentModel` metadata stores layout knobs (e.g., `start_row`, `start_col`, randomization) but does not encode selected plate format as a first-class compatibility field in design persistence.

Impact:
- Reopening design on a different active plate can silently alter assignment outcomes.

Risk:
- Non-reproducible experiment layouts across sessions.

---

## 8) Tests to add (aligned with current `pytest` structure)

Create tests under `tests/` using the existing `experiment_model_factory` pattern from `tests/conftest.py`.

1. `tests/test_wellplate_exclusions_consistency.py`
   - Verify `exclude_well("A1")` removes A1 from `get_available_wells()`.
   - Verify mixed legacy state (`{Well("A1"), "B1"}`) is normalized/handled consistently.
   - Verify auto-assignment never places reactions into excluded wells.

2. `tests/test_well_id_encoding_high_density.py`
   - Use a 32x48 plate fixture (1536-like).
   - Validate row naming uses deterministic multi-letter scheme (e.g., A..Z, AA..AF).
   - Validate `get_well`, assignment ordering, and view index mapping assumptions.

3. `tests/test_plate_format_change_signal_once.py`
   - Instrument or monkeypatch signal-connected handlers.
   - Assert one logical plate format change triggers one reassignment/update cycle.

4. `tests/test_progress_plate_compatibility.py`
   - Save progress on one plate format, switch to another, attempt load.
   - Assert explicit compatibility check/error/warning behavior (no silent skip).
   - Assert persisted progress includes plate format metadata.

5. `tests/test_start_row_col_bounds_validation.py`
   - Parameterize invalid `start_row/start_col` for 96/384/1536 shapes.
   - Assert precise `ValueError` with actionable message before assignment.

6. `tests/test_exclusion_revalidation_on_plate_change.py`
   - Preserve exclusions, change plate format, verify invalid exclusions are dropped or rejected with explicit reporting (whichever policy is adopted).

7. `tests/test_plates_json_schema_validation.py`
   - Feed malformed plate definitions (missing fields, duplicate names, invalid defaults).
   - Assert deterministic startup/load errors with clear messages.

8. `tests/test_experiment_design_plate_binding.py`
   - Persist and reload design metadata with plate format.
   - Assert mismatch handling policy (block, force-confirm, or remap).

9. `tests/test_view_plate_selection_sync.py`
   - Verify combobox stays in sync after plate changes via model/API and after experiment reload.
   - Verify blocked switch with loaded gripper restores previous selection reliably.

10. `tests/test_key_progress_include_plate_fields.py`
   - Assert progress payload carries plate name/dimensions/version.
   - Assert key file generation path includes or cross-validates against the same plate metadata source.

---

## 9) Implementation plan

1. **Normalize well identity model-wide**
   - Standardize `excluded_wells` to `set[str]` of canonical well IDs.
   - Add helper(s) to normalize/validate IDs centrally.

2. **Introduce robust row encoding for high-density plates**
   - Replace single-letter ID generation with Excel-like row labels (`A..Z, AA..`).
   - Update row parsing/indexing helpers in `Well` and ordering logic.

3. **Harden plate format change signaling**
   - Emit `plate_format_changed_signal` exactly once per logical plate switch.
   - Ensure `update_well_plate()` is not invoked redundantly.

4. **Add explicit plate compatibility metadata to persisted artifacts**
   - Include `plate_name`, `rows`, `columns` (and optional schema version) in progress/design persistence.
   - Enforce checks on `load_progress()` and design reload.

5. **Validate assignment preconditions early**
   - Validate `start_row/start_col` bounds before assignment.
   - Validate manual well IDs against current plate with clear errors.

6. **Revalidate exclusions on plate change**
   - On format change/load, canonicalize and prune/flag invalid excluded wells.
   - Define explicit policy and user feedback path.

7. **Schema-validate `Plates.json` at load time**
   - Enforce required keys/types/ranges.
   - Enforce unique names and exactly one default (or deterministic fallback policy).

8. **Expand automated tests first for safety-critical behavior**
   - Add the tests listed above.
   - Keep changes incremental: tests for one risk cluster, then minimal code fixes.

9. **UI synchronization and operator feedback improvements**
   - Ensure combobox/model state always converge.
   - Surface plate mismatch and exclusion pruning events explicitly.

10. **Migration/backward compatibility**
   - Provide fallback handling for old progress/design files without plate metadata.
   - Add one-time upgrade path or explicit warning.

---

## 10) Recommended delivery order (small, safe slices)

1. Fix exclusion type mismatch + tests.
2. Add bounds validation for start row/col + tests.
3. Add single-emission format-change behavior + tests.
4. Add plate metadata to progress/design + compatibility checks + tests.
5. Add 1536-capable well ID encoding + tests.
6. Add `Plates.json` schema validation + tests.

This order minimizes risk by first fixing currently silent misassignment hazards, then strengthening compatibility guarantees, then enabling larger plate formats safely.

---

## 11) Follow-up plan: move plate-format ownership into Experiment Design window + improve well plate UX

### Target behavior
1. **Plate format is set only in `ExperimentDesignDialog`** (designer window), via a dropdown near existing metadata/settings controls.
2. Main-window well-plate tab is **display-only for plate format** (no local format switching control).
3. Main-window grid shows **axis identifiers**:
   - row labels on the left (`A`, `B`, ...)
   - column labels on top (`1`, `2`, ...)
4. Each well has a tooltip showing for the currently selected reagent:
   - target droplet count for that well
   - final concentration in that well (for selected reagent)
5. Keep assignment/calibration safety behavior unchanged (no firmware/protocol impact).

### Call path for the proposed implementation
- UI:
  - `ExperimentDesignDialog` (plate selector source of truth)
  - `WellPlateWidget` (read-only presentation, headers, tooltips)
- Model:
  - `Model.load_experiment_from_model(plate_name=...)`
  - `WellPlate.set_plate_format(...)`
  - reaction/well lookups for tooltip values
- Controller/comms/firmware:
  - unchanged

### Proposed implementation plan (≤8 steps)
1. **Add designer plate selector**
   - Add a `QComboBox` in `ExperimentDesignDialog` near metadata controls.
   - Populate from `model.well_plate.get_all_plate_names()`.
   - Initialize from currently active plate (or `experiment_model.metadata["plate_name"]` if set).

2. **Persist selection in design metadata**
   - On designer updates/finish, store selected plate in metadata (`plate_name`).
   - Keep `plate_rows`/`plate_columns` synchronized after application.

3. **Apply format only during design apply/finish path**
   - When user confirms design and app loads from model, pass `plate_name` into `load_experiment_from_model`.
   - Ensure no implicit plate mutation in the main well-plate tab.

4. **Remove main-window plate-format mutator**
   - Remove `plate_selection` combobox (or replace with read-only label showing active format).
   - Remove `on_plate_selection_changed` mutation path from main window.

5. **Add row/column headers in grid**
   - In `WellPlateWidget.update_grid()`, reserve first row/column for labels.
   - Render top headers as numeric columns and left headers as row labels via `Well.index_to_row_label`.

6. **Add per-well tooltip data**
   - In `update_well_colors()` (or a helper called from it), set tooltip per cell:
     - if reaction assigned: show selected reagent target droplets + final concentration
     - if absent: show “No reaction assigned”
   - Concentration source options:
     - preferred: model helper `get_final_concentration_for_well_stock(well_id, stock_id)`
     - fallback: compute from reaction composition + volume metadata in one shared helper.

7. **Add tests for new view behavior**
   - Designer-only plate ownership (main window cannot change plate format).
   - Grid header rendering for rows/columns with multi-letter rows.
   - Tooltip content correctness for selected reagent and unassigned wells.

8. **Validation + migration sanity checks**
   - Verify old designs without `plate_name` fall back to current default safely.
   - Verify selected plate remains consistent across reopen/finish cycles.

### Test cases to add for this follow-up
1. `tests/test_experiment_designer_plate_selector.py`
   - selector exists in designer
   - selected plate is persisted in metadata on finish

2. `tests/test_wellplate_widget_no_plate_mutation.py`
   - no mutable plate-format control in main widget (or control is disabled/read-only)

3. `tests/test_wellplate_grid_headers.py`
   - top numeric headers and left alpha headers render with correct dimensions

4. `tests/test_wellplate_tooltips_selected_reagent.py`
   - assigned well shows droplets + concentration for selected reagent
   - unassigned well shows neutral message

5. `tests/test_plate_selection_applies_on_finish_only.py`
   - plate format changes only when design is applied/finished

6. `tests/test_designer_plate_reopen_consistency.py`
   - reopening designer reflects active/saved plate selection

### Additional recommendations (view + model)
1. **Introduce a typed plate config schema object**
   - Encapsulate `name/rows/columns/spacing/calibrations` instead of loose dicts.
   - Reduces key-typo bugs and simplifies validation.

2. **Add `WellPlate.iter_well_ids()` and `iter_rows()` helpers**
   - Keep view rendering independent from internal dict ordering.

3. **Centralize concentration calculation in model**
   - Avoid duplicate concentration math in view/tooltips and CSV generation.
   - Provide one model API used by both tooltip/UI and export paths.

4. **Expose active plate summary signal**
   - Emit plate name/dimensions metadata signal for labels/status bars.
   - Reduces direct view polling.

5. **UX safety for incompatible progress on plate mismatch**
   - Keep strict mismatch check; add user-facing message in UI with recovery action.

6. **Header/tooltip performance guard**
   - Cache tooltip strings per selected reagent and invalidate only on relevant events.
   - Important for larger plates (384/1536).

7. **Accessibility/readability**
   - Ensure headers/tooltips adapt to dark theme and high-DPI.
   - Keep tooltip format concise and consistently unit-tagged.
