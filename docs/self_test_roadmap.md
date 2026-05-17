# Machine Self-Test and Qualification Roadmap

## Purpose

This roadmap defines a bounded path for expanding the existing HIL self-test system into a repeatable machine qualification framework for building and accepting multiple LabCraft printers.

The core design is a hybrid:

- Firmware owns deterministic, timing-sensitive operations and measurements.
- Python owns orchestration, manifests, analysis, reports, history, and operator workflow.
- The main app may expose a qualification window later, but the backend must remain usable from the command line for factory and remote HIL runs.

The intent is to increase quantitative coverage without turning the firmware, Python runner, or GUI into a large monolith with many failure points.

## Progress

| Milestone | State | Current artifact |
| --- | --- | --- |
| Milestone 0: Baseline Inventory and Acceptance Definitions | Complete | `docs/self_test_milestone0_baseline.md` |
| Milestone 1: Python Qualification Skeleton, No Firmware Behavior Change | Complete | `tools/qualification/`, `tools/run_qualification.py`, `tools/qualification/manifests/factory_acceptance_v0.json` |
| Milestone 2: Firmware Diagnostics Extraction, Behavior Preserved | Complete | `firmware/Core/Src/Diagnostics.cpp`, `firmware/Core/Src/DiagnosticResultEmitter.cpp`; FULL HIL `hil_reports/selftest_20260513_163220.json` |
| Milestone 3: Stable Report Schema and Analyzer Gate | Complete | `tools/qualification/analyzers.py`, `docs/self_test_report_schema_v1.md` |
| Milestone 4: Motion Qualification Slice | Complete | `2007 motion_home_repeatability_factory`, `2008 motion_pattern_return_factory`, `factory_acceptance_v1` |
| Milestone 5: Pressure Regulator Leak and Step-Position Slice | Complete | `2201 pressure_hold_leak_factory`, `2202 pressure_target_cycle_repeatability_factory`, `2203 pressure_motor_position_hysteresis_factory`, `factory_acceptance_v2`; FULL HIL `hil_reports/selftest_20260513_191209.json` |
| Milestone 6: Valve Pulse Repeatability Slice | Complete | `2401 print_valve_pulse_drop_repeatability_factory`, `2402 refuel_valve_pulse_drop_repeatability_factory`, `2403 dual_valve_interaction_factory`, `factory_acceptance_v3`; FULL HIL `hil_reports/selftest_20260513_200311.json`; qualification pass with candidate warnings |
| Milestone 7: Local Operator-Gated Gripper Seal Qualification | Complete enough to move on | `gripper_seal_v1`, selected firmware suite `2501`-`2503`; regulators home through watchdog-safe async tasks before conditioning, then pause during valve-open bursts |
| Milestone 8A: Read-Only Qualification Window Prototype | Complete | Main app `Machine Qualification` window displays existing `qualification_report_v1` reports without launching hardware tests |
| Milestone 8B: Qualification Run Shell | In progress | `Run Qualification` tab launches existing manifests through the Python qualification backend with coarse progress and final row coloring |
| Milestone 8C: Live Per-Test Qualification Events | In progress | `tools/run_selftest.py --progress-jsonl` emits backend-owned per-test events consumed by the qualification window |
| Milestone 8D: Qualification Timing and Compact History | Complete | Machine Qualification window estimates typical test durations from local reports, shows elapsed/remaining time during runs, and compacts report history labels |
| Milestone 8E: XY Motion Qualification Suite | Complete enough to move on | Standalone operator-gated `xy_motion_v1` suite selects firmware XY long-travel/raster diagnostics `2010`-`2011` without adding them to default FULL |
| Milestone 8F: Motion Envelope Qualification Suite | In progress | Standalone operator-gated `motion_envelope_v1` suite selects firmware motion envelope diagnostics `2012`-`2016` without adding them to default FULL |
| Milestone 8G: Pressure Regulator Qualification Suite | In progress | Standalone operator-gated `pressure_regulator_v1` suite selects firmware pressure regulator diagnostics `2210`-`2219` without adding them to default FULL |
| Milestone 8H: Valve Characterization Qualification Suite | In progress | Standalone operator-gated `valve_characterization_v1` suite selects isolated 2 psi valve repeatability/linearity diagnostics `2473`-`2475` without adding them to default FULL |
| Milestone 8I: Gripper Seal Stress and Motion Suite | In progress | Standalone operator-gated `gripper_seal_stress_v1` suite selects firmware execution rows `2510`-`2513` and Python-derived gripper trace artifacts without adding them to default FULL |
| Later fixture-dependent diagnostics | Not started | Planned |

## Current Call Path

Existing HIL self-test flow:

`firmware/scripts/run_fw_hil_windows.ps1 -> firmware/hil/flash_and_test.sh -> tools/run_selftest.py -> CMD_SELFTEST_START -> Orchestrator dispatcher -> DiagnosticsRunner::runSelfTest -> hardware primitives -> CMD_SELFTEST_RESULT/CMD_SELFTEST_DONE -> JSON report`

Existing main app control flow:

`View -> Controller -> Machine_FreeRTOS -> serial command queue -> Orchestrator -> Stepper / Gantry / PressureRegulator / Printer / Gripper`

Target qualification flow:

`Qualification CLI or app window -> Python qualification runner -> serial diagnostic command -> firmware diagnostics module -> hardware primitives -> streamed metrics/traces -> Python analysis/report -> stored machine history`

## Guiding Constraints

- Keep normal device protocol behavior stable unless a milestone explicitly requires a backward-compatible self-test extension.
- Add one bounded capability at a time.
- Keep each firmware diagnostic test deterministic, timeout-bounded, and independently abortable.
- Do not add a GUI surface until the command-line backend, report schema, and at least one fixture-dependent diagnostic are stable.
- Prefer firmware metrics that are compact and objective; let Python perform richer analysis and pass/fail interpretation.
- Every hardware-facing milestone must define fixture requirements, safety preconditions, validation commands, stop conditions, and rollback steps.
- Each milestone should be mergeable on its own.

## Decisions and Assumptions

### Machine Identity

Recommendation:

- Generate a stable local machine identity the first time a qualification command is run.
- Store it in a non-tracked local file, not in the repository history.
- Include both a human-readable ID and a generated UUID-like internal ID in every report.

Suggested initial file:

- `local/machine_identity.json`

Suggested file contents:

```json
{
  "machine_id": "LC-0001",
  "machine_uuid": "generated-stable-uuid",
  "assigned_at": "2026-05-13T00:00:00Z",
  "notes": ""
}
```

Milestone 1 should add an explicit ignore rule for either `local/` or `*.local.json` before writing this file. If that is not implemented yet, a temporary identity file under `hil_reports/` is acceptable because `hil_reports/` is already ignored, but the identity should eventually live outside transient report folders.

### Fixture Identity

Use stable, lowercase fixture IDs in manifests and reports.

Initial gripper fixture recommendation:

- `blocked_head_seal_test`

Potential future fixture IDs:

- `motion_clear_envelope`
- `pressure_hold_closed_loop`
- `pressure_closed_loop_v1`
- `print_valve_pneumatic_drop`
- `refuel_valve_pneumatic_drop`
- `dummy_blocked_head_v1`

### Acceptance Thresholds

Initial thresholds should be empirical. The first threshold milestone should collect baseline data from a known-good machine before making hard pass/fail limits strict.

Recommended threshold maturity levels:

- `informational`: collect metric only, no pass/fail except safety/infrastructure errors.
- `candidate`: warn when outside provisional bounds.
- `acceptance`: fail qualification when outside validated bounds.

Milestone 3 should support these threshold levels in Python analysis so early data collection does not force premature limits.

### Test Duration and Progress

Each long-running firmware diagnostic must emit progress/check-in results while it is running. Python should abort only after multiple missed progress windows, not merely because a test takes longer than a fixed nominal duration.

Recommended policy:

- Firmware emits `selftest_progress` or equivalent progress frames at least every 1-5 seconds during long operations.
- Python tracks both a hard run timeout and a progress timeout.
- Missing one expected progress interval should warn internally.
- Missing multiple progress intervals should abort the diagnostic run and mark the report as infrastructure/timeout failure.
- Every long-running test still has an absolute maximum timeout to avoid indefinite pressure, motion, or valve activity.

### Operator Workflow

Operator workflow means an explicit checklist and confirmation step before hardware-active tests, not a yes/no prompt for every low-level command.

For example, before a gripper seal test the runner or future GUI should show:

- The exact suite and hardware-active tests that will run.
- Required fixture: `blocked_head_seal_test`.
- Expected machine state.
- Motion/pressure/valve/gripper activity that will occur.
- Safety confirmations, such as clear motion envelope and installed dummy head.

SAFE/read-only tests can run with minimal prompts. Motion, pressure, valve, and gripper tests should require explicit confirmation unless the run is launched in an approved unattended factory mode.

### Report Format

Use JSON and CSV for now.

- JSON is the canonical complete report.
- CSV is the fleet-comparison/export format.
- HTML/PDF can be added later after the schema stabilizes.

### Main App Integration

The first GUI should be read-only:

- Browse existing reports.
- Show pass/fail summaries.
- Show metrics, warnings, and artifact paths.

Launching tests directly from the app is a later step after the CLI backend and report schema are stable.

### Remote Execution

Codex/automation may SSH into the machine, flash firmware, and run HIL tests when needed for this work.

Current machine address:

- `192.168.0.33`

This is an environment-specific default and should not be hardcoded into reusable scripts unless a local config layer owns it.

### Default Assumptions

- Use `hil_reports/qualification/<machine_id>/<timestamp>/` for run folders.
- Use JSON as the canonical report format and CSV for fleet comparison.
- Use operator-confirmed fixture gates for any motion, pressure, valve, or gripper actuation.
- Keep the existing `CMD_SELFTEST_START`, `CMD_SELFTEST_RESULT`, and `CMD_SELFTEST_DONE` protocol family unless a milestone explicitly adds compatible selector/config TLVs.

## Target Architecture

### Firmware

Extract the current self-test implementation from `Orchestrator.cpp` into a diagnostics subsystem while preserving behavior.

Proposed files:

- `firmware/Core/Inc/Diagnostics.h`
- `firmware/Core/Src/Diagnostics.cpp`
- `firmware/Core/Inc/DiagnosticResultEmitter.h`
- `firmware/Core/Src/DiagnosticResultEmitter.cpp`
- `firmware/Core/Inc/DiagnosticTests.h`
- `firmware/Core/Src/DiagnosticTests.cpp`

Optional split files after the registry is stable:

- `firmware/Core/Src/DiagnosticMotion.cpp`
- `firmware/Core/Src/DiagnosticPressure.cpp`
- `firmware/Core/Src/DiagnosticValves.cpp`
- `firmware/Core/Src/DiagnosticGripper.cpp`

Firmware responsibilities:

- Decode a diagnostic request prepared by `Orchestrator`.
- Run tests from a table/registry.
- Emit compact result metrics and optional trace chunks.
- Enforce timeouts and abort checks.
- Restore safe hardware state after each test.

`Orchestrator` responsibilities after extraction:

- ACK `CMD_SELFTEST_START`.
- Pause/resume status traffic as appropriate.
- Convert command TLVs into a `DiagnosticRequest`.
- Call `Diagnostics::run(request)`.
- Keep shutdown, command queue, and normal command behavior unchanged.

### Python

Restructure `tools/run_selftest.py` gradually into a package while keeping the current script as a compatibility wrapper.

Proposed package:

- `tools/qualification/protocol.py`: frame/TLV encode/decode and constants
- `tools/qualification/runner.py`: serial session, HELLO/GOODBYE, progress watchdog, artifact capture
- `tools/qualification/manifest.py`: suite definitions, fixture requirements, thresholds
- `tools/qualification/analyzers.py`: derived metrics and pass/fail interpretation
- `tools/qualification/report.py`: canonical JSON, CSV summaries, optional HTML/PDF
- `tools/qualification/artifacts.py`: run folders, trace files, plots
- `tools/qualification/cli.py`: factory/service command-line entrypoint
- `tools/run_selftest.py`: compatibility wrapper during migration

Python responsibilities:

- Select tests and parameters from a manifest.
- Enforce operator/fixture checklist requirements.
- Run firmware diagnostics and collect results.
- Analyze metrics and traces.
- Compare thresholds and flag issues.
- Store raw and derived artifacts in a stable run folder.
- Produce reports suitable for machine acceptance and fleet comparison.

### Main App

Add a separate app window only after the backend is stable.

Recommended window name: `Machine Qualification`.

Initial GUI scope should be intentionally thin:

- Select or enter machine ID.
- Select qualification suite.
- Show fixture checklist.
- Launch or monitor a backend run.
- Display pass/fail summary and report path.
- Browse previous reports.

Do not duplicate analysis logic in `View.py` or `Controller.py`. The app should call the same Python backend used by CLI/HIL runs.

## Test ID Ranges

Reserve test IDs by subsystem:

- `1000-1099`: SAFE protocol, status, watchdog, crash log, memory headroom
- `2000-2099`: motion and homing factory tests
- `2100-2199`: pressure trace single-case diagnostics
- `2200-2299`: regulator leak, hysteresis, and step-position repeatability
- `2300-2399`: pressure sweep suites
- `2400-2499`: valve pulse repeatability
- `2500-2599`: gripper seal and clamp diagnostics
- `2600-2699`: imaging, flash, and camera timing
- `9000-9099`: fixture/operator preflight checks

## Validation Lanes

Python local tests:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Focused Python self-test runner tests:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_run_selftest_metrics.py tests/test_run_selftest_goodbye.py tests/test_run_selftest_trace.py tests/test_pressure_sweep_artifacts.py
```

Firmware local checks:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Full Windows-to-Pi HIL:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

Direct Pi runner examples:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile SAFE --timeout-ms 30000 --out hil_reports/selftest_safe_now.json
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-trace --pressure-trace-test 2102 --timeout-ms 180000 --out hil_reports/selftest_pressure_trace_2102.json
```

Automation may run SSH/HIL commands when explicitly authorized. Otherwise, the operator can run the commands directly on the machine and provide the generated report artifacts.

## Milestone 0: Baseline Inventory and Acceptance Definitions

Objective:

Document the current self-test behavior, report schema, known passing HIL baseline, fixture assumptions, and first-pass acceptance metrics before changing code.

Allowed changes:

- Documentation only.
- Optional report schema examples or sample manifests.

Expected outputs:

- Current SAFE and FULL test inventory.
- Current report schema summary.
- Initial qualification suite outline.
- Initial fixture list.
- A small table of proposed acceptance metrics for motion, pressure, valves, and gripper tests.

Milestone 0 artifact:

- `docs/self_test_milestone0_baseline.md` records the current baseline inventory and latest-known-good report reference.

Validation:

- Inspect latest passing HIL report in `hil_reports/`.
- If hardware is available, run:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

Proceed only when:

- A latest-known-good report path is recorded.
- Existing SAFE/FULL behavior is understood and documented.
- Initial fixture names and machine ID convention are either confirmed or explicitly marked as open.

Stop conditions:

- No recent passing SAFE self-test can be produced.
- The firmware and Python runner disagree on the current report schema.

Rollback:

- Documentation-only milestone; revert doc changes if needed.

## Milestone 1: Python Qualification Skeleton, No Firmware Behavior Change

Objective:

Create a bounded Python qualification layer around the existing runner without changing firmware behavior or self-test protocol.

Allowed changes:

- Add `tools/qualification/` package.
- Keep `tools/run_selftest.py` working.
- Add manifest loading, run-folder creation, and report normalization.
- Add a gitignored local machine identity path, such as `local/machine_identity.json`.
- Add Python tests for manifest parsing and report output.

Not allowed:

- Firmware changes.
- New GUI.
- New hardware behavior.

Expected outputs:

- A `factory_acceptance_v0` manifest that runs existing SAFE/FULL tests.
- First-run machine identity creation with a stable `machine_id` and generated `machine_uuid`.
- An explicit `.gitignore` rule for the local machine identity location.
- Run folder layout:
  - `report.json`
  - `raw_selftest.json`
  - `summary.csv`
  - optional `traces/`
  - optional `plots/`
- A compatibility path where existing scripts still run.

Validation:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_run_selftest_metrics.py tests/test_run_selftest_goodbye.py tests/test_run_selftest_trace.py
.\env\Scripts\python.exe -m pytest -q
```

If hardware is available:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile SAFE
```

Proceed only when:

- Existing runner behavior is preserved.
- Manifest-driven execution can wrap an existing self-test run.
- A machine identity can be created once, reused on later runs, and included in reports without being tracked by git.
- Reports are written atomically to a per-run folder.
- Python tests pass.

Stop conditions:

- Existing `tools/run_selftest.py` command-line behavior breaks.
- Report schema becomes incompatible with existing tests.

Rollback:

- Revert `tools/qualification/` and wrapper changes.
- Keep existing `tools/run_selftest.py` path intact.

## Milestone 2: Firmware Diagnostics Extraction, Behavior Preserved

Objective:

Extract self-test code from `Orchestrator.cpp` into a dedicated diagnostics module without adding new tests or changing pass/fail behavior.

Allowed changes:

- Add diagnostics module files.
- Move result emission and test registry logic behind a small API.
- Add host tests for pure helper logic if introduced.
- Update firmware repo map if ownership/entrypoints change.

Not allowed:

- New motion, pressure, valve, or gripper behavior.
- Protocol format changes.
- Threshold changes.

Expected outputs:

- `Orchestrator.cpp` self-test case becomes a thin dispatcher.
- Existing SAFE and FULL test IDs still emit the same names and metrics, apart from intentional formatting fixes documented in the PR.
- Diagnostic tests are table-driven enough that new tests can be added without growing the dispatcher.

Validation:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
.\env\Scripts\python.exe -m pytest -q tests/test_run_selftest_metrics.py tests/test_run_selftest_goodbye.py tests/test_run_selftest_trace.py
```

Preferred HIL:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

Proceed only when:

- Local firmware checks pass.
- Existing SAFE/FULL HIL report has the same set of expected test IDs.
- No new hardware behavior is introduced.
- Aborts and timeouts still produce a valid JSON report.

Stop conditions:

- HIL becomes less stable than the recorded baseline.
- A self-test failure cannot be clearly attributed to the extraction.

Rollback:

- Revert the extraction commit.
- Re-run firmware local checks and SAFE HIL.

## Milestone 3: Stable Report Schema and Analyzer Gate

Objective:

Separate raw firmware metrics from Python-derived analysis so acceptance thresholds can evolve without reflashing firmware.

Allowed changes:

- Add report schema versioning.
- Add analyzer functions for existing motion, pressure, valve, and safety metrics.
- Add threshold maturity states: `informational`, `candidate`, and `acceptance`.
- Add CSV summary generation for comparing machines.
- Add tests around analyzers using sample reports.

Not allowed:

- New firmware tests.
- GUI launch controls.

Expected outputs:

- `report.json` includes:
  - run metadata
  - firmware metadata
  - machine ID
  - fixture ID
  - raw firmware results
  - derived analysis
  - final verdict
  - warnings and operator notes
- `summary.csv` includes stable columns for fleet comparison.
- Analyzer results distinguish:
  - infrastructure failure
  - fixture/setup failure
  - machine performance failure
- Initial empirically-derived thresholds can be recorded as `candidate` before they are promoted to `acceptance`.

Validation:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Proceed only when:

- Existing raw reports can be converted without data loss.
- Analyzer tests cover passing, failing, aborted, and missing-metric cases.
- The schema has a version field and migration note.

Stop conditions:

- Analyzer pass/fail disagrees with raw firmware summary without an explicit reason.
- Report fields are ambiguous for machine acceptance.

Rollback:

- Revert analyzer/report changes.
- Keep raw self-test artifacts as the source of truth.

## Milestone 4: Motion Qualification Slice

Objective:

Add the first new factory diagnostic that quantitatively checks gantry repeatability without broadening pressure or valve behavior.

Proposed test IDs:

- `2007 motion_home_repeatability_factory`
- `2008 motion_pattern_return_factory`

Firmware responsibilities:

- Home axes with existing homing primitives.
- Execute bounded motion patterns.
- Re-home or probe limit switch repeatability.
- Report per-axis repeatability metrics.
- Restore to a safe home or known idle state.

Python responsibilities:

- Select repetitions and patterns from manifest.
- Analyze drift, outliers, and failure modes.
- Report that this is repeatability/lost-step evidence, not absolute metrology unless an external measurement fixture is added.

Expected metrics:

- `2007` reports compact frame-budget-safe aliases: `axis`, `rep`, `x_min`, `x_max`, `x_span`, `y_min`, `y_max`, `y_span`, `ret_err`, `move_to`, `home_to`.
- `2008` reports compact frame-budget-safe aliases: `axis`, `rep`, `pts`, `ret_err`, `x_ret`, `y_ret`, `move_to`, `home_to`, `bound`.
- These metrics are repeatability/lost-step indicators from firmware positions and homing drift, not absolute metrology.

Validation:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

Manual checklist:

- Motion envelope is clear.
- Axes are mechanically assembled and free to move.
- Emergency stop path is available.
- Operator confirms no pressure fixture is required.

Proceed only when:

- Motion test passes on a known-good machine.
- Abort during the test leaves motors disabled or in an explicitly safe state.
- Python report flags repeatability failures without hiding raw metrics.

Stop conditions:

- Any unexpected motion beyond the planned envelope.
- Limit switch behavior is inconsistent before qualification patterns begin.

Rollback:

- Disable new motion selectors in manifest.
- Revert firmware diagnostic test additions if needed.

## Milestone 5: Pressure Regulator Leak and Step-Position Slice

Objective:

Add quantitative regulator tests for hold stability, leak suspicion, target repeatability, and motor step-position consistency.

Proposed test IDs:

- `2201 pressure_hold_leak_factory`
- `2202 pressure_target_cycle_repeatability_factory`
- `2203 pressure_motor_position_hysteresis_factory`

Firmware responsibilities:

- Use existing regulator control loops and pressure sensors.
- Hold selected targets for bounded durations.
- Cycle between pressure targets.
- Record pressure and motor position snapshots.
- Emit compact metrics and optional trace chunks.
- Restore baseline targets and pause regulators.

Python responsibilities:

- Fit pressure decay or correction demand over time.
- Compare motor position at repeated target pressures.
- Flag likely leaks, step loss, hysteresis, or settling problems.

Implemented metrics use compact names to stay inside the existing self-test result frame budget:

- `2201`: `channel`, `target_raw`, `hold_ms`, `p_start`, `p_end`, `slope_raw_min`, `corr_steps`, `motor_start`, `motor_end`, `ready_miss`, `timeout`
- `2202`: `channel`, `cycles`, `low_raw`, `high_raw`, `settle_max_ms`, `err_max`, `low_span`, `high_span`, `ready_miss`, `timeout`
- `2203`: `channel`, `target_raw`, `visits`, `pos_min`, `pos_max`, `repeat_span`, `hyst_span`, `err_max`, `ready_miss`, `timeout`

Status:

- Implemented in firmware FULL profile after the existing pressure step-response test and before valve/pulse tests.
- Added `factory_acceptance_v2` with the 28-test FULL suite and candidate Python analyzer rules for the new pressure metrics.
- Validated on hardware with FULL HIL report `hil_reports/selftest_20260513_191209.json`: non-aborted, `28/28` passing.
- Converted the raw HIL report through `tools/run_qualification.py --manifest factory_acceptance_v2`; qualification verdict was `pass` with no warnings.
- During Milestone 6 HIL, the 2201-2203 pressure waits were aligned with the existing candidate analyzer band: test `2003` still uses the strict regulator ready tolerance, while the M5 qualification rows may proceed once pressure is within the candidate `err_max` band so Python owns performance warnings.

Validation:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Direct Pi diagnostic example after flashing known firmware:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --timeout-ms 240000 --out hil_reports/selftest_pressure_hold_now.json
```

Manual checklist:

- Pressure plumbing is connected to the expected test fixture.
- Dummy head or blocked fixture state is correct for the selected test.
- Safe maximum pressure is confirmed in the manifest.

Proceed only when:

- Known-good machine produces stable pressure metrics.
- Known induced leak or loose connection produces a clearly worse metric, if a safe induced-fault test is available.
- Regulators return to baseline or paused state at test end.

Stop conditions:

- Pressure exceeds safe bounds.
- Regulator cannot reach a low, conservative target during preflight.
- Motor position telemetry is unavailable or ambiguous.

Rollback:

- Disable pressure qualification selectors in manifest.
- Revert firmware pressure diagnostic additions.

## Milestone 6: Valve Pulse Repeatability Slice

Objective:

Measure fast valve repeatability using pressure-drop traces while accounting for chamber depletion trends.

Proposed test IDs:

- `2401 print_valve_pulse_drop_repeatability_factory`
- `2402 refuel_valve_pulse_drop_repeatability_factory`
- `2403 dual_valve_interaction_factory`

Firmware responsibilities:

- Stabilize target pressure.
- Generate deterministic valve pulse trains.
- Capture pressure trace samples and pulse events.
- Report timing and pressure-drop metrics.
- Restore regulator and valve safe state.

Python responsibilities:

- Fit pulse index versus pressure drop to estimate depletion trend.
- Compute residual variation after trend correction.
- Flag outliers and inconsistent pulse timing.

Expected metrics:

- `2401` and `2402` use compact frame-budget-safe names: `ch`, `pulses`, `pw_us`, `hz`, `mean`, `cv_pct`, `slope`, `out`, `rec_w`, `slip_w`, `ready`, `sc`, `ec`.
- `2403` reports paired print/refuel interaction metrics: `mode`, `pulses`, `p_pw`, `r_pw`, `p_mean`, `r_mean`, `ratio`, `delta`, `p_out`, `r_out`, `slip_w`, `ready`.

Status:

- Implemented in firmware FULL profile after `2005 print_refuel_pulse_integrity_full` and before `2006 emergency_abort_and_safe_stop_full`.
- Added `factory_acceptance_v3` with the 31-test FULL suite and candidate Python analyzer rules for the valve pulse metrics.
- Local validation passed with `firmware/scripts/run_fw_checks.ps1 -Config Debug` and focused qualification tests.
- FULL HIL validation passed with `hil_reports/selftest_20260513_200311.json`: non-aborted, `31/31` passing.
- Converted the raw HIL report through `tools/run_qualification.py --manifest factory_acceptance_v3`; qualification verdict was `pass` with non-blocking candidate warnings for small observed valve pressure deltas.

Validation:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Direct Pi trace example:

```bash
python3 tools/run_selftest.py --port /dev/ttyAMA0 --profile FULL --pressure-trace --timeout-ms 240000 --out hil_reports/selftest_valve_repeatability_now.json
```

Manual checklist:

- Fluid/air path is configured for dry pneumatic qualification or approved dummy setup.
- Pulse count and pressure target are conservative.
- Printer head fixture is safe for repeated pulses.

Proceed only when:

- Trace artifacts are decodable.
- Trend-corrected pulse variation is reported in Python.
- Valve safe state is verified at test end.

Stop conditions:

- Pulse queue misses deadlines in a way that invalidates pressure-drop metrics.
- Pressure trace export becomes transport-unstable.

Rollback:

- Disable valve tests in manifest.
- Revert valve diagnostic test additions.

## Milestone 7: Gripper Seal Fixture Slice

Objective:

Add a fixture-gated gripper seal diagnostic using a non-captive dummy blocked printer head. The test is local-only and operator-mediated: the operator loads the dummy head when prompted, the firmware closes the gripper and measures seal behavior without opening it during the diagnostic, then the operator supports/removes the dummy head during an explicit teardown prompt.

Proposed test IDs:

- `2501 gripper_seal_closed_decay_factory`
- `2502 gripper_seal_hold_duration_factory`
- `2503 gripper_seal_repeatability_factory`

Deferred / not in the first implementation:

- Open-control testing with the dummy head loaded. Because the dummy head is not captive and there is no gripper-position feedback sensor, opening the gripper is an operator teardown action, not an in-test control condition.

Firmware responsibilities:

- Confirm or require fixture-gated profile.
- Apply gripper close using existing gripper primitives after an operator load prompt.
- Apply a conservative `1 psi` pressure stimulus through the head-side print/refuel 3-way valves.
- Capture pressure decay/drop metrics.
- Keep the gripper closed during diagnostic execution; do not automatically open it on normal diagnostic completion.
- On abort or completion, deactivate head-side valves, close regulator vent valves, and stop pressure safely while leaving the gripper closed until the operator confirms the dummy head is supported.
- Open the gripper only in a separate operator-confirmed teardown step.

Python responsibilities:

- Run this suite only from the local machine with interactive operator prompts; do not use unattended SSH/HIL automation for this fixture.
- Prompt the operator to load the dummy blocked printer head, confirm it is supported/aligned, and continue.
- Run a short print/refuel valve-click preflight using the normal command path and require operator confirmation before pressure timing begins.
- Prompt the operator to support the dummy head before any gripper-open teardown action.
- Prompt the operator to remove the dummy head after the gripper is opened.
- Send normal shutdown after fixture removal so regulators, motors, and LEDs return through the standard disconnect path.
- Analyze closed-grip pressure response to repeated burst stimuli and how long the gripper maintains seal without refresh.
- Flag insufficient sealing, inconsistent clamp behavior, short hold duration, or fixture setup failure.
- Store operator notes for fixture setup.

Expected metrics:

- `fixture`
- `cmd`
- `refresh`
- `target_raw`
- `valve_drive`
- `pulse_ms`
- `tick_us`
- `bursts`
- `head_valve_mode`
- `reg_vent`
- `reg_pause`
- `grip`
- `p_drop`
- `r_drop`
- `drop_raw`
- `seal_ms`
- `repeat_span_raw`
- `seal_ms_min`
- `timeout`
- `phase`, `cond_done`, and `ready_ms` on setup/skip failures

Initial suite shape:

- Before scored rows, the firmware homes P/R regulators through the regulator vent path with head-side print/refuel valves inactive, using the existing async regulator-home tasks so the orchestrator can keep checking into the watchdog. It then closes the gripper once, disables gripper refresh, and runs two unscored `2 s` conditioning bursts at `1 psi`.
- `2501` uses the conditioned loaded dummy head, charges the regulators to `1 psi`, pauses regulation, then applies one `2 s` diagnostic one-pulse burst through the head-side print/refuel valves.
- `2502` keeps the gripper closed without refreshing close pressure and applies six `2 s` paused-regulator bursts over roughly `60 s` to check whether the pressure response worsens over time.
- `2503` repeats three paused-regulator `2 s` burst applications on the same loaded dummy head while keeping the gripper closed and without re-closing between cycles. Multi-load repeatability is deferred until a higher-level multi-run workflow can safely prompt for load/support/remove between runs.
- Setup failures should emit rows for all expected IDs and a normal `CMD_SELFTEST_DONE`; only explicit self-test aborts should mark the run aborted. The Python runner also decodes any `CMD_RESET_REPORT` seen during the wait loop so MCU resets are reported as `mcu_reset_report_seen` with compact reset fields instead of only a status-only timeout.

Validation:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Manual HIL run should be operator-gated:

```bash
python3 tools/run_qualification.py --manifest gripper_seal_v1 --machine-id <machine_id> --fixture dummy_blocked_head_v1 --operator-prompts --port /dev/ttyAMA0 --timeout-ms 420000
```

The gripper seal suite is not intended for unattended SSH execution. If run over SSH, the operator running the command must be physically present at the machine and able to respond to prompts at the correct time.

Manual checklist:

- Dummy blocked printer head is not loaded before the suite starts unless the first prompt explicitly requests it.
- Operator is physically present at the machine and can support the dummy head during load/unload.
- Operator confirms the preflight print/refuel valve clicks before seal timing begins.
- Fixture is rated for the selected pressure.
- Operator confirms gripper area is clear.
- Operator confirms a soft catch/support path is available in case of power loss.
- Operator confirms no test step will intentionally open the gripper while the dummy head is unsupported.

Proceed only when:

- Closed-seal pressure retention is clearly measurable on a known-good machine.
- A loose/incorrect fixture is flagged as setup failure, not silently as machine failure.
- The teardown prompt leaves the dummy head safely removed and the gripper state known.

Stop conditions:

- Fixture leaks before closed-seal measurement begins.
- Pressure response cannot distinguish fixture state.
- Gripper refresh settings are unknown or unsafe.
- Operator cannot remain physically present through load, test, and unload prompts.
- The dummy head is dropped or becomes unsupported.

Rollback:

- Disable gripper tests in manifest.
- Revert gripper diagnostic additions.

## Milestone 8: Qualification Window in Main App

Objective:

Expose qualification runs and reports in the main app without duplicating backend logic.

Allowed changes:

- Add a separate `Machine Qualification` window or dialog.
- Add controller methods that invoke the qualification backend in a worker thread or subprocess.
- Add report browsing and summary display.

Not allowed:

- Reimplement analyzers in UI code.
- Make GUI-only qualification paths.
- Add new hardware behavior as part of the UI milestone.

Expected UI sections:

- Setup: machine ID, operator, fixture, suite.
- Checklist: required confirmations before hardware tests.
- Run: progress, current test, abort.
- Results: pass/fail table, metrics, warnings.
- Artifacts: report folder, plots, raw files.
- History: previous machine reports.

Initial read-only prototype:

- Add a button in the Firmware tab that opens a separate `Machine Qualification` window.
- Browse existing reports under `hil_reports/qualification/`.
- Show run summary, warnings/failures, subsystem result tables, selected-row details, and artifact paths.
- Do not start qualification runs, open serial ports, or invoke firmware diagnostics from this prototype.

Initial run shell:

- Add a `Run Qualification` tab beside `Review Results`.
- List available manifests from `tools/qualification/manifests/` and show expected tests, fixture notes, metrics, and operator-gated status.
- Launch `tools.qualification.runner.run_qualification()` through a Qt worker thread with coarse stage/log updates.
- Color expected-test rows from the final `qualification_report_v1`; live per-frame progress remains a later backend event API.
- Do not add a GUI abort button until the backend owns a safe abort path.

Live per-test event slice:

- Add additive `SELFTEST_EVENT` JSONL lines from `tools/run_selftest.py` while it decodes existing self-test frames.
- Forward event dictionaries through the qualification worker and controller without duplicating firmware protocol logic in the UI.
- Update expected-test rows during a run from raw result events, then keep final analyzer reconciliation from `qualification_report_v1`.

Timing and compact history slice:

- Estimate typical per-test duration from prior local `qualification_report_v1` result timestamps.
- Show suite elapsed time, expected remaining time, typical total time, and per-row typical/elapsed timing in the run tab.
- Keep timing empirical and local-only; do not add a persistent timing database or protocol changes.
- Show report history entries as compact `YYYY-MM-DD HH:MM:SS` labels while keeping report details in tooltips.

XY motion qualification slice:

- Add `xy_motion_v1` as a separate operator-gated FULL manifest requiring fixture `motion_clear_envelope_v1`.
- Select the suite with existing `CMD_SELFTEST_START` selector field value `2009`; no protocol layout or opcode changes.
- Firmware rows `2010 motion_xy_long_travel_factory` and `2011 motion_xy_raster_repeatability_factory` exercise X/Y travel inside `X<=45000`, `Y<=35000`, with a cable-chain guard requiring `Y>=500` whenever `X>1000`.
- Keep the suite out of `factory_acceptance_v3` until enough local data exists to tune thresholds and runtime.

Motion envelope qualification slice:

- Add `motion_envelope_v1` as a separate operator-gated FULL manifest requiring fixture `motion_full_envelope_v1`.
- Select the suite with existing `CMD_SELFTEST_START` selector field value `2019`; no protocol layout or opcode changes.
- Firmware rows `2012`-`2016` cover reverse long XY travel, diagonal XY travel, a 16 x 24 plate raster from `(43000,13000)` toward `(33000,30000)`, Z long travel to `39000`, and homing from already-triggered X/Y/Z limit starts.
- The `2014` plate raster returns to a near-home `Y=500` measurement anchor before the post-raster home so drift is not inflated by a long-distance homing approach artifact.
- Keep `motion_envelope_v1` out of `factory_acceptance_v3`; use it for explicit, operator-confirmed full-envelope qualification runs.

Pressure regulator qualification slice:

- Add `pressure_regulator_v1` as a separate operator-gated FULL manifest requiring fixture `pressure_closed_loop_v1`.
- Select the suite with existing `CMD_SELFTEST_START` selector field value `2299`; no protocol layout or opcode changes.
- Firmware rows `2210`-`2219` cover idle P/R pressure stability, regulator homing repeatability, print/refuel 2 psi holds, print/refuel cycling through adjacent 1 psi target steps, print/refuel 2 psi hysteresis approaches, and print/refuel `1 -> 2 -> 3 -> 2 -> 1 psi` step ladders.
- The ladder targets use the existing raw conversion: `1 psi=2512`, `2 psi=3386`, and `3 psi=4259`.
- Pressure-regulator qualification target changes are split into at most 1 psi waits and include a diagnostic motor-travel guard so excessive regulator travel fails rows cleanly instead of relying on the regulator internal step-limit/watchdog path.
- Normal pressure-regulator setpoint changes now slew the control target at `2 psi/sec` (`1748 raw/sec`) and cap commanded motor speed at `16000 Hz` only while a setpoint transition is active. Once the ramp reaches the requested target, ordinary pressure maintenance and dispense recovery use the existing behavior.
- Active pressure qualification rows `2212`-`2219` perform a fresh regulator home before starting pressure motion and report `home_to`, `slew`, and `cap_hz` so stale home references and no-slew regressions are visible in `qualification_report_v1`.
- `2211` performs an unscored setup home before measured P/R homing repetitions and reports measured success counts (`p_n`, `r_n`); span and drift are computed only from successful measured homes.
- `pressure_regulator_v1` target waits rely on the production regulator ready state, with no qualification-only `100 raw` acceptance fallback.
- `2214`/`2215` report same-direction cycle spans as `low_dn_span` and `high_up_span`; `2216`/`2217` report same-direction `below_span`/`above_span` and keep cross-direction `hyst_span` informational.
- `2214`/`2215` and `2218`/`2219` report informational `over`/`under` raw-pressure transient metrics to support regulator speed tuning.
- Keep `pressure_regulator_v1` out of `factory_acceptance_v3`; use it for explicit, operator-confirmed pressure regulator qualification runs before deciding whether any rows belong in the default FULL suite.

Valve characterization qualification slice:

- Add `valve_characterization_v1` as a separate operator-gated FULL manifest requiring fixture `valve_closed_loop_pulse_matrix_v1`.
- Select the suite with existing `CMD_SELFTEST_START` selector field value `2499`; no protocol layout or opcode changes.
- Firmware rows `2473` and `2474` execute print/refuel valve pulses at `2 psi=3386`, across matched grouped `1500`, `3000`, and `4500 us` pulse widths. Each width group now runs its own unmeasured conditioning pulse immediately before the measured repeats. The first measured pulse after each width change is kept in the artifacts but excluded from steady fixed-width settled-drop aggregates.
- The suite homes P/R regulators asynchronously once at startup and reports `home_to` on every row so selected valve rows do not depend on the default FULL-suite motion-home gate.
- Row `2475` remains a no-actuation balance row. Python derives print/refuel channel balance from the isolated 2 psi trace artifacts.
- Active-regulator recovery behavior is deferred to a future dummy-head or restricted-flow fixture suite so this slice focuses on valve actuation repeatability and pulse-width linearity.
- Valve response is computed in Python from trace sample windows around each pulse rather than immediate pulse-start/pulse-end event deltas or firmware-side aggregation. `raw_selftest.json` keeps compact MCU execution rows; `report.json` and `summary.csv` are enriched from the trace artifacts. The main `m15/m30/m45` linearity metrics use the post-ring settled pressure drop, measured from the median pressure in the `pulse_end+80 ms` to `pulse_end+150 ms` window.
- When `valve_characterization_v1` runs, it focuses pressure sampling on the tested channel, aligns each pulse to a fresh sample, records per-replicate regulator motor position context, and exports annotated pressure trace artifacts and static plots for stitched time-course review, replicate overlays, settled response-vs-width trends, settled drop versus motor position, ringing amplitude, actuation latency, and baseline noise / signal-to-noise inspection. Transient ringing amplitude and first-deviation latency are reported separately as `rg*` and `lt*`; missing latency/ring detections are informational (`lat_miss` / `ring_miss`) and no longer invalidate a settled pressure-drop replicate.
- Keep response magnitude and balance metrics informational for the first data-collection slice; analyzer rules focus on execution integrity such as timeout, readiness, sample/event availability, rejects, and deadline slip.
- Keep `valve_characterization_v1` out of `factory_acceptance_v3` until enough fixture data exists to set meaningful acceptance thresholds.

Valve gap sweep exploratory slice:

- Add `valve_gap_sweep_v1` as a separate operator-gated FULL manifest using the same closed-loop valve fixture and selector field value `2498`.
- Firmware rows `2476` and `2477` test print/refuel `1500 us` pulses at `2 psi` with post-ready settle gaps of `250`, `500`, `1000`, `2000`, and `5000 ms`, eight measured replicates per gap.
- Firmware rows `2478` and `2479` provide print/refuel `3000` and `4500 us` controls at `500` and `2000 ms`, four measured replicates per condition.
- Per-replicate traces record requested gap, previous pulse width, actual pulse-to-pulse interval, and regulator motor position so fixed-width short-pulse decay can be separated from timing and pneumatic memory effects.
- Gap sweep settled-drop magnitudes remain informational. Firmware rows check startup homing, pressure readiness, fresh samples, and trace sample/event capture; Python adds settled-drop rejection counts and gap/control means from exported traces. Missing latency/ring detections are retained as diagnostic context rather than pass/fail failures.

Gripper seal stress qualification slice:

- Add `gripper_seal_stress_v1` as a separate operator-gated FULL manifest requiring fixture `dummy_blocked_head_motion_v1`.
- Select the suite with existing `CMD_SELFTEST_START` selector field value `2599`; no protocol layout or opcode changes.
- The Python runner uses the same explicit dummy-head prompt, valve-click preflight, support-before-release prompt, gripper release/off teardown, and GOODBYE handoff path as `gripper_seal_v1`.
- Firmware rows `2510`-`2513` keep MCU pass/fail focused on execution integrity: P/R regulator startup homing, pressure readiness, trace export, gripper refresh state, and X/Y raster safety counters.
- `2510` measures static dummy-head seal response at 1, 2, and 3 psi with gripper refresh disabled. `2511` measures repeated 3 psi challenges while normal gripper refresh is enabled at `30000 ms`. `2512` homes X/Y before any motion, then runs the 384-well endpoint-interpolated plate raster while launching 3 psi pulse-window traces at `10000 ms` intervals. `2513` compares pre/post-raster 3 psi static seal traces.
- Gripper trace analysis is Python-derived from exported pressure traces. `raw_selftest.json` remains the MCU source of truth; `report.json` and `summary.csv` are enriched with baseline, end-of-pulse drop, post-pulse pressure, slope, noise, SNR, matrix, refresh, raster, and pre/post comparison summaries.
- Keep `gripper_seal_v1` as the quick local baseline and keep `gripper_seal_stress_v1` out of `factory_acceptance_v3` until enough dummy-head motion-stress data exists to set acceptance thresholds.

Validation:

```powershell
.\env\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Manual app validation for the read-only prototype:

- Launch app.
- Open qualification window.
- Load an existing report.
- Confirm subsystem tabs, warnings/failures, selected-row details, and artifact paths match `report.json`.
- Confirm the window can be closed and reopened from the Firmware tab.

Manual app validation before enabling run launch:

- Start a dry-run or SAFE-only suite if hardware is connected.
- Confirm abort/cancel path does not leave backend process running.

Proceed only when:

- CLI qualification remains fully functional.
- UI can display existing reports before it is allowed to launch hardware tests.
- Worker/subprocess errors are surfaced clearly.

Stop conditions:

- UI hangs during serial/HIL execution.
- GUI and CLI produce different report interpretations.

Rollback:

- Hide or remove the qualification window.
- Keep CLI/report backend.

## Milestone 9: Multi-Machine Trend and Threshold Refinement

Objective:

Use reports from multiple machines to refine thresholds and identify drift, assembly variation, and recurring failure modes.

Allowed changes:

- Add aggregation tooling.
- Add trend plots and fleet CSV exports.
- Adjust manifest thresholds based on documented evidence.

Not allowed:

- Loosen thresholds just to make failing machines pass.
- Change firmware behavior without a separate diagnostic or control milestone.

Expected outputs:

- Fleet summary CSV.
- Per-test distributions across machines.
- Recommended threshold updates with rationale.
- Known-good baseline set.

Validation:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Proceed only when:

- At least several machine qualification reports are available.
- Threshold changes are traceable to data.
- Outliers can be traced back to machine, fixture, or operator notes.

Stop conditions:

- Reports are not comparable because schemas or suite versions drifted.
- Fixture revisions are mixed without being recorded.

Rollback:

- Revert threshold changes in manifests.
- Preserve raw historical reports.

## Suggested First Implementation Sequence

1. Milestone 0 is complete with the current latest-known-good report and fixture assumptions.
2. Milestone 1 is complete with qualification reports, manifests, and local machine identity support.
3. Implement Milestone 2 to make firmware diagnostics extensible without behavior changes.
4. Add one hardware slice at a time: motion, pressure, valves, gripper.
5. Add the app window only after CLI/report behavior is proven.

## Definition of Done For Each Milestone

Every milestone must end with:

- Files changed listed in the summary.
- Validation commands and results.
- Known risks and edge cases.
- Rollback steps.
- A clear statement of whether the next milestone is unblocked.

Hardware-facing milestones must also include:

- Fixture used.
- Machine ID.
- Report path.
- Safety checklist result.
- Any operator-observed issues.
