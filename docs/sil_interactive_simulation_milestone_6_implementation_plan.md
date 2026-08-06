# Milestone 6 — Shared Automation Harness And 24-Well UI Smoke

Status: `complete — implemented and validated on 2026-08-06`

Planning baseline: `999d10bee1191acb3069de7416e2794d5a7897a3`, the
single Milestone 5 commit above
`130c47fb3e109b974cb4a687e2cc44c815c99196`.

## Audit Result

The local worktree was clean during this audit. Milestone 5 is no longer an
intentionally uncommitted change here: its implementation, focused tests,
README and roadmap updates, three focused-correction plans, and completion
record are committed at the planning baseline.

The retained Windows roots named by the Milestone 5 completion record are not
present under this computer's `%LOCALAPPDATA%\LabCraft\SIL\interactive-sessions`
directory. Their documented results and hashes are historical evidence only;
this plan does not claim that they were re-inspected or revalidated here.

No automated test was rerun during the documentation-only audit.

## Scope

Milestone 6 extracts one shared automation harness and proves it by migrating
only `virtual_print_array_24_v1`. The migrated journey must create, prepare,
calibrate, stage, and print its one-stock 24-well experiment through normal Qt
controls. Direct reads may support assertions, but operator actions must not
mutate Model state, authoritative files, the rack, or the simulated machine
behind the UI.

The milestone preserves all other scenario implementations as compatibility
paths. It does not migrate editor, multi-stock, soft-stop, reload/resume, 96-
well, 384x10, comparison, performance, Pi, or fault-injection workflows.

It also does not change production MVC behavior, firmware, protocol, physical
hardware behavior, synthetic-calibration schemas/providers, or manual-refuel
behavior.

## Audited Call Paths

### Existing interactive path to reuse

```text
tools/run_simulated_app.py
  -> SimulationSession.create()/launch()
  -> simulation_dependencies
  -> real MainWindow / Controller / Model / SimulatedMachine
  -> normal connection, editor, rack, calibration, pressure, and array UI
  -> StateRecorder snapshots/events
  -> SimulationSession.close()
```

### Existing automated print path

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> scenarios.run_virtual_print_array_scenario()
  -> _create_prepared_fixture() writes an authoritative bundle directly
  -> ExperimentModel.load_experiment() and Model runtime activation directly
  -> ExperimentModel.apply_execution_calibration() directly
  -> SimulatedMachine.connect_board() plus Controller home/settings directly
  -> rack_model slot/gripper mutation directly
  -> Controller pressure regulation directly
  -> QTest Start / Stop / Resume buttons
  -> embedded scenario validators
  -> scenario-specific report-v1 assembly and teardown
```

Only Start/Stop/Resume and the authoritative-reload editor path currently
demonstrate Qt interaction. The action ledger does not record an interaction
surface, so direct Model, Controller, simulator, and UI actions are not
distinguishable in coverage output.

### Existing editor path

```text
registry.run_registered_scenario()
  -> editor_scenarios._run_editor_lifecycle_scenario()
  -> separate Qt/application/session/evidence setup
  -> workflow-specific editor driver in actions.py
  -> direct Model activation, lock, reload, and validation operations
  -> separate report-v1 assembly and teardown
```

### Target migrated smoke path

```text
CLI/registry
  -> typed 24-well JourneyDefinition
  -> shared AutomationHarness owning one SimulationSession
  -> semantic action
  -> one surface-specific QTest page driver
  -> normal UI signal/slot
  -> real Controller -> Model -> SimulatedMachine/authoritative writers
  -> StateRecorder plus action/assertion ledgers
  -> report-v1 compatibility adapter, evidence hashes, replay command
  -> fail-closed teardown
```

The migrated execution call path remains:

```text
normal Qt control
  -> Controller
  -> Model / ExperimentModel
  -> simulated command queue / SimulatedMachine
  -> existing authoritative plan, calibration, progress, and resume writers
```

No firmware handler or device-protocol path is involved.

## Duplication To Remove In This Slice

- Qt creation, simulation construction, session-root handling, and component
  ownership in `scenarios.py` and `editor_scenarios.py` overlap the existing
  `SimulationSession`.
- Observer installation, dialog polling, screenshots, failure traceback,
  cleanup, and report finalization are assembled independently by each runner
  family.
- `scenarios.py` branches inside one large function for smoke, soft stop,
  authoritative reload, and multi-stock behavior, then branches again while
  calculating assertions and report content.
- editor create/finalize, rename/refinalize, and post-start-copy mechanics are
  large workflow-specific functions rather than one driver per UI surface.
- assertions both inspect state and decide report classification inside runner
  functions; their pass/fail/incomplete semantics are not reusable.
- action IDs are repeated in Python sets and the capability manifest, while
  their actual `ui`, `controller`, `model`, `simulator`, or `harness` surface
  is absent from evidence.

Milestone 6 removes these duplications only from the new harness and migrated
smoke. Legacy branches remain unchanged until their individual Milestone 7
parity gates pass.

## Frozen Design Decisions

1. **One session owner.** The harness uses `tools.sil.session.SimulationSession`
   with borrowed Qt ownership when a test application already exists and a
   retained root beneath the safe OS temporary SIL directory. The report links
   the exact root. It does not reproduce application construction or cleanup.
   A report-contained root was rejected because report output may be inside the
   repository, which `SimulationSession` correctly forbids for application data.
2. **UI means QTest.** An action may claim surface `ui` only when its state-
   changing operation is performed through a visible/enabled Qt control using
   bounded `QTest` input. Calling a Controller slot or changing a widget with a
   direct setter is not UI coverage.
3. **Reads are not actions.** Assertions may read widgets, recorder snapshots,
   validated authoritative files, and stable Model/Controller accessors. They
   must not repair state, invoke state-changing slots, or write files.
4. **One driver per surface.** Initial drivers are `MainWindowDriver`,
   `ExperimentEditorDriver`, `MachineControlsDriver`, `RackDriver`,
   `CalibrationDialogDriver`, and `ArrayDriver`. They expose Qt mechanics only;
   workflow policy and expected business outcomes remain in actions and
   assertions.
5. **Action-local dialog policy.** Each action declares the exact ordered modal
   sequence it permits. Any other visible modal, missing expected modal, stale
   modal, or timeout fails the action and the journey. The existing global
   auto-accept allowlist is not used by the migrated smoke.
6. **Report-v1 compatibility.** Keep the v1 top-level envelope and existing
   24-well identity/metric paths. Add nested action-surface, assertion, session,
   seed, evidence-manifest, and replay fields. Do not introduce report-v2 in
   this milestone.
7. **Fixture compatibility.** Preserve registry ID, workload ID, scenario name,
   and 24-completion contract. Change the smoke's canned 5-to-10 nL data to the
   manually qualified 9 nL/1300 us, zero-fill normal-UI recipe so the real
   pulse-aware synthetic calibration path can produce the requested result.
8. **Legacy sequencing.** Slice 4.7/disconnect remains paused. All portfolio
   migration, fault injection, seeded exploration, performance work, and Pi
   operation remain Milestones 7 or 8.

These decisions are part of plan approval. A requested change to any of them
requires updating this plan before implementation.

## Typed Contracts

`InteractionSurface` is a closed enum: `ui`, `controller`, `model`,
`simulator`, and `harness`. Each `SemanticAction` has a stable ID, typed input,
one declared surface, precondition, bounded execution, completion predicate,
allowed dialogs, and bounded evidence. Each ledger row records sequence,
surface, application-session ID, start/end/duration, status, failure stage,
and snapshot/screenshot correlations.

`AssertionResult` has a stable ID, checkpoint, decision (`pass`, `fail`, or
`incomplete`), observable sources, and bounded evidence. Assertions never run
actions. A required `fail` or `incomplete` result fails the journey.

`JourneyDefinition` contains scenario/workload identity, fixture identity and
hash, seed, ordered actions, checkpoint assertions, terminal assertions,
dialog policy, deadline, retention policy, capability mapping, and limitations.
The 24-well composition is short typed Python; the experiment recipe remains
validated JSON data.

`AutomationHarness` owns the deadline, `SimulationSession`, action/assertion
execution, unexpected-dialog monitor, recorder health checks, failure capture,
report finalization, and idempotent teardown. It fails closed on exhausted
deadlines, unexpected/stale dialogs, recorder failure, stale authoritative
identity, ambiguous persistence, missing assertions, or cleanup failure.

## Implementation Steps

1. Freeze the current CLI, registry, report-v1, capability, fixture, and smoke
   assertions in focused compatibility tests. Update only the 24-well fixture
   to the validated 9 nL/1300 us normal-UI recipe and add an additive `--seed`
   CLI input with a deterministic default.
2. Add the generic `AutomationHarness` around `SimulationSession`: contained
   retained root, shared deadline, recorder correlation, dialog monitor,
   screenshots/snapshots, failure traceback, evidence inventory with SHA-256,
   exact replay command, and idempotent teardown.
3. Refactor Qt mechanics into the six surface drivers listed above. Every
   mutating driver operation uses `QTest`, checks visibility/enabled state,
   observes a bounded completion condition, and rejects unexpected dialogs.
4. Refactor `actions.py` to the typed semantic-action contract and implement
   only the actions needed by the smoke: launch, connect, enable/home, create
   and finalize, stage head, generate/select/apply droplet calibration, enable
   pressure regulation, start, wait for completion, capture milestone, and
   close. Record the declared interaction surface in every result.
5. Add reusable read-only assertions for hardware isolation/simulation
   identity, machine readiness, prepared execution, rack/head association,
   applied calibration/settings, queue and intent durability, exact 24-well
   progress, terminal bundle reconciliation, artifacts, and cleanup. Missing
   evidence produces `incomplete`, never an inferred pass.
6. Add the short typed `virtual_print_array_24_v1` composition and dispatch
   only that registry ID to the new harness. Preserve the old print and editor
   runners unchanged for every other registered scenario.
7. Add a report-v1 compatibility adapter and manifest join that preserve old
   required fields while adding interaction-surface/action and assertion
   ledgers, session/seed/fixture identities, evidence-manifest location, and
   replay command. Reject a UI capability claim backed only by a non-UI action.
8. Run focused unit/contract/system tests, the full affected regression, one
   visible Windows gate, one replay from its emitted command, and finally the
   complete Python suite. Inspect both success and intentionally induced
   harness-failure evidence before recording completion.

## Exact Implementation File Set

New files:

- `tools/virtual_workflows/harness.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tests/test_virtual_workflow_harness.py`
- `tests/test_virtual_workflow_page_drivers.py`
- `tests/test_virtual_workflow_assertions.py`
- `docs/sil_interactive_simulation_milestone_6_completion_record.md`

Modified files:

- `tools/run_virtual_workflow.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/page_drivers.py`
- `tools/virtual_workflows/scenarios.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/report.py`
- `tools/virtual_workflows/fixtures/virtual_print_array_24_v1.json`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`
- `tests/test_virtual_workflow_actions.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_smoke.py`
- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this plan

No file under `FreeRTOS-interface/`, `firmware/`, performance tests, Pi tools,
comparison/baseline tooling, or another system scenario is in the approved
implementation set. If a missing normal UI seam is discovered, stop and write
a separate scoped diagnosis/plan instead of expanding this list implicitly.

## Focused Automated Gates

Run the contract/unit gate first:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulation_session.py `
  tests\test_virtual_workflow_harness.py `
  tests\test_virtual_workflow_page_drivers.py `
  tests\test_virtual_workflow_actions.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\test_sil_normal_ui_convergence.py
```

Run the migrated proof and unchanged adjacent lifecycle compatibility gates:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\system\test_virtual_workflow_smoke.py `
  tests\system\test_virtual_workflow_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py `
  tests\system\test_virtual_workflow_multi_stock_lifecycle.py `
  tests\system\test_virtual_workflow_editor_lifecycle.py `
  tests\system\test_virtual_workflow_editor_post_start_lifecycle.py
```

The smoke test must prove that every state-changing operator action is
surface `ui`; direct reads used by assertions must be separately labeled and
must not appear as UI actions. It must also prove exact 24 completions, zero
unexpected dialogs, recorder health, authoritative reconciliation, clean
timers/locks, report-v1 validation, evidence hashes, and a replay command.

After focused gates pass, run the repository gate with the required timeout:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\harness.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\actions.py `
  tools\virtual_workflows\page_drivers.py `
  tools\virtual_workflows\report.py `
  tools\virtual_workflows\registry.py
git diff --check
git status --short
```

## Visible And Replay Gates

Use a new ignored output root and a fixed seed:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_24_v1 `
  --output-root verification_reports\milestone6-visible `
  --visible `
  --seed 1 `
  --speed-multiplier 2 `
  --timeout-seconds 300
```

The visible run passes only when an observer confirms normal controls were used
for connection, motor enable/home, editor creation/finalization, rack staging,
calibration generation/selection/Apply, pressure regulation, and array start;
all required dialogs match the action-local policy; the 24-well terminal state
reconciles; and close leaves no session lock or simulator timer.

Run the exact replay command stored in the first report. The replay must
reproduce the same scenario, fixture hash, seed, action order/surfaces,
assertion decisions, calibrated values/settings, plan-derived completion
counts, and terminal state. UUIDs, timestamps, durations, report/session paths,
generated plan/head/run identities, calibration fingerprints containing those
identities, and identity-bearing authoritative hashes are allowed to differ.

Manually inspect both reports, evidence manifests, state traces, action and
assertion ledgers, milestone screenshots, terminal snapshots, cleanup rows,
and replay commands. The completion record must name the retained roots and
SHA-256 inventories actually inspected on the implementation computer.

## Failure-Evidence Gate

Use a unit/integration-controlled harness failure after the session is active;
do not add a production fault-injection CLI or migrate a fault scenario. The
gate must prove that an unexpected dialog, timeout, stale recorder/state, or
ambiguous assertion:

- fails the current action with its exact stage and surface;
- marks remaining required assertions `incomplete`;
- captures the visible application screenshot and cross-layer snapshot;
- writes the traceback, ledgers, seed, fixture hash, evidence inventory, and
  replay command;
- attempts every teardown phase without masking the primary failure; and
- retains the failed root with no session lock or live simulator timer.

## Risks And Mitigations

- **False UI coverage:** direct calls survive behind semantic names. Mitigate
  with the closed surface enum, driver-only QTest mutation, source tests, and
  manifest rejection of unsupported UI claims.
- **Report/CLI drift:** the migrated smoke breaks existing consumers. Mitigate
  with the report-v1 adapter, unchanged scenario/workload IDs, additive CLI,
  contract-freeze tests, and unchanged legacy dispatch.
- **Dialog races:** a broad timer accepts the wrong modal. Mitigate with
  action-local ordered modal expectations, active-modal identity checks, and
  fail-closed timeouts.
- **State recorder and harness evidence disagree:** one source silently fails.
  Mitigate by checking recorder health and correlating every action/assertion
  to application-session snapshots before report classification.
- **Fixture semantics change:** 5-to-10 nL canned setup cannot be reproduced by
  the qualified 1300 us normal synthetic path. Mitigate by explicitly freezing
  the 9 nL/1300 us recipe while preserving the 24-completion workload contract.
- **Qt teardown instability:** failure capture obscures cleanup errors. Mitigate
  with `SimulationSession.close()` as the sole owner, idempotence tests, and
  separate primary-failure and cleanup evidence.
- **Scope creep:** shared abstractions trigger broad migration. Mitigate by
  dispatching exactly one registry ID to the harness and retaining every other
  legacy runner unchanged.

## Rollback

Rollback restores `virtual_print_array_24_v1` registry dispatch and its fixture
to the legacy `run_virtual_print_array_scenario` path, removes the new harness,
assertion, journey, and driver tests/modules, and removes only the additive
report/manifest/CLI fields introduced here. The legacy report-v1 runner and all
other scenarios remain available throughout implementation.

No experiment migration, authoritative-schema rollback, production MVC
rollback, firmware/protocol rollback, Pi cleanup, hardware action, or deletion
of retained evidence is required. Retained success/failure roots may be left
for inspection; rollback must not rewrite or delete them.

## Approval Gate

This plan was approved and implemented only for the exact 24-well smoke slice.
Any production seam, additional workflow migration, production fault-injection
feature, performance finding, firmware/protocol issue, Pi operation, or
hardware issue requires a separate decision.
