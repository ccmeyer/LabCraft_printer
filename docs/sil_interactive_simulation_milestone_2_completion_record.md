# SIL Interactive Simulation Milestone 2 Completion Record

Status: `complete`

Completed: 2026-07-31

Planning baseline: `ecc8cf7`

Implementation commit: not created; the worktree remains intentionally
uncommitted for user review.

Related documents:

- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_2_implementation_plan.md`
- `docs/sil_state_trace_schema_v1.md`
- `docs/sil_interactive_simulation_milestone_1_completion_record.md`

This record is authoritative for Milestone 2 status.

## Outcome

Milestone 2 is complete. The interactive hardware-isolated simulator now owns
a bounded state recorder, complete append-only JSONL trace, cross-layer
snapshots, deterministic action/command/snapshot correlation, queued
reconciliation, and a visible read-only State Inspector. Recorder failure
retains and fails the simulation session without changing application or
hardware-safety state.

The observed path is:

`existing Qt signals -> SimulationStateObserver -> StateProjectionBuilder -> StateRecorder -> contained state artifacts -> read-only StateInspectorDock`

The recorder does not wrap Controller/Model decisions, write an experiment,
repair state, select production dependencies, or access firmware/protocol or
physical hardware.

## Implementation Scope

Runtime implementation:

- `tools/sil/state_recorder.py`
- `tools/sil/state_projection.py`
- `tools/sil/state_observer.py`
- `tools/sil/inspector.py`
- `tools/sil/session.py`
- `tools/sil/control.py`
- `tools/sil/__init__.py`

Focused validation:

- `tests/test_sil_state_recorder.py`
- `tests/test_sil_state_projection.py`
- `tests/test_sil_state_observer.py`
- `tests/test_sil_state_inspector.py`
- `tests/test_simulation_session.py`
- `tests/test_simulator_control.py`

Documentation:

- `docs/sil_state_trace_schema_v1.md`
- `README.md`
- the concrete plan and parent-roadmap status records
- this completion record

No production MVC, firmware, protocol, release, accepted-baseline, Pi, camera,
balance, calibration-generation, workflow-migration, failure-injection, or
performance-remediation file changed.

## Schema And Artifacts

Each application launch writes:

```text
artifacts/state/<application_session_id>/
  events.jsonl
  latest_snapshot.json
  terminal_snapshot.json
```

The JSONL schema is `labcraft.sil_state_event` version 1. Snapshot files use
`labcraft.sil_state_snapshot` version 1. The session metadata remains
`labcraft.sil_simulation_session` version 1 and adds backward-compatible,
relative recorder artifact pointers per application session.

Default bounds are a 512-event memory tail, 64 changed fields, 2,048-character
strings, 100 collection entries, and depth 8. JSONL remains complete when the
memory tail evicts. Explicit and terminal snapshots use one same-directory,
flushed/fsynced replace attempt; failures are not retried.

## Automated Validation

Focused Milestone 2/Milestone 1 acceptance command:

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

Result: 51 passed.

Full repository validation:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Result: 3,694 passed and 38 skipped in 826.82 seconds. Reported warnings were
the existing Qt chart deprecations.

Additional checks passed:

- launcher `--help`;
- Python compilation for all Milestone 2 runtime modules;
- `git diff --check`; and
- focused source/import hardware-isolation regression.

## Visible Windows Retained And Reopen Gate

Commands:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py --keep-session
.\env\Scripts\python.exe tools\run_simulated_app.py `
  --session-root "C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260801T032615434879Z-3ab2dc39f14f"
```

Retained root:

```text
C:\Users\conar\AppData\Local\LabCraft\SIL\interactive-sessions\20260801T032615434879Z-3ab2dc39f14f
```

Stable session ID: `e6f517464df648a59aa50bc27b9aa1f9`.

The visible exercise used the persistent simulation identity/control surfaces,
normal Experiment Editor, exact `SIMULATED` connection, enable/home, pressure
regulation, virtual movement, gripper operations, explicit snapshot export,
disconnect, and normal close. Each launcher process exited with code 0 and no
leftover-process timeout. Session metadata records hardware access as false,
terminal status completed, and cleanup complete.

The first two visible traces did not contain an explicit manual-export action.
They were preserved unchanged. A third reopen completed the missing action and
recorded three `export_state_snapshot` actions with corresponding
`manual_export` snapshots. This was not an ambiguous write failure; no failed
write was retried or overwritten.

## Trace And Reconciliation Evidence

| Application session | JSONL events | Memory retained | Evicted | Terminal reconciliation | Purpose |
| --- | ---: | ---: | ---: | --- | --- |
| `8df4ca1d53c64560a35b83d233fe6f9e` | 690 | 512 | 178 | `ok` | full visible exercise |
| `067c471f411e4563b8d8d1786693861f` | 375 | 375 | 0 | `ok` | retained-root reopen |
| `80237e8a05084429947472e60b704ebb` | 384 | 384 | 0 | `ok` | explicit-export completion |

For every trace, metadata event count equals parsed JSONL line count, sequence
numbers are strictly increasing from 1, recorder status is closed, and the
last two events are `cleanup_completed` then `recorder_stopped`.

The first trace SHA-256 remained unchanged across both reopens:

```text
750BDC55AF9BC4D03E65A45ED2A603B1CD1360A90EC56B917E59245EF6821DE7
```

The full first run recorded connection, command lifecycle, machine state,
experiment load, rack transitions, persisted snapshots, disconnect, teardown,
and cleanup. Its settled pre-cleanup and terminal reconciliations are `ok`.
Three intermediate mismatches were retained rather than hidden:

- one motor-enabled signal-order transition; and
- two expected-versus-actual rack transitions while a confirmed head moved
  between a slot and the gripper.

All three settled in later snapshots. No terminal mismatch or recorder failure
occurred. Both snapshot files parse as schema v1 and all metadata artifact
pointers are contained relative paths.

## Failure Containment Evidence

Focused tests force a single snapshot replace failure and prove:

- exactly one replace attempt;
- same-directory temporary evidence is retained;
- recorder health and session status fail with the first error;
- observer slots are removed and further recorder writes stop;
- simulator/application state is unchanged;
- the root is retained; and
- normal teardown continues without selecting hardware or retrying the write.

No failure occurred during the visible gate, so there is no visible-gate
failure root to list.

## Known Limitations

- The recorder observes existing signals; it does not wrap every developer UI
  action, so some UI actions have command correlation without an action ID.
- Reconciliation intentionally records transient mismatches before layers
  settle and never repairs them.
- Persistence hashing occurs only for explicit/launch/load/terminal captures;
  high-frequency events reuse the last persistence projection.
- The inspector is evidence UI, not a controller and not a performance tool.
- The evidence does not validate collision safety, pressure response, camera
  output, firmware, protocol, or physical motion.

## Risks And Rollback

Rollback removes only the four simulation-owned recorder/projection/observer/
inspector modules, their additive session/control integration, focused tests,
and Milestone 2 documentation/status fields. Previously retained traces remain
inert evidence. Do not remove production experiments, accepted baselines,
release metadata, tags, firmware, protocol code, or Milestone 1 evidence.

Milestone 3 remains separate. Do not begin synthetic calibration until a
concrete Milestone 3 implementation plan is reviewed and approved.
