# Milestone 9 Slice 9.6 — Qualification and Milestone Closeout

Status: implementation authorized (2026-08-08)

## Summary

Close Milestone 9 by qualifying the source-current eight-case calibration
requantization catalog, the preserved eight-case mixed-mode catalog, the
lifecycle suite, host regression, and the default Python suite. Retain and
inspect exact replay evidence, requalify one visible count-increase and one
visible count-decrease boundary, then mark Milestone 9 complete.

This is a qualification and documentation slice. It does not authorize
changes to production MVC, simulator behavior, firmware, protocol, tracked
fixtures, report-v1, matrix plans, aggregate schemas, or matrix catalogs.

## Frozen source and contracts

- Source commit for restarted qualification:
  `792a7b06a4bb8088319f522622dfd8a9e06dbd3b`.
- Worktree before restarted qualification: only this untracked
  implementation-plan document.
- `calibration_requantization_v1`: eight cases in frozen order, catalog
  SHA-256
  `d826a9e54c2e6190acfd5afdb0b2475de2be62557647aafa378890ca826c55af`.
- `mixed_mode_calibration_v1`: eight cases in frozen order, catalog SHA-256
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.
- Report-v1 and the matrix plan and aggregate schemas remain at version 1.

The implementation-plan document is excluded from the workflow source-tree
fingerprint. Any source change discovered to be necessary during
qualification stops this slice and requires a separate reviewed correction.
The independently reviewed cross-session evidence correction is commit
`792a7b0`; all earlier pre-correction qualification is historical and cannot
satisfy this closeout.

## Call paths

```text
Matrix closeout
CLI matrix selector
→ generic matrix registry and plan validation
→ fresh child process per case
→ real Qt/Controller/Model calibration and execution journey
→ SimulatedMachine completion or expected fail-closed boundary
→ report-v1 and matrix aggregate validation
→ exact aggregate replay

Compatibility closeout
CLI suite selector
→ validated capability manifest plan
→ fresh child process per scenario
→ existing lifecycle or 96-well host-regression journey
→ report-v1 and suite aggregate validation
→ exact aggregate replay
```

## Implementation steps

1. Capture clean source identity, matrix listings, and deterministic dry-run
   plans before execution.
2. Run the complete requantization and mixed-mode matrices offscreen, then
   execute each aggregate's retained replay command exactly.
3. Run `droplet_volume_increase_10_to_9` and
   `droplet_volume_decrease_10_to_11` visibly on the Windows Qt platform at
   20× with a 120-second watchdog, then execute both retained replay commands
   under the same Qt environment.
4. Run the complete lifecycle and host-regression suites offscreen, then
   execute each aggregate's retained replay command exactly.
5. Run the default Python suite exactly once using a fresh external
   `%LOCALAPPDATA%\Temp\LabCraft` base temporary directory and a tool timeout
   of at least 15 minutes. Do not enable the unrelated analysis pipeline.
6. Inspect aggregate, child, report, assertion, dialog, hardware-isolation,
   count-oracle, terminal-reload, and teardown evidence. Calculate retained
   aggregate and representative report hashes.
7. Add the Slice 9.6 completion record and update README, the SIL operator
   runbook, and the master plan with exact results and replayable evidence.
8. Run `git diff --check`, confirm the diff is documentation-only, and commit
   independently as `test: close calibration requantization SIL milestone`.

## Qualification commands

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90 `
  --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix mixed_mode_calibration_v1 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 1000 --timeout-seconds 90 `
  --qt-platform offscreen

$env:QT_QPA_PLATFORM = "windows"
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 `
  --case droplet_volume_increase_10_to_9 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 20 --timeout-seconds 120 --visible

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --matrix calibration_requantization_v1 `
  --case droplet_volume_decrease_10_to_11 `
  --output-root verification_reports\matrices `
  --seed 1 --speed-multiplier 20 --timeout-seconds 120 --visible

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite lifecycle --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --suite host_regression --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000 --qt-platform offscreen

.\env\Scripts\python.exe -m pytest -q --basetemp <fresh-external-temp-path>
```

Execute every retained aggregate or visible-case replay command exactly. The
replay is a separate source-current run and must produce a new valid aggregate
or report.

## Acceptance criteria

- Both matrices pass 8/8 cases in fresh child processes and pass exact
  aggregate replay.
- Every positive requantization case reconciles prepared, preview, plan,
  progress, runtime, intent, simulator, and terminal counts to its independent
  catalog oracle.
- The grouped, fill, completed-terminal reload, and two-reagent isolation
  cases retain their specialized evidence and exact cardinalities.
- The missing-fill safeguard retains a byte-identical authoritative boundary
  and zero intent, simulator, or completion dispatch.
- Visible execution and exact replay prove `10 → 9` and `10 → 11` across all
  count layers.
- Lifecycle passes 8/8 scenarios and replay; host regression passes its
  96-well journey and replay.
- Each accepted child has return code zero, no timeout, exactly one matching
  valid report, correct source/catalog/case identity, clean teardown, no
  prohibited hardware access, and no process/report disagreement.
- The complete default Python suite passes once.
- Representative success, completed reload, safeguard failure, reagent
  isolation, mixed-mode, and manual-refuel evidence is manually inspected and
  recorded.

## Failure policy and rollback

- Retain any failure and reproduce it with the exact emitted replay before
  classification. Do not increase a timeout unless evidence proves continued
  forward progress.
- A production or SIL defect requires a separate reviewed correction plan and
  independent commit. After any source change, restart all Slice 9.6
  qualification so accepted evidence shares one source identity.
- Host stress, Pi qualification, firmware checks, physical hardware, release
  operations, and the opt-in analysis pipeline are excluded.
- Refill-required/resume remains deferred while authoritative volume tracking
  is disabled. Existing soft-stop/reload lifecycle scenarios do not expand
  that scope.
- Rollback reverts only the Slice 9.6 documentation/closeout commit. Slices
  9.1–9.5 and historical ignored evidence remain intact.
