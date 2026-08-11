# Coordinated XY Milestone 3: Pure Planner Evidence

## Status And Baseline

Milestone 3 is verified. The local firmware, full Python regression, and
ordinary target SAFE HIL gates pass.

| Field | Value |
| --- | --- |
| Branch | `feature/motor_movement_LUT` |
| Starting commit | `005f57a1af97be1e61118da650ed0bc6d54784e6` |
| Starting worktree | Clean |
| Accepted Milestone 2 binary SHA-256 | `A51F8DD56B107BC6A4C00E54EB864A59E450DEC75F837300D501FC78DAEB32F1` |
| Milestone 3 Debug binary SHA-256 | `3661EFC3FC106528BE7F836C3C0C12803E6E5447767482E763C623412D9A4105` |
| Milestone 3 Debug binary length | 353,320 bytes |

The production call path remains:

`ABSOLUTE_XY -> Orchestrator -> Gantry -> independent X/Y Stepper timers`

`CoordinatedXyPlanner` has no runtime caller. No timer, GPIO, Stepper, Gantry,
Orchestrator, diagnostic, command, protocol, Z, homing, or pressure behavior
changed in this milestone. The existing ignored feed-rate request also remains
separate; normal XY still uses the legacy effective 40 kHz maximum.

## Implemented Contract

`CoordinatedXyPlanner` is a pure C++ module that prepares a shared master-step
trajectory and exposes one cached event at a time. A future executor can use
the same event for the STEP rising and falling edges, then call
`completeCurrentStep()` after the falling edge. The module itself never accesses
hardware or changes positions.

Preparation performs the integer division and integer square root needed to:

- convert signed deltas to bounded absolute distances and directions;
- choose `max(xSteps, ySteps)` as the master-step count;
- derive master speed and acceleration caps from every participating axis;
- apply generic timer/minimum-pulse limits;
- choose cruise-capable or triangular ramp lengths;
- prepare forward and reversed Milestone 2 cosine ramps.

The per-step path uses centered-error DDA. Each participating accumulator starts
at `floor(masterSteps / 2)`, adds its axis distance once per master event, emits
on `>= masterSteps`, and subtracts the threshold. Per-step work uses bounded
integer addition, subtraction, comparison, LUT access, shifts, and
multiplication. It contains no division, floating point, allocation, HAL, or
FreeRTOS dependency.

For every completed prefix, tests enforce the integer invariant:

`abs(emittedAxis * masterSteps - completedMaster * axisSteps) <= floor(masterSteps / 2)`

This proves exact endpoint counts and limits minor-axis displacement error to at
most half a step, stricter than the milestone's one-step gate.

## Profile Evidence

The normal 90 MHz timer, 40 kHz cap, 140,000 steps/s2 cases produce:

| Move | Master rate | Accelerate | Cruise | Decelerate | Target ARR | Start ARR |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 30,000 master steps | 40,000 Hz | 5,715 | 18,570 | 5,715 | 1,124 | 5,620 |
| 1,000 master steps | 11,832 Hz triangular peak | 500 | 0 | 500 | 3,802 | 19,010 |

One-, two-, and three-step moves have explicit triangular phase joins. A
one-step move has no artificial ramp intervals and emits its single event at
the attainable triangular peak. Acceleration reaches the exact target ARR
before cruise/deceleration; the completed reversed cursor reaches the exact
start ARR.

## Camera Path Review

The table records completed master events, emitted pulse magnitudes, and the
minor-axis error numerator. Directions are negative for the actual return; the
same masks and ARR sequence are proven for the positive/reverse form.

### Bounded qualification camera return `(-8416, -30000)`

| Completed master events | X pulses | Y pulses | X error numerator | X error in steps |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 1 | 8,416 | 0.2805 |
| 7,500 | 2,104 | 7,500 | 0 | 0 |
| 15,000 | 4,208 | 15,000 | 0 | 0 |
| 22,500 | 6,312 | 22,500 | 0 | 0 |
| 30,000 | 8,416 | 30,000 | 0 | 0 |

The maximum X error numerator across all 30,000 events is 14,992, or 0.4997
step. Final counts are exact.

### Original camera ratio `(-10850, -38676)`

| Completed master events | X pulses | Y pulses | X error numerator | X error in steps |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 0 | 1 | 10,850 | 0.2805 |
| 9,669 | 2,713 | 9,669 | 19,338 | 0.5000 |
| 19,338 | 5,425 | 19,338 | 0 | 0 |
| 29,007 | 8,138 | 29,007 | 19,338 | 0.5000 |
| 38,676 | 10,850 | 38,676 | 0 | 0 |

The maximum X error numerator is exactly 19,338, or one-half step. Final counts
are exact.

## Host Coverage And Target Build

The host suite covers:

- every X/Y magnitude pair from 0 through 64, with the path invariant checked
  after every event;
- all direction combinations, stationary axes, equal axes, one-step axes, and
  highly asymmetric ratios;
- both camera vectors and their reverse traces;
- every nonzero move in the existing 8x12/400-step qualification raster;
- all 383 nonzero moves in the existing 384-well serpentine path and its return;
- long/cruise, short/triangular, and one-/two-/three-step profiles;
- unequal axis speed/acceleration caps using exact cross-multiplied bounds;
- 90 MHz operation from 3-40 kHz and 32-/16-bit timer bounds;
- invalid limits, unrepresentable slow rates, excessive magnitudes,
  `INT64_MIN`, cursor busy/reuse, and invalid state transitions;
- full-width `uint32_t` plans, 64-bit accumulator bounds, and deterministic
  repeated event traces.

The focused and complete firmware command passed:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

Result: 299/299 host tests, 6,284,665 checks, and a successful Debug target
build with zero errors and the three pre-existing C++17-extension warnings.
The target build compiled `Core/Src/CoordinatedXyPlanner.cpp`; object inspection
confirmed no divide or floating-point instruction/helper in `nextMask()`,
`primeEvent()`, or `completeCurrentStep()`. Preparation retains the expected
division helpers outside the per-step path.

The full Python regression also passed:

```powershell
.\env\Scripts\python.exe -m pytest -q
```

Result: 4,506 passed, 135 skipped, and 440 existing warnings in 266.24 seconds.

## HIL Evidence

The accepted binary was uploaded to `192.168.0.33`; its Pi SHA-256 exactly
matched the local tracked artifact before flash. The standard Windows HIL
wrapper completed its local gate but stalled before upload because its SSH call
does not accept the repository's identity file and attempted interactive
authentication. No upload or flash had occurred at that point. The stalled
local processes were stopped, and the wrapper's upload, Pi flash/SAFE runner,
and report-download steps were then executed unchanged with the dedicated
`pi_sil_codex_network_ed25519` key.

| Field | Result |
| --- | --- |
| Binary SHA-256, local and Pi | `3661EFC3FC106528BE7F836C3C0C12803E6E5447767482E763C623412D9A4105` |
| Raw report | `hil_reports/selftest_m3_safe_20260811T203725Z.json` |
| Raw report SHA-256 | `C314D5F10CA8CE7F57CB5AC788A5EA40257FDFCE6E11F06D6AD114C30E960983` |
| Run/profile | `4069312361` / `SAFE` |
| Result | 28/28 pass; 0 failed; not aborted |
| Session close | GOODBYE ACK and GOODBYE DONE received |
| Reset state | `reset_report` empty; no reset observed |
| Watchdog | `1042 watchdog_supervisor_safe` passed |
| Motion gates | `executed=0; motion=0; gate=safe_only` |
| Pressure gates | `executed=0; pressure=0; gate=safe_only` |
| Valve gate | `executed=0; valves=0; gate=safe_only` |

There was no reset, abort, watchdog failure, motion, pressure change, or valve
actuation. No motion qualification or operator straightness observation was
required because the module remains unrouted.

## Risk, Proceed Gate, And Rollback

The planner cannot cause motion in Milestone 3 because no runtime code calls it.
All Milestone 3 proceed gates pass, so concrete planning for the gated
timer/GPIO executor in Milestone 4 may begin. Hardware integration must not
begin without that reviewed plan.

Rollback is one milestone commit: remove the unused planner, tests, and
documentation, then restore the Milestone 2 binary with SHA-256
`A51F8DD56B107BC6A4C00E54EB864A59E450DEC75F837300D501FC78DAEB32F1`.
