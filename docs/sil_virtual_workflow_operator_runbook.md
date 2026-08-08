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
