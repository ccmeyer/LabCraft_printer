# Coordinated XY Milestone 2 Fixed-Point LUT Record

Status: `verified`

## Purpose And Scope

Milestone 2 adds and qualifies a pure fixed-point normalized cosine profile.
It is deliberately not connected to motion. Normal XY still follows
`ABSOLUTE_XY -> Orchestrator -> Gantry -> independent Stepper timers`, and Z,
homing, direct-axis, and pressure-regulator movement are unchanged.

The only target entry point is an explicitly selected, non-motion SAFE
diagnostic:

`profile_lut_benchmark_v1 -> run_selftest.py --profile-lut-benchmark -> P3 selector 2039 -> DiagnosticsRunner -> NormalizedCosineProfile -> result 2030`

No opcode, frame, TLV layout, status field, parser format, GPIO path, pressure
path, valve path, or homing path changed.

## Starting State

| Field | Value |
| --- | --- |
| Branch | `feature/motor_movement_LUT` |
| Clean starting commit | `a045c7f6ccfc530f66ad8bdec794678002eccbdc` |
| Starting commit subject | `firmware: add legacy XY ISR timing instrumentation` |
| Preserved Milestone 1 rollback binary SHA-256 | `E850806BA3743C59C75A9A70C321C58D89760EAF7D0438C302DA5F429A3BF7A6` |
| Build configuration | STM32 Debug, repository default `-O0`; fixed-point ISR-callable functions use local GCC optimization attributes |
| Target | LC-001 through `labcraft@192.168.0.33` |

The tracked build output remains
`firmware/artifacts/LabCraft_firmware.bin`, as required for firmware history.
Generated CubeIDE environment-hash drift was removed after each build.

## Candidate Sweep And Selection

The planning sweep evaluated every combination of 64, 128, and 256 intervals
with Q15, Q16, and Q20 values against the existing
`StepperProfileMath::ease01(SCurveCosine, t)` and its exact float-to-integer
ARR conversion over the intended normal X/Y domain.

| Intervals | Q15 | Q16 | Q20 |
| --- | --- | --- | --- |
| 64 | Evaluated; reject | Evaluated; reject | Evaluated; reject |
| 128 | Evaluated; reject | Evaluated; reject | Evaluated; reject |
| 256 | Evaluated; reject | Evaluated; reject: insufficient error margin | Evaluated; select |

The decision-relevant measurements were:

| LUT intervals / format | Flash bytes | Maximum ARR error | RMS ARR error | Decision |
| --- | ---: | ---: | ---: | --- |
| 64 / Q20 | 260 | 8 ticks | 2.493 ticks | Reject |
| 128 / Q20 | 516 | 2 ticks | 0.716 ticks | Reject: RMS budget |
| 256 / Q15 | 514 | 3 ticks | 0.710 ticks | Reject: max and RMS budgets |
| 256 / Q20 | 1,028 | 1 tick | approximately 0.36 tick | Select |

The selected table has 257 values for 256 intervals. Offline generation used
`floor(cosine_value * 2^20 + 0.5)` and explicit midpoint mirroring, giving
exact endpoints `0` and `1,048,576` and exact symmetry.

## Pure Module

`NormalizedCosineProfile` provides `RampSpec`, `RampCursor`,
`PrepareStatus::{Ready, Immediate, InvalidBounds}`, `prepare()`,
`currentArr()`, `advance()`, and `atEndpoint()`.

Preparation clamps both endpoints to the supplied bounds and calculates the
Q0.32 quotient/remainder increment. Sample `k` therefore represents exactly
`floor(k * 2^32 / intervalCount)`. The top eight phase bits select a LUT
interval and the next sixteen bits interpolate within it. A 64-bit
intermediate protects full-width ARR multiplication.

The cursor caches the current ARR. `currentArr()` is an inlined single read,
and `advance()` computes the next cached sample. This removes duplicate state
checks and ARR work while retaining these contracts:

- the first positive-interval sample is exactly the clamped source;
- exactly `intervalCount` advances reach the clamped destination;
- zero intervals return `Immediate` at the destination;
- invalid bounds return `InvalidBounds` and ARR zero;
- endpoint advancement is idempotent and returns false;
- reversed endpoints use the same implementation for deceleration;
- intermediate values remain monotonic and bounded;
- ISR-callable work has no floating point, cosine, allocation, or division.

Host tests cover interval counts `0, 1, 2, 3, 10, 258, 1000, 11430, 60000`,
forward/reverse ramps, deterministic output, triangular and cruise-capable
assembly, timer bounds, 3-40 kHz normal X/Y rates, five-times-start ARR,
zero-distance/one-axis preparation, and full-width `uint32_t` arithmetic.

## Target Instruction Audit

The final Debug disassembly was inspected after the accepted build:

- `currentArr()` is inlined as one `LDR` at its use site;
- `advance()` contains integer loads/stores, addition/subtraction,
  comparisons, branches, shifts, `MUL`, and `UMULL` only;
- neither path contains a branch-and-link, `UDIV`, `SDIV`, an `__aeabi`
  helper, a math-library call, or a floating-point instruction;
- division remains confined to `prepare()`, outside the timed sample loop.

## Permanent SAFE Diagnostic

Result `2030 profile_lut_cycle_benchmark_safe` is category `performance`,
profile `SAFE`, policy `explicit_selection`. Selector `2039` is emitted only
by `--profile-lut-benchmark`; ordinary SAFE remains unchanged.

The diagnostic prepares outside timed evaluation and measures 258-, 1,000-,
and 11,430-interval forward and reverse ramps. Each DWT measurement saves
PRIMASK, disables interrupts for one bounded call, restores the saved value,
and verifies restoration. It retains deterministic volatile checksums and
checks the orchestrator watchdog before and after the benchmark. It does not
obtain or access Stepper, Gantry, GPIO, pressure, valve, or homing objects.

The first target build exposed that globally unoptimized Debug functions made
the new path slower than its intended ISR compilation context. Function-local
optimization reduced the raw maximum from 526 to 208 cycles. A subsequent
target run showed only 2.70x speedup because `currentArr()` recomputed a value
that `advance()` could prepare once. Caching the current sample removed that
duplicate work. The fixed acceptance thresholds were not relaxed.

## Accepted Build And Hardware Evidence

| Field | Value |
| --- | --- |
| Tracked binary | `firmware/artifacts/LabCraft_firmware.bin` |
| Binary length | 353,320 bytes |
| Binary SHA-256 | `A51F8DD56B107BC6A4C00E54EB864A59E450DEC75F837300D501FC78DAEB32F1` |
| Pi hash before flash | Exact match |
| Ordinary SAFE raw report | `hil_reports/selftest_m2_safe_final.json` |
| Ordinary SAFE raw SHA-256 | `BCFA05E724B562F9141C80D9EB1F683DCF3EFAF7B27AE087E37FCC3210C2E50B` |
| Ordinary SAFE result | Run `4066258513`; 28/28 pass; not aborted; no reset report |
| Benchmark raw report | `hil_reports/selftest_m2_profile_lut_final.json` |
| Benchmark raw SHA-256 | `A5340BEF6098D82F06B038A94940187323C6E853C0024D10207A4BACBA4116BC` |
| Normalized report | `hil_reports/qualification/LC-001/20260811T194835Z/report.json` |
| Normalized report SHA-256 | `44BAA1DE5970ADDEF3F058611BBB88263BDB662D9A2A4F4FB8A12A9B5267A7F8` |
| Qualification CSV SHA-256 | `595DFF8E8A010CAF378E3F6C8A1A3A1B68E17C0AF913ADE1EC8F334E4FBA6167` |
| Qualification verdict | Pass; 0 blocks; 0 warnings |

Accepted result `2030` metrics at 180 MHz:

| Metric | Result | Gate |
| --- | ---: | ---: |
| `samples` | 25,376 | 25,376 |
| `lut_max` | 145 cycles | <= 225 |
| `lut_mean` | 135 cycles | informational |
| `legacy_max` | 594 cycles | informational |
| `legacy_mean` | 464 cycles | informational |
| `speedup_x100` | 439 (4.39x) | >= 400 |
| `prep_short` | 978 cycles | <= 1,800 |
| `prep_long` | 898 cycles | <= 1,800 |
| `err_max` | 1 ARR tick | <= 2 |
| `irq_restore` | 1 | exactly 1 |
| `checksum` | 2,386,608,165 | deterministic/informational |

Both reports completed with normal GOODBYE ACK/DONE. There was no reset,
abort, watchdog failure, motion, pressure change, or valve actuation. Motion
qualification and operator straightness observation were intentionally not
run because no motion path uses this module.

## Validation

The required firmware gate passed:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

The full firmware command passed with 285/285 host tests and 1,807,614 checks,
followed by a successful Debug target build with 0 errors and the three
existing warnings. Two final host-only assembly/zero-axis tests were then
added and `run_fw_unit_tests.ps1` passed 287/287 tests and 1,833,012 checks;
no target source or binary changed after the accepted build and HIL run.

The focused selector, manifest, catalog, analyzer, and dynamic suite tests
passed 67/67. The final full Python suite passed 4,506 tests with 135 skips and
440 existing warnings in 289.64 seconds.

## Risks, Proceed Gate, And Rollback

The LUT remains unused by motion, so Milestone 2 introduces no physical path
change. The target performance and error gates pass, allowing Milestone 3 to
begin with a pure coordinated X/Y planner. Milestone 3 must still prove DDA
geometry, exact pulse counts, axis scaling, short/zero-axis behavior, and
overflow bounds before any timer or GPIO integration.

Rollback is one milestone commit. Remove the unused module, tests, selector,
manifest, documentation, and matching binary, then restore the Milestone 1
artifact with SHA-256
`E850806BA3743C59C75A9A70C321C58D89760EAF7D0438C302DA5F429A3BF7A6`.
