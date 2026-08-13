# Coordinated XY Milestone 6: Production-Speed Qualification

Status: `implemented`

## Starting State

| Item | Accepted value |
| --- | --- |
| Starting commit | `6814737d7ff248d496d6385844e1d458e3ab8263` |
| Milestone 5 binary SHA-256 | `F1F6D4871B1B6FE277FA108A25F128280339DDE79910D786438BE26ABD2FEAD1` |
| Legacy comparison commit | `a045c7f6` |
| Legacy comparison binary SHA-256 | `E850806BA3743C59C75A9A70C321C58D89760EAF7D0438C302DA5F429A3BF7A6` |
| Machine | `LC-001` on Pi `192.168.0.33` |
| Core/timer clocks | 180 MHz / 90 MHz |
| Normal XY route | Coordinated, compile-time legacy override retained |

The accepted Milestone 1 comparison report is
`hil_reports/qualification/LC-001/20260811T185807Z/report.json`, SHA-256
`4990666AB60D81B8D50535FB34FFF0BE219779AC5583F2FBC9843FB6E0C89028`.
Its raw report SHA-256 is
`B58AF706B8034091C0AC2EC5D4868B70F475D77899088F6687327DB5CD8FCBD1`.

## Fixed Safety Contract

- No protocol, normal routing, feed-rate, pressure-control, limit polarity,
  GPIO/EXTI, or production homing algorithm changes are part of this milestone.
- The tracked candidate retains the 40 kHz X/Y cap and enables conservative
  coordinated ISR instrumentation.
- The FULL suite has one fixture confirmation covering the approved closed-loop
  pressure fixture and the complete clear XY/Z envelope.
- The bounded diagnostic-home change passed the established manual X/Y
  pressed/released preflight, low-rate regression, and focused loaded gate.
  Because subsequent code does not affect switch reading or homing, the full
  suite returns to its planned single combined fixture/envelope confirmation.
- If the final diff changes limit polarity, GPIO/EXTI handling, raw limit
  sampling, limit-before-rise ordering, or homing state/rates/backoff, HIL is
  blocked until the existing manual switch preflight and low-rate
  `normal_xy_route_v1` regression pass.
- Failure at any rate stops progression. Thresholds are not relaxed and the
  configured speed is not silently reduced.

## Qualification Matrix

Selector `2069` emits results `2060` through `2068` plus investigation result
`2070` under manifest
`coordinated_xy_performance_v1`.

| ID | Qualification |
| --- | --- |
| 2060-2064 | Five-geometry forward/reverse ladder at 5, 10, 20, 30, and 40 kHz |
| 2065 | Exact Milestone 1 X, Y, equal, camera-ratio, and short vectors |
| 2066 | 40 kHz asymmetric ratios and Z-up 16x24 serpentine raster |
| 2067 | Five repeated 40 kHz camera/home-ratio round trips |
| 2068 | 40 kHz camera-ratio motion while both P/R regulators actively transition |
| 2070 | Direction-isolated X-only checks at 30/35/40 kHz, including a reduced-acceleration 40 kHz case, with an independent home reference after every leg |
| 2071 | Standalone cold camera-ratio round trip followed immediately by bounded legacy X home, with enable/STEP/ownership/limit transition evidence |

The expected 90 MHz target/start ARR pairs are `8999/44995`, `4499/22495`,
`2249/11245`, `1499/7495`, and `1124/5620`.

## Acceptance Gates

- Active ISR maximum `<= 2025` cycles; terminal maximum `<= 2250` cycles.
- Zero pending updates and zero pending streak at every accepted rate.
- Exact pulse counts, `TIM2 callbacks = 2 * masterSteps`, and zero coordinated
  TIM7 callbacks.
- Duration error `<= 100` basis points, firmware status gap `<= 100 ms`, and
  host status gap `< 500 ms`.
- No reset report, watchdog late task, timeout, abort, counter saturation, or
  unexpected DWT wrap.
- X/Y post-home drift `<= 25` steps and return error `<= 10` steps.
- Both pressure regulators move during the concurrent-load row, settle to the
  accepted targets, and tear down safely.
- The operator reports no visible S curve or bow in the required 40 kHz paths.

## Evidence

Local implementation gates are complete. The source-scoped Diagnostics size
optimization is built, regression-tested, and accepted against its measured
source-pragma thresholds. Target rows remain pending the single combined
fixture/envelope confirmation and an accepted HIL run.

| Evidence | Result | Path / SHA-256 |
| --- | --- | --- |
| Firmware checks | PASS | 337/337 host tests, 7,416,877 checks; Debug target link passed with zero errors and the three pre-existing C++17-extension warnings in `callbacks.cpp` |
| Python regression | PASS | 4,555 passed, 135 skipped |
| Legacy-route A/B compile | PASS | Host gate target and ARM `Gantry.cpp` syntax build with `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0` |
| Per-edge disassembly | PASS | No divide instructions/helpers, floating helpers/instructions, cosine, allocation, or exception calls in the executor, recorder, or TIM2 adapter path |
| Diagnostics source optimization | PASS | Whole-translation-unit GCC `Os` pragma is scoped only to `Diagnostics.cpp`; object 99,543 bytes is within the explicitly approved 100,000-byte post-investigation gate, and the largest suite frame 4,064 is within the unchanged 4,096-byte gate |
| Link / stack review | PASS | text 310,680; data 13,128; bss 80,824 bytes; binary 323,824 is within the explicitly approved 324,000-byte post-investigation gate; partition headroom 69,392 bytes; outer diagnostics frame 3,464 bytes; M6 diagnostic 3,072 bytes; focused helper 1,272 bytes |
| Tracked binary | Full HIL failed safely at 40 kHz geometry reference | 323,824 bytes; `517B53AE236C0E644BB51220D6D7C4965F1D882840DAE93463D22461B1B4E05A` |
| Pre-run SAFE | PASS | 28/28, not aborted; `hil_reports/m6_diag_os_harness_pre_safe_20260812T044900Z.json`; `7C4040CAE48B87C1D3B6F83FF108461A28B1982623BFAC2A8C0DDCB97C9048F8` |
| Normalized-cosine LUT benchmark | PASS | LUT mean/max 128/149 cycles; legacy mean/max 432/590; speedup 4.37x; prepare 973/873; ARR error 1; IRQ restore and deterministic checksum pass; `hil_reports/m6_diag_os_harness_lut_20260812T045000Z.json`; `DF51555070A7B30E773E494CC1A21707F264D004078856AC5996B8D61312FEDD` |
| Focused X direction suite | PASS | 8/8 legs; exact 168,000 X pulses / 336,000 TIM2 callbacks, zero TIM7/pending/timeout, ISR active/terminal maxima 1,091/2,157 cycles, home drift 0-4 steps; raw `hil_reports/m6_x_direction_geometry_20260812T0147Z.json`, `A04FBBA28A84B8C10A09D5521691E4B8EF43E38E2EC8640413B58D2F3B62C859`; normalized `hil_reports/qualification/LC-001/20260812T084723Z/report.json`, `18319ACA2AEF2F690510F49D6D11966C8FF95EC66DA86EA1E26CBD36C3971CD5` |
| FULL performance suite | FAIL-STOP | 5-30 kHz and focused X gate pass; all ten 40 kHz geometry legs pass logical/timing gates, then X bounded home exhausts coarse guard plus probe without switch; later rows skipped; raw `hil_reports/m6_full_final_20260812T0154Z.json`, `F778EEC34F0165B4D08AC80ADF8F6D3874795E79E6581141F09C8F26BF09DEB8`; normalized expected-fail `hil_reports/qualification/LC-001/20260812T090030Z/report.json`, `0E2D5A6D7B6E3649AF58A6C58F12627AB06CFA920AA2328B929ABC34B3602D7D` |
| Normalized focused report | Expected FAIL | `hil_reports/qualification/LC-001/20260812T081707Z/report.json`; `4300E470C247679D04711282CAAB6E66280095264E9CC7D5C7879A40649982FF` |
| Post-run SAFE | PASS | 28/28, not aborted, no reset report; `hil_reports/m6_full_final_post_safe_20260812T0200Z.json`; `67DEE5835CD8A4BDCD40A056EB1B0F94DF8F2A630447E4878E10CB0A1AC75D8D` |
| Operator straightness | Pending | Pending |

The final candidate pre-run SAFE passed 28/28 without abort, reset, or watchdog
evidence: `hil_reports/m6_x_direction_terminalfix_pre_safe_20260812T0115Z.json`,
SHA-256 `76A1ECCF84BFA3F419E54D89A0E055BF49DD876576F731FE300BF0C66BBFE996`.

### First 40 kHz Investigation Run

The first performance run reached and completed all ten 40 kHz geometry legs
with exact requested pulses and callbacks, zero pending updates, no watchdog or
reset evidence, active ISR maximum 1,202 cycles, and terminal maximum 2,206
cycles. The subsequent X reference home did not reach its switch before the
20-second diagnostic wait expired, so row 2064 failed and rows 2065-2068 were
correctly skipped. The raw report is
`hil_reports/m6_observation_fix_full_20260812T065800Z.json`, SHA-256
`1A08CFFDF8DDE682423160D15BBA328CA95A06F3F886F10BE1381053D2DCDA6F`.

A read-only status check after the stop reported X position `-51049` and X
target `-291084`, while Y remained at position/target `30500`. Starting from
the expected X coordinate `8916`, the home attempt therefore accounted roughly
59,965 X steps without reaching the switch. The physical gantry was observed
near the X home switch, remained square, and showed no component damage. This
does not establish whether the remaining distance was small; it does establish
that simply extending an unbounded timeout would conceal a position mismatch.

The investigation build replaces that diagnostic behavior with a guard derived
from the known software coordinate plus 3,000 steps. Unknown startup positions
use the established envelope plus the same margin. It captures commanded and
accounted coarse-home steps, phase, outcome, switch observation, and timeout
state. Result 2070 then tests positive and negative X independently at 30 kHz,
35 kHz, 40 kHz with 70,000 steps/s^2, and 40 kHz with the current 140,000
steps/s^2. The reduced-acceleration legs use 24,000 steps, which exceeds their
22,858-step combined ramp distance and therefore includes a true 40 kHz cruise;
the other legs use 20,000 steps. Every leg gets its own home reference, so equal
losses in opposite directions cannot cancel. Any failure blocks the ordinary
40 kHz row.
Selector `2079` exposes this as the standalone
`coordinated_xy_x_direction_v1` suite and emits only result `2070`, allowing the
focused evidence to be accepted before selector `2069` is permitted to resume.
The manual X/Y pressed/released preflight, low-rate regression, and focused
loaded gate passed after the bounded-home change. Subsequent changes affect only
coordinated abort cleanup, failure reporting, and diagnostic vector length; they
do not touch switch sampling, EXTI, or homing. Both selectors therefore retain
one fixture/envelope confirmation and do not repeat manual switch actions.

Selector `2078` exposes the separate
`coordinated_xy_camera_transition_v1` investigation and emits only result
`2071`. After the normal Z and sequential X/Y reference homes, it positions at
5 kHz, runs one measured 40 kHz camera-ratio forward/reverse pair, captures
both X enable outputs plus coordinated STEP/ownership/pending state, and starts
the bounded 3 kHz/1 kHz legacy X home immediately. It records the raw switch
state before and after home, bounded coarse command/accounting, home phase and
outcome, and the final legacy TIM2 callback/pulse snapshot. The path does not
actuate pressure and has one clear-envelope prompt with no manual switch gates.

### Direction-Isolated Obstruction Run

The focused selector fail-stopped on its first measured case, positive X at
30 kHz and 140,000 steps/s^2. Firmware telemetry reported exactly 20,000 X
pulses, 40,000 TIM2 callbacks, zero Y pulses, and zero pending updates. The
following bounded X home started from software coordinate 20,100, observed the
physical switch, completed at the expected 100-step backoff, and did not hit
the outer timeout. It accounted 19,672 coarse return steps before the switch;
the fine-trigger coordinate differed from the newly established zero by more
than the 25-step gate. The approximately 428-step coarse discrepancy is an
estimate of the physical/software divergence, not a replacement for the fine
trigger metric.

After the run, the operator reported that X contacted an obstruction during the
measured leg. That observation explains the physical/software divergence and
invalidates this run as evidence of an intrinsic 30 kHz motor-speed limit. It
still separates the event from ISR starvation: software produced the exact
event and pulse totals with no pending timer update while the external contact
prevented the physical axis from traveling the corresponding distance. The
selector correctly detected the offset during the next home and skipped every
later direction/rate case. Raw report:
`hil_reports/m6_x_direction_terminalfix_20260812T0117Z.json`, SHA-256
`61A7D6E243D44BA388D1DE08F1D1ED1787C6F2A4255246192E1D248E624D9317`.

The next unobstructed run passed both directions at 30 and 35 kHz and completed
the positive 40 kHz / 70,000 steps/s^2 leg with exactly 20,000 pulses, 40,000
callbacks, and zero pending updates. Its original report did not identify the
failed move sub-gate. A compact failure mask was therefore added without
changing motion, limit, or homing behavior. The repeated run reported mask
`5120`, which is exactly selected-rate mismatch (`1024`) plus ARR-range mismatch
(`4096`). All other reported gates passed: active maximum 1,091 cycles, terminal
maximum 2,157 cycles, zero pending observations/streak, zero duration error,
66 ms firmware status period, 51 ms status-watchdog age, no alternation or late
watchdog events, and no cycle wrap or saturation. Raw enhanced report:
`hil_reports/m6_x_direction_gate_metrics_20260812T0142Z.json`, SHA-256
`898D4FFC7C77D808464E3C89792DD6030E540FBBCFA1BCF6F192D19DAA5FBD7F`.

That failure was a diagnostic geometry error. A 20,000-step triangular move at
70,000 steps/s^2 peaks at approximately 37.4 kHz, so it cannot legitimately
produce the requested 40 kHz selected rate or 40 kHz ARR. The reduced-
acceleration pair is now 24,000 steps, exceeding its 22,858-step combined ramp
distance and creating a real 40 kHz cruise interval. Expected focused totals
are consequently 168,000 X/master steps and 336,000 TIM2 callbacks. The other
six legs remain 20,000 steps. This test-only correction does not alter normal
motion behavior.

The corrected focused gate subsequently passed all eight legs. It emitted
exactly 168,000 X pulses and 336,000 TIM2 callbacks, used no TIM7 callbacks,
recorded zero pending updates or timeouts, and measured active/terminal ISR
maxima of 1,091/2,157 cycles. Its eight independent home references drifted by
only 0-4 steps. The normalized analyzer accepted the report with no blocking
issues or warnings.

### Full 40 kHz Geometry Failure

The next full run passed the complete 5, 10, 20, and 30 kHz geometry rows and
passed the focused X gate again. At 40 kHz, all ten geometry legs completed and
individually passed the firmware's exact endpoint, target, pulse, callback,
ARR, ISR-cycle, pending-update, duration, status, and watchdog gates. The row
then failed its independent X reference home. The home began at software
coordinate 8,916, consumed all 11,916 commanded/accounted coarse steps without
seeing the switch, then consumed the fixed 1,600-step slow probe and still did
not see it. It ended in `Probe` / `Failed` at software coordinate -4,600.

This proves a physical/software X displacement exceeding 4,600 steps after the
mixed 40 kHz geometry workload despite an exact logical event stream. It does
not reproduce in the isolated X-only 40 kHz cases and it is not attributable to
MCU interrupt starvation: every measured move had already passed the zero-
pending and ISR-cycle gates before the reference home was attempted. The suite
correctly skipped the Milestone 1, raster, camera-repeat, and pressure-stress
rows. Post-failure SAFE passed 28/28 with no reset or watchdog evidence. No
additional motion is permitted until the operator confirms the physical X
location, gantry squareness, and absence of contact or abnormal sound.

A closely observed rerun reproduced the same software result after the
operator reported that all motion, including the final long diagonal, appeared
normal and square with no missed-step sound or crash. Firmware entered the
post-tier X home at `15:37:36.488`, accounted its complete coarse guard and
probe over approximately 5.5 seconds without observing the switch, emitted the
failure result, and then completed the normal GOODBYE shutdown. The report was
not aborted, contained no reset report, and received both GOODBYE acknowledgments;
the following SAFE run passed 28/28. This narrows the apparent freeze/reset to
an open-loop actuation or accumulated-position problem during the final home,
followed by intentional motor disable, rather than MCU starvation or reset.

The standalone selector `2078` was selected as the next diagnostic. It separates
the final camera vector and coordinated-to-legacy transition from the preceding
5-30 kHz tiers and the extra 168,000-step focused X workload. Passing cold would
favor cumulative thermal/power/driver loading; reproducing cold would favor the
camera vector or the coordinated-to-legacy GPIO/enable transition. The full
suite remains blocked regardless of the standalone result.

### Camera/Home Transition Isolation Result

The cold standalone transition diagnostic passed on 2026-08-12. Its two
coordinated legs emitted exactly 16,832 X pulses and 60,000 Y pulses in 120,000
TIM2 callbacks with no TIM7 callbacks or pending updates. The active and
terminal ISR maxima were 1,165 and 2,156 cycles. Immediately before legacy
home, both X enable outputs were asserted, both coordinated STEP outputs were
low, and coordinated ownership was released.

The immediate bounded X home started at software coordinate 8,916, observed
the physical limit after 8,919 accounted coarse steps within its 11,916-step
guard, completed its 100-step release backoff, and ended at X coordinate 100.
The final legacy TIM2 snapshot recorded 201 callbacks, 100 completed backoff
pulses, and no pending update. The raw limit input was released before and
after the home. This cold pass does not clear Milestone 6, but it makes the
camera-ratio vector and coordinated-to-legacy enable/GPIO transition unlikely
to be sufficient causes of the repeated full-suite failure. Accumulated
workload effects, including driver temperature, supply behavior, or a
history-dependent mechanical/electrical condition, are now the leading class
of hypotheses.

Evidence:

- Firmware binary SHA-256:
  `E0E802A4D6B5E47825FA90DF31850AA33B0FBF48A3C08EBDA8E083DDF758E7C9`.
- Pre-run SAFE: `hil_reports/m6_camera_transition_pre_safe_20260812T160117Z.json`,
  SHA-256 `591A5F55EE8CFD0C6DB5CD4E8E043A211368C8E1B3344CD192166377637E4324`,
  28/28 pass with no abort or reset evidence.
- Raw focused report: `hil_reports/m6_camera_transition_20260812T160117Z.json`,
  SHA-256 `B05D0EAC1570B046330BEC6C9176495DCBF092AE67DCB04D5B3CE17D2C94285E`.
- Normalized report:
  `verification_reports/LC-001/20260812T160332Z/report.json`, SHA-256
  `52DE1256D74BC69022D727373B7056E00DD859282131F7431E6EEE55E4C8DE68`,
  verdict `pass` with zero blocking issues and zero warnings.
- Post-run SAFE: `hil_reports/m6_camera_transition_post_safe_20260812T160117Z.json`,
  SHA-256 `3351E15045E02C3B6970D6E0BB0E163B9190DB3D56825CC6B1D996F68F11E73E`,
  28/28 pass with no abort or reset evidence.

The full 2060-2068 suite remains blocked. The next diagnostic should preserve
the passing camera/home transition while adding controlled preceding workload
in bounded increments, with a reference-home check between increments, so the
first workload level that produces physical/software divergence is identified
without repeating the entire failing suite.

Selector `2077` provides the first such isolation step through
`coordinated_xy_40khz_v1`. It reuses result `2064` and its exact five
forward/reverse geometry pairs, initial reference homes, and bounded post-row
X/Y homes. It deliberately skips the 5-30 kHz tiers, the 168,000-step focused
X-direction gate, and results 2065-2068. A cold pass would show that the
ordinary 40 kHz row is also insufficient by itself and would further favor
accumulated workload. A cold failure would isolate the problem to one or more
motions inside that geometry row rather than the preceding tiers.

### Standalone 40 kHz Geometry Result

The first standalone 40 kHz run failed closed before completing the row. The
first three geometry pairs and the forward 1:4 leg completed, producing 85,000
X pulses, 100,000 Y pulses, 140,000 master steps, and 280,000 TIM2 callbacks.
The aggregate contains eight move slots because `addPair()` records an empty
reverse observation after a failed forward observation; only seven physical
measured legs ran. The forward 1:4 observation recorded one pending TIM2 update
with a maximum streak of one. Its ordinary active-handler maximum was 1,205
cycles. The result therefore failed before the 1:4 reverse, camera-ratio pair,
or post-row reference homes, and the post-home drift fields remained their
sentinel values.

The pending flag is sampled only for non-terminal callbacks after the
coordinated handler and before instrumentation recording. It does not mean the
2,221-cycle terminal maximum directly caused this observation. The active
measurement begins inside the Gantry dispatch and excludes interrupt-entry,
HAL TIM dispatch, and any time TIM2 waited behind an already-running equal- or
higher-priority interrupt. Consequently, an active handler can measure 1,205
cycles while the timer nevertheless reasserts its update flag before the
callback completes. The 2,221-cycle terminal maximum independently shows only
29 cycles of in-handler margin against a 2,250-cycle 40 kHz edge interval.
Together these observations show that the complete interrupt path does not
have reliable 40 kHz margin under this workload, even with pressure motion
disabled.

The host received the result and SELFTEST_DONE normally, followed by both
GOODBYE acknowledgments. Pre- and post-run SAFE each passed 28/28 with no abort,
reset report, or watchdog evidence. This is distinct from the earlier
post-row-home displacement because fail-stop prevented the standalone run from
reaching either reference home. It proves the isolated 40 kHz row has a real
timing problem, but it does not yet establish whether that timing problem caused
the prior physical displacement.

Evidence:

- Firmware binary: 325,320 bytes, SHA-256
  `016FD8EEE18879AD9EDF2933F633056110380CF7D9FBDD276139CC1860D9924C`.
- Pre-run SAFE: `hil_reports/m6_40khz_only_pre_safe_20260812T161623Z.json`,
  SHA-256 `B8FABC232FA8988C7816AB4AE36CB0CAF67EA11E07B022CF7B27CC806A6B4BE6`,
  28/28 pass.
- Raw focused report: `hil_reports/m6_40khz_only_20260812T161623Z.json`,
  SHA-256 `8353C7466772F1CA147286601D1A2C4AB03EAC89E6F58CDD0529336895BA8070`.
- Normalized report:
  `verification_reports/LC-001/20260812T161928Z/report.json`, SHA-256
  `31FBD124DF52C36A8A081F251FCFDBF76DFED8A9AF06DB05DBABEF8BEC2DDA93`,
  verdict `fail` with 11 blocking issues and no warnings.
- Post-run SAFE: `hil_reports/m6_40khz_only_post_safe_20260812T161623Z.json`,
  SHA-256 `881E802141036141C4421C4A038E3D4279F3CE86BBB975B4BBBECFEC84353AB4`,
  28/28 pass.

Do not rerun the 40 kHz row unchanged. The next diagnostic change should move
the DWT entry timestamp outward to the earliest TIM2 IRQ/dispatch point or add
a second outer timestamp, preserving the current inner phase timing. This will
separate Gantry handler cost from HAL/dispatcher latency and interrupt blocking.
After that evidence, reduce the terminal path and/or full IRQ path rather than
relaxing the zero-pending gate.

The next candidate implements that measurement without changing movement. The
TIM2 handler's first USER CODE block records DWT only while coordinated timing
is armed. Gantry consumes that timestamp alongside its existing inner entry,
phase, pending, and terminal state. The second TIM2 USER CODE block records the
return from `HAL_TIM_IRQHandler()` and closes the same sample even when the
terminal callback has already released coordinated ownership. Result `2072`
reports full sample coverage, missing correlations, pre-Gantry and full
software-IRQ maxima/means, terminal full-path maximum, and the pre/full values
of any pending-correlated callback. This brackets HAL and dispatch overhead but
does not claim to measure exception-entry waiting before the first C handler
instruction or exception-return overhead after its last timestamp.

### Correlated TIM2 IRQ-Path Result

The first outer-instrumented attempt completed five physical measured legs and
stopped on an instrumentation-inflated inner terminal value of 2,310 cycles.
It recorded all 200,000 TIM2 callbacks with no pending updates. The complete
software-path maximum was 2,948 cycles and was exactly the terminal callback;
because TIM2 was already stopped, that terminal duration could not create a
following pending update. The added outer-correlation bookkeeping was then
moved after the established inner timing boundary, and result `2072` gained
`ax`, a separate non-terminal full-path maximum. This changed measurement only,
not motion, timer, limit, homing, or GPIO behavior.

The refined run reproduced the timing failure during the sixth physical move,
the reverse equal diagonal. It completed the X-only, Y-only, and equal pairs,
then failed closed before the 1:4 pair with 16 pending observations and a
maximum streak of one. The completed workload contained exactly 80,000 X
pulses, 80,000 Y pulses, 120,000 master steps, and 240,000 TIM2 callbacks with
no TIM7 callbacks. Every TIM2 callback had a matching outer timing sample and
there were no missing correlations or counter saturations.

Measured cycle evidence at the 180 MHz core clock was:

- inner active maxima: acceleration 1,175, cruise 1,116, deceleration 1,210;
- inner terminal maximum: 2,232;
- pre-Gantry C-path maximum/mean: 361/334;
- complete software IRQ maximum/mean: 2,911/1,412;
- non-terminal complete software IRQ maximum: 1,909;
- terminal complete software IRQ maximum: 2,911;
- pending-correlated pre-Gantry/full-path maxima: 358/1,816.

The pending-correlated full C-level path retained 434 cycles of nominal margin
inside the 2,250-cycle edge interval. Therefore the pending update cannot be
explained by the coordinated handler, LUT/DDA work, HAL return path, or their
combined measured duration alone. The unmeasured interval is between the timer
update becoming pending and the first C instruction in `TIM2_IRQHandler`.
TIM2 and many peripheral interrupts use NVIC priority 5, and FreeRTOS critical
sections raise `BASEPRI` to priority 5. The strongest current source candidate
is task/interrupt masking before TIM2 entry. In particular, the 50 ms status
task's `recordStatusSend()` performs its full metric update inside
`taskENTER_CRITICAL()`, and the 16 observations over a roughly one-move window
are consistent with that 20 Hz cadence. Equal-priority UART/DMA/timer service
and other critical sections remain alternatives until directly correlated.

Evidence:

- Firmware binary: 326,992 bytes, SHA-256
  `5582489DCB01CAE6843535E39E4DB5147C7964FF516CD97FFE86BDA232D1D470`.
- Pre-run SAFE: `hil_reports/m6_irq_path_refined_pre_safe_20260812T165115Z.json`,
  SHA-256 `D6B94F1E4D572CE72F8544EE0742CD29DA7E67EF553E4EC33B27CF6C29C2BD5A`,
  28/28 pass.
- An intervening host-timeout attempt was aborted before results because the
  status-only timeout was 10 seconds. Its post-abort SAFE report
  `hil_reports/m6_irq_path_refined_abort_post_safe_20260812T165331Z.json`,
  SHA-256 `54D2A4CCE9472BBF318FD62675AAA74143AD2263F0EB19BF1E956448467F24A6`,
  passed 28/28. The accepted rerun used 120 seconds without changing firmware.
- Raw focused report:
  `hil_reports/m6_irq_path_refined_40khz_20260812T165423Z.json`, SHA-256
  `86EB7E8E55430D8B525B19B2FDF634D99A802A88C195ABFE802CAA539944A019`.
- Normalized report:
  `verification_reports/LC-001/20260812T165540Z/report.json`, SHA-256
  `BA8690E2D8452476B5DEB4A4961BCCFACF958EB7709565A912C3A8EF8F9144B1`,
  verdict `fail` with 11 blocking issues and no warnings.
- Post-run SAFE:
  `hil_reports/m6_irq_path_refined_post_safe_20260812T165519Z.json`, SHA-256
  `2F2C74D343AF514217C6F48FB57915D5B742FC0E641A28E0DC32781A10158CAB`,
  28/28 pass with no reset evidence.

Do not rerun the same 40 kHz image. The next change should measure timer-counter
lateness at the first TIM2 C hook and perform a controlled status-critical-
section A/B test. A fix should shorten or remove the priority-5 masking window;
the zero-pending gate must not be relaxed.

### Stage 1 TIM2 Entry-Lateness Candidate

The measurement-only Stage 1 candidate implements the first half of that next
diagnostic. In the first TIM2 USER CODE block, while coordinated timing is
armed and before `HAL_TIM_IRQHandler()`, it captures DWT `CYCCNT`, TIM2 `CNT`,
and TIM2 `ARR` using register reads and stores only. Bounded integer aggregation
runs after the established pending-update observation, so the new calculations
cannot create the pending state they are intended to correlate.

Result `2073`, `coord_xy_40khz_entry_lateness`, is emitted beside `2064` and
`2072`, including on a measured-row fail-stop. Its metrics are callback count
(`i2`), valid/missing samples (`s`/`mi`), maximum/mean entry counter in 90 MHz
timer ticks (`cm`/`ca`), pending-correlated counter maximum (`pm`), entries at
or above 128 ticks (`lc`), maximum positive inter-entry overrun in 180 MHz core
cycles (`dm`), status synchronization mode (`sm=0`), saturation (`sf`), and
timeout (`to`). The 128-tick value is diagnostic only. Result `2073` requires
complete unsaturated evidence but does not require zero pending observations;
the unchanged `2064` row remains the fail-closed zero-pending acceptance gate.

Automated validation is complete for normal/late entry samples, pending
correlation, first-sample suppression, DWT wrap, schedule overrun, missing
samples, saturation, result-frame budget, selector routing, manifest coverage,
and analyzer rejection of incomplete evidence:

- firmware checks: 342/342 host tests and a zero-error Debug target link (the
  three existing target warnings remain unchanged);
- Python regression: 4,568 passed and 135 skipped;
- candidate binary: 328,096 bytes, SHA-256
  `CD3330841ACF8FF9099FE621096971E1641F66BF70D1A10D43992F70BC4A07CE`,
  leaving 65,120 bytes in the 384 KiB application partition;
- retained baseline commit: `23d706af`; Stage 1 source/artifact commit:
  `b777f993`.

### Stage 1 HIL Result And Stage 2 Gate

The single physical Stage 1 run completed the exact ten-move 40 kHz row and all
440,000 TIM2 callbacks. Results `2072` and `2073` passed with complete sample
coverage, no missing samples, no saturation, clean host status cadence, and no
watchdog/reset evidence. Unlike the preceding refined image, this run produced
zero pending observations and a zero pending streak. Entry lateness was still
visible: `cm=506` timer ticks, `ca=24`, `lc=2072`, and `dm=966` core cycles.
Because `pu=0`, `pm=0` is not a pending-correlated observation. The approved
Stage 2 gate requires pending to reproduce as well as `pm >= 128` or
`dm >= 256`; it therefore did not open. Do not repeat motion solely to force a
pending event, and do not implement or run selector `2076` from this evidence.

The unchanged motion row failed for a separate post-row X reference defect:
X drift was 54 steps against the 25-step gate while Y drift was 3. The bounded
X home did reach its limit and return to coordinate 100; this was not an outer
home timeout. The normalized report has 20 blocking analyzer issues because
the fail-closed home-specific `2064` frame intentionally omits the normal
success-frame timing fields; it does not represent 20 independent physical
faults. Results `2072`/`2073`, host cadence (100 ms maximum over 201 samples),
and the progress watchdog all passed.

An initial SSH invocation delivered an invalid fixture response and firmware
aborted at the envelope gate with zero results, before homing or motion. It is
retained as infrastructure evidence. The corrected invocation supplied the
explicit response `continue`; only that invocation performed motion.

Evidence:

- binary: 328,096 bytes, SHA-256
  `CD3330841ACF8FF9099FE621096971E1641F66BF70D1A10D43992F70BC4A07CE`;
- pre-SAFE: `hil_reports/m6_entry_lateness_pre_safe_20260812T180724Z.json`,
  SHA-256 `837CDE4068269430CE1182A7CBD7925816438ABD6ADC2DE469BDE2397117FA2C`,
  28/28 pass;
- no-motion fixture-abort report:
  `hil_reports/m6_entry_lateness_40khz_20260812T180724Z.json`, SHA-256
  `FA99F8926AF142E041665FAE9C4CA102C8F162D42B0C9F6FC74840A1E920E6EE`;
- physical focused report:
  `hil_reports/m6_entry_lateness_40khz_physical_20260812T180724Z.json`,
  SHA-256 `D3A6F52B687E5863CA03071B90017E0AF17BA0747ADD571C536A22B952145BE6`;
- normalized report:
  `verification_reports/LC-001/20260812T181108Z/report.json`, SHA-256
  `A1BFA3DB4165D2ECE0C86204D9ED83355415B60459616623D6C8441323B35943`,
  verdict `fail` with 20 blocking issues and no warnings;
- post-SAFE: `hil_reports/m6_entry_lateness_post_safe_20260812T180724Z.json`,
  SHA-256 `44F6E1F7333750779F094B0650A77A1B78C16B398D465ECEA90FC927F938AD4B`,
  28/28 pass with unchanged boot/watchdog counters and no reset evidence.

This diagnostic-only image is 4,096 bytes above the previously approved
324,000-byte Milestone 6 candidate ceiling, while retaining 65,120 bytes of
application-partition headroom. That observation is not approval to raise the
production ceiling; Stage 1 remains diagnostic-only and is not a production
default. The task-mutex variant is not implemented or enabled, so normal
operation continues to use the existing status critical section.

### Velocity-Domain Acceleration Correction Candidate

Review of the separate X reference defect found that the `140000 steps/s^2`
axis value was a planner input but not an actual peak bound. The old planner
used `v^2/(2a)` to select 5,715 acceleration steps at 40 kHz, then applied the
cosine to timer `ARR`. Because velocity is proportional to `1/(ARR+1)`, the
resulting smooth velocity envelope peaked at approximately 443,900 steps/s2,
about 3.17 times the configured value, near 86 percent of the ramp. This can
increase physical torque demand and is a credible contributor to lost steps;
it is separate from the TIM2 interrupt-entry investigation.

The correction keeps the ISR fixed-point, table-driven, allocation-free, and
division-free. The 257-point Q20 table now represents a cosine in velocity
squared transformed back into timer period. Deceleration reads its reciprocal
time-reversed form. Planner preparation uses the conservative bounded ramp
length

`ceil(7 * target_rate^2 / (8 * acceleration_cap))`.

For the 90 MHz timer, 40 kHz target, and 140,000 steps/s2 cap, this changes each
full acceleration/deceleration ramp from 5,715 to 10,000 master steps. The
calculated piecewise smooth-envelope peak is approximately 131,100 steps/s2.
Every 20,000-step geometry leg still reaches target `ARR=1124` at its phase
join, and the 30,000-step camera-ratio leg has a 10,000-step cruise, so the
focused selector remains a genuine 40 kHz qualification. Integer ARR
quantization remains visible as one-tick pulse-period granularity; the bounded
contract is the 256-cell velocity envelope that exposed the prior 443,900
steps/s2 defect.

Automated candidate evidence before HIL:

- 344/344 host tests and 8,723,583 checks pass, including period ratios
  1.01-5.00, full coordinated traces from 3-40 kHz, triangular moves, unequal
  axis limits, and 16-/32-bit timer bounds;
- Debug target build passes with the same three pre-existing warnings;
- candidate binary: 328,272 bytes, SHA-256
  `598EAD7B83DA6E0455B9D1B9761DD0D2865DD63D151BDE38FD085D341B796F20`.

HIL acceptance remains one pre-SAFE 28/28 run, exactly one guarded selector
`2077` run, and one post-SAFE 28/28 run. The Stage 1 lateness/IRQ results remain
enabled so the repeat also reports whether the pending symptom recurs. This
motion-profile candidate does not implement status mutex selector `2076`.

### Velocity-Domain Correction HIL Result

The single authorized selector `2077` repeat passed all three firmware results
and normalized with no blocking issues or warnings. The motion row completed
the exact ten moves, 106,832 X pulses, 180,000 Y pulses, 220,000 master steps,
and 440,000 TIM2 callbacks with no TIM7 callbacks. It retained the real 40 kHz
target, reported zero pending observations/streak, zero saturation, zero
timeout, 100 ms maximum host status gap over 181 samples, and a passing progress
watchdog. The post-row reference errors were X=4 and Y=1 steps, compared with
X=54 and Y=3 on the immediately preceding ARR-cosine Stage 1 image.

The result strongly supports excessive effective acceleration as a contributor
to the physical X displacement, but one passing repeat is not a statistical
proof that all lost-step behavior is eliminated. It also does not resolve the
separate interrupt-entry issue: result `2073` still measured `cm=507`,
`lc=1799`, and `dm=968`. No pending update happened in this run, so `pm=0` is
again not a pending-correlated sample and the status-mutex Stage 2 gate remains
closed.

Timing remained within the retained acceptance gates: inner acceleration,
cruise, deceleration, and terminal maxima were 1,202, 1,068, 1,230, and 2,221
core cycles respectively; non-terminal complete software IRQ maximum was 2,051
cycles. Results `2064`, `2072`, and `2073` all passed with complete coverage.
Pre/post SAFE passed 28/28, both reported no reset record, and watchdog metrics
were unchanged (`sticky_ct=1`, `recovery_boot=1`, all four required tasks live).

Evidence:

- binary: 328,272 bytes, SHA-256
  `598EAD7B83DA6E0455B9D1B9761DD0D2865DD63D151BDE38FD085D341B796F20`;
- pre-SAFE: `hil_reports/m6_accel_profile_pre_safe_20260812T183642Z.json`,
  SHA-256 `4B1D416E203C3CDFE5157F9FAB50C6A237BDD8E551019AD62836B684484B7328`,
  28/28 pass;
- focused physical run:
  `hil_reports/m6_accel_profile_40khz_20260812T183642Z.json`, SHA-256
  `090CCACC94F4CE29DF6289BB5CC37E6DB3859AD4BCE0FD95505EB36FE23E3476`,
  3/3 pass;
- normalized report:
  `hil_reports/qualification/LC-001/20260812T184002Z/report.json`, SHA-256
  `BA7A8ABCBA82D50BBEA872F1C96C136831AA6AD4417A48C0978E92F3EEA41E14`,
  verdict `pass` with zero blocking issues and zero warnings;
- post-SAFE: `hil_reports/m6_accel_profile_post_safe_20260812T183642Z.json`,
  SHA-256 `28E44458848E972124811557E8BFAEAAD13F17D2FF7B4BD66589F72883973983`,
  28/28 pass.

The printer remains flashed with this exact velocity-domain correction image.
Do not promote it to the production default or rerun FULL until the evidence
and the remaining entry-lateness risk are reviewed.

### Stage 2 Status-Synchronization A/B Candidate

The retained pending-update run establishes an intermittent real-time deadline
miss even though the two later entry-lateness runs did not reproduce pending.
Because the primary objective is to eliminate rare movement-related failures,
the user authorized a controlled A/B comparison rather than additional
critical-section-only attempts to force the symptom.

Selector `2076` now reuses selector `2077`'s exact ten-move 40 kHz geometry,
bounded homes, result IDs, live status transmission, and watchdog checks. The
only experimental change is status-metric synchronization. `Comm` creates a
dedicated static FreeRTOS mutex at boot but continues to default to the existing
critical section. Selector `2076` temporarily protects metric reset, update,
and consistent snapshot operations with that mutex, using a 5 ms bounded wait;
selector `2077` explicitly retains the critical section. UART transmission is
outside the metric lock. A scope guard restores critical-section mode on every
return, and an unavailable mutex or any lock failure fails closed before or
during evidence collection. Result `2073` adds lock-failure count `lf` and
reports `sm=1` for the mutex arm.

The initial diagnostic artifact was 329,352 bytes with SHA-256
`23A820FC54FF990BEA66A7F7AF893749B94BC16902F77884B7699E33F5242944`.
Its first Pair 1 critical-section arm stopped during the first measured X-only
leg after 2,599 of 20,000 requested pulses and 5,198 TIM2 callbacks. It recorded
complete IRQ/entry coverage for those callbacks, zero pending observations,
`cm=253`, `lc=10`, `dm=455`, `sm=0`, `lf=0`, passing host cadence, and no reset
or watchdog evidence. The four-second wall time rules out expiration of the
30-second move timer; the legacy `to=1` aggregate convention represents any
non-completed observation. Because result `2064` did not retain the terminal
reason, this attempt cannot distinguish a raw/EXTI limit abort from a planner
fault. No B arm or later motion was run. Pre/post SAFE both passed 28/28 with
unchanged boot/watchdog counters.

Evidence for that stopped arm:

- pre-SAFE: `hil_reports/m6_status_sync_p1_a_pre_safe_20260812.json`, SHA-256
  `8E4149DCD0BF814581D4D681827953CD63C650D2A5F7867DBEE2450AF54D1614`;
- raw A report: `hil_reports/m6_status_sync_p1_a_critical_20260812.json`,
  SHA-256 `74BE84744B0ECC2BBC76339F6EE79F863B32C8C4488C5C03EB131389232F9947`;
- normalized failure: `hil_reports/qualification/LC-001/20260812T191209Z/report.json`,
  SHA-256 `DA4D907297E42B48D0BB3E04159EABA238870D699CA6982446C850BB7B7DB532`;
- post-SAFE: `hil_reports/m6_status_sync_p1_a_post_safe_20260812.json`, SHA-256
  `F530C4A7DC32FD7200D759020900400FBE1C29B1AB7443E962FF4734F24BDE66`.

The measurement-only retry artifact retains the first failed leg in result
`2073` as `fv`, terminal reason `tr`, coordinated limit-abort request count
`la`, and raw limit observation count `ra`. It does not change the planner,
timer, GPIO, limit decision, motion, or synchronization paths. A successful row
reports all four fields as zero; `tr=3`/`4` identifies X/Y limit termination and
`tr=5` identifies a planner fault. The strict mutex manifest now requires those
zero values. The artifact is 329,504 bytes with SHA-256
`2E63EE041788393ED726F60EA8CA2477990CA2550420875DCFCE9FDA347B9A28`,
leaving 63,712 bytes in the 384 KiB application partition. Firmware host tests
pass 346/346 with 8,723,591 checks, the Debug target links with the same three
pre-existing warnings, and the full Python regression passes 4,573 tests with
135 skipped. Mutex mode remains diagnostic-only and must not become the
production default without separate review and qualification.

### One-Interrupt-Per-Step Diagnostic Candidate

The next robustness experiment is implemented behind explicit selector
`2075`. It does not change the normal call path or boot default: ordinary
coordinated motion still uses one TIM2 callback for the STEP rise and one for
the STEP fall. Selector `2075` temporarily selects `CompleteStep`, programs the
full master-step period, raises the DDA-selected STEP pins with direct BSRR
writes, waits at least the planner's 2 us minimum using wrap-safe DWT cycle
arithmetic, lowers the pins, and commits the event before returning from the
same ISR. Interrupts remain enabled during the high interval. The selector's
scope guard restores `TwoEdge` after every success, failure, abort, timeout, or
setup exit.

The exact selector-`2077` geometry now expects 220,000 TIM2 callbacks rather
than 440,000, while master-step counts, LUT checksums, 40 kHz target, corrected
velocity-domain acceleration, status transmission, watchdog supervision,
limit sampling, and bounded homes remain unchanged. Result `2074` records mode,
interrupts per step, DWT pulse-window bounds, required pulse cycles, full-path
deadline samples, missing/missed deadlines, minimum timer slack, pending
updates, saturation, timeout, and exact-motion state. Manifest
`coordinated_xy_single_irq_v1` requires a 360-cycle minimum pulse interval and
at least 500 remaining 90 MHz timer ticks after every full software IRQ path.

The final unflashed diagnostic artifact is 333,584 bytes with SHA-256
`5D429338CFB3E1EA59147E7F79D67A039237611AAF03CC1C7E3A103CDD06A3F4`,
leaving 59,632 bytes in the 384 KiB application partition. The Debug ELF uses
320,440 bytes of text, 13,128 bytes of initialized data, and 81,072 bytes of
BSS. Firmware validation passes 363/363 host tests with 10,213,593 checks and
links with zero errors and the three existing warnings. The full Python
regression passes 4,590 tests with 135 skipped. Static stack analysis
reports 120 bytes for the coordinated TIM2 handler and 3,464 bytes for the
outer diagnostic runner. ARM disassembly confirms that the DWT pulse loop is
an inlined load/subtract/compare/branch sequence with no helper call, division,
HAL GPIO call, allocator call, or interrupt-masking instruction.

Automated host and target checks are the prerequisite for flashing. Before
selector `2075`, the no-motion self-test scheduler A/B experiment must close
the retained pressure-watchdog starvation finding. New images report SAFE as
30/30 because rows `1044` and `1043` add retained pressure-phase and live
scheduler evidence. After that closeout, the motion HIL procedure is one
pre-SAFE 30/30 run, one watched selector `2075` run, one post-SAFE 30/30 run,
and normalization with the matching manifest. Stop for
contact, abnormal sound, lost squareness, limit anomalies, incomplete motion,
reset/watchdog evidence, missing telemetry, or any deadline miss. This is an
experimental candidate, not production enablement.

The subsequent lightweight I2C-attribution image includes this same selector
`2075` implementation and is 338,768 bytes with SHA-256
`220B93804445B99F1E116B9FA41CA87794C711B8B135BA7EAFE53AD4EA2E7906`.
It leaves the pressure deadline, recovery sequence, and normal motion path
unchanged. A short no-motion SAFE check should classify the observed recovery
as HAL error/busy/timeout before watched selector `2075` motion is run; the
long idle soak remains deferred at the user's request.

The preceding low-rate normal-route regression completed all five ordinary
motion rows exactly. Its control row failed only because the instrumented abort
terminal measured 2,349 cycles versus the retained 2,250-cycle gate; cancel
latency, no-post-request rise, target rebasing, STEP-low state, and pending count
all passed. The ISR abort cleanup now avoids redundant GPIO-low writes only
after the executor has proven STEP low; task/startup cleanup retains forced-low
writes. ARM disassembly confirms that split. No additional motion run is
allowed until the obstruction is removed and the operator confirms the dual-X
gantry, belts, rails, cable path, limit switch, and complete envelope remain
square, clear, and mechanically normal.

Before source-scoped optimization, the Milestone 6 candidate added 1,800 bytes
relative to the accepted Milestone 5 image and measured 392,800 bytes. Applying
the GCC `Os` scope only to `Diagnostics.cpp`, while preserving the Milestone 2
timing harness and legacy oracle at `O0`, removes 72,272 bytes and leaves the
current candidate 70,472 bytes smaller than Milestone 5. The coordinated TIM2
handler frame remains 80 bytes, and the localized FULL diagnostic remains
within the existing Orchestrator task stack. The source pragma does not enable
all preprocessing-time and interprocedural passes selected by command-line
`-Os`, explaining the difference from the earlier 316,200-byte experimental
link. The measured source-pragma gates accepted for this candidate are a
97,000-byte Diagnostics object, 321,000-byte firmware binary, and 4,096-byte
maximum diagnostic suite frame. The bounded-home and focused direction
investigation added 2,597 bytes to `Diagnostics.o` and 3,048 bytes to the
binary. On 2026-08-12 the user explicitly approved corrected ceilings of
100,000 bytes for `Diagnostics.o` and 324,000 bytes for the binary because the
candidate still leaves 69,640 bytes in the application partition. The 4,096
byte stack-frame ceiling is unchanged. These corrected ceilings apply to this
safety investigation and are not permission for unrelated future growth.

## Rollback

Immediate rollback disables coordinated instrumentation or builds with
`LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0`. Full rollback restores commit
`6814737d` and its accepted Milestone 5 binary identified above.
