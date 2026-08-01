# Milestone 2 Cross-Layer State Recorder and Inspector Implementation Plan

Date: 2026-07-31

Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Prerequisite: Milestone 1 `complete`

Planning baseline: `ecc8cf7`

Status: `complete`

## Goal

Add simulation-owned, read-only observability around the real application MVC
stack. A retained interactive session must provide a bounded in-memory view,
a complete append-only JSONL event trace, explicit cross-layer snapshots, and
an optional visible inspector without changing application decisions or
authoritative experiment data.

This milestone is evidence infrastructure only. It does not add synthetic
calibration, manual-refuel simulation, workflow migration, failure injection,
firmware or protocol work, Pi operations, performance remediation, or any
physical-hardware behavior.

## Baseline And Decisions

Milestone 1 already provides:

- a contained `SimulationSession` and retained-root lifecycle;
- schema-v1 `session.json` metadata and one atomic-write attempt;
- simulator `state_changed`, `command_lifecycle_changed`, connection, error,
  and fault signals;
- Controller array/error/fault signals;
- Model, machine-model, rack, experiment, calibration, and refuel signals;
- a simulation-only control dock; and
- a point-in-time `SimulationSession.snapshot()` that currently records only
  the simulator dataclass into `session.json`.

Milestone 2 will use those existing seams. The planned implementation must
not monkey-patch Controller methods, replace application writers, poll
production devices, or add recorder calls to production business logic.

The existing private event logs beneath `tools/virtual_workflows/` remain
unchanged. They may consume the shared recorder in Milestone 6 or 7, but
migration is not part of Milestone 2.

## Call Paths

### Normal observed transition

```text
real UI or Simulator Control
  -> Controller
  -> Model and SimulatedMachine
  -> existing Qt state/lifecycle signals
  -> SimulationStateObserver
  -> StateProjectionBuilder
  -> StateRecorder
  -> artifacts/state/<application_session_id>/events.jsonl
  -> latest_snapshot.json
  -> recorder-backed State Inspector projection
```

The recorder observes the result of the normal operation. It never decides
whether an action is allowed and never writes a Model, Controller, simulator,
rack, experiment, calibration, refuel, or UI property.

### Explicit snapshot export

```text
Simulator Control "Export State Snapshot"
  -> SimulationSession.snapshot("manual_export")
  -> StateProjectionBuilder.capture(..., include_persistence=True)
  -> StateRecorder.record_snapshot(...)
  -> latest_snapshot.json plus one JSONL snapshot event
  -> session.json artifact pointer/summary update
```

### Teardown

```text
SimulationSession.close()
  -> record teardown_started and live pre-cleanup snapshot
  -> normal Controller simulator disconnect
  -> allow resulting disconnect/model signals to be recorded
  -> detach SimulationStateObserver idempotently
  -> dispose inspector and Simulator Control
  -> normal application component cleanup
  -> record cached cleanup_completed or cleanup_failed terminal event
  -> write terminal_snapshot.json and flush/close StateRecorder
  -> write terminal session.json metadata
  -> release lock and apply the existing root-retention policy
```

The terminal event may describe cleanup results from cached state, but it must
not inspect Qt or application objects after they have been closed.

## Scope

### In scope

- schema-v1 event and cross-layer snapshot contracts;
- pure bounded state projections;
- one recorder per application session;
- append-only JSONL with monotonic sequence numbers;
- command and optional action correlation;
- bounded in-memory retention with complete retained JSONL on a normal close;
- deterministic observer installation, queued reconciliation, and removal;
- recorder health/error evidence;
- explicit, terminal, and cleanup snapshots;
- a simulation-only read-only inspector backed only by recorder output;
- additive session metadata/artifact pointers;
- focused automated tests and a visible Windows gate.

### Out of scope

- generated calibration results or calibration application;
- simulated manual-refuel outcomes;
- typed journey actions or legacy scenario migration;
- allowlisted fault controls or failure campaigns;
- accepted report-v1 field changes or baseline changes;
- performance claims or 384x10/Pi stress work;
- production startup, physical ports, cameras, balances, firmware, GPIO,
  updater, qualification, protocol, motion, or pressure changes.

## Artifact Layout

Each application session writes beneath its already-contained session root:

```text
artifacts/
  state/
    <application_session_id>/
      events.jsonl
      latest_snapshot.json
      terminal_snapshot.json
```

Reopening a retained root creates a new application-session directory. It
must not append to or replace an earlier application's trace.

`session.json` remains `labcraft.sil_simulation_session` schema version 1.
Additive fields may record:

- recorder schema/version and health;
- application-session-relative event/snapshot paths;
- latest event sequence and counts;
- terminal flush/close result; and
- any recorder failure text.

Existing Milestone 1 roots without these optional fields remain valid.

Clean fresh sessions may still be deleted after a clean close. Retained and
failed sessions preserve recorder artifacts under the existing policy.

## Schema V1 Contracts

The schema reference will define two independent documents:

- `labcraft.sil_state_event`, version 1; and
- `labcraft.sil_state_snapshot`, version 1.

### Event envelope

Every JSONL line is one complete event object containing:

- `schema_id` and `schema_version`;
- `event_sequence`, starting at 1 per application session;
- `captured_at_utc` and process-monotonic `monotonic_ns`;
- `session_id` and `application_session_id`;
- `event_kind` and `source_layer`;
- `simulated_elapsed_ms` when available;
- `correlation` with optional `action_id`, `command_id`, and `snapshot_id`;
- bounded `before` and `after` changes when meaningful;
- a bounded source payload;
- truncation/drop evidence rather than silent omission; and
- recorder/configuration identity where generation or limits matter.

The sequence is assigned only by `StateRecorder`. Callers cannot provide or
reuse a sequence number.

### Canonical event kinds

The initial vocabulary is:

- `recorder_started`;
- `action_started` and `action_completed`;
- `simulator_connection_changed`;
- `simulator_command_lifecycle`;
- `simulator_state_changed`;
- `simulator_fault`;
- `controller_array_state_changed`;
- `controller_error` and `controller_transport_fault`;
- `model_machine_state_changed`;
- `model_experiment_loaded`;
- `rack_state_changed`;
- `calibration_state_changed`;
- `refuel_check_changed`;
- `projection_reconciled`;
- `snapshot_exported`;
- `teardown_started`;
- `cleanup_completed` or `cleanup_failed`; and
- `recorder_stopped`.

New event kinds require schema-documentation and focused-test updates. They do
not require a schema version change if they preserve the event envelope.

### Snapshot envelope

A snapshot contains the same identity/timestamp/correlation envelope plus one
bounded projection for each required layer. Each layer reports `available`,
its normalized state, and any observation error. An unavailable layer is
evidence; it is not filled with manufactured state.

Snapshots must contain summaries and stable identities, not arbitrary object
graphs, full image data, pressure-history arrays, or all per-well objects.

## Cross-Layer Projection

`StateProjectionBuilder` is a pure read-only adapter. It accepts the already
constructed session/components and returns JSON-safe values without emitting
signals or calling a mutation/repair method.

| Layer | V1 projection |
| --- | --- |
| Session | session/application IDs, source/runtime identity, seed, speed multiplier, profile, relative roots, recorder version/health |
| Simulator | complete bounded `SimulatedMachineState`, current command identity, queue depth, pause state, simulated time |
| Controller | public array run state, bounded active-pass summary, latest observed error/fault/disconnect state |
| Model machine | connection, motors/home, current/target position, pressure/regulation, gripper, command numbers, pause state |
| Rack/head | actual and expected slot occupancy summaries, gripper head/slot, stable stock/head identities and printing settings |
| Experiment | experiment-relative path, design/load state, plan ID/revision/state, eligibility, bounded progress counts, active runtime state |
| Calibration | selected/applied record identity, mode, effective volume, pressure, pulse width, run/phase/fingerprint when available |
| Refuel check | required/passed/deferred/bypassed/stale state and linked calibration identity when available |
| UI | current page/workflow guidance, enabled/text state for primary connection/home/regulation/array controls, active modal class/object/title |
| Persistence | relative authoritative paths, existence/size/hash, schema identities, plan/revision joins, progress counts, pending/completed/ambiguous intent counts |

Persistence hashing/parsing occurs only for explicit, launch, experiment-load,
and terminal snapshots. High-frequency machine events use cached persistence
identity so observation cannot become a checkpoint hot path.

The builder records mismatches; it never repairs them. Reconciliation rules
include:

- simulator versus Model connection, motor, home, position, pressure,
  regulation, gripper, command-number, queue, and pause state;
- Controller array state versus the primary array control projection;
- rack actual/expected state versus loaded-head identity;
- in-memory plan/progress identity versus authoritative file identity; and
- applied calibration/refuel identity versus the existing sidecar state.

## Recorder Configuration And Bounds

`StateRecorderConfigV1` is immutable and validates all limits before opening
an artifact. Initial defaults:

- in-memory event tail: 512 events;
- flush interval: every event;
- maximum changed fields per event: 64;
- maximum normalized string length: 2,048 characters;
- maximum normalized collection entries: 100; and
- JSONL encoding: UTF-8, one sorted-key JSON object plus `\n` per event.

The in-memory tail uses a deque. Eviction increments counters by event kind;
it does not drop the corresponding JSONL line. Source payload normalization
records truncated field/item/character counts.

Normal semantic events are written and flushed once. Explicit and terminal
snapshots additionally use one flushed/fsynced atomic temp-write/replace for
their JSON snapshot file. An ambiguous replace or append failure is not
retried or masked.

The recorder exposes copies through:

- `record_event(...)`;
- `record_snapshot(...)`;
- `begin_action(...)` / `complete_action(...)`;
- `latest_snapshot()`;
- `memory_tail()`;
- `health_snapshot()`;
- `flush()`; and
- idempotent `close()`.

## Correlation Policy

Session-owned actions such as connect, disconnect, and manual snapshot export
receive recorder-generated action IDs before the Controller call. The
asynchronous connection result closes the corresponding action.

Simulator command lifecycle events receive a stable command ID derived from
the application session and simulator command number. State changes caused by
the command retain that command ID through completion/cancellation.

An `action_id` is optional for developer-operated production UI controls in
Milestone 2 because the recorder must not wrap or replace their slots. Their
resulting simulator command events still carry command correlation. The
`begin_action()` API is the future seam for Milestone 6 typed actions.

Events that are neither actions nor commands use a recorder-generated
snapshot ID or explicitly documented null correlation. Correlation must never
be inferred from wall-clock proximity alone.

## Observer Lifecycle And Ordering

`SimulationStateObserver` installs only after the real application components
and recorder exist. It connects to the existing signals needed for the V1
event vocabulary, including:

- simulator state, command lifecycle, connection, error, and fault;
- Controller array, error, and transport-fault signals;
- Model experiment-load signal;
- machine-model connection/motor/regulation/gripper/command/pause signals;
- rack slot/gripper signals; and
- applied-calibration and manual-refuel-check signals.

Each source signal records its source event immediately. The observer then
coalesces at most one queued `projection_reconciled` capture per Qt event-loop
turn so Controller and Model slots can settle before cross-layer comparison.
All source events remain in JSONL even when reconciliation is coalesced.

`install()` and `dispose()` are idempotent. The observer keeps an explicit
connection ledger and disconnects only slots it installed. It does not use a
global singleton, process-global event filter, method wrapper, or stdout
redirect.

## Recorder Failure Policy

Recorder/projection exceptions are contained at the observer boundary:

1. mark recorder health failed with the first error;
2. append to the launcher log when possible;
3. stop further artifact writes and disconnect recorder observers;
4. mark the simulation session failed so its root is retained; and
5. allow the normal UI/Controller/Model/simulator operation and teardown to
   continue.

After a recorder failure, the JSONL/terminal snapshot may necessarily be
incomplete. The retained `session.json` failure state and launcher log are the
fallback evidence; implementation must not pretend that a terminal recorder
event was written.

A recorder error must never:

- select production dependencies;
- enable a physical port or hardware factory;
- call a Model/Controller mutation to make state reconcile;
- modify an experiment, plan, progress, resume, or calibration sidecar;
- suppress a normal application error; or
- trigger an unbounded retry.

## Visible Inspector

`StateInspectorDock` is simulation-only and read-only. Simulator Control gets
`Show State Inspector` and `Export State Snapshot` buttons. The inspector is
hidden by default and displays:

- recorder health and schema version;
- latest sequence/event/source/correlation;
- retained versus evicted in-memory counts;
- latest cross-layer reconciliation status; and
- formatted JSON for the recorder's latest snapshot.

The inspector receives immutable/copy payloads from `StateRecorder`. It gets
no Controller, Model, machine, experiment, or persistence writer reference.
Closing/hiding it does not stop recording, and reopening it does not install a
second observer.

## Expected Implementation Files

New runtime modules:

- `tools/sil/state_recorder.py`;
- `tools/sil/state_projection.py`;
- `tools/sil/state_observer.py`;
- `tools/sil/inspector.py`.

Expected integration edits:

- `tools/sil/session.py`;
- `tools/sil/control.py`;
- `tools/sil/__init__.py`.

Expected tests:

- `tests/test_sil_state_recorder.py`;
- `tests/test_sil_state_projection.py`;
- `tests/test_sil_state_observer.py`;
- `tests/test_sil_state_inspector.py`;
- focused additions to `tests/test_simulation_session.py` and
  `tests/test_simulator_control.py`.

Expected documentation:

- `docs/sil_state_trace_schema_v1.md`;
- `README.md`;
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`;
- this plan; and
- a separate Milestone 2 completion record only after every gate passes.

No edit to `Controller.py`, `Model.py`, `View.py`, `simulation/machine.py`,
firmware, protocol, production composition, authoritative stores, or existing
virtual-workflow scenarios is expected. If an existing signal cannot support
the frozen contract, stop before crossing an MVC layer and present the exact
gap, call path, a revised plan of no more than eight steps, and files to touch.

## Implementation Steps

1. Add schema/config/normalization types, pure layer projectors, bounded
   reconciliation output, and unit tests.
2. Add the append-only recorder, per-application-session artifact layout,
   sequence/correlation APIs, memory bounds, single-attempt persistence, and
   writer-failure tests.
3. Add the idempotent observer with its explicit signal ledger, immediate
   source events, queued coalesced reconciliation, and ordering tests.
4. Integrate recorder creation, action correlation, explicit snapshots,
   artifact metadata, failure retention, and terminal ordering into
   `SimulationSession`.
5. Add the recorder-backed inspector and Simulator Control buttons without
   exposing application objects to the inspector.
6. Add retained-root/reopen, cross-layer reconciliation, recorder-failure,
   hardware-isolation, UI, cleanup, and source/import regression tests; update
   the schema reference and README commands.
7. Run focused and full validation, complete the visible Windows gate, inspect
   retained JSONL/snapshots manually, then create the completion record and
   mark Milestone 2 complete.

## Automated Acceptance

Unit/contract tests must prove:

- schema IDs/versions, required fields, and JSON-safe normalization;
- strictly increasing per-application-session sequences;
- deterministic command/action/snapshot correlation;
- bounded payloads and memory tails with exact eviction/truncation counters;
- complete ordered JSONL on normal close;
- flush and idempotent-close behavior;
- single-attempt snapshot replacement and preserved failure evidence;
- pure projections do not call mutation/repair methods;
- unavailable/error layers remain explicit;
- persistence inspection is excluded from high-frequency captures; and
- recorder/writer failure cannot change application or safety state.

Qt/session integration tests must prove:

- observer installation/removal and inspector show/hide are idempotent;
- connection, three-phase home, regulation, movement, gripper, queue, and
  disconnect transitions appear in deterministic source order;
- simulator and Model machine projections reconcile after queued capture;
- Controller/experiment/rack/persistence projections reconcile after loading
  an existing experiment;
- terminal and cleanup events are the final lifecycle records when the
  recorder remains healthy;
- retained-root reopen creates a separate trace and preserves the prior one;
- clean fresh deletion and failure retention remain unchanged;
- the inspector uses only recorder copies; and
- physical factories/imports remain blocked exactly as in Milestone 1.

Focused validation command after implementation:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_state_recorder.py `
  tests\test_sil_state_projection.py `
  tests\test_sil_state_observer.py `
  tests\test_sil_state_inspector.py `
  tests\test_simulation_session.py `
  tests\test_simulation_session_owned.py `
  tests\test_simulator_control.py `
  tests\test_simulated_app_launcher.py `
  tests\test_safe_application_construction.py
```

Final automated validation:

```powershell
.\env\Scripts\python.exe -m pytest -q
.\env\Scripts\python.exe tools\run_simulated_app.py --help
git diff --check
git status --short
```

Allow at least 15 minutes for the full Python suite. Firmware validation is
not required because this milestone must not touch `firmware/`.

## Visible Windows Gate

Launch and retain one session:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py --keep-session
```

Through the normal UI and simulation-only controls:

1. show the State Inspector and confirm its health/sequence advances;
2. connect only to `SIMULATED`;
3. enable motors and complete home;
4. regulate pressure and perform virtual movement;
5. open/close/deactivate the gripper;
6. load an experiment through the existing Experiment Editor;
7. export an explicit state snapshot;
8. disconnect and close without a timeout or leftover process.

Inspect the retained root and confirm:

- JSONL parses line by line with strictly increasing sequence numbers;
- connection, home, regulation, movement, gripper, queue, experiment-load,
  explicit-snapshot, disconnect, teardown, and cleanup records are ordered;
- the latest and terminal snapshot schemas validate;
- simulator/Model/controller/experiment/persistence reconciliation is clean;
- in-memory retention counts reconcile with JSONL counts;
- session metadata points only to contained relative artifacts; and
- no production/hardware access or authoritative-file mutation was attributed
  to the recorder.

Reopen the retained root with `--session-root`, confirm the prior trace is
unchanged, create a second application-session trace, export one snapshot, and
close cleanly.

Any ambiguous JSONL/snapshot write failure retains the root and stops the
gate. Do not retry or replace the evidence silently.

## Stop Conditions

Stop implementation and diagnose before editing further if:

- observation requires a production hardware or protocol path;
- an existing signal cannot be observed without changing MVC behavior;
- the recorder causes a Controller/Model decision or authoritative write;
- a projection requires full per-well/image/history serialization;
- event ordering depends only on timing guesses;
- observer teardown leaves duplicate slots, filters, or timers;
- an artifact write is ambiguous or retried implicitly; or
- existing Milestone 1 hardware-isolation/teardown tests regress.

For an MVC-crossing defect or missing seam, provide the call path, a revised
plan of no more than eight steps, files to touch, verification, and rollback
before editing, as required by the repository instructions.

## Risks And Mitigations

### Event storms and memory growth

Retain every bounded source event on disk, keep only a 512-event memory tail,
coalesce cross-layer reconciliation once per event-loop turn, and record exact
eviction/truncation counts.

### Observer ordering and transient mismatch

Record source signals immediately but perform cross-layer comparison through a
queued capture after existing Controller/Model slots settle. Never repair a
mismatch.

### Private application-state drift

Prefer public getters and stable dataclass/document fields. Every layer is an
isolated projector with focused tests and explicit unavailable/error output.

### Recorder persistence failure

Recorder artifacts are non-authoritative. On the first failure, stop recorder
writes, retain/fail the session, preserve the error, and continue normal
application teardown without retry.

### Inspector feedback into application state

Give the inspector only recorder copies and snapshot/export callbacks. It must
not receive Controller, Model, machine, or writer references.

### Windows shutdown/replace interruption

Use contained same-directory temporary files, flush/fsync explicit and
terminal snapshots, perform one replace attempt, retain ambiguity, and never
weaken normal experiment durability.

## Rollback

Rollback removes the four simulation-owned recorder/observer/inspector
modules, their session/control integration, focused tests, and Milestone 2
documentation. Remove only additive recorder fields/artifact pointers from
the session schema writer.

No production data, retained evidence, experiment schema, report schema,
firmware, protocol, release metadata, tag, accepted baseline, or hardware
rollback is required. Previously retained state traces may remain as inert
evidence; older Milestone 1 sessions continue to open because schema-v1
session metadata remains backward compatible.

## Completion Record Requirements

Do not mark Milestone 2 complete until the completion record includes:

- implementation commit and exact files changed;
- schema and artifact examples;
- focused and full-suite results;
- visible Windows retained/reopen evidence paths;
- ordered transition and reconciliation results;
- memory/JSONL/flush counts;
- observer and cleanup results;
- manual inspection findings;
- known limitations and failure roots; and
- confirmation that Milestone 3 remains separate.
