# SIL Verification Framework Hardening Plan

Status: `in_progress`

Date opened: 2026-07-24

## Purpose

This is a separate verification-framework effort. Its purpose is to turn the
existing focused virtual print workflows into a maintainable software-in-the-
loop (SIL) validation portfolio with:

- fast standard smoke coverage;
- independently runnable lifecycle scenarios;
- scheduled Windows stress and Raspberry Pi SIL lanes;
- reusable, typed scenario actions;
- a tracked capability-coverage manifest;
- explicit ownership, cadence, assertions, limitations, and evidence freshness.

This effort reorganizes and extends verification tooling only. It does not
resume the performance-remediation work recorded in
`docs/virtual_workflow_verification_plan.md`, and it does not authorize changes
to production behavior.

## Decision Updates

- 2026-07-26: Deferred refill-required pause/resume because volume tracking is
  disabled. Promoted editor creation/finalization, prepared
  rename/refinalization, and the post-start edit boundary to the first targeted
  lifecycle family after an observed pre-start rename could not be finalized.

## Scope Freeze

In scope:

- scenario registry and suite selection;
- test-owned scenario orchestration;
- tracked, versioned virtual-workflow fixtures;
- reusable scenario actions that drive existing Qt controls or Controller APIs;
- scenario assertions, artifacts, reports, and coverage summaries;
- pytest tiering and opt-in controls;
- scheduled Windows and Pi invocation contracts;
- documentation and tests for the framework itself.

Out of scope:

- further execution-persistence, pass-start, terminal-transition, guidance, or
  Windows atomic-rename performance optimization;
- changes to `Controller`, `Model`, `View`, `Machine_FreeRTOS`, production
  persistence ordering, or production UI behavior;
- changes to motion, pressure, command timing, or safety interlocks;
- firmware or device-protocol changes;
- protocol-level virtual MCU work;
- physical hardware validation or claims about physical motion, pressure,
  cameras, droplets, or printer-head behavior;
- weakening `flush`, `fsync`, atomic replacement, intent ordering, recovery, or
  external-change guards to make a scenario faster;
- treating a failed scheduled stress run as authorization for production
  optimization inside this effort.

If a proposed scenario cannot be built using existing application and simulator
interfaces, record the capability as `partial`, `planned`, or `deferred`.
Opening a separate production-change effort is required before adding a new
production seam.

## Current Call Path

Real print-array path:

`WellPlateWidget -> Controller.print_array -> Controller array lookahead -> Machine command queue -> serial protocol -> firmware Orchestrator -> Printer/motion handlers -> status command counters -> Machine CommandQueue completion -> Controller._handle_array_well_complete -> progress/execution checkpoint updates -> Qt repaint and next lookahead command`

Current in-process SIL path:

`QTest/scenario driver -> real MainWindow -> real Controller -> real Model and authoritative execution files -> SimulatedMachine command queue/status -> real completion callback -> Qt UI updates -> metrics/report`

This hardening effort operates on the second path only. It must not alter the
first path.

## Relationship To Existing Work

The existing virtual-workflow implementation already provides:

- an explicit, hardware-isolated application construction path;
- a deterministic in-process simulated machine;
- real Qt event-loop execution;
- real Controller, Model, persistence, widget, and callback behavior;
- a versioned 96-well print-array fixture;
- a versioned 384-well by 10-stock stress fixture;
- lifecycle, persistence, queue, responsiveness, and resource instrumentation;
- canonical reports, summaries, screenshots, event traces, and stall stacks;
- same-host report-set comparison and candidate baselines;
- fail-closed Pi preflight, Bubblewrap isolation, hardware-access tracing,
  evidence bundling, hash validation, retrieval, and path-safe cleanup.

The current implementation is intentionally focused rather than framework
shaped:

- CLI scenario selection is a hard-coded choice between two workload IDs;
- both workloads run through one large print-array orchestration function;
- scenario identity and workload identity are effectively conflated;
- setup, actions, waits, instrumentation, assertions, reporting, and teardown
  are interleaved;
- the 96-well real-UI workflow is larger than necessary for routine smoke
  coverage;
- the reduced multi-stock test is derived from the stress fixture rather than
  registered as a lifecycle scenario;
- pytest has one broad `virtual_workflow` marker rather than distinct smoke,
  lifecycle, regression, and stress tiers;
- simulator pause, resume, clear, disconnect, reset, and deterministic fault
  behavior is tested mostly below the composed workflow level;
- no tracked manifest connects risk capabilities to scenarios, assertions,
  cadence, platforms, limitations, or current evidence.

The framework should preserve the existing evidence machinery and make scenario
composition, selection, and coverage claims smaller and more explicit.

## Design Principles

### Preserve application truth

Scenario actions must drive existing Qt controls, signals, Controller methods,
or simulator interfaces. They must not duplicate production business rules,
edit authoritative files behind the application's back during an active
transaction, or directly force UI/model state to make an assertion pass.

### Separate scenario, workload, and suite identity

- A scenario describes a lifecycle and its assertions.
- A workload describes the versioned data volume and fixture.
- A suite selects scenarios for a cadence or purpose.

For example, the existing 96-well workload may participate in a host-regression
scenario and a Pi-primary suite without becoming the identity of either suite.

### Prefer typed Python composition

Use Python scenario definitions and typed/bounded action objects or functions.
Do not create an unrestricted JSON instruction interpreter. JSON should declare
coverage metadata and fixture data; Python should perform actions and validate
their inputs.

### Keep functional and performance decisions separate

Smoke and lifecycle scenarios primarily prove state transitions, durability,
UI composition, hardware isolation, and artifact production. Existing
responsiveness metrics remain visible, but only explicitly scheduled regression
or stress lanes apply performance comparison or workload-specific stress gates.

### Fail closed and retain evidence

Every composed scenario must:

- use an isolated scenario root;
- be timeout bounded;
- reject unexpected dialogs and hardware access;
- restore observers, event filters, timers, and wrappers;
- retain a canonical report and failure artifacts when setup progressed far
  enough to create a run root;
- report incomplete capability assertions as failures rather than silently
  omitting them.

### Make coverage claims executable

A capability is not `covered` merely because a scenario name appears in a
manifest. At least one active scenario must declare a required assertion for
the capability, and the report must contain the corresponding assertion result.

## Target Validation Portfolio

| Tier | Purpose | Initial contents | Default cadence | Target duration |
| --- | --- | --- | --- | ---: |
| Contract/unit | Validate framework, manifest, actions, simulator contracts, and report compatibility | Manifest/registry validation, action unit tests, fixture contracts, simulator lifecycle tests | Every standard pytest run | Seconds |
| Standard SIL smoke | Prove one composed real-UI path quickly | New 24-well, one-stock happy path | Every standard pytest and PR run | At most 30 seconds |
| Targeted lifecycle | Exercise bounded user journeys, recovery, and state transitions | Editor create/finalize/refinalize/lock boundary, soft-stop/resume, authoritative reload/resume, 24x2 head exchange, disconnect fail-closed | By capability/change; all nightly | At most 60 seconds each |
| Host regression | Retain representative workflow and comparison evidence | Existing 96-well scenario and baseline comparison | Nightly and for execution/UI/persistence changes | A few minutes |
| Host stress | Detect sustained-load correctness, growth, and responsiveness problems | Existing 384x10 scenario | Weekly and before relevant releases | Existing 1,800-second timeout |
| Pi SIL primary | Detect target CPU/filesystem regressions without hardware | Existing 96-well Pi lane with safety proof | Weekly | Existing Pi timeout |
| Pi SIL stress | Characterize sustained target behavior | Existing 384x10 Pi lane | Monthly and before relevant releases | Existing 1,800-second timeout |

The initial cadence is a starting policy. Revisit it after at least four
successful scheduled cycles per lane. Any cadence change must update the
manifest and this document.

## Standard Smoke Scenario

Proposed scenario ID:

`print_array_smoke_24_v1`

Proposed workload ID:

`virtual_print_array_24_v1`

The fixture should:

- use `shallow-384_well_plate`;
- construct the real 16-row by 24-column widget tree;
- select one deterministic serpentine row, A1 through A24;
- use one virtual stock and one virtual printer head;
- require one stock/well completion per selected well;
- retain the existing two-well lookahead;
- use the existing canned virtual calibration approach;
- use existing safe simulation construction.

Required actions:

1. Create an isolated, prepared authoritative experiment.
2. Launch the real application in explicit simulation mode.
3. Connect only to the sentinel simulated port.
4. Enable/home the simulated machine and set dispense frequency.
5. Stage the virtual head and apply its print settings.
6. Enable print-pressure regulation.
7. Start the array through the real Qt control and acknowledge only allowlisted
   dialogs.
8. Wait for exact terminal completion and tear down cleanly.

Required assertions:

- simulation banner is present and hardware access is disabled;
- real 16x24 plate UI is constructed;
- exactly 24 stock/well completions occur;
- each intended well updates exactly once;
- lookahead does not starve while work remains;
- intent lifecycle and durable operation counts match the 24 completions;
- retained and pending terminal intents are zero;
- terminal plan state is `completed`;
- no unexpected dialog or workflow error occurs;
- simulator timers, event-loop probe, resource observer, progress observer, and
  I/O observer are restored or stopped;
- report, summary, event trace, stall-stack file, and named screenshots exist;
- the report validates against the stable report-v1 envelope.

The smoke workload is not a replacement for the existing 96-well baseline. It
is the default composed correctness check.

## Targeted Lifecycle Scenarios

Implement lifecycle scenarios sequentially. A scenario does not proceed to the
next status until its focused test, shared action tests, report inspection, and
full regression lane pass.

### Experiment editing state policy

The editor scenarios must encode the intended boundary between an editable
design and immutable physical execution history:

| Execution state | In-place editing | Expected workflow |
| --- | ---: | --- |
| Draft, with no execution plan | Allowed | Save or finalize |
| Prepared, with no calibration or print progress | Allowed | Reconcile and refinalize safely |
| Calibration or printing started | Not allowed | Resume or create an editable copy |
| Completed or aborted | Not allowed | Analyze or create an editable copy |

Prepared-state scenarios should validate the final authoritative invariants
without prescribing whether the implementation safely replaces the prepared
plan, advances a revision, or assigns a new plan identity. Active or terminal
scenarios must prevent any solution from weakening the immutable-history
boundary.

### 1. Create and finalize through the editor

Scenario ID:

`experiment_editor_create_finalize_v1`

Call path:

`QTest -> MainWindow experiment-designer control -> real ExperimentDesignDialog -> new experiment -> Qt design controls -> optimize/generate -> Finish -> save design -> MainWindow.complete_experiment_design -> Model.load_experiment_from_model -> initial execution-plan creation -> authoritative files -> main-window runtime state`

Required behavior and assertions:

- open the real editor from the real main window;
- start a new experiment through the editor;
- enter a deterministic name and a bounded minimal design;
- optimize and generate through the real Qt control;
- finalize through the real Finish control;
- return to the main window without unexpected dialogs or errors;
- prove folder name and saved `metadata.name` match the entered name;
- validate `experiment_design.json`, execution plan, immutable revision history,
  progress, resume, and key-file consistency;
- prove the plan state is `PREPARED` and progress is zero;
- prove runtime assignments match the selected wells;
- reload the experiment and prove it is `ready_to_start`;
- retain editor-opened, generated, finalized, reloaded, and validated
  milestones.

### 2. Rename and refinalize before execution

Scenario ID:

`experiment_editor_prestart_rename_refinalize_v1`

Call path:

`first editor finalization -> prepared execution with zero progress -> reopen real editor -> edit experiment-name control -> Finish -> save/rename design -> execution-plan reconciliation/refinalization -> authoritative inspection -> reload eligibility`

Required behavior and assertions:

- begin with a valid prepared execution created through the editor;
- prove no calibration, printing, or saved progress has begun;
- reopen the real editor and prove the name field is editable;
- change only the experiment name and finalize again;
- reject any unexpected save/finalization warning;
- prove folder name and saved `metadata.name` agree after the rename;
- prove authoritative inspection succeeds after refinalization;
- prove the current execution plan matches the revised saved design;
- prove plan, progress, resume, and immutable-history references are mutually
  consistent;
- prove the plan remains `PREPARED`, progress remains zero, and eligibility is
  `ready_to_start`;
- prove no duplicate, stale, ambiguous, or conflicting current execution
  artifact remains;
- retain rename/refinalization audit and event evidence;
- close and reload from disk so an in-memory success cannot hide inconsistent
  persisted files.

This is the direct regression scenario for the observed workflow in which the
name field accepted an edit after initial finalization but the second Finish
operation reported that the experiment could not be saved.

If the scenario reproduces that failure, retain the diagnostic evidence and
leave `experiment.prepared_rename_refinalize` incomplete. Correcting production
refinalization behavior requires a separate, explicitly scoped MVC change with
its own call path, validation, risks, and rollback. Do not weaken the scenario,
silently accept the warning, or permanently mark the regression as expected.

### 3. Enforce the post-start edit boundary

Scenario ID:

`experiment_editor_post_start_lock_v1`

Call path:

`prepared execution -> existing calibration/printing lock transition -> reopen real editor -> lock-state UI -> rejected in-place edit/finalization -> Create Editable Copy -> source validation`

Required behavior and assertions:

- begin with a valid execution whose calibration or printing lifecycle has
  crossed the existing lock boundary;
- reopen the real editor and prove in-place name/design controls are disabled
  or read-only;
- display a clear reason that in-place editing is unavailable;
- prove Finish cannot overwrite or refinalize the active execution;
- create an editable copy through the supported UI workflow;
- prove the editable copy has a distinct directory and fresh execution
  identity;
- prove the source design, execution plan, revision history, progress, and
  resume checkpoint remain unchanged;
- prove the copy is editable while the source remains protected.

This scenario is the safety counterpart to prepared-state refinalization. It
must be implemented in the same editor-lifecycle milestone so that allowing
safe pre-start edits cannot accidentally permit mutation after execution
history exists.

### 4. Soft stop and resume

Scenario ID:

`print_array_soft_stop_resume_24_v1`

Call path:

`QTest start -> Controller.print_array -> simulated command lookahead -> QTest soft-stop control -> Controller.request_array_soft_stop -> pause-after watermark -> clear/park/finalize -> resume_ready -> QTest resume control -> Controller.print_array resume -> terminal completion`

Required behavior and assertions:

- request soft stop after a deterministic observed completion count;
- stop through the real UI/Controller path;
- prove the pause watermark and completion catch-up are bounded;
- reach `resume_ready`;
- retain a valid authoritative checkpoint with no ambiguous intent;
- prove no completion occurs after the stopped boundary while awaiting resume;
- resume through the real UI start/resume path;
- finish every target exactly once with no skipped or duplicated stock/well;
- retain stop, stopped, resumed, and completed milestones in the event trace.

### 5. Authoritative reload and resume

Scenario ID:

`authoritative_reload_resume_24_v1`

Call path:

`first simulated app -> partial execution and clean stop -> first app teardown -> second explicit simulated app -> real experiment load/authoritative inspection -> runtime activation -> resume_ready -> QTest resume -> terminal completion`

Required behavior and assertions:

- create partial durable progress using the real completion path;
- stop and tear down the first application cleanly;
- preserve the isolated scenario directory between application instances;
- reconstruct the second application using normal explicit simulation
  dependencies;
- load through the real authoritative execution path;
- prove eligibility and runtime state agree with persisted progress;
- resume without replaying completed stock/wells;
- finish with a valid terminal bundle;
- attribute artifacts and events to both application sessions in one scenario
  report.

### 6. Multi-stock head exchange

Scenario ID:

`print_array_multi_stock_24x2_v1`

This scenario should promote the existing reduced 24-well by two-stock
workflow into a named lifecycle scenario rather than constructing it inside a
test by mutating the 384x10 fixture.

Required assertions:

- two distinct stock and printer-head identities;
- exactly two independently recorded stock passes;
- an idle, drained queue before each virtual head exchange;
- correct head/stock association and print settings;
- intermediate plan state after pass one and completed state after pass two;
- exactly 48 stock/well completions;
- bounded retained event history and clean simulator teardown.

### 7. Disconnect fail-closed

Scenario ID:

`print_array_disconnect_mid_array_24_v1`

Call path:

`QTest start -> active simulated command lifecycle -> existing simulated disconnect -> Controller/Model disconnect handling -> array no longer advances -> retained recovery evidence -> teardown`

Required behavior and assertions:

- disconnect after a deterministic completion count;
- stop accepting new completions after the disconnect boundary;
- cancel or retire simulator work according to its current contract;
- leave no running array state that can advance without reconnection;
- retain the last proven durable progress and explicit recovery eligibility;
- classify the scenario according to its expected fail-closed outcome rather
  than treating the intentional disconnect as an unexpected framework crash;
- retain failure/recovery screenshots, events, and terminal diagnostics.

This scenario proves application behavior at the in-process simulated machine
boundary. It does not claim serial framing, ACK/status, MCU reset, or firmware
recovery coverage.

### Deferred lifecycle candidates

Track but do not initially implement:

- refill-required pause and resume while volume tracking is disabled;
- board reset mid-array;
- protocol transport delay/drop/rejection;
- canned calibration-result application as a standalone workflow;
- calibration UI workflows using virtual recordings;
- physical HIL equivalents.

`execution.refill_resume` remains `deferred` until volume tracking is restored
and independently validated. No current SIL scenario should claim automatic
refill triggering. When the prerequisite is met, the future scenario must
reach the real refill-required decision through bounded fixture data, preserve
progress, resume without duplicates, and avoid a production-only test hook.

Board-reset and transport-fault capabilities remain `partial` or `deferred`
until their simulation semantics can be tied to the real protocol/firmware
contract. This plan does not start the deferred virtual-MCU slice.

## Reusable Action Architecture

### Scenario context

Introduce a test-owned `ScenarioContext` that owns:

- scenario and workload definitions;
- isolated run and experiment paths;
- application, view, controller, model, experiment model, and simulator
  references;
- event recorder and named phase recorder;
- installed observers and restoration callbacks;
- expected dialogs and captured dialogs;
- milestone screenshots;
- deadline and predicate-based wait helper;
- accumulated action and assertion results.

The context must not outlive one scenario run.

### Action contract

Each action should have:

- a stable action ID;
- validated, bounded input;
- a declared precondition;
- one application-facing operation;
- predicate- or signal-based completion;
- a bounded timeout derived from the scenario deadline;
- structured action result and evidence;
- an explicit failure message;
- no hidden retries that change application semantics.

Suggested initial actions:

| Action ID | Responsibility |
| --- | --- |
| `fixture.prepare_authoritative` | Create a new isolated prepared experiment from a tracked workload |
| `app.launch_simulated` | Construct and show the real application with explicit safe dependencies |
| `editor.open` | Open the real experiment designer from the real main window |
| `editor.start_new` | Start a fresh experiment through the supported editor workflow |
| `editor.set_experiment_name` | Edit the real experiment-name control and observe dirty state |
| `editor.configure_minimal_design` | Populate a deterministic bounded design through Qt controls |
| `editor.optimize_generate` | Invoke the real optimize/generate control and wait for completion |
| `editor.finish` | Invoke the real Finish/Activate control and classify dialogs or handoff errors |
| `editor.reopen` | Reopen the editor against the current experiment and inspect lock/edit state |
| `editor.create_editable_copy` | Create a distinct editable copy through the supported UI workflow |
| `machine.connect_ready` | Connect sentinel simulator, enable/home, and wait for ready state |
| `head.stage_virtual` | Exchange/stage a configured virtual head while idle and drained |
| `pressure.enable_regulation` | Apply existing settings and wait for regulation |
| `array.start_via_ui` | Click the real start/resume control and handle allowlisted dialogs |
| `array.wait_for_completions` | Wait for an exact or minimum observed completion count |
| `array.request_soft_stop_via_ui` | Invoke the real soft-stop UI path |
| `array.wait_for_state` | Wait for a supported array state with diagnostics |
| `machine.disconnect_simulated` | Invoke the simulator's existing disconnect contract |
| `experiment.reload_authoritative` | Load an existing authoritative execution through the real application path |
| `artifact.capture_milestone` | Record event and nonempty screenshot |
| `validation.prepared_execution` | Validate prepared state, zero progress, and ready-to-start eligibility |
| `validation.design_plan_consistency` | Validate saved design, plan, revisions, progress, resume, and reload agreement |
| `validation.execution_edit_lock` | Validate active/terminal source protection and editable-copy separation |
| `validation.terminal_bundle` | Perform final full authoritative validation |
| `scenario.teardown` | Stop timers, restore wrappers/observers, close UI, and verify cleanup |

### Scenario definition

A scenario definition should declare:

- scenario ID and version;
- workload fixture ID and version;
- ordered action construction;
- capability IDs;
- required assertion IDs;
- applicable platforms;
- tier and suite membership;
- timeout;
- expected outcome policy;
- required artifacts and limitations.

Keep definitions in Python so actions can use typed inputs and normal code
review. The coverage manifest references stable IDs from these definitions.

### Compatibility adapter

Retain the public `VirtualPrintArrayScenarioConfig` and
`run_virtual_print_array_scenario` interfaces during extraction.

Compatibility requirements:

- existing 96-well and 384x10 scenario IDs remain accepted;
- current output-root containment remains unchanged;
- report-v1 top-level fields remain unchanged;
- current report-set and baseline compatibility identity remains unchanged for
  existing workloads;
- current Pi proof/report linkage remains unchanged;
- failure artifacts remain available;
- existing callers do not need to adopt suite selection immediately.

Remove the adapter only in a separately reviewed compatibility-breaking
milestone. Its removal is not required by this effort.

## Capability-Coverage Manifest

Proposed path:

`tools/virtual_workflows/manifests/capability_coverage_v1.json`

Proposed schema identity:

`labcraft.sil_capability_coverage`, version `1`

Top-level sections:

- `capabilities`;
- `scenarios`;
- `suites`;
- `schedules`;
- `policy`.

### Capability entry

Each capability records:

- stable ID;
- risk statement;
- owner role;
- status: `covered`, `partial`, `planned`, or `deferred`;
- required verification layers;
- active scenario IDs;
- required assertion IDs;
- related source areas for human selection guidance;
- explicit limitations;
- maximum evidence age when freshness matters.

Capability IDs and current hardening status:

| Capability ID | Initial status | Primary evidence |
| --- | --- | --- |
| `sil.hardware_isolation.host` | `covered` | Safe construction, source/import guards, smoke |
| `sil.hardware_isolation.pi` | `covered` | Pi preflight, private `/dev`, trace proof |
| `ui.real_app_construction` | `covered` | Standard smoke |
| `execution.array_happy_path` | `covered` | Standard smoke and 96 regression |
| `execution.lookahead_no_starvation` | `covered` | Standard smoke, 96, multi-stock |
| `execution.intent_durability` | `covered` | Standard smoke, 96, multi-stock |
| `execution.terminal_bundle` | `covered` | Standard smoke, 96, multi-stock |
| `experiment.editor_create_finalize` | `covered` | `experiment_editor_create_finalize_v1` |
| `experiment.prepared_reopen` | `covered` | `experiment_editor_create_finalize_v1` |
| `experiment.prepared_rename_refinalize` | `planned` | Direct pre-start rename regression scenario |
| `experiment.design_plan_consistency` | `covered` | `experiment_editor_create_finalize_v1` |
| `experiment.active_edit_lock` | `planned` | Post-start editor lock scenario |
| `experiment.editable_copy` | `partial` | Existing unit coverage; composed post-start scenario pending |
| `execution.soft_stop_resume` | `covered` | `print_array_soft_stop_resume_24_v1` |
| `execution.refill_resume` | `deferred` | Volume tracking is disabled; prerequisite not met |
| `execution.authoritative_reload_resume` | `covered` | `authoritative_reload_resume_24_v1` |
| `execution.disconnect_fail_closed` | `planned` | Disconnect lifecycle scenario |
| `execution.multi_stock_head_exchange` | `covered` | `print_array_multi_stock_24x2_v1` |
| `ui.event_loop_stall_detection` | `covered` | Injected-stall probe test |
| `ui.sustained_responsiveness.windows` | `partial` | Scheduled 96/384x10 evidence |
| `ui.sustained_responsiveness.pi` | `partial` | Scheduled Pi evidence |
| `resources.sustained_growth.windows` | `partial` | Scheduled 384x10 evidence |
| `resources.sustained_growth.pi` | `partial` | Scheduled Pi 384x10 evidence |
| `protocol.serial_lifecycle` | `deferred` | Future virtual MCU or HIL |
| `protocol.reset_mid_array` | `deferred` | Future virtual MCU or HIL |
| `hardware.motion_pressure_droplet` | `deferred` | HIL only |

The manifest must describe current truth. Do not mark planned lifecycle
capabilities covered until their scenario reports contain every required
assertion result. Keep `execution.refill_resume` deferred until volume tracking
is restored and independently validated.

### Scenario entry

Each scenario records:

- stable scenario ID and version;
- Python registry ID;
- workload fixture ID;
- tier;
- suite memberships;
- supported platforms;
- timeout;
- action IDs;
- assertion IDs;
- capability IDs;
- required artifacts;
- expected outcome;
- limitations;
- test node IDs.

### Suite entry

Initial suites:

| Suite ID | Selection |
| --- | --- |
| `standard` | Contract/unit plus one real-UI 24-well smoke |
| `lifecycle` | All active targeted lifecycle scenarios |
| `host_regression` | Existing 96-well run and compatible comparison collection |
| `host_stress` | Existing 384x10 run |
| `pi_primary` | Existing 96-well Pi collection with fixed safety proof |
| `pi_stress` | Existing 384x10 Pi collection with fixed safety proof |

### Manifest validation

The validator must reject:

- unknown top-level or enum values;
- duplicate capability, scenario, suite, action, or assertion IDs;
- missing registry definitions or fixtures;
- scenario entries with no assertions;
- suite entries referencing unknown scenarios;
- active scenarios with missing tests;
- capabilities marked covered with no active scenario;
- capabilities marked covered when required assertions are absent;
- incompatible platform/suite combinations;
- stress or Pi scenarios included in `standard`;
- Pi suites without the existing preflight/proof requirement;
- nonportable absolute paths or secrets.

## Report And Coverage Output

Keep report schema v1's top-level envelope unchanged. Add framework evidence
under fields that the existing envelope intentionally allows to vary.

Suggested additions under `workload`:

- `scenario_definition_id`;
- `scenario_definition_version`;
- `workload_id`;
- `portfolio_tier`;
- `suite_ids`;
- `declared_action_ids`;
- `declared_capability_ids`;
- `manifest_schema_version`.

Suggested additions under `metrics.workflow.values`:

- `action_results`;
- `assertion_results`;
- `capability_results`;
- `lifecycle_milestones`.

Every capability result should include:

- capability ID;
- decision: `pass`, `fail`, `incomplete`, or `not_applicable`;
- required assertion IDs;
- observed assertion results;
- limitations;
- evidence paths or event references when applicable.

The CLI should support a read-only coverage summary that joins the tracked
manifest with inspected reports and prints:

- covered capabilities;
- partial capabilities;
- planned/deferred gaps;
- failed or incomplete latest evidence;
- stale evidence based on manifest policy;
- scenario and suite responsible for refreshing each capability.

Generated evidence must not rewrite the tracked manifest automatically.

## CLI And Pytest Interface

### CLI compatibility

Preserve existing `--scenario` behavior. Add:

- `--suite standard|lifecycle|host_regression|host_stress`;
- repeatable `--capability CAPABILITY_ID`;
- `--list-scenarios`;
- `--list-capabilities`;
- `--coverage-summary REPORT_OR_ROOT`;
- an explicit error when suite, scenario, and capability selections conflict.

Do not infer a production-impact selection from git paths in the first
milestone. The manifest's related-source fields provide review guidance, while
humans and Codex explicitly select capabilities. Automated diff-based
selection may be proposed later after the portfolio is stable.

### Pytest markers and options

Add markers:

- `sil_smoke`;
- `sil_lifecycle`;
- `sil_regression`;
- `sil_stress`;
- `sil_pi_contract`.

Default behavior:

- contract/unit tests run;
- the 24-well real-UI smoke runs;
- lifecycle, regression, and stress composed runs are skipped unless selected;
- Pi contract/unit tests remain host runnable;
- no remote Pi job is started by pytest.

Proposed options:

- `--run-sil-lifecycle`;
- `--run-sil-regression`;
- `--run-sil-stress`.

These options enable composed tests only. Remote Pi orchestration remains an
explicit wrapper invocation.

## Scheduled Execution Policy

The repository currently supplies commands and Pi orchestration but does not
contain a general tracked CI scheduler. Framework implementation must first
make every scheduled lane a deterministic, noninteractive command with stable
exit codes. Connecting those commands to a lab scheduler is a separate
operational action and must identify its owner.

Initial schedule:

| Cadence | Lane | Required result |
| --- | --- | --- |
| Nightly | Windows lifecycle suite | All active lifecycle scenarios pass and retain reports |
| Nightly | Windows 96-well regression | Functional pass; compatible comparison result retained |
| Weekly | Windows 384x10 stress | Terminal report set retained even on stress-gate failure |
| Weekly | Pi 96-well primary | Clean preflight/proof, functional pass, bundle retrieval and hash validation |
| Monthly | Pi 384x10 stress | Terminal report set, bundle retrieval, hash validation, and resource/responsiveness classification |
| Pre-release | All applicable lanes | Evidence within manifest freshness policy |

Scheduling rules:

- never run Windows and Pi reports as performance-compatible samples;
- never use traced Pi timings as performance evidence;
- never bypass Pi Bubblewrap or private-device requirements;
- never auto-promote or overwrite a tracked baseline;
- retain failed evidence according to existing policy;
- stagger Pi primary and Pi stress jobs;
- if the scheduler does not run or evidence cannot be retrieved, classify the
  capability evidence as stale/incomplete rather than pass;
- a stress performance failure opens a verification finding, not a production
  change in this effort.

## Implementation Slices

Each slice follows the root `AGENTS.md` proceed gate: restate call path, provide
a plan of at most eight steps, list files before editing, identify focused/full
validation, document risks and rollback, inspect artifacts, and commit
independently when commits are requested.

### Slice 0: Scope and compatibility freeze

Status: `verified`

Starting state:

- commit: `faca479f23f519384ad452bd5fe0b60bd2fce143`;
- tracked worktree: clean;
- intended untracked plan:
  `docs/sil_verification_framework_hardening_plan.md`;
- six pre-existing untracked execution-cache temporary directories remain
  untouched;
- no production, firmware, protocol, simulator, performance, or Pi
  orchestration behavior changes are permitted;
- no performance characterization or remote Pi run is permitted.

Frozen call path:

`QTest/scenario driver -> MainWindow -> Controller -> Model/authoritative files -> SimulatedMachine -> completion callbacks -> Qt updates -> report/comparison/Pi evidence`

Goal:

- establish this plan;
- record current scenario, report, fixture, CLI, comparison, and Pi contracts;
- declare existing 96 and 384x10 workflows compatibility anchors;
- confirm no production or firmware files are in scope.

Likely files:

- this document;
- `docs/virtual_workflow_verification_plan.md` for a cross-link only.
- `tests/test_virtual_workflow_contract_freeze.py`.

Compatibility baseline:

| Contract area | Frozen compatibility anchor | Slice 0 protection |
| --- | --- | --- |
| Legacy scenario IDs | `virtual_print_array_96_v1` and `virtual_print_array_384x10_v1` | Both remain accepted CLI choices and fixture/runner mappings; later IDs may be added. |
| Scenario identity | Name `virtual_print_array`, version `1` | Existing name/version remain supported; future identities may be added. |
| Completion contract | 96 and 3,840 completions | Existing completion-count mappings remain available. |
| CLI surface | Default scenario is the 96-well workflow; existing output, speed, timeout, visibility, Qt, Pi evidence, injection, repetition, host, report-set, baseline, maturity, and comparison flags/defaults remain available. | Help, choices, and defaults are asserted as a required subset. |
| Exit policy | Success/warning `0`; functional failure `2`; incomplete/reporting failure `3`; accepted performance failure `4`. | Representative comparison classifications assert the stable mapping. |
| Scenario API | `VirtualPrintArrayScenarioConfig`, `load_virtual_print_array_fixture`, and `run_virtual_print_array_scenario`. | Existing config fields/defaults and callable entry points are required; additive fields are allowed. |
| Report v1 | `labcraft.virtual_workflow_report`, schema version `1`, with the required run/source/environment/safety/workload/metrics/artifacts/classification/limitations envelope. | Schema identity, required envelope, and responsiveness/workflow/queue/persistence/resources metric groups remain supported. |
| Comparison policy | Report-set, baseline, and comparison schema identities with policy `virtual_workflow_policy_v1`. | Schema/policy identities and both tracked baseline summaries are loaded by the compatibility suite. |
| Platform baselines | Windows SIL and Pi SIL baselines are separate compatibility populations. | Tracked 96-well baseline summaries must retain distinct `offscreen_windows_sil` and `offscreen_pi_sil` identities. |
| Pi safety contract | Paired preflight and traced proof precede execution; Bubblewrap uses a read-only host filesystem, private `/dev`, no network, and only the report root writable. | The established fail-closed contract remains documented and protected by the existing Pi lane tests; Slice 0 does not launch a Pi operation. |

Gate:

- current focused virtual-workflow tests pass before structural extraction;
- representative existing reports validate;
- current CLI help and scenario IDs are captured in tests;
- no performance characterization is rerun solely for this slice.

Verification record (2026-07-26):

- Slice 0 started as `in_progress` at commit
  `faca479f23f519384ad452bd5fe0b60bd2fce143` with a clean tracked
  worktree, this intended untracked plan, and six pre-existing inaccessible
  execution-cache temporary directories. It is now `verified`.
- The clean pre-edit focused baseline passed 48 tests in 17.68 seconds. An
  earlier attempt was discarded after Windows Application Control blocked a
  pandas extension; after that security block was removed, the clean rerun
  passed.
- The isolated additive compatibility suite passed 3 tests in 0.06 seconds.
  The final post-change focused suite passed 51 tests in 16.89 seconds with 40
  existing Qt chart deprecation warnings.
- The retained Windows 96-well report passed report-v1 validation and retained
  classification `pass`. The retained Windows 384x10 and Pi 384x10 reports
  passed report-v1 validation and each retained classification `fail`; those
  historical classifications are review evidence, not Slice 0 acceptance
  gates.
- The tracked Windows and Pi 96-well baseline summaries passed
  `load_baseline_summary` and retained distinct `offscreen_windows_sil` and
  `offscreen_pi_sil` identities.
- The bare full-suite command could not collect through the six pre-existing
  access-denied execution-cache directories. With only those untouched
  directories explicitly ignored, the full Python suite passed 3,491 tests,
  skipped 24, and reported 148 existing deprecation warnings in 426.32
  seconds.
- No scenario characterization, stress workload, performance collection,
  remote Pi operation, production behavior change, firmware change, protocol
  change, fixture change, baseline change, or Pi-script change was made.

Retained evidence:

- `verification_reports/virtual_workflows/virtual_print_array_96_v1/20260724T234536876929Z_b1c027b76fa7/report.json`;
- `verification_reports/virtual_workflows/virtual_print_array_384x10_v1/20260724T234610716464Z_dca2fc445730/report.json`;
- `verification_reports/pi_compact_384x10_artifacts_20260724/report.json`;
- `tests/performance/baselines/virtual_print_array_96_v1_windows_sil_primary_v1.json`;
- `tests/performance/baselines/virtual_print_array_96_v1_pi5_sil_primary_v1.json`.

Risks and rollback:

- The compatibility suite intentionally binds the established private CLI
  parser/exit-policy helpers and public scenario/report identities. Planned
  additive extensions remain allowed, but an intentional incompatible change
  will require explicit review and a versioned migration.
- Retained reports remain ignored review evidence; automated compatibility
  coverage depends only on tracked baselines and repository code/fixtures.
- Rollback removes `tests/test_virtual_workflow_contract_freeze.py` and the
  cross-link, restores this Slice 0 status to `planned`, and retains the
  agreed lifecycle content. No application data, production behavior,
  firmware, protocol, hardware, fixture, baseline, or Pi rollback is needed.

Next permitted action:

- Slice 1, manifest and registry. Action extraction, lifecycle scenarios,
  performance remediation, and production changes are not permitted in the
  Slice 0 milestone.

### Slice 1: Manifest and registry

Status: `verified`

Starting state:

- commit: `faca479f23f519384ad452bd5fe0b60bd2fce143`;
- Slice 0's three intended changes remain present and uncommitted;
- six pre-existing inaccessible execution-cache directories remain untouched;
- pre-edit focused compatibility/system baseline: 51 passed with 40 existing
  Qt deprecation warnings in 16.39 seconds.

Frozen dispatch path:

`CLI --scenario -> registry lookup -> existing VirtualPrintArrayScenarioConfig -> existing run_virtual_print_array_scenario -> unchanged report/comparison/Pi evidence`

Goal:

- add the capability manifest, validator, and Python scenario registry;
- register existing 96 and 384x10 workflows without changing their execution.

Files:

- `tools/virtual_workflows/registry.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- `tests/test_virtual_workflow_manifest.py`;
- `tools/run_virtual_workflow.py`;
- `README.md`;
- this document.

Implementation constraints:

- register only the existing 96-well and 384x10 workflows;
- keep registry inspection and CLI help independent of Qt/application imports;
- lazy-dispatch through the existing scenario config and runner;
- describe current capability truth without activating future smoke or
  lifecycle scenarios;
- keep `standard` and `lifecycle` planned and empty;
- retain paired Pi preflight/traced-proof requirements;
- reject manifest/registry/fixture/test drift, invalid coverage claims,
  nonportable paths, and secret-like content;
- defer suite/capability CLI selection to Slice 5 and report/coverage joins to
  Slice 6.

Gate:

- all manifest drift/failure tests pass;
- existing single-scenario CLI runs still dispatch identically;
- no report compatibility identity changes.

Verification record (2026-07-26):

- Slice 1 started as `in_progress` at commit
  `faca479f23f519384ad452bd5fe0b60bd2fce143`, with Slice 0's intended
  changes present and the six pre-existing inaccessible execution-cache
  directories untouched. It is now `verified`.
- Added a standard-library-only immutable registry for the two legacy CLI IDs.
  Registry inspection and CLI help remain independent of Qt, application, and
  physical-hardware imports. Execution lazily constructs the existing
  `VirtualPrintArrayScenarioConfig` and invokes the existing
  `run_virtual_print_array_scenario`.
- Added manifest identity `labcraft.sil_capability_coverage`, version 1, with
  26 current-truth capabilities, two active scenarios, six suites, six
  intended schedules, embedded action/assertion catalogs, platform policy,
  limitations, and evidence-age policy. `standard` and `lifecycle` remain
  planned and empty; schedule automation remains `not_configured`.
- The manifest validator rejects schema/enum drift, duplicate or dangling IDs,
  missing registry/fixture/test definitions, inconsistent completion counts,
  unsupported suite/platform membership, invalid covered-capability claims,
  missing Pi preflight/proof policy, nonportable paths, URI credentials, and
  secret-like fields.
- The isolated final manifest suite passed 32 tests in 0.87 seconds. The final
  focused manifest/contract/comparison/96/384x10/Pi suite passed 83 tests with
  40 existing Qt deprecation warnings in 17.17 seconds.
- CLI help retained both legacy choices and every frozen flag. Mocked CLI and
  registry dispatch tests proved that each legacy ID reaches the existing
  config and runner exactly once with unchanged defaults.
- All three retained reports passed report-v1 validation with classifications
  unchanged: Windows 96-well `pass`, Windows 384x10 `fail`, and Pi 384x10
  `fail`. Both tracked baseline summaries loaded and retained distinct
  `offscreen_windows_sil` and `offscreen_pi_sil` identities.
- With only the six pre-existing inaccessible cache directories explicitly
  ignored, the full Python suite passed 3,523 tests, skipped 24, and reported
  148 existing deprecation warnings in 422.81 seconds.
- No standalone scenario characterization, full stress workload, performance
  collection, remote Pi operation, production behavior change, scenario-runner
  change, fixture/baseline/report change, firmware/protocol change, or Pi
  orchestration change was made.

Risks and rollback:

- Registry and manifest metadata can drift from executable fixtures or tests;
  strict load-time validation and mutation tests fail on that drift.
- Initial assertion evidence locators describe current report fields and test
  nodes. Generated assertion/capability results and freshness joins remain
  deferred to Slice 6, so this slice does not overstate automated coverage
  reporting.
- Rollback restores the CLI's two hard-coded choices and direct config/runner
  construction, removes the registry, manifest, and manifest tests, and
  removes the Slice 1 README/plan additions. No application data, production
  behavior, fixture, baseline, report, firmware, protocol, hardware, or Pi
  rollback is required.

Next permitted action:

- Slice 2, action/context extraction. Do not add the smoke workload, lifecycle
  scenarios, suite selection, coverage output, performance remediation, or
  production behavior changes to the Slice 1 milestone.

### Slice 2: Action/context extraction

Status: `verified`

Starting state:

- commit: `9304fe6a04f6187452c59c35e910d747331325ca`;
- tracked worktree: clean;
- six pre-existing inaccessible execution-cache directories remain untouched;
- pre-edit focused registry/contract/96/384x10/comparison/Pi baseline: 83
  passed with 40 existing Qt chart deprecation warnings in 16.89 seconds;
- no production, simulator, firmware, protocol, fixture, baseline, Pi
  orchestration, or performance-remediation change is permitted.

Frozen action path:

`registry -> public scenario adapter -> ScenarioContext/actions -> existing MainWindow/Controller/Model/SimulatedMachine -> unchanged callbacks -> report/comparison/Pi evidence`

Goal:

- extract reusable context, actions, waits, dialog handling, milestone capture,
  and teardown from the existing runner;
- retain compatibility adapter behavior.

Files:

- `README.md`;
- `docs/virtual_workflow_report_schema.md`;
- this document;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/scenarios.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- `tests/test_virtual_workflow_actions.py`;
- `tests/system/test_virtual_print_array_workflow.py`;
- `tests/system/test_virtual_print_array_384x10_workflow.py`.

Implementation:

- Added a test-owned per-run `ScenarioContext`, one monotonic
  `ScenarioDeadline`, bounded JSON action evidence, explicit
  precondition/operation/timeout failure stages, and an ordered action ledger.
- Extracted eleven stable actions for fixture preparation, simulated
  application launch, machine readiness, virtual head staging, pressure
  regulation, real UI array start, completion/state waits, milestone capture,
  terminal validation, and teardown.
- Kept Qt imports lazy in the reusable module and retained the adapter's
  explicit `SIMULATED` dependency construction. Import/source guards cover both
  the adapter and action module.
- Reused the existing dialog allowlist, real Qt controls, Controller APIs,
  authoritative fixture preparation, instrumentation, callbacks, and
  validation. Actions add no retry or production-only hook.
- Made all waits use the single scenario deadline; local timeouts may shorten
  but never extend it. Teardown ignores an exhausted scenario deadline,
  attempts all eleven cleanup phases in deterministic order, aggregates
  failures, and is idempotent.
- Added compatible `action_results`, `lifecycle_milestones`, and
  `cleanup_results` beneath `metrics.workflow.values`. The report-v1 envelope,
  classifications, comparison paths/policy, and existing artifact paths are
  unchanged.
- Replaced the manifest's embedded legacy action placeholders with the eleven
  reusable IDs. No capability status, suite membership, schedule, scenario,
  fixture, assertion, or coverage-join claim changed.

Gate:

- action precondition, timeout, failure, and cleanup tests pass;
- existing 96-well focused scenario passes;
- reduced multi-stock scenario passes;
- report-v1, report-set, comparison, artifact, and safety assertions remain
  valid;
- source/import guards show no production machine or device construction.

Verification record (2026-07-26):

- Slice 2 started as `in_progress` at the commit and worktree state above and
  is now `verified`.
- The reusable action unit suite covers catalog identity, additive
  serialization, precondition and operation failures, global/local timeout
  behavior, head-exchange safety, allowlisted/unexpected dialogs, contained
  nonempty milestone screenshots, cleanup continuation, expired-deadline
  teardown, idempotence, closed-context rejection, and application/Qt-free
  import.
- The 96-well system scenario passes through the extracted action path and
  reports all eleven action IDs, four lifecycle milestones, and eleven
  successful cleanup phases. Its forced timeout retains a failed action,
  failure screenshot/trace, and successful full teardown.
- The reduced two-stock scenario passes through two head-stage and two real-UI
  start actions, retains durable completion order, and reports successful
  milestones and cleanup. The full 384x10 workload was not launched.
- The final focused action/manifest/contract/96/384x10/comparison/Pi suite
  passed 97 tests with 40 existing Qt chart deprecation warnings.
- All three retained reports passed report-v1 validation with classifications
  unchanged: Windows 96-well `pass`, Windows 384x10 `fail`, and Pi 384x10
  `fail`. Both tracked baseline summaries loaded and retained distinct
  `offscreen_windows_sil` and `offscreen_pi_sil` identities.
- With only the six pre-existing inaccessible cache directories explicitly
  ignored, the final full Python suite passed 3,537 tests, skipped 24, and
  reported 148 existing deprecation warnings.
- No standalone scenario characterization, scheduled stress/Pi run,
  performance collection/remediation, production MVC behavior change,
  simulator behavior change, fixture/baseline change, firmware/protocol
  change, hardware operation, or Pi orchestration change was made.

Risks and rollback:

- The action layer intentionally owns private Qt/widget and simulator details
  already used by the legacy adapter. Future application refactors may require
  corresponding test-tool updates, but failures now identify the stable action
  and stage rather than timing out opaquely.
- Action evidence is additive and bounded, but is diagnostic rather than a new
  classification or comparison gate. Assertion/capability result joins remain
  deferred to Slice 6.
- Rollback restores the legacy runner's inline orchestration, removes
  `actions.py` and its tests, restores the embedded manifest action catalog,
  removes the additive nested report fields and documentation, and retains the
  Slice 0/1 compatibility and manifest work. No application data, production,
  simulator, fixture, baseline, firmware, protocol, hardware, or Pi rollback
  is required.

Next permitted action:

- Slice 3, standard smoke tier. Do not combine it with lifecycle scenarios,
  scheduled stress/Pi automation, coverage-result joins, performance
  remediation, or production behavior changes.

### Slice 3: Standard smoke tier

Status: `verified`

Starting state:

- commit: `c72832e8d264d402e7ed4ffde049d4c2e42202a1`;
- tracked worktree: clean;
- six pre-existing inaccessible execution-cache directories remain untouched;
- pre-edit focused action/manifest/contract/96/384x10/comparison/Pi baseline:
  97 passed with 40 existing Qt chart deprecation warnings in 16.70 seconds;
- no production, simulator, firmware, protocol, baseline, Pi orchestration, or
  performance-remediation change is permitted.

Frozen smoke path:

`standard pytest or direct scenario ID -> registry -> VirtualPrintArrayScenarioConfig -> reusable actions -> real MainWindow/Controller/Model/authoritative files -> SimulatedMachine -> completion callbacks -> report-v1 evidence`

Goal:

- add the 24-well workload and smoke scenario;
- make it the only default composed real-UI SIL run;
- preserve existing fixture contract tests.

Files:

- `tools/virtual_workflows/fixtures/virtual_print_array_24_v1.json`;
- `tools/virtual_workflows/scenarios.py`;
- `tools/virtual_workflows/registry.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- `tests/system/test_virtual_workflow_smoke.py`;
- `tests/system/test_virtual_print_array_workflow.py`;
- `tests/system/test_virtual_print_array_384x10_workflow.py`;
- `tests/system/test_pi_virtual_workflow_lane.py`;
- `tests/test_virtual_workflow_manifest.py`;
- `pytest.ini`;
- `tests/conftest.py`;
- `README.md`;
- this document.

Implementation:

- Added schema-v2 workload `virtual_print_array_24_v1`: real
  `shallow-384_well_plate` geometry, selected row A1-A24, one printable 1x
  virtual stock, one virtual head, one completion per well, two-well
  lookahead, and staging slot zero.
- Appended the smoke workload to the registry without reordering or changing
  the two legacy IDs. The direct CLI remains scenario-ID based and keeps
  `virtual_print_array_96_v1` as its compatibility default.
- Activated `print_array_smoke_24_v1` as the sole member of the manifest's
  `standard` suite. Standard membership rejects lifecycle, regression, and
  stress tiers. The smoke backs the existing host-isolation, real-UI,
  completion, queue, intent-durability, terminal-bundle, and artifact
  capabilities with existing report-v1 assertions.
- Added bounded launch-action evidence for the simulation banner and real
  plate-widget dimensions. This is additive nested action evidence and does
  not change report-v1 identity or classification.
- Added one fast fixture/config contract and one composed real-UI smoke test.
  The composed test proves exact completion/durability counts, queue and
  cleanup state, simulation identity, the 16x24 widget, allowlisted dialogs,
  milestones, screenshots, artifact presence, containment, and report-v1
  validity.
- Added `sil_smoke`, `sil_lifecycle`, `sil_regression`, `sil_stress`, and
  `sil_pi_contract` markers. Smoke and fast local Pi contract tests remain in
  standard pytest. Lifecycle, regression, and stress are independently
  opt-in through `--run-sil-lifecycle`, `--run-sil-regression`, and
  `--run-sil-stress`; analysis-pipeline selection remains independent.
- Marked the three existing composed 96-well paths as regression and the
  reduced two-stock path as stress. Fixture, source, registry, comparison,
  report, and Pi safety-contract tests remain fast default coverage.

Gate:

- smoke completes within the target budget on the primary Windows development
  environment;
- all required functional/durability/UI/safety/artifact assertions pass;
- standard pytest selection does not include lifecycle, regression, stress, or
  remote Pi execution;
- full Python suite passes.

Verification record (2026-07-26):

- Slice 3 started at the commit and worktree state above and is now
  `verified`.
- The isolated smoke suite passed 2 tests with 10 existing Qt chart
  deprecation warnings in 3.47 seconds. During implementation, its first
  execution revealed that a one-stock 10x/1x composition produced no running
  transition at the intended reaction volume; changing only the new fixture
  to the established 1x/1x one-stock composition produced the intended 24
  completions.
- The final default focused framework/system selection passed 98 tests,
  skipped the three composed regression tests and one composed stress test,
  and reported 10 existing warnings in 7.07 seconds.
- The opt-in 96-well regression file passed 10 tests with 30 existing warnings
  in 11.88 seconds. The opt-in reduced two-stock stress file passed 5 tests
  with 10 existing warnings in 4.79 seconds. The full 384x10 workload was not
  launched.
- Running the 96-well file with only `--run-analysis-pipeline` passed 7 fast
  tests and skipped all 3 regression tests, proving that unrelated opt-in
  controls do not enable a SIL tier.
- A direct CLI smoke completed with classification `pass`, 24 of 24
  stock/well completions, zero queue starvation, and a validated report-v1
  bundle in 3,066.462 ms:
  `verification_reports/virtual_workflows/virtual_print_array_24_v1/20260727T011808653165Z_c72832e8d264/report.json`.
- That smoke report and the three retained compatibility reports passed
  report-v1 validation. Classifications were smoke `pass`, Windows 96-well
  `pass`, Windows 384x10 `fail`, and Pi 384x10 `fail`; historical stress
  classifications remain review evidence rather than Slice 3 gates.
- Both tracked 96-well baseline summaries loaded and retained distinct
  `offscreen_windows_sil` and `offscreen_pi_sil` identities.
- With only the six pre-existing inaccessible cache directories explicitly
  ignored, the full default Python suite passed 3,538 tests, skipped 28, and
  reported 118 existing deprecation warnings in 415.76 seconds.
- No lifecycle scenario, full stress workload, performance collection,
  remote Pi operation, production behavior change, simulator behavior change,
  firmware/protocol change, baseline change, or Pi orchestration change was
  made.

Risks and rollback:

- Marker omissions on a future composed scenario could put it in the default
  lane. Registry/manifest policy, marker documentation, and default-selection
  validation make the intended tier visible, but new scenarios still require
  review.
- The 30-second smoke gate is a functional budget, not a performance baseline.
  It must not be used to compare Windows and Pi timing populations or to
  authorize performance remediation.
- The smoke uses real private widget/action surfaces already covered by the
  SIL adapter. UI refactors may require test-tool updates, while a failure
  remains bounded to test code and retained evidence.
- Rollback removes the 24-well fixture and smoke test, removes its registry and
  manifest entries, removes the additive launch evidence and tier gates,
  restores the 96/reduced tests to default selection, and removes the Slice 3
  README/plan additions. No application data, production, simulator, baseline,
  firmware, protocol, hardware, or Pi rollback is required.

Next permitted action:

- Slice 4's first independently reviewed milestone: create and finalize an
  experiment through the editor. Do not combine it with prepared rename,
  post-start locking, pause/resume, reload/resume, head exchange, disconnect,
  scheduled automation, coverage-result joins, performance remediation, or
  production behavior changes.

### Slice 4: Lifecycle portfolio

Goal:

- add one lifecycle scenario per independently reviewed milestone;
- promote reduced multi-stock coverage to a named fixture/scenario.
- keep refill-required pause/resume deferred while volume tracking is disabled.

Implementation order:

1. Editor create/finalize.
2. Prepared rename/refinalize.
3. Post-start edit lock/editable copy.
4. Soft stop/resume.
5. Authoritative reload/resume.
6. Multi-stock head exchange.
7. Disconnect fail-closed.

Likely files:

- scenario definitions and reusable actions;
- new bounded lifecycle fixtures where necessary;
- `tests/system/test_virtual_workflow_editor_lifecycle.py`;
- `tests/system/test_virtual_workflow_lifecycle.py`;
- manifest;
- report-schema documentation;
- `README.md`;
- this document.

Gate per scenario:

- focused scenario and negative-path tests pass;
- declared capabilities have assertion-backed report results;
- editor scenarios validate persisted artifacts after close/reload rather than
  relying only on in-memory state;
- the post-start editor lock scenario passes before prepared-state editing is
  considered covered;
- failure artifacts are inspected;
- the standard smoke remains unchanged;
- existing 96 and reduced/full stress contracts remain compatible;
- full Python suite passes.

#### Slice 4.1: Editor create and finalize

Status: `verified`

Call path:

`QTest -> Experiment Editor button -> ExperimentDesignDialog.exec -> New Experiment -> real editor controls and Printable Wells dialog -> Optimize and Generate -> Finish -> MainWindow.complete_experiment_design -> Model.load_experiment_from_model -> authoritative prepared files -> persisted reload -> Model.load_authoritative_execution_runtime`

Files:

- `tools/virtual_workflows/fixtures/experiment_editor_create_finalize_v1.json`;
- `tools/virtual_workflows/editor_scenarios.py`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/registry.py`;
- `tools/run_virtual_workflow.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- `tests/system/test_virtual_workflow_editor_lifecycle.py`;
- `tests/test_virtual_workflow_actions.py`;
- `tests/test_virtual_workflow_manifest.py`;
- `README.md`;
- `docs/virtual_workflow_report_schema.md`;
- this document.

Implementation:

- Added a strict minimal editor fixture with experiment name
  `sil-editor-create-finalize-v1`, the real shallow 384-well plate, two
  deterministic reactions at A1/A2, 10 nL printed/final volume, zero
  tolerance, and one fixed 1x `Editor Stock` droplet reagent.
- Added a bounded modal QTest state machine. It opens the real editor button,
  creates a new session, disables auto-update through the checkbox, enters
  values with keyboard/mouse events, selects A1/A2 through the real Printable
  Wells modal, optimizes/generates, and presses Finish. It does not call
  `_on_*` handlers directly.
- Added reusable editor action IDs, explicit-widget milestone capture,
  wrong-modal rejection, deadline/failure propagation, unexpected-message
  rejection, prepared-bundle validation, and authoritative reload actions.
- Added an editor lifecycle runner using existing isolated simulation
  dependencies without connecting the simulated machine or executing print
  commands. It always runs the existing full teardown contract.
- Added report-v1 lifecycle evidence for the five required screenshots, all
  action/assertion/cleanup results, prepared artifacts, reload activation,
  dialogs/errors, and explicit `not_applicable` queue, responsiveness, and
  resource measurements.
- Appended the lifecycle registry ID without changing the three existing IDs,
  their order, or the 96-well default. Registry/CLI inspection remains free of
  Qt/application imports.
- Limited lifecycle CLI execution to one direct local run. Pi evidence,
  injected-stall controls, report sets, repetition, and baseline creation are
  rejected before scenario construction.
- Activated the lifecycle suite with this scenario as its sole member and
  promoted only `experiment.editor_create_finalize`,
  `experiment.prepared_reopen`, and
  `experiment.design_plan_consistency`. Prepared rename/refinalize,
  post-start locking, and all later lifecycle capabilities remain unchanged.

Verification record (2026-07-26):

- Started at commit `c6eb7d1ff83d2983782a999ce43e03565d2c5b6b`
  with a clean tracked worktree and the six pre-existing inaccessible
  execution-cache directories left untouched.
- The first action probe retained a valid failure report after an offscreen
  checkbox mouse click did not toggle. The driver now uses a focused Space-key
  QTest event for checkbox state.
- A diagnostic retry showed that Enter on a spin control activated the
  dialog's default Printable Wells button. Spin and combo controls now commit
  through focus traversal, and the intended Printable Wells modal is driven
  explicitly.
- The first fully finalized report correctly showed the production default
  column-fill layout A1/B1. The scenario was amended through the real
  Printable Wells UI to select the fixture-required A1/A2; no production
  assignment behavior changed.
- The exact documented direct CLI scenario passed in 1,984.421 ms with all eight
  assertions, every action and cleanup phase, no dialogs/errors, no print
  commands, a revision-1 `PREPARED` plan, `ready_to_start` reload eligibility,
  a clean zero-intent activation checkpoint, and five nonempty screenshots:
  `verification_reports/virtual_workflows/experiment_editor_create_finalize_v1/20260727T021051247383Z_c6eb7d1ff83d/report.json`.
- Default lifecycle-file selection passed the fixture test and skipped the
  composed scenario (`1 passed, 1 skipped` in 0.04 seconds).
- The final focused lifecycle/framework selection passed 109 tests with 30
  existing Qt chart deprecation warnings in 7.65 seconds.
- The opt-in 96-well regression plus comparison and local Pi-contract
  selection passed 43 tests with 30 existing warnings in 13.78 seconds.
- All three retained reports passed report-v1 validation without rerunning
  their workflows; their classifications remained Windows 96-well `pass`,
  Windows 384x10 `fail`, and Pi 384x10 `fail`. Both tracked baseline summaries
  loaded successfully and retained distinct `offscreen_windows_sil` and
  `offscreen_pi_sil` identities.
- With only the six pre-existing inaccessible cache directories ignored, the
  full default Python suite passed 3,549 tests, skipped 30, and reported 118
  existing warnings in 692.48 seconds.
- No remote Pi operation, full stress workload, performance collection,
  production behavior change, simulator behavior change, firmware/protocol
  change, baseline change, or Pi orchestration change was made.

Risks and rollback:

- The driver intentionally depends on real editor widget contracts and will
  fail with retained stage evidence if those controls or modal sequencing
  change.
- This scenario proves one minimal prepared-state design and one in-process
  persisted reload. It does not cover prepared rename/refinalize, process
  restart, post-start locking, resume after printing, performance, firmware,
  protocol, or physical hardware.
- Rollback removes the editor fixture, runner, reusable editor actions, tests,
  registry/manifest additions, and documentation above while preserving
  verified Slices 0-3. No application data, production, simulator, firmware,
  protocol, hardware, baseline, or Pi rollback is required.

Next permitted action:

- Slice 4.2, prepared rename/refinalize. Keep post-start locking,
  pause/resume, authoritative partial reload/resume, head exchange,
  disconnect, scheduled automation, performance remediation, and production
  behavior changes out of that milestone.

#### Slice 4.2: Prepared rename and refinalize

Status: `verified`

Call path:

`QTest -> first real editor finalization -> zero-progress PREPARED execution -> reopen ExperimentDesignDialog -> edit only experiment name -> Finish -> _ensure_experiment_dir -> ExperimentModel.rename_experiment -> save_experiment -> MainWindow.complete_experiment_design -> create_or_reuse_initial_execution_plan -> authoritative inspection/reload`

Implementation:

- Added strict fixture
  `experiment_editor_prestart_rename_refinalize_v1` with initial name
  `sil-editor-prestart-rename-v1`, renamed name
  `sil-editor-prestart-renamed-v1`, the Slice 4.1 A1/A2 design, two Finish
  operations, and one rename.
- Extended the shared modal QTest actions to reopen the prepared editor, prove
  the name control is editable, change only that control, press Finish, reject
  every unexpected warning, and retain modal failure evidence.
- Generalized the editor lifecycle configuration and registry dispatch
  additively while preserving the Slice 4.1 exports, default, report, and
  direct runner.
- Added pre-rename hashes/audit/runtime evidence, successful refinalized-bundle
  and reload invariants, and post-rename failure-state capture. A successful
  implementation may replace, revise, or re-identify the prepared plan as
  long as the final persisted bundle is internally consistent.
- Added a transactional prepared-rename reconciliation in
  `ExperimentModel.rename_experiment`. A name-only rename of an untouched
  `PREPARED`, revision-1, `ready_to_start` execution now stages the renamed
  design, replaces the prepared plan and its immutable revision, rewrites
  zero-progress and exported key artifacts against the replacement identity,
  records the superseded prepared plan and audit event, validates the staged
  authoritative bundle, and publishes the renamed directory atomically.
- At this original milestone the implementation rejected started, resumed,
  calibrated, progressed, invalid, and non-name-only executions without
  mutating the authoritative source bundle. The prepared-plan replacement
  follow-up recorded after Slice 4.6 supersedes only the non-name-only
  limitation.
- Activated the scenario in the registry and manifest, appended it to the
  active lifecycle suite, and advanced
  `experiment.prepared_rename_refinalize` to `partial`. It remains partial
  until Slice 4.3 proves the post-start edit-lock and editable-copy boundary.
- Added exact fixture, action, registry/CLI, synthetic failure-policy, and
  composed expected-success tests. The expected-success test remains a strict
  passing gate and was not weakened or converted to `xfail`.

Initial regression-gate verification record (2026-07-26):

- Started at commit `adbb5b86a11222e48b592ef45728451edc17f97b`
  with a clean tracked worktree and the six pre-existing inaccessible
  execution-cache directories untouched.
- The pre-edit focused lifecycle selection passed 109 tests with 30 existing
  Qt chart deprecation warnings in 7.58 seconds.
- Fast default-tier action/registry/manifest/editor collection passed 74 tests
  and skipped four opt-in composed lifecycle tests in 3.44 seconds.
- The Slice 4.1 composed scenario, shared framework tests, and both synthetic
  lifecycle failure-policy tests passed 77 tests with 30 existing warnings in
  6.17 seconds.
- The real Slice 4.2 expected-success test failed at the second Finish, as
  required for an unresolved functional regression. The failure occurred in
  2.63 seconds and was not converted to an expected failure.
- The final requested focused lifecycle selection reported 121 passes, the
  single expected-success Slice 4.2 gate failure, and 50 existing warnings in
  10.22 seconds. All other focused framework and lifecycle tests passed.
- The final direct CLI diagnostic classified `fail` in 2,034.187 ms. It
  retained the initial valid PREPARED bundle, successful name-only action,
  exact warning, failed refinalization action, post-rename filesystem state,
  traceback, six screenshots including `failure.png`, and 11 passing cleanup
  phases:
  `verification_reports/virtual_workflows/experiment_editor_prestart_rename_refinalize_v1/20260727T025546327055Z_adbb5b86a112/report.json`.
- The warning was `Could not apply experiment design`: the renamed
  `experiment_design.json` no longer matched the retained
  `execution_plan.json` design hash. The old directory was absent, the renamed
  directory and metadata name were present, and the conflicting prepared plan
  remained inspectable for the separate defect effort.
- Default editor-lifecycle selection passed both fixture contracts and skipped
  the four composed lifecycle tests (`2 passed, 4 skipped`) in 0.05 seconds.
- The isolated 96-well regression, comparison, and local Pi-contract retry
  passed all 43 tests with 30 existing warnings in 13.11 seconds. A preceding
  parallel invocation hit the known transient missing-checkpoint failure; the
  immediate isolated retry passed without code changes.
- All three retained reports passed report-v1 validation with classifications
  Windows 96-well `pass`, Windows 384x10 `fail`, and Pi 384x10 `fail`. Both
  tracked baselines loaded with distinct `offscreen_windows_sil` and
  `offscreen_pi_sil` identities.
- With only the six pre-existing inaccessible cache directories ignored, the
  full default Python suite passed 3,560 tests, skipped 32, and reported 118
  existing warnings in 487.43 seconds.
- No production, simulator, firmware, protocol, performance, baseline, Pi, or
  hardware behavior changed.

Resolution and final verification record (2026-07-27):

- The separately scoped MVC defect fix was committed as `2a8b365` and merged
  into the font-hardened main worktree as `4bff994`. The automatic
  `editor_scenarios.py` merge retained both the SIL font-validation gate and
  the cross-platform authoritative-plan path normalization.
- Before validation, the ignored `FreeRTOS-interface/Experiments` corpus was
  restored from external backup. All 312 `frames.jsonl` and `events.jsonl`
  files referenced by the 156-run gravimetric validation manifest were present
  and nonempty before the test run and remained so afterward. Both files for
  the additional affected run `run_20260408_104206_ffe2616e` were also
  restored and nonempty.
- The complete focused lifecycle selection passed 126 tests with 50 existing
  Qt chart deprecation warnings in 10.75 seconds. This included the real
  create/finalize and rename/refinalize workflows, retained failure-evidence
  paths, manifest activation, authoritative reload, and the SIL font gate.
- A direct CLI execution of
  `experiment_editor_prestart_rename_refinalize_v1` classified `pass` in
  2,322.511 ms with all nine assertions passing and no hardware access:
  `verification_reports/virtual_workflows/experiment_editor_prestart_rename_refinalize_v1/20260727T043740214843Z_4bff9945882f/report.json`.
- With only the six pre-existing inaccessible execution-cache directories
  ignored, the full default Python suite passed 3,574 tests, skipped 32, and
  reported 118 existing warnings in 431.14 seconds.
- `git diff --check` passed, the defect worktree was clean, and the main
  worktree had no tracked changes after the merge and validation.
- No remote Pi operation, stress workload, performance collection, baseline
  regeneration, firmware/protocol change, simulator behavior change, or
  hardware access occurred.

Final disposition, risks, and rollback:

- Slice 4.2 is `verified`; its scenario is active, the lifecycle suite contains
  both editor scenarios, and `experiment.prepared_rename_refinalize` is
  intentionally `partial` pending Slice 4.3.
- The original production correction was deliberately narrow and reconciled
  only a name change. The prepared-plan replacement follow-up recorded after
  Slice 4.6 generalizes untouched prepared edits while preserving fail-closed
  behavior for started, progressed, resumed, calibrated, or invalid
  executions.
- Rollback reverts merge commit `4bff994`, returns the scenario and capability
  manifest entries to their planned state, and restores the original Slice 4.2
  failure disposition. No firmware, protocol, hardware, baseline, or Pi
  rollback is required.

Next permitted action:

- Slice 4.3, post-start edit locking and safe editable-copy behavior. Keep
  pause/resume, authoritative partial reload/resume, head exchange,
  disconnect, scheduled automation, performance remediation, firmware,
  protocol, Pi, and hardware behavior out of that milestone.

#### Slice 4.3: Post-start editor lock and editable copy

Status: `verified`

Call path:

`QTest -> real editor finalization -> authoritative runtime activation -> ExperimentModel.lock_execution_plan("printing_started") -> reopen ExperimentDesignDialog -> inspect/reject in-place editing -> Create Editable Copy -> edit/finalize copy -> source/copy authoritative inspection`

Implementation:

- Added strict fixture `experiment_editor_post_start_lock_v1` for the minimal
  A1/A2 design, source/copy names, tolerance-only copy edit, two
  finalizations, one activation, one printing-start lock, and one editable
  copy.
- Added reusable actions for activation, the durable printing-start
  transition, locked-control inspection, rejected QTest edits, real
  `QFileDialog`/`QInputDialog` copy creation, copy editing, and copy
  finalization. All actions share the existing 60-second deadline and
  fail-closed dialog/cleanup handling.
- Replaced binary editor workload selection with an additive internal
  definition mapping while preserving the Slice 4.1/4.2 exports, defaults,
  registry order, and CLI restrictions.
- Added report-v1 evidence beneath
  `metrics.persistence.values.post_start_edit_boundary` for the locked source,
  editor control matrix, copy before/after finalization, and source
  immutability comparison.
- Registered the scenario for direct execution but left it `planned`, absent
  from the active lifecycle suite, and disconnected from capability claims
  until the strict composed gate passes.
- Added exact-fixture, action/control-matrix, registry/CLI, report,
  expected-success, and retained-failure tests. The initial framework
  implementation did not change a production MVC file.

Verification record (2026-07-27):

- Started at commit `d8d20769e757344802d45e5bed1f9c4800b5c347`
  with a clean tracked worktree. `.worktrees/` and the six pre-existing
  inaccessible execution-cache directories remained untouched.
- The expanded pre-edit focused lifecycle selection passed 139 tests with 50
  existing Qt chart deprecation warnings in 11.71 seconds.
- The final fast post-change action, manifest, compatibility, and default-tier
  selection passed 84 tests and skipped the three opt-in Slice 4.3 composed
  tests in 3.26 seconds.
- The strict composed gate crossed the intended durable boundary successfully:
  the source was valid, revision 2, `ACTIVE`, locked for
  `printing_started`, zero-progress, and backed by a clean zero-intent resume
  checkpoint and two-revision immutable history.
- Reopening the real editor then failed
  `editor.inspect_active_lock_via_ui`. The name, volume, tolerance, plate,
  reagent, optimization, save, and Finish surfaces were enabled (the name
  control was not read-only), and the status text was empty. The editable-copy
  button was enabled, but there was no lock/read-only guidance.
- In accordance with the failure policy, the scenario stopped before the
  in-place edit attempt and editable-copy workflow. It retained the complete
  control matrix, source inventory and SHA-256 hashes, plan/history/resume and
  audit evidence, five screenshots including `failure.png`, traceback, and
  cleanup results. The final direct diagnostic classified `fail` in
  2,073.339 ms:
  `verification_reports/virtual_workflows/experiment_editor_post_start_lock_v1/20260727T050609503744Z_d8d20769e757/report.json`.
- The focused failure-policy rerun passed the fixture and synthetic evidence
  checks while leaving the strict expected-success gate failing (`2 passed,
  1 failed`) in 3.74 seconds. The gate was not converted to `xfail`, and no
  assertion or boundary was weakened.
- A test-only lock-policy shim exercised the otherwise unreachable downstream
  path through the real file/name dialogs, editable tolerance change,
  optimization/finalization, source byte-identity comparison, and fresh copy
  validation. That copy-path scenario passed in 3.27 seconds; the shim does
  not alter or excuse the strict production-UI gate.
- The final complete requested focused lifecycle selection passed 153 tests
  and reported only the same strict Slice 4.3 expected-success failure, with
  80 existing Qt chart deprecation warnings in 14.91 seconds.
- Default Slice 4.3 collection passed its fixture contract and skipped the
  three opt-in composed tests (`1 passed, 3 skipped`). The unaffected 96-well,
  comparison, and local Pi-contract selection passed 40 tests and skipped 3.
- All three retained reports remained report-v1 valid with classifications
  Windows 96-well `pass`, Windows 384x10 `fail`, and Pi 384x10 `fail`. Both
  tracked baselines loaded with distinct `offscreen_windows_sil` and
  `offscreen_pi_sil` identities.
- The first full-suite invocation encountered only the six known inaccessible
  cache directories during collection. Repeating with exactly those six paths
  ignored passed 3,586 tests, skipped 34, and reported 118 existing warnings
  in 417.41 seconds. This run preceded the final opt-in copy-path test; that
  test subsequently passed directly and is skipped by default.
- After the full run, all 312 restored `frames.jsonl`/`events.jsonl` files
  referenced by the 156-run gravimetric manifest remained present and
  nonempty. The two restored files in
  `run_20260408_104206_ffe2616e` also remained nonempty.

Disposition, risks, and rollback:

- Slice 4.3 remains `in_progress`.
  `experiment_editor_post_start_lock_v1` remains `planned` and outside the
  lifecycle suite. `experiment.active_edit_lock` remains `planned`,
  `experiment.editable_copy` remains `partial`, and
  `experiment.prepared_rename_refinalize` remains `partial`.
- The failure is a production UI-policy defect around
  `WellPlateWidget.open_experiment_designer ->
  ExperimentDesignDialog.prepare_progress_policy_for_current_design ->
  _refresh_all_lock_states -> _apply_progress_edit_lock_state`: the existing
  policy protects printed-progress designs but does not surface the already
  durable active-plan lock at zero progress.
- Rollback removes the Slice 4.3 fixture, actions, runner/registry/manifest
  entries, tests, and this documentation while preserving verified Slices
  0-4.2. No production, application-data, firmware, protocol, hardware,
  baseline, performance, or Pi rollback is required.

MVC defect resolution record (2026-07-27):

- Corrected the effective `ExperimentDesignDialog` lock-state path in
  `FreeRTOS-interface/View.py`. The editor now layers the authoritative
  execution lock after uploaded/manual and printed-progress restrictions and
  before the gripper interlock.
- A locked active runtime disables the name, design, reagent, optimization,
  auto-update, Save, and Finish surfaces; keeps New Experiment, Load Design,
  and `Create Editable Copy...` available; and displays actionable read-only
  guidance. The gripper interlock remains highest precedence.
- The Finish handler now rejects an indirectly invoked Finish for an
  already-active locked runtime before the authoritative activation path.
  An inactive persisted `ACTIVE` execution remains read-only while retaining
  an eligible `Activate Execution` path.
- The default edit-state reset restores the name, duplicate, auto-update, and
  reagent controls after a fresh editable copy loads. The test-only lock shim
  was removed before final verification.
- Focused production editor tests passed 39 tests. The promoted manifest and
  strict Slice 4.3 selection passed 62 tests with 20 existing Qt chart
  deprecation warnings. The complete focused lifecycle portfolio passed 159
  tests with 70 existing warnings in 13.43 seconds.
- A direct CLI execution classified `pass` in 2,643.204 ms with all nine
  assertions passing, no dialogs or errors, and ten nonempty readable
  screenshots:
  `verification_reports/virtual_workflows/experiment_editor_post_start_lock_v1/20260727T054314253824Z_d8d20769e757/report.json`.
  The source remained byte-identical at revision 2 `ACTIVE`; the editable copy
  finalized as a distinct revision-1 `PREPARED` execution with a different
  plan ID.
- Default collection passed the fixture contract and skipped the two opt-in
  composed tests (`1 passed, 2 skipped`). The unaffected 96-well,
  comparison, and local Pi-contract selection passed 40 tests and skipped 3.
- All three retained reports remained report-v1 valid with classifications
  Windows 96-well `pass`, Windows 384x10 `fail`, and Pi 384x10 `fail`. Both
  tracked baselines loaded with distinct `offscreen_windows_sil` and
  `offscreen_pi_sil` identities.
- With exactly the six known inaccessible execution-cache directories
  ignored, the full default Python suite passed 3,592 tests, skipped 34, and
  reported 118 existing warnings in 417.96 seconds.
- After the full run, all 312 restored `frames.jsonl`/`events.jsonl` files
  referenced by the 156-run gravimetric manifest remained present and
  nonempty. The restored `run_20260408_104206_ffe2616e` files were also
  nonempty (167,458-byte events and 45,968-byte frames).
- `experiment_editor_post_start_lock_v1` is now active in the lifecycle suite.
  `experiment.active_edit_lock`, `experiment.editable_copy`, and
  `experiment.prepared_rename_refinalize` are `covered`, with a two-day
  evidence age.
- No simulated-machine connection, print command, remote Pi operation, stress
  workload, performance collection, baseline regeneration, firmware/protocol
  change, or hardware access occurred.

Final disposition, risks, and rollback:

- Slice 4.3 is `verified`. The initial failed report remains retained as
  regression evidence; the passing report above is the promotion evidence.
- The lock deliberately keys off the existing authoritative model APIs and
  does not change execution-plan, persistence, simulator, or copy semantics.
- Rollback reverts the effective editor lock layer and focused tests, removes
  the Slice 4.3 manifest promotion, and returns the scenario/capabilities to
  their pre-fix planned/partial states. The Slice 4.3 framework and retained
  defect evidence remain. No application-data, firmware, protocol, hardware,
  baseline, performance, or Pi rollback is required.

Next permitted action:

- Slice 4.5, `authoritative_reload_resume_24_v1`. Keep refill-required resume
  deferred while volume tracking is disabled, and keep performance
  remediation, firmware, protocol, Pi, and hardware behavior out of that
  milestone.

#### Slice 4.4: Print-array soft stop and resume

Status: `verified`

Call path:

`QTest Start Print Array -> Controller.print_array -> simulated lookahead -> queued QTest Stop After Well -> Controller.request_array_soft_stop -> pause watermark -> confirmed clear/discard/park -> resume_ready -> paused validation/quiescence -> QTest Resume Print -> terminal completion`

Implementation:

- Added strict schema-v3 fixture `print_array_soft_stop_resume_24_v1` for
  shallow-384 A1-A24, one unique virtual stock/head, lookahead 2, 20 Hz, the
  completion-6 request boundary, at most two catch-up completions, and a
  250 ms quiescence observation.
- Added a separate reusable print lifecycle action set. The soft-stop action
  arms after the real UI starts, listens to real well-state notifications,
  queues a QTest click at exactly completion 6, and requires `Stop Pending`,
  `stop_requested`, and a positive barrier. Paused validation and quiescence
  are explicit actions; existing uninterrupted action IDs remain unchanged.
- Extended the existing print scenario with an explicit soft-stop/resume
  strategy while retaining common application construction, instrumentation,
  teardown, and report assembly. The uninterrupted 24-, 96-, and 384x10
  drivers and their legacy persistence formulas remain unchanged.
- Instrumentation now records confirmed watermark/clear evidence and
  discard batches. Terminal reconciliation partitions every begin occurrence
  into completion or confirmed discard, proves discarded stock/well work is
  reissued, and requires 24 exact progress writes and terminal completions.
  Deterministic stock/well intent IDs may be reused for the reissue; occurrence
  counters preserve the exactly-once proof.
- Added report-v1 evidence beneath
  `metrics.persistence.values.soft_stop_resume`, ten assertion results, and
  the six `ready`, `printing`, `stop_requested`, `stopped`, `resumed`, and
  `completed` screenshots. Responsiveness and resources remain diagnostic
  with `not_applicable` status.
- Appended the registry entry without changing the legacy order/default,
  activated it in the lifecycle suite after the composed pass, and marked
  `execution.soft_stop_resume` covered with a two-day evidence age. Pi
  evidence, injected stalls, repetition/report sets, and baseline creation
  remain rejected.
- Added exact fixture, action/deadline/quiescence, registry/manifest/CLI,
  composed-success, and retained-failure tests. No production MVC, simulator,
  firmware, protocol, performance, baseline, Pi, or hardware behavior changed.

Verification record (2026-07-27):

- Started at commit `64363f4e86a0baf07b35037db49d79085f8e95f2`
  with a clean tracked worktree. `.worktrees/` and the six pre-existing
  inaccessible execution-cache directories remained untouched.
- The pre-edit relevant baseline passed 233 tests with 10 existing Qt chart
  deprecation warnings in 10.04 seconds.
- The final strict direct scenario classified `pass` in 5,977.893 ms with all
  ten declared assertions passing:
  `verification_reports/virtual_workflows/print_array_soft_stop_resume_24_v1/20260727T063617161281Z_64363f4e86a0/report.json`.
  The click occurred at completion 6; one catch-up completion finished the
  watermark well; one lookahead intent was discarded, later reissued, and
  completed; and all 24 stock/well targets finished exactly once.
- The stopped bundle retained the original `ACTIVE` plan ID, a paused
  zero-intent checkpoint, valid authoritative inspection, confirmed
  watermark/clear, `ready_to_resume`, an empty simulator queue, and unchanged
  completion/progress counts throughout the 250 ms quiescence window.
- Resume was initiated through the real UI and ended in a valid `COMPLETED`
  plan. The run recorded 24 cached progress writes and 75 resume writes:
  25 begins, 25 sequence attachments, 24 completions, and one discard batch.
- The focused lifecycle module, including the retained synthetic paused-gate
  failure, passed three tests with 20 existing warnings in 8.72 seconds.
- The complete requested focused lifecycle selection passed 257 tests with 90
  existing Qt chart deprecation warnings in 21.08 seconds. Default collection
  passed the schema-v3 fixture contract and skipped the two opt-in composed
  tests (`1 passed, 2 skipped`).
- The real 96-well regression, comparison, and local Pi-contract selection
  passed 43 tests with 30 existing warnings in 12.31 seconds. No remote Pi
  operation was launched.
- The retained Windows 96-well report remained report-v1 valid with
  classification `pass`; the retained Windows and Pi 384x10 reports remained
  schema-valid with their existing `fail` classifications. Both tracked
  baseline summaries loaded with distinct `offscreen_windows_sil` and
  `offscreen_pi_sil` identities.
- With exactly the six known inaccessible execution-cache directories
  ignored, the full default Python suite passed 3,605 tests, skipped 36, and
  reported 118 existing warnings in 413.53 seconds.
- `git diff --check` passed. The only untracked paths outside this slice remain
  `.worktrees/` and the six pre-existing cache directories; all remained
  untouched. No zero-byte `frames.jsonl` or `events.jsonl` files were found
  under the restored experiments root after the full run.

Final disposition, risks, and rollback:

- Slice 4.4 is `verified`; the scenario is active in `lifecycle`, all ten
  declared assertions pass, and `execution.soft_stop_resume` is `covered`.
- The evidence is application-facing SIL only. It does not prove firmware
  pause/clear acknowledgements, physical parking, pressure behavior, or
  droplet delivery.
- Rollback removes the schema-v3 fixture, lifecycle actions/strategy,
  instrumentation/report additions, tests, registry/manifest promotion, and
  documentation while preserving verified Slices 0-4.3. No application-data,
  production, firmware, protocol, hardware, baseline, performance, or Pi
  rollback is required.

#### Slice 4.5: Authoritative reload and resume

Status: `verified`

Call path:

`QTest Start Print Array -> real soft stop -> paused authoritative bundle -> first application-session teardown -> fresh simulation dependencies and MVC composition -> Experiment Editor -> Load Design -> QFileDialog -> ExperimentModel.load_experiment -> Activate Execution -> Model.load_authoritative_execution_runtime -> resume_ready -> QTest Resume Print`

Starting state:

- HEAD remains `64363f4e86a0baf07b35037db49d79085f8e95f2`; the
  verified Slice 4.4 changes are present as the uncommitted prerequisite.
- The pre-edit focused selection passed 262 tests with 90 existing Qt chart
  deprecation warnings in 21.36 seconds.
- Slice 4.4 remains verified and unchanged. No production, simulator,
  firmware, protocol, baseline, Pi, performance, or hardware behavior was
  modified for this slice.

Implemented verification framework:

- Added strict schema-v3 fixture `authoritative_reload_resume_24_v1` for
  A1-A24, one unique virtual stock/head, completion-6 soft stop, at most two
  catch-up completions, 250 ms quiescence, and two application sessions.
- Added session-attributed actions, a reusable intermediate application
  cleanup primitive, and real modal editor folder-load/activation automation.
  The parent report and one 60-second deadline survive the first application
  teardown.
- The first session uses the verified Slice 4.4 start/stop path, freezes the
  complete authoritative inventory, and passes every prefixed cleanup phase
  without changing an authoritative file.
- The second session uses fresh simulation dependencies and a new
  Model/Controller/MainWindow/SimulatedMachine composition inside the same
  process-wide `QApplication`. It selects the persisted folder through the
  real `QFileDialog`; no direct activation handler or test-built runtime is
  used.
- Added additive report-v1 session attribution and
  `metrics.persistence.values.authoritative_reload_resume`, strict assertion
  results, failure screenshot retention, registry/CLI coverage, and a planned
  manifest scenario. The active lifecycle suite and capability were not
  promoted.

Strict scenario result and defect evidence:

- Session 1 passes the real soft-stop boundary at completion 6 with bounded
  catch-up, a valid `ACTIVE` plan, paused zero-intent checkpoint,
  `ready_to_resume`, an empty simulator queue, and quiescent progress.
- The frozen disk design remains byte-identical through teardown and its hash
  matches the execution plan. Independent authoritative inspection remains
  valid and `ready_to_resume`.
- Session 2 reaches the real editor load, but the editor-loaded in-memory
  `ExperimentModel.to_dict()` hash differs from the disk design and plan hash.
  Eligibility is `blocked`, `Activate Execution` is disabled, and the editor
  reports that the design does not match the execution-plan hash.
- The run stops at that boundary and retains both session identities, the
  passing first-session cleanup, disk/model/plan hashes, exact status text,
  failed action, traceback, cleanup, and `session_2_load_failed.png`.
  Downstream activation/resume assertions are `incomplete`.
- The retained direct report is:
  `verification_reports/virtual_workflows/authoritative_reload_resume_24_v1/20260727T071337559090Z_64363f4e86a0/report.json`.
  It is report-v1 valid, classifies `fail` in 4,225.156 ms, and its readable
  editor screenshot visibly shows the disabled activation state and hash
  mismatch guidance.
- The complete focused lifecycle selection passed 273 tests with 110 existing
  Qt chart deprecation warnings in 24.95 seconds. Default collection passed
  the strict fixture contract and skipped the opt-in composed scenario
  (`1 passed, 1 skipped`).
- The 96-well/comparison/local Pi-contract selection passed 40 tests and
  skipped 3 remote-only cases. All three retained compatibility reports, the
  new failure report, and both tracked baselines validate.
- The full default Python suite passed 3,615 tests and skipped 37 with 118
  existing warnings in 417.97 seconds after ignoring only the six known
  inaccessible cache directories.

MVC defect correction and verified rerun:

- The defect correction started from committed HEAD
  `0a5e46b636a5895972eb1d922e12d867fab81fc7`. The retained failure above
  remains the discovery evidence.
- Root cause was an ownership error in `ExperimentModel.from_dict`: assigning
  the parsed `metadata` mapping directly allowed
  `_ensure_well_selection_metadata` to add a default to the same payload that
  `load_experiment` subsequently passed to authoritative hash inspection.
  The persisted file and execution plan matched, but inspection saw the
  mutated in-memory payload.
- `from_dict` now deep-copies persisted metadata before normalization. Focused
  regressions prove caller-owned JSON remains unchanged, the model still
  receives normalized defaults, and a minimal authoritative design without
  `well_selection` remains valid and activatable without any file rewrite.
- The unchanged real editor load now reports `ready_to_resume`, leaves
  authoritative files byte-identical, enables `Activate Execution`, and
  reconstructs the exact seven-completion partial runtime.
- Completing the previously unreachable two-session evidence path also
  restored its intended queue-drained click precondition, session-attributed
  lifecycle merge, per-simulator command-sequence monotonicity, combined
  pass/terminal accounting, and conditional accounting for an activation
  checkpoint rewrite. No functional, persistence, or no-replay invariant was
  weakened.
- The passing direct report is:
  `verification_reports/virtual_workflows/authoritative_reload_resume_24_v1/20260727T074222212574Z_0a5e46b636a5/report.json`.
  It is report-v1 valid, classifies `pass` in 7,101.735 ms, completes all 24
  stock/well pairs exactly once, retains the original plan identity, passes
  all 12 assertions and both cleanup sets, and contains all eight required
  screenshots.
- The complete focused lifecycle selection passed 275 tests with 110 existing
  Qt chart deprecation warnings in 27.85 seconds. Default collection passed
  the fixture contract and skipped the opt-in composed scenario
  (`1 passed, 1 skipped`).
- The 96-well/comparison/local Pi-contract selection passed 40 tests and
  skipped 3 remote-only cases. The original failure report, new passing
  report, three retained compatibility reports, and both tracked baselines
  validate.
- The full default Python suite passed 3,617 tests and skipped 37 with 118
  existing warnings in 416.11 seconds after ignoring only the six known
  inaccessible cache directories.

Disposition, risk, and rollback:

- Slice 4.5 is `verified`;
  `authoritative_reload_resume_24_v1` is active in `lifecycle`, all 12
  declared assertions pass, and `execution.authoritative_reload_resume` is
  `covered` with a two-day evidence age.
- The evidence proves a fresh MVC/simulator composition inside one
  process-wide `QApplication`. It does not prove an operating-system restart,
  firmware behavior, physical transport recovery, or droplet delivery.
- Rollback reverts the metadata-ownership correction, its focused regression
  tests, evidence-path completion, and manifest/documentation promotion. The
  retained initial failure remains available. No application-data, firmware,
  protocol, hardware, baseline, performance, or Pi rollback is required.

Next permitted action:

- Slice 4.6, `print_array_multi_stock_24x2_v1`.

#### Slice 4.6: Multi-stock head exchange

Status: `verified`

Call path:

`strict A1-A24 by two-stock fixture -> simulation composition -> virtual head 1 stage -> real UI Start Print Array -> pass-1 completions -> idle/drained ACTIVE boundary -> return head 1 and stage head 2 -> apply distinct settings -> second real UI Start Print Array -> terminal authoritative validation`

Starting state:

- HEAD was `74496a6eb634ce7295c1def7304cc350fb0c8bcd`.
- The tracked worktree was clean. `.worktrees/` and the six pre-existing
  inaccessible execution-cache directories remained untouched.
- The pre-edit reduced two-stock baseline passed 3 selected tests with 10
  existing Qt chart deprecation warnings in 4.58 seconds.
- Slice 4.5 remained verified. No production MVC, simulator, firmware,
  protocol, baseline, Pi, performance, or hardware behavior was changed.

Implemented verification framework:

- Added strict schema-v3 fixture `print_array_multi_stock_24x2_v1` with
  shallow-384 A1-A24, two distinct stocks and heads, distinct pulse-width and
  pressure settings, lookahead 2, 20 Hz, two passes, and 48 expected
  stock/well completions.
- Promoted the former test-created reduction of the 384x10 fixture into a
  named `multi_stock_head_exchange` strategy while preserving the
  uninterrupted 24-, 96-, and 384x10 strategies.
- Extended reusable `head.stage_virtual` evidence with pre/post queue state,
  previous and new stock/head identities, returned-head evidence, origin and
  staging slots, and requested/effective settings. Added
  `validation.stock_pass_boundary` for the durable idle boundary after each
  pass.
- The first stage proves an initially empty gripper. The between-pass stage
  proves head 1 was returned before head 2 was loaded, and both stages require
  an idle Controller with a drained simulator queue.
- Added `metrics.persistence.values.multi_stock_head_exchange`, 11 explicit
  assertion decisions, bounded simulator/report history evidence, failure
  retention, and six readable screenshots. Responsiveness, resources, and
  performance are `not_applicable`.
- Registered the new local-only lifecycle ID after Slice 4.5. Pi evidence,
  injected stalls, repetition/report sets, and baseline creation remain
  rejected. The 96-well default and all legacy order/contract anchors remain
  unchanged.
- Replaced the reduced stress-derived composed test with a dedicated lifecycle
  module. The actual 384x10 fixture, scheduled stress identity, comparison,
  and Pi contracts remain unchanged.
- Activated the scenario in `lifecycle` and advanced
  `execution.multi_stock_head_exchange` from `partial` to `covered` with a
  two-day evidence age.

Verification result:

- The direct report is
  `verification_reports/virtual_workflows/print_array_multi_stock_24x2_v1/20260727T081543770968Z_74496a6eb634/report.json`.
  It is report-v1 valid, classifies `pass` in 8,406.974 ms, and passes all 11
  assertions.
- Pass 1 records 24 exact completions and leaves the original plan `ACTIVE`.
  Pass 2 uses the second stock/head/settings, reaches 48 exact completions,
  and leaves the same plan `COMPLETED`.
- All 48 intent begins, attachments, completions, and progress writes
  reconcile with zero discard batches, ambiguity, duplication, or outstanding
  intents. Both head stages are idle/drained and the second records the
  returned first head.
- The six required screenshots are nonempty and readable with the configured
  Segoe UI font. Manual inspection of `stock_2_staged.png` shows the second
  stock loaded, first pass complete, 1500 us pulse width, 1.50 psi target, and
  the simulation-only banner.
- Default collection validates the fixture and skips the two opt-in composed
  tests (`1 passed, 2 skipped`).
- All 287 focused nodes passed using module-isolated Qt processes: 268
  framework/controller/action/manifest/contract/384x10 nodes passed in 4.76
  seconds, and all 19 composed lifecycle/system nodes passed in their
  respective modules. This avoids a Windows native Qt shutdown termination
  observed only when every composed UI scenario shares one long process; no
  scenario assertion failed.
- The 96-well/comparison/local Pi-contract selection passed 40 tests and
  skipped 3 remote-only cases. Four retained reports, including the new
  report, and both tracked baseline summaries validate.
- The full default Python suite passed 3,630 tests and skipped 38 with 118
  existing warnings in 443.23 seconds.

Disposition, risk, and rollback:

- Slice 4.6 is `verified`; `print_array_multi_stock_24x2_v1` is active in
  `lifecycle`, all declared assertions pass, and
  `execution.multi_stock_head_exchange` is `covered`.
- Evidence proves application behavior using the in-process simulator and
  virtual rack. It does not prove physical head handling, pressure response,
  firmware transport, or droplet delivery.
- Rollback removes the fixture, strategy-specific evidence/action, tests,
  registry/manifest promotion, and documentation while preserving verified
  Slices 0-4.5 and the existing 384x10 stress scenario. No application-data,
  production, firmware, protocol, hardware, baseline, performance, or Pi
  rollback is required.

#### Prepared-plan replacement follow-up

Status: `verified`

Call path:

`reopen untouched PREPARED design -> edit real editor controls -> Save or Finish -> MainWindow.complete_experiment_design -> Model.commit_prepared_experiment_design_from_editor -> staged design/plan generation -> authoritative validation -> atomic publish -> persisted reload`

This follow-up broadens the Slice 4.2 contract without adding another
scenario. The original name-only correction was insufficient: reagent or
general experiment edits changed the canonical design/runtime assignments
while the existing prepared plan remained in place, so finalization correctly
rejected the resulting mismatch.

Implementation and coverage:

- A valid revision-1 `PREPARED`, `ready_to_start` bundle with zero progress,
  no resume checkpoint, and no calibration/manual-refuel history remains
  editable, including after disk reload.
- Save and Finish share one transactional replacement path. It copies the
  source into a sibling staging directory, saves the edited design, creates a
  fresh prepared plan/progress/key bundle, archives the superseded design,
  plan, and immutable revision beneath
  `superseded_prepared_execution_plans/<plan-id>/`, validates the staged
  bundle, and publishes it by a rollback-protected directory swap.
- Any prevalidation, generation, validation, publish, or cleanup failure
  leaves the original authoritative directory byte-identical. Active,
  progressed, resumed, calibrated, invalid, or non-revision-1 executions
  remain read-only/fail-closed and continue to use the Slice 4.3 editable-copy
  boundary.
- Existing Slice 4.2 scenario
  `experiment_editor_prestart_rename_refinalize_v1` now changes the name,
  replicate count, selected wells, printed/final volumes, reagent targets,
  reagent mode, reagent dispense volume, fill mode, and fill dispense volume.
  It regenerates through the real editor and requires a fresh A1-A6 plan,
  changed runtime assignments, consistent key files, archived superseded
  artifacts, zero progress, and a `ready_to_start` reload.
- The same scenario remains the only registry/lifecycle entry. Capability
  `experiment.prepared_design_refinalize` is covered by its dedicated
  assertion, while `experiment.prepared_rename_refinalize` remains covered.

Verification record (2026-07-27):

- Starting HEAD was `ec0e2947c2503a7e566bdc72f903b07991118fb1`
  with a clean tracked worktree.
- The pre-edit focused model/editor baseline passed 66 tests.
- Focused production model/editor/authoritative tests passed 73 tests.
- Action, manifest, contract, and default editor-lifecycle selection passed
  118 tests and skipped four opt-in composed runs.
- The expanded real Slice 4.2 composed workflow passed in 2.94 seconds with
  all ten assertions, ten screenshots, and cleanup phases passing. Manual
  inspection of `prepared_design_edited.png` confirmed readable Segoe UI text
  and the intended replicate, well, volume, target, reagent-mode, and
  fill-mode edits.
- A direct CLI execution classified `pass` in 2,522.610 ms with all ten
  assertions:
  `verification_reports/virtual_workflows/experiment_editor_prestart_rename_refinalize_v1/20260727T092850340803Z_ec0e2947c250/report.json`.
- Module-isolated post-start lock, soft-stop/resume, authoritative
  reload/resume, and multi-stock lifecycle selections all passed. The
  96-well/comparison/local Pi-contract regression passed 43 tests with 30
  existing warnings.
- Four retained reports validated with classifications `pass`, `fail`, `fail`,
  and `pass` as expected. Both tracked baseline summaries loaded with distinct
  `offscreen_pi_sil` and `offscreen_windows_sil` identities.
- The full default Python suite passed 3,637 tests, skipped 38, and reported
  118 existing warnings in 444.53 seconds.
- No simulator, firmware, protocol, performance, baseline, Pi, or hardware
  behavior changed.

Risk and rollback:

- Replacement intentionally changes the plan identity because the prepared
  execution has not started. Superseded artifacts are retained for diagnosis;
  they are not active execution history.
- Rollback reverts the transactional prepared-commit method, Save/Finish
  handoff changes, expanded Slice 4.2 fixture/actions/assertions, manifest
  capability, tests, and this documentation. Existing verified Slices 0-4.6,
  started-execution locks, firmware, protocol, baselines, Pi behavior, and
  hardware state require no rollback.

#### Editor lifecycle clarity and direct editable-copy follow-up

Status: `verified`

Call paths:

`Experiment Editor -> ExperimentDesignDialog -> design-lock/runtime/plan-state classifier -> Finalize Design | Load Execution | Execution Loaded | Execution Locked`

`Create Editable Copy... -> current experiment_file_path + experiment_dir_path -> widened copy-name QInputDialog -> sibling destination -> ExperimentModel.duplicate_design_from -> staged validation/publish -> editable copy in the same dialog`

`volume-calibration start button -> PREPARED-plan confirmation -> existing mode preflight -> existing Controller/CalibrationManager -> selected calibration apply -> existing lock_execution_plan("calibration_started")`

Implementation and coverage:

- Editable drafts and `PREPARED` designs retain `Finalize Design` even when
  authoritative eligibility is `ready_to_start`. Locked inactive executions
  expose `Load Execution`; an active authoritative runtime shows disabled
  `Execution Loaded`; blocked and terminal executions show disabled
  `Execution Locked`.
- `Load Execution` retains the existing runtime-reconstruction handler and
  does not start or resume printing.
- A full-width banner is hidden while editable and gives distinct active,
  loadable-saved, and blocked/terminal guidance while preserving the lower
  transient status line. The gripper lock remains the highest-precedence
  control/status lock.
- `Create Editable Copy...` resolves only the current persisted design,
  rejects missing/inconsistent paths, empty or colliding names, existing
  destinations, and unwritable parents, and creates a fresh sibling through
  the existing transactional duplicate implementation. The source selector
  was removed. The name dialog is at least 640 px wide with a name field
  minimum of 480 px.
- The first top-level pressure-sweep, online stream-volume, droplet
  `Calibrate All`, or stream `Calibrate All` start while the authoritative
  plan remains `PREPARED` requires explicit `Start Calibration`; `Cancel` is
  the default and runs before mode preflight, controller callbacks, machine
  settings, or queue changes. The UI does not move or duplicate the durable
  model lock, which remains authoritative when a selected calibration is
  applied.
- Existing Slice 4.2, 4.3, and 4.5 scenario and action IDs remain unchanged.
  Their nested report-v1 evidence additively records lifecycle labels/banner,
  automatic copy source, name-dialog widths, and destination. Slice 4.3 now
  treats any source `QFileDialog` as an unexpected modal.

Verification record (2026-07-28):

- Starting HEAD was `73d0045c94d7` with a clean tracked worktree. The
  pre-edit editor/copy/calibration/action/authoritative baseline passed 96
  tests.
- Focused post-edit validation passed 114 tests, including lifecycle
  classification/banner, direct-current copy behavior and fresh-copy model
  semantics, calibration confirmation/cancellation, report actions, droplet
  imaging summary, and authoritative loading.
- The opt-in editor lifecycle selection passed 11 tests. Direct Slice 4.2,
  4.3, and 4.5 CLI runs classified `pass` with 10/10, 9/9, and the complete
  24/24 resume workflow respectively.
- Manual inspection of retained `locked_editor_opened.png` and
  `session_2_loaded.png` confirmed readable full-width banners plus visible
  `Execution Loaded` and `Load Execution` actions.
- The full default suite completed with 3,654 passed and 38 skipped. Its only
  failure was a test-only `__new__` dialog stub exposed by an over-broad New
  Experiment refresh. The refresh was narrowed to the two new lifecycle/copy
  states, and that failure plus all affected focused suites then passed 73
  tests. A clean full-suite rerun reached 21% without failures before an
  external interruption; this record does not claim a complete post-fix full
  run.
- No Model execution semantics, Controller, simulator, firmware, protocol,
  hardware, performance, baseline, or Pi behavior changed.

Risk and rollback:

- The visible labels and modal sequence are UI contracts; automation that
  matched `Finish` or `Activate Execution` must use the new visible text while
  retaining internal action IDs.
- Copy publication remains staged and transactional. Cancel or any
  path/name/filesystem failure leaves the source unchanged.
- Rollback reverts this UI/test/documentation follow-up. It requires no
  execution data, simulator, firmware, protocol, hardware, performance,
  baseline, or Pi rollback.

Next permitted action:

- Slice 4.7, `print_array_disconnect_mid_array_24_v1`.

### Slice 5: Suites and scheduling contracts

Goal:

- add suite/capability CLI selection;
- add pytest opt-in controls;
- make scheduled Windows commands noninteractive and stable;
- extend Pi wrapper selection without changing Pi safety behavior.

Likely files:

- `tools/run_virtual_workflow.py`;
- scenario registry and manifest;
- `pytest.ini`;
- `tests/conftest.py`;
- CLI/comparison/system tests;
- `scripts/pi/run_virtual_workflow_sil.sh`;
- `tools/run_pi_virtual_workflow.ps1`;
- Pi lane tests;
- `README.md`;
- this document.

Gate:

- standard, lifecycle, host-regression, and host-stress selection tests pass;
- dry-run Pi orchestration names the correct suite/scenario;
- preflight, proof, bundle, extraction, and cleanup tests remain fail closed;
- no scheduler or wrapper can select physical hardware mode;
- shell/PowerShell validation and full Python suite pass.

### Slice 6: Coverage summary and operational handoff

Goal:

- add assertion-backed capability results to reports;
- add manifest/report coverage and freshness summary;
- document scheduler ownership and exact commands;
- run and inspect one cycle of every available non-Pi lane;
- run Pi lanes only through separately authorized existing remote operations.

Likely files:

- registry/manifest/report integration;
- coverage summary tool/tests;
- report-schema documentation;
- `README.md`;
- this document;
- operational scheduler documentation, if a scheduler is selected.

Gate:

- manifest and latest reports produce a deterministic coverage summary;
- missing, stale, failed, partial, and deferred evidence is distinguished;
- no capability is covered without all required assertions;
- scheduled evidence is retrievable and inspectable;
- final focused and full validation pass;
- final diff, ignore, artifact, and worktree checks pass.

## Expected File Boundary

Likely new files:

- `docs/sil_verification_framework_hardening_plan.md`;
- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/registry.py`;
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`;
- a tracked 24-well smoke fixture;
- bounded tracked lifecycle fixtures where needed;
- manifest, registry, action, smoke, editor-lifecycle, and execution-lifecycle
  tests.

Likely existing files:

- `tools/virtual_workflows/scenarios.py`;
- `tools/run_virtual_workflow.py`;
- `tools/virtual_workflows/report.py` only if nested validation needs tightening;
- `tests/system/test_virtual_print_array_workflow.py`;
- `tests/system/test_virtual_print_array_384x10_workflow.py`;
- `tests/system/test_pi_virtual_workflow_lane.py`;
- `tests/performance/test_virtual_workflow_comparison.py`;
- `tests/conftest.py`;
- `pytest.ini`;
- `scripts/pi/run_virtual_workflow_sil.sh`;
- `tools/run_pi_virtual_workflow.ps1`;
- `README.md`;
- `docs/virtual_workflow_report_schema.md`;
- `docs/virtual_workflow_verification_plan.md` for cross-link/status only.

Files excluded from this effort:

- production MVC files under `FreeRTOS-interface/`;
- `Machine_FreeRTOS` and serial/protocol modules;
- firmware;
- production persistence codecs/order/guards;
- production motion, pressure, calibration, or timing behavior.

## Validation Commands

Commands below are targets for the completed framework. Exact node IDs may be
adjusted when files are created, but each slice must record the actual commands
used.

Focused framework:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_actions.py `
  tests\system\test_virtual_workflow_smoke.py
```

Lifecycle:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_lifecycle.py
```

Existing workflow and comparison compatibility:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-regression `
  tests\system\test_virtual_print_array_workflow.py `
  tests\system\test_virtual_print_array_384x10_workflow.py `
  tests\performance\test_virtual_workflow_comparison.py `
  tests\system\test_pi_virtual_workflow_lane.py
```

Standard smoke through the CLI:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite standard `
  --speed-multiplier 1000 `
  --timeout-seconds 60 `
  --output-root verification_reports\virtual_workflows
```

Lifecycle suite:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle `
  --speed-multiplier 1000 `
  --output-root verification_reports\virtual_workflows
```

Existing Windows stress:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_stress `
  --emit-report-set `
  --host-label windows-sil-384x10-v1 `
  --warmup-runs 0 `
  --measured-runs 1 `
  --timeout-seconds 1800 `
  --output-root verification_reports\virtual_workflows
```

Full Python regression:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Pi commands must continue to use `tools/run_pi_virtual_workflow.ps1` and
`scripts/pi/run_virtual_workflow_sil.sh` with their existing clean-commit,
preflight, proof, sandbox, trace, bundle, hash, extraction, and cleanup gates.
This document does not authorize a Pi run by itself.

## Artifact Review Checklist

For every composed scenario:

- scenario, workload, suite, tier, and manifest versions are correct;
- source commit and dirty-worktree state are visible;
- simulation mode and disabled hardware interfaces are explicit;
- editor scenarios record the draft, prepared, locked, or terminal state at
  each transition;
- editor refinalization scenarios validate folder/metadata identity and
  design/plan/progress/resume/revision consistency after close/reload;
- expected action and assertion IDs appear in the report;
- capability results agree with assertion results;
- completion, intent, durable-operation, and queue counts match the workload;
- lifecycle milestones occur in the required order;
- no unexpected dialogs or errors were suppressed;
- screenshots are nonempty and show the simulation banner;
- events and stacks are bounded but sufficient for diagnosis;
- failure traceback exists only when expected;
- terminal/recovery validation reflects the scenario's expected outcome;
- timers, observers, wrappers, event filters, and simulator state are clean;
- report schema validation passes;
- generated evidence remains beneath the ignored output root.

For report sets and scheduled lanes:

- every referenced report hash and path validates;
- warm-up and measured boundaries are correct;
- platform/environment compatibility is correct;
- traced Pi runs are excluded from performance sets;
- copied Windows and Pi reports are not compared as same-platform evidence;
- failed or incomplete runs remain visible;
- coverage freshness reflects the inspected report timestamps.

## Risks And Mitigations

### Scenario abstraction duplicates business logic

Risk:

An overly generic action layer could reproduce Controller decisions and allow
tests to pass while the application path is broken.

Mitigation:

Actions perform one UI/Controller/simulator operation and wait for observable
state. Business decisions and authoritative writes remain inside the
application.

### False capability coverage

Risk:

A manifest can create the appearance of coverage without executable proof.

Mitigation:

Covered capabilities require active scenarios, required assertion IDs, and
passing report assertion results. Manifest/report joins fail on missing or
incomplete evidence.

### Fixture and scenario explosion

Risk:

Many nearly identical fixtures and scenarios become expensive to understand
and maintain.

Mitigation:

Keep a small number of tracked reference fixtures, use bounded typed builders
for test variations, and add a scenario only for a meaningful risk or
historical failure.

### Qt and timing flakiness

Risk:

Fixed sleeps, modal dialogs, or host load make lifecycle scenarios unreliable.

Mitigation:

Use predicate/signal waits with a scenario deadline, allowlist dialogs, keep
functional assertions independent of performance thresholds, and reserve
performance decisions for scheduled lanes.

### Compatibility drift

Risk:

Extraction changes report identity, baseline compatibility, Pi linkage, or
failure artifacts.

Mitigation:

Retain the public compatibility adapter, add explicit compatibility tests, and
compare existing report/report-set validation before enabling new suites.

### Simulator drift

Risk:

In-process simulator behavior is treated as proof of serial, MCU, or physical
behavior.

Mitigation:

Manifest capabilities identify required verification layers and limitations.
Disconnect and pause scenarios claim only in-process SIL behavior. Protocol and
physical capabilities remain deferred.

### Hardware-isolation regression

Risk:

New actions accidentally import or construct physical-device code.

Mitigation:

Preserve source/import traps, sentinel-port enforcement, explicit simulation
dependencies, Pi private-device proof, and report safety fields.

### Scheduled lane silently stops running

Risk:

Tracked coverage remains green even though scheduled evidence is old.

Mitigation:

Manifest freshness policy and coverage summary classify missing or stale
evidence explicitly. Generated runs never update tracked status automatically.

### Stress findings restart optimization implicitly

Risk:

A 384x10 warning or failure expands this effort into production performance
work.

Mitigation:

Retain the evidence and open a separate issue/plan. Do not change production
behavior under this plan.

## Rollback Plan

Use one milestone per commit. Roll back by reverting the affected framework
milestone:

- registry/manifest rollback restores hard-coded existing scenario selection;
- action extraction rollback restores the existing monolithic runner;
- smoke rollback returns default composed coverage to its prior state;
- an unstable lifecycle scenario can be removed while its capability returns to
  `planned` or `partial`;
- suite/marker rollback preserves direct scenario CLI invocation;
- coverage-summary rollback preserves canonical scenario reports;
- Pi selection changes can be reverted while retaining the existing 96/384x10
  wrapper behavior and safety proof.

Existing 96-well and 384x10 fixtures, reports, comparison tooling, and Pi
evidence contracts remain compatibility anchors throughout. There is no
application-data migration, firmware rollback, hardware rollback, or protocol
rollback.

## Definition Of Done

The effort is complete when:

- the standard Python lane runs exactly one fast composed real-UI SIL smoke
  scenario and no stress or remote Pi workflow;
- smoke, lifecycle, regression, stress, and Pi tiers are distinct and
  independently selectable;
- every active lifecycle scenario is timeout bounded, independently runnable,
  and produces inspectable success/failure artifacts;
- editor creation/finalization, prepared rename/refinalization, and post-start
  edit-lock/editable-copy scenarios have assertion-backed coverage;
- prepared executions can follow the documented safe edit/refinalize policy
  while executions with calibration or print history remain protected;
- refill-required pause/resume remains explicitly deferred while volume
  tracking is disabled;
- existing 96-well scenario and baseline comparison compatibility is preserved;
- existing 384x10 execution remains explicit and scheduled rather than default;
- Pi preflight, proof, sandbox, trace, bundle, extraction, hash, and cleanup
  behavior remains fail closed;
- reusable actions drive existing application interfaces without duplicating
  production business logic;
- the tracked manifest validates with no duplicate, dangling, or unsupported
  claims;
- every covered capability has active assertion-backed report evidence;
- coverage summaries distinguish covered, partial, planned, deferred, failed,
  incomplete, and stale evidence;
- focused framework, lifecycle, compatibility, Pi contract, and full Python
  tests pass;
- representative reports, summaries, screenshots, timelines, stacks, bundles,
  and coverage output are manually inspected;
- documentation contains exact standard, targeted, scheduled, and
  troubleshooting commands;
- final diff, ignore, artifact, and worktree checks pass;
- no production MVC, machine, firmware, protocol, motion, pressure, timing, or
  persistence behavior was changed by a framework slice; separately scoped
  MVC defect corrections required by a strict lifecycle gate are recorded
  independently with their own verification and rollback.

## Current Next Action

Create the concrete implementation plan for Slice 4.7,
`print_array_disconnect_mid_array_24_v1`. Preserve the verified Slice 4.6
multi-stock head-exchange scenario and do not combine the next slice with
refill resume, performance, firmware, protocol, Pi, or hardware changes.
