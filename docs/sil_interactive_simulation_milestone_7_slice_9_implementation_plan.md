# Milestone 7 Slice 9 - Composed Mid-Array Disconnect Fail-Closed

Status: `implemented and validated`

Baseline: `fb6730823801b81674ee26e9736dbead09a6a980`, with a clean
worktree and Milestone 7 Slice 8 complete.

## Objective

Add `print_array_disconnect_mid_array_24_v1` as a composed lifecycle
journey. It must create and start the normal 24-well workflow through Qt,
disconnect through the normal connection control after exactly six durable
completions, prove the simulated queue and durable pending intents are safely
retired, retain an explicit `ready_to_resume` recovery boundary, and produce
normal report-v1 evidence.

## Call Path

```text
QTest connection-button click
  -> ConnectionWidget.request_machine_connect_change()
  -> SimulationSession.disconnect_simulator()
  -> Controller.disconnect_machine()
  -> SimulatedMachine.disconnect_board()
  -> machine_connected_signal(False)
  -> Controller.update_machine_connection_status(False)
  -> confirmed simulated intent reconciliation / array interruption
  -> MachineModel.disconnect_machine()
  -> retained recovery evidence / teardown
```

Only canonical simulation with a disconnected, drained simulator may discard
the intent IDs attached to canceled look-ahead work. Physical or otherwise
unconfirmed disconnection retains ambiguous intents and remains blocked.

## Frozen Contract

- trigger the normal UI disconnect at completion 6;
- retain exactly six completed stock/well pairs and cancel two look-ahead
  intents in one durable discard batch;
- reach Controller `resume_ready`, ACTIVE plan, authoritative
  `ready_to_resume`, disconnected/unhomed machine state, and a required
  `machine_disconnect` dock check;
- observe 250 ms with no completion or persisted-progress change;
- emit no array completion, unexpected dialog, or error;
- retain `editor_opened`, `generated`, `ready`, `printing`, `disconnected`, and
  `recovery_ready` screenshots plus the standard report, ledgers, hashes,
  events, seed, replay command, and teardown evidence;
- classify the expected fail-closed result as `pass` only when every required
  assertion passes.

## Gates And Exclusions

Run focused unit/system tests, a fast offscreen run, one visible Windows run,
and its exact emitted replay. Because this is the final Milestone 7 migration,
run the complete Python suite once only after those gates pass. Do not add a
legacy disconnect runner, protocol/firmware behavior, Pi operation, hardware
work, performance remediation, seeded exploration, or general fault
injection.

## Risks And Rollback

The primary risk is falsely discarding uncertain physical work; simulation
identity and queue-drained checks therefore fail closed. Exact-trigger
overshoot is rejected rather than tolerated. Rollback removes this scenario,
its reusable actions and tests, and the bounded Controller correction while
returning `execution.disconnect_fail_closed` to `planned`; existing journeys,
report v1, simulator behavior, protocol, firmware, and hardware are unchanged.

## Approved-Scope Validation Amendment

The first visible qualification reached `recovery_ready` in six seconds but
then blocked before report creation. A bounded `faulthandler` diagnostic traced
the block to `ApplicationComponents.close()`: hiding the visible window
committed the focused pressure editor after disconnect, which attempted a
simulator command and opened a modal error dialog. The implementation therefore
also touches `FreeRTOS-interface/ApplicationComposition.py` and
`tests/test_safe_application_construction.py`. Cleanup now blocks signals from
the view and its child QObjects before hide/delete, with a regression proving a
queued child UI commit cannot become a teardown command. This cleanup-only
correction changes no live workflow, machine timing, protocol, firmware, or
hardware behavior.

The final full-suite gate exposed a second test-only isolation issue: Qt
dialogs intentionally constructed by earlier modules remained visible in the
session-scoped QApplication and were later, correctly, rejected by harness
dialog guards. `tests/conftest.py` now hides and deferred-deletes all top-level
widgets after each test that requests `qapp`, with signals blocked during that
cleanup. This makes each Qt test own its windows and changes no application or
workflow runtime.
