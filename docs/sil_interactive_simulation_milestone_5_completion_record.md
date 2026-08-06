# Milestone 5 Completion Record

Milestone 5 is complete on the intentionally uncommitted worktree based on
`130c47fb3e109b974cb4a687e2cc44c815c99196`.

## Qualification result

The normal visible application completed all three required manual journeys
through the real UI, Controller, ExperimentModel, simulated command queue, and
authoritative execution writers. Each successful root was closed, reopened in
a new process, loaded through Experiment Editor, and reconciled without relying
on prior in-memory state.

| Journey | Retained root | Plan ID | Final revision | Completion |
|---|---|---|---:|---:|
| One-stock droplet | `20260806T173414957454Z-d34b950b36ff` | `289aca91-8fd0-487f-b83e-852f9089b798` | 4 | 24/24 |
| Two-stock droplet | `20260806T185750574411Z-146a3bf647d4` | `00514991-7434-4fc1-bd13-cec3532d710e` | 5 | 24 + 24 |
| Mixed droplet/stream | `20260806T194625202363Z-df33506470f8` | `bb608e13-efda-45a0-b4e9-6900b8b525ba` | 5 | 24 + 24 |

All three final plans are `completed`. Their resume checkpoints are `clean`
with zero intents. Each stock has exactly 24 added dispenses against 24 planned
dispenses. Every final session cleanup reported no errors and left no session
lock.

The one-stock root contains the prepared, safe stopped/resume-ready, resumed,
completed, and completed-reload boundaries. Resume did not repeat completed
targets. One unintended duplicate application launch is retained as an
operator/environment deviation; the three qualifying application sessions for
the prepared, resume-ready, and terminal gates all completed normally.

The two-stock root contains two distinct heads, authoritative 9 nL/1300 us and
18 nL/1800 us droplet calibrations, a real rack head exchange, exact 24 + 24
progress, and a completed analysis-only reload.

The mixed root contains two distinct heads and authoritative calibrations:

| Stock | Mode | Volume | Pulse width | Calibration record |
|---|---|---:|---:|---|
| `reagent-droplet_20.00_mM` | droplet | 9 nL | 1300 us | `74bc9a9f-ad4d-5ec5-9244-b590781a9277` |
| `reagent-stream_3.00_mM` | stream | 60 nL | 2500 us | `598e3c6d-28d6-560f-a6f6-0dc7ff1fb5a2` |

Its real manual-refuel dialog recorded `passed`, source
`sil_simulated_manual_refuel_check`, two paired trials, five trial droplets,
operator judgment `stable`, 2500 us print pulse, and 6000 us refuel pulse. The
stream pass started immediately after that sanctioned write and completed
without reloading or explicitly reactivating the execution.

The mixed terminal snapshot reported plan revision 5, `completed`, two applied
calibrations, one Passed refuel record, an empty command queue, a healthy
recorder, and reconciliation `ok` with zero mismatches. The reload snapshot
reproduced the same plan ID/revision and records as `analysis_only`. The design,
plan, progress, resume, and calibration-sidecar SHA-256 hashes remained
byte-identical across that reload.

## Focused corrections discovered during characterization

Three functional gaps stopped their journeys and received separate plans,
regressions, and fresh validation:

1. **Production seam - zero-target fill omission.** A finalized execution that
   required no fill stock could not apply a non-fill calibration. The calibrated
   target-count path now permits an absent fill stock only while the recalculated
   fill requirement remains zero, and fails closed if calibration would require
   a missing fill stock.
2. **Simulation adapter - multi-stock exact context.** Synthetic calibration
   incorrectly required one non-fill execution stock. It now selects the exact
   current head/stock identity while rejecting missing or ambiguous matches.
3. **Production seam - manual-refuel runtime synchronization.** A valid refuel
   outcome durably changed `execution_calibrations.json`, but the active runtime
   retained the old file identity. The writer now guards before persistence,
   accepts the new identity only after success, and updates the active cached
   calibration document. External sidecar changes still fail closed and are not
   overwritten.

The retained failure/deviation roots were not repaired or retried:

- `20260806T165651925531Z-edbea4a66eed` - zero-fill defect;
- `20260806T183623168760Z-c2fcb49be09e` - multi-stock adapter defect;
- `20260806T191023960919Z-7ae703378c6f` - manual-refuel runtime-sync defect;
- `20260806T185009520211Z-7daf003dedbb` - wrong-concentration operator configuration;
- `20260806T032903130569Z-2055f3023a2a` - earlier operator-error evidence.

## Automated evidence

The approved Milestone 5 preflight passed 155 tests with 5 skipped. Focused
correction gates then passed:

- zero-fill calibration: 55 passed;
- multi-stock calibration application: 65 passed, with 20 existing Qt warnings;
- manual-refuel runtime synchronization: 173 planned focused tests plus 6 SIL
  adapter/lifecycle tests passed.

The final runtime-sync commands were:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_initial_execution_plan_integration.py `
  tests\test_authoritative_execution_runtime_cache.py `
  tests\test_experiment_model_runtime_refresh.py `
  tests\test_controller_print_guards.py

.\env\Scripts\python.exe -m pytest -q `
  tests\test_sil_manual_refuel.py `
  tests\system\test_sil_stream_calibration_lifecycle.py
```

Python compilation and `git diff --check` passed after the correction. The full
pytest suite was not run because the frozen Milestone 5 plan explicitly limited
qualification to focused, directly affected tests on this Windows host.

## Evidence inventories

The complete roots remain under:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\
```

Inventory files and their own SHA-256 hashes are:

| Journey | Inventory SHA-256 |
|---|---|
| One-stock | `c0b358dfef6928663e6530eaf88c825267f6fc9f70b7299136f506a39d6944d2` |
| Two-stock | `2dc666cef9896327967bf86b948fd1079cfc612ca11e809eb4d59b4913b5ba82` |
| Mixed | `e6a519b6f2b03664fb43f124efed7b43d9b6cb0ae1a026722506d5992fa45b7d` |

The mixed final inventory contains 47 files and excludes only itself. Named
terminal and reload screenshots, canonical synthetic artifacts, complete JSONL
traces, exported snapshots, logs, and authoritative experiment files remain in
the retained root.

## Limitations and decision

This is application-contract qualification. It does not prove physical
droplet/stream quality, fluid observation, camera or balance behavior,
collision safety, firmware, protocol, GPIO, serial transport, Pi operation, or
performance.

There is a **go** decision for planning Milestone 6 shared-harness extraction.
Milestone 6 implementation must not begin until its concrete plan is created
and reviewed. Workflow migration, failure injection, performance remediation,
firmware, protocol, and hardware work remain outside this completion.

Rollback removes the Milestone 5 documentation and reverts the three focused
corrections with their tests. No retained experiment migration, schema
rollback, firmware rollback, protocol rollback, or hardware rollback is
required.
