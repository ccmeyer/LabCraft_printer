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
deadline: 250 ms
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

Watchdog_EarlyInit() starts IWDG and zeros supervisor state.
Watchdog_StartTask() creates a low-priority watchdog task once scheduler is live.
critical tasks call Watchdog_EnableTask(id) once they are fully initialized
critical tasks call Watchdog_CheckIn(id) once per normal loop iteration
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

for a normal healthy SAFE boot:
pending == 0
fault == none
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