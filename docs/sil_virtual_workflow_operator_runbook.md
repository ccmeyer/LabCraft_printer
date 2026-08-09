# SIL Virtual Workflow Operator Runbook

## Operating model

All LabCraft SIL execution is operator-initiated. No scheduler, background
service, CI job, or calendar cadence starts these workflows. Select a lane
after reviewing the changed areas, run it explicitly, and retain the emitted
command and evidence.

The workflow runner constructs the real application with `SimulatedMachine`
and drives normal Qt controls through QTest. It does not validate firmware,
serial protocol behavior, physical motion, pressure response, droplet quality,
camera segmentation, or real printer-head handling.

Use the repository interpreter on Windows:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list all
```

Listing, dry-run planning, and changed-source recommendations never start a
workflow. A plan's `execution_authorized: false` means it is descriptive; only
an explicit non-dry-run selector starts children.

## Choosing a manual lane

| Changed behavior | Minimum lane | Add when warranted |
| --- | --- | --- |
| Shared Qt driver, application construction, or basic editor/start controls | `standard` | visible standard plus replay |
| Editor lifecycle, persistence, stop/resume, reload, disconnect, calibration, or manual refuel | `lifecycle` | affected direct scenario |
| Calibration values, droplet/stream modes, stock order, or manual-refuel safeguards | `mixed_mode_calibration_v1` matrix | visible positive and safe-block cases |
| Calibration volume or exact prepared/preview/commanded/completed droplet counts | `calibration_requantization_v1` matrix | visible boundary or `stream_to_droplet_40_to_10_8` case |
| Experiment formulation, stock feasibility, well selection/randomization, capacity, or Finalize safeguards | `experiment_design_pairwise_v1` matrix | visible positive and rejected-boundary cases |
| Prepared-editor ordering or activation guards | `editor_prepared_guard_v1` exploration | selected legal/illegal visible sequences |
| General execution or durability changes | `host_regression` | `host_stress` for sustained effects |
| Rack, revision history, responsiveness, resource growth, or scalability | `host_stress` | retained visible 384×10 evidence or a separately justified visible run |
| Pi transport, process isolation, bundle, replay, or Pi-specific environment | `pi_primary` | separately authorized `pi_stress` only for sustained Pi characterization |
| Release candidate affecting several areas | standard, lifecycle, matrix, exploration, regression, stress | separately authorized `pi_primary`; final default pytest suite |

Changed-source recommendations are advisory and never execute tests:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --recommend-changed --changed-path tools\virtual_workflows\page_drivers.py
```

## Planning and execution

Inspect a selection before executing it:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py --list suites
.\env\Scripts\python.exe tools\run_virtual_workflow.py --suite lifecycle --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix mixed_mode_calibration_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix calibration_requantization_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --matrix experiment_design_pairwise_v1 --dry-run
.\env\Scripts\python.exe tools\run_virtual_workflow.py --exploration editor_prepared_guard_v1 --dry-run
```

Common Windows commands:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite standard --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix mixed_mode_calibration_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 `
  --case stream_to_droplet_40_to_10_8 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix experiment_design_pairwise_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90 `
  --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --exploration editor_prepared_guard_v1 `
  --output-root verification_reports\exploration `
  --speed-multiplier 1000 --timeout-seconds 60

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_regression --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_stress --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000
```

For visible Windows evidence, set `QT_QPA_PLATFORM=windows`, add `--visible`,
and use a realistic bounded speed such as 20x. Run the exact replay command
printed by the report or aggregate rather than reconstructing it manually.
The requantization catalog has eight ordered cases. Cases four through six
require exact grouped stock/well evidence: 36 positive intents for the
multi-target case, 48 for the stream-to-droplet case, and 48 for the fill
transition. The stream case must additionally retain a passing
completed-terminal fresh-session reload; the application reports that terminal
bundle as `COMPLETED` and `analysis_only`, with zero remaining progress and
hardware activation blocked.

The experiment-design catalog has nine ordered cases. Positive cases must
reach prepared state through normal editor controls, reload the authoritative
design and execution plan, and reproduce catalog-owned stock, reaction, and
well assignments. For `two_stock_required`, require the rejected one-stock
attempt to leave authoritative execution artifacts unchanged before the
two-stock attempt succeeds. For `custom_wells_with_exclusions`, inspect
`well_picker_configured`: selected wells are `A1`, `A3`, `A4`, and `A6`, while
excluded `A2` and `A5` remain disabled and unassigned. The seed-4321 and
seed-1234 cases must retain the same reaction multiset and distinct catalog
assignments.

`capacity_plus_one_rejected` must show `Insufficient Well Capacity` with five
required reactions and four available wells.
`fixed_stock_exceeds_max_rejected` must show `Optimization failed` with fixed
35 mM exceeding max 20 mM for `Infeasible A`. For both, require byte-identical
draft state, no new or modified finalization-owned authoritative artifact, no
runtime activation, and zero durable-intent or simulator dispatch. Retain and
exactly replay visible representatives rather than reconstructing their
inputs manually.

Case seven, `zero_fill_missing_fill_rejected`, is a safeguard terminal rather
than an execution terminal. Inspect
`metrics.persistence.values.calibration_rejection_evidence`: the visible
preview must show zero reagent drops, the modal sequence must be
`Apply calibration as mode switch?` then `Apply failed`, the experiment
directory must remain byte-identical, and all intent/simulator/completion
counters must remain zero. Case eight,
`two_reagent_second_1_to_2_isolated`, completes reagent 1 before applying the
reagent-2 `1 -> 2` change. Inspect `dispense_count_evidence` and
`two_reagent_isolation`; require 48 unique commands, 72 total droplets, and
unchanged reagent-1 assignments, targets, calibration linkage, and progress.

The Milestone 9 closeout baseline at source commit `792a7b0` passed both
complete matrices and exact replays, visible `10 -> 9` and `10 -> 11` cases
and replays, lifecycle and host-regression suites and replays, and the default
Python suite. See
`docs/sil_interactive_simulation_milestone_9_slice_6_completion_record.md`
for exact retained paths and hashes. Those artifacts document the accepted
baseline; new changes still require a source-current selection and its emitted
replay.

The Milestone 10 closeout baseline at source commit `a373433` passed the
complete nine-case experiment-design matrix and exact replay, five visible
positive/negative representatives and replays, lifecycle and host-regression
suites and replays, and the default Python suite (`4146 passed, 88 skipped`).
See
`docs/sil_interactive_simulation_milestone_10_slice_6_completion_record.md`
for retained paths, hashes, source fingerprint, and limitations. The baseline
does not make historical artifacts a substitute for source-current
qualification.

## Randomized calibration/reload lifecycle

Use the singleton `randomized_calibration_reload_execution_v1` scenario when
a change can affect the join between experiment randomization, stock-specific
calibration, clean application-session reload, execution, or terminal
persistence. It creates the qualified seed-4321 multi-reagent design through
the real Qt editor, calibrates Design A across the 10 nL to 18 nL count
boundary, rotates into a clean application session, calibrates Water and
Design B, executes all three stock passes, and performs a third-session
completed read-only reload.

Inspect selection without executing:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 --dry-run
```

Run retained offscreen evidence:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root verification_reports\m11-s5\offscreen `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 180 `
  --qt-platform offscreen
```

Run visible Windows evidence:

```powershell
$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root verification_reports\m11-s5\visible `
  --seed 1 --speed-multiplier 20 --timeout-seconds 240 --visible
```

Execute the exact replay list printed in `summary.txt` and stored at
`run.replay_command`; do not reconstruct it from memory. For visible
replay, retain `QT_QPA_PLATFORM=windows` in the caller environment. The
qualified direct replay shapes are:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root <exact-output-root-from-report> `
  --seed 1 --speed-multiplier 1000.0 --timeout-seconds 180.0

$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario randomized_calibration_reload_execution_v1 `
  --output-root <exact-output-root-from-report> `
  --seed 1 --speed-multiplier 20.0 --timeout-seconds 240.0 --visible
```

Require the literal reaction mapping `A1:R8`, `A2:R6`, `A3:R3`, `A4:R2`,
`A5:R7`, `A6:R4`, `A7:R1`, `A8:R5`. Final keyed droplet counts are Design A
`1,1,1,1,1,1,1,1`, Design B `3,3,1,3,1,3,1,1`, and Water
`6,6,8,6,8,6,8,8` for wells A1 through A8. Require 24 unique intents and
completed simulator DISPENSE commands, 80 droplets, pass boundaries 8/16/24,
revisions 1-6, three distinct application-session IDs, zero dispatch in
sessions 1 and 3, and terminal `completed`/`analysis_only` state.

For failure triage, inspect the report, action/assertion ledgers, and evidence
manifest from the exact failed run before changing timeouts:

```powershell
$run = "<exact-run-directory>"
Get-Content -LiteralPath "$run\summary.txt"
Get-Content -LiteralPath "$run\report.json" | ConvertFrom-Json |
  Select-Object classification, source, workload, metrics
Get-Content -LiteralPath "$run\evidence_manifest.json" | ConvertFrom-Json
```

Cleanup is successful only when `scenario.teardown` passes, every application
recorder closes, `close_succeeded` is true, and `session_lock_present` is
false. Verify those fields in the retained report:

```powershell
$report = Get-Content -Raw -LiteralPath "<exact-run-directory>\report.json" |
  ConvertFrom-Json
$report.metrics.workflow.values.cleanup_results |
  Select-Object status, failure_message, evidence
```

Do not delete the retained run after validation. The Milestone 11 closeout
baseline at source commit `a385b1b` passed offscreen and visible direct runs
and exact replays, lifecycle and host-regression suites and exact replays, and
the default Python suite (`4192 passed, 90 skipped`). See
`docs/sil_interactive_simulation_milestone_11_slice_5_completion_record.md`
for retained paths, hashes, exact evidence, and limitations.

## Optimizer 360 calibration/reload host stress

Use `optimizer_360_calibration_reload_execution_v1` for changes that can affect
optimizer-selected stocks, high-cardinality randomized designs, repeated
calibration requantization, ID-keyed execution, or terminal reconstruction.
It is Windows-only and belongs only to `host_stress`; never select it through a
Pi lane.

Inspect and run offscreen evidence:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario optimizer_360_calibration_reload_execution_v1 --dry-run

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario optimizer_360_calibration_reload_execution_v1 `
  --output-root verification_reports\milestone_11a\offscreen_direct `
  --seed 1 --speed-multiplier 20 --timeout-seconds 600 `
  --qt-platform offscreen
```

Run visible Windows evidence:

```powershell
$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario optimizer_360_calibration_reload_execution_v1 `
  --output-root verification_reports\milestone_11a\visible_direct `
  --seed 1 --speed-multiplier 20 --timeout-seconds 900 --visible
```

Always run the emitted `run.replay_command` exactly. Require optimizer stocks
222.22222222222223, 100, 555.5555555555555, and 20; seven approximate and zero
unreachable targets; 360 assigned wells in rows A-O; all 24 row-P wells
unassigned; and five applied calibration records. Terminal evidence must show
pass boundaries 360/720/1080/1440/1800, 1,800 unique begins/attachments/
DISPENSE commands/completions, 46,208 droplets, revisions 1-8, three distinct
application sessions, no dispatch in sessions 1 and 3, and zero overflow,
discard, duplicate, or starvation evidence.

At the Milestone 11A closeout source, the new child passes in `host_stress`.
The complete aggregate remains red because the older 384x10 child compares its
per-stock 1300-1390 us fixture values with the existing fixed 1355 us stress
staging value. Retain that report as a separate finding; do not change the new
oracle, production behavior, or timeout to conceal it.

## Evidence layout and authority

Generated data remains beneath the ignored `verification_reports/` tree:

```text
verification_reports/
  suites/<selector>/<run>/
  matrices/<matrix>/<run>/
  exploration/<campaign>/<run>/
  virtual_workflows/pi-sil/<suite>/<run>/
```

For a suite, `selection_plan.json` records the requested order and
`aggregate.json` records each fresh child process, logs, result, and report
hash. Matrix and exploration runs use their corresponding plan and aggregate
schemas. The authoritative workflow evidence remains each child's report-v1
tree; aggregates reference and hash it instead of copying its contents.

Inspect at minimum:

- aggregate/plan selector, manifest hash, seed, source identity, and replay;
- child PID, return code, timeout state, stdout/stderr, and report hash;
- report classification, workload, actions, assertions, interaction surfaces,
  unexpected dialogs, errors, queue/starvation state, and teardown;
- screenshots for visible state and the `SIMULATION — NO HARDWARE CONNECTED`
  banner;
- evidence-manifest hashes and required snapshots/ledgers.

Never accept a successful process without exactly one valid matching report,
or a passing report whose process failed. Do not choose an arbitrary report
when discovery is missing or ambiguous.

## Exit codes and failure triage

- `0`: completed pass or warning; inspect warnings before acceptance.
- `2`: execution/evaluation completed with a failing, missing, incomplete, or
  stale result; retain all artifacts and follow the recorded reasons.
- `3`: planning, orchestration, validation, launch, or evidence-writing error;
  inspect parent output and child logs before rerunning.

`timeout` means the bounded child watchdog expired. `missing_report` and
`ambiguous_report` mean authoritative evidence could not be selected.
`identity_mismatch` includes workload, seed, source, platform, or Pi-safety
drift. An unexpected dialog, ambiguous write, stale state, or process/report
disagreement fails closed.

Reproduce a failure with the exact retained replay. Do not increase a timeout
until logs and progress evidence show a slow but advancing workload; do not
wait out a clearly stalled process merely because a larger watchdog remains.
If a correction changes an execution input, treat older reports as historical
and regenerate affected current-source evidence.

## Source freshness and capability coverage

The source-tree fingerprint covers tracked and non-ignored execution and
verification inputs. Documentation, retained reports, caches, and runtime
artifacts are excluded. A matching fingerprint establishes byte-level source
freshness for the current platform checkout; evidence age is informational and
never schedules a run.

Coverage evaluation uses only aggregates named explicitly by the operator:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --coverage-from <standard-aggregate.json> `
  --coverage-from <lifecycle-aggregate.json> `
  --coverage-from <host-regression-aggregate.json> `
  --coverage-from <host-stress-aggregate.json> `
  --output-root verification_reports\suites
```

Run the emitted coverage replay exactly. `pass`, `fail`, `incomplete`,
`missing`, and `stale` are distinct outcomes. Coverage never writes generated
status into the tracked manifest and cannot turn matrix or exploration
evidence into registered scenario coverage.

A Windows-only evidence set is expected to leave Pi-only capabilities
`incomplete`, so the combined evaluator can return nonzero even when every
Windows capability passes. Review the per-capability counts: a Windows closeout
requires zero failed, stale, or missing Windows capabilities. Validate Pi
capabilities separately from an authorized, source-current Pi aggregate and
bundle.

## Pytest temporary roots

SIL session tests intentionally reject any session root that overlaps the
repository. Therefore, do not place pytest `--basetemp` below
`verification_reports` or anywhere else in the checkout. The default Windows
pytest temp directory may also have inherited permission problems. Use a fresh,
explicit root below `%LOCALAPPDATA%\Temp\LabCraft`, for example:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  --basetemp "$env:LOCALAPPDATA\Temp\LabCraft\pytest-<purpose>-<unique-id>"
```

Use a new suffix for each invocation. Do not weaken the session repository-
overlap guard to accommodate an in-repository basetemp.

## Raspberry Pi safety

Pi execution requires separate authorization for the named host and workload.
Before access, confirm a clean checkout at the intended branch/commit and run a
wrapper dry run. The wrapper never updates code, installs packages, changes Pi
configuration, or cleans artifacts.

Only `pi_primary` and explicit `pi_stress` suite selectors may execute. Pi
capability selectors remain planning-only so they cannot select stress
indirectly. The complete aggregate parent and children remain inside one
Bubblewrap private-device, read-only-root, no-network boundary. Every child
must match the preflight, traced proof, source, Qt/Pi identity, proof/trace
hashes, and zero prohibited-device-access result.

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\run_pi_virtual_workflow.ps1 `
  -PiHost <authorized-host> -PiUser <authorized-user> `
  -Suite pi_primary -Seed 1 -SpeedMultiplier 100 -ReplaySuite -DryRun
```

Remove `-DryRun` only after authorization and exact-source confirmation. Suite
mode retrieves and validates one bundle containing the original and replay
aggregates. Remote evidence remains in place. Never run `pi_stress` merely as
part of ordinary primary qualification.

## Retention and future cleanup policy

Slice 8 implements no deletion or automatic retention timer. Until a separate
cleanup operation is approved:

- retain milestone, release, baseline, visible, replay, stress, and Pi
  qualification evidence referenced by a completion record;
- retain every failure until its cause and replacement evidence are reviewed;
- retain authoritative raw reports required by accepted baseline summaries;
- keep remote Pi roots until the retrieved bundle and every member hash have
  validated locally;
- never delete by glob, guessed timestamp, “latest” selection, or an
  unvalidated path.

A future cleanup operation must be separately approved, restricted to cleanup
roots from a validated manifest beneath `verification_reports/`, previewed
before execution, reject traversal/symlinks/overwrites, preserve tracked files
and accepted baselines, and report exactly what was removed and whether a
validated local copy remains. No such operation is authorized by this runbook.
