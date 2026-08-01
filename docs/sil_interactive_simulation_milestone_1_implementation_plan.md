# Milestone 1 Interactive SimulationSession Implementation Plan

Date: 2026-07-28  
Parent plan: `docs/sil_interactive_simulation_and_composable_workflows_plan.md`

Status: `complete`
Completed: 2026-07-31
Completion record:
`docs/sil_interactive_simulation_milestone_1_completion_record.md`

## Goal

Launch and manually operate the real application MVC stack in a contained,
hardware-isolated simulation session. The application must create its normal
configuration, experiment, progress, and calibration-memory files through the
same writers used in production.

This milestone does not add synthetic calibration, state-event JSONL,
composable workflow migration, failure injection, firmware/protocol changes,
Pi operations, or physical-hardware behavior.

## Call Path

```text
Simulator Control
  -> SimulationSession.connect_simulator()
  -> Controller.connect_machine("SIMULATED")
  -> SimulatedMachine.connect_board("SIMULATED")
  -> machine signals
  -> Model
  -> MainWindow
```

Normal motor, home, pressure, movement, and gripper requests continue through
the existing UI and Controller methods. Disconnect and connected-window close
return through `Controller.disconnect_machine()`,
`SimulatedMachine.disconnect_board()`, and the existing disconnect-complete
signal.

## Interfaces And Behavior

### `SimulationSessionConfigV1`

The immutable configuration owns:

- visible versus hidden launch and owned versus borrowed `QApplication`;
- fresh versus explicitly retained roots;
- optional retained experiment identity, recorded but not automatically loaded;
- instance-local seed and simulator speed multiplier;
- interactive dialog policy and reserved automation deadline;
- clean-fresh deletion versus explicit retention;
- source identity and the required `simulation` runtime identity.

Invalid seed/timing, relative retained paths, broad roots, repository or
production-data overlap, nonempty unmarked roots, containment escapes, and
non-simulation identity fail before real application construction.

### `SimulationSession`

The reusable session provides:

- `create(config)`;
- `launch()`;
- owned-Qt `run()`;
- `connect_simulator()` and `disconnect_simulator()`;
- point-in-time `snapshot(reason)` in the session document; and
- idempotent `close()`.

It owns the application roots, per-root lock, `QApplication` policy, real MVC
components, `SimulatedMachine`, simulator control dock, session document,
launcher log, and teardown. It does not own experiment logic or write normal
experiment artifacts.

### Interactive CLI

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py
.\env\Scripts\python.exe tools\run_simulated_app.py --keep-session
.\env\Scripts\python.exe tools\run_simulated_app.py --session-root "C:\path\to\retained-session"
.\env\Scripts\python.exe tools\run_simulated_app.py --seed 1 --speed-multiplier 2
```

The launcher has the distinct `LabCraft Simulator` Qt identity and does not
acquire the production single-instance lock. It prints the selected root and
hardware-blocked identity. `--session-root` implies retention; experiments are
loaded manually through the existing Experiment Editor.

## Root And Artifact Policy

Fresh roots default to:

```text
%LOCALAPPDATA%\LabCraft\SIL\interactive-sessions\<timestamp>-<uuid>\
```

Each root contains:

```text
session.json
session.lock
logs/
artifacts/
config/
experiments/
calibration-memory/
```

`session.json` uses `labcraft.sil_simulation_session` version 1 and records the
stable session ID, source/runtime identity, relative application roots,
containment proof, hardware-disabled flags, simulator seed/timing/port,
application-session history, artifact map, latest explicit snapshot, terminal
status, and cleanup state.

Clean fresh roots are deleted unless `--keep-session` is selected. Explicit,
reopened, failed, or incompletely cleaned sessions remain available for
diagnosis. Metadata writes use resolved absolute paths and one atomic
temp-write/replace attempt; ambiguous Windows failures are not retried or
masked.

## Implementation Steps

1. Add the frozen configuration, root validation, lock, schema-v1 metadata,
   atomic writer, and fresh/retained lifecycle.
2. Build the real current-profile MVC components exclusively through
   `simulation_dependencies()` and the explicit simulated-machine factory.
3. Permit exact `SIMULATED` connect and simulator disconnect in the
   Controller while preserving every production and physical-only guard.
4. Add the non-closable `SIMULATOR CONTROL — NO HARDWARE` dock with connection
   buttons and current simulator-state projection.
5. Add the dedicated launcher and exact retained-root commands.
6. Add focused configuration, containment, lifecycle, Controller, UI, file
   ownership, teardown, and CLI tests.
7. Run focused and full Python validation, then record completion only after
   the visible Windows and Slice 0.1 repetition gates pass.

## Acceptance

- Only the literal `SIMULATED` sentinel can connect in simulation.
- No production machine, serial, camera, balance, updater, GPIO, firmware, or
  qualification factory is invoked.
- The normal UI can connect, enable/home, regulate, move, operate the gripper,
  disconnect, and close without waiting for the close timeout.
- All application data remains beneath the selected session root and all
  tooling metadata remains outside experiment directories.
- Reopening preserves the session ID, adds an application-session record, and
  leaves experiment loading to the existing UI.
- Teardown is idempotent and leaves no active simulator or known application
  cleanup timers.
- Existing virtual-workflow report-v1 and scenario behavior remain compatible.

Focused validation:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_simulation_session.py `
  tests\test_simulator_control.py `
  tests\test_simulated_app_launcher.py `
  tests\test_safe_application_construction.py `
  tests\test_mainwindow_closeevent.py
```

Final automated validation:

```powershell
.\env\Scripts\python.exe -m pytest -q
git diff --check
```

The visible Windows gate additionally requires one manual fresh/retained
launcher exercise and the Slice 0.1 repetition set: five 24-well smoke runs,
three two-stock runs, and three reload/resume runs without checkpoint access
failures.

## Implementation Validation Status

Automated implementation validation completed on 2026-07-28:

- launcher `--help`: passed;
- Python compilation for the new runtime and tests: passed;
- focused Controller and Milestone 1 suite: 46 passed;
- clean full Python suite: 3,675 passed, 38 skipped, 190 existing Qt
  deprecation warnings;
- `git diff --check`: passed.

The visible fresh/retained Windows exercise completed on 2026-07-30. The
Slice 0.1 repetition set completed on 2026-07-31 with five clean 24-well smoke
runs, three clean two-stock runs, and three clean reload/resume runs. Every run
reconciled its terminal plan/progress/resume state without a checkpoint access
failure. Milestone 1 is complete; see the completion record linked above.

## Risk And Rollback

The only production MVC edit is the runtime-context branch that accepts
`SIMULATED` and disconnects the injected simulator. Production connection
classification and every hardware-facing path remain unchanged.

Rollback reverts the Milestone 1 commit: remove the launcher/session/control
package and tests, restore the prior Controller simulation guard, and remove
the documentation additions. Never include production or retained experiment
data, accepted baselines, release metadata, tags, or history in cleanup.
