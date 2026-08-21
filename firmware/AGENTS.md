# Firmware - Agent Instructions (STM32 / CubeIDE)

## Scope and mission

These rules specialize the repository root instructions for `firmware/`.
Safely modify and validate the STM32 firmware that controls the physical
printer. Keep changes minimal, reviewable, and bound to an exact deployable
binary.

Firmware validation has three distinct lanes:

1. Host unit tests for pure logic.
2. Headless STM32CubeIDE build for the real target and tracked binary.
3. Explicitly authorized Pi HIL using the isolated development workflow.

## Layout

- `Core/Inc` and `Core/Src`: target source and generated integration code.
- `tests_host/`: CMake/CppUTest host tests.
- `tests_host/stubs/`: minimal HAL/FreeRTOS test stubs.
- `third_party/cpputest/`: CppUTest framework.
- `scripts/run_fw_unit_tests.ps1`: host-test lane.
- `scripts/build_firmware_headless.ps1`: target build lane.
- `scripts/run_fw_checks.ps1`: required combined host/build gate.
- `hil/flash_and_test.sh`: Pi flash and self-test runner used by the protected
  development supervisor.
- `artifacts/LabCraft_firmware.bin`: tracked deployable binary.
- Repository `tools/run_selftest.py`: Pi self-test report collector.

## Non-negotiable firmware safety

- Do not change message IDs, payload layouts, framing, parsing, or protocol
  semantics unless the user explicitly requests a protocol change.
- Avoid changes that could create unsafe motion, pressure, valve, pump, pulse,
  or timing behavior. State the verification and rollback plan before editing
  such code.
- SAFE must remain non-actuating. It may not dispatch motion, homing, pressure,
  pumps, valves, dispensing, cameras, balances, or FULL-only tests.
- Never run FULL unattended or reinterpret generic flashing authority as
  permission to actuate hardware.
- Never flash an arbitrary, untracked, locally substituted, or byte-mismatched
  artifact.
- Never infer installed firmware from a Git checkout or manually edit the
  external firmware-state file.

## Generated code

CubeMX-generated files must be edited only inside
`/* USER CODE BEGIN */ ... /* USER CODE END */` regions. Do not edit outside
those regions unless the file is clearly hand-written. Do not edit `.ioc`
unless the user explicitly requests it.

If generation status is unclear, search for `USER CODE BEGIN` markers and
assume the file is generated until proven otherwise.

## Required local validation

After any firmware source, firmware test, build-tool, or HIL-tool change, run:

`powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug`

This gate must pass the host tests and headless Debug build. If the combined
script is unavailable, run both:

- `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_unit_tests.ps1 -Config Debug`
- `powershell -ExecutionPolicy Bypass -File firmware/scripts/build_firmware_headless.ps1`

For fast iteration, the host-test command may be run alone, but it does not
replace the combined pre-commit gate.

The headless build must refresh
`firmware/artifacts/LabCraft_firmware.bin`. Commit that binary with the source
and tests produced by the same build/configuration. Verify the working binary
matches the tracked commit before HIL. Do not commit other transient build
outputs.

## Host-test design

Prefer pure logic that compiles without target peripherals:

- protocol encode/decode golden vectors, framing, parsing, and CRC;
- queues, ring buffers, bounds, math, and conversions;
- state-machine logic isolated from HAL/FreeRTOS calls;
- timeout and fault handling with deterministic inputs.

Do not directly host-compile peripheral initialization, interrupt handlers,
FreeRTOS startup, or register-dependent drivers. When production code includes
HAL/FreeRTOS headers, add only the minimal matching declarations under
`tests_host/stubs/`; do not invent target behavior that the test does not need.

Keep HAL/RTOS I/O at the edges. Split mixed logic into a host-tested pure
function and a thin target wrapper when practical.

## Authorized SAFE HIL

The legacy `firmware/scripts/run_fw_hil_windows.ps1` is not the isolated Pi
development workflow and must not be used for autonomous qualification. It can
upload into a selected repository and exposes broader profiles.

When the user has explicitly authorized exact development/released flashing
and the non-actuating SAFE profile, use the repository-level wrapper:

- `tools/run_pi_development_firmware.ps1 -Action Roundtrip`

Take current host, identity, operator, and known-good release arguments from
`README.md` and `docs/pi_development_workflow_plan.md`; do not encode transient
deployment values here.

Before the development flash, the supervisor must prove:

- clean/pushed Windows commit and clean detached Pi development worktree;
- tracked Windows/Pi development artifact byte identity;
- known-good released artifact manifest, provenance, and recovery command;
- valid external workflow/data binding and current firmware-state evidence;
- no application, updater, DFU, flash, or HIL process is running.

Success requires this fixed sequence:

1. Atomically record `recovery-required` before flashing.
2. Flash the exact development artifact.
3. Pass the strict 30-result non-actuating SAFE inventory.
4. Record exact `development` state and evidence.
5. Record `recovery-required` and flash the prevalidated released artifact.
6. Pass released SAFE 30/30.
7. Record exact `released` state.
8. Prove protected invariants match and no related process remains.

Autonomous work must never yield, commit another slice, or move to unrelated
work while development firmware remains installed.

## Attended development activation

`tools/run_pi_development_firmware.ps1 -Action Activate-Development` is an
attended exception. It requires the wrapper's execute switch and a fresh exact
human confirmation for that campaign. The confirmation authorizes only the
scope the user explicitly grants; it does not automatically authorize motion,
pressure, dispensing, camera, balance, or FULL tests.

After the attended session, or immediately after any launch failure, run:

- `tools/run_pi_development_firmware.ps1 -Action Restore-Released`

Then run the repository read-only status wrapper. If restoration cannot reach
released plus strict SAFE, preserve all evidence, do not launch either app,
and request attended recovery. Never repair the condition by editing JSON.

## Self-test reports and evidence

HIL evidence belongs outside Git worktrees:

- Windows: `verification_reports/development-workflow/firmware/`.
- Pi: the configured external `development-workflow/firmware-sessions/` root.

Use the structured report rather than terminal text alone. Require a complete,
non-aborted report, exact SAFE test inventory, zero failed results, skipped
actuation gates, and zero actuation/dispatch metrics. Treat missing reports,
aborts, framing faults, or incomplete metrics as failures requiring diagnosis.

When adding a self-test, keep the firmware emitter table-driven with a stable
numeric `test_id`, stable name, structured metrics, explicit timeouts, and
abort handling. New SAFE tests must remain non-actuating.

## Build and commit discipline

- Run headless builds in the isolated workspace provided by the scripts. Do
  not assume STM32CubeIDE is open on the same workspace.
- One firmware milestone per commit. Include source, host tests, build/HIL tool
  changes, and the same-build tracked `.bin` as applicable.
- Do not commit `tests_host/build/`, CubeIDE workspace metadata, temporary
  logs, or downloaded evidence.
- Update `firmware/docs/repo_map.md` when module ownership, entrypoints, or
  protocol handling changes.

## Definition of done

- The combined local firmware gate passes.
- The tracked `.bin` matches the changed source/configuration.
- Focused failure-path tests cover the change.
- Authorized HIL, when required, uses the isolated SAFE workflow and ends on
  verified released firmware with protected invariants unchanged.
- Evidence paths and PASS/FAIL summaries are reported.
- The handoff names changed modules, risks, edge cases, rollback, and any
  deferred attended testing.
