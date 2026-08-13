Plan: Retained Crash Record + Watchdog-Based Fault Reset
Summary
Implement a firmware-only crash visibility and watchdog system with these properties:

Post-reset crash visibility persists across MCU reset using retained backup registers.
Runtime faults (HardFault, MemManage, BusFault, UsageFault, stack overflow, configASSERT, Error_Handler) write a retained crash record.
A watchdog resets the MCU when the firmware faults or when a critical periodic task stops making progress.
Initial visibility surface is SAFE self-test + boot log only, not live protocol status, to avoid unnecessary protocol expansion.
No protocol opcode changes are required. run_selftest.py should continue working with metrics-only additions.
This plan deliberately avoids CubeMX .ioc edits and avoids enabling new HAL modules for IWDG/RTC. It uses:

direct IWDG register access
direct RCC reset-flag reads
direct RTC backup register access
That keeps the diff localized and avoids generated-init churn.

Validation Commands
Implementation must validate with:

run_fw_checks.ps1 -Config Debug
run_fw_hil_windows.ps1 -PiHost 192.168.0.29 -Profile SAFE
Additional manual fault/watchdog validation should be done on hardware after the automated SAFE lane is green.

Current Repo Facts
These are the design constraints confirmed from the repo:

There is no watchdog configured today.
HAL_IWDG_MODULE_ENABLED is commented out in stm32f4xx_hal_conf.h
HAL_WWDG_MODULE_ENABLED is commented out too
There is no RTC/HAL_RTC setup today.
HAL_RTC_MODULE_ENABLED is commented out
there is no MX_RTC_Init() or RTC_HandleTypeDef hrtc
Fault handlers currently just spin forever:
stm32f4xx_it.c
Error_Handler() also just disables IRQs and spins:
main.c
vApplicationStackOverflowHook(...) now exists and latches a RAM-only flag, but that flag is not retained across reset:
freertos.c
STM32F446 backup registers are available in the device headers.
Current SAFE self-test already has:
1040 rtos_memory_headroom_safe
space for more SAFE self-tests before the FULL branch in Orchestrator.cpp
Current self-test metrics TLV is currently truncated at 112 bytes in the firmware emitter. That is enough for compact summary metrics, but not for a verbose crash dump.
Chosen Scope
User-selected visibility surface:

SAFE self-test + boot log only
Not in scope for this slice:

live status/tag additions for the Python app
UI/model/controller crash banner work
protocol opcode changes
intentionally crashing the MCU during automated SAFE HIL
Public API / Interface Changes
New internal firmware modules
Add two new internal modules:

CrashLog.h
CrashLog.c
Responsibilities:

read/reset-classify RCC reset flags

own retained backup-register layout

record crash/fault/watchdog-starve state

expose read-only accessors for self-test/logging

provide fault-handler-safe record functions

WatchdogSupervisor.h

WatchdogSupervisor.c

Responsibilities:

configure and refresh IWDG using direct register access
track periodic task heartbeats
record watchdog starvation into CrashLog
stop feeding IWDG on detected starvation
New internal enums / record types
In CrashLog.h, define:

CrashFaultKind

CRASH_FAULT_NONE
CRASH_FAULT_HARD
CRASH_FAULT_MEM
CRASH_FAULT_BUS
CRASH_FAULT_USAGE
CRASH_FAULT_NMI
CRASH_FAULT_STACK_OVF
CRASH_FAULT_ASSERT
CRASH_FAULT_ERROR
CRASH_FAULT_WDT_STARVE
CrashResetCause

CRASH_RESET_UNKNOWN
CRASH_RESET_POWER
CRASH_RESET_PIN
CRASH_RESET_SOFTWARE
CRASH_RESET_IWDG
CRASH_RESET_WWDG
CRASH_RESET_LOW_POWER
CrashTaskId

CRASH_TASK_NONE
CRASH_TASK_BOOT
CRASH_TASK_ORCH
CRASH_TASK_STATUS
CRASH_TASK_PRESSURE
CRASH_TASK_PREG_P
CRASH_TASK_PREG_R
New self-test IDs
Add two new SAFE self-tests:

1041
crash_record_retained_safe
1042
watchdog_supervisor_safe
No protocol format changes. These are emitted through the existing self-test result TLV path.

Architecture
1. Retained crash record
Storage choice
Use RTC backup registers directly, not HAL RTC.

Reason:

backup registers persist across system reset
available on STM32F446
no .ioc or MX_RTC_Init() work needed
safe in fault context if backup-domain access is enabled early and left enabled
Backup register ownership
Reserve a fixed layout, owned only by CrashLog.c.

Recommended layout:

BKP0: magic
BKP1: version + flags
BKP2: boot_count
BKP3: fault_count_total
BKP4: watchdog_reset_count
BKP5: last_reset_flags_raw
BKP6: last_fault_kind
BKP7: last_reset_cause
BKP8: last_task_id
BKP9: last_uptime_ms
BKP10: last_cfsr
BKP11: last_hfsr
BKP12: last_mmfar
BKP13: last_bfar
flags in BKP1:

pending bit: the current boot follows a crash or watchdog-starve event not yet marked healthy
valid bit: record initialized
Early boot init
Call CrashLog_EarlyBootInit() from main.c inside a USER CODE block immediately after HAL_Init() and before normal app init proceeds.

What it does:

enable PWR clock
enable backup-domain write access
enable RTC APB clock only as needed for backup register access
read current RCC->CSR reset flags
classify reset cause
load/initialize backup-register record
increment boot_count
increment watchdog_reset_count if reset cause is IWDG
preserve any previously recorded fault information
clear RCC reset flags after capture
Healthy-boot clear policy
Do not erase the last-crash record on boot.

Use two concepts:

last crash record: sticky until overwritten by the next crash
pending: whether the current boot is still in post-crash recovery state
pending should be cleared only after the system has been healthy for a defined grace window.

Chosen rule:

WatchdogSupervisor calls CrashLog_MarkBootHealthy() after 10 seconds of continuous healthy watchdog supervision.
That gives:

post-reset visibility after a crash
no permanent stale “pending” alarm once the device has recovered
persistent last-crash info for later inspection
2. Fault recording path
Fault handlers to update
Modify only inside USER CODE blocks in:

stm32f4xx_it.c

NMI_Handler
HardFault_Handler
MemManage_Handler
BusFault_Handler
UsageFault_Handler
freertos.c

vApplicationStackOverflowHook(...)
FreeRTOSConfig.h

update configASSERT(...) to call into CrashLog before halting
main.c

Error_Handler()
Common behavior
All of these paths should call a common crash recorder:

CrashLog_RecordFault(CrashFaultKind kind, CrashTaskId taskIdHint)
It should capture:

fault kind
task id
last_uptime_ms = HAL_GetTick()
SCB->CFSR
SCB->HFSR
SCB->MMFAR
SCB->BFAR
pending = 1
Task identity
Use a small explicit task-ID enum, not raw pointers.

Map current task name to enum using pcTaskGetName(NULL) when scheduler is running:

"Orch" -> CRASH_TASK_ORCH
"Status" -> CRASH_TASK_STATUS
"Pressure" -> CRASH_TASK_PRESSURE
"PReg" -> CRASH_TASK_PREG_P or CRASH_TASK_PREG_R cannot be disambiguated by name alone, so:
if called from watchdog starvation path, use the exact registered task ID
if called from generic fault path, use CRASH_TASK_PREG_P for single-port builds and CRASH_TASK_NONE for ambiguous dual-port fault cases unless a better mapping is available from context
StartDefaultTask loop -> CRASH_TASK_BOOT
Reset behavior after fault
Preferred behavior:

if watchdog is armed:
record crash
disable interrupts
spin forever
let IWDG reset the MCU
if watchdog is not yet armed:
record crash
call NVIC_SystemReset() as fallback
This keeps “watchdog performs the reset” once the runtime system is live, while still preventing early-boot permanent hangs.

3. Watchdog supervisor
Watchdog choice
Use IWDG, not WWDG.

Reason:

independent of main clocks
continues working through scheduler stalls and most fault hangs
simpler and more robust for “MCU unresponsive” recovery
Initialization
Do not use CubeMX MX_IWDG_Init().

Instead:

implement direct register setup in WatchdogSupervisor.c
call Watchdog_EarlyInit() from main.c in USER CODE BEGIN 2
Chosen initial constants:

kWatchdogTimeoutMs = 4000
kWatchdogServicePeriodMs = 100
kHealthyBootGraceMs = 10000
These must be file-local constants in WatchdogSupervisor.c and easy to tune.

Heartbeat model
Do not pet the watchdog from a single generic heartbeat task only.

That would miss partial system failure.

Instead:

each critical periodic task reports liveness with Watchdog_CheckIn(CrashTaskId id)
a dedicated watchdog supervisor task refreshes IWDG only if all required tasks are on time
Required monitored tasks
Monitor only tasks that are periodic even when the machine is idle:

CRASH_TASK_BOOT
from StartDefaultTask forever loop in main.c
deadline: 1000 ms
CRASH_TASK_ORCH
from Orchestrator _run() polling loop
deadline: 500 ms
CRASH_TASK_STATUS
from Comm status task
deadline: 500 ms
CRASH_TASK_PRESSURE
from PressureSensor loop
deadline: 500 ms
CRASH_TASK_PREG_P
from print regulator loop
deadline: 250 ms
CRASH_TASK_PREG_R
only when LC_PRESSURE_PORTS > 1
deadline: 250 ms
Do not require these for watchdog health:

PRNT
LED
GRP_REFR
FlashMon
LogStats
Reason:

they are event-driven or low-priority informational tasks and can legally block for long periods
Supervisor behavior
WatchdogSupervisor maintains:

enabled task mask
last-seen timestamp per task
late task ID, if any
Behavior:

Watchdog_EarlyInit() zeros supervisor state. In the default build it does not arm IWDG.
Watchdog_StartTask() creates a low-priority watchdog task once scheduler is live.
the first accepted HELLO is the normal arming point; immediate arming is available only through the explicit LC_WATCHDOG_ARM_MODE build override
critical tasks call Watchdog_EnableTask(id) once they are fully initialized; enable/disable mask transitions and the initial timestamp are one short task-context critical section
critical tasks call Watchdog_CheckIn(id) once per normal loop iteration; check-in updates only the aligned timestamp and cannot change participation
watchdog task wakes every 100 ms
if every enabled task is within deadline:
refresh IWDG
if healthy window exceeds 10 s, clear pending
if any task is late:
record CRASH_FAULT_WDT_STARVE
record late task_id
stop refreshing IWDG
remain passive until reset
No direct software reset should be used for watchdog-starve detection. Let IWDG time out naturally.

4. SAFE self-test visibility
New SAFE self-test 1041
Add after 1040 and before the FULL-profile branch in Orchestrator.cpp:

1041 crash_record_retained_safe
Exact metrics:

pending
fault
task
reset
boot
fault_ct
wdg_ct
Metric meanings:

pending: 0/1
fault: string enum
none|hard|mem|bus|usage|nmi|stkovf|assert|error|wdt
task: string enum
none|boot|orch|status|press|pregp|pregr
reset: string enum
power|pin|soft|iwdg|wwdg|lpwr|unk
boot: boot count
fault_ct: retained total crash count
wdg_ct: retained watchdog reset count
Pass rule:

pending == 0
historical fault fields do not fail this row after recovery has become healthy
the existing narrowly scoped sticky-status recovery exception remains valid while pending is set
New SAFE self-test 1042
Add immediately after 1041:

1042 watchdog_supervisor_safe
Exact metrics:

enabled
timeout_ms
req_n
live_n
late_task
Metric meanings:

enabled: 0/1
timeout_ms: configured IWDG timeout
req_n: required enabled tasks count
live_n: tasks currently on time
late_task: none|boot|orch|status|press|pregp|pregr
Pass rule:

enabled == 1
late_task == none
live_n == req_n
Self-test emitter change
Increase the self-test metrics TLV cap in Orchestrator.cpp from 112 to 160 bytes so 1041 and 1042 are not silently truncated.

This must be covered by host tests.

5. Boot log visibility
On every boot, after logger init is available, emit one concise log line from CrashLog:

Example format:

[BOOT] reset=iwdg pending=1 fault=hard task=status boot=42 cfsr=123 hfsr=1073741824 mmfar=0 bfar=0
This log line is informational and does not affect self-test pass/fail.

It should run once, after logger startup, from StartDefaultTask or immediately after MX_LOGGER_Init(...) if that location is safer.

6. File changes
New files
CrashLog.h
CrashLog.c
WatchdogSupervisor.h
WatchdogSupervisor.c
CrashLogCodec.h
CrashLogCodec.c
CrashLogCodec is the pure helper for host tests:

reset-flag classification
enum-to-string mappings
task-id mappings
optional backup-record normalization
Existing files to edit
Generated files: edit only inside USER CODE blocks

main.c
stm32f4xx_it.c
freertos.c
FreeRTOSConfig.h
Hand-written files:

Orchestrator.cpp
Comm.cpp
PressureSensor.cpp
PressureRegulator.cpp
tests_host/CMakeLists.txt
test_comm_codec.cpp
test_run_selftest_metrics.py
new host test file:
test_crash_log_codec.cpp
Implementation Steps
Add pure codec/helper layer
create CrashLogCodec.*
implement:
reset-flag classification
fault-kind string mapping
task-id string mapping
unit test this first in tests_host
Add retained crash record module
create CrashLog.*
implement backup-register layout
implement CrashLog_EarlyBootInit()
implement accessors for:
pending
last fault
last task
reset cause
counters
implement CrashLog_RecordFault(...)
implement CrashLog_MarkBootHealthy()
Add watchdog supervisor
create WatchdogSupervisor.*
direct-register IWDG init/refresh
task heartbeat tracking
late-task detection -> record CRASH_FAULT_WDT_STARVE and stop feeding
Wire early boot
in main.c
call CrashLog_EarlyBootInit() after HAL_Init()
call Watchdog_EarlyInit() in USER CODE BEGIN 2
start watchdog supervisor in StartDefaultTask
log one retained-crash summary after logger is ready
Wire task check-ins
add Watchdog_EnableTask(...) and Watchdog_CheckIn(...) in:
StartDefaultTask
Orchestrator::_run()
Comm::statusTask()
PressureSensor::taskLoop()
PressureRegulator::controlLoop() for regP
PressureRegulator::controlLoop() for regR when present
Wire fault paths
HardFault, MemManage, BusFault, UsageFault, NMI
vApplicationStackOverflowHook
configASSERT
Error_Handler
all of them record crash and then either:
wait for watchdog reset if armed
software reset fallback if not armed
Expose through SAFE self-test
add 1041 and 1042
raise metrics cap to 160
keep 1040 unchanged apart from any shared accessor reuse
Extend host/Python tests
add test_crash_log_codec.cpp
extend test_comm_codec.cpp for long 1041/1042 metrics frames
extend test_run_selftest_metrics.py to preserve new metrics keys
Test Cases And Scenarios
Host unit tests
test_crash_log_codec.cpp
IwdgResetFlagClassifiesAsIwdg
input: synthetic RCC CSR with IWDGRSTF
assert: reset cause = iwdg
PowerResetFlagsClassifyAsPower
input: POR/PDR/BOR combinations
assert: reset cause = power
FaultKindToMetricStringIsStable
input: each CrashFaultKind
assert: exact expected metric string
TaskIdToMetricStringIsStable
input: each CrashTaskId
assert: exact expected metric string
test_comm_codec.cpp
SelftestResultWithCrashRecordMetricsRoundtrips
metrics example:
pending=1;fault=hard;task=status;reset=iwdg;boot=42;fault_ct=3;wdg_ct=2
assert: frame encodes, parses, and survives roundtrip
SelftestResultWithWatchdogMetricsRoundtrips
metrics example:
enabled=1;timeout_ms=4000;req_n=5;live_n=5;late_task=none
assert: frame encodes, parses, and survives roundtrip
Python test
test_run_selftest_metrics.py
parse both metrics strings above
assert keys and values survive into JSON
Firmware / HIL scenarios
Scenario 1: Normal SAFE boot
Expected:

1041 crash_record_retained_safe passes
pending=0
fault=none
1042 watchdog_supervisor_safe passes
enabled=1
late_task=none
Scenario 2: Forced HardFault on hardware
Manual validation, not automated SAFE:

induce a deliberate fault in a temporary debug build or via debugger
allow watchdog reset
next SAFE self-test should show:
1041 pending=1
fault=hard
reset=iwdg
Scenario 3: Stack overflow
Manual validation:

deliberately shrink a task stack in a temporary debug build or create a known overflow harness
confirm:
stack overflow hook records stkovf
watchdog resets
post-reset 1041 shows fault=stkovf, reset=iwdg
Scenario 4: Watchdog starvation
Manual validation:

suspend or stall one monitored periodic task in a temporary debug build
confirm:
watchdog supervisor records fault=wdt
task=<late task>
reset cause = iwdg
Scenario 5: Normal software reset
Expected:

fault=none
reset=soft
pending=0
Acceptance Criteria
The implementation is complete when all of the following are true:

The MCU retains the last crash record across reset using backup registers.
Fault handlers, stack overflow hook, configASSERT, and Error_Handler all record a crash cause.
The watchdog is active during normal runtime and can reset the MCU if critical tasks stop progressing.
SAFE self-test includes:
1041 crash_record_retained_safe
1042 watchdog_supervisor_safe
Normal SAFE HIL passes with:
1041 pending=0
1042 enabled=1, late_task=none
Host tests cover reset-cause classification and long self-test metric framing.
No protocol opcode changes are introduced.
Generated files are modified only inside USER CODE regions.
Risks / Edge Cases
Backup registers are only retained across reset while backup power/domain remains valid. A full power loss can clear the retained record.
If a fault occurs before backup-domain access is enabled, the first very-early crash may not be fully retained. Starting CrashLog_EarlyBootInit() immediately after HAL_Init() minimizes this.
PReg task name is shared across both regulators, so watchdog starvation path must use explicit task IDs rather than raw task names.
Event-driven tasks must not be required for watchdog health or the machine will false-reset while idle.
Raising the self-test metrics cap must be paired with host frame-length coverage so future truncation regressions are caught.
Assumptions And Defaults
Initial visibility surface is SAFE self-test + logger boot line only
No live status protocol additions in this slice
Use IWDG with direct register access
Use RTC backup registers with direct register access
Watchdog timeout defaults to 4000 ms
Supervisor period defaults to 100 ms
Healthy-boot clear window defaults to 10 s
1041 and 1042 are the stable new SAFE self-test IDs
The last crash record remains sticky; pending clears after a healthy boot window
Early-boot faults before watchdog arm use software-reset fallback; after watchdog arm, the watchdog is the reset mechanism

Watchdog evidence-integrity implementation (2026-08-12):

- Source baseline: `fd20e66a`; the final implementation source is the commit that contains this record. The matching Debug artifact is `firmware/artifacts/LabCraft_firmware.bin`, 329,744 bytes, SHA-256 `AFC14C33B65EBBE424D47A4D51D365875FF1E79F5E0BC51E0719BB89F5FD0731`.
- `LC_WATCHDOG_ARM_MODE` is now a numeric preprocessor contract. The production default is `WATCHDOG_ARM_AFTER_HELLO_ACK`; unsupported values stop compilation, and the immediate mode is compile-tested as an explicit override.
- Pressure-regulator hold/start/release paths explicitly enable or disable their participant. The 5 ms regulator loop only checks in when eligible, so a stale loop cannot silently re-enable itself.
- `CrashLog_MarkBootHealthy()` clears only `PENDING`. The last fault/task, uptime, fault stage, late task, active command, raw/register values, counters, regulator context, and valid exception context remain available until a later fault replaces them or the existing retention/version/reset rules invalidate storage.
- Base fault paths clear an older incompatible extended exception context before committing the replacement record. Exception capture continues to commit its matching extended context.
- SAFE result `1041` treats `pending=0` as recovered health while continuing to emit the historical fields. An active `pending=1` record still fails except for the existing sticky-status recovery exception.
- `tools/run_selftest.py` uses a completed-frame inbox across HELLO, START-ACK, and result collection. A reset report whose frame sequence matches HELLO and whose `reset_seq32` matches the run ID is retained as nullable `startup_reset_report`; it does not populate the unexpected `reset_report` field or abort SAFE.
- Firmware attempts reset-report delivery once per MCU boot, after an accepted HELLO. A second SAFE run on the same boot is therefore expected to have `startup_reset_report: null`.

No-motion idle-soak closeout:

1. Flash the exact recorded artifact, wait at least 15 seconds without HELLO, and run SAFE.
2. Run SAFE again on the same boot; no second startup reset report is expected.
3. After GOODBYE, keep the powered MCU idle for three 30-minute intervals and run SAFE after each interval. Compare `boot`, `fault_ct`, and `wdg_ct` without commanding motion.
4. If watchdog starvation reproduces, retain the first post-reset `pending=1;fault=wdt` report and its non-`none` `wdg_late`, uptime, and stage evidence. After at least 12 seconds of healthy supervision, rerun SAFE and require `pending=0` with the same history still visible.
5. Stop and flash the pre-change artifact for a reset loop, missing HELLO after the allowed window, corrupt evidence, or unexplained counter increments.

No-motion idle-soak evidence (2026-08-12):

- Source/artifact commit: `99bb8c5866d1d00ca5dee334b813316938268d3e`;
  binary 329,744 bytes, SHA-256
  `AFC14C33B65EBBE424D47A4D51D365875FF1E79F5E0BC51E0719BB89F5FD0731`.
- Initial SAFE and the same-boot repeat both passed 28/28. The initial run
  retained the expected once-per-boot startup reset report; the repeat did not
  receive another one.
- Three powered-idle intervals of 30 minutes each were followed by independent
  SAFE runs. All three passed 28/28 with `aborted=false`, no unexpected reset
  report, `boot=112`, `fault_ct=1`, `wdg_ct=3`, `pending=0`, `fault=none`,
  `late_task=none`, and all four required watchdog participants live.
- Report SHA-256 values, in execution order:
  - `hil_reports/watchdog_evidence_99bb8c58_initial.json`:
    `5C50982A7493904E1726B519365F5407C47121B6C1C0D5A25BEA9F2F5C1BEBBD`;
  - `hil_reports/watchdog_evidence_99bb8c58_same_boot.json`:
    `6BB93FFBDA3ECB339D1A17B21A32F4445D5CFCF8E2A21823C68A7DF3F72212F6`;
  - `hil_reports/watchdog_evidence_99bb8c58_soak_1.json`:
    `2B9B4197981B150B6A2B3B7DB3E71081561EB77E6B13584653681923EE46F304`;
  - `hil_reports/watchdog_evidence_99bb8c58_soak_2.json`:
    `9E30251C9CF616C493A18166FD3773B5E21756E6CD89B3160E449225257C935C`;
  - `hil_reports/watchdog_evidence_99bb8c58_soak_3.json`:
    `E7F87D2A448EC120BD08E367FE9E6B54D71D3A1EEFE93DF04BEBFEB50760D652`.
- None of the three scheduled 30-minute SAFE observations saw a reset. This
  establishes that each sampled interval completed cleanly and verifies the
  once-per-boot host capture behavior, but the conclusion must include the
  delayed evidence below.

Delayed starvation evidence discovered at the next flash (2026-08-12):

- The third scheduled SAFE finished at `2026-08-12T22:31:00.184513Z` with
  `boot=112`, `fault_ct=1`, and `wdg_ct=3`. Before the next firmware flash, the
  MCU recorded another watchdog-starvation fault. The first SAFE after that
  flash retained it as `pending=1;fault=wdt;task=orch;wdg_late=press`, with
  `boot=116`, `fault_ct=2`, `wdg_ct=4`, `uptime_ms=5621501`, and
  `active_command=250` (`CMD_SELFTEST_START`). No motion had been commanded in
  this interval.
- Result `1041` passed only through the existing sticky-status recovery
  exception while the record was pending. A follow-up SAFE more than 12 seconds
  into healthy supervision reported `pending=0` while preserving the same
  historical fault and counters. A second same-boot SAFE kept those values and
  received no new startup or unexpected reset report.
- The evidence-integrity objective is therefore verified: the fault survives
  recovery and the host captures it. The idle-soak reliability objective is not
  clean; starvation did reproduce after the last scheduled observation.
- `active_command=250` and `wdg_late=press` localize the event to pressure-sensor
  participation while a self-test command owned the orchestrator. The current
  code runs diagnostics in the priority-2 orchestrator and emits result frames
  with synchronous UART transmission, while the pressure-sensor task is
  priority 1 with a 250 ms deadline. This is a strong scheduling-starvation
  hypothesis, not yet a proven root cause.
- The planned selector `2075` motion was not started. The diagnostic artifact
  was rolled back to commit `99bb8c58`'s 329,744-byte binary with SHA-256
  `AFC14C33B65EBBE424D47A4D51D365875FF1E79F5E0BC51E0719BB89F5FD0731`;
  its post-flash SAFE passed 28/28 with unchanged fault/watchdog counters.
- Additional report SHA-256 values, in execution order:
  - `hil_reports/coord_xy_single_irq_3182a287_pre_safe.json`:
    `CC4CC0924490B5194ACD5025DF96C759C11F4A894DBD854593C756882A24DC83`;
  - `hil_reports/coord_xy_single_irq_3182a287_recovery_safe.json`:
    `5D458382B8F60C864A7E4A504CC19CD261D55E8497618BD2E1B39DCE86B56140`;
  - `hil_reports/coord_xy_single_irq_3182a287_stability_safe.json`:
    `662BFEF90E7852C0703D60F0E81B23D3963008CA982C5AF61442A3D2B7EB2A46`;
  - `hil_reports/coord_xy_single_irq_abort_rollback_99bb8c58_safe.json`:
    `954BA67A6B159A0E20C7BCE315BE907A3955536B78EECEB676F3275D5097B690`.

## Self-test scheduling attribution implementation

The follow-up image retains 20 ms I2C operation timeouts and ordinary task
priorities. During each cooperative result/progress transmission and its
one-tick delay, an RAII guard temporarily lowers only the emitting orchestrator
task to the pressure task's priority. Tick-level time slicing lets pressure
interrupt polling UART output and finish an in-progress I2C operation or
recovery without also time-slicing the emitter against the idle task; the
original priority is restored after every frame. Cooperative self-test frames
use a local 50 ms UART timeout because their intentional time slicing can
exceed the ordinary 25 ms frame timeout; normal communication and selector
`1039` retain 25 ms. Send failure latches incomplete scheduler evidence.
Diagnostic selector `1039` retains the original
high-priority/no-yield behavior; selector `1038` explicitly selects the default
cooperative behavior. Both run the same no-motion SAFE inventory.

`PressureSensorWatchdogTelemetry` records loop-start gaps and phases for delay,
mux select, sensor read, both recovery paths, and sample processing. A pressure
watchdog fault copies this data into a versioned/checksummed `.noinit` context
before the normal 20-register crash record is committed. The reset report and
backup-domain version remain unchanged. SAFE rows `1044` and `1043` expose the
retained context and live scheduler window; prior versioned FULL/focused
qualification manifests remain unchanged.

The follow-up lightweight I2C attribution adds the last failed-read HAL status
(`h`: 1 error, 2 busy, 3 timeout), failed receive duration `r`, active or
last completed read-recovery wall duration `x`, and `HAL_I2C_GetError()` mask
`e` to the live and retained snapshots. The retained pressure-context version
is 3. Error-mask capture occurs only after a failed receive and before recovery
can reset the peripheral state. Recovery continues to
request exactly 20 one-tick delays; comparing `x` with 20 ticks separates the
known delay budget from combined scheduler/GPIO/HAL stretch without enabling
continuous RTOS tracing. Successful reads pay only two tick reads and one
subtraction. All telemetry-state writes, recovery timing, and retained-context
updates remain on failure, diagnostic snapshot, or fault paths.

The no-motion HIL order is `1039-1038, 1038-1039, 1039-1038`, with at least six
seconds between arms, followed by a default SAFE after 12 seconds and one
30-minute idle soak. Cooperative arms must keep pressure gap and age at or
below 125 ms with no I2C error/recovery delta or watchdog increment. The
pressure participant deadline is 500 ms so a complete recovery retains ample
margin; the 125 ms qualification gates and all other watchdog deadlines remain
unchanged.

The matching Debug artifact is 339,640 bytes with SHA-256
`5A944627C3A5352F3AA1A259F86D0D202996A7FA5C78FD486CFDCB7D6BEE03D5`.
It leaves 53,576 bytes in the 384 KiB application partition. The globally
enabled `INCLUDE_uxTaskGetStackHighWaterMark` option remains off. Instead, the
existing trace facility scans only the pressure task once when a diagnostic or
fault snapshot is requested; there is no per-loop stack scan. Unknown headroom
fails result evidence closed. The outer
diagnostic runner's static frame is 3,512 bytes, below the retained
4,096-byte investigation ceiling.

### Lightweight I2C attribution HIL evidence (2026-08-12 local)

Commit `5bae8edf`'s 338,768-byte artifact, SHA-256
`220B93804445B99F1E116B9FA41CA87794C711B8B135BA7EAFE53AD4EA2E7906`,
was flashed once and exercised without motion, pressure targets, valves, or
heaters. One selector-`1038` cooperative SAFE and its delayed-reset bracket
both passed 30/30 with all four watchdog participants live, complete 29/29
cooperative yields, passing host cadence, no in-run reset, and unchanged
`boot=128;fault_ct=4;wdg_ct=6` counters.

Both runs reproduced the same pressure read failure. The focused arm reported
`pg=39;pa=218;ph=5;pha=180;se=0;re=1;bc=1;h=1;r=25;x=180;hw=169;sf=0`;
the bracket reported the same `h=1;r=25;x=180` with `pg=28`, `pa=218`, and
`hw=167`. Thus the STM32 HAL call returned the generic `HAL_ERROR` after 25 ms
and the pressure task was still in read recovery at 180 ms. The receive API
maps several internal causes, including its timeout helpers, to `HAL_ERROR`,
so `h=1` alone cannot distinguish acknowledge failure, timeout, or another
I2C error bit. The 25 ms elapsed call versus the configured 20 ms timeout is
consistent with the lower-priority polling call being preempted, but is not
standalone proof of the internal HAL error cause.

The cooperative manifest fails intentionally on `pa`, `re`, `bc`, `h`, `r`,
and `x`; its scheduling-frame, stack, status-cadence, and watchdog-integrity
gates pass. Report evidence:

- `hil_reports/i2c_5bae8edf_cooperative_safe.json`, SHA-256
  `2478DAE3980F84A604B34897AD09E1EBED9AE9A1219E39AEE922618054505B03`;
- `hil_reports/i2c_5bae8edf_post_safe.json`, SHA-256
  `020CD7695A4FF1F77A5995F70609BF7D174F712F9E6C965EF8A5A4031893AB1C`;
- normalized report
  `hil_reports/qualification_i2c_5bae8edf/LC-001/20260813T004639Z/report.json`,
  SHA-256
  `32F573E15E3789AA00EE63553A058D0692886FECEFF58A05DBF1C8A5D798CF68`.

The long idle soak remains deferred. This diagnostic image copies
`HAL_I2C_GetError()` only inside the existing failed-read branch, adding no
successful-read work and distinguishing timeout, acknowledge, bus, and
arbitration error bits. Its short no-motion HIL result is recorded separately
after the matching artifact is built and flashed.

### HAL I2C error-mask HIL evidence (2026-08-12 local)

Commit `bb599263`'s 338,968-byte artifact, SHA-256
`A90B83E35358C1924745BA7F050B014D02B2B406BA318E3D7CF9A7108919711B`,
was flashed once and exercised without motion, pressure targets, valves, or
heaters. The selector-`1038` cooperative SAFE and its delayed default-SAFE
bracket both passed 30/30. Both reported
`pg=28;pa=218;ph=5;pha=180;re=1;bc=1;h=1;r=25;x=180;e=32;sf=0`.
The bracket retained `boot=130;fault_ct=4;wdg_ct=6`, so the test produced no
new reset or watchdog fault. All four participants were live and host cadence
and progress-watchdog checks passed.

`e=32` is `HAL_I2C_ERROR_TIMEOUT`; neither run set acknowledge-failure, bus-
error, or arbitration-loss bits. Combined with the 25 ms observed duration of
the configured 20 ms polling receive and the repeatable 180 ms recovery stretch
during higher-priority result emission, this strongly supports scheduler
preemption expiring the HAL polling timeout. It is not evidence of a sensor
NACK or a physical bus fault in these runs. The one-tick cooperative delay is
therefore insufficient to guarantee that the lower-priority pressure task can
finish an in-progress blocking receive before result emission resumes.

The strict cooperative manifest fails as designed on `pa`, `re`, `bc`, `h`,
`r`, `x`, and `e`; evidence integrity, frame/yield counts, stack evidence,
status cadence, and watchdog counters pass. Reports:

- `hil_reports/i2c_error_bb599263_cooperative_safe.json`, SHA-256
  `C0A86BC2958F18585A6B25FE2A6DE6635A45E361D81494ADCE963AEBC4071DD3`;
- `hil_reports/i2c_error_bb599263_post_safe.json`, SHA-256
  `C815C552604CA71686B18C054BE6BF5EB234A9C4EA5A764B3AE72BE0D5A71EE2`;
- normalized report
  `hil_reports/qualification_i2c_error_bb599263/LC-001/20260813T010139Z/report.json`,
  SHA-256
  `4A5FFFEC8C987BBDC49B2D15707CF4F2CF656FEFB1DC8EC5DA583C4E105DEB9A`.

The long soak remains deferred. The next image combines priority-aware
cooperative result pacing with a 500 ms pressure-participant deadline. The
deadline is recovery containment, while the unchanged 125 ms host gates still
reject degraded normal pressure scheduling. Further physical motion HIL waits
for the short no-motion check to show no I2C failure/recovery delta.

Messages from past attempts:
I’ve implemented the crash-log/watchdog slice and the remaining issue is target boot reachability during SAFE HIL. I’m checking the latest report and the startup paths that can prevent HELLO_ACK, then I’ll make the smallest fix and rerun validation.

The local lane is green; the blocker is still that the flashed target never answers HELLO. I’m checking the actual latest HIL report paths and the boot/init code around crash-log and watchdog startup to isolate what is killing comms before the session starts.

I have the likely fault surface narrowed to startup, not the self-test path itself: the board never reaches a usable comm session after flash. I’m inspecting the watchdog task creation and the earliest crash-log paths now, because either one can produce a reset loop before HELLO_ACK.

The failure pattern matches an early reset loop more than a comm bug. The highest-probability cause is stack pressure in the default startup task after adding the boot crash log, so I’m making that path non-stack-heavy and giving the startup task explicit headroom before rerunning the full lane.

I’ve reduced startup stack pressure in the only new boot-time formatting path and increased the default task stack to remove a likely reset-loop source. I’m rerunning the required local lane first, then the SAFE HIL lane on the Pi.

The current failure is consistent with lost startup frames rather than a dead firmware path: HELLO is sent once with a 2 s window, and if comm comes up after that, both HELLO and SELFTEST_START are simply missed. I’m fixing the host self-test runner to retry the hello handshake until the port is actually ready, then I’ll rerun the SAFE HIL lane.

The firmware side is now locally stable, and the remaining failure mode is the Pi-side runner assuming comm is ready too early. I’m making the hello handshake retry until the target is actually alive, with a unit test that proves delayed bring-up still reaches self-test.

The startup path no longer looks like the primary blocker. I’ve made the Pi runner tolerant of delayed UART bring-up and added a regression test for repeated HELLO sends, then I’m rerunning the Python tests and the SAFE HIL lane.

The runner fix proved the board still never becomes responsive, so this is back on the firmware startup path. The next highest-risk startup change is touching the backup domain before the clocks are configured; I’m moving crash-log initialization to just after SystemClock_Config() and rerunning the SAFE lane.

The target is still not answering at all after flash, so the remaining issue is not the host handshake. I’m checking for startup-time faults in the new crash-log/watchdog code path itself now, especially anything that can execute before comm comes up or recursively fault inside a fault/assert path.

The empty report means the MCU never produced a single self-test frame, but that still doesn’t prove a crash loop; it only proves the session never started. I’m extending the runner so HELLO retries for a much larger portion of the SAFE timeout and only then gives up, which will tell us whether this is late bring-up or a dead startup path.

The remaining high-probability startup failure is still task-stack exhaustion before comm is armed. The default task does a lot of hardware bring-up before MX_COMM_Init(), and the watchdog task is new, so I’m giving both explicit headroom and rerunning the SAFE lane.
