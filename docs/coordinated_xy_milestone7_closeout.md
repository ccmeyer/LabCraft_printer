# Coordinated XY Milestone 7 Production Closeout

## Status

Implementation and local validation are complete. Watched HIL is required
before this milestone is accepted; its reports will be added in a separate
evidence commit.

## Fixed production contract

Normal motion remains:

`Controller.set_absolute_XY()` -> opcode `0x0E` ->
`Orchestrator::executeAbsoluteXy()` -> `Gantry::moveTo()` -> coordinated TIM2
executor.

The production path is now fixed at TMC2208 MRES=3, DEDGE enabled,
`multistep_filt=0`, legacy logical command/status units through
`MotionUnitScale`, two timer callbacks per complete STEP cycle, and conditional
late rearming at 1,125 TIM2 ticks. Coordinated and ordinary direct X/Y/Z cosine
profiles use the normalized fixed-point LUT. Homing, limit soft-stop, P/R, and
alternate direct profiles retain their specialized behavior.

Normal XY has no legacy fallback or runtime schedule/execution mode. Rollback
uses a recorded source commit and hashed firmware artifact. The `feedHz`
argument remains ignored by the existing normal XY route and is deliberately
deferred because making it authoritative changes motion behavior.

## Removed experimental surface

- CompleteStep software pulse generation and pulse-width telemetry;
- FreeRunning and unconditional RearmFromActualEdge runtime choices;
- conditional-rearm synthetic late-edge injection and intentional-wait
  accounting;
- task-mutex status-metric synchronization and its lock-failure path;
- diagnostic MRES3 build configuration and binary;
- firmware selectors 2049, 2059, 2069, 2075, 2076, 2077, 2079, 2084, 2085,
  and 2086, plus their `run_selftest.py` flags;
- legacy XY compile gates, fallback implementation, and compile-only tests;
- obsolete diagnostic-only ISR counters and first-failure collection fields.

The historical result catalog and manifests remain readable. Superseded
manifests have `lifecycle: archived`: the UI and campaigns hide/reject them and
live qualification refuses them, while `--raw-report` still supports retained
evidence.

## Retained production observability

The earliest generated TIM2 user hook still captures DWT, CNT, and ARR before
HAL dispatch; the post-HAL hook records the final deadline and full IRQ path.
Saturating telemetry retains callback/entry/deadline coverage, pending updates
and streak, entry lateness maximum/count, schedule overrun, deadline misses and
minimum slack, conditional decisions/missing samples, rearm/pending-at-rearm,
minimum non-rearmed slack, edge-to-restart maximum, phase/terminal/full-IRQ
maxima, duration, ownership, STEP-low state, DWT wraps, and saturation.

Production result IDs are:

- `2097` selector -> `2087` motion, `2088` IRQ path, `2089` conditional
  schedule, `2090` driver configuration;
- `2096` selector -> `2091` through `2095` direct X/Y/Z LUT regression;
- `2078` selector -> `2071` production camera-ratio/home transition.

Active manifests are `coordinated_xy_production_mres3_v2`,
`direct_xyz_lut_v1`, and `coordinated_xy_camera_transition_v2`.

## Build and size record

The accepted parent baseline is commit `a9c8bcde`. Its production artifact was
357,224 bytes with SHA-256
`09A00B221816B73390666BB1A084EE7009DF9555072965E1F7C659B9683DF2FB`.
The baseline Debug ELF used 344,080 bytes text, 13,128 data, and 81,880 BSS.

The current closeout build uses 312,152 bytes text, 13,128 data, and 81,680
BSS. The production binary is 325,296 bytes with SHA-256
`69AC8ECB3F3330DF7B8835AFD64BDA56FE73D71F2DC12F64FF945A65C8AA153F`.
This is a 31,928-byte binary/text reduction and a 200-byte BSS reduction from
the accepted baseline. The fixed conditional TIM2 body has a 120-byte static
frame; with its 24-byte dispatcher the inspected call-depth envelope is 144
bytes, below the accepted 168-byte measurement and the 1,024-byte MSP reserve.
ELF symbol inspection found no CompleteStep, injection/wait, task-mutex,
diagnostic-MRES3, runtime schedule-mode, or legacy-route symbols.

The build helper now treats a nonzero CubeIDE exit as terminal and does not
copy a possibly stale artifact after a failed build.

## Local validation

The required final gates are:

```powershell
.\env\Scripts\python.exe -m pytest -q
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
git diff --check
```

Final local results:

- Python: 4,623 passed, 135 skipped;
- firmware host: 396 tests, 8,723,789 checks, zero failures;
- Debug firmware: zero build errors (three pre-existing C++17-extension
  warnings in `callbacks.cpp`);
- `git diff --check`: clean.

## Watched HIL closeout

Flash the exact closeout artifact once. SAFE-bracket every motion suite and
stop for contact, abnormal sound, lost squareness, missing motion/home, limit
abort, reset, watchdog increment, incomplete telemetry, or communication loss.

Run in order:

1. SAFE (30/30).
2. Selector `2097`, manifest `coordinated_xy_production_mres3_v2`.
3. SAFE.
4. Selector `2096`, manifest `direct_xyz_lut_v1`.
5. SAFE.
6. Selector `2078`, manifest `coordinated_xy_camera_transition_v2`.
7. SAFE.
8. Operator-gated `xy_motion_v1`.
9. SAFE.
10. Operator-gated `motion_envelope_v1`.
11. SAFE.
12. General FULL through `firmware/scripts/run_fw_hil_windows.ps1` against Pi
    `192.168.0.33`.

Acceptance requires exact logical endpoints/native pulses, bounded home drift,
complete timing evidence, no pending-at-rearm, saturation, timeout, reset, or
watchdog increment, passing status cadence, and normal operator observation.

## Rollback

Immediate rollback is commit `5750b3ca` and its accepted 357,224-byte artifact,
SHA-256
`09A00B221816B73390666BB1A084EE7009DF9555072965E1F7C659B9683DF2FB`.
Direct-LUT-only rollback is commit `9dc66f11`, artifact SHA-256
`7EB588C49258F215046BB77C5E5A5518D4BCAAB550F1AFA32CB62E45E2A1A2C6`.
A full pre-normal-route rollback uses the accepted Milestone 4 source/artifact
identity in the Milestone 4 record. No rollback branch is compiled into the
closeout firmware.
