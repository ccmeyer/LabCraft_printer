# Camera Capture Refactor Contract

> Desired-state contract, not an implementation patch.
>
> This document defines how the droplet imager capture lifecycle should behave
> after refactoring. It builds on the current-state map in
> `docs/camera_capture_life_cycle_map.md`, the vulnerability register in
> `docs/camera_capture_refactor_requirements.md`, and the layered validation
> strategy in `docs/camera_capture_test_strategy.md`.

## Purpose

The capture stack should stop depending on scattered boolean flags, implicit
`None` callbacks, and cleanup side effects. After refactor, every accepted
capture request should have one authoritative Python owner, one stable request
id, one visible lifecycle, and one typed terminal result.

This contract is intentionally conservative. The first refactor pass should not
change firmware opcodes, command formats, motion commands, pressure commands,
flash pulse timing, or normal print/refuel timing.

## Scope

In scope:

- Python request ownership from UI/calibration through Controller/Machine.
- Typed capture states and terminal results.
- Stop, close, cancellation, timeout, stale completion, and recovery behavior.
- Python handling of firmware flash fault and HIL camera benchmark outcomes.
- Future design requirements for separating flash timing from ready-for-next
  semantics.

Out of scope for the first implementation pass:

- Firmware protocol changes.
- Firmware flash trigger timing changes.
- Hardware pin remapping.
- Motion, pressure, print/refuel command format, or regulator behavior changes.
- Removing the existing force-close escape path.

## Current Baseline

The current HIL baseline for refactor acceptance is:

| Lane | Command characteristics | Expected result |
| --- | --- | --- |
| `flash_only` | SAFE profile, fixed flash settings, warm-up excluded | All counted triggers ACK, select frames, and detect flash |
| `print_then_flash` | FULL profile, post-selftest, `100 ms` minimum trigger period | `ext_count_delta == flash_num_delta == requested_cycles` and camera detections equal requested cycles |
| `coordinated_flash` | FULL profile, post-selftest, `100 ms` minimum trigger period, gripper `5000 ms / 500 ms`, pressure target `0.6 psi` | 100/100 firmware flashes and 100/100 camera detections |

The most recent coordinated baseline artifact was:

- `hil_reports/camera_capture_coordinated_flash_20260630_173845_camera_benchmark.json`
- `hil_reports/camera_capture_coordinated_flash_20260630_173845.json`

It passed with:

- `firmware_trigger_observed_cycles = 100`
- `firmware_flash_success_cycles = 100`
- `camera_flash_detected_cycles = 100`
- `missed_flash_cycles = 0`
- `camera_detection_miss_cycles = 0`
- `early_abort.triggered = false`

## Core Semantics

The refactor must keep these concepts distinct:

| Concept | Meaning | Current ambiguity to remove |
| --- | --- | --- |
| Capture request accepted | Python coordinator has accepted ownership of a request and assigned a request id | UI, Controller, and Machine can currently disagree about pending state |
| Flash session armed | Python and firmware have both entered a bounded flash-capable session | A stray Pi trigger or stale firmware state must not be able to fire the flash |
| Trigger accepted by firmware | MCU observed and accepted a hardware trigger | Current Python code does not model this directly outside the HIL artifact |
| Flash fired | Firmware flash output fired and ACK edge was produced | Current ACK also tempts the host to infer readiness, which is not always true |
| Frame selected | Camera backend returned a post-trigger frame candidate | Frame selected is not proof that flash was optically observed |
| Flash observed by camera | Selected frame passed optical flash detection | Firmware success and optical success can differ |
| Transaction ready | Firmware/camera/coordinator are ready for another trigger/request | Current ACK pulse is not a reliable ready-for-next-trigger signal |
| Terminal result delivered | The accepted Python request has exactly one result for its caller | Current `None` callback patterns can be ambiguous |

## Ownership Model

The refactor should introduce one authoritative Python capture coordinator in a
small imported module adjacent to `Controller.py`. `Controller` remains the
adapter between UI/model signals and the coordinator, but the coordinator owns
the capture lifecycle contract.

| Layer | Desired role |
| --- | --- |
| UI | Request captures, render coordinator state, offer Stop/Close/Force Close, avoid owning capture truth |
| Calibration process | Request a capture and consume typed results for retry/stop/failure policy |
| Controller | Adapt UI/model signals and legacy APIs to the coordinator |
| CaptureCoordinator module | Own active request id, state, cancellation, timeout, stale completion, backend recovery, and terminal result emission |
| Machine/Camera | Execute camera work for a request id/generation and report typed payloads |
| Firmware | Own flash safety, trigger acceptance, flash firing, print/refuel completion, and faults |

The UI may keep local debounce state, but it must clear that state from the
coordinator result rather than independently deciding that capture is done.

## Calibration Capture Policy Contract

All calibration capture requests should go through one shared capture policy and
typed result contract. The refactor should treat direct
`captureImageRequested.emit(...)` calls with local `frame` / `None`
interpretation as migration debt, not as intentional parallel capture paths.

Calibration processes may still customize capture behavior by passing policy
inputs to the shared layer:

- capture context and role,
- retry count and retry delay,
- guard timeout,
- warm-up or discard behavior,
- metadata builder,
- success callback,
- final failure callback,
- stop/cancellation behavior.

Those customizations must not bypass the shared owner for:

- request id assignment,
- pending-state ownership,
- timeout classification,
- stale completion rejection,
- cancellation semantics,
- backend recovery,
- flash arm/preflight,
- terminal typed result emission.

The practical target is not that every calibration calls the exact same
one-line helper. The target is that every calibration capture is governed by the
same lifecycle contract and can be tested through the same coordinator/result
surface.

## Capture State Machine

The Python coordinator state machine should be small enough to test without
hardware.

| State | Entry | Exit | Required behavior |
| --- | --- | --- | --- |
| `idle` | App start or terminal cleanup | `requesting`, `closed`, `dirty_detached` | No active request id |
| `requesting` | UI/calibration asks for capture | `capturing`, terminal rejection | Validate prerequisites and assign request id |
| `capturing` | Machine/camera accepts work | `succeeded`, `failed`, `recovering`, `cancelling` | Exactly one active request/generation owns the worker |
| `recovering` | Timeout/stale backend path enters recovery | `capturing`, `failed`, `cancelled` | Bounded recovery with typed result |
| `cancelling` | Stop Calibration or graceful close requests cancellation | `cancelled`, `failed` | Release waiting calibration callback promptly |
| `succeeded` | Matching frame accepted | `idle` | Update model once and emit terminal success |
| `failed` | Terminal non-cancel failure | `idle` | Emit typed failure once |
| `cancelled` | Explicit user cancellation | `idle` | Do not retry as an ordinary capture failure |
| `dirty_detached` | Force-close confirmed | App restart only | UI shell closes; lower-layer state is not trusted |
| `closed` | Normal close after idle cleanup | Reopen imager | Cleanup completed normally |

Allowed transitions should be explicit. A stale worker completion must not move
the active state machine.

## Request Contract

Every accepted request should carry:

| Field | Requirement |
| --- | --- |
| `request_id` | Stable id from acceptance through terminal result |
| `context` | Manual preview, optics scale bar, calibration name, refuel capture, or diagnostic lane |
| `source` | UI, calibration process, diagnostic runner, or internal retry |
| `created_at_monotonic` | Start timestamp for timeout and diagnostics |
| `timeout_policy` | Coordinator-level timeout and lower-layer attempt timeout references |
| `cancellation_policy` | Whether Stop/Close may cancel and whether cleanup/recovery is required |
| `retry_policy` | Whether automatic retry is allowed, and who owns the decision |

At most one active physical droplet camera request may exist at a time.

## Result Contract

Internal capture callers should receive a typed result object. The exact Python
class name can be chosen during implementation, but it should include:

| Field | Requirement |
| --- | --- |
| `request_id` | Matches accepted request id |
| `status` | One terminal status from the table below |
| `frame` | Present only for successful image capture |
| `metadata` | Camera metadata, timing, request context, and diagnostics |
| `reason` | Stable human/log reason or enum token |
| `retryable` | True only when the caller may automatically retry |
| `recoverable` | True only when backend recovery is appropriate |
| `source` | Layer that produced the result |
| `stale` | True only for ignored completions that did not mutate active state |
| `dirty_shutdown` | True after force-close/detached UI closure |

Minimum terminal statuses:

| Status | Meaning | Retry policy |
| --- | --- | --- |
| `success` | Frame captured and accepted for active request | Not applicable |
| `cancelled` | Explicit Stop/Close cancellation | Do not retry |
| `timeout` | Timed out without a usable frame | Retry only if policy says so |
| `busy` | Rejected because another capture/worker is active | Retryable only for explicit busy policy |
| `queue_rejected` | Request was not accepted by coordinator/machine | Usually retryable after backoff |
| `backend_unavailable` | Camera/backend missing, closed, or failed to initialize | Recoverable if backend recovery is allowed |
| `recovery_succeeded` | Backend recovery completed and retry may proceed | Internal/non-terminal for caller unless exposed diagnostically |
| `recovery_failed` | Backend recovery failed | Terminal failure |
| `flash_disarmed` | Trigger or capture requested while flash session is not armed | Do not fire; caller may request a new session |
| `firmware_flash_fault` | Firmware safety state blocks capture | Do not clear via capture cancellation |
| `firmware_flash_latched` | Firmware detected stuck trigger, stuck ACK, stuck busy state, or flash output protection fault | Do not retry until explicit recovery/clear |
| `firmware_flash_missed` | Firmware saw trigger but did not produce flash/ACK | Diagnostic/HIL result; retry depends on lane |
| `flash_not_observed` | Firmware flash/ACK occurred but camera did not detect flash | Retry depends on optical policy |
| `stale_ignored` | Late completion ignored by request id/generation | Non-mutating diagnostic |
| `detached_force_close` | UI shell closed while lower layers may be dirty | App restart required |
| `internal_error` | Unexpected exception or inconsistent state | Terminal failure |

Compatibility adapters may temporarily translate these results back to legacy
`frame` / `None` callbacks, but internal policy should use typed statuses.

## Cancellation Contract

Stop Calibration and graceful imager close are explicit user cancellation
actions.

Requirements:

- Cancellation must transition the coordinator to `cancelling`.
- Waiting calibration callbacks must receive exactly one terminal `cancelled`
  result unless the UI has intentionally entered `dirty_detached`.
- Cancellation must invalidate the active request id/generation so late worker
  completions are stale.
- Backend recovery after cancellation must be bounded and diagnostic.
- Cancellation must not silently clear firmware flash faults.
- Cancellation must not be retried as an ordinary camera failure by calibration
  capture policy.

## Close And Force-Close Contract

Normal close:

1. Stop preview/UI timers.
2. Ask the coordinator to cancel active capture if one exists.
3. Ask calibration to stop if active.
4. Wait for coordinator/calibration idle through bounded asynchronous retry.
5. Run normal close prompt and cleanup.

Force-close:

1. Requires explicit operator confirmation.
2. Closes only the imager UI shell.
3. Skips risky synchronous camera/controller cleanup.
4. Emits/records `detached_force_close`.
5. Marks the imager session dirty and tells the operator to close and reopen the
   app before using the imager again.

Force-close must remain a last-resort escape hatch until the refactor has a
validated safer replacement.

## Stale Completion Contract

Machine/camera completions must carry enough identity to prove they belong to
the active request:

- `request_id`
- worker generation or backend generation
- capture context
- completion timestamp

If the identity does not match the active request, the coordinator must:

- record a `stale_ignored` diagnostic,
- avoid model updates,
- avoid invoking the active callback,
- avoid changing active state.

## Timeout Ownership

Timeouts should be layered but not ambiguous.

| Timeout | Owner | Result |
| --- | --- | --- |
| Request acceptance timeout | Coordinator | `queue_rejected` or `busy` |
| Camera frame/worker timeout | Machine/Camera, reported to coordinator | `timeout` or `backend_unavailable` |
| Coordinator pending guard | Coordinator | `timeout`, then optional `recovering` |
| Calibration retry deadline | Calibration policy | Retry/stop decision from typed result |
| Close deferred wait | UI close controller | Keep waiting, normal close, or force-close prompt |
| HIL trigger/ACK timeout | Benchmark only | `firmware_flash_missed` / edge timeout classification |

No caller should infer timeout meaning from `frame is None` alone.

## Firmware And Trigger Semantics

Current firmware behavior must be treated accurately:

- The MCU-to-Pi ACK edge means the flash fired.
- The ACK edge does not guarantee the print/refuel transaction is complete.
- The host must not infer "ready for next trigger" from the flash ACK alone.
- A physical trigger edge must not be sufficient to fire the flash unless an
  explicit flash session is armed.
- HIL `print_then_flash` and `coordinated_flash` should continue using the
  minimum trigger period baseline until a future ready signal is designed.

## Flash Arming And Safety Contract

The refactor must make flash arming a first-class state shared by Python and
firmware. The safe default is always disarmed.

Flash session requirements:

- The flash may only fire inside an explicit flash session created for a
  calibration, droplet imaging, or diagnostic capture lane.
- A session must have a session id or generation, owner/context, monotonic start
  time, bounded lifetime, expected trigger count or trigger policy, and maximum
  flash-on duration.
- Python must only drive trigger pulses and monitor flash ACKs while its active
  capture session is armed.
- Firmware must ignore or reject trigger edges while disarmed. If the GPIO/ISR
  remains enabled for implementation reasons, the handler must exit before
  enqueueing print/flash work when the session is disarmed.
- Boot, normal idle, calibration stop, imager close, timeout, cancellation,
  backend recovery failure, force-close, and firmware flash fault must all leave
  the firmware flash session disarmed with the flash output low.
- Rearming after a terminal fault must require an explicit setup/recovery path;
  Stop/Close must not silently clear flash faults.

Maximum-on-time requirements:

- The firmware, not the UI, owns the final maximum flash-on duration cap.
- Any path that sets the flash output high must have a guaranteed bounded path
  that sets it low again.
- The low transition should be enforced by a hardware timer or equivalent
  firmware safety primitive, not only by a long-running application task
  completing successfully.
- If the firmware detects that the flash output, trigger state, ACK state, or
  flash busy state is latched beyond the allowed window, it must force the flash
  output low, disarm the session, enter a typed fault state, and reject further
  triggers until explicit recovery.

Latched or wedged states to identify during refactor:

| Possible latch/wedge | Required handling |
| --- | --- |
| Pi trigger line stuck high or rapidly retriggering | Firmware ignores/rejects while disarmed or busy; Python reports typed failure |
| MCU ACK line stuck high or low | Python times out/classifies ACK state; firmware session does not stay armed indefinitely |
| Flash output stuck high or high longer than maximum duration | Firmware forces low, disarms, records `firmware_flash_latched` or flash fault |
| Firmware flash/print busy flag never clears | Session watchdog disarms and reports fault instead of accepting more triggers |
| Print/refuel pressure wait never reaches ready | Transaction timeout disarms session and reports typed timeout/fault |
| Queue command accepted but flash session setup never becomes active | Coordinator reports setup failure and does not send triggers |
| Camera worker stalls while firmware session is armed | Coordinator cancellation/timeout disarms or requests disarm before recovery |

The refactor does not need to solve every firmware detail in the first Python
slice, but the Python contract must represent these outcomes explicitly so they
are not collapsed into generic `None` callbacks or UI hangs.

Future design direction:

The future ready-for-next-trigger design should reuse the existing physical ACK
line as a state signal rather than adding another channel. The desired
semantics are:

- LOW before trigger means ready/idle.
- Rising edge means flash fired.
- HIGH means flash fired but transaction still busy.
- Falling edge after the rising edge means transaction complete and ready for
  the next trigger.

The Pi side should combine edge detection with level polling and bounded
timeouts so a missed edge does not wedge the host-side state machine.

This is not part of the first Python refactor. If implemented later, it must be
handled as a firmware/Pi contract change with HIL validation.

## HIL Result Semantics

The refactor should preserve the distinction now present in the camera
benchmark:

| HIL classification field | Meaning |
| --- | --- |
| `firmware_trigger_observed_cycles` | MCU status `ext_count_delta` |
| `firmware_flash_success_cycles` | MCU status `flash_num_delta` |
| `missed_flash_cycles` | Trigger observed but no firmware flash |
| `disarmed_trigger_ignored_cycles` | Trigger attempt occurred while session was not armed and did not fire flash |
| `latched_or_faulted_cycles` | Firmware reported a latched trigger/ACK/busy/output fault |
| `camera_flash_detected_cycles` | Camera selected a bright flashed frame |
| `camera_detection_miss_cycles` | Firmware flash occurred but selected frame was not bright |
| `edge_timeout_cycles` | Pi did not see ACK edge within timeout |

Python capture results should preserve the same separation:

- firmware/trigger failure is not the same as optical detection failure,
- optical detection failure is not the same as backend unavailability,
- cancellation is not the same as timeout.

## Diagnostics Contract

Each accepted capture should produce a compact timeline:

| Event | Required details |
| --- | --- |
| `request_created` | request id, context, source |
| `request_accepted` | active state, timeout policy |
| `flash_session_arm_requested` / `flash_session_armed` | session id/generation, context, limits |
| `flash_session_disarmed` | reason and final firmware state |
| `worker_started` | request id, worker/backend generation |
| `trigger_wait_started` | if applicable |
| `frame_received` | request id, metadata, timing |
| `result_emitted` | typed status, reason, retryable/recoverable |
| `cancel_requested` | source: Stop, Close, Force Close, internal |
| `recovery_started` / `recovery_finished` | recovery diagnostics |
| `stale_completion_ignored` | stale id/generation |
| `firmware_fault_seen` | fault token, latch classification, and block reason |

The timeline should make it possible to answer which layer was blocking:

- UI close/deferred close,
- calibration policy,
- coordinator pending state,
- machine worker/backend,
- firmware flash safety,
- pressure/print/gripper HIL path.

## Implementation Slices

The refactor should move in small reversible slices:

1. Add `CaptureResult` and `CaptureRequest` dataclasses/enums plus tests.
2. Add a `CaptureCoordinator` in its own imported module. It should initially
   delegate to the existing Controller/Machine path.
3. Route Controller pending state through the coordinator while preserving the
   existing public API.
4. Convert cancellation and stale-completion handling to typed results.
5. Convert `_capture_with_policy` to consume typed results and become the
   calibration-facing adapter to the shared capture policy.
6. Migrate direct calibration capture callbacks into the shared capture policy
   contract, removing local `frame` / `None` result interpretation.
7. Simplify UI pending state so it observes coordinator state.
8. Tighten Machine camera worker payloads around request id/generation.
9. Add explicit flash-session arm/disarm representation to the Python contract
   while preserving the current firmware protocol until a firmware pass is
   approved.
10. Surface firmware flash fault and latched flash/trigger states as typed
    capture-blocking results.
11. Re-evaluate firmware/Pi ready-for-next-trigger semantics as a later,
    separately validated project.

Recommended order for migrating calibration capture bypasses:

The end state is zero calibration-specific direct capture routes. Each existing
path below should either become a caller of the shared calibration capture
policy or be removed as unreachable/dead code.

| Order | Existing path or bypass | Centralization target |
| --- | --- | --- |
| 1 | `_capture_with_policy` | Convert into the calibration-facing adapter for the shared typed capture policy, giving broad coverage because most calibration captures already route through it |
| 2 | `NozzleFocusCalibrationProcess._move_to_Y_clamped` direct recapture | Replace the local direct callback with a shared-policy request using nozzle-focus-specific policy inputs |
| 3 | `OnlineStreamCalibrationProcess._start_single_flow_capture` and `_start_single_tail_capture` | Replace local guard/callback handling with shared-policy requests while expressing recording, metadata, flow/tail state, and timeout differences as policy inputs |

## Acceptance Gates

Before merging the refactor:

- Focused Python capture/coordinator tests pass.
- Existing capture cancellation/close/force-close tests pass.
- HIL camera benchmark runner tests pass.
- Full Python suite passes.
- Firmware host checks pass only if firmware was modified.
- HIL baseline is re-run on the Pi:
  - `flash_only`
  - `print_then_flash` at `100 ms`
  - `coordinated_flash` at `100 ms`, gripper `5000 ms / 500 ms`

For the coordinated lane, the target is:

- `completed_cycles == requested_cycles`
- `firmware_trigger_observed_cycles == requested_cycles`
- `firmware_flash_success_cycles == requested_cycles`
- `camera_flash_detected_cycles == requested_cycles`
- `missed_flash_cycles == 0`
- `camera_detection_miss_cycles == 0`
- no early abort

Before any firmware-side flash arming refactor is merged, additional host and
HIL tests should prove:

- triggers while disarmed do not fire the flash,
- flash output cannot remain high beyond the firmware maximum-on window,
- latched trigger/ACK/busy states are classified and leave the session disarmed,
- recovery/rearm is explicit and observable.

Test staging decision:

- Start with firmware host tests for disarmed-trigger, maximum-on-time, and
  latched-state behavior because they are deterministic and cannot endanger the
  flash LED.
- Add HIL tests after the host behavior is proven to validate Pi/MCU wiring,
  real GPIO timing, ACK-line interpretation, and camera observation.
- Avoid HIL tests that intentionally try to hold the LED on dangerously long;
  use host tests for that fault path and HIL tests for safe observable outcomes.

## Planning Decisions

| Topic | Decision |
| --- | --- |
| Coordinator location | Put `CaptureCoordinator` in its own imported module adjacent to `Controller.py`, not inside the already-large Controller class |
| Calibration capture policy | All calibration captures should use the same shared policy/result contract; direct `captureImageRequested.emit(...)` bypasses are migration debt |
| Direct calibration migration order | Convert `_capture_with_policy` first, then the small nozzle-focus direct recapture path, then the online stream flow/tail direct capture paths |
| Firmware session/fault checks | Use a hybrid approach: the coordinator may accept the logical request into `requesting`, but it must complete a bounded firmware preflight/arm step before entering `capturing` or sending triggers |
| Diagnostic vocabulary | Reuse HIL-style terms internally in typed results, logs, and developer diagnostics; keep operator-facing UI messages simpler |
| Ready signal channel | Reuse the existing ACK line as the future ready/busy state signal; do not plan on adding another physical channel |
| Disarmed-trigger and max-on-time tests | Implement firmware host tests first, then HIL validation once the deterministic safety behavior is covered |
