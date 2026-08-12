# Coordinated XY Trajectory Implementation Plan

> Working execution plan for replacing independent X/Y acceleration and pulse
> generation with a shared, fixed-point coordinated XY trajectory.
>
> This document is a plan and decision record. It does not authorize combining
> Z with XY, changing pressure-regulator behavior, weakening watchdog coverage,
> or changing the device protocol.

## Document Status

| Field | Value |
| --- | --- |
| Status | `in_progress` |
| Created | 2026-08-11 |
| Working branch | `feature/motor_movement_LUT` |
| Current source baseline | `c8cb3375fd2ca9127116c62cae5ca415327bc7f4` firmware artifact source; firmware tree unchanged through branch HEAD |
| Reset incident source | `6494bb57550dcbf4398606707fa5e2eac50f9590` |
| Incident evidence | `logs/reset_bundles_260810_0739/` |
| Designated HIL Pi | `192.168.0.33` |
| Tracked firmware artifact policy | Every firmware milestone commit includes its matching `firmware/artifacts/LabCraft_firmware.bin` |
| Runtime behavior changed by this document | Yes - the Milestone 5 candidate is verified at 3 kHz; production-speed qualification remains Milestone 6 |

The core motion sources are unchanged between the reset-incident source and
the source baseline recorded above. Milestone 0 replaced the original planning
baseline with the exact retained firmware artifact source, build identity, and
HIL evidence recorded in `docs/coordinated_xy_milestone0_baseline.md`.

## Purpose

The current normal XY path starts independent X and Y timer-driven Stepper
moves. Each axis calculates its own acceleration and deceleration profile and
performs floating-point profile work, including cosine, from its timer ISR.
This has two related consequences:

1. At high combined X/Y rates, the two timer ISRs can consume enough CPU time
   to starve the RTOS tick, status reporting, watchdog supervisor, and other
   tasks.
2. During acceleration and deceleration, X and Y do not maintain a constant
   step-rate ratio. A commanded diagonal can therefore follow an S-shaped path
   even when its endpoints are correct.

The target design will:

- plan one shared XY path profile before motion starts;
- use a normalized fixed-point acceleration lookup table instead of runtime
  cosine and floating-point division;
- use a master XY step clock plus DDA/Bresenham accumulation to distribute X
  and Y steps;
- update the profile once per complete master step, not independently on both
  axes and both STEP edges;
- preserve exact final X and Y step counts;
- leave Z, homing, direct single-axis commands, and P/R pressure regulation on
  their existing motion paths for the initial implementation;
- retain the independent watchdog as an acceptance guard, not work around it;
- preserve the existing command protocol.

## Primary Call Paths

### Current normal XY path

`View/location/calibration request -> Controller.set_absolute_XY -> Machine_FreeRTOS ABSOLUTE_XY -> Orchestrator CMD_ABS_XY -> Gantry::moveTo -> Gantry::moveBy -> Stepper X TIM2 ISR + Stepper Y TIM7 ISR`

The host currently queues `ABSOLUTE_XY` with `p3=30000`, but
`Gantry::moveBy()` ignores `feedHz` and selects the longest axis's configured
maximum, normally `40000 steps/s`. Milestones must not accidentally compare a
40 kHz legacy move with a slower coordinated move and attribute the difference
to the motion algorithm.

### Proposed normal XY path

`View/location/calibration request -> Controller.set_absolute_XY -> Machine_FreeRTOS ABSOLUTE_XY -> Orchestrator CMD_ABS_XY -> Gantry::moveCoordinatedXY -> prepared shared XY trajectory -> one master timer ISR -> fixed-point LUT phase + DDA X/Y pulse mask`

### Paths intentionally kept separate

- `CMD_MOVE_X`, `CMD_MOVE_Y`, `CMD_ABS_X`, and `CMD_ABS_Y` continue to use the
  existing single-axis Stepper path initially.
- `CMD_MOVE_Z` and `CMD_ABS_Z` remain single-axis and are never joined to the XY
  trajectory.
- `CMD_HOME_XY` continues to use the independent X and Y homing tasks and
  limit-aware Stepper homing implementation.
- P/R pressure control continues to select direction and rate from live
  pressure error and continues to support `setSpeedHz()`.
- P/R homing, syringe reset, and vacuum preparation remain on their existing
  paths.

## Scope

### In scope

- A fixed-point normalized profile LUT suitable for ISR use.
- A pure coordinated XY planner with explicit speed and acceleration limits.
- DDA/Bresenham distribution for every sign combination, axis ratio, and a
  zero-distance axis.
- A shared XY pulse executor for normal Gantry position moves.
- Timer ownership, position accounting, completion signaling, cancellation,
  and unexpected-limit behavior for the shared executor.
- Cycle, overrun, scheduling, and move-duration instrumentation.
- Host tests, firmware build checks, staged HIL, existing motion qualification,
  and camera-to-home regression coverage.
- Documentation of actual feed semantics and module ownership.

### Out of scope for the initial implementation

- Coordinated XYZ movement.
- Changing pressure-control algorithms or P/R rate behavior.
- Replacing homing with the coordinated executor.
- Changing opcodes, command payloads, status schemas, or framing.
- Changing motor driver GPIO assignments or CubeMX `.ioc` configuration.
- Raising watchdog deadlines or disabling watchdog participants to make motion
  pass.
- Immediately migrating every direct single-axis command to the LUT.
- Mechanical calibration, belt alignment, motor-current tuning, or microstep
  configuration changes unless separate evidence identifies one of those as a
  prerequisite.

## Target Architecture

### Shared path geometry

For a move with absolute step distances `Nx` and `Ny`:

```text
masterSteps = max(Nx, Ny)
```

Each complete master step advances an error accumulator for every participating
axis. An axis emits a STEP pulse when its accumulator crosses
`masterSteps`. The executor must emit exactly `Nx` X pulses and `Ny` Y pulses,
with commanded cross-track error bounded to approximately one motor step.

The shared master speed and acceleration must be limited so that every axis's
scaled instantaneous speed and acceleration remain within that axis's caps.
The path planner must not assume that X and Y have equal limits.

### Normalized profile LUT

The LUT stores only the dimensionless easing curve from `0` to `1`. A move
provides:

- starting timer period;
- target timer period;
- acceleration master-step count;
- deceleration master-step count;
- fixed-point phase increment.

The executor maps LUT output into that move's timer-period range using bounded
integer arithmetic. Milestone 2 selected 256 intervals (257 points) in Q20
after comparing 64-, 128-, and 256-interval Q15/Q16/Q20 candidates against
the legacy ARR sequence.

### Pulse edges

- DDA and profile phase advance once per complete master step.
- The rising edge records which axes stepped.
- The falling edge reuses that step mask so every asserted STEP output receives
  a valid pulse width.
- The profile is not recomputed on the falling edge.
- Completion leaves every STEP pin in its defined idle state.

The preferred first implementation uses one existing XY timer as the master
without changing pin mapping or `.ioc` configuration. The exact timer-routing
design must be reviewed in Milestone 4 before generated files are edited.

### Runtime ownership

Only one owner may control X/Y pulse generation at a time:

- legacy single-axis Stepper;
- independent homing tasks; or
- coordinated Gantry executor.

Starting a conflicting mode must fail safely before enabling motion. The
Orchestrator normally serializes commands, but the firmware must enforce this
invariant rather than relying only on queue behavior.

## Safety And Compatibility Invariants

Every milestone that touches motion must preserve these invariants:

1. No motion begins until direction, enable state, counters, target positions,
   DDA state, timer period, and both STEP outputs are prepared.
2. X and Y final software positions change only when their corresponding full
   STEP pulse completes.
3. Successful completion emits exactly the commanded X and Y step counts and
   sets both existing completion bits.
4. A zero-distance axis emits no pulses but still reaches a completed state.
5. Cancel, shutdown, or unexpected limit assertion stops the shared trajectory
   and leaves both axes in a deterministic state. A single axis must not
   continue a nominal coordinated path after the other axis aborts.
6. Homing retains its current limit-triggered behavior and does not enter the
   coordinated executor.
7. Pressure regulators retain dynamic rate control and are not given a frozen
   position schedule.
8. Z cannot be accepted as part of a coordinated XY trajectory.
9. Minimum STEP high and low times remain within driver requirements at every
   requested rate.
10. Timer ISR code performs no logging, allocation, blocking calls, cosine,
    floating-point division, or unbounded loops.
11. Watchdog check-in requirements and deadlines are unchanged.
12. Normal status reporting continues during maximum-rate motion.
13. The command protocol and host command queue behavior remain compatible.
14. A failed plan or busy-mode check results in no motion, not a partial move.

## Status Legend

| Status | Meaning |
| --- | --- |
| `not_started` | Work has not begun |
| `planned` | Slice scope and gates are documented |
| `in_progress` | Files are being changed |
| `implemented` | Code is complete and focused automated checks pass |
| `verified` | Required HIL and regression evidence pass |
| `blocked` | A documented prerequisite or decision prevents safe progress |
| `deferred` | Intentionally postponed and not required by this plan |

## Milestone Summary

| Milestone | Status | Outcome | Gate before continuing |
| --- | --- | --- | --- |
| 0. Baseline and decisions | `verified` | Reproducible legacy source/build, reset, motion, and straightness evidence recorded | Baseline source/build/HIL artifacts complete |
| 1. Behavior-preserving instrumentation | `verified` | Legacy timing, pending-interrupt, reset, pulse, status, and straightness evidence recorded | Milestone 1 evidence complete |
| 2. Fixed-point normalized LUT | `verified` | Unrouted 257-point Q20 profile and explicit non-motion target benchmark pass | Error and cycle budgets accepted |
| 3. Pure coordinated XY planner | `verified` | DDA path and exact pulse counts proven on host | Exhaustive geometry tests pass |
| 4. Shared XY executor behind a gate | `verified` | Gated TIM2 executor passes 3 kHz loaded integration without normal routing | Build, SAFE, low-rate motion, pause/cancel/limit, and qualified visual gates pass |
| 5. Route normal Gantry XY motion | `verified` | Route-enabled candidate passes SAFE, loaded 3 kHz normal-route, M4 regression, physical-limit, and pressure gates | Milestone 5 evidence complete; production-speed use remains blocked on Milestone 6 |
| 6. Performance and motion HIL qualification | `implemented` | The velocity-domain correction reduced the calculated peak from 443,900 to about 131,100 steps/s2 and passed one guarded 40 kHz row with X=4/Y=1 drift; a diagnostic-only one-interrupt-per-step executor is implemented to test a structurally larger deadline margin | Run and review the SAFE-bracketed selector `2075` diagnostic; FULL remains blocked |
| 7. Default enablement and closeout | `not_started` | Legacy fallback decision, docs, and completion record finalized | Full firmware and HIL gates pass |

## Next Planned Action

Stage 1 is complete at source/artifact commit `b777f993`. Its physical selector
`2077` run covered all 440,000 callbacks without pending observations, but the
row failed its post-row X reference with `xd=54`. Review then identified an
independent trajectory defect: the configured `140000 steps/s^2` selected only
the old ramp distance, while applying the cosine to timer period produced an
approximately `443900 steps/s^2` smooth-envelope peak at 40 kHz.

The verified correction candidate applies the cosine to velocity squared,
maps that curve back into the same fixed-point ARR LUT, and sizes the ramp with
a conservative `7/8 * v^2/a` bound. At 40 kHz it uses 10,000 acceleration
steps and has a calculated smooth peak of approximately `131100 steps/s^2`.
The shortest 20,000-step qualification legs still reach the exact target ARR,
so selector `2077` remained a real 40 kHz test. The required automated gates,
pre-SAFE 28/28, single guarded selector `2077`, and post-SAFE 28/28 all passed.
The physical reference error improved from X=54/Y=3 to X=4/Y=1, with all three
focused results passing. Entry lateness remained measurable (`cm=507`,
`dm=968`) without a pending observation. The retained historical run already
proves that pending updates can occur intermittently, and the user explicitly
prioritized eliminating rare movement-related failures. That reliability goal
authorizes the controlled Stage 2 comparison without requiring another
critical-section-only failure first.

The status-synchronization experiment showed that removing the status-metric
critical section alone does not address the more fundamental fragility of a
two-edge executor at the maximum rate. The next candidate therefore adds
diagnostic selector `2075` while leaving boot and normal operation unchanged.
It programs one full-period TIM2 interval per master step, emits a complete
STEP-high/STEP-low pulse in that one ISR with a DWT-enforced 2 us minimum, and
commits exactly one planner event. The same 40 kHz row consequently expects
220,000 callbacks instead of 440,000 while preserving the planner LUT,
approximately 131,100 steps/s2 acceleration peak, geometry, DDA masks, limits,
status traffic, and watchdog behavior.

Result `2074` adds pulse and post-handler deadline evidence. The required HIL
gate is complete 220,000-callback/pulse/deadline coverage, no missing or missed
deadline samples, no pending update, at least 360 core cycles of enforced pulse
high time, at least 500 timer ticks of remaining full-period slack, exact
motion evidence, clean bounded homes, passing status cadence, and no reset or
watchdog evidence. A scope guard restores the two-edge executor on every exit.
The next action is one watched SAFE-bracketed selector `2075` run followed by
normalization with `coordinated_xy_single_irq_v1`. Do not promote this mode or
resume FULL qualification until that evidence is reviewed.

## Milestone 0: Baseline And Decisions

Status: `verified`

Evidence record: `docs/coordinated_xy_milestone0_baseline.md`

### Goal

Record evidence from the unchanged motion engine so later results are directly
comparable and resolve decisions that would otherwise confound the comparison.

### Required work

- Record the exact Git SHA, firmware build configuration, compiler optimization
  level, binary hash, machine identity, motor-current/microstep configuration,
  and active X/Y speed/acceleration settings.
- Preserve the reset-bundle analysis and identify the camera-to-home start,
  target, actual effective rates, and last status time.
- Run the existing operator-gated motion suites on the legacy engine:
  - `xy_motion_v1` (`2010`, `2011`);
  - `motion_envelope_v1` (`2012` through `2016`), with primary comparison focus
    on `2012`, `2013`, and `2014`.
- Record report paths, raw metrics, aborted/reset state, and observed diagonal
  path behavior.
- If it is safe to reproduce, run a bounded camera-session-to-home sequence.
  Do not repeatedly provoke watchdog resets merely to enlarge the sample.
- Record physical straightness as a standardized operator observation because
  no logic analyzer or suitable camera-tracking setup is available. For each
  required diagonal, record `appears_straight`, `visible_s_or_bow`, or
  `uncertain`, and note whether any visible deviation occurs mainly during
  acceleration, cruise, or deceleration.
- Record the existing working-tree state before every implementation milestone.

### Feed-rate decision

For the initial algorithm comparison, preserve the legacy effective `40 kHz`
maximum. Do not simultaneously fix ignored `feedHz` semantics. The ignored host
`30000` request will be addressed as a separate follow-up change after this
coordinated-motion work, so its behavior and evidence are not conflated with
the trajectory-engine comparison.

### Likely files

- `docs/coordinated_xy_trajectory_plan.md`
- optional baseline summary under `docs/`
- HIL artifacts under `hil_reports/` according to existing artifact policy

### Validation

- No production code change in this milestone.
- If firmware is rebuilt for baseline identity, run:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

- Run the applicable operator-gated qualification manifests using the existing
  qualification workflow and preserve the raw and normalized reports.

### Proceed criteria

- Source, binary, machine, and effective-rate identities are recorded.
- Existing lost-step/return metrics are recorded, including known warnings.
- The feed-rate comparison policy is explicit.
- Operator straightness observations are recorded for the legacy diagonal and
  camera-to-home-ratio moves.
- Required motion envelope and fixture clearance are confirmed.

### Rollback

Documentation and evidence only; no runtime rollback is required.

## Milestone 1: Behavior-Preserving Instrumentation

Status: `verified`

Evidence record: `docs/coordinated_xy_milestone1_instrumentation.md`

### Goal

Measure the legacy ISR and scheduling behavior without changing its pulse
sequence or motion profile.

### Required work

- Add DWT cycle-counter measurement around the timer handler and/or
  `_stepTick()` with separate acceleration, cruise, and deceleration maxima.
- Count X and Y timer entries, continuously pending/overrun observations, and
  completed STEP pulses.
- Measure move start/end time and maximum status/watchdog task age observed
  during the move using non-ISR reporting.
- Store counters in fixed-size state. Never format or transmit logs from the
  timer ISR.
- Report measurements after motion using an existing diagnostic/result
  mechanism. Adding a permanent diagnostic ID requires registry/catalog review
  and must not alter normal command framing.
- Add a compile-time gate so instrumentation can be disabled if measurement
  overhead is not negligible.

### Likely files

- `firmware/Core/Src/Stepper.cpp`
- `firmware/Core/Inc/Stepper.h`
- `firmware/Core/Src/Diagnostics.cpp`
- a small pure instrumentation-summary helper if needed
- `firmware/tests_host/tests/` for pure counter/summary policy tests
- diagnostic catalog/qualification files only if a permanent test is added

### Validation

- Golden comparison showing the same commanded ARR sequence and pulse counts
  with instrumentation enabled and disabled.
- Host unit tests for counter reset, maximum tracking, and overflow handling.
- Local firmware checks.
- Low-rate HIL comparison before maximum-rate measurement.
- Legacy maximum-rate measurements for:
  - X only;
  - Y only;
  - equal X/Y diagonal;
  - camera-to-home ratio;
  - short triangular move.

### Proceed criteria

- Instrumentation overhead is quantified and does not materially alter the ISR
  timing being measured.
- Pulse counts and move results match the baseline.
- Legacy worst-case cycles, overrun observations, move duration, status gap, and
  reset behavior are recorded.

### Rollback

- Disable or revert instrumentation only. No motion-algorithm change exists yet.

## Milestone 2: Fixed-Point Normalized LUT

Status: `verified`

Evidence record: `docs/coordinated_xy_milestone2_lut.md`

Post-Milestone-6 correction: the original compatibility LUT applied its cosine
directly to ARR. That preserved the legacy timer sequence but did not preserve
the configured velocity-domain acceleration bound. The correction milestone
retains the 257-point Q20 fixed-cost ISR interface while transforming a cosine
in velocity squared back into timer period and using its proven acceleration
coefficient to size the ramp.

### Goal

Provide a pure, bounded-cost profile calculation that reproduces the accepted
legacy cosine/ARR trajectory closely enough without runtime cosine, floating
point, or division in the ISR.

### Required work

- Introduce a small pure profile module compiled by host tests.
- Generate or embed a normalized cosine LUT as constant flash data.
- Evaluate candidate LUT sizes and fixed-point formats.
- Use a phase accumulator or other bounded integer mapping so runtime cost does
  not grow with move length.
- Define exact rounding, saturation, endpoint, and phase-completion behavior.
- Preserve the distinction between timer-period interpolation and velocity
  interpolation. Initial compatibility tests compare against the current ARR
  behavior; any change to velocity-domain shaping requires a separate decision.
- Reuse the acceleration ramp in reverse for normal deceleration.

### Implemented files

- `firmware/Core/Inc/NormalizedCosineProfile.h`
- `firmware/Core/Src/NormalizedCosineProfile.cpp`
- `firmware/tests_host/tests/test_normalized_cosine_profile.cpp`
- `firmware/tests_host/CMakeLists.txt`
- explicit SAFE result `2030`, selector `2039`, host selector, catalog,
  manifest, analyzer, and discovery coverage

### Automated tests

- LUT endpoints are exactly `0` and full scale.
- LUT is monotonic and symmetric within defined rounding.
- Interpolated ARR never exceeds timer or minimum-pulse bounds.
- Maximum and RMS ARR error versus the current cosine implementation are
  reported across representative and boundary ranges.
- Long, short/triangular, zero-distance, and one-step plans are deterministic.
- No multiplication or phase arithmetic can overflow at supported limits.
- The module has no HAL or FreeRTOS dependency.

### Proceed criteria

- Approximation error budget is reviewed and recorded.
- Host tests pass for the selected LUT resolution and fixed-point format.
- Measured target-MCU cycle cost is comfortably below the agreed ISR budget.
- No normal motion path uses the new module yet.

### Rollback

- Revert the Milestone 2 commit and restore the Milestone 1 tracked binary with
  SHA-256
  `E850806BA3743C59C75A9A70C321C58D89760EAF7D0438C302DA5F429A3BF7A6`.

## Milestone 3: Pure Coordinated XY Planner

Status: `verified`

Evidence record: `docs/coordinated_xy_milestone3_planner.md`

### Goal

Prove coordinated geometry, speed/acceleration scaling, and pulse distribution
without HAL, timers, GPIO, or real hardware.

### Required work

- Define a `CoordinatedXyPlan` containing signed directions, absolute distances,
  master steps, target rate, ramp lengths, timer bounds, and DDA increments.
- Calculate the master speed and acceleration limit from every participating
  axis's limits.
- Generate a deterministic per-master-step axis mask through DDA/Bresenham
  accumulation.
- Specify one-axis-zero behavior without falling back to undefined state.
- Specify completion and error results for impossible, overflowed, busy, or
  out-of-range plans.
- Add a host-only event-trace simulator combining LUT timing with DDA masks.

### Automated tests

- Exact pulse counts for X and Y.
- All four direction combinations.
- `Nx=0`, `Ny=0`, `Nx=Ny`, `Nx=1`, `Ny=1`, and highly asymmetric ratios.
- Camera-to-home and reverse camera-to-home geometry.
- Representative envelope-corner and 384-well raster deltas.
- Commanded path error stays within the documented one-step bound.
- Reverse paths produce matching counts and bounded reverse traces.
- Short triangular and long cruise plans finish on the correct LUT endpoint.
- Speed and acceleration scaling never exceeds either axis's caps.
- Maximum supported step counts do not overflow accumulators.
- Deterministic output across repeated runs.

### Implemented files

- `firmware/Core/Inc/CoordinatedXyPlanner.h`
- `firmware/Core/Src/CoordinatedXyPlanner.cpp`
- `firmware/tests_host/tests/test_coordinated_xy_planner.cpp`
- `firmware/tests_host/CMakeLists.txt`

### Proceed criteria

- All geometry tests pass.
- A reviewed trace demonstrates a straight commanded camera-to-home path.
- Exact endpoint counts do not depend on floating-point behavior.
- HAL/RTOS integration has not begun.

### Rollback

- Revert pure planner additions without affecting existing runtime motion.

## Milestone 4: Shared XY Executor Behind A Gate

Status: `verified`

Loaded verification status: `passed_3khz_gate`

Evidence record: `docs/coordinated_xy_milestone4_executor.md`

### Goal

Integrate the proven planner with timer and GPIO execution while keeping normal
production routing on the legacy path until bench safety behavior is verified.

### Preferred integration shape

- `Gantry` owns coordinated move state.
- One existing XY timer acts as the master during coordinated mode.
- The other XY step timer remains stopped during that move.
- `Stepper` exposes narrow ISR-safe hooks for direction/enable preparation,
  STEP edge emission, position accounting, target accounting, and completion.
- Direct Stepper and homing behavior remain intact outside coordinated mode.
- A build-time gate selects legacy versus coordinated normal routing for A/B
  qualification and immediate rollback.

### Required work

- Implement prepare/arm/start phases so neither axis starts while the other is
  still being prepared.
- Route the selected timer callback to exactly one owner.
- Advance the LUT and DDA only on complete master steps.
- Preserve minimum pulse width and deterministic idle pin state.
- Set both legacy completion bits at shared completion.
- Add safe stop/cancel that terminates the timer and both axis states.
- Route unexpected normal-move X or Y limit assertion to abort the complete
  coordinated move.
- Reject conflicting single-axis, homing, or coordinated ownership before any
  GPIO or timer change.
- Keep generated-file edits inside `USER CODE` blocks.

### Likely files

- `firmware/Core/Inc/Gantry.h`
- `firmware/Core/Src/Gantry.cpp`
- `firmware/Core/Inc/Stepper.h`
- `firmware/Core/Src/Stepper.cpp`
- `firmware/Core/Src/main.c` only if existing user callback routing is used
- pure host-testable ownership/completion policy helper and tests

### Implemented shape

- `CoordinatedXyExecutor` owns the pure two-edge state machine and priority
  rules for pause, cancel, and X/Y limit requests.
- `Gantry` owns plan preparation, both-axis reservation, TIM2 master dispatch,
  TIM7 exclusion, hardware cleanup, completion bits, and diagnostic snapshots.
- `Stepper` exposes Gantry-only pin/position/target hooks and rejects direct or
  homing starts while coordinated reservations exist.
- `LC_COORDINATED_XY_EXECUTOR_ENABLE=1` compiles the diagnostic path while
  `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0` keeps ordinary motion legacy.
- Explicit FULL selector `2049` and manifest `coordinated_xy_executor_v1`
  contain the seven 3 kHz loaded qualification results.

### Validation

- Host tests for ownership, completion, abort, and limit policy.
- Local firmware checks and headless link/map review.
- Stack and static RAM delta recorded; no motion-path dynamic allocation.
- Low-rate bench test with motors disabled or mechanically isolated where
  practical.
- Verify pulse count, edge-state sequencing, calculated high/low time, shared
  start, shared completion, and pin idle state through host traces, internal
  counters, and static timer calculations. External pin capture is optional if
  suitable equipment becomes available later; it is not a required gate.
- Verify legacy path remains selectable and unchanged.

### Proceed criteria

- No timer ownership conflict is possible in tested state transitions.
- Cancel and unexpected limit stop both axes.
- Position and target telemetry agree with emitted complete pulses.
- Low-rate bench evidence passes before loaded movement.
- Legacy routing remains the default.

### Rollback

- Disable the coordinated build gate or revert this milestone commit. The legacy
  executor remains available.

## Milestone 5: Route Normal Gantry XY Motion

Status: `verified`

Evidence record: `docs/coordinated_xy_milestone5_normal_route.md`

### Goal

Route normal `Gantry::moveTo/moveBy` XY position moves through the coordinated
executor while leaving all named out-of-scope paths unchanged.

### Required work

- Route `CMD_ABS_XY` and direct diagnostic calls to `Gantry::moveTo()` through
  coordinated mode.
- If `dz != 0` reaches `Gantry::moveBy`, reject or retain an explicitly separate
  legacy behavior; do not silently add coordinated Z.
- Preserve the Orchestrator's large-move pressure-regulator motion hold and
  watchdog participation policy.
- Preserve existing completion waits or replace them with an equivalent shared
  completion policy that cannot return after only one axis completes.
- Confirm target-position and status reporting during and after the move.
- Confirm application disconnect/shutdown/cancel paths stop coordinated motion.
- Confirm direct X/Y commands, Z, X/Y/Z homing, P/R control, and P/R homing still
  select their legacy paths.
- Keep the A/B build gate available through Milestone 6.

### Implemented shape

- `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=1` is the tracked candidate default;
  `-DLC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0` compiles the legacy A/B path.
- `Gantry::moveTo()` returns the real coordinated startup result and passes a
  requested rate of zero, preserving the ignored command feed field and the
  configured 40 kHz cap. XY-only `moveBy()` is coordinated; Z-only remains
  legacy; combined XY+Z is rejected before state changes.
- Orchestrator uses one shared completion wait and validates the terminal
  reason, positions, and targets. Rejection, limit, planner, and endpoint
  failures pause the transport without retiring the command; successful CLEAR
  or GOODBYE cleanup releases the latch.
- Both EXTI forwarding and direct raw-switch sampling protect coordinated
  motion. The raw check occurs before `onTimerUpdate()`, so no new rising edge
  follows an asserted sample.
- Explicit selector `2059` and manifest `normal_xy_route_v1` provide the 3 kHz
  loaded integration, bounded physical-limit, status, control, and legacy-path
  qualification. Pressure remains a separate fixture and suite.

### Likely files

- `firmware/Core/Src/Gantry.cpp`
- `firmware/Core/Inc/Gantry.h`
- `firmware/Core/Src/Orchestrator.cpp`
- `firmware/Core/Src/Stepper.cpp` and `.h`
- focused host policy tests
- no Python or protocol file unless an unexpected compatibility defect is found

### Automated validation

- Full host firmware unit tests.
- Headless Debug build.
- Static assertions or build checks for LUT size and accumulator widths.
- Tests showing unchanged dispatch for direct X/Y, Z, homing, and P/R modes.
- Tests showing both done bits and final targets for XY including one zero axis.
- Tests for rejected busy/conflicting ownership.

### Initial loaded HIL sequence

Use a clear, controlled motion envelope and begin below production speed:

1. short X-only through `ABSOLUTE_XY`;
2. short Y-only through `ABSOLUTE_XY`;
3. short equal diagonal;
4. short asymmetric diagonal;
5. cancel at low speed;
6. controlled unexpected-limit test only through an existing safe fixture;
7. normal X/Y homing after coordinated moves;
8. pressure-control smoke test after coordinated moves.

### Proceed criteria

- Every initial HIL result matches planned pulse counts and endpoints.
- Status frames continue throughout motion.
- No reset, watchdog late task, timer overrun, or stuck completion occurs.
- Homing, Z, and P/R regression smoke tests pass.

### Rollback

- Select the legacy build gate and re-run the same HIL sequence.
- Revert normal routing while retaining pure LUT/DDA tests if integration is the
  failing layer.

## Milestone 6: Performance And Motion HIL Qualification

Status: `implemented`

### Goal

Demonstrate that coordinated motion improves ISR/scheduler headroom and path
coordination without reducing accepted motion performance or introducing lost
steps.

### Speed ladder

Run each representative geometry at safe increasing master rates. Exact rates
are confirmed in Milestone 0, with the expected ladder:

```text
5 kHz -> 10 kHz -> 20 kHz -> 30 kHz -> 40 kHz
```

Do not advance after a reset, overrun, unexpected noise/heat, lost-step failure,
or safety-envelope violation. Inspect evidence and correct the defect first.

### Geometry matrix

- X only and Y only through coordinated `ABSOLUTE_XY`.
- Equal diagonal in both directions.
- 1:2, 1:4, 4:1, and camera-to-home ratios.
- Short 1000-step triangular move.
- Long envelope travel with cruise.
- Reverse travel.
- Plate-like short raster transitions.
- Camera-session stop followed by home movement.

### Evidence required

- Exact planned/emitted X and Y pulse counts.
- Command-space cross-track error bound from host trace tests.
- Host edge-state traces and static timing checks for STEP high/low time,
  shared start, and pin-idle behavior.
- Standardized operator straightness observations for representative diagonals
  and the camera-to-home ratio. Physical in-flight straightness is explicitly a
  qualitative result because no logic analyzer or suitable camera/fiducial
  tracking setup is available.
- Maximum and average ISR cycles by phase.
- Timer overrun/pending count.
- Move duration and comparison with planned duration.
- Maximum status-task gap and watchdog-task health.
- Reset/crash report state.
- Existing HIL return-error and lost-step metrics.

### Acceptance gates

Final numeric thresholds are frozen after Milestone 0/1 baseline evidence, but
the following are hard qualitative requirements:

- zero timer overruns at the accepted production maximum;
- zero watchdog resets or watchdog starvation records;
- continuous status reporting with margin below the 500 ms status deadline;
- ISR worst-case cost leaves explicit margin before the next master interrupt;
- exact software pulse counts and final target positions;
- no regression beyond existing accepted HIL thresholds for return error,
  drift, timeout, bounds, or cable guard;
- diagonal command-space error remains within the DDA bound;
- the operator reports no visible S curve or bow on the required diagonal runs;
  any `uncertain` observation must be repeated or explicitly left unverified;
- no reduction in accepted maximum rate unless separately approved and
  documented.

### Existing qualification runs

- `xy_motion_v1`: `2010`, `2011`.
- `motion_envelope_v1`: `2012`, `2013`, `2014`, plus unchanged Z/home regression
  rows `2015`, `2016`.
- `coordinated_xy_camera_transition_v1`: cold 40 kHz camera-ratio round trip
  followed immediately by bounded legacy X home passed on 2026-08-12. This
  isolates the vector and executor-to-home transition from the preceding speed
  tiers and favors an accumulated-workload cause for the full-suite failure.
- `coordinated_xy_40khz_v1`: selector `2077` runs the existing result `2064`
  geometry row plus results `2072` and `2073`, with bounded post-row X/Y homes
  and without the lower-rate
  tiers, focused X-direction gate, raster, camera-repeat, or pressure workload.
  Its first run failed closed on one pending TIM2 update during the forward 1:4
  leg. After adding result `2072`, a refined run reproduced 16 pending updates
  during the equal-diagonal reverse and stopped before the 1:4 pair. All
  240,000 callbacks had complete outer samples. The non-terminal full software
  IRQ maximum was 1,909 cycles and the pending-correlated full path was 1,816
  cycles, both below the 2,250-cycle edge interval. This moves the remaining
  latency outside the measured C handler, toward pre-entry interrupt masking or
  equal-priority service delay. Pre/post SAFE passed with no reset evidence.
  The Stage 1 candidate adds first-hook counter-at-entry and inter-entry
  schedule-lateness evidence without changing motion; its HIL gate is pending.
- Applicable pressure-regulator and homing smoke/qualification lanes because
  the shared Stepper integration was touched even though P/R behavior is out of
  scope.
- Full firmware HIL gate:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

### Proceed criteria

- A/B reports identify source and binary hashes and use the same machine setup.
- Every speed and geometry row has an accepted result or a documented reason it
  is not required.
- Existing motion qualification reports pass without hiding warnings.
- Camera-to-home no longer causes connection loss/reset in the accepted repeat
  count.
- A bounded incremental-workload diagnostic identifies and clears the
  history-dependent X displacement seen after the full 40 kHz geometry row;
  the full suite remains blocked until then.
- Host pulse-trace evidence proves the DDA path bound, and the operator reports
  that the required physical diagonal moves appear straight.

### Rollback

- Restore the legacy routing gate and validated legacy binary.
- Do not raise watchdog deadlines, suppress reset reporting, or lower speed
  silently to convert a failure into a pass.

## Milestone 7: Default Enablement And Closeout

Status: `not_started`

### Goal

Make the qualified coordinated XY path the supported normal behavior, update
ownership documentation, and preserve a clear rollback story.

### Required work

- Decide whether the temporary legacy build gate is removed, retained as a
  diagnostic-only option, or retained for one release as rollback protection.
- Record the ignored `feedHz` behavior as a separate follow-up item; do not fold
  that behavior change into this milestone.
- Remove dead experimental code and instrumentation that is not part of ongoing
  diagnostics.
- Keep useful low-overhead timing/overrun counters if they provide operational
  safety evidence.
- Update `firmware/docs/repo_map.md` for the new trajectory/planner ownership.
- Update firmware README material if build, diagnostic, or qualification
  commands changed.
- Create a completion record containing file list, test commands/results,
  HIL report paths, remaining risks, and rollback binary/source identity.

### Required final validation

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

Also run the operator-gated XY and motion-envelope qualification manifests and
the camera-session-to-home regression sequence.

### Definition of done

- Normal `ABSOLUTE_XY` uses one shared fixed-point coordinated trajectory.
- No cosine, floating-point division, allocation, logging, or unbounded work
  remains in the coordinated timer ISR.
- X/Y pulse counts and command-space path bounds are proven by host tests.
- Maximum-rate cycle, overrun, task-gap, and watchdog evidence pass.
- Existing motion, homing, Z, and pressure regression gates pass.
- HIL reports and build/source hashes are preserved.
- Protocol behavior is unchanged.
- Rollback is documented and tested by selecting or flashing the known legacy
  path/binary.

## Validation Command Matrix

Before editing firmware in any milestone, read `firmware/AGENTS.md` and list the
files and at-most-eight-step slice plan.

### Fast host iteration

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_unit_tests.ps1 -Config Debug
```

### Required local firmware gate

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
```

If the combined script is unavailable, run both the firmware host tests and
headless build scripts documented in `firmware/AGENTS.md`.

### Required hardware gate

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.33 -Profile FULL
```

Motion-envelope and qualification fixtures must be explicitly confirmed by the
operator. SAFE self-test alone is not sufficient for a motion-engine change.

## Evidence And Artifact Requirements

Every HIL artifact used for a proceed decision must record or be accompanied by:

- Git SHA and dirty-tree status;
- firmware binary SHA-256;
- build configuration and optimization;
- machine ID and relevant motor configuration;
- selected legacy/coordinated gate state;
- commanded and effective rate/acceleration;
- pattern, direction, distance, and repetition count;
- raw self-test report path;
- normalized qualification report path when applicable;
- ISR/timer/task metrics when available;
- reset report or an explicit statement that none occurred;
- operator observations, including path curvature, noise, heat, or vibration.

Suggested baseline directory naming:

```text
hil_reports/baselines/coordinated_xy_m0_<YYYYMMDD>/
```

Follow repository artifact policy; if raw reports are not committed, commit a
summary containing hashes and durable report locations.

## Risk Register

| Risk | Mitigation | Detection | Rollback |
| --- | --- | --- | --- |
| Wrong DDA rounding loses/adds a step | Pure exact-count tests and wide accumulators | Host trace and pulse counters | Revert pure planner milestone |
| X/Y path still curves | One shared master phase and DDA | Host cross-track proof plus standardized operator observation | Restore legacy and inspect planner/executor boundary |
| Timer ownership conflict | Explicit exclusive mode state | State-transition tests and busy rejection | Disable coordinated routing |
| STEP high/low time violation | Rising/falling state machine, timer bounds, and explicit cycle margin | Host edge-state/static timing tests plus target ISR-cycle measurements; external capture if equipment later becomes available | Lower test rate, revert executor; do not accept |
| ISR remains too expensive | Fixed-point bounded work and cycle instrumentation | DWT cycles and overrun counter | Revert routing and optimize before retry |
| Limit stops only one axis | Shared abort policy | Safe fixture test | Disable coordinated routing |
| Software position diverges from pulses | Update only on completed axis pulse | Host trace, internal emitted-pulse counters, and post-home error | Revert executor |
| Feed-rate change confounds comparison | Freeze effective legacy rate for A/B | Artifact metadata | Repeat comparison at matched rates |
| Pressure or homing behavior regresses | Separate modes plus regression HIL | Pressure/home suites | Revert shared Stepper hooks |
| Dynamic allocation or RAM growth reduces safety margin | Static storage and link-map review | Build/map and RTOS headroom diagnostic | Reduce/remove storage, revert milestone |
| Mechanical lost steps at new timing distribution | Speed ladder and existing return tests | HIL post-home drift/return metrics | Stop at last passing speed and investigate |
| Watchdog reset is masked | Deadlines unchanged | Reset report and task-gap metrics | Reject change; never weaken watchdog gate |

## Rollback Strategy

- One milestone per commit.
- Keep pure planning/math changes separate from HAL/timer integration.
- Keep timer integration separate from normal command routing.
- Retain a build-time legacy route through A/B qualification.
- Preserve the known-good legacy firmware binary and SHA before loaded HIL.
- After any unexpected reset or motion behavior, stop the speed ladder, capture
  reset/black-box evidence, restore the last passing binary, and inspect before
  continuing.
- Do not use `git reset --hard`, delete HIL evidence, or overwrite the known-good
  firmware artifact during rollback.

## Decision Record And Remaining Decisions

Clarifications recorded on 2026-08-11:

| Decision | Status | Resolution |
| --- | --- | --- |
| Working branch | Resolved | Use `feature/motor_movement_LUT` for the planned code changes. |
| Initial feed behavior | Resolved | Preserve the current effective `40 kHz` rate for matched A/B testing. Address the ignored host `30000` request separately. |
| Straightness evidence | Resolved | Use quantitative host DDA/path proofs plus standardized operator observation. No logic analyzer or suitable camera-tracking setup is available. |
| HIL target | Resolved | Use the printer/Pi at `192.168.0.33`. |
| Direct single-axis LUT migration | Deferred | Leave direct X/Y/Z, homing, and P/R paths unchanged during coordinated XY implementation; consider normal single-axis migration only after this plan is accepted. |

One decision intentionally remains open until qualification evidence exists:

| Decision | Recommended default | Resolve by |
| --- | --- | --- |
| Legacy fallback lifetime | Keep through HIL qualification; decide removal or diagnostic-only retention after acceptance | Milestone 7 |
