# Experiment Design Reagent + Head Type Integration Plan

## Scope

This is a design-only plan for integrating calibration-memory-aware reagent selection and intended printer-head-type selection into the Experiment Design Window.

No code changes are proposed in this document.

Goals:

- upgrade reagent selection from freeform-only text to registry-backed selection with a new-reagent path
- add intended `head_type_id` selection per reagent row
- show prior availability per reagent row using the existing calibration-memory sidecar and recommendation index
- keep disposable `printer_head_id` generation in the runtime/model layer, not in the design UI
- preserve current experiment design semantics and saved designs where practical

Non-goals for this phase:

- no change to calibration execution semantics
- no new runtime dependency for the main app
- no new parallel reagent database
- no direct UI integration into `DropletImagingDialog` beyond reusing the existing calibration-memory architecture

## Architecture Summary

### Current call paths

Experiment design authoring today:

`MainWindow.open_experiment_designer()` in `FreeRTOS-interface/View.py`
-> `ExperimentDesignDialog` in `FreeRTOS-interface/View.py`
-> `ExperimentDesignDialog._rebuild_model_from_table()`
-> `ExperimentModel.add_additive()` / `ExperimentModel.add_choice_group()` / `ExperimentModel.add_choice_option()` in `FreeRTOS-interface/Model.py`
-> `ExperimentModel.optimize_stock_solutions()`
-> `ExperimentModel.generate_experiment()`
-> `MainWindow.complete_experiment_design()`
-> `Model.load_experiment_from_model()` in `FreeRTOS-interface/Model.py`
-> `Model.load_reactions_from_model()`
-> `StockSolutionManager.add_stock_solution()`
-> `Model.assign_printer_heads()`
-> `PrinterHeadManager.create_printer_heads()`

Calibration-memory lookup today:

`Model.__init__()` / `Model.reload_droplet_model()` in `FreeRTOS-interface/Model.py`
-> `CalibrationMemoryStore` in `FreeRTOS-interface/CalibrationMemoryStore.py`
-> `CalibrationIdentityRegistry` in `FreeRTOS-interface/CalibrationIdentity.py`
-> `CalibrationMemoryAggregator.get_best_prior()` in `FreeRTOS-interface/CalibrationMemoryAggregator.py`

Calibration-memory UI preview today:

`DropletImagingDialog` in `FreeRTOS-interface/CalibrationClasses/View.py`
-> `CalibrationManager.preview_calibration_memory_recommendation()` in `FreeRTOS-interface/CalibrationClasses/Model.py`
-> `CalibrationMemoryStore.get_best_prior(...)`

### Current ownership

Current designer row ownership:

- `ExperimentDesignDialog` owns the live row widgets in `self.reagent_table`
- `ExperimentModel` owns persisted row semantics via `FactorSpec` and `OptionSpec`
- `OptionSpec.name` is the current reagent string and flows into stock naming, keys, and runtime stock creation
- `OptionSpec.droplet_nL` already owns nominal droplet volume

Current runtime ownership:

- `StockSolution` owns runtime stock identity such as `stock_id`, `reagent_name`, `concentration`, `units`
- `PrinterHead` owns runtime physical-head state and already has Phase 2 identity fields:
  - `printer_head_id`
  - `head_type_id`
  - `display_name`
  - `nominal_nozzle_diameter_um`
- `PrinterHeadManager.create_printer_heads()` creates disposable runtime head objects, but does not yet assign explicit identity

Current calibration-memory ownership:

- `CalibrationMemoryStore.identity_registry` already owns reagent and head-type registries:
  - `FreeRTOS-interface/CalibrationMemory/entities/reagents.json`
  - `FreeRTOS-interface/CalibrationMemory/entities/printer_head_types.json`
- `CalibrationMemoryStore.get_best_prior(...)` already returns the best available prior using current aggregation rules
- `CalibrationMemoryAggregator.get_best_prior(...)` already supports:
  - `exact_pair`
  - `exact_reagent_head_type`
  - `reagent_family_head_type`
  - `reagent_only`
  - `head_type_only`

## Current Repo Findings

### 1. Experiment Design Window

Implemented in `FreeRTOS-interface/View.py`:

- `class ExperimentDesignDialog`
- `__init__`
- `_add_reagent_row`
- `_load_factors_into_table`
- `_rebuild_model_from_table`
- `_apply_uploaded_design_mode_to_ui`
- `_apply_default_edit_state`
- `_apply_gripper_edit_lock_state`
- `_refresh_all_lock_states`
- `_on_save_design`
- `_on_finish`

The current reagent table is created as `QTableWidget(0, 8, self)` with columns:

1. Reagent Name
2. Group
3. Starting
4. Targets
5. Units
6. Set Stock Conc
7. Droplet Vol (nL)
8. Delete

The reagent name cell is currently a freeform `QLineEdit`.

### 2. Experiment row model

Implemented in `FreeRTOS-interface/Model.py`:

- `@dataclass OptionSpec`
- `@dataclass FactorSpec`
- `ExperimentModel.add_additive(...)`
- `ExperimentModel.add_choice_option(...)`
- `ExperimentModel.to_dict()`
- `ExperimentModel.from_dict()`
- `ExperimentModel.set_uploaded_design_from_dataframe(...)`

Current persisted row semantics:

- `OptionSpec.name`
- `OptionSpec.targets`
- `OptionSpec.units`
- `OptionSpec.droplet_nL`
- `OptionSpec.starting_conc`
- optional dynamic `forced_stock_conc`

Current saved `experiment_design.json` stores only factor/option name-based reagent semantics. There is no persisted `reagent_id` or `head_type_id` yet.

### 3. Where the reagent string currently flows

The current freeform reagent string flows through these concrete seams:

- `ExperimentDesignDialog._rebuild_model_from_table()` reads the name widget and passes it into `ExperimentModel.add_additive(...)` or `ExperimentModel.add_choice_option(...)`
- `OptionSpec.name` is serialized in `ExperimentModel.to_dict()`
- `OptionSpec.name` is used in `ExperimentModel.optimize_stock_solutions()` when `_stock_rows_cache` rows are built as `factor_name` and `option_name`
- `Model.load_reactions_from_model()` converts stock rows into `StockSolutionManager.add_stock_solution(reagent_name, concentration, units, ...)`
- `StockSolutionManager._make_stock_id(...)` builds `stock_id` from the reagent string plus concentration and units
- `StockSolution.get_reagent_name()` feeds the current runtime reagent label
- `CalibrationContextBuilder.build()` reads the current runtime `StockSolution` and uses `stock_solution.get_reagent_name()` plus `CalibrationIdentityRegistry.resolve_reagent(...)`

This means the current reagent string is both:

- the user-facing row label
- the stock-id stem
- the runtime reagent display label
- the fallback calibration-memory reagent identity source

### 4. Where head type should connect

There is no intended head-type field in the experiment design path today.

The best existing seam is:

- persisted row-level source of truth in `OptionSpec`
- carried into stock rows during `ExperimentModel.optimize_stock_solutions()`
- copied into `StockSolution` during `Model.load_reactions_from_model()`
- copied into `PrinterHead.head_type_id` when runtime head objects are created

This preserves the intended-vs-physical distinction:

- experiment design owns intended `head_type_id`
- runtime `PrinterHead` owns physical `printer_head_id`

### 5. Where prior availability should be queried

The best existing API is:

- `Model.calibration_memory_store.get_best_prior(context, target_pulse_width_us=None, target_volume_nl=None)`

The best designer-time context is not the same as the live calibration context because the designer does not yet have a disposable `printer_head_id`.

The design-time prior query should therefore use:

- `reagent_id`
- `reagent_family` if available
- intended `head_type_id`
- `target_volume_nl = OptionSpec.droplet_nL`
- no `printer_head_id`
- no `pulse_width_us`

This naturally favors `exact_reagent_head_type` and grouped fallbacks, and it correctly excludes `exact_pair` at design time.

### 6. Where disposable `printer_head_id` should be generated

The correct runtime seam is after the experiment has been materialized into runtime `PrinterHead` objects.

Concrete candidate seams:

- `PrinterHeadManager.create_printer_heads(...)`
- `Model.assign_printer_heads()`

Recommended owner:

- top-level runtime `Model` should own the generation policy
- `PrinterHeadManager` should remain responsible for head object creation and slot assignment

Reason:

- top-level `Model` already owns `calibration_memory_store`
- top-level `Model` already bridges design data into runtime objects
- top-level `Model` can generate ids without coupling `PrinterHeadManager` directly to calibration-memory internals

## Recommended Architecture

## A. Data model changes

### Recommendation

Keep `OptionSpec` as the persisted row-level source of truth.

Add optional fields directly to `OptionSpec` instead of introducing a new persisted design model class.

Recommended new `OptionSpec` fields:

| Field | Owner | Persisted | Purpose |
| --- | --- | --- | --- |
| `reagent_id` | `OptionSpec` | yes | stable grouped reagent identity for memory/analysis |
| `reagent_display_name` | `OptionSpec` | yes | canonical user-facing reagent label from the registry |
| `intended_head_type_id` | `OptionSpec` | yes | intended dispensing configuration for this row |
| `intended_head_type_display_name` | `OptionSpec` | optional | cached display label; may also be derived from registry |

Fields that should stay as they are:

| Field | Owner | Reason |
| --- | --- | --- |
| `name` | `OptionSpec` | keep as the current stock/display label and stock-id stem for backward compatibility |
| `droplet_nL` | `OptionSpec` | already the correct owner for nominal droplet volume |
| `targets`, `units`, `starting_conc`, `forced_stock_conc` | `OptionSpec` | already correct row-level design semantics |

### What not to persist in `OptionSpec`

Do not persist prior availability status in the experiment design JSON.

Reason:

- it is derived from calibration-memory state
- it will become stale
- it is not design-authored data

Prior availability should be a transient UI/model preview result only.

### Stock/display naming recommendation

Do not replace `OptionSpec.name`.

Use `OptionSpec.name` as the current stock/display label and stock-id stem.

Use `OptionSpec.reagent_id` as the stable grouped identity for calibration memory.

This avoids breaking:

- stock-id generation
- existing progress/key files
- reagent-name-based option lookup
- old saved experiments

If a separate stock display label is needed later, it should be added as an optional alias field, not as a replacement for `name`.

## B. Runtime model changes

### `StockSolution`

`StockSolution` should continue to own actual stock identity:

- `stock_id`
- `reagent_name`
- `concentration`
- `units`

It should also carry the design-selected calibration-memory metadata copied from `OptionSpec`:

- `reagent_id`
- `display_name`
- `reagent_family`
- `glycerol_percent`
- `intended_head_type_id`
- optional `intended_head_type_display_name`

Recommended change:

- keep using `StockSolution.set_reagent_identity(...)`
- add a small companion setter for intended dispensing metadata, for example:
  - `StockSolution.set_intended_head_type(...)`

### `PrinterHead`

`PrinterHead` should remain the owner of physical disposable-head identity:

- `printer_head_id`
- `head_type_id`
- `display_name`
- nozzle metadata

The runtime should copy `StockSolution.intended_head_type_id` into `PrinterHead.head_type_id` when the physical head instance is created.

### `PrinterHeadManager`

Do not make the Experiment Design Window responsible for physical head instances.

Keep `PrinterHeadManager` responsible for:

- creating `PrinterHead` objects
- assignment to rack slots

Use top-level `Model` to decorate newly created `PrinterHead` objects with:

- generated `printer_head_id`
- copied `head_type_id`
- copied display/nozzle metadata from the head-type registry where available

### Disposable `printer_head_id` policy

Recommended policy:

- generate a unique runtime id when a `PrinterHead` object is created from a design-derived stock
- do not ask the user to enter it
- do not store it in the Experiment Design Window
- do not require it to exist in `entities/printer_heads.json`

Reason:

- disposable heads are single-use runtime objects
- `CalibrationIdentityRegistry.resolve_printer_head(...)` already treats explicit runtime `printer_head_id` values as usable even when they are unregistered
- this avoids polluting the curated printer-head registry with one-off disposable instances

Recommended id shape:

`<head_type_id or unknown>__<experiment token>__<utc timestamp>__<counter>`

Properties:

- unique
- human-readable
- slot-independent
- session-safe

## C. Prior availability architecture

### Recommendation

Do not make `ExperimentDesignDialog` parse memory snapshot files directly.

Add small wrapper methods on top-level `Model` that use the existing store and registry:

- list known reagents from `CalibrationIdentityRegistry`
- list known head types from `CalibrationIdentityRegistry`
- resolve a designer reagent selection into `reagent_id` metadata
- preview best available prior for a designer row

Recommended owner:

- top-level `Model` in `FreeRTOS-interface/Model.py`

Reason:

- it already owns `calibration_memory_store`
- it keeps calibration-memory internals out of the UI
- `ExperimentModel` stays focused on design math and persistence

Recommended designer-row prior query path:

`ExperimentDesignDialog`
-> top-level `Model.preview_experiment_design_prior(...)`
-> `CalibrationIdentityRegistry.resolve_reagent(...)`
-> `CalibrationMemoryStore.get_best_prior(...)`

### Prior availability categories

Recommended row categories:

- `Strong prior`
  - best prior is `exact_reagent_head_type`
  - confidence is above a conservative threshold
- `Some prior`
  - any weaker grouped fallback exists
  - or `exact_reagent_head_type` exists but confidence is lower
- `No prior`
  - no usable prior found
- `Head type not set`
  - row cannot be evaluated yet because intended head type is missing

Recommended interpretation policy:

- `exact_reagent_head_type` is the strongest design-time bucket
- `reagent_family_head_type`, `reagent_only`, and `head_type_only` are informational fallbacks only
- `exact_pair` is not expected at experiment-design time because no disposable `printer_head_id` exists yet

Recommended UI tooltip/detail fields:

- aggregation/source label
- adjusted confidence
- recommended pulse width if present
- recommended pressure / pressure band
- emergence time if present
- expected volume / CV if present
- contributing run count

### Prior availability should not be a parallel database

Do not use `FreeRTOS-interface/Presets/Reagents.json` for this feature.

Repo inspection shows that file exists but is not used by the current experiment design or calibration-memory path.

The canonical sources should be:

- `FreeRTOS-interface/CalibrationMemory/entities/reagents.json`
- `FreeRTOS-interface/CalibrationMemory/entities/printer_head_types.json`
- `CalibrationMemoryStore.get_best_prior(...)`

## Recommended UI Behavior

### Reagent selection

Recommended table design:

1. `Stock / Label`
2. `Reagent`
3. `Group`
4. `Head Type`
5. `Prior`
6. `Starting`
7. `Targets`
8. `Units`
9. `Set Stock Conc`
10. `Droplet Vol (nL)`
11. `Delete`

Reason:

- `Stock / Label` preserves current freeform reagent-name semantics and stock-id behavior
- `Reagent` becomes the registry-backed selector
- `Head Type` and `Prior` stay visible per row
- no new window is needed

Recommended widget behavior:

- `Stock / Label`
  - keep as `QLineEdit`
  - this remains the per-stock display label and current stock-id stem
- `Reagent`
  - editable `QComboBox`
  - dropdown populated from calibration-memory reagent registry
  - user may type a new value when the reagent is not yet known
- `Head Type`
  - `QComboBox`
  - populated from `printer_head_types.json`
  - allow blank `Unspecified` initially for backward compatibility
- `Prior`
  - read-only `QLabel` or non-editable table item
  - show `Strong prior`, `Some prior`, `No prior`, or `Head type not set`
  - add tooltip with provenance/details

### Existing reagent selection behavior

When a known reagent is chosen:

- store `OptionSpec.reagent_id`
- store `OptionSpec.reagent_display_name`
- keep `OptionSpec.name` unchanged unless the row still contains a default placeholder
- if `Stock / Label` is blank or still `reagent-N`, auto-fill it from the selected reagent display name

### New reagent behavior

When the user types a new reagent into the selector:

- derive a candidate `reagent_id` by normalization
- mark it as a new local selection in UI state
- persist the derived `reagent_id` and display text in `OptionSpec`
- on successful save/finish, upsert it into the reagent registry using the existing `CalibrationIdentityRegistry.upsert_reagent(...)`

Recommended registry-upsert timing:

- on `Save Design`
- on `Finish`

Do not upsert on every keystroke.

### Uploaded design behavior

For uploaded CSV designs, keep the imported stock/display label locked as today.

However:

- keep the new `Reagent` selector editable
- keep `Head Type` editable
- keep `Droplet Vol`, `Starting`, and `Set Stock Conc` editable as they are today

Reason:

- uploaded design columns still define the reaction matrix
- the user still needs to map imported reagent labels to known reagent identities and intended head types

### No-prior behavior

If no usable prior exists:

- show `No prior`
- add tooltip such as `No calibration-memory prior found for this reagent/head-type combination`
- do not block design completion
- runtime calibration later proceeds exactly as it does now

### Old experiments

If a loaded experiment has only the legacy freeform reagent string:

- populate `Stock / Label` from `OptionSpec.name`
- attempt alias-based registry resolution using `CalibrationIdentityRegistry.resolve_reagent(reagent_name=OptionSpec.name)`
- if matched, pre-populate the `Reagent` selector but do not require rewriting the file until the user saves
- leave `Head Type` blank if missing
- show `Head type not set` until the user chooses one

## Recommended Runtime Behavior

### Design -> runtime stock transfer

Recommended transfer point:

- `Model.load_reactions_from_model()`

For each stock row created from the experiment design:

1. create or retrieve the `StockSolution`
2. copy design reagent identity from the source `OptionSpec` into the `StockSolution`
3. copy intended `head_type_id` into the `StockSolution`

This ensures later calibration context building can recover explicit reagent identity from the runtime stock.

### Runtime head creation

Recommended transfer point:

- after `PrinterHeadManager.create_printer_heads(...)` inside `Model.assign_printer_heads()`

For each newly created runtime `PrinterHead`:

1. read `StockSolution.intended_head_type_id`
2. resolve head-type metadata from `CalibrationIdentityRegistry.get_head_type(...)`
3. generate a disposable `printer_head_id`
4. call `PrinterHead.set_identity_metadata(...)`

This keeps the design UI free of disposable-head concerns while making later calibration runs explicitly identified.

### Calibration startup later

No experiment-design-specific calibration changes are needed after the runtime stock/head identities are set.

The existing calibration path will automatically benefit because:

- `CalibrationContextBuilder.build()` already reads the current `StockSolution` and `PrinterHead`
- `CalibrationIdentityRegistry.resolve_reagent(...)` already honors explicit `StockSolution.reagent_id`
- `CalibrationIdentityRegistry.resolve_printer_head(...)` already honors explicit runtime `printer_head_id` and `head_type_id`

## Migration / Backward Compatibility

### Existing experiment files

Backwards compatibility plan for `experiment_design.json`:

- `OptionSpec` new fields must all be optional
- `ExperimentModel.from_dict()` must default missing fields to `None`
- `ExperimentModel.to_dict()` should only add the new keys when present or serialize them as `null`
- old files with only `name`, `targets`, `units`, `droplet_nL`, `starting_conc` must still load

### Missing head type

For old rows with no `intended_head_type_id`:

- show blank head-type selector
- show `Head type not set` in the prior column
- do not block load, optimize, save, or finish
- runtime falls back to current behavior if no head type was chosen

### Old runtime behavior

If the experiment has no explicit reagent/head-type metadata:

- runtime stock creation still works from `OptionSpec.name`
- disposable `printer_head_id` generation still happens
- `head_type_id` may remain unknown
- calibration-memory lookup later uses weaker or no identity, just as current fallback logic already allows

### Registry behavior

Do not migrate or rely on `FreeRTOS-interface/Presets/Reagents.json`.

The migration target is the calibration-memory registry:

- `CalibrationMemory/entities/reagents.json`
- `CalibrationMemory/entities/printer_head_types.json`

## Exact Files / Classes / Functions To Modify

### Primary files

#### `FreeRTOS-interface/View.py`

Modify:

- `MainWindow.open_experiment_designer` only if constructor dependencies change
- `ExperimentDesignDialog.__init__`
- `ExperimentDesignDialog._add_reagent_row`
- `ExperimentDesignDialog._delete_row`
- `ExperimentDesignDialog._load_factors_into_table`
- `ExperimentDesignDialog._rebuild_model_from_table`
- `ExperimentDesignDialog._apply_uploaded_design_mode_to_ui`
- `ExperimentDesignDialog._apply_default_edit_state`
- `ExperimentDesignDialog._apply_gripper_edit_lock_state`
- `ExperimentDesignDialog._refresh_all_lock_states`
- `ExperimentDesignDialog._on_save_design`
- `ExperimentDesignDialog._on_finish`

Add small new dialog helpers rather than pushing lookup logic into widget lambdas, for example:

- `_build_known_reagent_selector(...)`
- `_build_head_type_selector(...)`
- `_resolve_reagent_selection_from_row(...)`
- `_refresh_prior_availability_for_row(...)`
- `_refresh_all_prior_availability(...)`

#### `FreeRTOS-interface/Model.py`

Modify:

- `OptionSpec`
- `ExperimentModel.add_additive(...)`
- `ExperimentModel.add_choice_option(...)`
- `ExperimentModel.to_dict()`
- `ExperimentModel.from_dict()`
- `ExperimentModel.set_uploaded_design_from_dataframe(...)`
- `ExperimentModel.optimize_stock_solutions(...)`
  - specifically the stock-row materialization points that populate `_stock_rows_cache`
- `StockSolution.__init__`
- `StockSolution.set_reagent_identity(...)`
- `StockSolutionManager.add_stock_solution(...)` or the caller path that mutates created stocks
- `Model.load_reactions_from_model()`
- `Model.assign_printer_heads()`

Add top-level model helpers for:

- known reagent list
- known head-type list
- designer prior preview
- reagent-registry upsert on save/finish
- disposable `printer_head_id` generation

Recommended new helpers in `Model`:

- `list_known_reagent_identities()`
- `list_known_printer_head_types()`
- `resolve_design_reagent_identity(...)`
- `preview_experiment_design_prior(...)`
- `_apply_design_identity_to_stock_solution(...)`
- `_generate_disposable_printer_head_id(...)`
- `_apply_runtime_printer_head_identity(...)`

### Reuse existing modules; likely no schema change needed

#### `FreeRTOS-interface/CalibrationIdentity.py`

Reuse existing methods directly:

- `CalibrationIdentityRegistry.load_reagents()`
- `CalibrationIdentityRegistry.load_printer_head_types()`
- `CalibrationIdentityRegistry.resolve_reagent(...)`
- `CalibrationIdentityRegistry.get_head_type(...)`
- `CalibrationIdentityRegistry.upsert_reagent(...)`

Only modify this file if a small convenience helper is needed for UI list formatting or alias normalization.

#### `FreeRTOS-interface/CalibrationMemoryStore.py`

Reuse existing:

- `CalibrationMemoryStore.get_best_prior(...)`
- `CalibrationMemoryStore.identity_registry`

Only modify this file if a store-level wrapper is preferred over a top-level `Model` wrapper.

## Phased Implementation Plan

### Phase 1: Persisted design identity fields

1. Extend `OptionSpec` with optional `reagent_id`, `reagent_display_name`, and `intended_head_type_id`.
2. Update `to_dict()` / `from_dict()` for backward-compatible save/load.
3. Keep `OptionSpec.name` unchanged as the stock/display label.
4. Update uploaded-design parsing to leave new fields optional/blank.

### Phase 2: Experiment Design UI

1. Add the new `Reagent`, `Head Type`, and `Prior` columns to `ExperimentDesignDialog`.
2. Populate the selector widgets from `CalibrationIdentityRegistry`.
3. Keep the reagent selector editable for new reagent creation.
4. Recompute prior availability on row edits using debounced updates.
5. Update uploaded-design lock rules so:
   - stock/display label stays locked
   - reagent identity mapping stays editable
   - head type stays editable

### Phase 3: Runtime propagation

1. Carry design reagent/head-type metadata into stock rows.
2. Copy that metadata into `StockSolution` in `Model.load_reactions_from_model()`.
3. Generate disposable `printer_head_id` values when runtime heads are created.
4. Copy intended `head_type_id` into `PrinterHead`.

### Phase 4: Registry write-back and polish

1. Upsert newly authored reagents on successful save/finish.
2. Backfill selector choices from alias resolution when loading legacy experiments.
3. Add tooltips/detail strings for prior availability.
4. Add tests for legacy designs, uploaded designs, and runtime identity propagation.

## Recommended Tests

### Existing tests that will likely need updates

- `tests/test_experiment_designer_interlock.py`
  - reagent table column count and widget assumptions currently use `QTableWidget(1, 8)`
- `tests/test_experiment_design_plate_metadata_sync.py`
  - if dialog construction or stub setup changes

### New tests to add

- `tests/test_experiment_design_reagent_identity.py`
  - selector -> `OptionSpec` serialization
  - new reagent creation path
- `tests/test_experiment_design_head_type_selection.py`
  - per-row `intended_head_type_id` round-trip
- `tests/test_experiment_design_prior_availability.py`
  - strong/some/no prior rendering from existing store API
- `tests/test_experiment_design_legacy_load.py`
  - old experiment with only freeform string and no head type
- `tests/test_experiment_design_uploaded_identity_mapping.py`
  - uploaded design keeps stock/display name locked but allows reagent/head-type mapping
- `tests/test_runtime_disposable_printer_head_identity.py`
  - runtime stock -> printer head propagation and generated `printer_head_id`

## Risks / Open Questions

1. Should new reagent registry entries be written on `Save Design`, `Finish`, or only once the experiment is loaded into runtime? Recommendation: `Save Design` and `Finish` so future dialogs immediately see the reagent.
2. Should disposable `printer_head_id` values be persisted across app restarts? The current repo does not have durable rack/head-instance persistence, so the first implementation should treat them as runtime-session identifiers.
3. Should fill reagent also gain intended head-type support later? This plan leaves fill reagent unchanged.
4. If two rows intentionally share the same grouped `reagent_id` but different stock/display labels, the UI must make that distinction clear. Keeping `Stock / Label` separate from the registry-backed `Reagent` selector solves this.
5. Prior availability in the Experiment Design Window should remain informational. It should not be coupled to runtime prior-application mode (`off`, `advisory`, `seed_start`) beyond perhaps a tooltip note.

## Recommended Final Architecture

Use the Experiment Design Window as the place where the user chooses:

- stock/display label
- grouped reagent identity
- intended head type
- droplet volume

Use `OptionSpec` as the persisted row-level source of truth.

Use top-level `Model` as the bridge between:

- experiment design UI
- calibration-memory registry and prior lookup
- runtime stock/head identity assignment

Keep `ExperimentModel` focused on persisted design semantics and stock math.

Keep `PrinterHeadManager` focused on object creation and slot assignment.

Keep disposable `printer_head_id` creation entirely out of the design UI.

This is the smallest clean architecture that fits the current repo without inventing a new parallel source of truth or rewriting the calibration pipeline.
