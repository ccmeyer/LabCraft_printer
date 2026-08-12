# Coordinated XY Trajectory Milestone 5: Normal Route

Status: `verified` at the Milestone 5 3 kHz integration scope.

## Baseline

- Branch: `feature/motor_movement_LUT`
- Starting commit: `4c1de0a3ea8c61d8d1275f7000fa15dab4a9a382`
- Accepted Milestone 4 binary SHA-256:
  `75F96CC8043509438AF8CC46342E1417A26269321F6B002D5DCB3823B7B1038D`
- Starting worktree: clean
- Candidate route: `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=1`
- A/B rollback route: compile with
  `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0`

The tracked Milestone 5 image is a qualification candidate. It is not approved
for production-speed use until Milestone 6 completes the 5--40 kHz speed ladder
and watchdog/starvation qualification.

## Fixed Contract

Normal `ABSOLUTE_XY` commands and direct `Gantry::moveTo()` calls use the shared
TIM2 coordinated executor. The command feed field remains ignored and a zero
requested rate selects the existing X/Y component-rate caps. Direct X/Y, Z,
homing, and pressure-regulator motion remain legacy-routed. `moveBy()` rejects
combined XY and Z displacement without starting any axis.

Coordinated start rejection must never synthesize completion. Normal command
retirement requires a completed coordinated terminal state and exact X/Y
position and target agreement. Unexpected start, limit, planner, or endpoint
failures pause the transport and remain unretired until a successful clear or
shutdown recovery.

The EXTI limit route remains active. The TIM2 edge handler also samples both raw
X/Y inputs before allowing a new rising edge, providing a bounded fallback when
the physical input is asserted during coordinated ownership.

No opcode, frame, TLV, status payload, or host application API changes are part
of this milestone.

## Safety Procedure

The explicit FULL diagnostic must fail closed unless the operator confirms the
motion envelope, manually proves X pressed/released and Y pressed/released with
the motors disabled, and allows low-rate Z then sequential X/Y homing. Normal
route tests temporarily cap X/Y at 3 kHz.

The physical-limit test starts each axis at the normal 100-step post-home
backoff and commands only to -100 steps. X and Y are tested separately. Any
aggressive contact, travel beyond the 200-step crossing window, abnormal sound,
reset, or missing limit termination stops the run and blocks a retry pending
review.

Pressure qualification uses the separate approved closed-loop fixture after
the motion fixture is removed.

## Local Evidence

| Evidence | Result |
| --- | --- |
| Firmware host checks and Debug build | PASS — 319/319 host tests, 7,416,303 checks; clean Debug link |
| Python regression | PASS — 4,536 passed, 135 skipped |
| Route-disabled A/B compile | PASS — host gate target plus ARM syntax builds of `Gantry.cpp` and `Orchestrator.cpp` with `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0` |
| Route-enabled binary SHA-256 / length | `F1F6D4871B1B6FE277FA108A25F128280339DDE79910D786438BE26ABD2FEAD1` / 391,000 bytes |
| Link size | text 377,856; data 13,128; bss 80,632 bytes |
| Delta from accepted Milestone 4 | +1,248 binary/text bytes; +0 data; +16 bss bytes |
| Stack review | coordinated hardware ISR 56 bytes; pure executor edge 24 bytes; normal ABS_XY operation 288 bytes; route diagnostic lambda 2,632 bytes; outer diagnostics frame 7,968 bytes within the 20,480-byte Orchestrator stack |
| Per-edge disassembly | PASS — no `UDIV`, `SDIV`, floating helpers/instructions, cosine, allocation, or exception calls in `Gantry::_handleCoordinatedTimerFromIsr()` or `CoordinatedXyExecutor::onTimerUpdate()` |

The Debug image initially exceeded flash when the new diagnostic was compiled
at the project-wide `-O0` setting. Only the explicit Milestone 4 and Milestone 5
diagnostic lambda bodies are therefore marked `noinline`/`optimize("Os")`.
Normal routing, planner/executor code, GPIO hooks, and the timed ISR retain their
existing optimization attributes. This localized change reduces the final
candidate slightly below the accepted Milestone 4 image rather than consuming
additional flash.

Local validation commands:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
.\env\Scripts\python.exe -m pytest -q
```

## Qualification-Driven Corrections

Target qualification exposed four bounded implementation defects before the
accepted run:

- the raw-switch fallback initially paid an out-of-line accessor cost in the
  TIM2 ISR, so the Gantry-only raw GPIO read was made an always-inlined hook;
- a pause requested while STEP was high advanced the planner before refreshing
  its cached event, which could repeat one event after resume; the executor now
  refreshes the cache before entering `Paused`, with exact physical mask/count
  host traces covering the boundary;
- Debug `-O0` helper-call overhead pushed cancel and limit samples near or above
  the 2,250-cycle preliminary gate; only the bounded per-edge control, cycle,
  ARR-observation, and terminal-cleanup helpers were inlined, without changing
  the planner or executor algorithm;
- the diagnostic teardown originally compared its final home position with an
  arbitrary first post-flash coordinate. It now compares with the normalized
  rehome reference captured by each physical-limit case.

Each correction was followed by the complete firmware checks, target rebuild,
matching artifact copy, and a fresh exact-binary target run. The final physical
limit path measured 898 cycles and terminated inside the fixed 200-step window.

## HIL Evidence

The local and Pi copies of the flashed Debug binary both had SHA-256
`F1F6D4871B1B6FE277FA108A25F128280339DDE79910D786438BE26ABD2FEAD1`.

| Evidence | Result | Raw report and SHA-256 | Normalized report and SHA-256 |
| --- | --- | --- | --- |
| Ordinary SAFE | PASS - 28/28, not aborted, reset `None` | `hil_reports/milestone5_final_safe_raw.json`; `14BCABF8A8394D5DE437245CD3DEF7C60B3FAF76E85E82E7CF2E35F63293CA59` | Not required for the unchanged ordinary SAFE set |
| `normal_xy_route_v1` | PASS - 8/8, not aborted, reset `None` | `hil_reports/milestone5_final_normal_route_raw.json`; `1B052E6AA24973A2E31767BE6732E78D57B9EC2DCC76A4B5D3F6809E651FBF13` | `hil_reports/qualification/LC-001/20260812T021550Z_001/report.json`; `1BF7FB055910CEC5EE585240EB04B89BF5E9A39F7D90E805E79E54A756593CC4` |
| `coordinated_xy_executor_v1` regression | PASS - 7/7, not aborted, reset `None` | `hil_reports/milestone5_final_m4_regression_raw.json`; `401DC174E9679E355E96B038990084F01DB815C430AAAD91E4F7DD91F85308D8` | `hil_reports/qualification/LC-001/20260812T021550Z/report.json`; `D43BD48A5559104050405B89116745AA0A82BC791E27AFC0AD3E69DA8A5928BF` |
| `pressure_regulator_v1` regression | PASS - 10/10, not aborted, reset `None` | `hil_reports/milestone5_final_pressure_raw.json`; `3DC852EB107515D86BBABDEFDEE8459EC4D8AAE9B77F1CA57682376C2309CD91` | `hil_reports/qualification/LC-001/20260812T022212Z/report.json`; `3FBB52322FEA44B8F1E5F4A090E0A7663284D6EA092B0D88ED0B51D8EAC7BB7D` |

The corresponding normalized summary CSV evidence is:

- `hil_reports/qualification/LC-001/20260812T021550Z_001/summary.csv`:
  `2CAFB6DC4E683D9259C48AAFA91E369196F038BCB4DEB0BD6CEFBAF2F70620B7`;
- `hil_reports/qualification/LC-001/20260812T021550Z/summary.csv`:
  `6769FDC529156025704CDF96706EA765AF6909F11CBD935A29BBC92C671F5667`;
- `hil_reports/qualification/LC-001/20260812T022212Z/summary.csv`:
  `B745943C4E86995327C3D5B2A121C7DB1B07F5F3917B7DCF252BD0948948A599`.

Accepted normal-route metrics included exact pulse counts and endpoints on all
complete legs, zero coordinated TIM7 callbacks, a 65 ms maximum status gap,
simultaneous completion, low STEP and no pending update at every terminal
state. The worst route ISR sample was 2,137 cycles. Physical X/Y limit cases
stopped after 105/102 emitted steps, emitted no later rising edge, rebased both
targets, measured 1/0 step home drift, and had an 898-cycle maximum ISR sample.

The Milestone 4 regression retained exact `2 * masterSteps` callbacks, zero
TIM7 callbacks, pause/cancel/limit behavior, and a 2,152-cycle worst ISR sample.
The operator reported that equal and asymmetric diagonals appeared straight.
All ten pressure rows passed with no timeout, guard trip, or ready miss.

An initial pressure invocation used the generic 90-second FULL deadline and was
safely host-aborted while valid progress frames were still arriving after rows
2210-2214 had passed. It reported reset `None` and is not acceptance evidence.
The accepted rerun used `--timeout-ms 240000` and completed in approximately
165 seconds; the README command records that required host window.

Milestone 5 is therefore `verified` at its planned 3 kHz integration scope.
Production-rate straightness, lost-step, starvation, and reset qualification
remain mandatory Milestone 6 gates.

## Rollback

Immediate A/B rollback builds with
`LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0`. Full rollback reverts the single
Milestone 5 commit and restores the accepted Milestone 4 binary identified
above.
