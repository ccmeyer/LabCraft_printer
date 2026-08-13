# Coordinated XY Milestone 7 Production Closeout

## Status

Milestone 7 is accepted. Implementation, local validation, and the complete
watched HIL sequence passed on the exact production artifact recorded below.

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
  schedule, `2090` driver configuration, and `2098` continuous motion-limit
  debounce attribution;
- `2096` selector -> `2091` through `2095` direct X/Y/Z LUT regression;
- `2078` selector -> `2071` production camera-ratio/home transition.

Active manifests are `coordinated_xy_production_mres3_v3`,
`direct_xyz_lut_v1`, and `coordinated_xy_camera_transition_v2`.

## Continuous motion-limit confirmation revision

The transient-stop evidence above exposed that raw X/Y samples could bypass
the configured debounce. Production now uses one fixed 15 ms policy for all
Stepper endstops X/Y/Z/P/R. Raw EXTI handlers mask/rearm their line and start a
candidate but never latch a hit, stop an axis, or request a coordinated abort.
The active axis timer ISR samples the GPIO; a release rejects the candidate,
while an uninterrupted assertion confirms at the 15 ms DWT-cycle boundary.
Confirmed direct and coordinated stops retain the established safe-edge
cleanup so STEP is low and completed pulses are accounted exactly.

Moving away from an already asserted home switch remains allowed. The switch
must then remain continuously released for 15 ms before another approach.
Coordinated startup performs the same stationary confirmation both before and
after reserving X/Y. DWT arithmetic is wrap-safe; an unavailable DWT confirms
an asserted input immediately and causes result `2098` to fail its timebase
gate. Z remains active-high with no internal pull. PG13/PG14 keep their
separate existing 15 ms pressure-regulator debounce.

Result `2098` reports X/Y candidates, rejected transients, confirmations and
pending state, timebase validity/failures, first abnormal terminal reason,
saturation, and timeout. Candidates and rejected transients are informational;
confirmed or unresolved inputs during the motion row fail qualification.
Manifest v2 is archived for historical normalization and v3 is the only live
production coordinated manifest.

The debounce revision uses 312,352 bytes text, 13,128 data, and 81,864 BSS.
Its versioned production binary is 325,496 bytes with SHA-256
`E12F9519498B84AC3913F1C6E0DDD56666A9443F9E43D868B7C9B576041523ED`.
The 200-byte binary and 184-byte BSS increases hold the bounded policy and five
per-axis states. The inspected coordinated ISR remains a 120-byte body plus a
24-byte optimized debounce helper, preserving the 144-byte call-depth
envelope. Obsolete immediate-limit ISR/task APIs are absent from the ELF.

## Build and size record

The accepted parent baseline is commit `a9c8bcde`. Its production artifact was
357,224 bytes with SHA-256
`09A00B221816B73390666BB1A084EE7009DF9555072965E1F7C659B9683DF2FB`.
The baseline Debug ELF used 344,080 bytes text, 13,128 data, and 81,880 BSS.

The pre-debounce closeout build uses 312,152 bytes text, 13,128 data, and 81,680
BSS. Its production binary is 325,296 bytes with SHA-256
`4EEC9952F564947A5293CE6A1198DA4397A9E6D084A4E7266493F4403BE7AB4D`.
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

- Python: 4,625 passed, 135 skipped;
- firmware host: 400 tests, 8,723,795 checks, zero failures;
- Debug firmware: zero build errors (three pre-existing C++17-extension
  warnings in `callbacks.cpp`);
- `git diff --check`: clean.

## Initial watched attempt and qualification correction

The first closeout artifact (`69AC8ECB...AA153F`) flashed successfully. Its
pre-SAFE passed 30/30 at `boot=164`, `fault_ct=4`, and `wdg_ct=6`. Selector
`2097` then completed one exact 10,000-master-step move with 4,538/4,538 IRQ
and entry samples, zero pending updates, zero missed deadlines, 2,145 ticks of
minimum deadline slack, correct driver configuration, and a 2,465-cycle
terminal maximum. It failed closed before the remaining row because the
closeout had inadvertently applied the old 2,250-cycle active-edge interval
limit to terminal cleanup. Post-SAFE passed 30/30 with all three retained
counters unchanged.

This was a qualification-policy regression, not an executor-cost regression:
the three retained pre-closeout production rows measured terminal maxima of
2,496, 2,502, and 2,508 cycles, while production deliberately did not apply
the active-edge gate after the final edge. The corrected production contract
remains strict but uses a separate 2,700-cycle terminal-cleanup bound (15 us
at 180 MHz), retaining margin over accepted evidence without changing motion,
GPIO, ARR, rearm, rate, or acceleration behavior. The watched sequence must
restart after flashing the corrected artifact recorded above.

## Corrected-artifact transient limit stop

The corrected `9afc8a76` artifact was 325,296 bytes with SHA-256
`4EEC9952F564947A5293CE6A1198DA4397A9E6D084A4E7266493F4403BE7AB4D`.
Its pre-SAFE passed 30/30 at `boot=166`, `fault_ct=4`, and `wdg_ct=6`.
Selector `2097` then stopped during the final reverse leg after completing
9 full moves and part of the tenth: X emitted 51,656 of 53,416 expected native
cycles, Y emitted 83,726 of 90,000, and TIM2 recorded 207,452 of 220,000
callbacks. The partial X/Y counts retain the exact commanded diagonal ratio.
Timing remained bounded (`pu=0`, `sl=671`, `ns=1151`, and `tm=2437`) and no
reset report was observed. The operator reported normal sound and motion before
the stop, with both physical limit switches released and no obstruction near
either switch. Post-SAFE again passed 30/30 with the same retained counters.

The production snapshot did not retain the terminal reason or raw/debounced
limit counts, so this run cannot prove which input requested the stop. The
existing firmware does, however, abort coordinated motion on the first raw X
or Y limit sample before the configured 15 ms software debounce can run. The
next production revision therefore treats this run as evidence for consistent
continuous limit confirmation and explicit limit attribution, not as evidence
for weakening any motion-timing gate.

Retained evidence:

- pre-SAFE `hil_reports/m7_closeout_20260813T214143Z_pre_safe.json`, SHA-256
  `9BE761F4864855B5A52986D5B3055426C2FC067E5902C6E4E3B5EC826597DDC4`;
- focused `hil_reports/m7_closeout_20260813T214143Z_2097.json`, SHA-256
  `2910A9889BC20346D978C6154047BAB0F36D336589B01FF5AAADD20EA9417C64`;
- post-SAFE `hil_reports/m7_closeout_20260813T214143Z_post2097_safe.json`,
  SHA-256
  `E1350482DED158871B433F8B61107BDA87305E0DEC14440537B14AF4A897F65F`;
- normalized report `hil_reports/qualification/LC-001/20260813T214543Z/report.json`,
  SHA-256
  `71551B2CFBDBD8B7519216DBC2C651BABBEE0FC84B5DB368113AA955278AE790`.

## Watched HIL closeout

Flash the exact closeout artifact once. SAFE-bracket every motion suite and
stop for contact, abnormal sound, lost squareness, missing motion/home, limit
abort, reset, watchdog increment, incomplete telemetry, or communication loss.

Run in order:

1. SAFE (30/30).
2. Selector `2097`, manifest `coordinated_xy_production_mres3_v3`.
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

### Accepted debounce qualification

The watched closeout ran on source commit `8f9ef80a` using the normal Debug
production image, 325,496 bytes, SHA-256
`E12F9519498B84AC3913F1C6E0DDD56666A9443F9E43D868B7C9B576041523ED`.
The Pi independently verified that hash before flashing. The source tree had
only the excluded generated
`firmware/.settings/language.settings.xml` change; no source or artifact
change was present.

The complete sequence passed:

- initial, inter-suite, and final SAFE brackets all passed 30/30;
- selector `2097` passed 5/5 with exact 53,416 X, 90,000 Y, 110,000
  master-step, and 220,000 TIM2-callback totals;
- result `2098` observed one Y candidate and rejected it before confirmation
  (`yc=1;yr=1;yf=0;yp=0`), while X remained clear and the row completed;
- selector `2096` passed all five direct X/Y/Z LUT rows;
- selector `2078` passed its exact 60,000-callback camera/home transition;
- `xy_motion_v1` passed three long-travel repetitions and two raster
  repetitions (194 raster moves), with maximum X/Y drift of 8/4 steps;
- `motion_envelope_v1` passed reverse, diagonal, 387-move plate raster, three
  Z long-travel repetitions, and already-triggered-home rows;
- general FULL passed 28/28, including four-axis homing and XY home
  repeatability; and
- the final SAFE retained `boot=168`, `fault_ct=4`, and `wdg_ct=6`, with all
  four watchdog participants live, no current late task, and no reset report.

All five focused reports normalized as `pass` with zero blocking issues and
zero warnings. The operator was present for every motion suite and reported
normal sound, motion, squareness, and homing. A visibly slow opening segment
in selector `2078` was consistent with its bounded initial homing/positioning
phase; exact motion and transition telemetry passed.

Raw evidence (path, SHA-256):

| Evidence | SHA-256 |
| --- | --- |
| `hil_reports/m7_limit_debounce_00_pre_safe.json` | `498B672DF7F71168A04B934649310FDF48395FD5CE3381FE4602FC5DE3336E1C` |
| `hil_reports/m7_limit_debounce_01_coord_2097.json` | `121C59F3DAF9F3962E5900C5BE272C11F5BC4A0E7F6E22FFA5EA3AC83047512F` |
| `hil_reports/m7_limit_debounce_02_post_2097_safe.json` | `E0723C7EAC40A92B131F4D03DFB9CDE4768311E069BFD463C0BFA9BA4276DA48` |
| `hil_reports/m7_limit_debounce_03_direct_2096.json` | `61CD1676E03BD7EC608E5DF0F1D48626C3FCDD971D1196704E04B3C6C021935B` |
| `hil_reports/m7_limit_debounce_04_post_2096_safe.json` | `55C2AA7E955A4A7F7DB9484A12368D074DA26FB8A8D3E5ECECC126A777E48AEC` |
| `hil_reports/m7_limit_debounce_05_camera_2078.json` | `F98A9D552DED304931F5D60860D33C31527F162F5109B8AD4D92FB6642E76319` |
| `hil_reports/m7_limit_debounce_06_post_2078_safe.json` | `FEE7ADD95037C4202BC16D22F3921E5D4F7A2EFC7E238D5B6A46AFA0AEC9C280` |
| `hil_reports/m7_limit_debounce_07_xy_motion.json` | `863D1CA2B65C30166B5D31FE006791F4AD16DB762BDA2D4933A8F439F48FAA9C` |
| `hil_reports/m7_limit_debounce_08_post_xy_motion_safe.json` | `ACCE6ACDD96E51BB8AA0A21649AB494E350D898B8122463327696D573F8EB422` |
| `hil_reports/m7_limit_debounce_09_motion_envelope.json` | `FB499002BA60584A5CB7578AC21609902493B813745808F0CF0BD9614A6FF814` |
| `hil_reports/m7_limit_debounce_10_post_motion_envelope_safe.json` | `B86E86F5B823B9B2C7946BA708BFCAC831AFA173C25C1841F3F012779FA89C13` |
| `hil_reports/m7_limit_debounce_11_general_full.json` | `9B4F408CD5ACFB19927D931BCB293F8E131CA1BE6241D48FB9522E1609DC8389` |
| `hil_reports/m7_limit_debounce_12_final_safe.json` | `04F33C7901848E381766DCC3AFA75F1E018062E5D71E4B6262C3D8804AA763C2` |

Normalized reports are retained below
`hil_reports/m7_limit_debounce_normalized/LC-001/` at timestamps
`20260813T224449Z`, `20260813T224552Z`, `20260813T224636Z`,
`20260813T225037Z`, and `20260813T225425Z` for `2097`, `2096`, `2078`,
`xy_motion_v1`, and `motion_envelope_v1`, respectively. Their `report.json`
SHA-256 values are, in that order:

- `F7A12A14A98DB9135221CAD23831091625CD7440A9261743532C6399534CEA53`;
- `B72E8C306574764133BDD7F9BDD3942798A1E7B1F0BDB7B88C4EC7C059CCBD62`;
- `4FE53BD58E89F3741C448827E53CA01B023619B3C69DCBCA5D8B066B5C341526`;
- `50501BDFC43E45E02C76EB4124603EDCF1035B8C99102812E3F8A82D2DF73FD6`;
  and
- `F9A7755E9F08084C85D68595E0380604135ED4BDB135F844CF8883E301F9560F`.

## Rollback

The immediate debounce-revision rollback is source commit `9afc8a76` and its
325,296-byte artifact, SHA-256
`4EEC9952F564947A5293CE6A1198DA4397A9E6D084A4E7266493F4403BE7AB4D`.
That rollback restores the prior raw-limit bypass and is for recovery only,
not an accepted production closeout.

Immediate rollback is commit `5750b3ca` and its accepted 357,224-byte artifact,
SHA-256
`09A00B221816B73390666BB1A084EE7009DF9555072965E1F7C659B9683DF2FB`.
Direct-LUT-only rollback is commit `9dc66f11`, artifact SHA-256
`7EB588C49258F215046BB77C5E5A5518D4BCAAB550F1AFA32CB62E45E2A1A2C6`.
A full pre-normal-route rollback uses the accepted Milestone 4 source/artifact
identity in the Milestone 4 record. No rollback branch is compiled into the
closeout firmware.
