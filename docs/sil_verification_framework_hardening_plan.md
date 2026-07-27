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

Initial capability IDs:

| Capability ID | Initial status | Primary evidence |
| --- | --- | --- |
| `sil.hardware_isolation.host` | `covered` | Safe construction, source/import guards, smoke |
| `sil.hardware_isolation.pi` | `covered` | Pi preflight, private `/dev`, trace proof |
| `ui.real_app_construction` | `covered` | Standard smoke |
| `execution.array_happy_path` | `covered` | Standard smoke and 96 regression |
| `execution.lookahead_no_starvation` | `covered` | Standard smoke, 96, multi-stock |
| `execution.intent_durability` | `covered` | Standard smoke, 96, multi-stock |
| `execution.terminal_bundle` | `covered` | Standard smoke, 96, multi-stock |
| `experiment.editor_create_finalize` | `planned` | Editor create/finalize lifecycle scenario |
| `experiment.prepared_reopen` | `planned` | Editor create/finalize and pre-start rename scenarios |
| `experiment.prepared_rename_refinalize` | `planned` | Direct pre-start rename regression scenario |
| `experiment.design_plan_consistency` | `planned` | Editor finalization/refinalization authoritative validation |
| `experiment.active_edit_lock` | `planned` | Post-start editor lock scenario |
| `experiment.editable_copy` | `partial` | Existing unit coverage; composed post-start scenario pending |
| `execution.soft_stop_resume` | `planned` | Soft-stop lifecycle scenario |
| `execution.refill_resume` | `deferred` | Volume tracking is disabled; prerequisite not met |
| `execution.authoritative_reload_resume` | `planned` | Reload lifecycle scenario |
| `execution.disconnect_fail_closed` | `planned` | Disconnect lifecycle scenario |
| `execution.multi_stock_head_exchange` | `partial` | Existing reduced test; named scenario pending |
| `ui.event_loop_stall_detection` | `covered` | Injected-stall probe test |
| `ui.sustained_responsiveness.windows` | `partial` | Scheduled 96/384x10 evidence |
| `ui.sustained_responsiveness.pi` | `partial` | Scheduled Pi evidence |
| `resources.sustained_growth.windows` | `partial` | Scheduled 384x10 evidence |
| `resources.sustained_growth.pi` | `partial` | Scheduled Pi 384x10 evidence |
| `protocol.serial_lifecycle` | `deferred` | Future virtual MCU or HIL |
| `protocol.reset_mid_array` | `deferred` | Future virtual MCU or HIL |
| `hardware.motion_pressure_droplet` | `deferred` | HIL only |

The initial manifest must describe current truth. Do not mark planned lifecycle
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

Goal:

- extract reusable context, actions, waits, dialog handling, milestone capture,
  and teardown from the existing runner;
- retain compatibility adapter behavior.

Likely files:

- `tools/virtual_workflows/actions.py`;
- `tools/virtual_workflows/scenarios.py`;
- action tests;
- existing 96/384 system tests;
- report-schema documentation if nested evidence is added;
- this document.

Gate:

- action precondition, timeout, failure, and cleanup tests pass;
- existing 96-well focused scenario passes;
- reduced multi-stock scenario passes;
- report-v1, report-set, comparison, artifact, and safety assertions remain
  valid;
- source/import guards show no production machine or device construction.

### Slice 3: Standard smoke tier

Goal:

- add the 24-well workload and smoke scenario;
- make it the only default composed real-UI SIL run;
- preserve existing fixture contract tests.

Likely files:

- new 24-well fixture;
- scenario registry and manifest;
- `tests/system/test_virtual_workflow_smoke.py`;
- existing real-UI tests where framework checks move to the smaller workload;
- `pytest.ini`;
- `tests/conftest.py`;
- `README.md`;
- this document.

Gate:

- smoke completes within the target budget on the primary Windows development
  environment;
- all required functional/durability/UI/safety/artifact assertions pass;
- standard pytest selection does not include lifecycle, regression, stress, or
  remote Pi execution;
- full Python suite passes.

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
  persistence behavior was changed.

## Current Next Action

Begin Slice 2 only as a separately reviewed action/context-extraction
milestone. Preserve the public config/runner adapter, registered legacy IDs,
manifest identity, report-v1 envelope, comparison policy, fixture mappings,
failure artifacts, and Pi proof linkage. Do not combine the extraction with a
new smoke fixture, lifecycle scenario, suite selector, coverage summary,
performance remediation, or production behavior change.
