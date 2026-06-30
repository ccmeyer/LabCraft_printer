# Camera Capture Test Strategy

> Testing strategy, not an implementation plan.
>
> This document defines how to prove the droplet imager capture path across
> Python, firmware, and hardware-in-the-loop layers. It complements
> `docs/camera_capture_life_cycle_map.md` and
> `docs/camera_capture_refactor_requirements.md`.

## Core Answer

The Python capture tests are necessary, but they are not sufficient proof of the
full capture sequence. They can prove that the app handles every result it is
given, releases callbacks, ignores stale completions, and keeps the UI from
hanging. They cannot prove that the MCU actually acknowledged a flash, that the
flash physically fired, or that the camera saw the flash in an image.

The trustworthy strategy is layered:

1. Python deterministic tests prove the app/coordinator state machine.
2. Firmware host tests prove MCU flash-safety logic.
3. Runner/benchmark tests prove the host-side HIL tooling and report parsing.
4. Hardware-in-the-loop camera tests prove Pi + MCU + camera + flash
   coordination on real hardware.

No single layer proves the whole system by itself.

## Current Relevant Coverage

| Layer | Current anchors | What it proves | What it does not prove |
| --- | --- | --- | --- |
| Python capture lifecycle | `tests/test_optics_capture_metadata.py`, `tests/test_droplet_camera_trigger_cleanup.py` | Controller pending state, cancellation, stale completions, backend recovery behavior with fakes | Physical MCU ACK, physical flash, camera optical visibility |
| Python flash fault UI | `tests/test_flash_safety_ui.py`, board status tests | Latched firmware fault state is surfaced and blocks/labels UI behavior | That firmware produced the fault correctly on hardware |
| Firmware host logic | `firmware/tests_host/tests/test_flash_safety.cpp` | `FlashSafety` state transitions, stable fault tokens, trigger/release behavior | Real GPIO timing, flash electrical behavior, camera frame selection |
| HIL self-test framework | `tools/run_selftest.py`, `docs/self_test_roadmap.md`, `docs/self_test_milestone0_baseline.md` | Serial session, firmware self-test reporting, qualification artifacts, fixture-gated test lanes | It is not yet a full droplet imager capture sequence test |
| HIL camera benchmark | `tools/run_selftest.py --camera-benchmark`, `tools/camera_flash_benchmark.py`, `tests/test_run_selftest_camera_benchmark.py`, `docs/droplet_imager_info.md` | Repeated Pi GPIO trigger, MCU ACK edge timing, frame selection, latency/FPS artifacts | Comprehensive negative outcome coverage and refactor acceptance gates |

The existing `--camera-benchmark` path is the strongest starting point for a
capture-specific HIL test because it already coordinates the Pi, MCU flash
configuration, GPIO trigger/ACK lines, and camera frame selection.

## Outcome Model To Cover

The capture path has two different truths that must stay distinct:

- MCU/firmware truth: whether the flash session was armed, trigger was accepted,
  ACK was produced, print completion happened, or a flash fault latched.
- Optical/camera truth: whether the camera produced a frame and whether that
  frame actually contains the flash.

The refactor tests should cover both.

| MCU outcome | Camera outcome | Expected app/coordinator result | Primary test lane |
| --- | --- | --- | --- |
| Flash session armed, trigger accepted, ACK edge seen | Bright post-ACK frame selected | `success` | HIL camera benchmark/self-test plus Python success tests |
| Flash session armed, trigger accepted, ACK edge seen | Frame arrives but flash is not visible | `flash_not_observed` or optical verification failure | HIL fixture/fault injection if safe; Python image-analysis simulation |
| Flash session armed, trigger accepted | No ACK edge before timeout | `firmware_flash_fault` with `flash_ack_timeout` or typed ACK timeout | Firmware host tests plus HIL fault injection if safe |
| Trigger line high when arming | No capture should proceed | `firmware_flash_fault` with `line_high_on_arm` | Firmware host tests; HIL only with safe trigger-line fixture |
| Trigger stays high after accepted trigger | No trusted next capture | `firmware_flash_fault` with release/stuck-high reason | Firmware host tests; HIL only with safe trigger-line fixture |
| Retrigger while awaiting release | Current cycle should stay protected | Busy/ignored trigger event, no active request mutation | Firmware host tests plus Python stale/busy tests |
| Print-then-flash cycle accepted | Print completion does not arrive | `firmware_flash_fault` with `print_completion_timeout` | Firmware host tests; fixture-gated HIL only |
| Firmware fault latched before capture request | Camera request blocked before worker start | `firmware_flash_fault` / capture blocked | Python UI/controller tests |
| Camera backend unavailable | No frame | `backend_unavailable` | Python fake backend tests |
| Camera worker stalls | No terminal frame until guard/recovery | `timeout`, `recovery_succeeded`, or `recovery_failed` | Python fake backend tests; optional HIL stress test |
| Capture cancelled while waiting | Late frame or ACK may still arrive | `cancelled`, late completion `stale_ignored` | Python deterministic tests |
| Force-close while cleanup blocked | Lower layers may remain dirty | `detached_force_close`, restart warning | Python UI tests |

`flash_not_observed` is intentionally listed separately from
`firmware_flash_fault`. The MCU can correctly produce an ACK while the camera
still fails to see useful light. Those should not collapse into the same result.

## Test Lanes

### 1. Python Deterministic Capture Tests

Purpose:

- Prove the Python app handles every typed result and every state transition.
- Run fast in normal development and CI without hardware.

Required coverage:

- Accepted capture request receives exactly one terminal result.
- Queue rejection, busy worker, backend unavailable, timeout, recovery success,
  recovery failure, explicit cancellation, and stale completion are distinct.
- Stop Calibration releases a waiting calibration request without waiting for a
  stalled camera worker.
- Close during capture defers cleanup and either closes normally or reaches the
  explicit force-close path.
- Direct calibration capture paths handle terminal cancellation/failure the same
  way as `_capture_with_policy`.
- Simulated firmware flash fault is surfaced as a distinct capture-blocking
  result.
- Simulated optical failure is surfaced as `flash_not_observed` or equivalent,
  not as generic timeout.

These tests are the main regression gate for refactoring the Python capture
coordinator.

### 2. Firmware Host Tests

Purpose:

- Prove the MCU flash safety state machine without hardware timing noise.

Required coverage:

- Arm succeeds only when the trigger line starts low.
- Line high on arm latches the expected fault token.
- Accepted trigger transitions into awaiting-release/busy state.
- Retrigger while busy is ignored or protected.
- Release polling clears busy state when the line returns low.
- ACK timeout and print-completion timeout have stable tokens and counters.
- Stop/clear returns firmware flash state to safe disarmed state.

These tests prove the firmware rules. They do not prove GPIO edge timing or
camera visibility.

### 3. Runner And Report Tests

Purpose:

- Prove the HIL runner can launch the capture benchmark/self-test, collect
  artifacts, and classify pass/fail correctly.

Required coverage:

- `tools/run_selftest.py --camera-benchmark` records a check row and artifact.
- Missing camera dependencies produce a clear skipped/error result.
- Benchmark result fields are parsed into the qualification report.
- Timeout, missing HELLO, missing benchmark artifact, and failed benchmark result
  are classified distinctly.

These tests make the HIL lane trustworthy before running it on real hardware.

### 4. HIL Camera Capture Smoke Test

Purpose:

- Prove the real Pi + MCU + camera + flash path works in the safe flash-only
  case.

Starting point:

```powershell
.\env\Scripts\python.exe tools\run_selftest.py --port <PORT> --profile SAFE --camera-benchmark --camera-benchmark-mode flash_only --camera-benchmark-cycles 20 --out hil_reports\camera_capture_flash_only.json
```

On the Raspberry Pi, the equivalent command should use the Pi Python
environment and serial port, for example:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --camera-benchmark --camera-benchmark-mode flash_only --camera-benchmark-cycles 20 --out hil_reports/camera_capture_flash_only.json
```

Required pass evidence:

- Firmware session starts and accepts trigger cycles.
- ACK edge is seen for each expected successful cycle.
- The camera selects a post-ACK frame for each expected successful cycle.
- Selected frame brightness exceeds the configured flash threshold or passes the
  documented fallback reason.
- Per-cycle artifact includes trigger/ACK/frame timing fields.
- Aggregate report includes pass/fail counts, latency summary, and artifact path.

Current benchmark fields already useful for this lane include:

- `t_trigger_high`
- `t_ack_edge`
- `t_selected_frame_done`
- `trigger_to_ack_ms`
- `ack_to_arm_ms`
- `trigger_to_frame_ms`
- `success_bool`
- `ack_seen_bool`
- `frame_selected_bool`
- `selected_mean`
- `edge_timeout_subreason`

### 5. Fixture-Gated Print-Then-Flash Test

Purpose:

- Prove the firmware print-completion and flash-on-final-droplet path with the
  real machine prepared for motion/pressure.

Starting point:

```powershell
.\env\Scripts\python.exe tools\run_selftest.py --port <PORT> --profile FULL --camera-benchmark --camera-benchmark-mode print_then_flash --camera-benchmark-order post_selftest --camera-benchmark-cycles 20 --out hil_reports\camera_capture_print_then_flash.json
```

This lane must remain fixture-gated because it can involve homing, pressure
readiness, and print-path behavior. It should require explicit operator/machine
preflight in the same spirit as the existing FULL HIL qualification path.

Required pass evidence:

- Machine-ready preflight completed.
- Firmware configured imaging droplets and flash delay/duration.
- Trigger cycles produced ACKs.
- Print completion happened within firmware timeout.
- Camera selected flashed frames.
- No flash fault latched during or after the run.

### 6. Fault-Injection And Simulation Lane

Purpose:

- Cover failures that are too risky, flaky, or awkward to create physically on
  every run.

Recommended split:

- Use Python fake-backend tests for camera stalls, backend unavailable, stale
  completion, cancellation, and force-close.
- Use firmware host tests for line-high-on-arm, retrigger/busy, release/stuck
  high, ACK timeout, and print-completion timeout state transitions.
- Use HIL fault injection only when there is a documented safe fixture or
  diagnostic mode.

Do not make routine tests depend on unplugging live wires, physically blocking
the flash, or creating unsafe electrical faults. If the project needs real HIL
negative tests for "ACK missing" or "flash not observed", add a dedicated safe
fixture or explicitly reviewed diagnostic mode first.

## Proposed Capture-Specific HIL Self-Test

The proposed self-test should build on the existing HIL runner and
`tools/camera_flash_benchmark.py` rather than starting from scratch. The
`docs/self_test_roadmap.md` ID range `2600-2699` is already reserved for
imaging, flash, and camera timing, so the capture self-test should live there.

Suggested initial tests:

| Proposed ID | Name | Mode | Purpose |
| --- | --- | --- | --- |
| `2600` | `camera_flash_only_smoke` | SAFE / flash-only | Verify trigger, ACK, and flashed-frame selection without motion/pressure |
| `2601` | `camera_flash_only_repeatability` | SAFE / flash-only | Verify repeated cycles stay within latency and success thresholds |
| `2602` | `camera_ack_timeout_fault` | Fixture/simulation | Verify missing ACK becomes a typed firmware fault |
| `2603` | `camera_flash_not_observed` | Fixture/simulation | Verify ACK-without-visible-flash becomes optical verification failure |
| `2604` | `camera_stale_completion_after_cancel` | Python/HIL hybrid | Verify late camera completion does not mutate active capture state |
| `2610` | `camera_print_then_flash_smoke` | FULL / fixture-gated | Verify print-completion plus final-droplet flash path |

Initial implementation should probably start with `2600` and `2601`, because
they can reuse the existing flash-only benchmark and do not require motion or
pressure. Negative HIL tests should wait until safe fault injection is designed.

## HIL Self-Test Artifact Requirements

Each capture HIL run should preserve enough data to debug a failure after the
machine is no longer attached.

Required artifacts:

- Raw runner report, compatible with existing `raw_selftest.json` expectations.
- Camera benchmark/self-test JSON artifact.
- Per-cycle timeline with host monotonic timestamps.
- Firmware counters before and after the run:
  trigger count, ACK count, task wake/done count, fault counters, and fault
  reason.
- Camera frame selection metadata:
  selected frame index/time, threshold, selected mean, fallback reason, and
  number of post-ACK frames inspected.
- A small sample of saved frames for failing cycles, preferably pre-trigger,
  post-ACK candidate, and selected frame.
- App/coordinator result status when the full Python capture path is part of the
  test.

The artifact should allow a reviewer to classify a failure as:

- host/serial/session failure,
- firmware flash session failure,
- missing ACK,
- camera backend/frame failure,
- optical flash-not-observed failure,
- app/coordinator state failure,
- or fixture/operator setup failure.

## Acceptance Gates

Before refactoring Python capture ownership:

- Python characterization tests pass for current cancel/timeout/stale/close
  behavior.
- Firmware host flash-safety tests pass.
- Existing `--camera-benchmark` unit tests pass.
- At least one known-good HIL `flash_only` benchmark artifact is recorded on a
  representative Pi + MCU + camera setup.

For each Python refactor slice:

- Run focused Python capture tests.
- Run runner/report tests if self-test tooling changed.
- Do not require HIL for every small local edit, but require HIL before treating
  a capture-stack refactor as hardware-validated.

Before merging a major capture lifecycle refactor:

- Python full suite passes.
- Firmware host tests pass if firmware-adjacent status handling changed.
- HIL `flash_only` camera capture test passes on target hardware.
- HIL `print_then_flash` passes only when the change affects print/flash
  coordination and the fixture is prepared.

## What Comprehensive Means

Comprehensive does not mean every physical fault is injected on every run. It
means every meaningful outcome has a trustworthy test lane:

- App state outcomes are covered by deterministic Python tests.
- MCU safety outcomes are covered by firmware host tests.
- Runner/report outcomes are covered by runner unit tests.
- Real trigger/ACK/frame timing is covered by HIL flash-only tests.
- Real print-completion/flash coordination is covered by fixture-gated HIL
  print-then-flash tests.
- Dangerous or awkward negative cases are covered by simulation until a safe
  hardware fixture exists.

The capture refactor should not claim "no regressions" from Python tests alone.
It should claim "no Python lifecycle regressions" from Python tests, and "no
end-to-end capture regressions on this hardware fixture" only after the HIL lane
passes.

## Recommended Next Steps

1. Add `flash_not_observed` or equivalent optical-verification status to the
   capture result requirements before implementation.
2. Add Python characterization tests for every typed result the coordinator will
   need.
3. Promote the existing camera benchmark into a named HIL capture qualification
   lane using IDs in `2600-2699`.
4. Record a current known-good flash-only HIL artifact before changing capture
   ownership.
5. Design safe fault-injection fixtures or diagnostic modes only after the
   positive HIL path is stable.

