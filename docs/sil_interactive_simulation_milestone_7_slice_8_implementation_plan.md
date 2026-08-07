# Milestone 7 Slice 8 - Composed 384x10 Stress Characterization

Status: `planned - awaiting approval`

Planning baseline: `af4ae5a7f5e5df7d7932b3f9936e164007b84715` with
Milestone 7 Slice 7 present in the intentionally uncommitted worktree. Before
this planning-only change, the worktree contained 18 modified tracked files
and four untracked Slice 7 files. Those changes are preserved and are part of
the implementation baseline; they must not be discarded or described as
committed.

## Objective

Migrate only `virtual_print_array_384x10_v1` from the legacy
`virtual_print_array` runner family to generic `composed_journey` dispatch.
The opt-in stress workflow must use the normal Experiment Editor, machine,
rack, calibration, and array controls for ten ordered stock passes over 384
wells, while reusing the shared multi-stock body, typed stock-pass phases,
Slice 7 sustained evidence, generic report lifecycle, and teardown.

Slice 8 preserves the tracked fixture, 384-well serpentine order, ten stock and
head identities, 3,840 stock/well completions, report-v1 paths, report-set and
local Pi-evidence compatibility, and the existing informational stress
thresholds. The legacy runner remains directly callable as a parity oracle
until all focused gates pass.

This slice does not migrate the disconnect scenario, accept or replace a
performance baseline, remediate performance, add active parameter matrices or
seeded exploration, add product/simulator fault injection, run a remote Pi
operation, change production MVC or simulator responses, change firmware or
protocol, or operate physical hardware. The complete Python suite remains
reserved for final Milestone 7 validation.

## Audit Baseline

- The roadmap names `384x10 stress` as migration item 9 after the completed
  96-well regression. The disconnect scenario remains item 10.
- The frozen schema-v2 fixture SHA-256 is
  `9584D481CA3423BD32CBC56327E0B619FD0B56387097485F4FBEA50423C0458D`.
  It expands A1-P24 in serpentine order, defines ten droplet stocks and ten
  deterministic head IDs, and declares exactly 3,840 completions.
- `registry.py` is the only active dispatcher still routing the stress ID to
  `run_virtual_print_array_scenario()`. Its Pi-evidence, injected-stall, and
  report-set support flags are already enabled.
- The legacy stress path prepares and activates authoritative files directly,
  performs mixed simulator/Model head and calibration setup, and embeds the
  workflow, instrumentation, stress classification, report, and teardown in
  `scenarios.py`. It does not exercise Experiment Editor or the normal
  machine/rack/calibration setup surfaces.
- The composed two-stock path already owns ordered head identity binding,
  normal UI setup/calibration/start/return, stock-pass boundaries, execution
  observation, assertions, reporting, and failure retention. Three helpers
  still encode the number two: pass terminal-state/milestone construction,
  lifecycle assertions, and multi-stock report projection.
- Slice 7's `RegressionEvidenceProfile` already owns the event-loop, resource,
  pressure-render, queue, persistence-I/O, progress, injected-stall, and local
  Pi evidence needed by stress. It currently assumes one pass/96 completions
  and exposes only regression terminal assertions.
- The generic composed report adapter currently derives only `pass` or `fail`.
  The legacy stress policy also permits `warning` for bounded responsiveness or
  RSS growth while treating more than a 1,000 ms service/render gap or a
  scheduling-lateness p99 over 250 ms as failure.
- No tracked stress baseline exists to rewrite. The 96-well Windows and Pi
  accepted baselines and both print-array fixtures are compatibility inputs.
- The full Python suite was not run during this audit and remains deferred.

## Current And Target Call Paths

### Legacy compatibility path

```text
tools/run_virtual_workflow.py
  -> registry.run_registered_scenario()
  -> runner_family == "virtual_print_array"
  -> scenarios.run_virtual_print_array_scenario()
       -> write/load a prepared authoritative bundle directly
       -> construct the simulated application
       -> mixed simulator/Model head setup and canned calibration
       -> normal UI array start for ten passes
       -> inline persistence/queue/UI/resource instrumentation
       -> inline stress warning/failure classification, report, teardown
```

### Target composed path

```text
registry -> JourneyExecutor -> AutomationHarness
  -> shared multi-stock JourneyDefinition/body
  -> machine_startup_steps()
       QTest -> Machine controls -> Controller -> Model -> SimulatedMachine
  -> run_editor_preparation()
       QTest -> Experiment Editor -> authoritative persistence
  -> generalized ordered StockPassSpec sequence (10 entries)
       QTest -> settings/rack/calibration/array controls for each stock
       -> read-only boundary validation after 384, 768, ... 3,840 updates
  -> one cardinality-neutral sustained-evidence profile
  -> shared lifecycle + stress assertions and report-v1 projection
  -> generic evidence retention and teardown
```

The application call path stops at `SimulatedMachine` on the literal
`SIMULATED` port. No comms framing, firmware handler, physical motion,
pressure hardware, camera, balance, GPIO, updater, or MCU is exercised or
changed.

## Frozen Slice Decisions

1. **One migration only.** Preserve the registry/workload/scenario identity,
   fixture bytes/hash, 384-well order, ten stock/head identities, 3,840
   completions, opt-in status, suite/platform membership, support flags, and
   informational threshold maturity.
2. **Generalize cardinality; add no stress body.** The existing multi-stock
   body, pass runner, lifecycle assertions, and payload must derive stock
   count, cumulative boundaries, terminal state, settings, and completion
   multiplicity from validated fixture/spec data. The 24x2 and 384x10
   definitions must call the same body and report projection.
3. **Fail before migration on recipe drift.** A preparation-only gate must
   prove that the normal editor creates 384 unique wells, ten ordered stocks,
   one target per stock/well, and exactly 3,840 planned pairs. If normal UI
   generation produces another cardinality, stop and amend this plan; do not
   alter the fixture, concentrations, target values, or expected count in this
   slice.
4. **Truthful calibration evidence.** The fixture retains its 5 nL prepared
   values and 10 nL design targets. The normal pulse-aware SIL model is
   authoritative for applied synthetic results: 1300-1390 us predicts
   9.00, 9.18, 9.36, 9.54, 9.72, 9.90, 10.08, 10.26, 10.44, and 10.62 nL.
   Assertions compare selected/applied/runtime values with that model while
   reporting the unchanged design target separately. This makes no physical
   volume-accuracy claim.
5. **Truthful interaction surfaces.** Editor, settings, volume, rack,
   calibration, pressure, start, and head-return operations remain QTest/UI
   actions. Deterministic head identity binding remains an explicit `model`
   action. Waits, observers, boundary checks, midpoint capture, Pi validation,
   reporting, and teardown remain `harness` actions.
6. **One sustained-evidence implementation.** Generalize the Slice 7 profile
   in place for expected completion cardinality and optional current-pass
   context. The 96-well and stress definitions share it; no second observer,
   resource sampler, persistence parser, stall detector, or report envelope is
   permitted.
7. **Preserve stress classification exactly.** Functional or evidence failures
   are `fail`. Event-loop or pressure-render gaps over 1,000 ms, or scheduling
   p99 over 250 ms, fail. Otherwise a service/render gap over 250 ms warns.
   RSS growth warns only when it exceeds both 100 MiB and a 1.25 ratio. No
   threshold is tuned and no baseline is accepted in this slice.
8. **Targeted validation only.** Run the focused gates below, one visible run,
   and its exact replay. Do not run unscoped pytest; the complete suite remains
   the final Milestone 7 gate.

## Frozen Composed Contract

Required assertions are exactly:

```text
sil.host_hardware_disabled
sil.pi_evidence_valid
ui.real_app_constructed
execution.multi_stock_head_exchange
execution.stock_pass_boundaries_valid
execution.stock_head_settings_match
execution.expected_completions
execution.no_queue_starvation
execution.intent_durability_exact
execution.event_history_bounded
execution.terminal_bundle_valid
artifacts.required_present
ui.injected_stall_detected
ui.responsiveness_metrics_present
ui.sustained_responsiveness_acceptable
resources.metrics_present
```

`execution.multi_stock_head_exchange` becomes cardinality-neutral while
retaining its public ID: it requires ten ordered identities/stages, nine safe
between-pass exchanges, idle controller state, and a drained queue. It does
not claim physical head handling. `sil.pi_evidence_valid` passes with explicit
not-applicable evidence locally and requires matched safe preflight/proof data
when supplied.

Required retained screenshots are exactly:

```text
editor_opened
generated
ready
printing
mid_array
completed
```

The midpoint is cumulative completion 1,920 after stock pass 5. All ten pass
boundaries remain in structured evidence without taking three screenshots per
pass. The action ledger contains ten settings/volume/stage/calibration/start/
wait/return groups, one identity-bind action, one pressure-enable action, six
milestone captures, and generic launch/teardown. The first start handles
`Start Print Array` plus `Evaporation Plate Dock Check`; the remaining nine
handle only `Start Print Array`.

Terminal evidence requires cumulative boundaries 384 through 3,840, plan
states `ACTIVE` for passes 1-9 and `COMPLETED` only after pass 10, 3,840 unique
stock/well pairs and intent lifecycles, 3,840 cached progress updates and zero
full rebuilds, 11,520 resume fsync/replace operations, 3,840 progress
fsync/replace operations, zero hot-path reads, exact compact-progress evidence,
zero unexpected starvation, bounded simulator histories, restored observers,
and clean teardown. Existing pass-start, terminal-transition, pressure,
resource, progress-format, cumulative-byte, report-set, Pi identity, and
comparison-compatible responsiveness paths remain inspectable.

## Code-Shape And Reuse Gates

- no new workflow body, page driver, report envelope, observer family, or
  persistence parser;
- the stress fixture/profile loaders, compact milestone policy, summary,
  contract, and `JourneyDefinition` add at most 110 physical lines total;
- two-stock cardinality removal and reusable pass/assertion/payload
  generalization add at most 220 net physical lines;
- sustained-profile and stress classification/report generalization add at
  most 250 net physical lines after moved/replaced code is subtracted;
- total touched runtime net growth is at most 500 physical lines;
- the 24x2 and 384x10 definitions reference the same body, pass phase,
  lifecycle assertion function, payload builder, and UI action set;
- `page_drivers.py` and `actions.py` gain no raw QTest or scenario-specific
  driver; `registry.run_registered_scenario()` gains no scenario-ID branch;
- the stress fixture, 96-well fixture, accepted baseline JSON, production MVC,
  simulator response, Pi script, firmware, and protocol bytes remain
  unchanged.

Line limits are review gates, not permission to compress behavior. If the
normal-UI recipe cannot retain 3,840 pairs or the report/evidence contract
cannot fit these reuse gates, stop and amend the plan rather than copy legacy
logic or weaken coverage.

## Exact Files To Touch During Implementation

Required runtime files:

- `tools/virtual_workflows/regression_evidence.py`
- `tools/virtual_workflows/composition.py`
- `tools/virtual_workflows/journey_phases.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/report.py`
- `tools/virtual_workflows/registry.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Required focused tests:

- `tests/test_virtual_workflow_journey_phases.py`
- `tests/test_virtual_workflow_assertions.py`
- `tests/test_virtual_workflow_composition.py`
- `tests/test_virtual_workflow_report.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/performance/test_virtual_workflow_comparison.py`
- `tests/system/test_pi_virtual_workflow_lane.py`
- existing `tests/system/test_virtual_print_array_384x10_workflow.py`
- existing `tests/system/test_virtual_workflow_multi_stock_composed.py`
- existing `tests/system/test_virtual_print_array_96_composed.py`
- new `tests/system/test_virtual_print_array_384x10_composed.py`

Required implementation documentation:

- `README.md`
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- this implementation plan, for status only
- new
  `docs/sil_interactive_simulation_milestone_7_slice_8_completion_record.md`

`tools/virtual_workflows/scenarios.py` remains the unchanged direct oracle.
`tools/run_virtual_workflow.py`, `compare.py`, `execution_observer.py`,
`metrics.py`, `persistence_io.py`, `progress_snapshot.py`, both print-array
fixtures, both accepted 96-well baselines, production MVC, simulator responses,
Pi scripts, firmware, protocol, and hardware files are validation inputs and
are not expected to change. If implementation proves one necessary, stop and
amend this plan before editing it.

## Implementation Steps

1. **Freeze inputs and prove normal-UI feasibility.** Record fixture/baseline
   hashes and legacy stress projections; add a bounded preparation-only test
   proving exact 384-well, ten-stock, 3,840-pair generation before printing.
2. **Generalize ordered stock passes.** Remove two-stock cardinality and
   terminal-state assumptions from typed pass construction; add a reusable
   compact milestone policy and preserve the existing 24x2 action/milestone
   contract unchanged.
3. **Generalize lifecycle assertions and payloads.** Derive exchange count,
   head/settings order, completion multiplicity, cumulative boundaries,
   durability, terminal state, and report workload fields from validated
   fixture/spec data; add pulse-aware per-stock calibration evidence.
4. **Generalize sustained evidence and classification.** Reuse the Slice 7
   profile for 3,840 completions and pass context, retain all metric paths, add
   fail-closed metric/resource assertions, and allow the generic report adapter
   to apply the frozen stress warning policy only after functional success.
5. **Compose and register stress.** Add the thin 384x10 definition over the
   shared multi-stock body, switch only its registry family, retain support
   flags and direct oracle, and update manifest actions/surfaces/assertions/
   artifacts/tests without broadening physical claims.
6. **Add focused success, parity, and failure tests.** Prove exact preparation,
   ten-pass execution, direct/composed stable parity, report-set compatibility,
   warning/failure thresholds, injected-stall and Pi contracts, unexpected
   between-pass dialog/timeout retention, restoration, and cleanup.
7. **Run targeted automated, visible, and replay gates.** Use only the commands
   below; inspect report-v1 paths, ledgers, six screenshots, classifications,
   hashes, report-set projection, replay stability, and absence of session
   locks or hardware access.
8. **Document and close Slice 8.** Update README and roadmap, record measured
   code shape, targeted results, retained evidence, risks, and rollback in a
   completion record, then stop before disconnect planning or implementation.

## Focused Automated Gates

Run reusable phase/assertion/report/manifest/comparison/Pi contracts:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice8-unit" `
  tests\test_virtual_workflow_journey_phases.py `
  tests\test_virtual_workflow_assertions.py `
  tests\test_virtual_workflow_composition.py `
  tests\test_virtual_workflow_report.py `
  tests\test_virtual_workflow_manifest.py `
  tests\test_virtual_workflow_contract_freeze.py `
  tests\performance\test_virtual_workflow_comparison.py `
  tests\system\test_pi_virtual_workflow_lane.py `
  tests\system\test_virtual_print_array_384x10_workflow.py
```

Revalidate the shared 24x2 and 96-well consumers:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice8-multi" `
  tests\system\test_virtual_workflow_multi_stock_composed.py

.\env\Scripts\python.exe -m pytest -q --run-sil-regression `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice8-regression" `
  tests\system\test_virtual_print_array_96_composed.py
```

Run the opt-in composed success/direct-parity and early fail-closed nodes:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-stress `
  --basetemp "$env:TEMP\LabCraft\pytest-m7-slice8-stress" `
  tests\system\test_virtual_print_array_384x10_composed.py
```

The full composed/direct node must run at an accelerated multiplier with a
bounded internal deadline. Once printing begins, observe completion progress;
if it stops increasing for 120 seconds, terminate only the confirmed test
process, retain available evidence, and diagnose instead of waiting for an
outer 15-minute timeout. Continued slow progress is not a hang.

Also run:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --help
.\env\Scripts\python.exe -m py_compile `
  tools\virtual_workflows\regression_evidence.py `
  tools\virtual_workflows\composition.py `
  tools\virtual_workflows\journey_phases.py `
  tools\virtual_workflows\journeys.py `
  tools\virtual_workflows\assertions.py `
  tools\virtual_workflows\report.py `
  tools\virtual_workflows\registry.py
git diff --check
git status --short
```

Do not run unscoped `pytest -q` in Slice 8. The complete Python suite remains
the final Milestone 7 validation gate.

## Success, Parity, And Failure Gates

The composed success gate must prove:

- real application construction with hardware access disabled and only the
  literal simulated port;
- normal editor creation of ten ordered reagents and 384 serpentine wells;
- ten normal UI calibration/start cycles, ten deterministic staged heads,
  nine safe between-pass exchanges, and no ambiguous calibration selection;
- pulse-aware selected/applied volumes for every stock while the fixture's
  10 nL design targets remain visible and unchanged;
- cumulative completion boundaries 384 through 3,840, `ACTIVE` through pass 9,
  one final `COMPLETED`, ten array-complete signals, zero starvation/errors,
  exact intents/durable writes, bounded histories, and compact progress;
- present responsiveness/resource measurements, unchanged warning/failure
  thresholds, all 16 required assertion decisions, and restored observers;
- report-v1, summary, events, stall stacks, action/assertion ledgers, evidence
  manifest, six screenshots, fixture hash, seed, replay command, scenario root,
  and clean teardown.

Stable direct/composed parity compares fixture/workload identity, well and
stock order, 3,840 completion cardinality, pass boundaries/states, queue and
persistence invariants, terminal state, responsiveness/resource metric shape,
stress classification, Pi safety projection, report-set compatibility, and
cleanup. It explicitly permits the composed path's broader truthful UI ledger,
editor screenshots, pulse-aware calibration values versus the direct oracle's
canned 10 nL shortcut, seed/replay fields, generated identities/paths/times,
measured performance values, and identity-bearing hashes to differ.

At minimum, tests fail closed for preparation cardinality drift, wrong stock or
head association, ambiguous calibration selection, an unexpected second-pass
dialog, timeout, incomplete boundary/terminal evidence, missing sustained
metrics, an unrestored observer, a greater-than-1,000 ms responsiveness gap,
one-sided/mismatched/unsafe Pi evidence, and missing artifacts. Failure reports
retain all available metrics, traceback, screenshot, events, stack file,
ledgers, manifest, partial roots, and best-effort teardown. Existing UI-stall
injection is a harness compatibility check, not new product fault injection.

## Visible And Replay Gate

Run once through the normal Windows UI:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario virtual_print_array_384x10_v1 `
  --output-root verification_reports\milestone7-slice8-visible `
  --visible --seed 1 --speed-multiplier 100 --timeout-seconds 600
```

Inspect the editor, generated design, ready, printing, midpoint, and completed
screenshots; all ten settings/calibration/pass action groups; ten cumulative
boundaries; report and metric paths; ledgers; evidence manifest; events;
stall-stack file; scenario root; and cleanup. Confirm the visible terminal
projection shows 3,840/3,840 stock/well work and the application remains
hardware-isolated.

Then execute the exact `run.replay_command` emitted by that report into the
same output root. Require equal stable projection for fixture hash/seed,
action IDs/multiplicity/surfaces/statuses, assertion decisions, dialogs,
well/stock/completion order, pulse-aware calibration results, milestone and
screenshot names, persistence relationships, metric shape, classification,
and cleanup. Ignore only documented generated identities, paths, timestamps,
durations, measured timing/resource values, and hashes bearing those values.

Monitor actual completion growth rather than waiting blindly. If no completion
progress occurs for 120 seconds after printing starts, terminate only the
confirmed workflow process and retain its evidence; do not wait out the
remaining 600-second deadline. Two consecutive fresh-root failures at the
same boundary block the migration and do not authorize a larger timeout or
performance remediation.

## Risks And Mitigations

- **The legacy fixture may not compose to 3,840 normal-UI pairs:** make exact
  prepared cardinality the first stop gate; require an amended reviewed plan
  for any fixture or recipe change.
- **Two-stock assumptions survive in shared code:** test 1-, 2-, and 10-stock
  normalized specs and require cumulative states/counts derived from data.
- **Stress diagnostics are duplicated:** enforce one generalized Slice 7
  profile and net-growth gates; no second sampler/observer/report path.
- **Instrumentation perturbs sustained measurements:** keep probes bounded,
  use six screenshots rather than per-pass screenshots, and preserve existing
  thresholds without claiming new performance acceptance.
- **Pulse-aware UI calibration differs from the legacy shortcut:** record both
  design and applied values, validate the deterministic response model, and
  review that difference explicitly in parity.
- **Warning semantics become a silent pass or failure:** unit-test each exact
  boundary and require functional failure precedence over warning policy.
- **Pi capability is dropped or overclaimed:** preserve support flags and local
  paired-evidence validation; perform no SSH, SCP, wrapper, or remote run.
- **Long Qt execution hangs:** use internal deadlines, live progress, a
  120-second no-progress stop rule, isolated roots, and best-effort retention.

## Rollback

Keep `run_virtual_print_array_scenario()` directly callable through all
focused gates. If migration fails, restore only the
`virtual_print_array_384x10_v1` registry and manifest entry to
`virtual_print_array`; remove its composed definition and focused tests; and
restore prior generic classification/profile behavior only if those changes
regress the composed 96-well or 24x2 journeys.

Retain cardinality-neutral pass/assertion/report helpers only when the existing
1-stock, 2-stock, and direct stress contracts continue to pass independently.
Do not modify or delete fixtures, accepted baselines, retained evidence,
earlier Slice changes, production data, or release metadata. No production,
simulator-response, Pi-host, firmware/protocol, or hardware rollback is
required.

## Approval Gate

Do not implement Slice 8 until the user approves this plan. Any fixture or
accepted-baseline change, production MVC or simulator-response edit,
report-schema revision, disconnect migration, performance remediation, active
matrix, seeded exploration, new product fault injection, remote Pi operation,
firmware/protocol change, or hardware work requires an amended plan and
separate approval.
