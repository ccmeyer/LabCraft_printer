# Camera Capture Refactor Vulnerabilities And Requirements

> Requirements artifact, not an implementation design.
>
> This document uses `docs/camera_capture_life_cycle_map.md` as the current-state
> baseline. Its job is to identify the vulnerabilities that the refactor must
> remove or contain, define the invariants that must hold afterward, and outline
> a safe sequence for getting there. It does not propose firmware, protocol,
> motion, or pressure-control changes.

## Purpose

The recent cancel, deferred-close, and force-close work added important escape
paths for stalled droplet captures. Those changes reduce operator lock-in, but
they do not eliminate the main structural risk: capture ownership is split
across UI flags, Controller pending state, calibration callbacks, machine camera
worker state, backend recovery, and firmware flash/trigger safety.

The refactor should make capture behavior deliberate instead of patch-driven.
The goal is not to make the capture stack larger. The goal is to make every
request have one owner, one request id, one terminal result, and one clear
cleanup path.

## Safety Constraints And Non-Goals

- Do not change firmware command formats, opcodes, parsing, or host/device
  protocol semantics as part of the first refactor pass.
- Do not change motion commands, pressure commands, print timing, or flash pulse
  timing as part of the first refactor pass.
- Do not remove the existing force-close escape path until a safer replacement
  is already validated.
- Do not require hardware to run unit tests for the Python capture coordinator.
- Preserve current operator-facing workflows unless a change is explicitly
  called out and reviewed.
- Treat firmware flash fault state as a separate safety domain. Python may
  surface it and block capture, but capture cancellation must not silently clear
  firmware safety latches.

## Vulnerability Register

| ID | Vulnerability | Current symptom | Required refactor response | Anchors |
| --- | --- | --- | --- | --- |
| V-001 | Split capture ownership across UI, Controller, calibration, Machine, and firmware | Stale UI pending flags, Controller pending state, and Machine worker state can disagree | Introduce one authoritative Python capture lifecycle owner below the UI, with UI/calibration observing results rather than owning partial state | `DropletImagingDialog._capture_request_pending`, `Controller.pending_capture_active`, `DropletCamera._capture_worker_active` |
| V-002 | Untyped failure contract | Capture failures are represented as `None` plus callback attributes like `_capture_rejection_reason` | Replace internal callback contract with a typed capture result while keeping compatibility adapters during migration | `Controller.cancel_pending_droplet_capture`, `BaseCalibrationProcess._capture_with_policy` |
| V-003 | Direct calibration capture bypasses shared policy | Some calibration processes emit `captureImageRequested` with local callbacks and do not use `_capture_with_policy` | Either route direct paths through the shared result policy or explicitly give them typed local policies | Direct `captureImageRequested` emissions in `CalibrationClasses/Model.py` |
| V-004 | Multiple timeout layers without one timeout owner | Calibration guard timers, Controller pending guard, Machine attempt timeout, and close retry timeout can race or mask each other | Define timeout ownership by layer and convert each timeout into a typed result or state transition | `_capture_with_policy`, `_on_pending_capture_timeout`, `capture_with_retry_sync`, `_retry_imager_close_after_stop` |
| V-005 | Stop/Close behavior depends on cleanup side effects | UI close can become part of capture cleanup, and force-close intentionally skips lower-layer cleanup | Separate "request cancellation", "observe idle", and "close UI shell" into explicit states | `DropletImagingDialog.closeEvent`, `Controller.stop_calibration` |
| V-006 | Late worker completions are possible after cancel/retry/close | Stale frames can arrive after Controller has cancelled, retried, or detached the UI | Preserve strict request id/generation checks and make stale completion an explicit non-mutating result | `_on_capture_completed_payload`, `DropletCamera` generation handling |
| V-007 | Backend recovery is defensive but not a full state transition | Recovery can run while the worker/backend is unwinding, and readiness is inferred | Model recovery as an explicit state with bounded entry/exit and a typed success/failure result | `Machine.recover_droplet_capture`, `DropletCamera.recover_stale_capture` |
| V-008 | UI pending state can remain latched independently | Buttons or close behavior can believe a capture is pending after Controller has already cleared or failed it | UI should derive pending/disabled state from coordinator state or receive one terminal event per request | `_capture_request_pending`, UI capture finished/failed handlers |
| V-009 | Calibration callback can wait indefinitely if no terminal result is delivered | A stalled capture can freeze calibration progress and make Stop/Close depend on capture cleanup | Every accepted calibration capture request must receive exactly one terminal result unless explicitly detached by force-close | `pending_capture_callback`, `captureImageRequested` |
| V-010 | Firmware flash fault is not a typed capture result | A flash fault blocks capture, but higher layers may treat it like a generic capture rejection/failure | Surface firmware flash fault as a distinct capture-blocked result in Python | `FlashSafety`, `Orchestrator::_latchFlashFault`, `tests/test_flash_safety_ui.py` |
| V-011 | Force-close creates a dirty lower-layer state by design | Operator can escape the imager, but camera/calibration state may remain unsafe for reuse until app restart | Keep force-close as a last-resort detached state and make the restart requirement explicit in state/result diagnostics | `_request_imager_force_close`, force-close `closeEvent` branch |
| V-012 | Diagnostics are spread across local logs/events | It is hard to reconstruct request id, worker generation, recovery, calibration state, and firmware fault status after a freeze | Add a single capture timeline/event record for each request and cleanup action | Controller calibration event recording, Machine capture payloads |

## Required Invariants

These are the behavioral rules the refactor should satisfy.

1. One Python component owns the active droplet capture lifecycle.
2. At most one droplet camera capture may be active for the physical camera at a
   time.
3. Every accepted capture request has a stable request id from acceptance until
   terminal result.
4. Every non-detached accepted request receives exactly one terminal result.
5. Terminal results are typed. Callers must not infer meaning from `frame is
   None` alone.
6. Stop Calibration and normal imager close cancellation are terminal user
   actions. They must not be retried as ordinary capture failures.
7. A stale worker completion must never update the model, invoke a waiting
   callback, or mutate the active request.
8. Backend recovery must be bounded and must return a typed success/failure
   result.
9. UI close must not synchronously stack risky camera shutdown on top of an
   already stalled capture.
10. Force-close must close only the imager UI shell, mark the imager session
    dirty/detached, and tell the operator to close and reopen the app before
    using the imager again.
11. Firmware flash fault state must remain independent from Python capture
    cancellation and must be surfaced as its own capture-blocking reason.
12. Tests must be able to drive timeout, cancel, stale completion, recovery, and
    force-close behavior without real hardware.

## Required Capture Result Contract

The refactor should introduce an internal typed result object before removing
legacy callback behavior. The exact class name can be decided during
implementation, but it should carry at least:

| Field | Requirement |
| --- | --- |
| `request_id` | Stable id assigned by the authoritative capture owner |
| `status` | One of the terminal or non-terminal statuses listed below |
| `frame` | Present only for successful image capture |
| `metadata` | Capture metadata, backend status, timing, and context when available |
| `reason` | Human/log-friendly reason string or enum for failure/cancellation |
| `retryable` | Whether the caller may automatically retry |
| `recoverable` | Whether backend recovery is appropriate |
| `source` | Layer that produced the result: controller, machine, backend, firmware, UI close, or calibration |
| `stale` | True only for ignored completions that must not mutate active state |
| `dirty_shutdown` | True when force-close detached the UI from lower-layer cleanup |

Minimum statuses:

| Status | Meaning |
| --- | --- |
| `success` | Frame captured and accepted for the active request |
| `cancelled` | Explicit Stop/Close cancellation |
| `timeout` | Timed out without a usable frame |
| `busy` | Rejected because another capture/worker is active |
| `queue_rejected` | Request was not accepted by Controller/Machine |
| `backend_unavailable` | Camera/backend is missing, closed, or failed to initialize |
| `recovery_succeeded` | Backend recovery completed and retry may proceed |
| `recovery_failed` | Backend recovery failed or did not reach retry-ready state |
| `firmware_flash_fault` | Firmware safety state blocks capture |
| `stale_ignored` | Late completion ignored because request id/generation no longer matches |
| `detached_force_close` | UI shell closed while lower layers may still be dirty |
| `internal_error` | Unexpected exception or inconsistent state |

## Desired Lifecycle Shape

The desired lifecycle should be small enough to test directly.

| State | Allowed entry | Allowed exit | Notes |
| --- | --- | --- | --- |
| `idle` | App start, terminal cleanup | `requesting`, `closed`, `dirty_detached` | UI may enable capture controls only when other prerequisites are satisfied |
| `requesting` | UI/calibration asks for a capture | `capturing`, terminal rejection | Assign request id and validate firmware/camera/preconditions |
| `capturing` | Machine accepts async capture | `succeeded`, `failed`, `recovering`, `cancelling` | One worker/generation owns camera backend activity |
| `recovering` | Timeout/cancel path requests backend recovery | `capturing`, `failed`, `cancelled` | Bounded and observable |
| `cancelling` | Stop Calibration or normal close cancellation | `cancelled`, `failed` | Must release calibration callback without waiting forever |
| `succeeded` | Matching frame accepted | `idle` | Updates model exactly once |
| `failed` | Terminal non-cancel failure | `idle` | Emits typed failure once |
| `cancelled` | Explicit user cancellation | `idle` | Does not retry through calibration policy |
| `dirty_detached` | Force-close selected | App restart only | UI shell closes; lower-layer state is not trusted for reuse |
| `closed` | Normal imager close after idle cleanup | Reopen imager | Normal cleanup completed |

## Layer Requirements

### UI Requirements

- The UI should request captures and render capture state, but should not be the
  authoritative owner of pending capture state.
- Manual capture, optics capture, Stop Calibration, normal close, deferred close,
  and force-close should all use the same typed state/result vocabulary.
- The UI may keep local button debounce state, but it must be cleared by the
  authoritative terminal result.
- Close behavior must remain two-stage:
  normal graceful cancellation first, explicit force-close only after bounded
  waiting and operator confirmation.
- Force-close must keep warning the operator to close and reopen the app before
  using the droplet imager again.

### Controller / Coordinator Requirements

- The Controller layer or a small component owned by it should be the
  authoritative Python capture coordinator.
- It should own request id assignment, active request state, terminal result
  emission, stale result rejection, cancellation, recovery, and diagnostics.
- It should expose a compatibility API for current callers during migration.
- It should emit one typed terminal result for every accepted non-detached
  request.
- It should treat explicit Stop/Close cancellation differently from retryable
  camera failures.

### Calibration Requirements

- `_capture_with_policy` should consume typed results instead of `frame or None`
  and callback attributes.
- Direct capture paths should either use `_capture_with_policy` or consume the
  same typed result contract.
- Calibration stop must not depend on the original camera worker finishing.
- Calibration retry decisions should be based on `status`, `retryable`, and
  `recoverable`, not on inferred local strings.

### Machine Camera Requirements

- Machine/Camera should include request id and worker generation in all async
  result payloads.
- Worker-active and backend recovery states should be observable to the
  coordinator without the UI querying backend internals.
- Recovery must invalidate stale workers and report a bounded, typed result.
- Camera worker completion should be able to report stale completion without
  mutating current state.

### Firmware Safety Requirements

- Firmware flash safety should remain independent and conservative.
- Python should surface latched flash fault as a typed capture-blocking result.
- The initial refactor should not change firmware flash trigger timing,
  `Printer::setFlashOnLast`, `FlashSafety`, or protocol messages.

### Diagnostics Requirements

- Each accepted capture should have a timeline containing request id, context,
  start time, current owner state, worker generation if available, recovery
  attempts, terminal result, and firmware fault status if relevant.
- Stop/Close/force-close should be captured as timeline events, not just UI
  status messages.
- Diagnostics should make it possible to answer: "Was the UI waiting on
  calibration, Controller pending state, worker/backend state, or firmware
  safety state?"

## Characterization Tests To Add Before Refactoring

These tests should lock down current intended behavior before architecture moves.

| Test area | Required coverage |
| --- | --- |
| Accepted request terminality | A calibration request receives exactly one terminal callback/result on success, timeout, cancellation, and queue rejection |
| Stop during stalled capture | Stop Calibration cancels pending capture, releases calibration wait, emits failure/cancel result, and ignores late worker completion |
| Close during stalled capture | Normal close defers, cancels capture, waits for idle, then resumes normal close prompt/cleanup |
| Force-close | Timeout prompt supports Keep Waiting and Force Close; Force Close skips risky camera cleanup and marks dirty/detached |
| Stale completion | Late success/failure from an old request id cannot update model or callback |
| Direct calibration paths | Direct `captureImageRequested` callbacks handle typed cancellation/failure consistently |
| Firmware flash fault | Latched flash fault blocks capture as a distinct result, not a generic busy/timeout |
| Backend recovery | Recovery success allows one controlled retry; recovery failure produces one terminal result |
| UI pending state | UI buttons/pending flags clear from terminal result and cannot remain latched after Controller clears pending |

## Suggested Refactor Sequence

1. Add characterization tests around the current high-risk scenarios without
   changing behavior.
2. Introduce a typed `CaptureResult` object and adapters that preserve existing
   callback APIs.
3. Centralize request id, terminal result, cancellation, stale completion, and
   diagnostics in a small Controller-owned coordinator.
4. Migrate `_capture_with_policy` to consume typed results.
5. Migrate direct calibration capture paths to the shared typed result contract.
6. Simplify UI pending/close state so it observes coordinator state instead of
   maintaining independent capture truth.
7. Tighten Machine camera payloads and recovery reporting around request id,
   generation, and typed recovery results.
8. Add firmware flash fault result plumbing in Python without changing firmware
   protocol or timing.

## Acceptance Criteria For The Refactor

- A stalled camera capture cannot leave a calibration callback waiting forever.
- Stop Calibration releases the UI and calibration process without waiting for a
  stalled camera worker to finish.
- Closing the imager during capture either completes graceful cleanup or reaches
  the explicit force-close path with a restart warning.
- Late worker completions are ignored and logged as stale.
- Firmware flash fault, camera busy, timeout, explicit cancellation, backend
  failure, and force-close dirty detach are distinguishable in tests and logs.
- UI pending state, Controller pending state, Machine worker state, and
  calibration state cannot disagree without a diagnostic event recording that
  disagreement.
- Existing manual preview, optics capture, calibration capture, refuel UI, and
  normal close flows continue to pass their focused tests.

## Open Decisions Before Code

- Should the coordinator live inside `Controller.py`, or should it be a small
  new module owned by Controller?
- Should typed results be delivered through Qt signals, callbacks, futures, or a
  compatibility layer that supports both signals and callbacks?
- Which direct calibration paths should be migrated first?
- Should force-close create a persistent dirty-session flag that prevents
  reopening the imager until app restart?
- How much diagnostic history should be retained in memory for field debugging
  on the Raspberry Pi?

