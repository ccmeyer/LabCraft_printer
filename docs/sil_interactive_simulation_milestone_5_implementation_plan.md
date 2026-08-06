# Milestone 5 — Manual Full-Lifecycle Characterization

## Summary

Baseline: clean worktree at
`130c47fb3e109b974cb4a687e2cc44c815c99196`; Milestones 1–4D are
complete.

Milestone 5 proves through the normal visible application that the simulator
supports complete printing workflows before the shared automation harness is
extracted in Milestone 6.

```text
Normal UI
  -> Controller
  -> ExperimentModel
  -> simulated command queue / SimMachine
  -> execution plan, calibration, refuel, progress, and resume writers
  -> retained-root process reload
  -> Experiment Editor
  -> authoritative reconciliation
```

This is a qualification-only milestone. It adds no application API, simulator
behavior, workflow automation, screenshot UI, schema, fixture, firmware,
protocol, hardware factory, camera, balance, or production-path change.
Evidence uses the existing retained trace and state exporter plus named Windows
screenshots. Each journey uses a separate fresh retained root.

## Implementation and Evidence Sequence

1. Record this frozen plan and mark the roadmap status
   `manual characterization in progress`.
2. Run the focused automated preflight. Do not run the full pytest suite.
3. Execute the one-stock droplet journey, including prepared reload,
   Stop After Well, process restart from `resume_ready`, resume, completion,
   and completed reload.
4. Execute the two-stock droplet journey with a real head exchange between
   passes.
5. Execute the mixed droplet/stream journey, including the real manual-refuel
   dialog, a five-droplet trial, and a Passed judgment for the stream stock.
6. Preserve each root, named screenshots, state snapshots, logs, synthetic
   artifacts, and a SHA-256 inventory. Never edit authoritative experiment
   files.
7. Classify every gap as framework, simulator, production seam, deferred
   physical behavior, or defect. Stop an affected journey and create a separate
   call-path diagnosis and correction plan before any fix.
8. Only after all gates pass, add the completion record, update the README and
   roadmap to complete, run final repository checks, and record the go/no-go
   decision for Milestone 6.

Tracked changes are limited to this plan, the eventual completion record,
README, and roadmap. Generated evidence remains in retained SIL roots.

## Manual Journey Definitions

All journeys use a shallow 384-well plate restricted to row A: 24 included
wells, one target dispense per active stock per well, and zero fill-stock
dispenses.

| Journey | Stock configuration | Expected completion | Required reloads |
|---|---|---:|---|
| One-stock droplet | One 9 nL droplet stock using the 1300 µs profile | 24 | Prepared, resume-ready, completed |
| Two-stock droplet | Stock 1 at 9 nL/1300 µs; Stock 2 at 18 nL/1800 µs | 48 | Completed |
| Mixed mode | Droplet stock first at 9 nL/1300 µs; stream stock second at 60 nL/2500 µs | 48 | Completed |

For every stock, use normal application controls to stage its matching head,
select and apply its print profile, generate/select/preview/Apply its synthetic
calibration, regulate the required pressures, wait for an empty queue, start or
resume printing, verify exact plan-derived counts, and return the completed
head through the rack UI.

For the stream stock, confirm that calibration makes manual refuel required.
Use the real manual-refuel dialog to exercise movement, refuel-only, print-only,
and one five-droplet trial. Select Stable, record Passed, and verify that only
the manual-refuel preflight clears.

The one-stock interruption sequence is:

1. Finalize and export the prepared state, then close.
2. Reopen the retained root and load through Experiment Editor.
3. Calibrate, stage, regulate, and start printing.
4. After at least six completed wells, click `Stop After Well`.
5. Wait for `resume_ready`, an empty queue, and a persisted checkpoint.
6. Export evidence and close cleanly.
7. Reopen, load through Experiment Editor, restage the head, and Resume Print.
8. Complete, export evidence, close, and reload once more to validate terminal
   state.

## Evidence and Acceptance Gates

Save named screenshots under:

```text
artifacts/manual-milestone-5/<journey-id>/
```

Capture the normal application and diagnostics at fresh session identity,
finalized preparation, each prepared or paused reload, each calibrated ready
state, printing, stop requested, resume ready, each stock-pass boundary and
head exchange, stream refuel required and Passed, terminal completion, and
completed reload. Use `Export State Snapshot` at the same stable boundaries.
After final closure, generate a SHA-256 inventory of the retained root while
excluding the inventory file itself.

Each journey passes only when:

- snapshot reconciliation is `ok` with zero mismatches;
- the command queue is empty at every stable boundary;
- UI guidance and task state agree with the active stock and lifecycle state;
- calibration identity, mode, pulse width, pressure, and volume agree with the
  execution plan;
- the mixed journey retains a matching Passed manual-refuel record;
- progress contains exactly 24 one-stock or 48 two-stock completions;
- plan revisions and calibration/refuel record IDs remain stable across reload;
- resumed printing does not repeat completed targets;
- terminal reload is reconstructed through Experiment Editor without prior
  in-memory state; and
- disconnect and close complete without a timeout or leftover process.

Direct JSON edits, fixture injection, Controller shortcuts, hidden Model
mutation, and the automated workflow runner are prohibited.

## Focused Validation

Run before visible testing:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulation_session.py `
  tests\test_sil_normal_ui_convergence.py `
  tests\test_sil_calibration_application.py `
  tests\test_sil_manual_refuel.py `
  tests\test_controller_print_guards.py `
  tests\system\test_sil_normal_ui_convergence_lifecycle.py `
  tests\system\test_virtual_workflow_lifecycle.py `
  tests\system\test_virtual_workflow_multi_stock_lifecycle.py `
  tests\system\test_virtual_workflow_authoritative_reload_lifecycle.py
```

Launch each fresh journey with:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --keep-session `
  --seed 1 `
  --speed-multiplier 2
```

Reopen with:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --session-root "C:\absolute\retained\session-root"
```

Final checks:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py --help
git diff --check
git status --short
```

Do not run the full pytest suite unless a separately approved correction
materially expands the affected surface.

## Completion Decision and Rollback

Milestone 5 completes only if all three journeys and every reload gate pass
without hidden workarounds. Deferred camera, balance, and physical-fluid
behavior remain explicit limitations but do not block automation extraction.

Any unresolved framework, simulator, production-seam, persistence, queue, or
UI defect produces a no-go decision for Milestone 6 until corrected and
revalidated.

Because this milestone changes documentation only, rollback removes its plan
and status documentation. Retained manual roots are generated evidence and
require no application, schema, firmware, protocol, or hardware rollback.
