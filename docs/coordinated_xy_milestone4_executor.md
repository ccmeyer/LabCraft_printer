# Coordinated XY Milestone 4: Gated Executor Evidence

## Status And Baseline

Milestone 4 is **verified** at its deliberately limited 3 kHz loaded-integration
gate. The final exact-binary run passed ordinary SAFE 28/28 and the explicit
coordinated executor suite 7/7 without a reset, watchdog failure, abort, pending
timer update, or unexpected contact. The operator reported that the equal and
asymmetric paths appeared straight, while noting that the low speed made the
short ramp sections difficult to judge. Production-speed straightness and
starvation remain Milestone 6 gates. Ordinary production motion is still routed
through the legacy executor.

An earlier qualification attempt exposed an unsafe legacy X/Y homing failure:
the axes reached their mechanical bounds aggressively instead of stopping at
their limit switches. That run was stopped immediately. The resulting safety
corrections and the complete evidence trail are retained below rather than
discarding the failed evidence.

| Field | Value |
| --- | --- |
| Branch | `feature/motor_movement_LUT` |
| Starting commit | `590c53be` |
| Starting worktree | Clean |
| Accepted Milestone 3 binary SHA-256 | `3661EFC3FC106528BE7F836C3C0C12803E6E5447767482E763C623412D9A4105` |
| Master timer | TIM2 / X |
| Secondary timer during coordinated execution | TIM7 stopped |
| Executor gate | `LC_COORDINATED_XY_EXECUTOR_ENABLE=1` |
| Normal-route gate | `LC_COORDINATED_XY_NORMAL_ROUTE_ENABLE=0` |
| Qualification selector/profile | P3 `2049` / `FULL` |
| Loaded qualification rate | 3 kHz |

Default call path:

`ABSOLUTE_XY -> Orchestrator -> Gantry -> independent X/TIM2 and Y/TIM7 Stepper timers`

Explicit qualification path:

`--coordinated-xy-executor-suite -> P3 2049 -> DiagnosticsRunner -> Gantry::startCoordinatedXY -> TIM2 -> CoordinatedXyExecutor -> shared LUT/DDA STEP masks`

No opcode, command frame, TLV layout, status payload, or parser format changed.
The ignored normal-command feed request remains unchanged. Z, direct-axis
motion, homing, and pressure regulation retain their separate implementations.

## Implemented Runtime Contract

`CoordinatedXyExecutor` is a pure state machine with no HAL or FreeRTOS
dependency. One cached `StepEvent` supplies both halves of a complete pulse:

1. the first TIM2 update raises the event mask;
2. the second update lowers the same mask and accounts completed X/Y pulses;
3. only the falling edge advances the DDA and normalized profile;
4. completion occurs on that final falling edge, with no trailing callback.

For `N` master events the executor therefore requires exactly `2N` TIM2
callbacks. TIM7 is not started. Pause, cancel, and limit requests received with
STEP high complete only that pulse; requests received with STEP low stop
immediately. Limit outranks cancel, which outranks pause. Every paused or
terminal state leaves both STEP pins low.

Position changes are made only after lowering a pulse that was actually raised.
Canceled, limit-aborted, and planner-faulted moves rebase both targets to the
last accounted position. Successful completion retains the prepared targets.

## Hardware Ownership And Start Sequence

`Gantry` prepares the complete planner/executor state in task context. It
checks timer identity, Z inactivity, signed target range, axis limits, timer
bounds, and both physical limit levels before any motion. It then reserves X
and Y independently; a failed Y reservation releases X without changing GPIO.

After both reservations, position-range and limit checks are repeated to close
the race with a legacy move completing or a switch changing during planning.
Only then does the adapter stop and clear TIM2/TIM7, force STEP low, set
participating DIR/ENABLE outputs, load the first ARR, clear completion bits, and
start TIM2 last. Stationary axes remain reserved but do not change DIR/ENABLE
or emit pulses.

`Stepper::dispatch()` offers a callback to the Gantry owner first only while
coordinated ownership is active. Otherwise it enters the unchanged legacy
dispatcher. Raw X/Y limit EXTI handling forwards the shared abort immediately;
the existing debounced path also forwards as a backup. Terminal cleanup stops
and clears both timers, forces all STEP pins low, finalizes targets, releases
both reservations, and sets `BIT_STEPPER1_DONE | BIT_STEPPER2_DONE` together.

No generated source was changed.

## Diagnostic And Qualification Contract

The explicit FULL diagnostic uses the existing P3 selector field and returns:

| ID | Case | Requested move |
| ---: | --- | --- |
| 2040 | X-only round trip | `(1000, 0)` |
| 2041 | Y-only round trip | `(0, 1000)` |
| 2042 | Equal round trip | `(1000, 1000)` |
| 2043 | Asymmetric round trip | `(500, 1500)` |
| 2044 | Pause/resume and reverse | `(2000, 1000)` |
| 2045 | Cancel and legacy recovery | `(2000, 1000)` |
| 2046 | Injected X/Y limit aborts | `(1000, 2000)` |

Before any motion, the suite disables both XY motors and requires four explicit
operator confirmations while directly reading the MCU inputs: X pressed, X
released, Y pressed, and Y released. A missing or stuck input fails closed and
skips every loaded test. After the operator has removed their hands, the suite
homes Z, then homes X and Y sequentially through the legacy path at a reduced
3 kHz coarse / 1 kHz fine rate. It moves to `(5000,5000)` at the legacy 6 kHz
setup rate. Coordinated legs run at 3 kHz.
Pause is held for 50 ms after at least 400 completed master steps. Cancel and
injected limit cases measure terminal edge latency and then recover through
legacy motion. Teardown rehomes XY and compares each fine-limit trigger with
the logical zero established by the initial home.

The manifest requires:

- exact emitted X/Y counts on complete forward/reverse legs;
- TIM2 callbacks equal to twice the master-event count and zero TIM7 callbacks;
- equal forward/reverse mask and ARR checksums;
- simultaneous X/Y done bits, low STEP pins, matching positions/targets, and
  no pending timer update;
- stable pause counters, cached-event resume, and terminal latency no greater
  than one remaining falling update with no new rise;
- maximum measured edge ISR cost no greater than 2,250 cycles;
- teardown fine-limit position no greater than 25 steps from the logical zero
  established by the initial home (the initial home's raw pre-zero coordinate
  is intentionally not a repeatability reference);
- operator confirmation that equal and asymmetric ramping paths appear straight.

No switch is intentionally struck by motor motion. After the stationary manual
input preflight, the loaded diagnostic injects the same pure executor limit
request used by the EXTI adapter; host/source tests lock the physical
forwarding route.

The legacy homing safety path is also hardened independently of this suite:

- X and Y use hard-stop-on-limit during homing;
- each active home timer callback reads the physical switch before profile math
  or another STEP edge, so stopping does not depend on deferred debounce/task
  work;
- the physical EXTI priority matches the step timers and remains FreeRTOS
  `FromISR` safe;
- firmware timeout/abort cancels and waits for active home workers;
- a host missing-DONE timeout transmits `CMD_SELFTEST_ABORT` before closing the
  serial session.

## Local Verification

The required final local command and result will be frozen here after the last
source change:

```powershell
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
.\env\Scripts\python.exe -m pytest -q
```

Final evidence:

| Evidence | Result |
| --- | --- |
| Firmware host tests | 314/314 pass; 7,416,229 checks |
| Debug target build | Pass; 0 errors, 4 pre-existing C++17-extension warnings |
| Python regression | 4,522 passed, 135 skipped, 440 existing warnings |
| Binary SHA-256 / length | `75F96CC8043509438AF8CC46342E1417A26269321F6B002D5DCB3823B7B1038D` / 389,752 bytes |
| Link size | text 376,608; data 13,128; bss 80,616 bytes |
| Delta from Milestone 3 | +36,432 binary/text bytes; +0 data; +380 bss bytes |
| Stack review | coordinated hardware ISR frame 56 bytes; legacy/home timer ISR frame 104 bytes; STEP-write frame 4 bytes; pure edge frame 24 bytes; full diagnostic frame 8,696 bytes within the 20,480-byte Orchestrator stack |
| Per-edge disassembly | Pass: no `UDIV`, `SDIV`, divide/float/cosine helpers, allocation, or exception calls in executor, DDA event, or LUT advance paths |

The focused host coverage includes exhaustive two-edge sequencing for all X/Y
magnitudes 0-64, reverse camera traces, exact falling-edge accounting,
pause/cancel/limit requests in low and high phases, priority collisions, final
pulse requests, planner faults, rearm, reservation conflicts, feature gates,
manifest selection, catalog/discovery, and analyzer regression behavior.

The Milestone 3 binary was 353,320 bytes. Because both images retain the same
16-byte binary/link-size offset and 13,128-byte initialized-data size, the
artifact delta is also the text delta. The static Gantry object grew from 4 to
384 bytes; the three new Stepper booleans occupy prior alignment padding, which
accounts for the measured 380-byte `.bss` increase. The final image retains
134,536 bytes of artifact address-space margin below 512 KiB.

## HIL Evidence

The first exact-binary run established basic executor behavior but failed the
preliminary ISR-cycle gate. The X-only round trip emitted exactly 2,000 X
pulses, used 4,000 TIM2 callbacks, used zero TIM7 callbacks, and had no pending
update, but measured 3,532 cycles against the 2,250-cycle gate. Results 2041-
2046 were skipped. Ordinary SAFE passed before this run with no reset.

| Evidence | SHA-256 |
| --- | --- |
| `hil_reports/milestone4_20260811_141935_safe_raw.json` | `3517E7A214311466FD49CB936629E57230121B560069BB4AB69C169D8734A69B` |
| `hil_reports/milestone4_20260811_141935_coordinated_raw.json` | `C91F8ECDB6742880B500930DA5D71AD5915165097B65755A253A9C8292553FD5` |

After optimizing the bounded coordinated hardware path, ordinary SAFE again
passed 28/28 with no reset. Two coordinated attempts then stalled during the
suite's old simultaneous 30 kHz legacy XY home. During the bounded retry, the
operator observed both axes drive aggressively into their mechanical bounds
instead of stopping at the switches. The host received no diagnostic result;
the active run was sent `CMD_SELFTEST_ABORT`. No hardware command, flash, or
test was issued after the operator's stop instruction.

| Evidence | SHA-256 |
| --- | --- |
| `hil_reports/milestone4_20260811_141935_safe_optimized_raw.json` | `032AA7900D6AE348493A2DC362F3069C5C7A15944BAE45ECEAE0256531DF76DC` |
| `hil_reports/milestone4_20260811_141935_coordinated_optimized_raw.json` | `761FF685EA42AB8328E8857246BC3DFF8BA04D9123A44848C0C4DE9AAB4912BA` |
| `hil_reports/milestone4_20260811_141935_safe_after_home_timeout_raw.json` | `5331322505A4A56FA95CE117E51FE2493EB4499FAD194C784DA8B5A81F3029E7` |
| `hil_reports/milestone4_20260811_141935_coordinated_optimized_retry_raw.json` | `65C5E7CE7A23F5EDDF86B59A918AD3E60C5CB95F42EA9694A31A52C5A7686DAD`; unsafe run ID `4072615104` |

The identified failure chain was simultaneous legacy TIM2/TIM7 homing at high
edge rates, step-timer priority above the raw limit EXTI, non-hard-stop X/Y
configuration, deferred debounce/task handling, and a host timeout that closed
serial without first aborting the firmware run. The operator inspected the
machine and switches before resuming. The corrected suite then required direct
MCU confirmation of X pressed/released and Y pressed/released before every
loaded attempt, used sequential 3 kHz/1 kHz X/Y homing, and canceled active
homes on timeout.

The subsequent bounded iterations were kept because each isolated a distinct
gate rather than relaxing an acceptance threshold:

| Raw coordinated report | Result | SHA-256 |
| --- | --- | --- |
| `hil_reports/milestone4_safety_20260811_145818_coordinated_raw.json` | X-only exact; ISR 3,258 cycles, over budget | `2E63A6EDCD5B2D014DD8B6943528FDA0D9C98368C87FC62AEC3C6F66305EF034` |
| `hil_reports/milestone4_perf_20260811_151124_coordinated_raw.json` | X-only exact; ISR 2,613 cycles, over budget | `32726490A0AA65348DAE348061FA65E41CBA516692F8E2D7716A2754F08EFDE9` |
| `hil_reports/milestone4_helpers_20260811_152153_coordinated_raw.json` | X-only exact; ISR 2,357 cycles, over budget | `6B47ECF3BC8A1212992F42E0822AEB31D0EF17480F21EC41B4803F041FAE775D` |
| `hil_reports/milestone4_terminal_20260811_153225_coordinated_raw.json` | 2040-2044 pass; legacy recovery after cancel exposed timer HAL-state handoff defect | `BF749F2B70090FFD81151BBBA1A67466B4A49661C6EA7BA7F621B45528BDABB6` |
| `hil_reports/milestone4_handoff_20260811_154700_coordinated_raw.json` | 2040-2045 pass; injected-limit path 2,277 cycles, 27 over budget | `26A6D2235BDD58B223F6F10EAA799B558A65285DAA510AA3EACE02BB72945735` |
| `hil_reports/milestone4_limit_20260811_155612_coordinated_raw.json` | Executor and limit gates pass; invalid first-post-flash home reference produced false drift 7,121/5,403 | `97EFB31285C45CA1CF19EA0E5A9B57FC3E45DDC986E8A5DA769DB40AE79E8D7E` |

The final run used binary SHA-256
`75F96CC8043509438AF8CC46342E1417A26269321F6B002D5DCB3823B7B1038D`.
The local and Pi hashes matched before flashing. Its evidence is:

| Evidence | Result | SHA-256 |
| --- | --- | --- |
| `hil_reports/milestone4_drift_20260811_160736_safe_raw.json` | SAFE 28/28; unchanged result set; `pending=0`, `fault=none`, `raw_sr=0`; no current watchdog fault | `748621F2A45672498C4471F246CA1E48696497A6927710AF9727D9ED0FCAB3F1` |
| `hil_reports/milestone4_drift_20260811_160736_coordinated_raw.json` | FULL 7/7; not aborted; all host checks pass | `0EE648589A18B56A66DDF45B6F76DB32F8D28D79E8F65B036AD6AAD397E544FF` |
| `hil_reports/qualification/LC-001/20260811T233728Z/report.json` | Normalized manifest status `pass`; no warnings | `476873F132D21A48654245F42C0087F8ACC945D7C22C275BCEEB69A3AE669892` |
| `hil_reports/qualification/LC-001/20260811T233728Z/summary.csv` | Normalized summary | `FB3A8EE778DB90987571A878770115541B019571BE260CADA90D9A2D93346C27` |

Final target metrics:

| ID | Max ISR cycles | Key result |
| ---: | ---: | --- |
| 2040 | 2,069 | 2,000 X pulses; 4,000 TIM2 callbacks; zero TIM7 |
| 2041 | 2,067 | 2,000 Y pulses; 4,000 TIM2 callbacks; zero TIM7 |
| 2042 | 2,119 | 2,000 X and 2,000 Y pulses; exact shared edges |
| 2043 | 2,076 | 1,000 X and 3,000 Y pulses; 6,000 TIM2 callbacks |
| 2044 | 2,077 | pause counters stable for 50 ms; cached-event resume and return pass |
| 2045 | 934 | cancel latency 0; no new rise; rebase and legacy recovery pass |
| 2046 | 929 | X/Y limit latency 0; no new rise; X/Y home drift 2/1 steps |

Every result was below the frozen 2,250-cycle preliminary gate, every terminal
state left STEP low, TIM7 and pending-update counts were zero, and complete
round trips returned to their starting coordinates. Run ID `4078397134`
completed with GOODBYE ACK/DONE and no reset or watchdog failure.

The operator reported that equal and asymmetric motion appeared straight with
no visible S-shaped entry or exit. Because this was a 3 kHz safety gate and the
ramp sections were short, the operator also reported that the observation was
harder to judge than a production-speed move. Milestone 4 accepts that qualified
observation; Milestone 6 must repeat straightness assessment on the speed ladder
and remains responsible for 40 kHz starvation qualification.

## Risks And Rollback

The principal remaining risks are behavior at production speed and the fact
that Milestone 4 injected limit requests instead of deliberately driving a
motor into a physical switch. The manual preflight proved that both switch
inputs asserted and released at the MCU, and low-rate sequential homing proved
the hardened home stop path, but controlled physical unexpected-limit
qualification remains a Milestone 5 gate. The 3 kHz ISR margin and visual
observation do not establish the final 40 kHz starvation or straightness
margin. The normal route remains disabled, which contains exposure to the
explicit FULL diagnostic.

Immediate rollback is building with `LC_COORDINATED_XY_EXECUTOR_ENABLE=0`.
Full rollback is reverting the single Milestone 4 commit and restoring the
accepted Milestone 3 binary with SHA-256
`3661EFC3FC106528BE7F836C3C0C12803E6E5447767482E763C623412D9A4105`.
