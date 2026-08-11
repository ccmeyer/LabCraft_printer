# Coordinated XY Milestone 1 Instrumentation Record

Status: `verified`

## Purpose

Measure the unchanged legacy X/Y timer ISR and scheduling behavior before the
motion profile or routing is modified. The measurements must distinguish the
cost of acceleration/deceleration profile work from the cost of the raw timer
entry rate while preserving the emitted pulse sequence.

## Clean Baseline Gate

The clean source baseline was validated before instrumentation edits.

| Field | Value |
| --- | --- |
| Command | `powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug` |
| Result | Pass |
| Host tests | 266/266 tests; 1,049 checks; 0 ignored; 0 filtered |
| CMake | 4.4.2 |
| Host compiler | MSVC 19.51.36256.0, x64 |
| STM32CubeIDE | 1.18.1 |
| ARM compiler | GNU Tools for STM32 13.3.rel1; GCC 13.3.1 20240614 |
| Firmware configuration | Debug, `-O0` |
| Source Git SHA | `113617029ee4fe41b51f64e3acb319bd1ab3e29b` |
| Rebuilt binary | `firmware/artifacts/LabCraft_firmware.bin` |
| Rebuilt binary SHA-256 | `3E0244262F6B064FDD0825A7B6CE1D1D01B239EEF5285B71ADF1C0A1A7304256` |
| Preserved Milestone 0 rollback SHA-256 | `FF653995F66BDB9667859028BDB8EA220A4C2D386C3ED06C8C385F31E8211CDA` |
| Build result | 0 errors; 3 existing warnings |

The first automated invocation was denied by the agent filesystem sandbox in
MSBuild `FileTracker` (`MSB4018`, access denied). The identical command passed
with normal build permissions. This was a host-side sandbox condition, not a
compiler, source, or firmware failure.

The headless build updated CubeIDE's machine-specific environment hash in
`firmware/.settings/language.settings.xml`. That metadata drift is excluded
from the milestone. The rebuilt firmware binary remains tracked intentionally.

## Firmware Artifact Policy

`firmware/artifacts/LabCraft_firmware.bin` is a required tracked output for
every firmware milestone. A firmware source commit must include the binary
built from that same source/configuration so the deployable image in Git stays
compatible with the code at that commit. Generated build directories and
machine-specific IDE metadata remain excluded.

## Confirmed Call Paths

### Normal XY command

`View/location/calibration request -> Controller.set_absolute_XY -> Machine_FreeRTOS.set_absolute_XY -> ABSOLUTE_XY (0x0E) -> Orchestrator CMD_ABS_XY -> Gantry::moveTo -> Gantry::moveBy -> Stepper::move for X and Y`

### Timer callback

`TIM2_IRQHandler/TIM7_IRQHandler -> HAL_TIM_IRQHandler -> HAL_TIM_PeriodElapsedCallback -> MX_DISPATCH -> Stepper::dispatch -> Stepper::_stepTick`

TIM2 drives X and TIM7 drives Y. Both timer interrupts currently use priority
5. The status task checks in to the watchdog and attempts a status frame every
50 ms. Normal `ABSOLUTE_XY` waits for both existing stepper completion bits.

### Qualification reporting

`qualification manifest -> tools/run_selftest.py -> CMD_SELFTEST_START selector -> Orchestrator -> DiagnosticsRunner -> existing self-test result frames -> qualification report`

No opcode, command payload, status tag, or normal transport frame will be
changed by this milestone.

## Frozen Slice 1: ISR Measurement Core

### Files

- `firmware/Core/Inc/StepperIsrInstrumentation.h` (new pure state and policy)
- `firmware/Core/Src/StepperIsrInstrumentation.cpp` (new pure implementation)
- `firmware/Core/Inc/Stepper.h` (fixed-size state and snapshot getter)
- `firmware/Core/Src/Stepper.cpp` (compile-gated DWT sampling around legacy work)
- `firmware/tests_host/tests/test_stepper_isr_instrumentation.cpp` (new host tests)
- `firmware/tests_host/CMakeLists.txt` (host source/test registration)
- `firmware/artifacts/LabCraft_firmware.bin` (matching tracked output)
- this evidence record and the parent trajectory plan

### Measurements

For each Stepper move, fixed-size state records:

- acceleration, cruise, deceleration, and completion entry counts;
- maximum measured `_stepTick()` cycles for each phase and overall;
- total timer callback entries;
- completed STEP pulses;
- timer-update-pending observations at the end of measured legacy work;
- maximum consecutive pending-observation streak;
- DWT move start/end values and observed counter wraps.

Cycle reads bracket the existing legacy work. State aggregation occurs after
the end timestamp so the recorded legacy duration does not include aggregation
cost. The compile-time gate is `LC_STEPPER_ISR_INSTRUMENTATION_ENABLE`; the
Milestone 1 measurement build enables it, and a disabled build removes the
runtime sampling/aggregation path.

### Preserved invariants

- The existing phase comparisons and ARR calculations remain the source of
  the timer period.
- No measurement value feeds back into motion control.
- GPIO writes, toggle accounting, position accounting, and completion bits
  retain their existing order and semantics.
- The ISR performs no allocation, logging, formatting, transport, blocking
  operation, or additional floating-point calculation.
- X/Y, Z, homing, and pressure-regulator routing remain unchanged.
- Watchdog participants and deadlines remain unchanged.

### Host validation

Pure tests cover:

- the exact legacy acceleration/cruise/deceleration boundary classification;
- counter reset between moves;
- phase entry and maximum-cycle tracking;
- completed-pulse tracking;
- pending count and maximum consecutive streak;
- saturating counters rather than wraparound;
- one and multiple DWT counter wraps in move-duration calculation;
- disabled-gate compilation through the full firmware build comparison.

## Frozen Slice 2: Non-ISR Reporting

Slice 1 passed its host tests and both the enabled and disabled firmware build
comparisons. Slice 2 exposes the completed snapshots through the existing
self-test result mechanism. It adds selector `2029` and result IDs `2020`
through `2025`; it does not add or change any opcode, TLV, frame layout, or
normal status field.

### Qualification sequence

The operator-gated `motion_timing_v1` suite homes Z and then XY before entering
the existing X <= 45000, Y <= 35000 clear-motion envelope. It executes:

| Test ID | Vector | Start -> target | Effective longest-axis rate |
| --- | --- | --- | --- |
| 2020 | Low-rate equal XY safety probe | `(2000,2000) -> (7000,7000)` | 6 kHz |
| 2021 | X only | `(2000,2000) -> (12000,2000)` | 40 kHz |
| 2022 | Y only | `(12000,2000) -> (12000,12000)` | 40 kHz |
| 2023 | Equal XY diagonal | `(12000,12000) -> (22000,22000)` | 40 kHz |
| 2024 | Scaled camera-to-home ratio | `(8916,30500) -> (500,500)` | 40 kHz |
| 2025 | Short triangular X move | `(2000,2000) -> (3000,2000)` | 40 kHz |

The `2024` X:Y distance ratio is `8416:30000` (`0.28053`), matching the
incident move's `10850:38676` ratio (`0.28053`) while remaining inside the
established test envelope. Positioning moves are not timing samples. The 6 kHz
probe temporarily lowers both X/Y speed caps and restores their exact previous
values before any 40 kHz row. A motion timeout cancels X/Y and prevents later
maximum-rate rows from starting. The suite attempts an XY home again during
normal teardown; this teardown does not alter the already captured timing row.

### Compact result metrics

Formatting occurs after motion completes, outside every ISR. Each result
contains the commanded deltas/rate, timeout and endpoint state, maximum
observed status-watchdog age, maximum firmware-observed status period, status
frame count, maximum move duration/counter wraps across X/Y, per-axis ISR entry
and completed-pulse counts, per-axis update-pending observations, worst
acceleration/cruise/deceleration ISR cycles across the participating axes,
maximum pending streak, and combined saturation flags.

The emitted compact keys are:

`dx,dy,hz,to,ep,wd,sg,sn,du,wr,xn,xp,xo,yn,yp,yo,am,cm,dm,ps,sf`

Host tests require exact pulse/entry counts, validate pass/fail policy, and
prove the longest metrics string fits the existing result-frame budget without
truncation. DWT duration and ISR cycle metrics remain the primary timing
evidence because a severely starved RTOS tick can also delay the firmware time
base used by `wd` and `sg`. Host receive timestamps in the HIL report provide
the independent status-gap observation.

## Hardware Verification

The operator confirmed LC-001 was powered, stationary, clear throughout the
full motion envelope, and connected through the designated Pi at
`192.168.0.33`. The exact artifact was hashed on the Pi before each flash. The
accepted run used the final corrected binary described below.

### Reporting defect found by the first run

The first hardware attempt flashed binary SHA-256
`57553F32D5458239C8A1DE64A7E55EF0D5F3A7440A5476C6C2E23FCCF97A0ACB`.
SAFE passed 28/28, and all six motion rows completed with exact endpoints, no
timeout, no reset, and normal teardown homing. The normalized qualification
correctly failed 25 acceptance checks because the target newlib-nano formatter
does not support the `%llu` conversion used for `du`. It emitted `du=lu` and
did not consume the 64-bit vararg, shifting every later metric.

This was a reporting-only failure discovered by HIL. Duration is now converted
to decimal explicitly outside the ISR and passed to `snprintf` as a string.
The regression test covers both a multi-wrap value and the maximum `uint64_t`
value. The affected first-attempt evidence is retained locally under
`hil_reports/qualification/LC-001/20260811T185409Z/`; its raw and normalized
report SHA-256 values are respectively
`E04B4AB492DAAC6C362697838891237348D1FC91B858ED5F9F6D1FD3E421168B` and
`919AD69C35C2E0B2F6A18AF4018FB13D89221AFD8636EE4B43F4FB2C8FDA78BA`.

### Accepted SAFE and motion gates

The corrected binary passed the required gates:

| Gate | Result | Evidence |
| --- | --- | --- |
| SAFE after corrected flash | 28/28 passed; not aborted; normal GOODBYE ACK/DONE | `hil_reports/selftest_m1_safe_formatter_fix_20260811T1158.json`; SHA-256 `8651F9CCE212F33CD529C080B1C6505327C120B3C817EFC29316E09BEBF22D2B` |
| `motion_timing_v1` | 6/6 passed; not aborted; 0 analyzer blocks/warnings; no reset report; teardown home completed | `hil_reports/qualification/LC-001/20260811T185807Z/report.json`; SHA-256 `4990666AB60D81B8D50535FB34FFF0BE219779AC5583F2FBC9843FB6E0C89028` |
| Raw timing report | Run `4063260026`; exact pulse/entry invariants; no saturation or counter wrap | `hil_reports/qualification/LC-001/20260811T185807Z/raw_selftest.json`; SHA-256 `B58AF706B8034091C0AC2EC5D4868B70F475D77899088F6687327DB5CD8FCBD1` |
| CSV summary | Qualification return code 0 | `hil_reports/qualification/LC-001/20260811T185807Z/summary.csv`; SHA-256 `E3DE15BB75C3F3ADBCC62B0F31F9CD4F10D42F93BE051710D0C553AB21F3F30C` |

At the 180 MHz core clock, the accepted row measurements were:

| ID | Rate | X entries / pending | Y entries / pending | Accel / cruise / decel max | Move duration | Firmware status gap / watchdog age |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 2020 low equal XY | 6 kHz | 10,001 / 0 | 10,001 / 0 | 956 / 406 / 1,018 cycles | 919.753 ms | 64 / 64 ms |
| 2021 X only | 40 kHz | 20,001 / 0 | 0 / 0 | 973 / 389 / 1,018 cycles | 800.970 ms | 66 / 63 ms |
| 2022 Y only | 40 kHz | 0 / 0 | 20,001 / 0 | 916 / 332 / 961 cycles | 800.970 ms | 65 / 80 ms |
| 2023 equal XY | 40 kHz | 20,001 / 1,325 | 20,001 / 1,610 | 953 / 389 / 1,018 cycles | 854.184 ms | 73 / 67 ms |
| 2024 camera ratio | 40 kHz | 16,833 / 0 | 60,001 / 1,024 | 953 / 406 / 998 cycles | 1,322.751 ms | 67 / 66 ms |
| 2025 short X | 40 kHz | 2,001 / 0 | 0 / 0 | 953 / 389 / 1,018 cycles | 253.714 ms | 65 / 63 ms |

The independent host status observation saw a maximum 200 ms gap across 71
samples, with no transport timeout or reset report. All `sf` and `wr` values
were zero. Exact completed-pulse counts were half of the nonzero-axis entry
count rounded down, as designed.

### Interpretation

The evidence implicates both concurrency and ramp work:

- The 6 kHz equal-axis probe and both 40 kHz single-axis rows had zero pending
  observations. Equal 40 kHz XY produced 2,935 pending observations across
  40,002 entries (7.34%), with a maximum consecutive streak of eight. The
  camera-ratio row produced 1,024 pending observations on its long Y axis and
  none on X, with a maximum streak of six.
- Acceleration and deceleration maxima were about 2.4-2.9 times the cruise
  maxima. On the equal diagonal they were 5.294 and 5.656 microseconds versus
  2.161 microseconds in cruise. This strongly supports the per-interrupt ramp
  math as a major consumer of the margin that remains after two axes' raw
  interrupt streams overlap.
- At 40 kHz step rate, each axis requests about 80,000 toggle callbacks per
  second. Two equal axes therefore request about 160,000 callbacks per second.
  Applying the measured maxima as a conservative illustration gives roughly
  35% combined core occupancy at the cruise maximum and roughly 85-90% at the
  ramp maximum if that maximum cost occurred at the full event rate. Actual
  ramp occupancy is lower because the event rate is still changing and the
  reported values are maxima, not averages.
- The result is not explained by interrupt count alone: single-axis 40 kHz had
  no pending observations. It is also not explained by ramp math alone: the
  6 kHz equal-axis row had the same per-entry ramp maxima without pending
  observations. The high-rate overlap creates the load, and the roughly 2.5x
  ramp work consumes much of the remaining scheduling margin.

The phase cycle interval includes the fixed phase-classification and DWT read
overhead but excludes pending-flag sampling, state aggregation, and all result
formatting. Those excluded operations occur after the exit timestamp, and the
pending flag is sampled before aggregation. The compile-time-disabled build
still matches the clean legacy core footprint. The enabled HIL image completed
the required moves without reset, timeout, lost software pulses, status
deadline violation, or saturation.

### Operator path observation

The operator classified both required multi-axis rows as
`visible_s_or_bow`:

| Row | Classification | Phase observation |
| --- | --- | --- |
| 2023 equal XY diagonal | `visible_s_or_bow` | S-shaped deviation at the start and end during acceleration and deceleration; cruise appears straight |
| 2024 scaled camera-to-home ratio | `visible_s_or_bow` | S-shaped deviation at the start and end during acceleration and deceleration; cruise appears straight |

The operator reported the same behavior for all XY motion observed during the
suite. This matches the Milestone 0 legacy baseline and supports the conclusion
that instrumentation preserved the existing path behavior. It also reinforces
the timing result: the visible path error occurs in the phases whose ISR maxima
are roughly 2.5 times the cruise maximum.

### Files

- `firmware/Core/Inc/StepperInstrumentationReport.h` and
  `firmware/Core/Src/StepperInstrumentationReport.cpp`
- `firmware/Core/Inc/Comm.h` and `firmware/Core/Src/Comm.cpp`
- `firmware/Core/Src/Diagnostics.cpp`
- `firmware/tests_host/tests/test_stepper_instrumentation_report.cpp` and
  `firmware/tests_host/CMakeLists.txt`
- `tools/run_selftest.py`, `tools/qualification/test_catalog.py`, and
  `tools/qualification/manifests/motion_timing_v1.json`
- `FreeRTOS-interface/QualificationSuites.py` and
  `FreeRTOS-interface/QualificationView.py`
- focused qualification manifest, suite, and selector tests under `tests/`
- the matching tracked `firmware/artifacts/LabCraft_firmware.bin`

## Validation And Rollback

Local validation command:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Final local validation:

| Check | Result |
| --- | --- |
| Firmware host tests | 279/279 tests; 1,115 checks; 0 ignored; 0 filtered |
| STM32 Debug build | Pass; 0 errors; 3 pre-existing C++17-extension warnings in `callbacks.cpp` |
| Enabled target footprint | text 343,336; data 13,128; BSS 80,232 bytes |
| Disabled core compile-gate footprint | text 335,304; data 13,128; BSS 79,824 bytes (matches the clean legacy footprint) |
| Final tracked binary size | 356,480 bytes |
| Final tracked binary SHA-256 | `E850806BA3743C59C75A9A70C321C58D89760EAF7D0438C302DA5F429A3BF7A6` |
| Focused qualification tests | 53 passed |
| Full Python regression | 4,502 passed; 135 skipped |

The first full Python run had one unrelated SIL imager control round-trip
failure after 4,501 passes. That test passed immediately in isolation, and the
complete suite then passed on rerun. No imager-control source was changed.

## Milestone 1 Closeout

Milestone 1 is `verified`:

- the local host/build gates and corrected SAFE HIL gate pass;
- `motion_timing_v1` passes all six rows without reset or abort;
- exact entry/pulse invariants, phase maxima, pending observations, move
  durations, status gaps, watchdog ages, and saturation state are recorded;
- enabled/disabled instrumentation boundaries and target footprints are
  recorded, and the measurement path does not feed back into motion control;
- operator observations confirm the instrumented motion retains the legacy
  acceleration/deceleration S shape and straight cruise behavior.

No coordinated motion or LUT implementation is active in this milestone.

Rollback is to revert the Milestone 1 instrumentation/reporting changes and
restore the matching prior tracked firmware binary. The preserved Milestone 0
binary remains the known legacy hardware rollback image.
