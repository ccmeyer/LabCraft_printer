# Pressure Testing Plan

## Purpose

This document captures the pressure-regulation work in progress so it can be resumed after interruption. The current effort is focused on:

1. Adding pressure-focused HIL diagnostics that capture regulator behavior under print/refuel disturbances.
2. Splitting pressure sensing into control-facing and status-facing paths.
3. Adding bounded post-pulse recovery/feedforward support.
4. Using the new HIL traces to compare baseline behavior against the modified regulator.

## Call Path

Pressure trace HIL execution currently flows through:

`tools/run_selftest.py -> Orchestrator self-test runner -> Printer / PressureRegulator -> PressureTraceRecorder -> self-test result export`

Pressure control during printing currently flows through:

`Printer -> PressureRegulator -> PressureSensor -> Stepper`

## Validation Commands

Firmware validation commands for this work:

- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

Python trace/parser validation used during this work:

- `.\\env\\Scripts\\python.exe -m pytest -q tests/test_run_selftest_metrics.py tests/test_run_selftest_goodbye.py tests/test_run_selftest_trace.py`

## Staged Plan Being Implemented

### Stage 1: Pressure HIL baseline infrastructure

Implemented:

- Added `PressureTraceRecorder` with fixed sample/event buffers.
- Added pressure-trace FULL self-tests `2101-2104`.
- Added trace chunk export from firmware self-test results.
- Added host-side trace decoding and trace artifact writing in `tools/run_selftest.py`.

Purpose:

- Capture baseline regulator behavior before and after control changes.
- Measure recovery time, pressure undershoot/overshoot, deadline slip, and rejected samples.

### Stage 2: Pure helper math and host tests

Implemented:

- Added pressure validation / recovery math helpers in `PressureRegulatorMath`.
- Added host tests for pressure math and trace record decoding.

### Stage 3: Split pressure measurement paths

Implemented:

- Added validated control-facing pressure samples in `PressureSensor`.
- Preserved rolling-average pressure for status/UI.
- Updated `PressureRegulator` to use the validated control sample instead of the rolling average.

### Stage 4: Post-pulse feedforward recovery

Implemented:

- Added recovery config/state to `PressureRegulator`.
- Added `notifyPulseStart()` / `notifyPulseEnd()` event handoff from `Printer`.
- Added bounded decaying recovery boost after pulse completion.

### Stage 5: Tune and compare

Partially complete:

- Baseline and post-change HIL runs have been executed.
- Repeated print pressure test now passes after trace harness fixes.
- Remaining work is isolating refuel-only and dual-channel failures.

### Current 2302 Stall Triage (in progress)

Latest findings:

- `2302` with `--pressure-trace` still times out on host `progress_timeout`.
- Host report shows progress heartbeats were received and the last stage was `wait_bits_enter`.
- Sweep output indicates only the first two combo rows (`2410`, `2411`) are emitted before the stall.

Latest mitigations implemented:

- Host `run_selftest.py` now records a ring buffer of recent frame headers (`cmd`, `test_id`, `name`, trace chunk metadata) in `selftest_progress_watchdog`.
- Host liveness timer now extends only on self-test result/done frames (not periodic status frames) to avoid masking MCU stalls.
- Firmware sweep now emits additional per-combo breadcrumbs (`sw_*` stages), includes `combo_ms` and `combo_to` in combo metrics, and applies a conservative trace export budget for `2302`.
- Firmware cancel path now waits for `Printer::isBusy()==false` with a short timeout instead of waiting on `BIT_PRINTING_DONE` after cancel.

Focused tuning sweep:

- Added selector `p3=2303` for a focused sweep centered on scenarios `2/6/8` (print guard + dual + refuel-high-slip) using parameter variants around the current best set.
- Added selector `p3=2304` for a micro-sweep around `param1/param5` with small refuel-only recovery/slew deltas for rapid tuning iterations.
- Promoted `param11` from micro-sweep into full `2302` sweep coverage (replacing the weakest full-suite candidate) to keep 48-combo runtime stable.

## Files Changed So Far

### Firmware

- `firmware/Core/Inc/PressureRegulatorMath.h`
- `firmware/Core/Src/PressureRegulatorMath.cpp`
- `firmware/Core/Inc/PressureTraceRecorder.h`
- `firmware/Core/Src/PressureTraceRecorder.cpp`
- `firmware/Core/Inc/PressureSensor.h`
- `firmware/Core/Src/PressureSensor.cpp`
- `firmware/Core/Inc/PressureRegulator.h`
- `firmware/Core/Src/PressureRegulator.cpp`
- `firmware/Core/Src/Printer.cpp`
- `firmware/Core/Src/Orchestrator.cpp`
- `firmware/tests_host/tests/test_pressure_regulator_math.cpp`
- `firmware/tests_host/tests/test_pressure_trace_math.cpp`
- `firmware/tests_host/CMakeLists.txt`
- `firmware/scripts/build_firmware_headless.ps1`
- `firmware/docs/repo_map.md`

### Host / Python

- `tools/run_selftest.py`
- `tests/test_run_selftest_trace.py`

## Important Fixes Already Made

### Stability / correctness fixes

- Initialized pressure validation config defaults in `PressureSensor`.
- Made failed pressure reads fall back to the latest accepted control sample.
- Guarded null sensor/task cases in `PressureRegulator`.
- Added automatic `TraceStart` / `TraceStop` events in `PressureTraceRecorder`.

### Pressure trace harness fixes

- Moved trace start so capture begins after the regulator reaches target and just before preroll.
- Stopped trace capture before restoring the baseline target to avoid contaminating metrics with teardown transients.
- Shortened metric key names to stay within self-test payload size limits:
  - `base`, `min`, `max`, `under`, `over`, `rec_w`, `rec_m`, `ready_miss`, `slip_w`, `slip_m`, `zero`, `rejects`
- Increased recorder event capacity to `128`.
- Updated the trace config default to actually use `128` events instead of still defaulting to `64`.
- Reworked `ready_miss` calculation so it only counts a miss when pressure leaves the ready band and fails to re-enter before the next pulse.

## Latest Verified Results

### Local validation

Passed:

- `.\\env\\Scripts\\python.exe -m pytest -q tests/test_run_selftest_metrics.py tests/test_run_selftest_goodbye.py tests/test_run_selftest_trace.py`
  - Result: `14 passed`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
  - Host tests: `53 tests, 53 ran, 217 checks`
  - Headless build: pass

Known non-blocking warning:

- Existing `callbacks.cpp` warnings about C++17-style init statements remain and are unrelated to this pressure work.

### Most recent HIL run

Latest Pi report inspected:

- `/home/labcraft/LabCraft_printer/hil_reports/selftest_20260228_170419.json`

Summary:

- `total=26`
- `passed=24`
- `failed=2`
- `aborted=false`

Passing pressure tests:

- `2003 pressure_regulator_step_response_full`
  - `target_pressure=1838`
  - `settle_time_ms=979`
  - `overshoot=0`
  - `steady_state_error=5`
- `2101 pressure_recovery_trace_print_single`
  - `base=2509`
  - `min=2503`
  - `max=2512`
  - `rec_w=28`
  - `ready_miss=0`
- `2102 pressure_recovery_trace_print_repeated`
  - `base=2509`
  - `min=2493`
  - `max=2539`
  - `under=19`
  - `over=27`
  - `rec_w=98`
  - `rec_m=42`
  - `ready_miss=0`
  - `slip_w=103`
  - `slip_m=69`
  - `zero=5`
  - `rejects=0`

Remaining failing pressure tests:

- `2103 pressure_recovery_trace_refuel_repeated`
  - `base=2073`
  - `min=2000`
  - `max=2082`
  - `under=75`
  - `over=7`
  - `rec_w=157`
  - `rec_m=97`
  - `ready_miss=0`
  - `slip_w=490`
  - `slip_m=250`
  - `zero=8`
  - `rejects=0`
- `2104 pressure_recovery_trace_dual_interleaved`
  - `base=2509`
  - `min=2011`
  - `max=2535`
  - `under=64`
  - `over=47`
  - `rec_w=45`
  - `rec_m=20`
  - `ready_miss=2`
  - `slip_w=6`
  - `slip_m=0`
  - `zero=63`
  - `rejects=0`

## Interpretation of Current State

The pressure trace infrastructure is now working well enough to distinguish harness issues from real control behavior:

- The repeated print-path trace (`2102`) now passes.
- The remaining failures appear concentrated in:
  - refuel repeated timing / recovery (`2103`)
  - dual-channel interaction (`2104`)

This suggests the next work should focus on:

1. Collecting raw trace artifacts for `2103` and `2104`.
2. Determining whether the remaining failures are caused by:
   - refuel regulator recovery being genuinely too slow
   - interaction between print/refuel scheduling
   - dual-channel sample cadence limits
   - a remaining edge case in the metric logic

## Next Restart Steps

When resuming, start here:

1. Run `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`.
2. Run `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`.
3. If HIL still fails on `2103` / `2104`, run pressure-trace capture directly on the Pi with trace export enabled:
   - `python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-trace --timeout-ms 180000 --out hil_reports/selftest_pressure_trace_now.json`
4. Inspect the resulting trace artifacts for:
   - refuel pulse spacing
   - ready-enter / ready-exit timing
   - recovery window duration
   - whether dual-channel interactions are causing the misses
5. Decide whether the next code change should target:
   - refuel recovery/feedforward tuning
   - dual-channel test logic / event interpretation
   - pressure sampling cadence under dual-channel load

## Parameter Sweep Mode (New)

Pressure self-test now supports diagnostic sweep selectors through existing `p3`:

- `p3=2301`: pressure sweep suite core (`24` combos + summary row)
- `p3=2302`: pressure sweep suite extended (`48` combos + summary row)

Host invocation examples:

- `python tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-trace --pressure-sweep-suite 2301 --timeout-ms 300000 --out hil_reports/selftest_pressure_sweep_s2301.json`
- `python tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-sweep-suite 2302 --timeout-ms 420000 --out hil_reports/selftest_pressure_sweep_s2302.json`

Sweep artifacts written by host:

- `hil_reports/selftest_<timestamp>_pressure_sweep_s<suite>.json`
- `hil_reports/selftest_<timestamp>_pressure_sweep_s<suite>.csv`

Selective raw trace export (when `--pressure-trace` is enabled) is triggered per combo when any condition is true:

- `ready_miss > 0`
- `slip_w > 120`
- `over > 20`
- `under > 40`

Sweep plotting:

- `py tools/plot_pressure_traces.py --sweep-summary hil_reports/selftest_<timestamp>_pressure_sweep_s2301.json`

Generated outputs:

- `*_score_by_param.png`
- `*_ready_miss_heatmap.png`
- `*_slip_over_scatter.png`

## Trace Plot Tool

To review regulator response before tuning changes, generate plots from trace artifacts:

1. Run pressure trace tests so trace files exist in `hil_reports/`:
   - `python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-trace --pressure-trace-test 2103 --timeout-ms 180000 --out hil_reports/selftest_pressure_trace_2103.json`
   - `python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-trace --pressure-trace-test 2104 --timeout-ms 180000 --out hil_reports/selftest_pressure_trace_2104.json`
2. Generate plots locally:
   - `py tools/plot_pressure_traces.py`
   - or target specific traces:
     - `py tools/plot_pressure_traces.py hil_reports/selftest_pressure_trace_2103_trace_2103.json hil_reports/selftest_pressure_trace_2104_trace_2104.json`
3. Review output PNGs in:
   - `hil_reports/pressure_trace_plots/`

Each plot overlays:
- pressure signals (`raw`, `control`, `avg`, `target`)
- control speed (`requested_hz`, `applied_hz`, `ff_boost_hz`)
- state flags (`pressure_ok`, `quiet`, `recovery`, `sample_rejected`)
- disturbance and state events (`pulse_*`, `quiet_*`, `recovery_*`, `ready_*`)

Use these plots to determine whether failures are due to:
- overshoot/ringing
- slow recovery to target
- excessive speed clamping or ramping behavior
- print/refuel disturbance interaction timing

## Risk Notes

- This is pressure- and timing-sensitive firmware, so changes must stay incremental.
- The current protocol additions are constrained to self-test trace TLVs; normal control protocol was not changed.
- Any next changes to `2103` / `2104` should be validated first with local checks, then with the full Pi HIL gate.

## Rollback Guidance

If the current pressure trace work needs to be backed out:

1. Revert the pressure trace recorder module changes.
2. Revert the pressure self-test additions in `Orchestrator.cpp`.
3. Revert the control-sample / recovery changes in `PressureSensor`, `PressureRegulator`, and `Printer`.
4. Re-run:
   - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
   - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29`

## March 2, 2026 Implementation Update

Implemented in this pass:

- Added new regulator math helpers:
  - `computeRecoveryRequestedHz(...)`
  - `applyAsymmetricSlew(...)`
  - `shouldExtendRecovery(...)`
- Extended `PressureRegulator::RecoveryConfig` with:
  - `recoveryFloorHz`
  - `recoveryExitErrorRaw`
  - `maxExtendTicks`
  - `allowExtendWhileUndershoot`
  - `boostOnlyWhenUndershoot`
- Added `PressureRegulator::SlewConfig` with:
  - `maxHzDeltaUpPerLoop`
  - `maxHzDeltaDownPerLoop`
  - `recoveryBypassSlewTicks`
- Updated control loop to:
  - support bounded recovery extension,
  - support directional feedforward gating,
  - apply asymmetric slew limiting.
- Updated `Printer::taskLoop()` to absolute cadence scheduling using `nextPhaseTick` (deadline-based delays) instead of chained relative half-delays.
- Added a short ready-stabilization guard before pulse launch.
- Added host-unit tests for the new regulator math behavior.

Validation results:

- Local checks pass:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- Python tests pass:
  - `.\\env\\Scripts\\python.exe -m pytest -q tests/test_pressure_trace_plots.py tests/test_run_selftest_trace.py`

Latest HIL status:

- HIL command still exits fail because full self-test reports failures:
  - `1040 rtos_memory_headroom_safe` (pre-existing/non-pressure gate issue)
  - `2102 pressure_recovery_trace_print_repeated` (still failing on `ready_miss`)
  - `2104 pressure_recovery_trace_dual_interleaved` (still failing on `ready_miss`)
- Most recent report inspected:
  - `hil_reports/selftest_20260302_155241.json`
- Key pressure metrics from that run:
  - `2102`: `ready_miss=4`, `slip_w=60`, `rec_w=30`
  - `2104`: `ready_miss=1`, `slip_w=110`, `rec_w=30`
  - `2103` now passes with `ready_miss=0`.

Interpretation:

- The cadence/slip objective improved (`slip_w` now comfortably under the 250 ms gate).
- Remaining pressure-gate failures are now concentrated on ready-band re-entry timing (`ready_miss`) for print and dual-interleaved scenarios.

## March 3, 2026 Tuning Update

Additional changes implemented in this pass:

- `Printer` cadence updates in `firmware/Core/Src/Printer.cpp`:
  - Added phase-advance rebasing logic to reduce bursty catch-up behavior.
  - Added mode-aware rebasing thresholds so single-channel runs rebase more aggressively on lateness than dual-channel runs.
- `PressureRegulatorMath` fix in `firmware/Core/Src/PressureRegulatorMath.cpp`:
  - Fixed `recoveryFloorHz` application so it only applies while recovery is active.
  - Tightened directional feedforward gating to only boost when undershoot exceeds the ready tolerance.
- `PressureRegulator` retuning in `firmware/Core/Src/PressureRegulator.cpp`:
  - Reduced print-channel recovery aggressiveness (shorter active window, smaller boost, no extension).
  - Made print-channel slew less aggressive on upward commands.

Validation results:

- Local checks pass:
  - `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`
- Full HIL still fails due pressure ready-miss criteria:
  - latest full report copied locally: `hil_reports/selftest_20260302_162506.json`
  - failing tests:
    - `1040 rtos_memory_headroom_safe` (pre-existing unrelated gate)
    - `2102 pressure_recovery_trace_print_repeated` (`ready_miss=3`, `slip_w=50`)
    - `2104 pressure_recovery_trace_dual_interleaved` (`ready_miss=2`, `slip_w=53`)

Current diagnosis:

- Slip is now generally within target for both pressure tests.
- Remaining failures are dominated by ready-band misses with pressure overshoot peaks (`over` around `28-30` raw) while using the tight ready band.
- Pressure trace artifacts continue to show occasional cadence compression events under load, which correlate with ready-miss counts.

