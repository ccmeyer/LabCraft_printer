# SIL Interactive Simulation Milestone 1 Completion Record

Status: `complete`

Completed: 2026-07-31

Source commit: `37644074f50c3541b9beb7f3d657f62726c98ba1`

Related documents:

- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `docs/sil_interactive_simulation_milestone_1_implementation_plan.md`
- `docs/sil_interactive_simulation_slice_0_1_windows_checkpoint_investigation.md`

This record is authoritative for Milestone 1 status.

## Outcome

Milestone 1 is complete. The dedicated launcher and reusable
`SimulationSession` operate the real application MVC stack in contained,
hardware-isolated sessions. The visible Windows and Slice 0.1 repetition gates
passed without invoking a production hardware factory, accepting a physical
port, or weakening authoritative persistence.

The validated application path is:

`tools/run_simulated_app.py -> SimulationSession -> real MainWindow -> Controller -> Model -> injected simulator -> normal persistence writers`

No application, firmware, protocol, calibration, report-schema, accepted
baseline, Pi, release, or hardware behavior changed while completing the
manual gates.

## Visible Windows Gate

The target-host exercise used:

```powershell
.\env\Scripts\python.exe tools\run_simulated_app.py --keep-session
```

Retained root:

```text
%LOCALAPPDATA%\LabCraft\SIL\interactive-sessions\20260730T180305611032Z-0039453ef45a
```

The exercise confirmed:

- both persistent simulation-identity surfaces were visible;
- the production connection widget was disabled;
- Simulator Control connected only through the exact `SIMULATED` sentinel;
- enable/home, regulation, movement, and gripper operations used the normal
  Controller path;
- disconnect and close completed without a timeout or leftover process;
- schema `labcraft.sil_simulation_session` version 1 metadata retained
  containment and all hardware-access denials; and
- cleanup completed without errors while explicitly retaining the root.

The root was reopened with `--session-root`. Its metadata records two completed
application sessions. The existing Experiment Editor created and loaded
`Untitled-20260730_110326`; its audit records another `experiment_loaded`
event during the reopened session with the same execution-plan identity.

## Persistence Preflight And Retained Failure

The earlier ambiguous failure remains preserved and was not retried:

```text
verification_reports/virtual_workflows/milestone1_gate_3764407/
  smoke/virtual_print_array_24_v1/
  20260730T180342875060Z_37644074f50c
```

After repair of host NTFS corruption, a fresh repository-local control
completed 3,000 absolute, same-directory, flushed and fsynced atomic
replacements with byte verification and no temporary leftovers.

The Codex managed ACL helper still fails while applying temporary deny-read
rules. Normal repository ACLs, ordinary Windows persistence, and the approved
SIL launcher path pass outside that tooling layer. No ACL reset, path
workaround, persistence retry, or application change was used.

## Slice 0.1 Repetition Gate

The repaired-host gate ran sequentially on 2026-07-31. Every failure would
have stopped the gate and retained its root; no retry was required.

| Scenario | Required | Result | Resume fsyncs/run | Progress fsyncs/run |
| --- | ---: | ---: | ---: | ---: |
| `virtual_print_array_24_v1` | 5 | 5/5 pass | 72 | 24 |
| `print_array_multi_stock_24x2_v1` | 3 | 3/3 pass | 144 | 48 |
| `authoritative_reload_resume_24_v1` | 3 | 3/3 pass | 75 | 24 |
| **Total** | **11** | **11/11 pass** | **1,017 total** | **336 total** |

Commands used the registered scenario IDs, speed multiplier 1000, timeouts of
120 seconds for smoke and 180 seconds for two-stock/reload, and these ignored
roots:

```text
verification_reports/virtual_workflows/milestone1_gate_3764407_postrepair_canary
verification_reports/virtual_workflows/milestone1_gate_3764407_postrepair
```

All reports were classified `pass`. Smoke completed 24/24 wells, two-stock
completed 48/48 stock/well operations and both passes, and reload/resume
reopened the authoritative execution through the real Experiment Editor before
completing 24/24. Every run retained zero terminal intents and reported no
checkpoint access denial, unexpected dialog, timeout, queue starvation,
hardware access, or teardown failure.

## Automated Validation

Implementation-time validation at the source commit recorded:

- launcher `--help`: passed;
- Python compilation: passed;
- focused Controller and Milestone 1 suite: 46 passed;
- clean full Python suite: 3,675 passed and 38 skipped; and
- `git diff --check`: passed.

Completion-time validation on 2026-07-31 recorded:

- focused Controller and Milestone 1 suite: 46 passed;
- launcher `--help`: passed;
- Python compilation for the Milestone 1 runtime: passed; and
- `git diff --check`: passed.

The full suite was not repeated for this documentation-only completion update,
as required by the handoff.

## Milestone 1 Gate

The Milestone 1 gate is satisfied:

- fresh and retained visible Windows sessions pass;
- only `SIMULATED` connects and production connection is disabled;
- normal Controller-driven home, regulation, movement, and gripper pass;
- Experiment Editor load and retained-root reopen pass;
- containment, locking, retention, failure preservation, and idempotent cleanup
  remain intact;
- the 5/3/3 repetition set passes with exact durable-write counts and terminal
  reconciliation; and
- automated implementation validation remains clean.

The next task is the concrete Milestone 2 plan. Do not begin the state recorder,
synthetic calibration, workflow migration, failure injection, firmware/protocol
work, Pi operations, or performance remediation under this record.

## Risks And Rollback

The prior checkpoint failure remains valid retained evidence. General Windows
stability remains under observation; any future host crash should preserve
`MEMORY.DMP` and must not justify weakening SIL durability. The managed Codex
ACL helper remains an environment concern, not a Milestone 1 application
change.

Rollback reverts only this record and the two status edits. It must not remove
the implementation, retained session, failed or passing evidence, production
data, accepted baselines, release metadata, tags, or history.
