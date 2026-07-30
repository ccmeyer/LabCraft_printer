# SIL Interactive Simulation Slice 0 Implementation Plan

Status: `proposed`

Parent plan:
`docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Date opened: 2026-07-28

## Purpose

Slice 0 freezes the architecture, compatibility contracts, and
production-artifact fidelity requirements for the interactive simulator and
composable SIL workflows before implementation begins.

This is a documentation, characterization, and retained-evidence slice. It
does not implement the launcher, `SimulationSession`, state recorder,
synthetic calibration provider, page drivers, actions, assertions, or
journeys.

The primary requirement is:

> Simulated hardware may provide external stimuli, but the application must
> create, update, validate, and reload the same experiment artifacts through
> the same application-owned paths used in normal operation.

The target application call path is:

`real Qt control -> MainWindow/Controller -> Model/ExperimentModel/CalibrationManager -> existing persistence and audit writers`

`SimulatedMachine`, simulator controls, and the future synthetic calibration
provider may supply only inputs or results that physical hardware would
otherwise supply. They must not replace the application call path above.

## Current-State Findings

The repository already has most of the production truth that the simulator
should reuse:

- `ApplicationComposition.simulation_dependencies(...)` constructs the real
  Model, Controller, and MainWindow with isolated config, experiment, and
  calibration-memory roots.
- `SimulatedMachine` tracks connection, motors, homing, position, pressure,
  regulation, gripper, queue, pause, command lifecycle, and simulated time.
- Experiment finalization already writes the design, initial execution plan,
  immutable revision, progress, exports, and audit history.
- Execution calibration already locks the plan, persists a calibration
  record, creates immutable plan revisions, recalculates targets, rewrites
  progress and exports, and synchronizes resume state.
- Authoritative activation already validates the saved bundle before creating
  or synchronizing `execution_resume.json`.
- Array execution already writes durable intents before simulated commands and
  reconciles callbacks into exactly-once progress.
- Calibration sessions already write `calibration.json`, experiment audit
  events, calibration-memory run data, and optional process recordings.

The main fidelity gap is in current workflow preparation:

`tools/virtual_workflows/scenarios.py::_create_prepared_fixture` directly
constructs a prepared design, plan, revision, and progress file. Current print
scenarios also use direct canned calibration and virtual rack staging. These
are useful compatibility tests, but they are not the production-like
full-lifecycle path requested for the new framework.

The editor lifecycle is closer to the target because it drives the real Qt
editor and application finalization path.

## Decisions Frozen By Slice 0

1. Pause hardening-plan Slice 4.7. Use disconnect as an early
   composed-journey proof after the shared session and harness exist instead of
   adding another branch to the current print runner.
2. Keep `FreeRTOS-interface/App.py` production-only. Interactive simulation
   uses a separate launcher and launcher-owned `SIMULATOR CONTROL` surface.
3. Keep the production connection widget disabled in simulation. The
   simulation control connects only to the literal `SIMULATED` sentinel and
   performs no port enumeration.
4. Use a fresh contained session root by default. Retention and reopening
   require an explicit keep option or selected retained path.
5. Use a fixed, instance-local seed for standard runs. Exploratory seed sets
   are versioned and every request/result is retained.
6. Preserve `labcraft.virtual_workflow_report` version 1 and the current
   report-set, baseline, and comparison identities during Milestones 1-5.
   New evidence is additive and nested. Report version 2 is reconsidered only
   during Milestone 6 harness extraction.
7. Make production-file fidelity a gate. The primary full lifecycle must
   start in the Experiment Editor and must not call
   `_create_prepared_fixture`, write authoritative JSON/CSV directly, mutate
   Model state as setup, or manufacture terminal state.
8. Do not synthesize camera frames or claim image-analysis or physical
   calibration coverage. Synthetic calibration may create normal
   application-owned metadata, analysis, verdict, memory, audit, and execution
   records through application APIs. Missing raw captures are explicit
   limitations.
9. Keep SIL reports, screenshots, state traces, generated-result envelopes,
   and harness diagnostics outside the experiment directory. The experiment
   directory contains only files owned by the normal application, including
   native calibration recording directories when that path is exercised.

## Production-Artifact Fidelity Contract

“Same files as normal use” means:

- the same application writer creates or mutates the artifact;
- the same lifecycle event controls when it appears;
- the same schema and cross-file identities are used;
- the same atomic, immutable, append-only, or conditional behavior applies;
- the same load, validation, lock, resume, and migration behavior applies.

It does not require identical generated UUIDs, wall-clock timestamps, source
commit, absolute roots, or platform path separators. Byte equality is required
only where the production application itself writes identical canonical
content, such as an immutable revision matching the plan snapshot persisted
for that revision.

### Required lifecycle matrix

| Checkpoint | Required application path | Required artifacts and invariants |
| --- | --- | --- |
| Session construction | `simulation_dependencies` plus normal `Model` construction with contained roots | Normal config and calibration-memory stores initialize beneath the session root. Record all config, schema, entity, index, and run files. Conditional files follow the same setting-dependent behavior as production. |
| New experiment | Experiment Editor/MainWindow handoff to `initialize_experiment` | The application writes `experiment_design.json`, seeded `progress.json`, `calibration.json`, and `experiment_audit.jsonl`. A real calibration-manager session opens; no test replaces its file afterward. |
| Finalization | `complete_experiment_design` to `load_experiment_from_model(..., finalize_execution_plan=True)` | The application writes `execution_plan.json`, `execution_plan_revisions/revision_000001.json`, populated `progress.json`, `key.csv`, and `concentration_key.csv`, and appends finalization/load audit events. Design hash, plan ID/revision, progress reference, and revision payload agree. |
| Virtual calibration generation | Application-owned result presentation and recording interface | `calibration.json` contains a real run, phase, and result envelope. With record mode active, the normal recorder owns `calibration_recordings/<process>/<run>/` and its metadata, event, analysis, and verdict files. Synthetic provenance is explicit. Raw image files are neither fabricated nor required. Calibration-memory changes use `CalibrationMemoryStore`. |
| Calibration application | Real result selection and Apply control to `apply_execution_calibration` | The application writes `execution_calibrations.json`, locks the plan, advances immutable revisions, recalculates targets, rewrites progress and both CSV exports, links the calibration record, updates printer-head settings, and appends audit events. |
| Stream readiness | Existing manual-refuel Controller/Model path | The application stores the outcome with matching head, stock, and applied-calibration fingerprint. Passed, failed, deferred, stale, and explicit bypass semantics remain unchanged. Normal printing requires a matching pass. |
| Runtime activation | `load_authoritative_execution_runtime` | The application validates the complete bundle before creating or synchronizing `execution_resume.json`, rewrites exports through normal code, and audits `authoritative_execution_activated`. |
| Array execution | Real Start/Stop/Resume controls and Controller callbacks | A pending intent is durable before each simulated dispense; command sequence is attached; callbacks update progress exactly once; intent is completed or compacted; pass and terminal plan revisions and audit events are normal application transitions. |
| Head exchange | Real rack/gripper and array controls with simulator-only physical stimulus | Normal preflight validates each head/stock/calibration association. All head passes reuse the same experiment directory and authoritative bundle. |
| Close/reload | Normal close, load, and authoritative activation paths | A new application session validates and reloads the unchanged bundle. Repair or migration artifacts appear only when the real loader decides they are required. |
| Prepared edit/refinalize | Existing prepared replacement and editor rename/copy behavior | Normal superseded-plan snapshots and renamed/copied experiment directories are preserved. Active designs remain locked after calibration or printing. |

### Artifact characterization record

At every checkpoint, Slice 0 records:

- relative path, file type, schema name/version where present, size, and
  SHA-256;
- the creating application method/event and preceding UI action;
- whether the file is immutable, append-only, atomically replaced, or
  conditional;
- plan ID/revision/state, design hash, calibration record key, progress
  reference, resume state, and audit event needed to prove consistency;
- normalized semantic content with only approved volatile values masked:
  timestamps, generated UUIDs, source identity, session root, and path
  separators.

The observed and reviewed characterization becomes the allowlist. A new
production-owned file is investigated and classified; it is not silently
ignored. An unexpected SIL-owned file inside the experiment directory fails
the fidelity check.

### Expected experiment-directory lifecycle

The exact set remains lifecycle- and setting-dependent, but the
characterization must account for:

- `experiment_design.json`;
- `progress.json`;
- `calibration.json`;
- `experiment_audit.jsonl`;
- `execution_plan.json`;
- `execution_plan_revisions/revision_*.json`;
- `execution_calibrations.json` after calibration;
- `execution_resume.json` after explicit authoritative activation;
- `key.csv`;
- `concentration_key.csv`;
- `calibration_recordings/` when the application recording path is active;
- uploaded design CSV materialization when that design mode is used;
- `superseded_prepared_execution_plans/` during prepared replacement;
- legacy migration manifest only when the real migration path is invoked.

Reports, screenshots, generic state events, generated calibration request/result
envelopes, stdout, tracebacks, stall stacks, and cleanup diagnostics are
session/report artifacts and must not appear in this directory.

## Interface Freeze

These are verification-tool interfaces. Slice 0 does not add production MVC
APIs.

### `SimulationSessionConfigV1`

Immutable fields:

- visibility and Qt ownership policy;
- session-root policy and optional retained experiment;
- seed and simulator timing;
- dialog policy and optional automation deadline;
- artifact retention policy;
- source identity and expected runtime mode.

Validation fails before application construction if the root is missing,
ambiguous, escapes containment, or overlaps production data.

### `SimulationSession`

Minimum operations:

- `create(config)`;
- `launch()`;
- `connect_simulator()`;
- `disconnect_simulator()`;
- `snapshot(reason)`;
- idempotent `close()`.

It owns QApplication policy, roots, dependencies, components, simulator,
provider, recorder, artifacts, and cleanup. It does not own experiment
business decisions.

### `StateRecorder`

Minimum operations:

- `start(session)`;
- `record_event(...)`;
- `capture_snapshot(reason)`;
- `flush()`;
- idempotent `close()`.

It subscribes to observable state and signals, correlates actions and simulator
commands, retains complete JSONL on disk, and keeps only bounded in-memory
projections.

### `SyntheticCalibrationProvider`

Pure operation:

`generate(CalibrationGenerationRequestV1) -> CalibrationGenerationResultV1`

It uses an instance-local random generator, validates finite bounds, returns a
stable fingerprint and provenance, and performs no UI, Model, Controller,
filesystem, process-global random, or authoritative-state mutation.

Presentation and application are separate actions that pass its result through
an application-owned calibration result surface and the existing Apply path.

### Drivers, actions, assertions, and journeys

Page drivers locate known controls, interact through QTest, read visible state,
and use shared waits. They do not make business decisions or mutate Model
objects.

Each `SemanticAction[TInput]` has:

- stable ID and one primary interaction surface;
- typed input and explicit precondition;
- one bounded operation and completion predicate;
- bounded evidence and failure stage;
- optional cleanup that never rolls back business state;
- `ActionResultV1` output.

Each assertion is a pure observation returning pass, fail, or incomplete with
bounded evidence. It cannot perform an action, repair state, or extend a
deadline.

`JourneyDefinitionV1` contains:

- journey, scenario, and workload identities;
- ordered actions and assertion checkpoints;
- timeout, dialog, and artifact policies;
- capabilities and explicit limitations.

Data variation uses typed builders and Python loops, not copied runner bodies
or an unrestricted JSON instruction language.

## Interaction-Surface Coverage Policy

Every action declares exactly one primary surface:

- `ui`: QTest or equivalent real Qt user interaction;
- `controller`: public Controller operation without Qt interaction;
- `model`: public Model operation without Controller/UI;
- `simulator`: virtual external stimulus or simulator control;
- `harness`: launch, wait, evidence, assertion, or cleanup only.

Observed downstream layers are recorded separately. A Controller or Model call
cannot be reported as UI coverage.

The reference full lifecycle uses `ui` for every operation available to a
normal operator. It uses `simulator` only for:

- virtual connection/disconnection;
- physical state stimuli unavailable without hardware;
- synthetic calibration generation;
- simulated manual-refuel/operator outcomes;
- explicit deterministic fault injection.

## Evidence Schema Freeze

Slice 0 approves these identities for later implementation:

- `labcraft.sil_simulation_session`, version 1:
  session/source identity, runtime mode, containment proof, relative roots,
  safety flags, simulator/provider configuration, application sessions,
  artifact map, terminal status, and cleanup status;
- `labcraft.sil_state_event`, version 1:
  increasing sequence, session/application IDs, monotonic timestamp, optional
  simulated time, source layer, event kind, action/command correlations, and
  bounded before/after/payload objects;
- `labcraft.sil_calibration_request`, version 1:
  seed, provider/profile versions, virtual run/head/stock/factor identities,
  requested mode, nominal volume/variation, and pressure/pulse-width bounds;
- `labcraft.sil_calibration_result`, version 1:
  request/result fingerprints, measured/effective volume, modes, pressure,
  pulse width, run/phase/timestamp, source-row fingerprint, seed/profile, and
  synthetic limitations;
- `labcraft.sil_action_result`, version 1:
  action ID/index/surface, status, bounded timing, correlation, evidence,
  failure stage/type/message, and cleanup;
- `labcraft.sil_assertion_result`, version 1:
  assertion ID, checkpoint, pass/fail/incomplete, bounded evidence, and related
  action/state sequences;
- `labcraft.sil_journey`, version 1:
  identities, ordered action declarations, assertion checkpoints, timeout,
  policies, capabilities, and limitations.

Evidence paths are relative to the session root unless a frozen report-v1 field
requires its current absolute form. Required fields cannot be removed or
reinterpreted without a schema-version change.

## Compatibility Anchors

The following remain public compatibility contracts through Milestone 5:

- CLI default `virtual_print_array_96_v1`;
- every currently registered scenario choice;
- current CLI flags, defaults, help behavior, and exit codes:
  success/warning `0`, functional failure `2`, incomplete/reporting failure
  `3`, accepted performance failure `4`;
- `VirtualPrintArrayScenarioConfig`;
- `run_virtual_print_array_scenario`;
- `EditorLifecycleScenarioConfig`;
- the three public editor lifecycle runner entry points;
- `ScenarioDefinition` and registry dispatch behavior;
- `labcraft.virtual_workflow_report` version 1;
- `labcraft.virtual_workflow_report_set` version 1;
- `labcraft.virtual_workflow_baseline` version 1;
- `labcraft.virtual_workflow_comparison` version 1;
- `virtual_workflow_policy_v1`;
- tracked Windows/Pi baseline population identities;
- capability-manifest identity, assertion IDs, artifact names, and Pi
  safety-evidence requirements.

Slice 0 does not change a scenario ID, fixture schema, report field meaning,
baseline, manifest claim, Pi script, or production API.

## Retained Reference Evidence

Create a fresh ignored reference directory associated with the exact source
commit and retain:

1. one passing `virtual_print_array_24_v1` report;
2. one passing `experiment_editor_create_finalize_v1` report;
3. one passing `print_array_multi_stock_24x2_v1` report;
4. one deterministic injected-stall failure report using
   `virtual_print_array_24_v1`.

The failure reference must include:

- failure screenshot;
- traceback;
- event trace;
- stall stack;
- failed action and failure stage;
- terminal diagnostics;
- cleanup evidence.

For each reference, record in this document during Slice 0 execution:

- report path and SHA-256;
- classification and schema identity;
- source commit and worktree state;
- fixture identity and hash;
- required artifact validation;
- experiment-tree characterization result;
- explicit limitations.

These reports are compatibility anchors, not accepted performance baselines.
Do not use `--accept-baseline` or replace a tracked baseline.

## Implementation Sequence

This sequence is intentionally limited to eight steps.

1. Record the nine decisions above as accepted in the parent decision log and
   cross-link the paused Slice 4.7 next action in the hardening plan.
2. Produce the artifact characterization from production call paths and
   existing integration tests; manually inspect one editor-created experiment
   and one completed/reloaded simulated experiment.
3. Freeze the interfaces, evidence schemas, interaction-surface policy,
   normalized comparison rules, and direct-authoritative-write prohibition.
4. Capture CLI/API/report/manifest/baseline compatibility anchors in focused
   tests and record exact node IDs; add a test only when an existing contract
   is not already executable and asserted.
5. Generate and validate the four fresh reference reports without accepting or
   replacing performance baselines.
6. Run focused contract, action, simulator, persistence, calibration, audit,
   lifecycle, comparison, and hardware-isolation checks, followed by the full
   Python suite.
7. Review experiment trees and reports for missing/extra files, invalid
   identities, hardware access, unexpected dialogs, unbounded artifacts, and
   incomplete cleanup; convert findings into explicit requirements for later
   milestones.
8. Mark Slice 0 complete only when all gates pass, then produce the concrete
   Milestone 1 plan without implementing calibration, composed journeys,
   disconnect injection, firmware, protocol, Pi operations, or hardware
   behavior.

## File Boundary

Expected Slice 0 changes:

- this document;
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md` for status,
  decisions, reference results, and cross-link;
- `docs/sil_verification_framework_hardening_plan.md` for the Slice 4.7
  disposition and cross-link;
- focused compatibility tests only if an existing anchor is not already
  asserted.

Excluded:

- production MVC code under `FreeRTOS-interface/`;
- simulator or virtual-workflow runtime behavior;
- fixtures and capability manifest;
- report schemas and accepted baselines;
- Pi scripts or remote runs;
- firmware and protocol;
- production or retained experiment data.

## Validation

Run with the repository environment. Allow at least 15 minutes for the full
suite.

Focused contracts:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_simulated_machine.py `
  tests\test_initial_execution_plan_integration.py `
  tests\test_execution_calibration_store.py `
  tests\test_experiment_audit_integration.py `
  tests\performance\test_virtual_workflow_comparison.py
```

Lifecycle:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_multi_stock_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py
```

Full regression:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Reference reports are run individually through
`tools/run_virtual_workflow.py` with fixed speed, timeout, Qt platform, and
output root. Record the exact successful commands and the intentional
non-zero failure command alongside their results. Do not run Pi operations in
this slice.

## Completion Gate

Slice 0 is complete only when:

- every decision is accepted and no dependency owner is unresolved;
- every observed experiment artifact has a documented normal writer and
  lifecycle;
- the primary future journey is prohibited from using prepared-fixture or
  direct authoritative-file shortcuts;
- application-produced files and cross-file identities pass the fidelity
  matrix at every checkpoint;
- all four reference reports validate against report-v1 and retain required
  evidence;
- focused, lifecycle, full-suite, and source/import hardware-isolation checks
  pass;
- every reference root is contained and no physical interface is invoked;
- raw camera and physical-behavior limitations are explicit;
- the final diff contains only reviewed documentation and any narrowly
  required compatibility-test additions.

## Risks And Rollback

The main risk is freezing an artifact list based only on the current shortcut
scenarios. Mitigate it by using both an editor-created experiment and a
completed/reloaded experiment, tracing the normal writers, and classifying
conditional artifacts.

The second risk is treating structural similarity as behavioral fidelity.
Mitigate it by recording the creating UI action/application call and by
validating cross-file plan, design, calibration, progress, resume, and audit
identities.

The third risk is overstating synthetic calibration coverage. Mitigate it by
retaining synthetic provenance, never fabricating camera captures, and keeping
camera, segmentation, physical ejection, pressure response, refuel behavior,
collision safety, firmware, and protocol claims out of scope.

Rollback is a documentation-only revert plus removal of ignored reference
evidence. It must never delete or rewrite production experiment data,
accepted baselines, tracked verification evidence, or release history.

