# Regulator Optimization Plan

## Purpose

This document breaks the proposed regulator optimization system into small,
reviewable stages with explicit checkpoints. The goal is to tune pressure
regulator behavior under real printing conditions, especially stream-mode
conditions where 20 Hz printing gives the regulator less than 50 ms to recover
from each valve pulse.

The system should let an operator test candidate regulator parameters using a
real calibrated printer head, collect pressure traces from the MCU, analyze the
results offline, and promote selected parameter sets into named regulator
profiles that can be applied by print mode.

## Current Problem

The existing regulator can fall outside the acceptable pressure band after a
valve pulse. When printing at 20 Hz, the next pulse may be due before pressure
has recovered, so printing pauses until `PressureRegulator::isPressureOk()`
returns true again. This is more visible in stream mode because stream-mode
printing tends to use higher pressure and longer pulse widths than water
droplet-mode printing.

Previous self-test tuning required firmware changes to test new parameter sets
and often ran without a printer head. That made iteration slow and the pressure
drop unrealistic because the pneumatic load did not match actual printing.

## Target Call Path

The target calibration flow is:

`Calibration window -> Controller -> Machine_FreeRTOS command queue -> Comm frame -> Orchestrator -> PressureRegulator config -> Printer pulse run -> PressureTraceRecorder -> host trace artifacts`

The normal production application flow remains:

`View -> Controller -> Machine_FreeRTOS command queue -> Comm frame -> Orchestrator -> Printer -> PressureRegulator -> PressureSensor/Stepper`

## Current Relevant Infrastructure

The repo already contains useful pieces for this work:

- `PressureRegulator::RecoveryConfig`
- `PressureRegulator::SlewConfig`
- `PressureRegulator::ReadyConfig`
- `PressureRegulator::setRecoveryConfig(...)`
- `PressureRegulator::setSlewConfig(...)`
- `PressureRegulator::setReadyConfig(...)`
- `PressureRegulator::notifyPulseStart(...)`
- `PressureRegulator::notifyPulseEnd(...)`
- `PressureTraceRecorder`
- pressure trace self-test export through `tools/run_selftest.py`
- pressure trace plotting and analysis in `tools/plot_pressure_traces.py`

The missing pieces are mostly:

- a stable host-side profile schema
- a safe runtime command surface for applying candidate profiles without
  reflashing
- an operator-facing calibration workflow
- offline comparison and promotion of successful profiles
- mode-specific application of promoted profiles during normal printing

## Guiding Principles

- Keep every stage independently reviewable and testable.
- Prefer RAM-only candidate application until a profile is explicitly promoted.
- Restore the previous regulator settings on completion, cancel, timeout, or
  error.
- Keep firmware commands bounded, clamped, and backward-compatible.
- Do not change normal device protocol behavior except through explicit,
  documented command additions.
- Keep initial tuning focused on recovery, slew, and ready-band behavior before
  exposing raw PID gain editing.
- Treat raw traces as evidence and promoted profiles as operational choices.
- Preserve the ability to run calibration and analysis without the GUI once the
  backend exists.

## Non-Goals For The First Pass

- Do not persist regulator profiles to MCU flash.
- Do not automatically select new profiles from one calibration run.
- Do not remove or replace existing self-tests.
- Do not expose unrestricted PID gains in the first implementation.
- Do not bypass existing pressure-ready safety checks during normal printing.
- Do not make stream mode print faster by ignoring recovery failures.

## Safety Guardrails

Every hardware-facing stage must include:

- bounded pressure and pulse-width limits
- bounded pulse count and run duration
- operator confirmation that a calibrated printer head is installed
- clear stop/cancel behavior
- previous-profile restore on all exit paths
- trace/run metadata that records the profile and printing condition
- automated tests for command validation and restore behavior

Candidate profile application must be temporary by default. A profile becomes a
production profile only after explicit promotion.

## Suggested Profile Scope

Profiles should be keyed by mode and optionally by printer-head or print-profile
context. A single global stream profile may be enough to start, but the schema
should not block future head-specific or reagent-specific tuning.

Initial profile dimensions:

- mode: `droplet`, `stream`, `custom`
- channel: `print`, `refuel`
- recovery config
- slew config
- ready config
- optional metadata: source run, operator notes, calibrated head, reagent,
  print pressure, pulse width, frequency

## Stage 1: Schema And Contract Design

Status: complete as a documentation/specification stage once
`docs/regulator_profiles_schema.md` has been reviewed. No firmware, host, UI,
or protocol behavior changes are part of this stage.

### Goal

Define the profile schema, run artifact schema, parameter bounds, and command
contract before changing hardware behavior.

### Scope

- Add a documented `RegulatorProfiles.json` schema.
- Define candidate run artifact metadata.
- Define safe parameter bounds for recovery, slew, and ready settings.
- Define how temporary candidate application differs from promoted profiles.
- Define the command payload shape for future firmware commands.
- Document firmware validation commands that will be required once firmware is
  touched.

### Files

- `docs/regulator_optimization_plan.md`
- `docs/regulator_profiles_schema.md`

### Locked V1 Decisions

The detailed Stage 1 specification lives in
`docs/regulator_profiles_schema.md`. It locks the following decisions for the
next implementation stages:

- `RegulatorProfiles.json` defaults live in
  `FreeRTOS-interface/Presets/RegulatorProfiles.json`.
- Generated calibration artifacts live under `local/regulator_optimization/`.
- Initial automatic profile selection is mode-level only: `droplet` and
  `stream`.
- Printer-head and reagent identifiers are recorded in metadata but are not used
  for automatic profile selection in v1.
- Runtime candidate profile application is RAM-only.
- V1 tuning exposes recovery, slew, and ready configs only; PID gains are out of
  scope.
- Stage 2 reserves command IDs `0x68` through `0x6C`.
- Stage 2 uses one channel per command and the existing `p1/p2/p3` 32-bit TLV
  fields only.
- The first calibration workflow uses the existing pressure trace export path
  before adding app-owned trace capture commands.

### Checkpoint

- The schema and command contract have been reviewed.
- The chosen parameter bounds are documented.
- No app or firmware behavior has changed.
- `docs/regulator_profiles_schema.md` contains exact schema field names,
  initial bounds, command names, and reserved command IDs.

### Validation

- Documentation review.
- No automated test required unless validation code is added in this stage.
- Sanity check:

```powershell
rg "Open[ ]Decisions|T[B]D|TO[D]O" docs/regulator_profiles_schema.md docs/regulator_optimization_plan.md
```

### Rollback

- Remove `docs/regulator_profiles_schema.md` and revert the Stage 1 status
  update in this file.

## Stage 2: Runtime Regulator Profile Commands

### Goal

Add firmware and host command support to apply regulator parameters at runtime
without reflashing firmware.

### Scope

- Add one or more commands for setting regulator profile components.
- Apply settings to RAM only.
- Support print and refuel channels independently.
- Clamp or reject out-of-range values.
- Add a way to query or restore the current baseline profile.
- Keep all changes compatible with the existing command queue and ACK behavior.

### Preferred Command Strategy

Use compact, bounded commands rather than one large unstructured JSON payload.
The concrete command contract is specified in
`docs/regulator_profiles_schema.md`.

Reserved command IDs:

- `0x68`: `CMD_SET_REG_RECOVERY_PROFILE`
- `0x69`: `CMD_SET_REG_SLEW_PROFILE`
- `0x6A`: `CMD_SET_REG_READY_PROFILE`
- `0x6B`: `CMD_RESTORE_REG_PROFILE`
- `0x6C`: `CMD_QUERY_REG_PROFILE` reserved for a future safe snapshot response

Stage 2 must use one channel per command and the existing `p1/p2/p3` 32-bit TLV
fields only. Recovery config is split across staged chunks and committed only
after all chunks validate for the same channel. Avoid changing existing command
semantics.

### Proposed Files

- `firmware/Core/Inc/PressureRegulator.h`
- `firmware/Core/Src/PressureRegulator.cpp`
- `firmware/Core/Src/Orchestrator.cpp`
- `firmware/Core/Inc/Comm.h` if new command constants are centralized there
- `FreeRTOS-interface/Machine_FreeRTOS.py`
- `FreeRTOS-interface/Controller.py` if controller wrappers are added
- firmware host tests under `firmware/tests_host/`
- Python protocol/command tests under `tests/`

### Required Firmware Prep

Before editing anything under `firmware/`, read `firmware/AGENTS.md`.

Required firmware validation after implementation:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

### Checkpoint

- Host firmware tests prove decode, clamp/reject, apply, and restore behavior.
- Python tests prove command encoding and queue behavior.
- Existing pressure self-test behavior remains available.
- No UI uses the new commands yet.

### Validation

- Firmware checks:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

- Targeted Python tests for command encoding:

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_machine_send_path_guards.py tests/test_protocol_contract_firmware_boundary.py
```

The exact targeted test list may change based on implementation files.

### Rollback

- Revert the new command handlers and command map entries.
- Firmware defaults remain the fallback because candidate application is RAM-only.

## Stage 3: Host Profile Store And Validation

### Goal

Add Python-side loading, saving, validation, and atomic writes for regulator
profiles. This stage should not automatically apply profiles during printing.

### Scope

- Add a small profile store module or model component.
- Load `RegulatorProfiles.json` from a predictable preset/config location.
- Validate schema version, required keys, numeric ranges, and channel fields.
- Write changes atomically.
- Provide defaults if the file is missing.
- Preserve unknown metadata fields where practical.

### Proposed Files

- `FreeRTOS-interface/RegulatorProfiles.py` or similar new module
- `FreeRTOS-interface/Presets/RegulatorProfiles.json` if defaults are tracked
- `FreeRTOS-interface/Model.py` only if needed to wire the store into app state
- `tests/test_regulator_profiles.py`

### Checkpoint

- Valid profile files load.
- Invalid profile files fail closed with clear errors.
- Atomic write tests pass.
- The app can start with no profile file and use safe defaults.
- No production mode auto-application yet.

### Validation

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_regulator_profiles.py
```

Run the full Python suite if the store is integrated into `Model.py`:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

### Rollback

- Remove the profile store module and default JSON.
- The app continues using firmware defaults.

## Stage 4: Calibration Window MVP

### Goal

Expose a minimal operator workflow that applies one candidate profile, runs one
bounded real-head pulse test, captures pressure traces, saves artifacts, and
restores the previous regulator settings.

### Scope

- Add an advanced calibration window launch point from the main app.
- Let the operator select mode, channel, pulse count, frequency, pressure, pulse
  widths, and one candidate profile.
- Require explicit confirmation that a calibrated printer head is installed.
- Apply candidate profile in RAM.
- Run a bounded pulse trace test.
- Save run metadata and raw trace artifacts.
- Restore the previous profile on completion, cancel, error, or timeout.

### Proposed Files

- `FreeRTOS-interface/View.py` or a new dialog module
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/Machine_FreeRTOS.py`
- `FreeRTOS-interface/RegulatorProfiles.py`
- `tests/test_regulator_calibration_window.py`
- `tests/test_controller_regulator_profiles.py`

### Command Order Requirement

The MVP workflow should be testable as this sequence:

1. Snapshot current regulator profile.
2. Apply candidate regulator profile.
3. Apply test pressure and pulse-width settings.
4. Wait for pressure ready.
5. Run bounded pulse trace.
6. Export trace and metadata.
7. Restore previous regulator profile.
8. Return the app to idle state.

### Checkpoint

- Fake-machine/controller tests prove command order.
- Cancel/error tests prove restore is attempted.
- Manual dry-run can execute without a real hardware pulse by using fakes or a
  disabled pulse path.
- No automatic profile promotion exists yet.

### Validation

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_regulator_profiles.py tests/test_controller_regulator_profiles.py tests/test_regulator_calibration_window.py
```

Run the full Python suite if core controller or view behavior changes:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

### Manual Checklist

- Window opens from the main app.
- Candidate profile can be selected.
- Unsafe values are rejected before hardware commands are queued.
- Start button is disabled while a run is active.
- Stop/cancel attempts to restore the previous profile.
- The saved run folder contains metadata and trace files.

### Rollback

- Remove the launch point and dialog.
- Runtime command support can remain unused.
- Firmware defaults continue to control normal printing.

## Stage 5: Offline Analysis And Ranking

### Goal

Extend offline tooling so candidate trace runs can be compared without relying
on the GUI.

### Scope

- Analyze one run folder or a set of trace files.
- Emit summary JSON, CSV, and plots.
- Rank candidates by objective metrics.
- Preserve raw trace files unchanged.
- Make the scoring formula explicit and configurable enough for iteration.

### Initial Metrics

- `ready_miss_count`
- worst recovery time
- median recovery time
- max undershoot
- max overshoot
- pressure-ok duty ratio
- recovery-active duty ratio
- pulse interval jitter
- deadline slip
- requested/applied Hz saturation
- zero crossing count
- rejected sample ratio

### Suggested Score Shape

Lower is better:

```text
score =
  1000 * ready_miss_count
  + 4 * worst_deadline_slip_ms
  + 2 * worst_recovery_ms
  + max_undershoot_raw
  + max_overshoot_raw
  + zero_crossing_count
  + saturation_penalty
```

The score should be treated as a sorting aid, not as an automatic promotion
decision.

### Proposed Files

- `tools/plot_pressure_traces.py` or a new `tools/analyze_regulator_runs.py`
- `tests/test_regulator_trace_analysis.py`

### Checkpoint

- Given saved trace JSONs, the tool emits:
  - per-trace analysis JSON
  - per-pulse CSV
  - candidate summary CSV
  - pressure/recovery plots
  - ranked candidate summary
- Tests cover representative trace fixtures and edge cases.

### Validation

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_pressure_trace_plots.py tests/test_regulator_trace_analysis.py
```

### Rollback

- Remove the analysis tool changes.
- Raw trace artifacts remain usable manually.

## Stage 6: Multi-Candidate Calibration Workflow

### Goal

Let an operator test a small batch of candidate profiles in one session while
keeping every individual run bounded and restorable.

### Scope

- Select a candidate set.
- Repeat each candidate a configurable number of times.
- Randomize or alternate candidate order if needed to reduce drift bias.
- Record baseline runs before and after the batch.
- Save a session manifest that references all candidate run folders.
- Launch offline analysis at the end of the batch or provide a command to run it.

### Proposed Files

- calibration window/dialog module
- controller orchestration helpers
- regulator profile store
- analysis tool integration
- tests for session manifests and command sequencing

### Checkpoint

- A real printer-head session produces a complete session folder.
- Session contains baseline, candidate, and restore metadata.
- Offline analysis can rank candidates from the session folder.
- Operator can discard all candidates without changing production settings.

### Validation

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_regulator_profiles.py tests/test_controller_regulator_profiles.py tests/test_regulator_trace_analysis.py
```

Manual hardware validation should include:

- confirm the printer head is installed and calibrated
- run a baseline trace
- run two low-risk candidate profiles
- confirm previous profile restore after each candidate
- confirm session report lists all candidates and outcomes

### Rollback

- Disable the batch workflow.
- Single-candidate MVP remains available.
- Production profiles are unchanged unless explicitly promoted.

## Stage 7: Profile Promotion And Mode-Specific Application

### Goal

Apply selected promoted profiles during normal operation based on print mode.

### Scope

- Add explicit profile promotion from analysis/calibration results.
- Set active profile IDs for `droplet` and `stream`.
- Apply the selected regulator profile when entering the corresponding mode or
  applying a print profile.
- Fall back to firmware defaults if no active profile exists or if validation
  fails.
- Restore/disable candidate-only profiles after calibration runs.

### Proposed Files

- `FreeRTOS-interface/RegulatorProfiles.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/View.py` if promotion UI is included
- `tests/test_regulator_profile_application.py`

### Checkpoint

- Controller tests prove stream mode applies the stream regulator profile.
- Controller tests prove droplet mode applies the droplet regulator profile.
- Missing or invalid profile falls back safely.
- Existing print-profile application behavior still works.
- Manual app test confirms the applied regulator profile is visible in run
  metadata or status diagnostics.

### Validation

```powershell
.\env\Scripts\python.exe -m pytest -q tests/test_regulator_profiles.py tests/test_regulator_profile_application.py
```

Full Python suite:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Firmware checks are required if this stage changes firmware:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

### Rollback

- Remove active profile IDs from `RegulatorProfiles.json` or set them to null.
- Disable the controller auto-apply hook.
- Firmware defaults remain available.

## Stage 8: Optional Refinements

These should wait until the core loop is proven with real traces.

### Optional: PID Gain Exposure

Expose PID gains only if recovery/feedforward and slew tuning cannot meet the
target. PID tuning carries a higher overshoot and ringing risk, so it should
have tighter bounds, stronger tests, and a smaller UI surface.

### Optional: Head-Specific Profile Selection

If trace data shows significant printer-head dependence, extend profile
selection by calibrated printer-head ID or head type.

### Optional: Reagent-Specific Profile Selection

If viscosity or material changes dominate pressure recovery, extend profile
selection by reagent or reagent class.

### Optional: Qualification Integration

Once stable, add a qualification manifest that verifies the active stream and
droplet profiles on a known fixture or calibrated head.

## Physical-Limit Interpretation

The calibration system should not assume all failures are tunable in software.
Trace analysis should explicitly report likely physical limits.

Possible physical-limit indicators:

- applied Hz saturates at the maximum for most of the recovery window
- recovery time remains above the pulse interval across all safe candidates
- undershoot scales strongly with pulse width and pressure despite aggressive
  recovery boost
- overshoot appears as soon as recovery boost is increased enough to reduce
  ready misses
- pressure sample rejection or sensor cadence limits dominate the trace

If these appear, next actions may involve pressure path volume, regulator motor
speed, pneumatic compliance, valve pulse settings, head resistance, or print
frequency rather than more aggressive controller parameters.

## Artifact Layout Recommendation

Store calibration sessions outside tracked source files by default, similar to
other generated run artifacts:

```text
local/regulator_optimization/
  session_YYYYMMDD_HHMMSS_<id>/
    session_manifest.json
    baseline_before/
      run_meta.json
      traces/
      analysis/
    candidate_stream_001_rep01/
      run_meta.json
      traces/
      analysis/
    candidate_stream_001_rep02/
      run_meta.json
      traces/
      analysis/
    baseline_after/
      run_meta.json
      traces/
      analysis/
    summary.csv
    ranking.json
```

Tracked source files should contain only schemas, defaults, tests, and code.
Generated calibration artifacts should not be committed unless a specific
golden fixture is intentionally added for tests.

## End-To-End Definition Of Done

The optimization system is complete enough for normal use when:

- candidates can be edited or loaded without reflashing firmware
- candidates are applied to the MCU in RAM only
- a real-head pulse test captures pressure traces with full metadata
- the previous profile is restored after every calibration run
- offline analysis compares candidates and reports objective metrics
- selected profiles can be explicitly promoted
- droplet and stream modes apply their active promoted profiles
- invalid or missing profiles fail closed to firmware defaults
- affected Python tests pass
- affected firmware host tests and headless build pass
- manual hardware validation has been run with a calibrated printer head

## Recommended First Milestone

Implement Stages 2 and 3 after Stage 1 review:

1. Add RAM-only firmware command support for recovery/slew/ready settings using
   the `docs/regulator_profiles_schema.md` command contract.
2. Add Python profile store and validation using the
   `docs/regulator_profiles_schema.md` JSON schema.

This creates the safe foundation for tuning without committing to the full UI
workflow. The first milestone should end with no automatic production behavior
change: profiles can be loaded, validated, and applied by explicit command only.

## Resolved Stage 1 Decisions And Deferred Items

Resolved for v1:

- Default tracked profiles live in `FreeRTOS-interface/Presets/RegulatorProfiles.json`.
- Generated calibration artifacts live under `local/regulator_optimization/`.
- Runtime candidate application is RAM-only.
- Stage 2 command IDs are reserved in the `0x68` through `0x6C` range.
- The first runtime command surface uses one channel per command.
- Automatic profile application starts with mode-level `droplet` and `stream`
  selection.
- The first calibration workflow uses existing pressure trace export before
  adding a new app-owned trace capture command.
- Initial recovery, slew, and ready bounds are defined in
  `docs/regulator_profiles_schema.md`.

Deferred until trace data or implementation pressure requires them:

- head-specific automatic profile selection
- reagent-specific automatic profile selection
- PID gain exposure
- MCU flash persistence for promoted profiles
- a compact query/snapshot response for `CMD_QUERY_REG_PROFILE`
