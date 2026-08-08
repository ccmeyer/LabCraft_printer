# SIL Interactive Simulation And Composable Workflows Plan

Status: `proposed`

Date opened: 2026-07-28

## Purpose

This plan defines the work required to turn the existing focused
software-in-the-loop (SIL) verification tooling into:

- a safe interactive application simulation that a developer can operate
  manually;
- a deterministic simulator state oracle with retained evidence;
- a synthetic droplet and stream calibration capability that exercises the
  application's real calibration-application path;
- a manually characterized full experiment lifecycle;
- a reusable typed action and assertion framework for composing broad UI
  journeys without adding a new monolithic runner for each variation;
- a maintainable SIL portfolio that combines broad happy-path coverage with
  independently runnable fault and lifecycle-boundary scenarios.

The immediate objective is not to automate every UI path. The objective is to
establish one complete virtual application environment, prove it manually,
and then make both developers and automated agents drive the same environment.

## Relationship To Existing SIL Work

This is a companion to
`docs/sil_verification_framework_hardening_plan.md`.

The existing hardening effort provides and must preserve:

- explicit hardware-isolated application construction;
- the deterministic in-process `SimulatedMachine`;
- real Qt event-loop, MainWindow, Controller, Model, persistence, and callback
  behavior;
- versioned smoke, regression, stress, and lifecycle fixtures;
- action ledgers, screenshots, event traces, stall stacks, metrics, reports,
  comparisons, and Pi safety evidence;
- a capability manifest and suite policy;
- independently runnable editor, pause/resume, reload/resume, and multi-stock
  lifecycle scenarios.

This plan addresses a different scaling problem:

- the production application has no persistent interactive simulation
  launcher;
- simulator state exists but is not exposed as one cross-layer session
  oracle;
- calibration imaging and calibration dispensing are intentionally
  unsupported by `SimulatedMachine`;
- print scenarios prepare and calibrate experiments through test-owned
  shortcuts instead of completing the entire user journey;
- action IDs are reusable evidence labels, but scenario execution is still
  concentrated in large runner-family functions;
- editor and print-array workflows cannot yet be joined naturally into one
  continuing experiment session;
- scenario-specific assertions and report construction still require
  substantial custom code.

The existing hardening plan remains authoritative for its current slices until
a reviewed decision explicitly changes its sequence. In particular, this
document does not silently cancel or implement Slice 4.7,
`print_array_disconnect_mid_array_24_v1`.

Before new implementation begins, choose and record one of these dispositions:

1. pause Slice 4.7 and implement Milestones 0-6 of this plan first;
2. complete Slice 4.7 as the final scenario on the current runner, then freeze
   new runner-family branching;
3. use Slice 4.7 as the first migrated composed journey after the new harness
   exists.

The recommended disposition is option 1 or 3. Adding more scenario-specific
branches before extracting the common harness increases migration work.

## Current Call Paths

### Production application

`App.py -> production_dependencies -> real Model -> real Machine_FreeRTOS -> real Controller -> real MainWindow -> physical interfaces`

This path must remain production-only and must never select simulation through
an implicit fallback.

### Existing in-process SIL construction

`test or tools/run_virtual_workflow.py -> simulation_dependencies -> real Model -> SimulatedMachine -> real Controller -> real MainWindow -> QTest/Controller actions -> authoritative files -> report`

### Existing print-array scenario preparation

`fixture loader -> test-owned authoritative prepared experiment -> application construction -> direct simulated connection/home -> direct canned execution calibration -> direct virtual rack staging -> real Qt Start/Stop/Resume controls -> real Controller completion callbacks -> authoritative progress -> validation/report`

### Existing editor lifecycle

`QTest -> real Experiment Editor -> real editor controls/modals -> Finish/Load/Copy -> MainWindow handoff -> real Model persistence/runtime activation -> authoritative validation -> report`

### Target interactive simulation

`dedicated simulation launcher -> SimulationSession -> simulation_dependencies -> real MainWindow/Controller/Model -> SimulatedMachine -> developer-operated UI plus simulator controls -> StateRecorder -> retained session evidence`

### Target synthetic calibration

`SyntheticCalibrationProvider -> application-owned calibration result surface -> real calibration selection/Apply control -> Model calibration revision -> plan target recalculation -> authoritative calibration/plan/progress files -> reload validation`

### Target composed automation

`typed JourneyDefinition -> shared SIL harness -> page drivers and semantic actions -> real Qt controls/Controller/simulator interfaces -> StateRecorder and assertion ledger -> generic report/artifacts`

## Desired End State

A developer can launch a visible simulation session and manually complete:

1. simulator connection;
2. motor enable and homing;
3. experiment design and finalization;
4. virtual printer-head loading;
5. deterministic virtual calibration;
6. calibration selection and application;
7. stream manual-refuel-check completion when required;
8. pressure regulation;
9. array printing;
10. head drop-off and the next head pass;
11. terminal completion;
12. application close and authoritative reload.

The same session construction, state oracle, calibration provider, and
application interfaces are then driven by automated actions. Scenario
definitions describe meaningful differences in journey and assertions rather
than recreating setup, instrumentation, reporting, and teardown.

## Design Principles

### Keep production and simulation entry points separate

Production startup remains `FreeRTOS-interface/App.py` with
`production_dependencies()`.

Interactive simulation uses a separate, explicitly named launcher. It must
construct `simulation_dependencies()` directly and fail closed. A typo,
missing option, invalid factory, or construction error must never fall back to
production dependencies.

### Share one simulation session between humans and automation

Manual evaluation and automated SIL must not build parallel virtual
applications with different behavior. Both use the same `SimulationSession`
factory, state recorder, calibration provider, root isolation, and cleanup
contract.

### Preserve application truth

Simulation tools may provide virtual external stimuli and deterministic
results. They must not:

- duplicate Controller or Model business decisions;
- directly edit active authoritative files to make a check pass;
- force widget state without following the associated application operation;
- skip lifecycle locks or execution preflights;
- manufacture a terminal state independently of real callbacks;
- weaken durable persistence or recovery behavior.

### Prefer semantic actions over unrestricted instruction data

Use typed Python functions or objects with validated inputs. Do not introduce
an unrestricted JSON UI instruction interpreter.

JSON may hold:

- versioned experiment and workload data;
- simulator timing/fault configuration;
- deterministic calibration profile inputs;
- capability metadata;
- retained evidence.

Python owns operations, waits, preconditions, and assertions.

### Separate virtual stimulus from physical claims

Synthetic calibration proves that the application can display, select, apply,
persist, reload, and use a calibration result. It does not prove:

- camera capture;
- image segmentation or volume measurement accuracy;
- physical droplet or stream formation;
- pressure response;
- refuel behavior;
- collision safety;
- firmware or serial protocol behavior.

Every report and capability claim must preserve this boundary.

### Determinism first, exploration second

Standard and pull-request lanes use fixed inputs and fixed seeds. Scheduled
exploratory lanes may use multiple seeds, but each seed and generated result
must be retained so the run is exactly reproducible.

### Keep scenarios independent at meaningful failure boundaries

Broad happy-path journeys reduce duplicated setup and expand UI coverage.
Focused scenarios remain separate when they inject faults, prove a lifecycle
boundary, require a distinct starting state, or would be hidden by an earlier
failure in one large journey.

### Make interaction surfaces explicit

Each action declares its driving surface:

- `ui`;
- `controller`;
- `model`;
- `simulator`;
- `harness`.

Coverage output must distinguish, for example, Controller-level homing
coverage from Qt Home-button coverage.

## Scope

### In scope

- a dedicated interactive simulation launcher;
- a reusable simulation-session owner;
- fresh and optionally retained isolated session roots;
- an explicit simulation-only connection operation;
- a cross-layer state recorder and optional inspector;
- deterministic synthetic droplet and stream calibration results;
- real calibration selection and application behavior;
- simulated manual-refuel-check outcomes for stream workflow coverage;
- manual characterization of complete virtual experiment lifecycles;
- shared page drivers, actions, assertions, waits, evidence, and teardown;
- joining editor and print execution in one application session;
- migration of existing scenario families to composed journeys;
- fixture/builders that vary data without multiplying near-identical schemas;
- capability, suite, report, freshness, and scheduling integration;
- focused tests and documentation for all new verification tooling.

### Out of scope

- changes to firmware or the serial protocol;
- protocol-level virtual MCU emulation;
- physical motion, pressure, camera, balance, GPIO, or droplet physics;
- validation of calibration accuracy;
- replacing HIL or physical calibration tests;
- weakening any hardware interlock or production safety behavior;
- enabling physical port discovery in simulation;
- making the production launcher accept an ambiguous simulation fallback;
- performance remediation discovered by a stress run;
- a general-purpose UI macro language;
- automatically treating random-seed coverage as an acceptance baseline;
- refill-required/resume SIL qualification while authoritative volume tracking
  is not enabled; `execution.refill_resume` remains deferred until volume
  tracking is enabled and observable through the application state;
- using simulation success to claim physical printer readiness.

## Non-Negotiable Safety Invariants

Every interactive or automated simulation session must:

- construct only explicit simulation dependencies;
- expose the persistent simulation identity banner;
- set `hardware_access_allowed` to false in retained evidence;
- reject serial, camera, balance, GPIO, MCU reset, firmware update, and
  application-update access;
- connect only to the literal `SIMULATED` sentinel;
- avoid port enumeration;
- keep configuration, experiment, calibration-memory, logs, and artifacts
  beneath the session root;
- prove root containment before application construction;
- use a visibly distinct simulator control surface;
- retain unexpected dialogs and errors as failures;
- use bounded timers, event histories, traces, and screenshots;
- restore observers, filters, wrappers, redirects, and timers;
- disconnect and close components during teardown;
- fail if a production factory or physical interface is imported or invoked
  by the simulation construction path.

## Target Architecture

### SimulationSession

`SimulationSession` is the single owner of one interactive or automated run.
It should hold:

- immutable session identity and configuration;
- isolated roots;
- `QApplication` ownership policy;
- application dependencies and components;
- simulator configuration and seed;
- synthetic calibration provider;
- state recorder;
- dialog policy;
- lifecycle deadline when automation is active;
- artifact locations;
- cleanup state.

It should support:

- visible interactive operation;
- offscreen automated operation;
- a fresh session by default;
- optional retained sessions;
- optional reopening of an explicitly selected retained experiment;
- one idempotent close operation;
- no global mutable simulator singleton.

### Simulator control surface

The preferred initial design is a launcher-owned simulator control window or
dock rather than re-enabling the production connection widget.

It may expose:

- Connect Simulator;
- Disconnect Simulator;
- speed multiplier;
- configured seed;
- generate virtual calibration;
- record virtual manual-refuel outcome;
- inject an allowlisted deterministic fault;
- show current simulator state;
- open the session artifact directory;
- export a state snapshot.

This control surface must be clearly labeled `SIMULATOR CONTROL` and must
exist only in simulation mode.

The production connection widget remains disabled in simulation unless a
separately reviewed UI change proves that it cannot enumerate or connect to
physical ports. Consequently, initial connection coverage is classified as a
simulation-control action rather than coverage of the production connection
widget.

### StateRecorder

The recorder combines state from:

| Layer | Minimum state |
| --- | --- |
| Session | session ID, seed, roots, versions, timing policy |
| Simulator | connection, motors, home state, positions, pressure, regulation, gripper, queue, pause, simulated time |
| Controller | array state, pass state, errors, disconnect/fault state |
| Rack/head | slot confirmation, loaded head, stock/head identity, settings |
| Experiment | design state, plan ID/revision/state, eligibility, progress, active runtime |
| Calibration | selected/applied record, effective volume, mode, pressure, pulse width |
| Refuel check | required/passed/deferred/bypassed/stale state |
| UI | visible workflow guidance, enabled primary controls, modal identity |
| Persistence | authoritative file identities, revisions, intent/checkpoint state |

Events should include:

- monotonically increasing event sequence;
- wall-clock monotonic timestamp;
- simulated timestamp where applicable;
- application session ID;
- event kind and source layer;
- action or command correlation ID;
- bounded before/after fields;
- seed and configuration identity where generation is involved.

The primary retained form is JSONL. A visible inspector is a projection of
the same recorder and must not maintain independent state.

### SyntheticCalibrationProvider

The provider accepts a validated request containing:

- seed;
- named generation profile;
- printer-head identity;
- stock identity;
- factor/option/fill identity;
- requested printing mode;
- nominal ejection volume and variation;
- allowed pressure and pulse-width configuration;
- virtual run identity.

It returns a result compatible with the existing calibration-application
path, including:

- measured and effective volume;
- original and applied printing modes;
- pulse width;
- pressure;
- run ID and phase;
- stable virtual timestamp;
- source-row fingerprint;
- provider version, profile, and seed.

Initial profiles:

- `nominal_droplet`;
- `nominal_stream`;
- `droplet_to_stream`;
- `low_volume_boundary`;
- `high_volume_boundary`;
- `invalid_outlier`;
- `missing_measurement`.

The first two profiles are required for the full lifecycle. Boundary and
invalid profiles support later focused negative scenarios.

The provider must use a local seeded pseudo-random generator. It must not
modify process-global random state. Generated numeric values must be finite,
bounded, recorded, and reproducible.

### Calibration presentation and application

The provider should inject a result through an application-owned calibration
result interface so the real calibration UI can:

1. display the result;
2. select the result;
3. preview the ejection-volume and mode effect;
4. ask for any required confirmation;
5. apply through the existing Model operation;
6. update printer-head mode and machine print settings;
7. persist the calibration and plan revision;
8. update task guidance and print preflight.

If no safe existing result-injection interface is available, record that gap
and implement the smallest simulation-only adapter. Do not write a synthetic
summary directly into active authoritative execution files.

### Stream manual-refuel simulation

Applying a stream calibration correctly makes a passed manual refuel check a
print precondition. The simulator must not silently bypass that requirement.

The simulation control surface may generate one of:

- `passed`;
- `deferred`;
- `failed`;
- `bypassed`, only in an explicit negative/bypass scenario.

The outcome must be recorded through the existing Controller/Model path with:

- the active printer-head and stock identity;
- applied-calibration fingerprint;
- virtual trial count and droplet count;
- pressure/settings snapshot;
- operator judgment marked as simulated;
- provider version and seed;
- source `sil_simulated_manual_refuel_check`.

The normal full lifecycle requires `passed`.

### Page drivers

Page drivers contain Qt mechanics, not business policy. Initial drivers:

- `MainWindowDriver`;
- `ExperimentEditorDriver`;
- `MachineControlsDriver`;
- `RackDriver`;
- `CalibrationDialogDriver`;
- `ArrayDriver`;
- `ExperimentLoaderDriver`.

Drivers may:

- find known controls;
- click, type, select, and close through QTest;
- read visible labels and control state;
- identify active dialogs;
- wait for observable UI conditions.

Drivers must not:

- decide target dispense counts;
- synthesize plan state;
- mutate Model objects directly;
- edit authoritative files;
- suppress unexpected dialogs;
- extend the scenario deadline.

### Semantic actions

Initial semantic actions:

- launch application;
- connect/disconnect simulator;
- enable motors;
- home machine;
- create experiment;
- finalize experiment;
- reopen/edit/refinalize experiment;
- load/drop off virtual head;
- generate virtual calibration;
- select/apply calibration;
- record virtual manual-refuel outcome;
- enable/disable pressure regulation;
- start/soft-stop/resume print array;
- wait for stock pass;
- reload authoritative experiment;
- inject simulator disconnect/fault;
- capture milestone;
- validate checkpoint or terminal bundle;
- close session.

Each action has:

- stable ID;
- typed input;
- interaction-surface classification;
- explicit preconditions;
- one bounded operation;
- predicate/signal-based completion;
- bounded evidence;
- failure stage;
- optional compensating cleanup, never business-state rollback.

### Assertions

Assertions consume observable application or retained state. They do not
perform actions.

Initial assertion families:

- simulation identity and hardware isolation;
- application/UI construction;
- machine readiness;
- rack/head association;
- calibration identity and mode;
- calibration application and plan revision;
- manual-refuel readiness;
- stock-pass completion;
- exactly-once well progress;
- queue and intent durability;
- editability/lock boundary;
- pause/disconnect/reload boundary;
- terminal authoritative bundle;
- artifact presence;
- cleanup completeness.

### Journey definitions

A journey combines:

- scenario identity;
- workload/fixture identity;
- ordered semantic actions;
- required checkpoint assertions;
- required terminal assertions;
- dialog policy;
- timeout;
- artifact policy;
- capability mapping;
- limitations.

Journey code should remain short enough to review as a user lifecycle.
Loops over stocks or heads are typed Python composition, not expanded copies
of the same orchestration.

## Milestone Roadmap

### Milestone 0: Architecture and contract freeze

Status: `planned`

Goal:

- agree on component boundaries before implementation;
- characterize current behavior and freeze compatibility anchors.

Deliverables:

- reviewed disposition for existing Slice 4.7;
- finalized `SimulationSession`, recorder, calibration-provider, driver,
  action, assertion, and journey interfaces;
- versioned session and state-event schema proposals;
- interaction-surface coverage policy;
- retained reference reports for existing 24, editor create/finalize,
  multi-stock, and selected failure paths;
- explicit list of existing public report and CLI compatibility contracts;
- recorded baseline test commands and results.

Likely files:

- this document;
- a small architecture-decision record if required;
- no production MVC, simulator, or workflow implementation.

Gate:

- current relevant tests pass;
- reference reports validate;
- hardware-isolation source/import guards pass;
- no implementation begins with unresolved production/simulation dependency
  ownership.

Rollback:

- documentation-only revert.

### Milestone 1: Interactive SimulationSession and launcher

Status: `complete`

Goal:

- launch and manually operate the real application in a retained,
  hardware-isolated simulation session.

Deliverables:

- dedicated interactive simulation launcher;
- reusable `SimulationSession`;
- fresh/retained session-root policy;
- explicit session configuration with seed and timing;
- launcher-owned simulator connection/disconnection control;
- persistent simulation identity;
- clean and idempotent teardown;
- exact launch and troubleshooting documentation.

Likely files:

- `tools/run_simulated_app.py`;
- new modules beneath `tools/virtual_workflows/` or a dedicated
  `tools/sil/` package;
- focused launcher/session tests;
- `README.md`;
- this document.

Gate:

- visible application launches from a fresh root;
- only `SIMULATED` can connect;
- developer can connect, enable/home, regulate, move, operate the gripper,
  disconnect, and close;
- all roots remain contained;
- no physical factory or device code is invoked;
- teardown leaves no simulator timers or Qt resources active.

Implementation status:

- the dedicated launcher, reusable session, simulator control, retained-root
  lifecycle, Controller sentinel seam, documentation, and automated tests are
  implemented;
- the clean automated regression completed with 3,675 passed and 38 skipped
  tests on 2026-07-28;
- the fresh/retained visible Windows exercise completed on 2026-07-30;
- the Slice 0.1 repetition gate completed on 2026-07-31 with five clean
  24-well smoke runs, three clean two-stock runs, and three clean
  reload/resume runs; and
- the authoritative completion evidence is recorded in
  `docs/sil_interactive_simulation_milestone_1_completion_record.md`.

Rollback:

- remove the standalone launcher/session modules and documentation; existing
  automated SIL remains unchanged.

### Milestone 2: Cross-layer state recorder and inspector

Status: `complete`

Concrete implementation plan:
`docs/sil_interactive_simulation_milestone_2_implementation_plan.md`

Completion record:
`docs/sil_interactive_simulation_milestone_2_completion_record.md`

Goal:

- make the interactive application state inspectable, correlated, bounded,
  and machine-readable.

Deliverables:

- session state snapshot;
- JSONL state/event recorder;
- action/command correlation;
- bounded retention and flush behavior;
- optional visible inspector backed only by recorder state;
- terminal and cleanup snapshots;
- schema and focused tests.

Likely files:

- new state-recorder/inspector modules;
- simulator/session integration;
- focused tests;
- report-schema documentation if existing report fields are extended;
- `README.md`;
- this document.

Gate:

- deterministic connection, homing, regulation, gripper, queue, and
  disconnect transitions appear in order;
- Controller, Model, experiment, and simulator snapshots reconcile;
- traces remain bounded in memory while complete retained JSONL is available;
- observer installation and removal are idempotent;
- a recorder failure cannot enable hardware or corrupt application state.

Rollback:

- detach the optional recorder/inspector; the interactive session continues
  without changing application behavior.

### Milestone 3: Deterministic synthetic calibration engine

Status: `complete`

Goal:

- create valid, reproducible droplet and stream calibration results without
  simulating cameras or physical ejection.

Deliverables:

- typed generation request and result;
- versioned named profiles;
- local seeded random generator;
- stable result fingerprint;
- positive, boundary, and invalid profile tests;
- result validation against existing calibration contracts;
- explicit limitations in evidence.

Likely files:

- new synthetic-calibration module;
- fixtures/profile definitions if needed;
- focused unit/contract tests;
- calibration report-schema documentation;
- this document.

Gate:

- identical inputs and seed produce byte-equivalent normalized results;
- different seeds remain bounded and retain their inputs;
- nominal droplet and stream results pass existing application validation;
- invalid results fail before application;
- no global random state, camera, balance, serial, or authoritative file is
  touched.

Rollback:

- remove the provider and its tests with no application-data migration.

### Milestone 4A: Droplet calibration UI application

Status: `complete`

Goal:

- show, select, and apply a synthetic droplet result through the real
  calibration UI.

Deliverables:

- safe application-owned result injection;
- calibration-dialog page driver;
- developer control to generate a result;
- visible summary/selection;
- real Apply operation;
- settings, plan-revision, task-guidance, persistence, and reload evidence;
- negative tests for missing or mismatched identities.

Likely files:

- simulation/session calibration adapter;
- calibration UI only if an existing result surface cannot be reused;
- page driver/actions;
- focused calibration UI and persistence tests;
- documentation.

Gate:

- selected synthetic result is visible and distinguishable as simulated;
- Apply follows the existing Model path;
- head identity, pressure, pulse width, effective volume, target counts,
  plan revision, progress, and calibration files reconcile;
- close/reload produces the same applied state;
- no active or progressed stock may change calibration contrary to existing
  locks.

Rollback:

- remove the simulation-only adapter/control and retain the core provider.
  Existing physical calibration behavior remains unchanged.

### Milestone 4B: Stream mode and manual-refuel workflow

Status: `complete`

Goal:

- exercise a droplet-to-stream calibration switch and the required stream
  manual-refuel lifecycle.

Deliverables:

- nominal stream and mode-switch result presentation;
- real mode-switch confirmation;
- applied stream plan revision;
- simulated manual-refuel outcomes through existing application APIs;
- preflight and task-guidance evidence;
- close/reload validation;
- focused stale/deferred/failed checks.

Likely files:

- simulation control/provider integration;
- calibration and refuel page drivers/actions;
- focused Model/Controller/UI/SIL tests;
- documentation.

Gate:

- stream Apply marks the refuel check required;
- printing remains blocked for required, deferred, failed, or stale evidence;
- a matching simulated passed check clears only the intended preflight;
- changing the applied calibration makes the previous check stale;
- printing-mode, settings, calibration fingerprint, and plan revision survive
  reload;
- no bypass is used by the normal happy path.

Rollback:

- remove simulated refuel outcomes and stream journey support while retaining
  droplet calibration UI coverage.

### Milestone 4C: Normal UI path convergence

Status: `complete`

Completion record:
`docs/sil_interactive_simulation_milestone_4c_completion_record.md`

The consolidated focused gate passed with 259 tests on 2026-08-05. Normal-UI
visible evidence covers all four calibration profile mappings, and the final
fresh/reload root reconciles the corrected 9 nL Droplet to 40 nL Stream
transition, immediate in-dialog manual-refuel trial dispatch, Passed outcome,
history reconstruction, plan revision, and clean teardown.

Goal:

- exercise simulation workflows through the application's normal connection,
  calibration, and manual-refuel surfaces.

Deliverables:

- normal Connect/Disconnect bound to the exact `SIMULATED` sentinel;
- full-layout camera-free calibration dialog launched by the normal button;
- Droplet and Stream Calibrate All profile selection, including
  stream-to-droplet transition;
- additive schema-v2 directional droplet-to-stream generation from any valid
  source below 40 nL, including the normal 9 nL default, with v1 fingerprints
  preserved;
- real manual-refuel command window with simulated outcome persistence;
- diagnostics-only Simulator Control dock;
- focused production-path, isolation, persistence, and reload coverage.

Gate:

- no dock workflow button is required for the normal journey;
- physical connection, camera, optics, capture, balance, and calibration
  handlers remain unreachable in simulation;
- real preview, confirmation, Apply, command, preflight, and persistence paths
  remain authoritative;
- passed, failed, unclear, and deferred refuel states retain exact trial and
  provenance evidence;
- forward and reverse printing-mode transitions survive retained-root reload.

Rollback:

- remove the post-construction UI bindings, full-dialog simulation mode,
  reverse profile, extended refuel bridge, and 4C tests while retaining
  Milestones 1–4B.

### Milestone 4D: Pulse-aware synthetic ejection response

Status: `complete`

Goal:

- make new synthetic calibration volume causally depend on the exact settled
  simulation pulse width before beginning full-lifecycle characterization.

Deliverables:

- schema-v3 pulse-aware requests/results with v1/v2 compatibility;
- deterministic droplet 1300–1800 us / 9–18 nL response;
- deterministic stream 2500–10000 us / 60–250 nL response;
- simulation-only settings preflight with configured profile selection;
- Controller/SimMachine settings convergence before generation;
- read-only historical pre-v3 synthetic application evidence.
- fingerprint-deduplicated pending, generated-unapplied, and applied synthetic
  history reconstructed from canonical artifact pairs and authoritative
  execution-calibration records.

Gate:

- unsupported pulse widths cannot create candidates or artifacts;
- valid current settings are preserved;
- selected profiles complete through the normal command path before generation;
- real preview, Apply, persistence, refuel, and retained-root reload reconcile;
- physical calibration preflight remains unchanged.
- generating a different profile retains earlier unapplied evidence, and
  applying a retained schema-v3 row promotes it without duplication.

Rollback:

- remove v3 response/contracts and the simulation pulse-preflight bridge while
  retaining Milestones 1–4C and all v1/v2 evidence.

### Milestone 5: Manual full-lifecycle characterization

Status: `complete`

Goal:

- prove the complete virtual workflow manually before automating it.

Required manual journeys:

1. one-stock droplet experiment;
2. two-stock droplet experiment;
3. mixed droplet/stream experiment;
4. close/reload of prepared, active/paused where supported, and completed
   experiments.

Manual happy-path checklist:

1. launch a fresh visible session;
2. connect the simulator;
3. enable and home motors;
4. create and finalize a bounded experiment;
5. load the first head through the real rack UI where supported;
6. generate, select, and apply virtual calibration;
7. complete the virtual manual-refuel check for stream mode;
8. enable pressure regulation;
9. start the array through the real UI;
10. observe exact stock-pass completion;
11. drop off the head;
12. repeat for every remaining stock;
13. reach terminal completion;
14. close cleanly;
15. reopen and validate the authoritative experiment.

Deliverables:

- retained state trace;
- screenshots at every lifecycle boundary;
- authoritative file inventory and validation;
- list of missing simulation capabilities or application defects;
- classification of each gap as framework, simulator, production seam,
  deferred physical behavior, or defect;
- go/no-go decision for automation extraction.

Gate:

- all three happy-path experiments complete;
- state, UI guidance, task list, plan, progress, calibration, refuel, queue,
  and persistence agree;
- reload does not rely on in-memory success;
- every workaround is explicit; no hidden fixture mutation is permitted;
- unresolved production defects receive separate scoped plans.

Rollback:

- no implementation rollback; retained manual evidence may be discarded from
  generated output while documentation records the result.

### Milestone 6: Shared harness, page drivers, actions, and assertions

Status: `complete`

Goal:

- make new journeys concise compositions over the manually proven session.

Deliverables:

- shared harness for session setup, evidence, report, failure retention, and
  teardown;
- initial page drivers;
- typed semantic action library;
- reusable assertion library;
- generic action/assertion ledgers;
- generic capability-result join;
- compatibility adapter for existing report-v1 consumers;
- unit tests for drivers/actions/assertions;
- migration of the 24-well smoke as the first proof.

Likely files:

- new harness/driver/assertion modules;
- `tools/virtual_workflows/actions.py` refactoring;
- `tools/virtual_workflows/report.py` integration;
- registry/manifest integration;
- focused tests and documentation.

Gate:

- migrated smoke follows the same real application path and passes all
  existing required assertions;
- action order and interaction surfaces are visible;
- unexpected dialogs and incomplete assertions fail closed;
- report compatibility tests pass;
- scenario setup/report/teardown are no longer duplicated;
- the scenario definition is a short reviewable lifecycle;
- full affected regression passes.

Rollback:

- restore the compatibility adapter to the existing runner while retaining
  independently useful interactive simulation and calibration capabilities.

### Milestone 7: Journey portfolio and legacy-runner migration

Status: `complete - Slices 1 through 9 and final validation complete`

Goal:

- expand broad UI coverage through composition and retire duplicated
  runner-family branches only after parity.

Initial broad journeys:

- complete one-stock droplet lifecycle;
- complete two-stock lifecycle;
- complete mixed droplet/stream lifecycle;
- create/finalize/reopen/edit/refinalize;
- droplet-to-stream recalibration before progress;
- close/reload/resume and terminal reload.

Focused independent scenarios:

- soft stop/resume;
- disconnect fail-closed;
- authoritative reload/resume;
- post-start edit lock/editable copy;
- invalid/mismatched calibration;
- required/deferred/failed/stale manual-refuel checks;
- deterministic simulator fault injection;
- stress and responsiveness workloads.

Migration order:

1. 24-well smoke;
2. editor create/finalize — complete in Slice 1;
3. multi-stock 24x2 — complete in Slice 2;
4. prepared edit/refinalize — complete in Slice 3;
5. soft stop/resume - complete in Slice 4; code-growth variance explicitly accepted;
6. authoritative reload/resume - complete in Slice 5;
7. post-start lock/copy - complete in Slice 6;
8. 96-well regression - complete in Slice 7;
9. 384x10 stress - Slice 8, its bounded ACTIVE-plan cache amendment, diagnostic
   decomposition, and guarded calibration-revision append are implemented.
   The final composed and direct nodes complete all 3,840 pairs; the unchanged
   responsiveness gate passes. A focused real-session rack-only regression
   identified Qt's post-open mouse-release guard; the reusable mouse driver now
   waits out that bounded guard. Visible and exact-replay runs both complete
   all 3,840 pairs with every required assertion passing and zero starvation;
10. disconnect scenario according to the Milestone 0 decision - complete in
    Slice 9. The composed journey disconnects through the normal Qt connection
    button at six durable completions, retires two look-ahead intents only
    after canonical simulator cancellation is confirmed, and proves a
    quiescent `ready_to_resume` boundary.

Gate per migration:

- old and new required assertions are equivalent or the difference is
  explicitly reviewed;
- retained success and failure evidence remains inspectable;
- relevant comparison/Pi contracts remain compatible;
- old code is removed only after parity and a full affected regression;
- capability coverage never remains `covered` without an active passing
  scenario.

Rollback:

- revert one migrated scenario to its compatibility adapter; do not revert
  unrelated journeys or simulator capabilities.

### Milestone 8: Manual suites, exploration, and operational handoff

Status: `complete` (2026-08-07; all eight slices and final validation complete)

Goal:

- make the composed portfolio easy to select and run on demand, add compact
  parameter and sequence exploration, and make coverage/source freshness
  visible without enabling unattended test scheduling.

Approved operating decisions:

- runs remain operator-initiated after relevant changes; Milestone 8 will not
  add GitHub Actions, Windows Task Scheduler, or another unattended scheduler;
- the mixed droplet/stream calibration and execution workflow becomes a
  registered composed lifecycle scenario because it represents normal user
  behavior;
- the first parameter matrix uses approximately eight curated pairwise cases
  instead of the full Cartesian product;
- the initial tracked exploration seed set is `1, 7, 19, 42, 101`;
- the first sequence campaign is capped at five seeds, one legal and one
  intentionally illegal sequence per seed, and 25 semantic actions per
  sequence;
- generated evidence remains beneath the existing ignored
  `verification_reports/` root; no automatic deletion is authorized.

Target suites:

| Suite | Purpose | Initial policy |
| --- | --- | --- |
| Standard | One deterministic complete smoke journey | Manually after shared UI, Controller, Model, simulator, or SIL-infrastructure changes |
| Lifecycle | Bounded editor/execution/calibration journeys | Manually after lifecycle, persistence, recovery, calibration, or execution-state changes |
| Matrix/exploration | Curated cases and bounded seeded sequences | Manually after changing the exercised actions, guards, values, modes, or ordering |
| Regression | Existing representative 96-well path | Manually before integrating substantial execution changes |
| Stress | Existing 384x10 path | Manually after persistence, rack, responsiveness, or scalability changes and before important releases |
| Pi primary | Representative safe SIL path | Manually after Pi-specific changes or before a release |
| Pi stress | Sustained target characterization | Explicit Pi characterization or pre-release only |

Manual selection is distinct from UI automation: the runner may automate a
journey after the operator launches it, but no service will decide when to
launch a run. Existing manifest schedule rows will be revised to express
manual triggers rather than calendar automation. Evidence age remains
informational; primary freshness is the evidence's source/worktree identity
and satisfaction of its required assertions.

Artifact layout:

```text
verification_reports/
  virtual_workflows/<scenario>/<run>/
  suites/<suite>/<run>/
  matrices/<matrix>/<run>/
  exploration/<campaign>/<run>/
```

Scenario reports remain authoritative. Suite, matrix, and exploration reports
reference and hash child reports rather than copying their complete artifact
trees. Failures, visible qualifications, and exact replays are retained until
manually reviewed. Any future cleanup command must be separately approved,
restricted to a validated `verification_reports/` subtree, dry-run by default,
and incapable of deleting tracked baselines.

Deliverables:

- manual suite/capability CLI selection, listing, and dry-run planning;
- optional changed-source recommendations that never start a run by
  themselves;
- a registered mixed droplet/stream lifecycle scenario;
- isolated host suite execution and aggregate reports;
- fixed standard seed;
- typed parameter cases and a recorded seed-set/sequence policy;
- rerun command emitted for every exploratory failure;
- assertion-backed coverage/freshness summary;
- manual trigger ownership and troubleshooting documentation;
- artifact retention policy with no automatic deletion;
- Pi suite selection that preserves preflight and hardware-isolation proof;
- final operational handoff.

#### Milestone 8 Slice 1: Registered mixed droplet/stream lifecycle

Status: `complete` (2026-08-07)

- compose one representative mixed-mode lifecycle from the existing editor,
  multi-stock, rack, calibration, manual-refuel, and stock-pass phases;
- exercise normal Qt controls for both droplet and stream heads, matching
  calibration evidence, the required passed manual-refuel check, both stock
  passes, exact terminal persistence, and clean teardown;
- retain visible Windows evidence and its exact replay before declaring the
  scenario active in the lifecycle suite;
- do not add another runner family or claim physical stream/refuel evidence.

#### Milestone 8 Slice 2: Manual suite and capability selection

Status: `complete` (2026-08-07)

- add deterministic `--suite`, `--capability`, listing, and dry-run selection
  over the validated manifest while retaining direct `--scenario` behavior;
- reject conflicting selectors, unsupported platforms, deferred capabilities,
  and missing Pi evidence before execution;
- optionally recommend affected scenarios from changed source areas without
  automatically executing them;
- freeze the standard lane's scenario, seed, order, and timeout.

Completion evidence:

- selection/listing/recommendation modes return before Qt/application imports,
  emit deterministic JSON with the validated manifest hash, and record
  `execution_authorized: false`;
- suite and capability selectors remain dry-run-only until Slice 3, while
  direct scenario execution retains its existing registry call path;
- all schedule rows now declare operator-initiated `on_demand` / `manual`
  ownership, with evidence-age values retained as informational metadata;
- 117 focused selection/manifest/contract tests and both existing 24-well SIL
  smoke tests passed on Windows. The full suite remains deferred to Slice 8.

#### Milestone 8 Slice 3: Host suite execution and aggregation

Status: `complete` (2026-08-07)

- run each manually selected Windows journey in a fresh child process so Qt
  state cannot leak between journeys;
- retain every child report and write an aggregate JSON/text summary with
  child paths, hashes, statuses, durations, and replay commands;
- continue independent lifecycle children after a failure to collect coverage,
  but classify the aggregate fail-closed;
- keep regression and stress explicitly selected rather than implied by the
  standard lane.
- Windows suite/capability execution now resolves the Slice 2 plan before any
  writes, launches every scenario sequentially in a fresh Python process, and
  retains a validated `labcraft.virtual_workflow_aggregate` v1 document with
  plan, process, report, source, hash, timeout, and replay evidence;
- the qualification standard suite, mixed-mode capability, eight-child
  lifecycle suite, visible standard suite, and its exact replay all passed.
  The lifecycle qualification also exposed and corrected bounded SIL-harness
  defects in expected editor-dialog synchronization and the soft-stop report
  builder; no production MVC or simulator behavior changed;
- focused unit/contract and real-process system tests passed. The complete
  Python suite remains deferred to Slice 8.

#### Milestone 8 Slice 4: Capability coverage and source freshness

Status: `complete` (2026-08-07)

- join retained reports to manifest capabilities, required assertions, action
  surfaces, and source identities;
- distinguish `pass`, `fail`, `incomplete`, `missing`, and `stale` instead of
  treating report presence as coverage;
- produce machine-readable and human-readable summaries without modifying the
  tracked manifest from generated evidence;
- treat evidence age as informational under the manual policy and source
  identity as the primary freshness boundary.
- the explicit, repeatable `--coverage-from` selector now validates retained
  aggregate/report hashes and joins them to manifest scenarios, required
  assertions, semantic actions, declared interaction surfaces, verification
  layers, and source-tree identities without importing Qt or executing a
  workflow;
- the versioned JSON/text evaluation distinguishes `pass`, `fail`,
  `incomplete`, `missing`, and `stale`, retains exact inputs and replay, and
  writes only new evidence beneath `verification_reports/suites/coverage`;
- one fresh mixed-mode capability evaluation and its exact replay passed as
  source-current; a retained pre-fingerprint aggregate remained readable but
  was correctly classified incomplete rather than accepted as fresh;
- 138 focused unit/contract tests and two real-process system tests passed.
  The complete Python suite remains deferred to Slice 8.

#### Milestone 8 Slice 5: Parameterized scenario matrices

Status: `complete`

- `mixed_mode_calibration_v1` defines eight immutable, hash-identified cases
  across mixed, droplet/droplet, and stream/stream pairs, both stock orders,
  both calibration profiles, and every planned manual-refuel state;
- every case is built in memory from the single tracked mixed-mode reference
  fixture and runs through the shared multi-stock body, stock-pass phases, Qt
  page drivers, assertions, report-v1 writer, and simulator;
- negative cases attempt Start through normal UI controls, choose Cancel in
  the exact manual-refuel safeguard, and pass only after authoritative proof
  that no bypass, new intent, additional completion, or running state occurred;
- the parent runner uses fresh child processes and retains a hashed plan,
  aggregate, child reports, logs, parameters, seed, and exact replay;
- the complete offscreen matrix and exact replay passed 8/8. Both visible
  representative cases and their exact replays passed. Focused validation
  passed 114 unit/contract tests and four system tests; the complete Python
  suite remains deferred to Slice 8.

#### Milestone 8 Slice 6: Seeded sequence exploration

Status: `complete`

- `editor_prepared_guard_v1` generates legal and intentionally invalid
  prepared-editor sequences for the frozen seeds `1, 7, 19, 42, 101` using one
  private seeded generator, one in-memory fixture derivation, and one dynamic
  journey;
- legal sequences vary rename and edit/regenerate ordering. Illegal sequences
  temporarily make printed volume exceed final reaction volume, attempt
  Finalize through the real Qt control, dismiss the real `Invalid volumes`
  warning, prove authoritative persistence/runtime state is unchanged, and
  recover through normal Qt edits, regeneration, refinalization, and reload;
- reports retain the normalized plan, catalog/sequence hashes, reached
  transitions, rejection and recovery evidence, action cap, seed, screenshots,
  snapshots, ledgers, and exact replay. Legal runs use 18 actions and the
  longest illegal run uses 23 of the 25-action maximum;
- ten fresh children run sequentially beneath a hashed exploration aggregate.
  The complete offscreen campaign and its exact replay passed 10/10; visible
  `seed_7_legal` and `seed_101_illegal` runs and both exact replays passed;
- focused validation passed 148 unit/contract tests and seven real-process
  system tests. The complete Python suite remains deferred to Slice 8.

#### Milestone 8 Slice 7: Manual Pi suite integration

Status: `complete` (2026-08-07)

- expose `pi_primary` and `pi_stress` through the same manual suite-selection
  and aggregate-report contracts;
- preserve mandatory Pi preflight, traced hardware-isolation proof, supported
  platform checks, and production-mode rejection;
- keep stress explicitly opt-in and perform remote Pi operations only after
  separate operator authorization;
- run local contract tests before any representative remote evidence is
  requested.
- aggregate v1 now accepts validated `pi_sil` plans, forwards one proved
  preflight/proof pair to fresh children, and rejects any report whose source
  tree, Pi model, Qt platform, proof, trace, or sandbox protections disagree;
- the remote wrapper exposes only named `pi_primary` and `pi_stress` suites,
  keeps Pi capabilities planning-only, and retains remote suite evidence by
  default. Stress remains explicitly selected and was not run locally;
- suite replay uses a strictly allowlisted argument vector, and artifact bundle
  v2 transports one original aggregate or an original plus replay without
  changing the legacy report-set bundle v1 contract;
- focused local validation passed 81 unit/contract tests and 14 system tests,
  including the real Windows standard suite and PowerShell primary/stress dry
  runs. A later combined source-identity selection passed 50 tests from a fresh
  ignored basetemp after the default Windows pytest temp root denied access;
- the authorized exact-source Raspberry Pi completed `pi_primary` and its exact
  allowlisted replay with 96/96 completions in each fresh child. Both
  aggregates, all ten required assertions, Pi proof/trace linkage, clean
  teardown, zero unexpected dialogs, and zero queue starvation passed;
- the final aggregate SHA-256 values are `25ec6c8389564041...` and
  `16799d1e19973d6a...`; the validated two-aggregate bundle SHA-256 is
  `ecb9fccc83017583...`. Remote evidence remains retained and `pi_stress` was
  not run;
- two fail-closed qualification findings were corrected before closeout: the
  composed proof audit now classifies native Linux ARM as Pi SIL, and isolated
  children/replay preserve the repository virtual-environment executable.

#### Milestone 8 Slice 8: Retention, runbook, and closeout

Status: `complete` (2026-08-07)

- document which manual suite to run for each class of change, artifact
  locations, replay, stale-evidence handling, troubleshooting, and Pi safety;
- retain artifacts in the existing root with no automatic cleanup; document a
  future bounded cleanup policy without implementing destructive behavior;
- inspect representative standard, lifecycle, matrix/exploration, regression,
  stress, and authorized Pi evidence;
- run focused tests per slice and the complete Python suite once at final
  Milestone 8 validation.

Closeout progress (2026-08-07):

- final-source Windows standard 1/1, lifecycle 8/8, matrix 8/8, exploration
  10/10, and host regression 96/96 passed;
- host stress completed 3,840/3,840 operations and ten head lifecycles with
  zero failed actions/assertions, starvation, or unexpected dialogs and clean
  teardown; its aggregate retains only informational responsiveness/RSS
  warnings;
- visible standard and its exact replay passed, and all 21 Windows
  capabilities are passing with zero failed/stale/missing entries;
- focused validation passed 189 unit/contract and 18 real-process system
  tests; the complete default suite passed 4,080 tests with 72 intentional
  skips and 389 warnings in 218.64 seconds;
- two fail-closed page-driver timing corrections changed the final Windows
  source fingerprint to
  `bd2fb283c348f1bd8585079f2287f180223bfea4b058448899e6c138a2ace5d9`;
- fresh authorized `pi_primary` and its exact replay passed 96/96 each from
  commit `1e7efa86f95461a2865c075c717f06af06ae28cd` in a separate clean Pi
  worktree. Aggregate hashes are `c884a480054f31fff6d435e5cb0aae7efd9223d6525bff342ca9c2af1baa25f8`
  and `228fd7aad64d28d03a93511cdd37791825737e70ccfddba11261c7c3293172a6`;
  the validated bundle hash is
  `785bcbbc8e6d6e34eff13c11fd7fcc4f20c1afa54b349d53810e89deae7b8ff0`;
- all remote evidence remains retained, no cleanup ran, and `pi_stress`
  remained out of scope.

Gate:

- standard lane is deterministic and bounded;
- exploratory failures are exactly replayable;
- stress and Pi policies retain existing safety gates;
- missing, failed, incomplete, and stale evidence remain distinct;
- no manual suite or generated sequence can select production hardware mode;
- the mixed droplet/stream lifecycle is active and assertion-backed;
- ordinary matrix cases add data rather than duplicate journey bodies;
- generated sequences are bounded, state-aware, and exactly replayable;
- every run is operator-initiated;
- complete documentation and representative evidence are inspected.

Rollback:

- remove one suite, matrix, or exploration selector while retaining direct
  scenario execution and its reports;
- return the mixed-mode scenario to focused test coverage without reverting
  unrelated reusable phases;
- remove generated aggregate/freshness output without deleting authoritative
  child scenario evidence.

### Milestone 9: Calibration requantization and exact dispense-count evidence

Status: `complete` (2026-08-08; all six slices and final validation complete)

Goal:

- make a passing calibration SIL run prove that a changed effective ejection
  volume produces the intended authoritative, displayed, commanded, and
  completed droplet counts rather than proving only calibration lifecycle and
  stock/well completion cardinality.

Current gap:

- `mixed_mode_calibration_v1` varies mode, stock order, calibration profile,
  and manual-refuel outcome, but each case prepares the same effective volume
  that its synthetic calibration later applies;
- the focused 40 nL to 10.8 nL convergence test proves revision persistence
  and reload but does not execute the recalculated plan;
- current composed execution evidence counts completed stock/well pairs while
  omitting the commanded droplet count from retained intent evidence.

Deliverables:

- a small typed matrix registry so additional matrix catalogs reuse the
  existing fresh-process runner, aggregate, hashing, replay, and report
  contracts without adding a runner family;
- calibration page-driver evidence for the exact visible preview rows,
  including old/new droplet counts, achieved targets, and printed-volume
  shifts;
- bounded execution evidence that retains `commanded_droplets` for every
  durable intent and the corresponding simulator dispense command;
- reusable assertions joining, by exact stock and well identity:
  - prepared target counts;
  - calibration-preview counts;
  - calibrated execution-plan target counts;
  - retargeted zero-progress counts and plan revision;
  - reconstructed runtime targets;
  - commanded simulator counts;
  - completed and terminal persisted counts;
- immutable, hash-identified requantization cases derived in memory from a
  small tracked reference fixture;
- exact replay, visible representative evidence, capability/manifest
  integration, focused tests, and documentation.

Initial curated cases:

1. identical-volume idempotent control with unchanged target counts;
2. same-mode droplet-volume increase crossing an `N -> N-1` rounding
   boundary;
3. same-mode droplet-volume decrease crossing an `N -> N+1` rounding
   boundary;
4. multiple targets in one reagent producing both changed and unchanged
   counts;
5. the existing stream-to-droplet 40 nL to 10.8 nL transition followed by
   actual array execution and terminal reload;
6. fill-stock requantization with non-fill stock targets unchanged;
7. a zero-fill plan whose requested calibration would require a missing fill
   stock and must fail without mutation;
8. a two-reagent plan where one single-stock reagent is recalibrated and the
   other stock, its assignments, and its counts remain unchanged.

Case policy:

- freeze expected boundary counts in the typed catalog independently of the
  production requantization method under test;
- choose values on both sides of a rounding boundary with an explicit margin;
  do not depend on an exact floating-point half tie;
- do not infer exact dispensing from stock/well completion cardinality;
- two-stock reagent auto-application remains outside this milestone because
  the production calibration UI currently supports automatic Apply only for
  single-stock reagent plans.

Likely files:

- matrix catalog/selection/runner modules beneath
  `tools/virtual_workflows/`;
- shared calibration page driver, execution observer, journey, and assertion
  modules;
- focused unit/contract and real-process system tests;
- capability manifest and operator documentation after executable evidence
  exists;
- production MVC files only if the new assertions expose a separately
  reviewed application defect.

Gate:

- every positive case proves exact equality across preview, plan, progress,
  runtime, intent, simulator command, and terminal added counts;
- the expected stock alone changes unless the case explicitly targets fill;
- plan revision, calibration record, printer-head identity, well assignment,
  and immutable revision history remain correctly linked across reload;
- the negative zero-fill case leaves the authoritative bundle byte-identical
  and emits no print intent or simulator dispense;
- complete offscreen matrix and exact replay pass in fresh processes;
- at least one count-increase and one count-decrease case pass visibly and by
  exact replay;
- focused validation, the lifecycle suite, host regression, and the complete
  Python suite pass before milestone closeout.

Rollback:

- remove the requantization catalog and its selector while retaining the
  generic evidence fields if they are backward-compatible and useful;
- otherwise revert the bounded observer/driver/assertion additions together;
- do not modify or delete retained experiment data or historical evidence.

### Milestone 10: Curated experiment-design pairwise matrix

Status: `execution planned` (2026-08-08; six independently reviewable slices)

Execution plan:

- `docs/sil_interactive_simulation_milestone_10_execution_plan.md`
- execute one slice at a time, with a slice-specific implementation plan,
  targeted validation, retained evidence, completion record, and independent
  commit before advancing;
- register no placeholder matrix in Slice 10.1. Publish the first executable
  two-case prefix in Slice 10.2, append cases without changing earlier case
  hashes, and freeze the final nine-case catalog in Slice 10.5;
- derive every case in memory from the unchanged
  `experiment_editor_create_finalize_v1.json` reference fixture;
- keep catalog expectations independent of production optimization,
  generation, assignment, finalization, and runtime-reconstruction code.

Slice sequence:

1. typed catalog, independent oracle, named pairwise audit, hashing, and
   test-local selector contracts;
2. reusable editor inputs, authoritative reload/activation, control case, and
   multiple-reagent seed-4321 case;
3. one-stock feasible and one-stock-rejected/two-stock-success formulation
   cases;
4. custom wells with exclusions and the paired seed-1234 randomization case;
5. exact capacity, capacity-plus-one rejection, and infeasible fixed/max-stock
   rejection with exact no-authoritative-mutation evidence;
6. complete matrix/replay, visible representatives, lifecycle and host
   regressions/replays, full Python suite, retained evidence, documentation,
   and milestone closeout.

Goal:

- promote high-risk formulation, assignment, randomization, and capacity
  behavior from focused Model/UI tests into real-editor, authoritative-file,
  reloadable SIL evidence without a Cartesian case explosion.

Deliverables:

- a typed experiment-design case schema and immutable catalog derived in
  memory from a small reference fixture;
- reusable editor-driver inputs for multiple reagents, target sets, fixed or
  optimized stocks, one/two-stock mode, replicate counts, randomization seed,
  custom printable wells, and preconfigured exclusions;
- independent expected reaction counts, stock identities, per-well
  assignments, target counts, and capacity outcomes;
- positive-case assertions for editor presentation, optimization output,
  prepared execution plan, progress, key/concentration exports, explicit
  reload, and reconstructed runtime assignment;
- negative-case assertions for exact production warning/status behavior and
  absence of partial authoritative artifacts;
- fresh-process aggregate, replay, visible representative evidence, focused
  tests, and documentation.

Initial curated cases:

1. one additive, one target, one stock, and one replicate as a control;
2. multiple reagents and concentration targets with a nontrivial reaction
   count;
3. a formulation feasible with one stock;
4. a formulation infeasible with one stock but feasible when two-stock mode
   is enabled;
5. a sparse custom well subset containing preconfigured excluded wells that
   must remain unavailable and unassigned;
6. deterministic randomized assignment with a fixed seed, same-seed replay,
   and a different-seed comparison while preserving the reaction multiset;
7. replicate count exactly equal to available plate capacity;
8. capacity plus one, which must be rejected through the real editor;
9. a deliberately infeasible target-volume or stock formulation, which must
   not finalize.

Pairwise policy:

- cover each important value and pair interaction deliberately; do not form a
  full product of reagents, concentrations, stock modes, wells, seeds, and
  capacity;
- manual well assignments and randomized automatic assignments remain
  separate cases because manual assignment intentionally bypasses
  randomization;
- exclusions may be staged as an explicit harness/model precondition when no
  production UI owns their configuration, but selection, disabled state,
  capacity, finalization, and reload must be exercised through the real UI and
  application;
- same-seed equality and different-seed divergence are asserted only where the
  reaction set has more than one valid permutation.

Likely files:

- matrix catalog and typed design-case builders;
- shared experiment-editor page driver, journey phases, assertions, and
  report evidence;
- a small reference fixture if the existing editor fixture cannot express the
  catalog cleanly;
- focused unit/contract and system tests;
- capability manifest and documentation after qualification.

Gate:

- every positive case finishes through normal Qt controls and reloads from a
  valid authoritative bundle;
- reaction count, stock plan, target counts, well IDs, reaction-to-well
  mapping, progress reference, and key files match the independent case
  oracle;
- same-seed replay reproduces the exact assignment and different-seed cases
  retain the same reaction multiset;
- excluded wells are never selectable or assigned;
- exact-capacity finalization succeeds, while capacity-plus-one and infeasible
  formulations produce the expected blocking result with no new or changed
  authoritative execution artifacts;
- complete matrix, exact replay, visible positive and negative
  representatives, focused tests, lifecycle suite, and complete Python suite
  pass before closeout.

Rollback:

- remove the design catalog and dynamic selector while retaining existing
  editor journeys and focused tests;
- revert any catalog-only driver generalization that has no remaining caller;
- no persisted application-data migration is permitted.

### Milestone 11: Randomized design, calibration, reload, and execution interaction

Status: `planned`

Goal:

- prove that a boundary-crossing calibration remains associated with the
  correct stock, well assignments, counts, printer head, progress, and
  completion events in a randomized multi-reagent design across an
  application-session reload.

Required lifecycle:

1. create a bounded multi-reagent design through the real editor;
2. enable deterministic automatic randomization and retain the seed and exact
   reaction-to-well mapping;
3. finalize and validate the prepared authoritative bundle;
4. stage the intended head and apply a Milestone 9 boundary-crossing
   calibration to one single-stock reagent through the real calibration UI;
5. record the changed and unchanged stock/count maps at zero progress;
6. close the application cleanly;
7. construct a fresh application session, load the experiment through the
   editor, and explicitly activate authoritative execution;
8. validate the same seed, stock identities, printer-head binding,
   calibration linkage, well mapping, and requantized counts;
9. calibrate any remaining stock as required and execute every stock pass;
10. reconcile exact intents, simulator commands, progress, stock-pass
    boundaries, terminal completion, and terminal reload.

Deliverables:

- a composed journey using the existing session, editor, calibration, rack,
  reload, execution, and evidence components;
- a reusable clean-session rotation phase for calibrated zero-progress
  authoritative execution if the current paused-reload phase cannot express
  it without scenario-specific branching;
- assertions keyed by `(stock_id, well_id)` rather than list position;
- proof that the uncalibrated stock and source design remain unchanged while
  the calibrated plan revision and progress reference advance correctly;
- retained screenshots, action/assertion ledgers, authoritative snapshots,
  exact replay, focused tests, and capability documentation.

Constraints:

- use a multi-reagent design whose calibrated reagent resolves to exactly one
  execution stock; this milestone does not extend production two-stock
  calibration Apply behavior;
- reload must reconstruct from authoritative files and may not reuse success
  from the first application session;
- randomization changes well assignment only; stock identity and calibration
  association must never depend on row or iteration position.

Gate:

- prepared, calibrated, reloaded, active, per-pass, terminal, and terminal
  reload checkpoints all pass their exact identity/count assertions;
- the calibrated stock changes by the expected boundary counts and the other
  stock does not;
- every commanded and persisted added count matches the reloaded calibrated
  plan exactly once;
- no unexpected dialog, error, queue starvation, duplicate intent, missing
  intent, or ambiguous checkpoint occurs;
- offscreen execution, exact replay, one visible qualification, focused tests,
  lifecycle suite, host regression, and complete Python suite pass.

Rollback:

- remove the interaction journey and any journey-specific report fields;
- retain independently useful Milestone 9 and 10 matrix coverage;
- revert a generalized reload phase only if it has no other validated caller.

### Milestone 12: Editor, execution-preflight, and persistence safeguards

Status: `planned`

Goal:

- prove through independently runnable real-UI and reload boundaries that the
  application fails closed before dispensing when design, calibration,
  identity, lifecycle, or authoritative persistence is invalid.

Safeguard groups:

- editor safeguards:
  - impossible target or printed/final volume;
  - infeasible one/two-stock formulation;
  - plate-capacity overflow;
  - invalid or excluded well selection;
  - finalization attempted from a dirty or invalid design;
- execution-preflight safeguards:
  - missing or stale applied calibration;
  - pulse-width or pressure mismatch;
  - calibration profile/mode mismatch;
  - loaded printer-head, stock, design, or calibration identity mismatch;
  - persisted execution inspected but not explicitly activated;
  - edit, recalibration, start, resume, or head exchange attempted at an
    invalid lifecycle boundary;
- persistence safeguards:
  - an unreflected pending intent producing an ambiguous reload;
  - conflicting or unavailable plan/progress revision;
  - missing calibration linkage for progressed execution;
  - incomplete or conflicting authoritative files.

Deliverables:

- separate typed safeguard catalogs or focused scenarios at meaningful
  failure boundaries rather than one large negative journey;
- normal Qt actions for editor Finalize, calibration generation/Apply, load,
  activation, Start, and other operator-visible attempts;
- exact expected dialog title, message class, preflight/eligibility code, and
  UI state evidence;
- a shared no-mutation/no-dispatch assertion proving unchanged authoritative
  hashes, plan/progress revision, completion count, queue, array state,
  command history, and intent set;
- explicit, instance-local persistence fault fixtures created only beneath an
  isolated scenario root before application launch, with original and mutated
  hashes retained;
- fresh-process execution, exact replay, visible representative failures,
  focused tests, and capability documentation.

Fault policy:

- a negative persistence case may create a deliberately invalid copy to test
  application rejection, but it must never modify a user experiment or write
  authoritative files to manufacture a passing state;
- each case must stop at its asserted boundary and must not rely on a later
  cleanup action to erase an unsafe command or intent;
- bypasses may be tested only as explicitly named safeguard behavior and may
  not satisfy the normal safe-start capability.

Gate:

- each safeguard attempts the real operator action and observes the expected
  fail-closed production response;
- zero new dispense intents, simulator print commands, completions, and added
  droplets occur after the rejected action;
- array state remains idle or at the exact pre-existing safe boundary, the
  queue drains, and no unrelated stock/head state changes;
- persistence cases are classified with the exact expected eligibility or
  synchronization result and never activate an ambiguous bundle;
- all negative-case reports retain failure-boundary evidence while the
  scenario report itself passes only when the safeguard works;
- complete safeguard catalogs, exact replay, visible representatives,
  focused tests, lifecycle suite, and complete Python suite pass.

Rollback:

- remove one safeguard catalog or scenario without weakening existing
  production guards;
- remove isolated fault builders and their generated evidence without
  deleting historical child reports or user experiment data;
- any production defect fix discovered during qualification receives its own
  minimal rollback description.

### Milestone 13: Bounded seeded design/calibration exploration

Status: `planned after Milestones 9-12 are stable`

Goal:

- explore bounded legal and illegal operation orderings around reagent edits,
  randomization, regeneration, calibration application, reload, and lifecycle
  guards only after deterministic matrices provide exact oracles for every
  operation used by the generator.

Deliverables:

- a versioned state-machine generator whose states distinguish at least:
  draft valid/invalid, prepared zero-progress, calibrated zero-progress,
  reloaded inactive, active zero-progress, progressed/locked, and terminal or
  safely rejected;
- a bounded semantic operation catalog covering selected combinations of:
  - add, remove, or change reagent inputs;
  - toggle one/two-stock design mode;
  - change printable wells, randomization, or seed;
  - optimize, generate, regenerate, finalize, and refinalize;
  - stage a matching or mismatching head;
  - generate, select, and apply calibration;
  - close, reload, activate, start, and attempt invalid lifecycle actions;
- fixed tracked seeds, a strict action cap, normalized sequence hashes, exact
  rerun commands, and fresh-process children;
- legal sequences that reach a valid authoritative terminal boundary and
  illegal sequences that prove rejection, no mutation/no dispatch, recovery,
  and a valid final boundary;
- retained generated plan, reached transitions, action/assertion evidence,
  screenshots, authoritative hashes, cleanup, aggregate, and exact replay.

Exploration policy:

- reuse the deterministic Milestone 9-12 actions and assertions; the
  generator must not invent weaker success criteria;
- use a small fixed seed set and keep each sequence below a reviewed semantic
  action maximum;
- generated exploration is diagnostic and may supplement but may not replace
  deterministic capability evidence;
- do not add refill-required/resume operations while volume tracking remains
  disabled and `execution.refill_resume` remains deferred;
- do not mutate active authoritative files except through an explicitly
  isolated Milestone 12 fault fixture.

Gate:

- generator output is deterministic, hash-stable, state-continuous, bounded,
  and exactly replayable;
- every operation has a deterministic matrix or focused-test oracle before it
  is admitted to the generator;
- legal and illegal sequences cover every admitted operation and every
  declared rejection class across the frozen seed set;
- unexpected dialogs, assertion omissions, action-cap overruns, state
  discontinuities, non-replayable failures, or hardware-access attempts fail
  the campaign;
- complete campaign and exact replay pass after the deterministic matrices,
  lifecycle suite, and complete Python suite are green.

Rollback:

- remove the new exploration campaign and selector while retaining all
  deterministic Milestone 9-12 cases and direct journeys;
- generated evidence remains historical unless separately reviewed for
  bounded cleanup.

## Milestone Dependency Graph

```text
Milestone 0
    |
    v
Milestone 1 --> Milestone 2
    |              |
    v              |
Milestone 3 -------+
    |
    v
Milestone 4A --> Milestone 4B
                      |
                      v
                 Milestone 5
                      |
                      v
                 Milestone 6
                      |
                      v
                 Milestone 7
                      |
                      v
                 Milestone 8
                      |
                      v
                 Milestone 9
                      |
                      v
                 Milestone 10
                      |
                      v
                 Milestone 11
                      |
                      v
                 Milestone 12
                      |
                      v
                 Milestone 13
```

Milestone 3 can begin after the interfaces in Milestone 0 are frozen and may
run in parallel with recorder implementation. UI application waits for the
interactive session and provider. Automation extraction waits for successful
manual lifecycle characterization.

Milestone 9 establishes the exact dispense-count oracle required by all later
dosage-sensitive work. Milestone 10 establishes deterministic formulation and
assignment cases. Milestone 11 joins those two areas across reload and actual
execution. Milestone 12 freezes the relevant negative lifecycle and
persistence boundaries before Milestone 13 admits the same operations to
seeded exploration. Refill-required/resume coverage is not on this dependency
chain and remains deferred until authoritative volume tracking is enabled.

## Target Validation Strategy

### Contract/unit validation

- session configuration and containment;
- deterministic seed behavior;
- result schema and numeric bounds;
- state event schema and ordering;
- action preconditions, timeouts, and evidence;
- assertion pass/fail/incomplete behavior;
- report and manifest joins;
- matrix-registry identity, independent expected-count catalogs, and exact
  case hashing;
- exact plan/progress/runtime/intent/simulator count reconciliation;
- safeguard no-mutation/no-dispatch behavior;
- state-machine continuity and action-cap enforcement for generated
  sequences;
- cleanup idempotence;
- source/import hardware isolation.

### Qt integration validation

- visible and offscreen session construction;
- simulator-control connection;
- page-driver widget interaction;
- calibration result display, selection, and Apply;
- calibration preview old/new count and printed-volume-shift presentation;
- stream refuel modal/task/preflight behavior;
- experiment editor to runtime handoff;
- multiple reagent rows, one/two-stock design selection, custom wells,
  randomization seed, and capacity/infeasibility presentation;
- rejected Finalize, calibration Apply, load/activation, and Start actions;
- failure screenshots and unexpected-dialog rejection.

### Composed SIL validation

- complete droplet lifecycle;
- multi-stock lifecycle;
- mixed droplet/stream lifecycle;
- boundary-crossing calibration followed by exact commanded-droplet
  execution;
- curated formulation, assignment, randomization, capacity, and infeasibility
  cases;
- randomized multi-reagent calibration/reload/execution association;
- reload/recovery lifecycle;
- focused fault boundaries;
- missing/stale/mismatched calibration and ambiguous persistence rejection;
- exact persistence and intent reconciliation;
- clean teardown.

### Existing compatibility validation

Until migration is complete, preserve the validation commands from
`docs/sil_verification_framework_hardening_plan.md`, including:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Focused commands and node IDs must be added to this document as files are
created. On this Windows checkout, use the repository `env` interpreter and
allow at least 15 minutes for the full suite.

Firmware validation is not required unless a separately authorized change
touches `firmware/`. This plan does not authorize firmware changes.

## Evidence Requirements

Every composed journey must retain:

- session identity and configuration;
- seed and synthetic-provider version;
- action ledger with interaction surfaces;
- assertion results;
- cross-layer state trace;
- dialog and error records;
- simulator command lifecycle;
- prepared, previewed, calibrated, runtime, commanded, and completed droplet
  counts keyed by stock and well where applicable;
- calibration requests and generated normalized results;
- manual-refuel outcomes;
- plan/progress/resume/calibration identities;
- original and mutated hashes for explicitly isolated negative persistence
  fixtures;
- normalized matrix case or exploration sequence identity and exact replay;
- named screenshots;
- failure traceback when applicable;
- cleanup results;
- report and summary;
- explicit limitations.

Sensitive machine, network, user, and credential data must not enter fixtures
or reports.

## Performance Policy

Functional journeys may record timing but do not create performance
acceptance thresholds.

- `speed_multiplier` applies only to simulated command durations.
- Fixed functional timeouts bound hangs; they are not performance baselines.
- Calibration generation time is diagnostic.
- Performance comparisons remain in explicitly compatible regression/stress
  lanes.
- A performance finding opens a separate optimization effort.

## Scenario And Fixture Policy

- Add a new scenario for a meaningful risk, lifecycle boundary, platform
  requirement, historical failure, or materially different evidence policy.
- Use parameters or typed builders for ordinary data variations.
- Keep a small set of tracked reference fixtures.
- Do not create a fixture per seed.
- Do not conflate scenario identity, workload identity, calibration profile,
  and suite identity.
- Keep failure injection explicit and instance-local.
- A broad journey does not replace focused tests for a state transition that
  can fail independently.

## Risks And Mitigations

### Interactive and automated simulation drift

Risk:

Manual and automated launch paths behave differently.

Mitigation:

Both construct the same `SimulationSession`; visibility and automation
drivers are configuration only.

### Accidental hardware access

Risk:

A simulation convenience re-enables a production factory or physical port.

Mitigation:

Separate launcher, sentinel-only connection, launcher-owned controls,
source/import traps, disabled production connection widget, explicit safety
evidence, and fail-closed dependency construction.

### Random calibration flakiness

Risk:

Uncontrolled random values make failures irreproducible.

Mitigation:

Local seeded generator, named profiles, recorded normalized result, fixed
standard seeds, and exact rerun commands.

### Synthetic result bypasses application behavior

Risk:

The test writes a valid calibration directly to disk and misses UI/Model
defects.

Mitigation:

Inject only a result candidate, then use real selection and Apply behavior.
Validate close/reload from authoritative files.

### Simulator becomes a second implementation of business logic

Risk:

The simulator calculates plans, eligibility, or completion independently and
allows the application to be wrong.

Mitigation:

Simulator provides external state and deterministic command completion only.
Controller and Model remain authoritative for business decisions.

### State recorder changes timing or behavior

Risk:

Heavy snapshots block the Qt event loop or retain unbounded memory.

Mitigation:

Bounded in-memory projection, append-only evidence, compact event payloads,
explicit sampling for high-frequency values, and recorder performance tests.

### One large journey hides later coverage

Risk:

An early failure prevents calibration, printing, or teardown paths from being
reached.

Mitigation:

Retain independently runnable focused scenarios and organize suites by
meaningful lifecycle boundaries.

### Shared Qt process instability

Risk:

Many composed journeys in one long Windows Qt process cause native shutdown
or state leakage.

Mitigation:

Use one session per meaningful journey and process isolation for composed
system modules where needed. Reuse composition code, not mutable application
instances across unrelated scenarios.

### Simulation claims exceed evidence

Risk:

Passing virtual calibration is interpreted as proof of physical accuracy.

Mitigation:

Capability layer and report limitations distinguish application workflow SIL,
protocol simulation, HIL, and physical validation.

### Migration destabilizes existing evidence

Risk:

Refactoring runners changes reports, baselines, Pi contracts, or failure
artifacts.

Mitigation:

Compatibility adapters, scenario-by-scenario parity, retained reports,
explicit schema changes, and rollback per migrated scenario.

## Rollback Strategy

Use one milestone per commit or a smaller commit when a milestone contains an
independently reviewable production defect correction.

Rollback order:

- Milestones 1-2 can be removed without affecting current automated SIL.
- Milestone 3 can be removed without application-data migration.
- Milestones 4A-4B remove simulation-only calibration/refuel adapters while
  preserving existing physical paths.
- Milestone 6 can restore the compatibility adapter for existing runners.
- Milestone 7 reverts one scenario migration at a time.
- Milestone 8 removes suite/schedule selection without deleting direct
  scenario execution.
- Milestone 9 removes the requantization catalog and, if necessary, its
  bounded count-evidence extensions without changing production data.
- Milestone 10 removes the design matrix and catalog-only editor-driver
  generalization while retaining existing editor journeys.
- Milestone 11 removes the joined interaction journey while retaining the
  independently useful Milestone 9 and 10 matrices.
- Milestone 12 removes one safeguard catalog or isolated fault builder at a
  time without weakening production guards.
- Milestone 13 removes the new generated campaign while retaining every
  deterministic case and direct journey.

Never use rollback to rewrite or delete retained production experiment data,
accepted baselines, or existing release tags.

## Decision Log

Record decisions here before implementation depends on them.

### D1: Existing Slice 4.7 sequencing

Status: `open`

Recommended:

- pause it and use disconnect as an early composed-journey proof after the
  shared harness exists.

### D2: Simulator connection UI

Status: `accepted and implemented in Milestone 1`

Recommended:

- use a launcher-owned simulator control and leave the production connection
  widget disabled in simulation.

### D3: Session retention default

Status: `accepted and implemented in Milestone 1`

Recommended:

- fresh isolated root by default; explicit `--keep-session` for manual
  diagnosis; automated reports retain their scenario root under the ignored
  verification output.

### D4: Synthetic calibration variability

Status: `proposed`

Recommended:

- fixed seed for standard lanes; explicit versioned seed sets for exploratory
  lanes; no unseeded acceptance runs.

### D5: Report evolution

Status: `open`

Options:

- preserve report-v1 with additive nested state/calibration evidence;
- define report-v2 when generic action surfaces and assertion joins cannot be
  represented cleanly without ambiguity.

Do not change report identity until comparison, baseline, Pi, and retained
report compatibility have been characterized.

### D6: Refill-required/resume sequencing

Status: `accepted` (2026-08-08)

Decision:

- do not include refill-required/resume qualification in Milestones 9-13;
- keep `execution.refill_resume` deferred while authoritative volume tracking
  is not enabled;
- do not add test-owned volume bookkeeping or infer a refill boundary from
  command counts alone;
- revisit refill-required/resume only through a separate reviewed plan after
  production volume tracking is enabled, durable where required, exposed to
  the SIL state oracle, and covered by focused tests.

This decision does not remove existing non-volume soft-stop/resume or
authoritative reload/resume coverage.

## Definition Of Done

Milestones 0-9 are complete. The expanded effort is complete when:

- a dedicated visible interactive launcher safely constructs the real
  application in simulation mode;
- manual and automated sessions use the same `SimulationSession`;
- simulator connection can only target `SIMULATED`;
- cross-layer state is observable, bounded, retained, and correlated;
- nominal droplet and stream calibration results are deterministic and
  reproducible;
- synthetic results are selected and applied through the real calibration
  workflow;
- stream printing requires and validates a matching passed simulated manual
  refuel check;
- one-stock, multi-stock, and mixed-mode experiments complete manually in
  isolated sessions;
- terminal experiments close and reload with valid authoritative state;
- shared page drivers, typed actions, assertions, reports, and cleanup replace
  duplicated scenario orchestration;
- broad happy-path journeys are concise and independently runnable;
- focused fault and lifecycle-boundary scenarios remain independently
  runnable;
- existing 96-well, 384x10, comparison, Pi, and report contracts are migrated
  or preserved intentionally;
- capability output distinguishes UI, Controller, Model, simulator, and
  harness interaction surfaces;
- fixed standard runs and scheduled seed exploration are reproducible;
- boundary-crossing calibrations reconcile exact displayed, authoritative,
  runtime, commanded, and terminal droplet counts;
- curated experiment-design cases cover multiple reagents/concentrations,
  one/two-stock feasibility, well subsets/exclusions, deterministic
  randomization, replicate/capacity boundaries, and infeasible formulations;
- the randomized design/calibration interaction survives a fresh application
  reload and completes with stock/well/count identity intact;
- editor, calibration, execution-preflight, lifecycle, and persistence
  safeguards prove no mutation and no dispense dispatch at rejected
  boundaries;
- expanded seeded exploration remains bounded, state-aware, reproducible, and
  subordinate to deterministic matrix evidence;
- refill-required/resume remains explicitly deferred and is not required for
  this expansion while authoritative volume tracking is disabled;
- hardware isolation remains fail closed;
- full affected and complete Python regression suites pass;
- representative success and failure evidence is manually inspected;
- documentation contains exact launch, replay, test, suite, troubleshooting,
  and cleanup commands;
- no firmware, protocol, physical calibration, motion, pressure, or droplet
  behavior is claimed by this application SIL effort.

## Current Next Action

Milestones 7, 8, and 9 are complete. Their operator capabilities remain the
current qualified baseline. Milestone 10 is the current next action:

1. Slice 10.1 is complete: the complete typed nine-case catalog, independent
   expected-value oracle, named 14-pair audit, fixed hashes, and test-local
   selector/runner contracts are recorded while the production registry
   remains unchanged.
2. Slice 10.2 is complete: the control and multiple-reagent seed-4321 cases
   execute through reusable Qt editor inputs, authoritative finalization,
   byte-identical prepared reload, and exact saved-plan assignment
   reconstruction.
3. Slice 10.3 is complete after the separately authorized two-stock accuracy
   correction. The one-stock and two-stock cases pass selected fresh-process,
   replay, and visible checks with exact stocks/counts, authoritative reload,
   and no-mutation evidence for the rejected first attempt.
4. Slice 10.4 is complete: the sparse custom-well/exclusion and seed-1234
   cases pass fresh-process, exact replay, and visible exclusion checks. The
   real picker proves disabled-cell rejection; authoritative reload proves
   exact selected/assigned wells; and persisted hashes prove equal reaction
   multisets with distinct seed-specific assignments.
5. Slice 10.5 is the current next action: append exact-capacity and the two
   rejected-finalization cases;
   prove exact warning/status behavior and no new or modified authoritative
   execution artifacts.
6. Slice 10.6: qualify and replay the complete nine-case matrix, visible
   positive/negative representatives, lifecycle and host regressions, and the
   complete default Python suite; retain evidence, update operator docs, and
   record Milestone 10 complete.

Validation policy: Slices 10.1-10.5 run only their targeted unit, contract,
selected fresh-process, and bounded visible checks. Slice 10.6 alone runs the
complete Milestone 10 matrix and exact aggregate replay, broader regression
suites/replays, and the full Python suite. Existing Milestone 7-9 hashes,
schemas, runners, reports, replay behavior, fixtures, and direct journeys
remain compatibility gates throughout.

The Milestone 9 count oracle is stable and is reused only to normalize
observed stock/well plan and runtime counts. Milestone 10 expected values remain
literal catalog-owned data and are not computed by production algorithms.
Milestone 13 must not begin until all deterministic Milestones 9-12 are stable.
Do not add refill-required/resume cases or operations while volume tracking
remains disabled. Do not run `pi_stress` unless it is explicitly selected and
separately justified, and do not infer firmware, protocol, physical
calibration, or physical-hardware coverage from application SIL evidence.
