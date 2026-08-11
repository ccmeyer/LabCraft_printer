# Coordinated XY Milestone 0 Baseline

Status: `verified`

Date: 2026-08-11

This record preserves the unchanged legacy XY engine and reset-incident
evidence before trajectory instrumentation or behavior changes begin. No
production firmware, protocol, MVC, motion, homing, Z, or pressure behavior is
changed by this milestone.

## Call Path And Scope

Normal XY requests use:

`View/location/calibration request -> Controller.set_absolute_XY -> Machine_FreeRTOS ABSOLUTE_XY -> Orchestrator CMD_ABS_XY -> Gantry::moveTo -> Gantry::moveBy -> independent Stepper X TIM2 and Y TIM7 ISRs`

The host sends `p3=30000`, but the current `Gantry::moveBy()` does not use that
argument. It chooses the longest axis's configured maximum and proportionally
scales the shorter axis. The initial A/B comparison therefore preserves the
legacy effective maximum of `40000 steps/s`; correcting the ignored request is
a separate change.

## Source And Binary Identity

| Item | Baseline identity |
| --- | --- |
| Working branch | `feature/motor_movement_LUT` |
| Branch HEAD when baseline preparation began | `83b6dcaa7103a9012903338450f32048125678e9` |
| Branch state | Clean before Milestone 0 documentation edits |
| Pi repository | `b66855d75466994023dba658c548baa91f6a0261`, branch `feature/balance_integration`, clean |
| Firmware artifact source commit | `c8cb3375fd2ca9127116c62cae5ca415327bc7f4` |
| Firmware tree object at artifact commit and branch HEAD | `e63673cad58427194376c3c5c2d88147465a8de4` |
| Firmware tree comparison | No changes from artifact commit through branch HEAD |
| Binary | `firmware/artifacts/LabCraft_firmware.bin` |
| Binary size | 348448 bytes |
| Binary SHA-256 | `FF653995F66BDB9667859028BDB8EA220A4C2D386C3ED06C8C385F31E8211CDA` |
| Preserved ignored rollback copy | `hil_reports/baselines/coordinated_xy_m0_20260811/LabCraft_firmware_legacy_ff653995.bin` |
| Git blob | `f9dbabe454ff910970c2685f7c168e2051ed82f1` |
| Firmware-reported build epoch | `Jul 14 2026 20:12:06` |
| Target | `STM32F446ZETx` |
| Preserved build configuration | `Debug`; C/C++ optimization option is unset in `.cproject` (CubeIDE Debug default/no optimization selection) |

The local and Pi binary hashes match. The firmware-reported build epoch is one
minute before the artifact source commit, and that commit introduced the exact
tracked binary. Because the firmware tree has not changed since that commit,
the preserved binary is the legacy implementation being characterized. The
compiler executable/version is not embedded in the raw `.bin` and cannot be
recovered from the retained artifact.

## Machine And Motion Configuration

| Item | Baseline value |
| --- | --- |
| HIL host | `labcraft` at `192.168.0.33` |
| Machine ID | `LC-001` |
| Machine UUID | `29e9ecec-9fed-48e4-be7d-69d8e40bdea7` |
| Serial transport | `/dev/ttyAMA0`, 115200 baud |
| X maximum | `40000 steps/s` |
| Y maximum | `40000 steps/s` |
| X acceleration | `140000 steps/s^2` |
| Y acceleration | `140000 steps/s^2` |
| Profile | Per-axis cosine S-curve, calculated in each timer ISR |
| Driver microstep register | TMC2208 `MRES=2`, or 1/64 microstepping |
| Edge mode | `DEDGE=1` (STEP activity on both edges) |
| Current selection | `I_SCALE_ANALOG=1`; current is set by hardware VREF, not a firmware current register |

No numeric VREF/current measurement is available in software. Reproducibility
therefore depends on retaining LC-001's existing driver adjustment and noting
any physical VREF change before later A/B runs.

## Reset Incident Baseline

The source evidence is retained under `logs/reset_bundles_260810_0739/`:

| Artifact | SHA-256 |
| --- | --- |
| `LabCraft_connection_lost_debug_bundle_20260811_021524_mcu_unresponsive_20260811T021046Z-e6d989f5.zip` | `26445E7DF2B691FD95CB0443913784D071CBDBAABDEBC75589EBD14F8DDC6ED1` |
| `LabCraft_reset_debug_bundle_20260811_021533_software_2147483648.zip` | `23B0044513C6A5868AF1089DF825F9F37110043A00317A1D8BA432AA4733E968` |

The host application source recorded by both bundles is
`6494bb57550dcbf4398606707fa5e2eac50f9590`. Its core motion sources have the
same behavior as the baseline above.

The failing sequence completed `ABSOLUTE_Z` to `Z=500`, then began command 51,
`ABSOLUTE_XY(500, 500, 30000)`. The final stationary sample before XY execution
was `(X=11350, Y=39176, Z=500)`, giving planned distances of `10850` X steps and
`38676` Y steps. The legacy proportional rate calculation therefore requested
approximately `11221 steps/s` on X and `40000 steps/s` on Y despite the host's
`30000` argument.

The last complete in-motion position sample was `(7648, 34155, 500)` at about
`2026-08-11T02:15:11.702Z`. The last status of any chunk arrived at about
`02:15:11.765Z`, while command 51 remained in `abs_xy_wait_x`. The host declared
the MCU unresponsive at `02:15:14.394Z` after 2629 ms without a valid frame.
The retained board report then classified a software reset with sticky
watchdog state. It did not attribute a specific late task, so ISR starvation is
the leading timing-based explanation rather than a uniquely proven fault site.

## Validation Evidence

### Non-motion SAFE gate

The unchanged installed binary passed all 28 SAFE rows on LC-001 on
2026-08-11. Important results were:

- 28 passed, 0 failed, not aborted;
- build identity `Jul 14 2026 20:12:06`;
- status cadence average 64 ms, maximum jitter 14 ms;
- watchdog enabled with 4000 ms timeout and no late task;
- minimum heap 11152 bytes and minimum reported task stack headroom 177 words;
- motion, pressure, valve, and abort FULL rows correctly reported as not
  executed under the SAFE gate.

Raw report locations:

- Pi: `hil_reports/baselines/coordinated_xy_m0_20260811/selftest_safe.json`
- Local ignored copy: `hil_reports/baselines/coordinated_xy_m0_20260811/selftest_safe.json`
- Report SHA-256: `1D781E6E36CDDDE8DBE9C2DC7A19159578E3027DC8DF2204DFEE9D4FE195017E`

### Local toolchain check

`firmware/scripts/run_fw_checks.ps1 -Config Debug` was attempted and stopped
before tests because `cmake` is not installed on this workstation. A separate
headless build probe stopped because STM32CubeIDE is not installed at the
configured path. The Pi also has no CMake, Arm GCC, or CubeIDE. This is not a
Milestone 0 rebuild failure: no firmware was edited or rebuilt, and the
source-identical retained binary is the artifact under test. A toolchain must
be installed or supplied before Milestone 1 firmware changes can pass the
mandatory local gate.

### Operator-gated motion evidence

The operator confirmed the full XY envelope, the raster-start Z volume, the
evaporation-plate setup, and operator presence before motion began.

| Suite | Rows | Automated result | Straightness observation |
| --- | --- | --- | --- |
| `xy_motion_v1` | 2010, 2011 | Pass; 2/2 rows, not aborted, no reset | `visible_s_or_bow` for multi-axis XY behavior |
| `motion_envelope_v1` | 2012-2016 | Pass; 5/5 rows, not aborted, no reset | `visible_s_or_bow` for row 2013 diagonals |
| Camera-to-home-ratio behavior | Normal `ABSOLUTE_XY` path | Qualitative legacy observation; incident reset evidence recorded separately | `visible_s_or_bow` |

`xy_motion_v1` run `4057319219` completed in about 60.6 seconds:

| Row | Repetitions/moves | Span and drift (steps) | Return/timeouts/safety |
| --- | --- | --- | --- |
| 2010 long travel | 3 repetitions, 5 points | X span 1, Y span 15; X drift 1, Y drift 13 | X/Y return 0, return error 0, no move/home timeout, guard, or bound violation |
| 2011 raster | 2 repetitions, 194 moves | X span 14, Y span 22; X drift 14, Y drift 27 | X/Y return 0, return error 0, no move/home timeout, guard, or bound violation |

The normalized result passes. Row 2011 retains one non-blocking candidate
warning: Y drift was 27 steps against the provisional 25-step threshold.

The first `motion_envelope_v1` launch completed rows 2012 and 2013, then stopped
safely at `evap_plate_confirm` because the piped response was consumed by the
parent qualification prompt and did not reach the child self-test process. It
recorded an operator-declined abort, not a reset or motion failure. That raw
attempt is retained as procedural evidence and is not the accepted baseline.

The controlled direct rerun `4057453651` reached the approved prompt correctly
and completed all five rows in about 174.9 seconds:

| Row | Repetitions/moves | Span and drift (steps) | Return/timeouts/safety |
| --- | --- | --- | --- |
| 2012 reverse travel | 3 repetitions, 5 points | X span 0, Y span 17; X drift 1, Y drift 30 | X/Y return 0, return error 0, no move/home timeout, guard, or bound violation |
| 2013 diagonal | 3 repetitions, 5 points | X span 0, Y span 17; X drift 0, Y drift 15 | X/Y return 0, return error 0, no move/home timeout, guard, or bound violation |
| 2014 384 raster | 1 repetition, 387 moves; Z=91500 | X/Y span 0; X drift 0, Y drift 13 | X/Y return 0, return error 0, no move/Z-home timeout, guard, or bound violation |
| 2015 Z long travel | 3 repetitions; Z=80000 | Z span 1, drift 1 | Z return 0, return error 0, no XY/move/home timeout, guard, or bound violation |
| 2016 triggered-limit home | XYZ, 200-step offset | X/Y/Z span 0; drift 3/16/1 | No move/home timeout; no bad limit-start state |

The normalized result passes. Row 2012 retains one non-blocking candidate
warning: Y drift was 30 steps against the provisional 25-step threshold.

Accepted raw and normalized evidence:

| Evidence | SHA-256 |
| --- | --- |
| `qualification/LC-001/20260811T171907Z/raw_selftest.json` | `A0C76C24F4BED206F38BA25973FE8624FDA7B128B6DB3232C8303DA90920CF64` |
| `qualification/LC-001/20260811T171907Z/report.json` | `F49152367F2E74C63D9D2CC7D7DD2B9598B59A8948FA57CB2D21326B595360AB` |
| `motion_envelope_completed_raw.json` | `0DED96A4B83B53EBE39CE198A6113DCDBDDD0669736CBFAB6A6E58CC1EC752B7` |
| `qualification/LC-001/20260811T172423Z/report.json` | `EF39891964013C67C715519C482BD952ECF5D619740C30B8330B8B1DB9CEF851` |
| Procedural abort `qualification/LC-001/20260811T172016Z/raw_selftest.json` | `CD6047DC73A67FD0C8C7B039AB2BD20533CBF02F5830D7FE8ECB4CB8D02D8666` |

All paths above are relative to the ignored local/remote baseline root
`hil_reports/baselines/coordinated_xy_m0_20260811/`.

The operator classified all observed multi-axis XY movement, including the
required diagonal and camera-to-home-ratio behavior, as `visible_s_or_bow`.
The deviation is visible during acceleration and deceleration. Once both axes
reach their maximum planned rates, the cruise segment appears straight. This
phase-specific result matches the independent per-axis ramp explanation and is
the qualitative legacy baseline the coordinated trajectory must improve.

The visible S shape is an accepted baseline defect, not a passing straightness
target for the new executor. Candidate qualification warnings are also retained
rather than hidden: row 2011 Y drift was 27 steps and row 2012 Y drift was 30
steps against the provisional 25-step threshold. Later qualification must show
no lost-step/return regression and should eliminate the visible acceleration
and deceleration curvature without lowering the approved 40 kHz maximum.

## Milestone 0 Closeout

Milestone 0 proceed criteria are satisfied:

- exact source tree, binary, build configuration, machine, driver mode, speed,
  acceleration, and incident identities are recorded;
- the ignored 30 kHz request remains explicitly separate from this work;
- SAFE passed 28/28;
- `xy_motion_v1` passed 2/2 with its candidate warning retained;
- `motion_envelope_v1` passed 5/5 with its candidate warning retained;
- accepted runs were not aborted and reported no reset, timeout, return error,
  guard violation, or bounds violation;
- physical clearance and operator presence were confirmed;
- the legacy S-shaped acceleration/deceleration path is recorded using the
  standardized observation vocabulary.

No production behavior changed. Milestone 1 must not begin until the missing
Windows build/test prerequisites are installed, the CppUTest submodule is
initialized, and the unmodified baseline passes
`firmware/scripts/run_fw_checks.ps1 -Config Debug`.

## Risks And Rollback

- The raw binary cannot identify the historical compiler version; the binary
  hash, source-identical firmware tree, build epoch, and configuration are the
  retained comparison identity.
- Analog motor current is machine-local and unmeasured. Do not adjust driver
  VREF between baseline and candidate qualification without recording it.
- Stop the speed/motion sequence after any reset, unexpected sound/heat,
  collision risk, timeout, or lost-step failure. Preserve the report and reset
  evidence rather than repeating a failing move.
- Milestone 0 changes documentation and ignored evidence only. Rollback is to
  revert the documentation edits; no runtime rollback is necessary. The known
  legacy binary is retained in Git and as the ignored rollback copy above; both
  identities use the recorded SHA-256.
