Troubleshooting Plan: Restore HELLO_ACK While Keeping Crash Retention + Watchdog
Summary
The failure path is now clear enough to troubleshoot systematically.

Current handshake call path:

Pi self-test runner: tools/run_selftest.py
UART RX ISR: Comm.cpp
Command decode and immediate HELLO handling: Orchestrator.cpp
ACK transmit: Comm.cpp
Current boot path:

reset -> main.c
CrashLog_EarlyBootInit()
peripheral init
StartDefaultTask()
MX_COMM_Init()
Watchdog_StartTask()
CrashLog_LogBootSummary()
Most likely root causes, in order:

A startup reset loop before or just after MX_COMM_Init(), most likely from the newly armed watchdog.
A startup crash caused by newly enabled stack-overflow checking or assert/fault hooks.
A fault or hang in early crash-log backup-domain setup.
Fault-recorder recursion or unsafe RTOS calls from a fault context.
Files To Touch
Primary firmware files:

main.c
WatchdogSupervisor.c
CrashLog.c
freertos.c
FreeRTOSConfig.h
Orchestrator.cpp
Comm.cpp
Validation/tests:

firmware/tests_host/tests/test_crash_log_codec.cpp
firmware/tests_host/tests/test_comm_codec.cpp
tests/test_run_selftest_metrics.py
Interfaces / API Changes
No protocol changes.

Add temporary internal-only troubleshooting controls, kept local to firmware:

LC_CRASHLOG_ENABLE
LC_CRASHLOG_EARLY_BOOT_ENABLE
LC_CRASHLOG_FAULT_HOOKS_ENABLE
LC_WATCHDOG_ENABLE
LC_WATCHDOG_ARM_MODE
Default LC_WATCHDOG_ARM_MODE for the fix:

ARM_AFTER_HELLO_ACK
This is the key implementation decision: do not arm IWDG during early startup. Arm it only after comm is proven alive by a successful HELLO exchange.

Also split crash recording into two paths:

normal-context recorder: allowed to inspect RTOS task identity
fault-context recorder: no RTOS calls, no logger calls, no dynamic behavior
Plan
Add boot-stage breadcrumbs before changing behavior.
Define a tiny retained or RAM breadcrumb enum and update it at these exact checkpoints: after HAL_Init, after CrashLog_EarlyBootInit, after MX_ORCH_Init, after MX_LOGGER_Init, after MX_COMM_Init, after Watchdog_StartTask, on HELLO receive, on HELLO_ACK send.
Emit the breadcrumb in the existing boot log line and expose it in self-test metric 1041 as an extra key such as boot_stage.

Add compile-time isolation switches and reproduce in a controlled ladder.
Build and test these four firmware states in order:
crashlog=off watchdog=off
crashlog=on watchdog=off
crashlog=on watchdog=on arm_after_hello
crashlog=on watchdog=on full_monitoring
Stop as soon as HELLO_ACK fails; that state identifies the responsible subsystem.

Fix watchdog bring-up so it cannot kill the board before communications are alive.
Change watchdog behavior to create the supervisor task early if needed, but do not start IWDG counting until HELLO has been acknowledged.
After CMD_HELLO is processed and CMD_HELLO_ACK is transmitted successfully, arm IWDG and start the healthy-boot grace timer.
Keep task registration passive before arming; deadlines should not be evaluated until watchdog mode is active.

Make crash logging safe in early boot and in fault context.
Keep CrashLog_EarlyBootInit() minimal: capture reset flags, initialize storage if needed, and return.
Move anything non-essential out of early boot.
Introduce a fault-safe recorder that never calls FreeRTOS APIs, never looks up task names, and only stores raw registers plus an optional caller-provided task ID.
Use that fault-safe path from HardFault, MemManage, BusFault, UsageFault, NMI, configASSERT, Error_Handler, and stack-overflow hook.

Treat stack-overflow detection as a likely regression until disproven.
Keep configCHECK_FOR_STACK_OVERFLOW=2, but do not assume current task stacks are sufficient.
Capture the offending task name in vApplicationStackOverflowHook.
If the failing configuration points here, increase only the specific overflowing task stack sizes first, starting with Status, Pressure, logger-adjacent tasks, and any task touched by new logging or metric formatting.

Add minimal observability for the handshake path itself.
Log or breadcrumb these exact events: HELLO_RX, HELLO_DECODED, HELLO_ACK_QUEUED, HELLO_ACK_SENT.
If UART1 logging is unavailable on the target, mirror the same stages via a spare GPIO pulse pattern or LED pulse count. The plan assumes UART1 is preferred and GPIO pulse fallback is only used if logs are inaccessible.

Re-enable the full retained-crash/watchdog design in the final safe order.
Order:
CrashLog storage
fault-safe fault hooks
stack-overflow hook
watchdog armed after HELLO_ACK
task monitoring deadlines
healthy-boot clear after 10 s
Do not return to watchdog arming in StartDefaultTask() unless hardware evidence shows boot remains stable with all tasks live.

Lock the fix with tests and hardware validation.
Keep existing host tests.
Add host coverage for the new boot-stage/metric field if exposed through self-test.
Validate first with local firmware checks, then with Pi HIL, then with one manual induced-fault run and one manual watchdog-starve run.

Test Cases And Scenarios
Host-level:

CrashLog_ClassifyResetFlags remains stable.
Long self-test metric frames still encode and parse.
New boot_stage metric, if added, survives Python parsing.
Hardware troubleshooting ladder:

crashlog=off watchdog=off: board must send HELLO_ACK.
crashlog=on watchdog=off: board must still send HELLO_ACK.
crashlog=on watchdog=on arm_after_hello: board must send HELLO_ACK, then self-test passes.
crashlog=on watchdog=on full_monitoring: board must send HELLO_ACK and remain stable for >10 s.
Final hardware acceptance:

normal boot: HELLO_ACK received, 1041 pending=0, 1042 enabled=1
forced assert or hard fault: reboot occurs, retained crash record shows expected fault
watchdog starvation: reboot occurs, retained crash record shows fault=wdt and correct late task
Validation Commands
Required when implementing:

powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_checks.ps1 -Config Debug
powershell -ExecutionPolicy Bypass -File firmware/scripts/run_fw_hil_windows.ps1 -PiHost 192.168.0.29
Recommended targeted checks while iterating:

host tests for tests_host
python -m pytest -q tests/test_run_selftest_metrics.py tests/test_run_selftest_goodbye.py
Risks / Edge Cases
The current fault recorder calls RTOS APIs from paths that may execute with a corrupted stack or scheduler state.
Enabling stack-overflow checking can expose latent stack shortages that existed before this feature.
Arming IWDG before comm readiness is too aggressive for this firmware; a single slow-start task can prevent any HELLO exchange.
Early backup-domain access is lower risk than protocol changes, but still belongs behind minimal early-init logic.
Rollback Plan
If troubleshooting gets blocked:

first rollback only watchdog arming timing
if still failing, temporarily disable fault hooks while keeping passive crash-log storage
if still failing, disable early crash-log init and return to the last known good boot/HELLO path
do not remove protocol or comm changes unrelated to this feature
Assumptions And Defaults
No protocol opcode or payload changes will be made.
UART1 boot logging is available; if not, GPIO pulse breadcrumbs are the fallback.
The preferred permanent design is retained crash logging plus watchdog, but watchdog arming moves to post-HELLO.
The immediate goal is not “full crash feature coverage”; it is “stable boot and HELLO handshake first, then re-enable protections incrementally.”