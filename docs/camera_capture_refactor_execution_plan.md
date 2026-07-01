# Camera Capture Refactor Execution Plan

> Working tracker for implementing the desired-state contract in
> `docs/camera_capture_refactor_contract.md`.
>
> This document tracks implementation slices, test gates, and proceed/rollback
> criteria. It should change as slices are completed. The contract should stay
> focused on the desired final behavior.

## Purpose

The camera capture refactor should move in small, reversible slices. Each slice
must leave the app in a valid state before the next slice starts.

Primary call path:

`UI/calibration process -> shared calibration capture policy -> CaptureCoordinator -> Controller -> Machine/camera backend -> firmware flash/trigger path`

This plan intentionally separates:

- design contract: `docs/camera_capture_refactor_contract.md`
- current-state map: `docs/camera_capture_life_cycle_map.md`
- risks and requirements: `docs/camera_capture_refactor_requirements.md`
- test strategy: `docs/camera_capture_test_strategy.md`
- execution status: this document

## Status Legend

| Status | Meaning |
| --- | --- |
| `not_started` | No implementation work has begun for this slice |
| `planned` | A concrete implementation plan exists for this slice |
| `in_progress` | Code/docs/tests are being changed |
| `blocked` | Work cannot proceed without a decision, hardware result, or prerequisite |
| `implemented` | Code is written and focused validation passed |
| `verified` | Required full validation and handoff checks passed |
| `deferred` | Intentionally postponed to a later milestone |

## Global Safety Rules

- Do not change firmware opcodes, message formats, GPIO pin mapping, motion
  commands, pressure command formats, or flash pulse timing unless a slice
  explicitly says firmware/protocol work is in scope.
- Do not remove the current force-close escape path until the replacement path
  has been validated on hardware.
- Do not let a slice widen the number of calibration capture paths. The target
  is one shared capture lifecycle with calibration-specific policy inputs.
- Do not collapse distinct outcomes into `frame is None`. Cancellation, timeout,
  busy, stale completion, flash fault, flash disarmed, and optical miss must stay
  distinguishable internally.
- For any firmware-touching slice, read `firmware/AGENTS.md` before editing and
  run the firmware validation required there.

## Global Proceed Gate

Before starting any implementation slice:

- Review the relevant current call path.
- Write a concrete slice plan with no more than eight implementation steps.
- List files to touch before editing.
- Identify focused tests to add or update.
- Identify manual/HIL checks if the slice affects hardware behavior.
- Confirm rollback is a small revert of that slice.

## Slice Status Summary

| Slice | Status | Scope | Required gate before next slice |
| --- | --- | --- | --- |
| 0. Baseline and guardrails | verified | Confirm starting tests and HIL baseline | Baseline recorded |
| 1. Typed request/result contract | verified | Add pure-Python dataclasses/enums and tests | Typed result tests pass |
| 2. Coordinator skeleton | verified | Add imported `CaptureCoordinator` module that delegates existing path | Coordinator unit tests pass with no behavior change |
| 3. Route Controller pending state | verified | Move Controller pending state through coordinator facade | Existing capture/cancel tests pass |
| 4. Typed cancellation and stale completion | verified | Replace ad hoc cancellation/stale handling internally | Cancellation/stale tests pass |
| 5. Shared calibration policy adapter | verified | Convert `_capture_with_policy` to typed results | Calibration policy tests pass |
| 6. Remove calibration capture bypasses | verified | Migrate direct calibration capture callbacks into shared policy | No direct calibration capture bypasses remain |
| 7. UI observes coordinator state | verified | Simplify imager UI pending/close state around coordinator | Close/force-close tests pass |
| 8. Machine request identity hardening | not_started | Carry request id/generation through camera worker payloads | Stale worker tests pass |
| 9. Flash session representation in Python | not_started | Represent arm/disarm/preflight states without firmware protocol change | Preflight/fault classification tests pass |
| 10. Firmware flash fault/latch surfacing | not_started | Surface flash faults and latched states as typed capture-blocking results | Python tests plus firmware/HIL plan ready |
| 11. Ready/busy ACK-line redesign | deferred | Future firmware/Pi contract change using existing ACK line | Separate firmware/HIL milestone approved |

## Slice 0: Baseline And Guardrails

Status: `verified`

Goal:

Record the starting point before code changes so regressions can be detected.

Call path:

`tools/run_selftest.py -> tools/camera_flash_benchmark.py -> firmware trigger/flash path -> camera detection`

Likely files touched:

- `docs/camera_capture_refactor_execution_plan.md`
- optionally a new baseline note under `docs/` if results need summarizing

Implementation notes:

- Record current focused Python test results.
- Record current HIL benchmark artifacts for:
  - `flash_only`
  - `print_then_flash` with `100 ms` minimum trigger period
  - `coordinated_flash` with `100 ms` minimum trigger period and gripper
    `5000 ms / 500 ms`
- Record known dirty working tree files before coding starts.

Accepted baseline:

- Baseline directory:
  `hil_reports/baselines/camera_capture_refactor_slice0_20260630/`
- Focused Python baseline:
  `71 passed in 3.41s`
- HIL baseline artifacts:
  - `flash_only`:
    `camera_capture_flash_only_20260630_184134.json`
    and `camera_capture_flash_only_20260630_184134_camera_benchmark.json`
  - `print_then_flash`:
    `camera_capture_print_then_flash_20260630_183339.json`
    and `camera_capture_print_then_flash_20260630_183339_camera_benchmark.json`
  - `coordinated_flash`:
    `camera_capture_coordinated_flash_20260630_173845.json`
    and `camera_capture_coordinated_flash_20260630_173845_camera_benchmark.json`

Accepted HIL result criteria:

- counted cycles completed: `100/100`
- ACK seen: `100/100`
- frames selected: `100/100`
- camera flash detections: `100/100`
- success cycles: `100/100`
- missed firmware flashes: `0`
- camera detection misses: `0`
- edge timeouts: `0`
- early abort: `false`

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py tests\test_droplet_camera_trigger_cleanup.py tests\test_flash_safety_ui.py tests\test_run_selftest_camera_benchmark.py`
- HIL benchmark reports saved on the Pi and copied into `hil_reports/` when
  intentionally preserving them.

Proceed criteria:

- Baseline results are written down. Complete.
- Any existing failures are classified as known baseline failures or fixed
  before refactor work begins. Complete.

Rollback:

- Documentation-only rollback if only notes are changed.

## Slice 1: Typed Request/Result Contract

Status: `verified`

Goal:

Create the pure-Python request/result vocabulary that later slices can consume
without changing runtime behavior yet.

Call path:

`calibration/UI request -> CaptureRequest -> CaptureResult -> legacy adapter`

Files touched:

- `FreeRTOS-interface/CaptureTypes.py`
- `tests/test_capture_types.py`

Behavior change:

- None intended for normal app behavior.
- Add typed statuses for at least:
  - `success`
  - `cancelled`
  - `timeout`
  - `busy`
  - `queue_rejected`
  - `backend_unavailable`
  - `recovery_succeeded`
  - `recovery_failed`
  - `flash_disarmed`
  - `firmware_flash_fault`
  - `firmware_flash_latched`
  - `firmware_flash_missed`
  - `flash_not_observed`
  - `stale_ignored`
  - `detached_force_close`
  - `internal_error`

Focused tests:

- Result factory/helper produces exactly one terminal status.
- `success` requires a frame.
- cancellation is terminal and not retryable.
- stale results are diagnostic and non-mutating.
- legacy adapter can translate typed failure to `None` for old callbacks.

Validation:

- Focused new tests:
  `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py`
  passed with `22 passed in 0.13s`.
- Regression tests:
  `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py tests\test_run_selftest_camera_benchmark.py`
  passed with `47 passed in 2.24s`.

Proceed criteria:

- Types are imported without Qt/hardware dependencies. Complete.
- Tests prove retryable/recoverable/cancelled/stale semantics. Complete.
- No existing runtime path depends on the new types yet. Complete.

Rollback:

- Delete the new type module and focused tests.

## Slice 2: Coordinator Skeleton

Status: `verified`

Goal:

Introduce an imported `CaptureCoordinator` module that owns lifecycle state but
initially delegates to the existing Controller/Machine path.

Call path:

`Controller.capture_droplet_image(...) -> CaptureCoordinator.request_capture(...) -> existing Controller delegate -> Machine.capture_droplet_image(...)`

Files touched:

- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CaptureCoordinator.py`
- `tests/test_capture_coordinator.py`
- `tests/test_optics_capture_metadata.py`

Behavior change:

- No intended operator-visible behavior change.
- Coordinator records state and request ids while legacy Controller code still
  performs most work.

Focused tests:

- Coordinator starts in `idle`.
- Request transitions `idle -> requesting`.
- Delegated success emits one terminal typed success.
- Delegated rejection emits one typed rejection.
- No second active request is accepted unless policy allows it.

Validation:

- Focused type/coordinator tests:
  `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py`
  passed with `32 passed in 0.18s`.
- Controller compatibility tests:
  `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py`
  passed with `27 passed in 2.08s`.
- Regression tests:
  `.\env\Scripts\python.exe -m pytest -q tests\test_droplet_camera_trigger_cleanup.py tests\test_flash_safety_ui.py tests\test_run_selftest_camera_benchmark.py`
  passed with `45 passed in 3.12s`.

Proceed criteria:

- Coordinator can be tested without hardware. Complete.
- Controller behavior remains compatible with existing tests. Complete.
- Public Controller API remains stable. Complete.

Rollback:

- Remove coordinator wiring and new module.

## Slice 3: Route Controller Pending State

Status: `verified`

Goal:

Move Controller pending capture state through the coordinator facade while
preserving existing public methods and signals.

Call path:

`Controller.capture_droplet_image -> coordinator active request -> Machine.capture_droplet_image -> Controller completion handler -> coordinator terminal result -> legacy callback/signal`

Likely files touched:

- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CaptureCoordinator.py`
- `tests/test_capture_coordinator.py`
- `tests/test_optics_capture_metadata.py`

Behavior change:

- Pending state has one owner.
- Existing callbacks/signals remain compatible.

Focused tests:

- Active pending capture rejects or queues according to existing behavior.
- Pending guard timer terminal failure clears coordinator state.
- Machine rejection clears coordinator state and invokes callback once.
- Late completion with mismatched request id does not mutate active state.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py` -> `35 passed in 0.21s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py` -> `29 passed in 2.10s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_refuel_camera_controller.py tests\test_app_update_request.py` -> `47 passed in 2.09s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_droplet_camera_trigger_cleanup.py tests\test_flash_safety_ui.py tests\test_run_selftest_camera_benchmark.py` -> `45 passed in 3.13s`
- `.\env\Scripts\python.exe -m pytest -q` -> `2678 passed, 24 skipped in 194.74s`

Proceed criteria:

- No duplicate pending flags can disagree in tested paths.
- Existing Stop/Close hardening tests still pass.

Rollback:

- Revert Controller/coordinator pending-state changes.

## Slice 4: Typed Cancellation And Stale Completion

Status: `verified`

Goal:

Replace ad hoc cancellation/stale completion handling with typed results
internally while preserving existing legacy callback behavior at boundaries.

Call path:

`Stop/Close -> Controller.cancel_pending_droplet_capture -> coordinator.cancel -> Machine recovery if needed -> typed cancelled/stale result -> calibration/UI adapter`

Likely files touched:

- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CaptureCoordinator.py`
- `tests/test_capture_coordinator.py`
- `tests/test_optics_capture_metadata.py`

Behavior change:

- Explicit cancellation becomes typed `cancelled`.
- Stale worker completion becomes typed `stale_ignored`.
- Legacy callbacks may still receive `None` through an adapter.

Focused tests:

- Cancel active capture invokes waiting callback once.
- Cancel when idle is idempotent.
- Cancelled capture is not retried by calibration policy.
- Late completion after cancellation is recorded as stale and ignored.
- Recovery failure after cancellation does not wedge pending state.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py` -> `38 passed in 0.24s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py` -> `30 passed in 2.13s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_refuel_camera_controller.py tests\test_app_update_request.py` -> `47 passed in 2.11s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_calibration_pressure_band_failure_modes.py` -> `30 passed in 1.83s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_droplet_camera_trigger_cleanup.py tests\test_flash_safety_ui.py tests\test_run_selftest_camera_benchmark.py` -> `45 passed in 3.15s`
- `.\env\Scripts\python.exe -m pytest -q` -> `2682 passed, 24 skipped in 184.17s`

Proceed criteria:

- Stop Calibration during pending capture releases the waiting calibration path.
- Close deferral and force-close tests still pass.

Rollback:

- Revert typed cancellation path while leaving type definitions if harmless.

## Slice 5: Shared Calibration Policy Adapter

Status: `verified`

Goal:

Convert `_capture_with_policy` into the calibration-facing adapter for the
shared typed capture policy.

Call path:

`BaseCalibrationProcess._capture_with_policy -> CalibrationManager.captureImageRequested or typed coordinator adapter -> Controller/coordinator -> typed result -> calibration retry/failure decision`

Likely files touched:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `FreeRTOS-interface/Controller.py` if signal adapter changes are needed
- focused calibration tests under `tests/`

Behavior change:

- Calibration retry decisions use typed statuses rather than `frame is None`
  plus callback attributes.
- Cancellation remains terminal.

Focused tests:

- Successful frame updates target attribute and emits capture completed.
- Timeout follows retry policy.
- Busy/retryable failure retries only when policy allows.
- `cancelled`, `flash_disarmed`, and `firmware_flash_fault` are terminal.
- Existing capture metadata remains intact.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_calibration_pressure_band_failure_modes.py` -> `37 passed in 7.55s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py` -> `30 passed in 5.47s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py` -> `38 passed in 0.49s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_refuel_camera_controller.py tests\test_app_update_request.py` -> `47 passed in 5.31s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_droplet_camera_trigger_cleanup.py tests\test_flash_safety_ui.py tests\test_run_selftest_camera_benchmark.py` -> `45 passed in 6.64s`
- `.\env\Scripts\python.exe -m pytest -q` -> `2689 passed, 24 skipped in 495.14s`

Proceed criteria:

- All existing `_capture_with_policy` users pass focused tests.
- No direct capture bypasses have been changed yet unless planned in this slice.

Rollback:

- Restore `_capture_with_policy` legacy callback interpretation.

## Slice 6: Remove Calibration Capture Bypasses

Status: `verified`

Goal:

Migrate remaining direct calibration capture callbacks into the shared capture
policy. The end state is zero calibration-specific direct capture routes.

Call path:

`direct calibration capture method -> shared calibration capture policy -> coordinator -> typed result -> calibration-specific success/failure handling`

Likely files touched:

- `FreeRTOS-interface/CalibrationClasses/Model.py`
- focused tests for nozzle focus and online stream calibration paths

Migration order:

1. `NozzleFocusCalibrationProcess._move_to_Y_clamped` direct recapture.
2. `OnlineStreamCalibrationProcess._start_single_flow_capture`.
3. `OnlineStreamCalibrationProcess._start_single_tail_capture`.

Behavior change:

- Direct paths no longer interpret local `frame` / `None` callbacks.
- Their unique metadata, recording, guard timeout, and flow/tail behavior become
  inputs to the shared policy.

Focused tests:

- Nozzle focus no-move recapture uses shared policy and handles cancellation.
- Online stream flow capture records success/failure metadata through shared
  policy.
- Online stream tail capture records success/failure metadata through shared
  policy.
- `rg "captureImageRequested.emit" FreeRTOS-interface\CalibrationClasses\Model.py`
  shows no calibration process bypasses except the shared adapter.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_calibration_focus_process_quality_gate.py tests\test_calibration_online_stream_process.py` -> `129 passed in 18.52s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_calibration_pressure_band_failure_modes.py` -> `37 passed in 4.56s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py` -> `30 passed in 4.84s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py` -> `38 passed in 0.44s`
- `.\env\Scripts\python.exe -m pytest -q` -> `2695 passed, 24 skipped in 411.12s`
- `rg "captureImageRequested\.emit" FreeRTOS-interface\CalibrationClasses\Model.py` -> one remaining emission in `_capture_with_policy`
- `git diff --check` -> passed

Proceed criteria:

- The only calibration capture emission is the shared adapter path. Complete.
- Metadata/recording behavior is unchanged in tests. Complete.

Rollback:

- Revert each bypass migration independently in reverse order.

## Slice 7: UI Observes Coordinator State

Status: `verified`

Goal:

Simplify droplet imager UI pending/close state so it observes coordinator state
instead of inventing separate capture truth.

Call path:

`DropletImagingDialog capture/stop/close -> Controller/coordinator state -> UI status/timers/deferred close`

Likely files touched:

- `FreeRTOS-interface/CalibrationClasses/View.py`
- `tests/test_optics_capture_metadata.py`
- possibly droplet imager UI tests

Behavior change:

- UI local flags become debounce/display state only.
- Close deferral waits on coordinator/calibration idle.
- Force-close remains available as an explicit last resort.

Focused tests:

- Manual capture button disables/re-enables from coordinator result.
- Close during capture requests cancellation and defers.
- Close timeout prompt still offers keep waiting and force close.
- Force close skips risky synchronous cleanup and marks dirty/detached.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py tests\test_optics_capture_metadata.py` -> `80 passed in 2.22s`
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py tests\test_droplet_imaging_summary_table.py tests\test_droplet_imaging_refuel_panel.py` -> `116 passed in 6.55s`
- `.\env\Scripts\python.exe -m pytest -q` -> `2707 passed, 24 skipped in 201.15s`
- `rg "_capture_request_pending" FreeRTOS-interface\CalibrationClasses\View.py` -> remaining uses are local mirror/setter/reset or accepted-request updates
- `git diff --check` -> passed

Proceed criteria:

- No UI test depends on stale local pending state. Complete.
- User can still close/force-close without blocking on camera cleanup. Complete.

Rollback:

- Revert UI observer changes.

## Slice 8: Machine Request Identity Hardening

Status: `verified`

Goal:

Ensure Machine/camera completions carry enough identity for the coordinator to
prove they belong to the active request.

Call path:

`Machine.capture_droplet_image -> DropletCamera.capture_with_retry_async -> worker completion payload -> Controller/coordinator result`

Likely files touched:

- `FreeRTOS-interface/Machine_FreeRTOS.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CaptureCoordinator.py`
- focused tests

Behavior change:

- Worker payloads include request id, generation, context, and timestamps.
- Stale completions are always ignored by identity check.

Focused tests:

- Matching request id/generation completes active request.
- Mismatched request id is `stale_ignored`.
- Mismatched generation is `stale_ignored`.
- Backend recovery increments generation or otherwise invalidates old workers.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py` -> 42 passed.
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py tests\test_droplet_camera_trigger_cleanup.py` -> 68 passed.
- `.\env\Scripts\python.exe -m pytest -q` -> 2717 passed, 24 skipped.
- Stale-worker identity search/coverage notes: focused tests cover same-request generation mismatch, missing generation when an expected generation is known, backend mismatch when both backend IDs are present, recovery requeue generation refresh, and Machine worker success/failure/stale payload identity fields.

Proceed criteria:

- Stale worker completion cannot update model, callback, or UI state. Complete.

Rollback:

- Revert payload identity changes and coordinator checks together.

## Slice 9: Flash Session Representation In Python

Status: `verified`

Goal:

Represent flash session arm/disarm/preflight state in Python without changing
firmware protocol yet.

Call path:

`coordinator request -> bounded firmware status/preflight check -> armed Python session state -> trigger/capture -> disarm on terminal result`

Likely files touched:

- `FreeRTOS-interface/CaptureCoordinator.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/Machine_FreeRTOS.py` if status access is needed
- focused tests

Behavior change:

- Coordinator may accept a logical request into `requesting`.
- It must complete bounded preflight before entering `capturing` or sending
  triggers.
- Preflight failure becomes typed `flash_disarmed`, `firmware_flash_fault`, or
  setup failure instead of a generic capture failure.

Focused tests:

- Preflight success enters `capturing`.
- Preflight timeout/failure does not send trigger.
- Stop/Close during preflight returns typed cancellation.
- Terminal success/failure disarms Python session state.
- Force-close marks dirty/detached and does not pretend the lower layer is
  clean.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_capture_types.py tests\test_capture_coordinator.py` -> 46 passed.
- `.\env\Scripts\python.exe -m pytest -q tests\test_optics_capture_metadata.py tests\test_flash_safety_ui.py tests\test_droplet_camera_trigger_cleanup.py` -> 76 passed.
- `.\env\Scripts\python.exe -m pytest -q` -> 2725 passed, 24 skipped.

Proceed criteria:

- No trigger is sent in tests unless Python session state is armed. Complete.
- Firmware protocol remains unchanged. Complete.

Rollback:

- Revert Python preflight/session-state checks.

## Slice 10: Firmware Flash Fault/Latch Surfacing

Status: `not_started`

Goal:

Surface firmware flash faults and latched trigger/ACK/busy/output states as
typed capture-blocking results.

Call path:

`firmware status/fault state -> Machine/Controller -> coordinator typed result -> calibration/UI handling`

Likely files touched:

- `FreeRTOS-interface/Machine_FreeRTOS.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/CaptureCoordinator.py`
- firmware files only if this slice is explicitly expanded into firmware work
- focused tests

Behavior change:

- Flash fault state blocks capture with a typed result.
- Latched states are not retried as ordinary camera failures.
- Stop/Close does not silently clear flash faults.

Focused tests:

- Existing flash fault blocks capture.
- Latched/faulted status maps to `firmware_flash_latched`.
- Cancellation does not clear fault state.
- UI/calibration receives clear terminal failure.

Validation:

- `.\env\Scripts\python.exe -m pytest -q tests\test_flash_safety_ui.py tests\test_optics_capture_metadata.py`
- If firmware is edited, run firmware host/build checks required by
  `firmware/AGENTS.md`.

Proceed criteria:

- Fault/latch outcomes are visible in diagnostics and cannot wedge pending
  capture state.

Rollback:

- Revert fault/latch mapping and any firmware edits in the same slice.

## Slice 11: Ready/Busy ACK-Line Redesign

Status: `deferred`

Goal:

Redesign the firmware/Pi ACK-line semantics so the existing line communicates
both flash-fired and ready-for-next-trigger state.

Call path:

`Pi trigger -> MCU trigger handler -> print/refuel/flash transaction -> ACK line rising edge for flash fired -> ACK line high while busy -> ACK line falling edge when ready`

Likely files touched:

- firmware flash/trigger/orchestrator files
- Pi GPIO trigger/ACK handling in the camera backend
- HIL benchmark tests and docs

Behavior change:

- LOW before trigger means ready/idle.
- Rising edge means flash fired.
- HIGH means transaction still busy.
- Falling edge means ready for the next trigger.
- Pi combines edge detection with level polling and bounded timeouts.

Required planning before implementation:

- Read `firmware/AGENTS.md`.
- Write a firmware/Pi protocol plan.
- Define host firmware tests before HIL.
- Define safe HIL tests that do not risk extended LED-on time.

Validation:

- Firmware host tests for disarmed trigger, max-on-time protection, busy latch,
  and ready transition.
- HIL tests for real ACK-line timing and camera flash detection.
- Full Python and firmware validation.

Proceed criteria:

- Separate milestone is approved.

Rollback:

- Revert firmware and Pi ACK-line semantic changes together.

## Per-Slice Plan Template

Before implementing a slice, create a short plan using this shape:

```text
Slice:
Call path:
Files to touch:
Behavior change:
Implementation steps:
Tests to add/update:
Validation commands:
Manual/HIL checks:
Proceed criteria:
Rollback:
```

## Full Refactor Acceptance Gate

Before considering the overall refactor complete:

- Focused coordinator/capture tests pass.
- Existing capture cancellation, close, and force-close tests pass.
- Calibration policy tests pass.
- HIL benchmark runner tests pass.
- Full Python suite passes:
  - `.\env\Scripts\python.exe -m pytest -q`
- Firmware host checks pass if firmware was modified.
- Pi HIL baseline passes:
  - `flash_only`
  - `print_then_flash` with `100 ms` minimum trigger period
  - `coordinated_flash` with `100 ms` minimum trigger period and gripper
    `5000 ms / 500 ms`

## Current Notes

- This plan starts with all slices unstarted.
- The first coding milestone should be Slice 0 followed by Slice 1.
- Slice 11 is intentionally deferred because it is a firmware/Pi contract change
  and needs its own safety plan.
