# Virtual Workflow Verification Plan

> Living implementation tracker for adding hardware-free workflow, UI
> responsiveness, and performance-regression verification to the LabCraft
> printer application.
>
> Update this document when a slice starts, when its scope changes, and when its
> validation finishes. Do not mark a slice `verified` without recording the
> commands, results, and artifact paths that support that status.

## Purpose

The current automated test suite provides strong functional regression
coverage, but it does not run a representative print workflow through the real
Qt event loop under sustained load. As a result, code can remain functionally
correct while introducing operator-visible latency, main-thread blocking,
growing per-well costs, or command-queue starvation.

This plan adds a layered verification loop that Codex, developers, CI, and the
Raspberry Pi can run without connecting to or actuating printer hardware.

The first target is the regression observed after durable execution-plan
checkpointing was added:

- pytest verified checkpoint ordering and recovery behavior;
- all functional tests passed;
- a real 96-well print exposed significant UI lag;
- historical audit data indicated that physical array throughput remained
  comparable while the Qt event loop became intermittently unresponsive.

The plan must therefore prove both:

1. the workflow remains functionally correct; and
2. the application remains responsive while performing realistic repeated
   work.

## Desired Outcome

At completion, the repository should provide:

- deterministic microbenchmarks for execution persistence and other
  performance-sensitive host operations;
- a hardware-free simulated machine that cannot connect to physical devices;
- scripted scenarios that launch the real Qt application offscreen or visibly;
- a representative print-array workflow using real Controller, Model,
  persistence, signals, widgets, and command-completion callbacks;
- event-loop latency, callback duration, queue, CPU, memory, and I/O metrics;
- machine-readable reports, diagnostic artifacts, and regression comparison;
- a Windows software-in-the-loop lane for normal development;
- a Raspberry Pi software-in-the-loop lane for target CPU/storage validation;
- a later protocol-level virtual MCU lane for serial and fault-injection
  coverage;
- documented rules telling Codex which verification lanes are required for a
  change.

## Current Call Path

Real print-array path:

`WellPlateWidget -> Controller.print_array -> Controller array lookahead -> Machine command queue -> serial protocol -> firmware Orchestrator -> Printer/motion handlers -> status command counters -> Machine CommandQueue completion -> Controller._handle_array_well_complete -> well/progress/execution checkpoint updates -> Qt repaint and next lookahead command`

Initial software-in-the-loop path:

`QTest/scenario driver -> real MainWindow -> real Controller -> real Model and execution files -> SimulatedMachine command queue/status -> real completion callback -> Qt UI updates -> metrics/report`

Later protocol-simulation path:

`QTest/scenario driver -> real MainWindow/Controller/Model/Machine -> in-memory serial transport -> VirtualMCU frame decoder and command state machine -> ACK/status frames -> real SerialReader -> real completion callback -> metrics/report`

Initial slices do not change the firmware handler or device protocol.

## Why Existing Tests Did Not Catch The Regression

Existing tests generally prove one or more of the following:

- a checkpoint operation produces the correct file;
- intent/progress operations occur in the required safety order;
- a Controller branch makes the expected calls;
- a widget reaches the correct state;
- protocol codecs accept and reject expected vectors.

They do not currently combine:

- a real `QApplication` event loop;
- the real `MainWindow` and 384-well widget tree;
- 96-384 consecutive well completions;
- real atomic writes and `fsync`;
- growth of completed execution intents over multiple arrays;
- realistic command completion cadence and lookahead replenishment;
- event-loop jitter and per-phase timing measurements.

The production UI freeze watchdog is intentionally passive and currently aimed
at multi-second freezes. The verification loop needs a higher-frequency,
test-owned latency probe capable of detecting operator-visible stalls in the
tens or hundreds of milliseconds.

## Status Legend

| Status | Meaning |
| --- | --- |
| `not_started` | No implementation work has begun |
| `planned` | Scope and gates are documented, but implementation has not begun |
| `in_progress` | Files, tests, or tools are being changed |
| `blocked` | Work cannot continue without a decision, prerequisite, or external result |
| `implemented` | The slice is written and focused validation passed |
| `verified` | Full required validation, artifacts, and handoff checks passed |
| `deferred` | Intentionally postponed and not required for the current milestone |

## Global Safety Rules

- Simulation mode must never open a physical serial port, GPIO line, camera,
  balance, or firmware-update path.
- Simulation mode must be explicit in code and reports. If it has a visible UI,
  it must show a persistent `SIMULATION - NO HARDWARE` indicator.
- Do not reuse a normal production hardware profile with a few methods patched
  at runtime. Use an explicit construction path whose dependencies are safe by
  design.
- Scenario data and generated execution artifacts must be written only to a
  temporary run directory or an explicitly selected report directory.
- Do not alter firmware opcodes, frame layouts, command semantics, motion,
  pressure, or timing behavior in the initial simulation slices.
- A protocol-level virtual MCU must consume the existing protocol contract; it
  must not create a second informal protocol.
- Performance work must not weaken durable intent ordering or remove `fsync`
  solely to improve a benchmark.
- Never allow a performance threshold to encourage unsafe command reordering.
- Any future firmware change must follow `firmware/AGENTS.md` and its required
  validation/HIL gates.

## Global Proceed Gate

Before starting any slice:

- update its status to `in_progress`;
- add a dated entry to the Progress Log;
- restate the affected call path;
- write a plan of no more than eight implementation steps;
- list files to touch before editing;
- identify focused and full validation commands;
- identify new safety risks and rollback steps;
- confirm unrelated dirty-worktree files will remain untouched.

Before proceeding to the next slice:

- run the slice's focused tests;
- run the required regression lane;
- inspect the generated report rather than checking only the exit code;
- record commands, results, artifacts, and important observations here;
- update decisions or thresholds if evidence changed them;
- commit the slice independently when the user requests commits.

## Slice Status Summary

| Slice | Status | Scope | Required gate before next slice |
| --- | --- | --- | --- |
| 0. Baseline, report contract, and safety boundaries | `verified` | Characterize current behavior and freeze interfaces | Reproducible baseline artifacts recorded |
| 1. Metrics library and Qt event-loop probe | `verified` | Deterministic measurement and JSON reporting | Probe detects injected stalls without hardware |
| 2. Execution persistence microbenchmark | `verified` | Repeated progress/resume/checkpoint workload | 96/384-well cost and growth reported |
| 3. Safe application construction seam | `verified` | Build real app components with explicit safe dependencies | App launches with no hardware access |
| 4. In-process simulated machine | `verified` | Command lifecycle and machine-state simulation | Controller command sequences complete deterministically |
| 5. Real-UI print-array scenario | `verified` | End-to-end Qt print workflow with real persistence | 96-well scenario completes with responsiveness report |
| 6. Regression comparison and performance gates | `not_started` | Baselines, budgets, comparison, exit policy | Stable candidate/baseline classification |
| 7. Target-Pi software-in-the-loop lane | `not_started` | Run the same scenario on Pi CPU/storage | Pi report produced without MCU/hardware setup |
| 8. Protocol-level virtual MCU and fault injection | `deferred` | Real framing, ACK/status, transport faults | Protocol scenarios pass without changing protocol |
| 9. Expanded workflow scenario catalog | `deferred` | Stop/resume, reset, loading, calibration adapters | Selected workflows produce trustworthy artifacts |
| 10. Codex skill, AGENTS rules, and automation | `not_started` | Make lane selection repeatable and enforceable | Codex/human instructions invoke repository tooling |

## Verification Layers

| Layer | Typical duration | Primary purpose | Required hardware |
| --- | ---: | --- | --- |
| Unit/functional pytest | seconds to minutes | Logic, state transitions, error handling | None |
| Host microbenchmark | seconds | Repeated persistence and algorithmic cost | None |
| UI software-in-the-loop | under a few minutes per scenario | Event-loop responsiveness and composed workflow | None |
| Pi software-in-the-loop | under a few minutes per scenario | Target CPU and filesystem characteristics | Pi only; MCU disconnected/not used |
| Protocol virtual MCU | minutes | Framing, ACK/status, queue, and fault behavior | None |
| Real HIL | minutes to longer fixture runs | Physical devices and timing | Prepared machine |

No single layer is allowed to claim what another layer proves. In particular:

- a passing UI simulation does not prove physical motion, pressure, droplet, or
  camera behavior;
- a passing HIL self-test does not prove that every app workflow stays
  responsive;
- a passing unit suite does not prove sustained-load performance.

## Metrics And Report Contract

Every performance or scenario run should write a canonical JSON report. CSV may
be added for longitudinal comparison, but JSON remains authoritative.

Required report identity:

- schema name and version;
- scenario and workload version;
- git commit and dirty-worktree flag;
- operating system, architecture, Python, Qt, and dependency versions;
- CPU identifier when available;
- run mode: Windows SIL, Pi SIL, protocol simulation, or HIL;
- simulation speed and timing policy;
- warm-up count and measured iteration count;
- start/end UTC timestamps and monotonic duration;
- pass, warning, or fail classification with reasons.

Required responsiveness metrics:

- Qt heartbeat interval;
- event-loop delay p50, p95, p99, and maximum;
- counts above provisional 25, 50, 100, 250, and 1000 ms bands;
- longest measured main-thread callback;
- main-thread stack or phase name for large stalls when available;
- time spent rebuilding/repainting the well plate;
- time spent in progress and execution-checkpoint phases.

Required workflow/queue metrics:

- wells planned and completed;
- commands queued, sent, accepted, executing, completed, and canceled;
- command queue depth over time;
- minimum lookahead depth during active printing;
- completed-command to next-command gap;
- total scenario duration;
- simulated device time versus host overhead;
- first-quartile and last-quartile per-well latency;
- slope/growth indicators for persistence operations.

Required resource and persistence metrics where supported:

- process CPU time;
- peak resident memory;
- bytes read and written;
- progress and resume file sizes;
- intent count;
- atomic-write and `fsync` duration distributions.

Required failure artifacts:

- canonical JSON report even when the scenario aborts;
- event timeline;
- command lifecycle summary;
- captured Python thread stacks for large stalls;
- final execution/progress/checkpoint validation result;
- screenshots at named workflow milestones when the UI exists;
- concise text summary suitable for Codex and human review.

## Threshold Policy

Thresholds must mature through three states:

| Maturity | Behavior |
| --- | --- |
| `informational` | Collect and compare metrics without failing the run |
| `candidate` | Emit warnings using provisional budgets |
| `acceptance` | Fail the verification lane using validated budgets |

Initial work must not guess strict cross-platform limits. Slice 0 and Slice 1
collect repeatability data first.

Provisional values for characterization, not acceptance:

- report every event-loop delay above 50 ms;
- highlight every event-loop delay above 100 ms;
- capture a stack/phase artifact for delays above 250 ms when practical;
- warn when candidate p95 or p99 latency is more than 25% slower than a
  same-host baseline and exceeds an absolute noise floor;
- warn when last-quartile checkpoint latency materially exceeds first-quartile
  latency.

Final gates should combine:

1. an absolute operator-responsiveness budget; and
2. a relative same-host regression budget.

This prevents a very fast baseline from producing noisy failures and prevents a
historically slow baseline from legitimizing unacceptable UI behavior.

## Proposed Repository Layout

Names remain provisional until each slice begins.

```text
FreeRTOS-interface/
  simulation/
    __init__.py
    machine.py
    state.py
    transport.py                 # later protocol-level slice
    virtual_mcu.py               # later protocol-level slice
tools/
  run_virtual_workflow.py
  virtual_workflows/
    metrics.py
    reports.py
    scenarios.py
    compare.py
tests/
  performance/
    test_execution_persistence_benchmark.py
    baselines/
  system/
    test_virtual_print_array_workflow.py
    fixtures/
verification_reports/            # generated and ignored
docs/
  virtual_workflow_verification_plan.md
```

Reusable runtime simulation belongs with application code only if it is a
supported application construction mode. Test-only drivers, fixtures, metric
analysis, and comparison logic should remain under `tools/` or `tests/`.

## Slice 0: Baseline, Report Contract, And Safety Boundaries

Status: `verified`

Goal:

Record the current performance and define stable interfaces before changing app
construction or simulation behavior.

Scope:

- define the first scenario workload precisely;
- capture current execution persistence timing without claiming acceptance;
- confirm which Qt tests use real PySide6 versus stubs;
- define report schema version 1;
- define simulation safety invariants;
- choose generated-report and tracked-baseline locations;
- record current focused/full test results.

Initial workload:

- workload ID `execution_persistence_v1`;
- `shallow-384_well_plate`, with 16 rows and 24 columns;
- the first 96 wells in deterministic serpentine order, covering rows A-D;
- four deterministic droplet-mode stocks, with one target dispense per stock
  per well;
- four stock-array passes of 96 wells each, for 384 lifecycle completions;
- durable execution plan active;
- real progress and resume file writes in a fresh temporary experiment
  directory for every run;
- one unpaced warm-up run and five unpaced measured runs, isolating host
  persistence cost;
- the later SIL scenario will use a monotonic 50 ms completion schedule,
  independent of host completion time, and the Controller's normal two-well
  lookahead;
- no cameras, GPIO, balance, serial port, MCU, application window, Controller,
  or production machine object.

Files in this slice:

- `docs/virtual_workflow_verification_plan.md`
- `docs/virtual_workflow_report_schema.md`
- `tools/virtual_workflows/__init__.py`
- `tools/virtual_workflows/report.py`
- `tools/characterize_execution_persistence.py`
- `tests/test_execution_persistence_characterization.py`
- `.gitignore`
- `README.md`

Focused validation:

- existing execution-plan, resume, Controller array, UI array, and watchdog
  tests;
- current full Python suite;
- repeated baseline runs sufficient to estimate noise.

Proceed criteria:

- workload and report schema are unambiguous;
- no baseline command can connect to physical hardware;
- current results and known limitations are recorded below;
- generated artifacts are not accidentally tracked.

Rollback:

- documentation and ignored report-directory changes can be reverted without
  runtime impact.

Completion record:

- Date: 2026-07-23.
- Files changed:
  - `.gitignore`
  - `README.md`
  - `docs/virtual_workflow_report_schema.md`
  - `docs/virtual_workflow_verification_plan.md`
  - `tests/test_execution_persistence_characterization.py`
  - `tools/characterize_execution_persistence.py`
  - `tools/virtual_workflows/__init__.py`
  - `tools/virtual_workflows/report.py`
- Report contract:
  - schema `labcraft.virtual_workflow_report`, version 1;
  - strict top-level envelope with explicit metric availability;
  - classifications remain `informational` in Slice 0;
  - atomic validated JSON plus a concise text summary.
- Safety evidence:
  - the runner uses `Model.__new__`, `ExperimentModel`, and `WellPlate`;
  - it does not instantiate App, Controller, Machine_FreeRTOS, transport,
    serial, GPIO, cameras, balance, MCU, or firmware update;
  - static forbidden-import and dynamic constructor-failure tests pass;
  - real PySide6 6.7.1 and Qt 6.7.1 were recorded, but no Qt event loop or
    real widget was exercised.
- Final baseline artifact:
  - `verification_reports/virtual_workflows/execution_persistence_v1/20260723T171247948161Z_acd0c0b3461f/report.json`
  - classification `pass`, threshold maturity `informational`;
  - one warm-up plus five measured 384-completion workloads;
  - all runs ended with a clean 384-intent checkpoint, exact target/progress
    equality, increasing unique command sequences, and a valid authoritative
    bundle;
  - five-run mean duration 106,301.275 ms, maximum 108,004.822 ms, and
    coefficient of variation 0.0173;
  - per-completion mean 275.593 ms, p50 273.993 ms, p95 361.991 ms, p99
    407.482 ms, and maximum 490.054 ms;
  - mean phase costs: begin intent 44.726 ms, attach sequence 48.159 ms,
    progress write 12.165 ms, and complete intent plus authoritative reload
    170.319 ms;
  - last-quartile mean was 1.0818 times the first-quartile mean.
- Validation:
  - `.\env\Scripts\python.exe -m pytest -q tests\test_execution_persistence_characterization.py tests\test_execution_plan.py tests\test_execution_resume_store.py tests\test_authoritative_execution_load.py tests\test_execution_lifecycle_hardening.py tests\test_initial_execution_plan.py tests\test_initial_execution_plan_integration.py tests\test_controller_print_guards.py tests\test_view_array_controls.py tests\test_app_freeze_watchdog.py`
    passed 226 tests in 16.34 seconds;
  - `.\env\Scripts\python.exe tools\characterize_execution_persistence.py`
    completed successfully and wrote the artifact above;
  - `git check-ignore` confirmed the generated report is ignored by
    `.gitignore`;
  - `.\env\Scripts\python.exe -m pytest -q` passed 3,306 tests with 24 expected
    skips in 683.64 seconds;
  - `git diff --check` passed, with only Git's existing Windows line-ending
    notices.
- Implementation observation:
  - the first full attempt placed experiment churn under the report directory
    and exposed a Windows `os.replace` sharing failure; the harness was
    corrected to use a fresh operating-system temporary directory for every
    workload and to copy only retained failure artifacts into the report.
    Production persistence behavior was not changed.
- Known limitations:
  - these measurements isolate synchronous host persistence and authoritative
    reload cost; they do not yet measure Qt heartbeat latency, repaint cost,
    Controller queue behavior, transport timing, CPU RSS, or OS I/O byte
    counters;
  - a passing Slice 0 report is not performance acceptance;
  - the measured 275.593 ms mean and 361.991 ms p95 completion costs are large
    enough to explain operator-visible stalls when executed on the Qt thread,
    but Slice 1 must measure that event-loop impact directly.
- Next permitted slice: Slice 1, metrics library and Qt event-loop probe.

## Slice 1: Metrics Library And Qt Event-Loop Probe

Status: `verified`

Goal:

Create reusable, low-overhead measurements that work in unit tests, UI
scenarios, Windows, and the Pi.

Scope:

- high-frequency Qt heartbeat using monotonic time;
- percentile and threshold-band calculations;
- named phase timing context/helper;
- optional resource sampling;
- versioned JSON report writer;
- deterministic tests using synthetic samples and deliberately injected Qt
  stalls.

Files in this slice:

- `docs/virtual_workflow_verification_plan.md`
- `docs/virtual_workflow_report_schema.md`
- `tools/virtual_workflows/metrics.py`
- `tools/run_qt_event_loop_probe.py`
- `tools/characterize_execution_persistence.py`
- `tests/performance/test_virtual_workflow_metrics.py`
- `pytest.ini`
- `README.md`

Implementation decisions:

- retain the existing singular `tools/virtual_workflows/report.py` as the
  versioned report implementation; the earlier provisional `reports.py` name
  is obsolete;
- use a 10 ms precise Qt timer for service-gap and lateness samples;
- use a stoppable observer thread for main-thread stack capture during stalls
  above 250 ms and named-phase attribution;
- sample CPU, RSS, I/O, and thread count with `psutil` when available, while
  reporting unsupported data without failing;
- keep thresholds informational and leave D-008 open.

Behavior change:

- None in normal application mode.
- Production freeze-watchdog behavior remains unchanged.

Focused tests:

- percentile calculations handle empty, short, and long sample sets;
- heartbeat reports no false stall while the event loop is serviced;
- an injected blocking callback is detected and attributed;
- report output is deterministic aside from documented identity/timestamps;
- sampler shutdown leaves no timer/thread active.

Validation:

- focused metrics tests;
- a real PySide6 offscreen probe run;
- full Python suite.

Proceed criteria:

- injected 50-250 ms stalls are observable;
- measurement overhead is characterized;
- report schema validates;
- no hardware imports or access occur.

Rollback:

- remove the isolated metrics/report modules and focused tests.

Completion record:

- Files changed:
  - `docs/virtual_workflow_verification_plan.md`;
  - `docs/virtual_workflow_report_schema.md`;
  - `tools/virtual_workflows/metrics.py`;
  - `tools/run_qt_event_loop_probe.py`;
  - `tools/characterize_execution_persistence.py`;
  - `tests/performance/test_virtual_workflow_metrics.py`;
  - `pytest.ini`;
  - `README.md`.
- Implemented deterministic shared statistics, bounded nested phase timing and
  overlap attribution, best-effort process resource sampling, and a real-Qt
  event-loop probe with a stoppable daemon observer.
- The observer captures the main-thread Python stack at most once per blocked
  episode and never calls Qt from its background thread. Cleanup requires both
  an inactive timer and a joined observer.
- Focused command:
  `.\env\Scripts\python.exe -m pytest -q tests\performance\test_virtual_workflow_metrics.py tests\test_execution_persistence_characterization.py tests\test_app_freeze_watchdog.py`;
  result: 44 passed in 6.65 s.
- Real-Qt command:
  `.\env\Scripts\python.exe tools\run_qt_event_loop_probe.py`; result: pass
  with real PySide6 6.7.1 / Qt 6.7.1. All 20 injected stalls across five
  measured runs were attributed, all five 350 ms phases had a main-thread stack
  capture, and timer/thread cleanup succeeded.
- Qt aggregate: 559 heartbeat samples; service-gap p50 10.014 ms, p95
  13.074 ms, p99 260.559 ms, and maximum 361.097 ms. Probe-callback p50 was
  0.0091 ms, p95 0.0207 ms, and maximum 0.0659 ms.
- Resource result: `measured`; mean process CPU delta 143.75 ms per measured
  run, maximum 171.875 ms, and peak RSS 50,479,104 bytes. These describe the
  entire injected workload and do not isolate observer overhead.
- Qt artifact:
  `verification_reports/virtual_workflows/qt_event_loop_probe_v1/20260723T180304075439Z_e0c2860fbc73/`;
  `report.json`, `summary.txt`, and `stall_stacks.txt` validate and are ignored.
- Slice 0 compatibility command:
  `.\env\Scripts\python.exe tools\characterize_execution_persistence.py --warmup-runs 0 --measured-runs 1`;
  result: pass with all 384 lifecycle invariants, schema v1 validation, and the
  original distribution field names. Measured workload duration was
  47,983.461 ms.
- Slice 0 compatibility artifact:
  `verification_reports/virtual_workflows/execution_persistence_v1/20260723T180358668191Z_e0c2860fbc73/`;
  report and summary validate and are ignored.
- Full command: `.\env\Scripts\python.exe -m pytest -q`; result: 3,332 passed
  and 24 skipped in 571.23 s. An earlier invocation displayed one transient
  failure but was interrupted before its traceback; it did not recur in either
  a complete fail-fast run or the final exact full-suite run.
- `py_compile`, both explicit schema validations, `git check-ignore`, and
  `git diff --check` passed.
- Limitations: offscreen Qt does not measure compositor/GPU rendering; injected
  sleeps validate detection rather than application behavior; the MVC,
  production watchdog, queue, transport, MCU, and hardware remain outside this
  slice. D-008 remains open and every performance result is informational.
- Rollback: remove the new metrics/probe/tests, restore Slice 0's private
  statistics helpers, and revert these documentation and pytest-marker edits.
  No application, protocol, firmware, motion, pressure, or timing rollback is
  needed.
- Next permitted slice: Slice 2 only; do not begin the simulation construction
  seam or production-UI integration as part of this slice.

## Slice 2: Execution Persistence Microbenchmark

Status: `verified`

Goal:

Catch repeated persistence regressions without requiring the UI or a simulated
machine.

Call path:

`prepared execution fixture -> begin intent -> attach command -> update progress -> complete intent -> authoritative validation -> repeat`

Scope:

- 96- and 384-well workloads;
- one-stock and multi-stock/multi-array workloads;
- real temporary filesystem writes and `fsync`;
- growing completed-intent history;
- per-phase and per-well timings;
- first/last quartile growth comparison;
- checkpoint/progress file size reporting.

Files in this slice:

- `tools/characterize_execution_persistence.py`
- `tests/test_execution_persistence_characterization.py`
- `tests/performance/test_execution_persistence_benchmark.py`
- `docs/virtual_workflow_verification_plan.md`
- `docs/virtual_workflow_report_schema.md`
- `README.md`

Implementation decisions:

- retain `tools/characterize_execution_persistence.py` as the supported Slice 0
  compatibility CLI rather than creating the broader scenario runner early;
- preserve `execution_persistence_v1` as the default 96-well/four-stock
  workload and add targeted 96-well/single-stock and
  384-well/single-stock workloads;
- keep performance classification informational: candidate growth emits a
  warning with exit code 0, while correctness and durability failures exit 2;
- detect candidate growth only when the median per-run last/first quartile
  ratio exceeds 1.25 and the median absolute increase exceeds 10 ms;
- keep the report envelope at schema version 1 and add only compatible nested
  workload and persistence metrics.

Focused tests:

- workload reaches the expected progress and intent counts;
- final authoritative execution bundle validates;
- timing phases are all present;
- output reports first/last quartile and file-growth metrics;
- an injected slow persistence operation is classified as a regression.

Validation:

- focused execution-plan/resume tests;
- microbenchmark repeated on the same host;
- full Python suite.

Proceed criteria:

- the current execution-plan workload has a reproducible report;
- the benchmark exposes per-well cost and growth rather than only total time;
- functional correctness is checked after timing completes.

Rollback:

- remove the benchmark/tooling without touching runtime execution behavior.

Completion record:

- Date: 2026-07-23.
- Files changed:
  - `tools/characterize_execution_persistence.py`;
  - `tests/test_execution_persistence_characterization.py`;
  - `tests/performance/test_execution_persistence_benchmark.py`;
  - `docs/virtual_workflow_verification_plan.md`;
  - `docs/virtual_workflow_report_schema.md`;
  - `README.md`.
- Implemented three selectable deterministic workloads, per-run quartile
  growth, progress/resume file-growth series, real `fsync` and atomic-replace
  observation by phase, and warning-only candidate growth classification.
  The original `execution_persistence_v1` CLI default and schema-v1 envelope
  remain compatible.
- Hardware/durability evidence:
  - no application or firmware file changed;
  - the benchmark continues to construct only `Model.__new__`,
    `ExperimentModel`, and `WellPlate`;
  - the synchronous observer always calls and restores the original
    `os.fsync` and `os.replace`, including injected failure;
  - every measured completion produced one begin-intent, attach-sequence,
    progress-write, and complete-intent durable write;
  - all final checkpoints were clean, all command sequences were unique and
    increasing, targets exactly matched progress, and all authoritative bundles
    validated.
- Focused command:
  `.\env\Scripts\python.exe -m pytest -q --basetemp tests\.slice2_focused_tmp tests\performance\test_execution_persistence_benchmark.py tests\test_execution_persistence_characterization.py tests\test_execution_plan.py tests\test_execution_resume_store.py tests\test_authoritative_execution_load.py tests\test_execution_lifecycle_hardening.py tests\test_initial_execution_plan.py tests\test_initial_execution_plan_integration.py`;
  result: 109 passed in 4.34 s. The repository-local temporary directory was
  removed after the run.
- Same-host environment: Python 3.13.14, real PySide6 6.11.1, and Qt 6.11.1.
  Each workload used one warm-up and three measured runs:
  - `execution_persistence_96_single_v1`: pass; 96 completions; mean run
    1,233.130 ms; per-completion p95 14.723 ms; duration CV 0.0088; median
    growth ratio 1.4057 and delta 4.139 ms, below the absolute warning floor;
    artifact
    `verification_reports/virtual_workflows/execution_persistence_96_single_v1/20260723T205206146265Z_9344e3ec5aca/`;
  - `execution_persistence_v1`: informational warning; 384 completions; mean
    run 9,780.238 ms; per-completion p95 34.980 ms; duration CV 0.0080; median
    growth ratio 2.0284 and delta 17.441 ms; artifact
    `verification_reports/virtual_workflows/execution_persistence_v1/20260723T205223148285Z_9344e3ec5aca/`;
  - `execution_persistence_384_single_v1`: informational warning; 384
    completions; mean run 12,477.742 ms; per-completion p95 41.628 ms; duration
    CV 0.0051; median growth ratio 1.7214 and delta 17.119 ms; artifact
    `verification_reports/virtual_workflows/execution_persistence_384_single_v1/20260723T205314942368Z_9344e3ec5aca/`.
- The 96-completion report recorded 97 file-size samples per file and 1,152
  observed calls each to `fsync` and atomic replace. Each 384-completion report
  recorded 385 samples per file and 4,608 calls per operation across its three
  measured runs. All three reports and summaries were inspected, validate
  against schema v1, and are ignored by Git.
- Full command:
  `.\env\Scripts\python.exe -m pytest -q --basetemp tests\.slice2_full_tmp`;
  result: 3,340 passed, 24 skipped, and 38 existing Qt deprecation warnings in
  367.47 s. The repository-local temporary directory was removed afterward.
- `py_compile`, CLI help, explicit validation of all three reports,
  `git check-ignore`, and `git diff --check` passed.
- Limitations: reports were generated from the intentionally dirty Slice 2
  implementation worktree; their performance evidence is informational and is
  not a release baseline. The I/O observer adds small synchronous measurement
  overhead. No Qt event loop, Controller, queue, protocol, MCU, or physical
  behavior is measured.
- Rollback: revert these six benchmark/test/documentation files. No application,
  firmware, protocol, motion, pressure, or timing rollback is required.
- Next permitted slice: Slice 3, as a separately reviewed application
  construction change.

## Slice 3: Safe Application Construction Seam

Status: `verified`

Goal:

Construct the real Model, Controller, and MainWindow with explicit safe
dependencies, without duplicating production startup logic.

Scope:

- extract or add an application composition/factory seam;
- define an explicit simulation profile or dependency bundle;
- inject machine, cameras, log reader, balance, config roots, and experiment
  roots;
- add a persistent simulation identity/banner for visible runs;
- hard-block connection, DFU, GPIO, camera, and updater actions in simulation;
- preserve normal `App.main()` behavior.

Files in this slice:

- `FreeRTOS-interface/App.py`
- `FreeRTOS-interface/ApplicationComposition.py`
- `FreeRTOS-interface/Machine_FreeRTOS.py`
- `FreeRTOS-interface/LocalConfig.py`
- `FreeRTOS-interface/Model.py`
- `FreeRTOS-interface/Controller.py`
- `FreeRTOS-interface/View.py`
- `tests/test_safe_application_construction.py`
- `tests/test_view_window_icon_contract.py`
- `README.md`
- `docs/virtual_workflow_verification_plan.md`

Focused tests:

- normal construction still selects the production `Machine`;
- simulation construction never instantiates `serial.Serial`;
- hardware connection/update actions are unavailable or rejected;
- application objects can be constructed and closed repeatedly offscreen;
- configuration and experiment writes stay in the supplied temporary roots;
- the visible simulation indicator cannot be confused with production mode.

Validation:

- focused startup, connection, close, and safety tests;
- offscreen construction smoke;
- full Python suite.

Proceed criteria:

- real application components launch with safe injected dependencies;
- production startup has no unintended behavioral change;
- a failing simulation dependency cannot fall back to real hardware.

Rollback:

- revert the construction seam and keep earlier host-only benchmark tooling.

Completion record:

- Started 2026-07-23 from commit
  `79b9e453bfc38b1fb5791911163a3db699aa2eef` with a clean worktree.
- Call paths:
  - production: `App.main()` -> production dependencies -> Model -> production
    Machine/peripherals -> Controller -> MainWindow;
  - simulation: explicit temporary roots and safe machine factory -> real Model
    -> guarded Controller -> bannered MainWindow;
  - protected action: UI/direct call -> Controller runtime guard -> rejection
    before serial, camera, GPIO/DFU, balance, or updater access.
- Fixed file boundary: `App.py`, `ApplicationComposition.py`,
  `Machine_FreeRTOS.py`, `LocalConfig.py`, `Model.py`, `Controller.py`,
  `View.py`, focused construction/startup tests, this plan, and `README.md`.
- Added immutable production/simulation runtime contexts, explicit dependency
  and storage-root bundles, fail-closed construction, idempotent construction
  cleanup, and injectable production camera/log-reader factories.
- `App.main()` retains its existing production-only entry point, application
  lock, profile/settings behavior, dispenser defaults, legacy balance wiring,
  splash, theme, watchdog, pending-update display, and event loop while
  delegating MVC construction through the shared seam.
- Simulation construction requires an explicit safe machine factory, seeds
  configuration and calibration memory beneath the supplied run root, owns its
  experiment root, and never retries with production dependencies.
- The simulation window has a fixed high-contrast identity banner and title
  prefix. Physical connection, balance, firmware/DFU, MCU reset, camera,
  qualification/calibration, and application updater controls are disabled;
  matching Controller entry points reject direct calls before dependencies are
  reached.
- Final focused command:
  `.\env\Scripts\python.exe -m pytest -q --basetemp tests\.slice3_final_focused_tmp tests\test_safe_application_construction.py tests\test_view_window_icon_contract.py tests\test_app_settings_fallback.py tests\test_local_config.py tests\test_mainwindow_closeevent.py tests\test_connection_widget_disconnect_state.py tests\test_machine_connection_retries.py tests\test_dfu_update_streaming.py tests\test_refuel_camera_controller.py tests\test_app_update_request.py tests\test_update_and_restart.py`;
  result: 254 passed with 50 existing Qt chart deprecation warnings in 17.47 s.
- Final full command:
  `.\env\Scripts\python.exe -m pytest -q --basetemp tests\.slice3_full_final_tmp`;
  result: 3,350 passed, 24 skipped, and 88 existing Qt deprecation warnings in
  414.46 s. The first full pass exposed three compatibility assumptions in a
  monkeypatched log-reader test and partial `Model.__new__` fixtures; those
  defaults were restored and both focused and full reruns passed.
- Python 3.13.14, PySide6 6.11.1, Qt 6.11.1, and
  `QT_QPA_PLATFORM=offscreen` were used. All repository-local pytest temporary
  directories were removed after validation. Slice 3 produces no retained
  report artifact.
- Primary risks are production startup-order drift, production-path
  redirection, a missed hardware entry point, and leaked Qt workers/timers.
  Mitigations are lazy production factories, compatible default roots and
  runtime policy, UI disablement plus Controller backstops, and repeated
  construction/close tests.
- Limitations: Slice 3 does not provide the simulated machine or a user-facing
  launcher. The API cannot prove an arbitrary caller-supplied machine factory
  is safe; supported simulation callers must use the Slice 4 implementation.
  Physical legacy balance construction is preserved for production but was not
  exercised against hardware.
- Rollback is a single Slice 3 commit revert. No firmware, protocol, motion,
  pressure, or timing rollback is required.

## Slice 4: In-Process Simulated Machine

Status: `verified`

Goal:

Provide deterministic command completion and machine state sufficient to drive
Controller workflows without emulating serial bytes.

Initial simulated behaviors:

- connect/disconnect;
- homed/motor-enabled state;
- print/refuel regulation state and targets;
- absolute movement completion;
- acceleration/profile commands;
- waits;
- dispense commands with configurable duration;
- gripper state;
- command queue depth and lifecycle signals;
- pause, clear, soft-stop, and completion;
- deterministic clock or speed multiplier.

Scope boundary:

- use the same public signals/method contract consumed by Controller;
- do not parse or emit firmware frames in this slice;
- do not simulate camera/calibration image analysis;
- reject unsupported commands explicitly instead of silently succeeding.

Likely files touched:

- `FreeRTOS-interface/simulation/machine.py`
- `FreeRTOS-interface/simulation/state.py`
- `tests/test_simulated_machine.py`
- application construction tests from Slice 3

Focused tests:

- command lifecycle order is stable;
- configured durations advance through Qt without blocking the event loop;
- callbacks execute exactly once;
- queue lookahead, pause, clear, and disconnect semantics match the app-facing
  contract;
- unsupported operations fail visibly;
- fault configuration is deterministic and reset between tests.

Validation:

- simulated-machine focused tests;
- existing command-queue and Controller sequence tests;
- full Python suite.

Proceed criteria:

- representative Controller command sequences complete deterministically;
- simulator timing can be accelerated without eliminating event-loop
  scheduling;
- simulator cannot access hardware.

Rollback:

- remove the isolated simulator and retain the construction/measurement seams.

Completion record:

- Implemented the isolated `simulation` package with immutable timing/fault
  configuration, explicit factory selection, app-shaped state/status payloads,
  a four-command accepted lookahead window, bounded lifecycle histories, and
  owned single-shot Qt timers. No production Machine, transport, camera,
  balance, GPIO, firmware, or protocol module is imported.
- Supported the initial Controller command surface: simulated connection,
  motor/home state, pressure targets/regulation, absolute movement,
  acceleration/speed, print profile, waits, duration-based dispense, gripper,
  sequence pause, immediate pause/resume, pause-after, confirmed clear,
  disconnect/reset, and deterministic instance-local faults. Unsupported
  operations emit stable errors and leave the queue/state unchanged.
- The official simulator was constructed twice through the real Slice 3
  composition seam with real Model, Controller, and MainWindow objects. Both
  runs connected through the `SIMULATED` sentinel and completed representative
  motor, homing, regulation, absolute-motion, wait, and dispense callbacks.
- Focused validation passed 182 tests with 70 existing Qt chart deprecation
  warnings:
  `tests/test_simulated_machine.py`,
  `tests/test_safe_application_construction.py`,
  Controller sequence/array guards, command queue, MachineModel, homing,
  clear-queue, and absolute-motion regressions.
- Full offscreen validation passed 3,366 tests with 24 skipped and 108 existing
  Qt deprecation warnings in 432.44 seconds on Python 3.13.14, PySide6 6.11.1,
  and Qt 6.11.1.
- Static and subprocess import checks confirmed that importing the simulator
  does not load `Machine_FreeRTOS`, serial, RPi/GPIO, or protocol code.
  `git diff --check` passed, and all repository-local pytest temporary
  directories were removed after validation. Slice 4 creates no retained
  report artifacts.
- Limitations: this simulator verifies the application contract and Qt
  scheduling only. It does not model firmware frames, motion physics,
  collision safety, pressure response, camera analysis, balance behavior, or
  droplet quality. Those claims continue to require protocol simulation or
  prepared HIL.
- Rollback is removal of the isolated simulator, focused tests, and
  documentation additions. The verified Slice 3 construction seam remains
  usable and no firmware or production-machine rollback is required.

## Slice 5: Real-UI Print-Array Scenario

Status: `verified`

Goal:

Run the first representative end-to-end application workflow and produce a
responsiveness report that would have exposed the execution-plan UI regression.

Call path:

`QTest -> MainWindow/WellPlateWidget -> Controller.print_array -> real execution persistence -> SimulatedMachine -> command completion -> Controller progress/checkpoint -> real well widget updates`

Scenario steps:

1. Create an isolated scenario run directory.
2. Construct and show the real MainWindow using safe simulation dependencies.
3. Load or build the versioned 96-well finalized experiment fixture.
4. Install a simulated printer head with a canned valid calibration/binding.
5. Set simulated machine readiness, homing, and regulation.
6. Start the array through the UI-facing control.
7. Drive the Qt loop until completion or a hard timeout.
8. Validate files/state and write metrics, screenshots, and diagnostics.

Scope:

- real PySide6 widgets, layouts, signals, and `QApplication`;
- offscreen mode by default, optional visible mode for local inspection;
- real progress/resume/plan writes under a temporary directory;
- configurable real-time or accelerated simulated command cadence;
- milestone screenshots: ready, printing, mid-array, completed, failure;
- no real calibration process in the initial scenario.

Likely files touched:

- `tools/run_virtual_workflow.py`
- `tools/virtual_workflows/scenarios.py`
- `tests/system/test_virtual_print_array_workflow.py`
- versioned scenario fixture/builders
- `README.md` with prerequisites and exact commands

Required assertions:

- 96 wells complete exactly once;
- execution intent ordering remains valid;
- progress and authoritative execution files validate;
- UI reaches running and completed states;
- no popup/error/freeze artifact is silently ignored;
- command lookahead does not starve unexpectedly;
- report contains the required responsiveness and phase metrics.

Validation:

- focused scenario test in offscreen mode;
- scenario CLI run producing inspectable artifacts;
- existing execution, Controller array, UI array, and command tests;
- full Python suite.

Proceed criteria:

- the scenario is deterministic enough for repeated comparison;
- it exposes deliberate injected UI blocking;
- it completes without hardware or manual interaction;
- a failed run leaves sufficient artifacts for Codex to diagnose.

Rollback:

- remove the scenario runner/test while retaining independently useful
  simulator and metrics modules.

Completion record:

- Files changed:
  - `tools/run_virtual_workflow.py`;
  - `tools/virtual_workflows/scenarios.py`;
  - `tools/virtual_workflows/fixtures/virtual_print_array_96_v1.json`;
  - `tests/system/test_virtual_print_array_workflow.py`;
  - `docs/virtual_workflow_verification_plan.md`;
  - `docs/virtual_workflow_report_schema.md`;
  - `README.md`.
- Added a strict versioned fixture that expands rows A-D of the real
  `shallow-384_well_plate` into 96 deterministic serpentine completions. Its
  prepared 5 nL basis is revised through the real canned 10 nL calibration so
  the final authoritative target is one droplet per well and the revision is
  distinguishable from a head-only binding.
- Added the offscreen-by-default real-UI runner, allowlisted start/dock dialog
  automation, real MVC construction, simulator readiness, instance-local
  persistence/UI phase timing, Qt heartbeat/stack/resource evidence, queue
  starvation checks, milestone screenshots, retained event/failure artifacts,
  and schema-v1 reporting. No production application or firmware file changed.
- Focused validation with a repository-local basetemp: 245 passed in 27.46 s.
  The dedicated Slice 5 system file passed all 9 cases in 21.34 s, including
  normal completion, a detected and attributed 300 ms UI stall with a captured
  main-thread stack, failure artifacts, root isolation, and clean timer/thread
  teardown.
- Normal one-timescale CLI report:
  `verification_reports/virtual_workflows/virtual_print_array_96_v1/20260724T001828866102Z_e211e8b91e40/`;
  informational pass in 16.959 s with 96/96 wells, 96 clean completed intents,
  one completion signal, no queue starvation, and a 140.578 ms maximum
  event-loop gap.
- Injected CLI report:
  `tmp/virtual_workflows/virtual_print_array_96_v1/20260724T003049865987Z_e211e8b91e40/`;
  informational pass in 10.838 s with 96/96 wells, no starvation, a detected
  300 ms named stall, one attributed stack capture, and a 412.042 ms maximum
  event-loop gap.
- Two injected attempts under the default report root retained functional
  failure evidence after Windows denied real atomic progress/resume
  replacements at wells 55 and 18. File ACLs and cleanup were valid; the same
  workload passed under pytest roots and the ignored repository-local `tmp`
  root. This host contention is documented as a limitation; durability and
  ordering were not weakened and no automatic fallback was added.
- All six development/manual reports were opened and schema-validated.
  Summaries, event traces, stack artifacts, and successful ready/completed
  screenshots were inspected. This PySide6 installation lacks bundled fonts,
  so offscreen text rendered as placeholder glyphs while layout and well-state
  changes remained visible.
- Full suite command:
  `.\env\Scripts\python.exe -m pytest -q --basetemp=tests\.slice5_full_tmp`;
  result: 3,375 passed, 24 skipped, and 138 existing deprecation warnings in
  456.93 s (7:36). Validated temporary pytest roots were removed.
- Environment: Windows 11 AMD64, CPython 3.13.14, PySide6 6.11.1, Qt 6.11.1.
  Raw reports remain ignored and machine-specific. Slice 6 thresholds and
  comparison logic remain intentionally absent.

## Slice 6: Regression Comparison And Performance Gates

Status: `not_started`

Goal:

Turn reports into trustworthy same-host comparisons and bounded pass/warn/fail
decisions.

Scope:

- warm-up and repeated measured runs;
- baseline report creation with explicit platform identity;
- candidate-versus-baseline comparison;
- absolute and relative threshold rules;
- noise-floor and incompatible-baseline detection;
- Markdown/console summary for Codex and code review;
- separate functional failure from performance regression.

Likely files touched:

- `tools/virtual_workflows/compare.py`
- `tools/run_virtual_workflow.py`
- `tests/performance/test_virtual_workflow_comparison.py`
- tracked baseline metadata or documented baseline-generation commands
- report schema/docs

Baseline policy:

- compare only compatible scenario/report versions;
- prefer baseline and candidate runs on the same host and software environment;
- do not silently compare Windows and Pi;
- retain raw run reports used to create a tracked/accepted baseline;
- regenerate an accepted baseline only through an explicit reviewed action;
- report dirty-tree state and never disguise it as a release baseline.

Focused tests:

- improvement, unchanged, warning, regression, noisy, and incompatible cases;
- relative threshold requires an absolute noise-floor delta;
- absolute severe stall can fail even when the baseline was also slow;
- functional failure always fails regardless of performance comparison;
- missing metrics produce an explicit incomplete result.

Validation:

- comparator unit tests;
- repeated scenario runs on one Windows host;
- review coefficient of variation and outliers;
- full Python suite.

Proceed criteria:

- repeated known-good runs do not flap;
- injected regressions are detected;
- threshold maturity is recorded as informational/candidate/acceptance;
- reports explain every classification.

Rollback:

- revert gating to informational while retaining raw measurements.

Completion record:

- Not started.

## Slice 7: Target-Pi Software-In-The-Loop Lane

Status: `not_started`

Goal:

Run the same hardware-free workflow on representative Raspberry Pi CPU and
storage, without requiring an MCU, printer heads, calibration, pressure, or
operator preparation.

Scope:

- Pi dependency/preflight command;
- isolated report and scenario directories;
- explicit proof that hardware access is disabled;
- headless Qt platform selection;
- remote invocation and artifact retrieval;
- platform-specific baselines and budgets;
- cleanup of temporary scenario data.

Likely files touched:

- `tools/run_virtual_workflow.py`
- a small Pi SIL wrapper if necessary
- `README.md` troubleshooting/prerequisites
- report/compare tooling
- optional automation script after manual commands are stable

Validation:

- run the 96-well scenario on the Pi at least three times;
- confirm no serial/GPIO/camera/balance device was opened;
- retrieve and inspect JSON, timeline, screenshots, and logs;
- compare repeatability with Windows without treating platforms as equivalent.

Proceed criteria:

- Pi SIL runs are operator-light and reproducible;
- target filesystem/CPU regressions are visible;
- the command cannot actuate the printer if the MCU is connected;
- artifacts can be collected by Codex for diagnosis.

Rollback:

- remove the remote wrapper and continue using local SIL; no firmware rollback
  is involved.

Completion record:

- Not started.

## Slice 8: Protocol-Level Virtual MCU And Fault Injection

Status: `deferred`

Goal:

Exercise the real `Machine`, `SerialReader`, framing, ACK handling, status
parsing, and command counters against a deterministic virtual MCU.

Reason for deferral:

The UI regression can be detected with the simpler in-process simulator. A
protocol virtual MCU adds value after the application scenario and metrics are
stable, but building it first would delay useful coverage and duplicate
debugging surfaces.

Scope:

- streaming in-memory duplex serial endpoint;
- real frame/TLV decoder using the canonical protocol contract;
- HELLO/GOODBYE;
- queue ACK and status cadence;
- command accepted/executing/completed/retired counters;
- pause-after, clear, and reset behavior;
- configurable ACK delay/drop, status delay/drop, queue rejection, reset,
  disconnect, and stalled completion;
- deterministic virtual time or controlled real-time pacing.

Likely files touched:

- `FreeRTOS-interface/simulation/transport.py`
- `FreeRTOS-interface/simulation/virtual_mcu.py`
- protocol-level simulation tests
- scenario catalog and report fields
- protocol documentation only if clarification is needed; no protocol change

Required protocol guard:

- reuse existing constants/codecs or generated shared vectors;
- compare virtual behavior with firmware host golden vectors;
- never make application tests pass by teaching the simulator behavior that the
  firmware does not implement.

Validation:

- protocol vector and parser tests;
- virtual MCU positive lifecycle tests;
- fault-injection tests;
- UI print scenario through the real serial reader;
- firmware host tests if shared protocol fixtures change;
- full Python suite.

Proceed criteria:

- positive path matches known firmware semantics;
- fault outcomes are distinct and diagnosable;
- simulator timing remains deterministic;
- no device protocol changes are required.

Rollback:

- remove protocol transport/MCU modules and retain in-process SIL.

Completion record:

- Deferred until Slice 7 is stable or a protocol-specific regression justifies
  earlier work.

## Slice 9: Expanded Workflow Scenario Catalog

Status: `deferred`

Goal:

Add high-value workflows without turning the initial scenario runner into a
large brittle UI robot.

Candidate scenarios, in recommended order:

1. Print array soft stop after well, then resume.
2. Refill-required pause and resume.
3. Board reset or transport fault mid-array.
4. Load a saved authoritative execution and resume.
5. Multiple stocks/heads across one experiment.
6. Experiment creation/finalization through the editor.
7. Canned calibration-result application.
8. Selected calibration UI workflows with virtual cameras/recordings.

Scenario selection rules:

- add a scenario only for a meaningful risk or historically observed failure;
- reuse application APIs and Qt controls rather than duplicating business logic;
- use canned calibration records before attempting camera/image simulation;
- keep each scenario independently runnable and timeout-bounded;
- version fixtures and scenario semantics;
- preserve failure artifacts.

Likely files touched:

- `tools/virtual_workflows/scenarios.py`
- `tests/system/`
- versioned fixtures/builders
- simulator fault configuration
- report schema only when genuinely new evidence is needed

Validation:

- focused scenario;
- shared scenario-runner tests;
- full Python suite;
- Pi SIL for performance-sensitive workflows.

Proceed criteria:

- each scenario has an owner, risk statement, and required assertions;
- total routine runtime remains bounded through fast and extended scenario sets.

Rollback:

- remove an unstable scenario without weakening the core print-array gate.

Completion record:

- Deferred until the first print-array scenario and comparator are verified.

## Slice 10: Codex Skill, AGENTS Rules, And Automation

Status: `not_started`

Goal:

Make verification selection and report review repeatable without making a
Codex-only workflow the source of truth.

Principle:

Repository scripts, tests, schemas, and reports own verification behavior. A
Codex skill orchestrates those stable tools and explains how to interpret
results; it does not reimplement the simulator or benchmark in prose.

Scope:

- update root `AGENTS.md` with a change-to-verification matrix;
- define when execution/UI/persistence changes require microbenchmark, Windows
  SIL, Pi SIL, protocol simulation, or HIL;
- create a concise `labcraft-verify-changes` skill after commands stabilize;
- include scripts/references in the skill only when they are reusable and not
  better owned by the repository;
- add CI or scheduled automation only after local repeatability is demonstrated;
- require Codex summaries to distinguish functional, SIL, Pi, protocol, and HIL
  confidence.

Proposed change-to-lane matrix:

| Changed area | Minimum additional lane |
| --- | --- |
| Pure model/helper logic | Focused/full pytest |
| Execution plan, progress, resume, atomic persistence | Persistence microbenchmark |
| Per-well callback, View repaint, task guide, Qt threading | Real-UI print scenario |
| Machine command queue/status handling | Real-UI scenario; protocol simulation when relevant |
| Protocol framing/ACK/status parsing | Protocol tests plus virtual MCU |
| Target-sensitive performance | Pi SIL |
| Firmware, motion, pressure, valves, physical camera | Firmware checks and applicable HIL |

Likely files touched:

- `AGENTS.md`
- skill folder chosen at implementation time
- CI/workflow configuration if approved
- `README.md` commands and troubleshooting
- this plan

Skill validation:

- initialize and validate using the supported skill-creator tooling;
- forward-test the skill on representative changes without leaking expected
  results;
- confirm it selects the correct lanes and reads generated artifacts;
- confirm humans can run every underlying command without the skill.

Proceed criteria:

- repository commands and reports are already stable;
- AGENTS rules are specific enough to prevent "pytest passed" from being
  reported as full workflow verification;
- skill behavior is validated on realistic change examples;
- automation runtime and flake rate are acceptable.

Rollback:

- remove or revise skill/automation without removing repository verification
  tooling.

Completion record:

- Not started.

## Standard Validation Commands

Commands will be finalized as slices land. Intended interfaces:

```powershell
# Existing full Python regression lane
.\env\Scripts\python.exe -m pytest -q

# Focused host persistence benchmark
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario execution_persistence_96 `
  --report verification_reports\execution_persistence_96.json

# Real-UI software-in-the-loop print scenario
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --scenario print_array_96 `
  --headless `
  --report verification_reports\print_array_96.json

# Compare a candidate report with an accepted same-platform baseline
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --compare verification_reports\baseline.json `
  verification_reports\candidate.json
```

Until these commands exist and are verified, they are design targets rather
than supported commands.

## Manual Review Checklist For Every Scenario Report

- Did the scenario execute the intended workload version?
- Was simulation mode explicit and was hardware access disabled?
- Was the working tree/commit identity recorded correctly?
- Did functional assertions pass?
- Are event-loop delay samples present and plausible?
- Are timing phases complete, or did instrumentation miss a path?
- Did command lookahead remain populated as expected?
- Did checkpoint cost grow during the run?
- Are the baseline and candidate platform identities compatible?
- Were screenshots and stack artifacts produced when required?
- Is the classification supported by the metrics rather than only total time?
- Are warnings/limitations stated before claiming verification?

## Risks And Mitigations

### Simulator Drift

Risk:

The simulated machine may behave differently from firmware and allow invalid
application assumptions.

Mitigation:

- keep the first simulator explicitly app-contract-level;
- add protocol simulation only from canonical constants/vectors;
- compare protocol behavior with firmware host tests;
- retain HIL for physical claims.

### Performance Test Flakiness

Risk:

Host load, antivirus, filesystem cache, and background tasks may move timings.

Mitigation:

- warm up;
- repeat runs;
- use percentiles and noise floors;
- compare on the same host;
- separate informational, candidate, and acceptance thresholds;
- preserve raw reports.

### Headless Rendering Differences

Risk:

Offscreen Qt may not reproduce compositor/GPU behavior.

Mitigation:

- focus initial gates on event-loop, Python, layout/style, and persistence cost;
- offer optional visible/native mode;
- run Pi SIL;
- use manual/native UI review for rendering-specific changes.

### Over-Broad First Scenario

Risk:

Virtualizing experiment design, calibration imaging, printing, and every device
at once would create a slow and fragile harness.

Mitigation:

- start with a prepared finalized experiment and canned calibration;
- add workflows only after the core runner is stable;
- keep scenario fixtures versioned and bounded.

### Unsafe Fallback

Risk:

A failed simulation dependency could accidentally instantiate production
hardware.

Mitigation:

- explicit dependency bundle;
- fail closed;
- safety tests patch physical constructors to raise if called;
- persistent simulation identity;
- no production-port fallback.

### Benchmark-Driven Safety Regression

Risk:

Optimization could weaken durable intent/checkpoint ordering.

Mitigation:

- retain functional and crash-consistency assertions in every performance
  workload;
- treat ordering invariants as hard gates;
- never approve performance improvement with correctness regression.

## Decisions And Open Questions

| ID | State | Decision or question |
| --- | --- | --- |
| D-001 | decided | Start with an in-process app-contract simulator; defer a byte-level virtual MCU |
| D-002 | decided | Repository tooling is the source of truth; a Codex skill is an orchestrator added later |
| D-003 | decided | First UI scenario uses a prepared experiment and canned calibration rather than full calibration imaging |
| D-004 | decided | Use both absolute responsiveness and relative same-host regression criteria |
| D-005 | decided | Run performance-sensitive scenarios on Windows and later on the Pi without an MCU |
| D-006 | decided | Write generated reports under ignored `verification_reports/virtual_workflows/`; retain them until manually removed, with no automatic deletion |
| D-007 | decided | Keep `simulation_dependencies` fail-closed and require the explicit official `make_simulated_machine_factory(config)`; use Qt timers with a positive speed multiplier so acceleration retains real event-loop scheduling |
| D-008 | open | Accepted event-loop latency budgets after characterization |
| D-009 | decided | Keep raw machine-specific reports local and ignored; commit summarized evidence, and later generate reference reports from a designated commit on the comparison host |
| D-010 | open | Shared skill location: developer-local skill versus versioned plugin/package |
| D-011 | open | Which CI environment can provide stable enough performance measurements |

Add or revise decisions here when evidence changes the plan. Do not hide a
scope or threshold change only inside implementation commits.

## Progress Log

| Date | Slice | Status change | Evidence / notes |
| --- | --- | --- | --- |
| 2026-07-23 | Plan | created | Added living architecture, slices, safety rules, metrics, gates, risks, and progress protocol. No runtime code changed. |
| 2026-07-23 | 0 | `planned` -> `in_progress` | Starting commit `acd0c0b3461f140360eb5f26f73062ae908905c9`; worktree contained only this untracked plan. Python 3.12.3, real PySide6 6.7.1, and Qt 6.7.1. Fixed the eight-file slice boundary, workload v1, ignored report location, and same-host reference strategy. |
| 2026-07-23 | 0 | `in_progress` -> `verified` | Added the report contract and hardware-isolated persistence characterization. Focused tests: 226 passed. Full suite: 3,306 passed and 24 skipped. Baseline: five measured runs, 106.301 s mean per run, 275.593 ms mean and 361.991 ms p95 per completion, 1.0818 last/first quartile ratio. Raw report remains ignored. |
| 2026-07-23 | 1 | `not_started` -> `in_progress` | Starting commit `e0c2860fbc7319d796b0f57fe20c1de3c0584b63` with a clean worktree. Fixed the eight-file boundary, hybrid observer, optional psutil sampling, real-Qt requirement, and continued informational threshold policy. |
| 2026-07-23 | 1 | `in_progress` -> `verified` | Added shared bounded metrics and a hardware-isolated offscreen Qt probe. Focused tests: 44 passed. Real-Qt probe: 20/20 stalls attributed, service-gap p95 13.074 ms, callback p95 0.0207 ms, and all required stacks/cleanup verified. Slice 0 compatibility passed all 384 completions. Full suite: 3,332 passed and 24 skipped. Raw reports remain ignored and D-008 remains open. |
| 2026-07-23 | 2 | `not_started` -> `in_progress` | Starting commit `9344e3ec5aca6a514a4bb70860178435cfc29239` with a clean worktree. Call path: prepared fixture -> begin intent -> attach sequence -> update runtime/progress -> complete intent -> authoritative validation. Fixed the six-file boundary, three targeted workloads, real fsync/replace observation, per-run quartile policy, informational warning thresholds, focused/full validation, and benchmark artifact inspection. Safety risks are timing-instrumentation distortion and accidental durability weakening; mitigations are observer restoration tests, real durable calls, no production-file changes, and retained ordering assertions. Rollback is limited to the six benchmark/test/documentation files. |
| 2026-07-23 | 2 | `in_progress` -> `verified` | Added selectable 96x1, compatible 96x4, and 384x1 persistence workloads with real durable-I/O timing, file growth, and per-run quartile warnings. Focused tests: 109 passed. All three same-host reports validated; 96x1 passed, while both 384-completion workloads emitted informational growth warnings without failing. Full suite: 3,340 passed and 24 skipped. Reports remain ignored; no production or firmware file changed. |
| 2026-07-23 | 3 | `not_started` -> `in_progress` | Starting commit `79b9e453bfc38b1fb5791911163a3db699aa2eef` with a clean worktree. Call paths cover production composition, explicit simulation composition, and Controller rejection before physical dependencies. Fixed the application/composition, peripheral injection, storage-root, Controller/View, focused-test, plan, and README boundary. Risks are production startup drift, unintended production-root changes, missed hardware entry points, and leaked Qt workers/timers; mitigations are compatible defaults, lazy imports, layered safety guards, repeated offscreen close tests, and full-suite validation. Rollback is the Slice 3 commit only. |
| 2026-07-23 | 3 | `in_progress` -> `verified` | Added the shared production/simulation construction seam, isolated roots, fail-closed hardware factories, persistent simulation identity, disabled hardware/update controls, and Controller safety backstops. Focused tests: 254 passed. Final full suite: 3,350 passed and 24 skipped. Repeated real MVC/MainWindow construction and cleanup passed offscreen; all temporary roots were removed. No firmware or protocol file changed. |
| 2026-07-23 | 4 | `not_started` -> `in_progress` | Starting commit `c62079214765504529cd9035acc650d95f2e50c0` with a clean worktree; Python 3.13.14, PySide6 6.11.1, and Qt 6.11.1. Call paths cover explicit simulation construction, Controller command lifecycle through Qt timers, and pause-after/clear soft-stop coordination. Fixed the seven-file simulator/test/documentation boundary, explicit factory contract, positive Qt speed multiplier, supported command surface, deterministic fault policy, focused/full validation, and no Slice 5 CLI or full-array scenario. Risks are callback reentrancy, false queue-drain reporting, leaked timers, and simulator/firmware drift; mitigations are exactly-once lifecycle tests, real Controller integration, fail-visible unsupported actions, hardware-import traps, and continued HIL requirements. Rollback removes the isolated simulator, tests, and documentation while retaining Slice 3. |
| 2026-07-23 | 4 | `in_progress` -> `verified` | Added the explicit protocol-free simulator, deterministic Qt lifecycle/timing, app-shaped status, command lookahead, pause/clear/disconnect controls, and fault configuration. Focused tests: 182 passed. The real MVC/MainWindow and representative Controller sequence passed twice offscreen. Full suite: 3,366 passed and 24 skipped in 432.44 seconds. Import traps and diff checks passed; temporary roots were removed and no reports were generated. |
| 2026-07-23 | 5 | `not_started` -> `in_progress` | Starting commit `e211e8b91e409af7365079d803e9992d320012e7` with a clean worktree. Call path: QTest click -> real MainWindow/WellPlateWidget -> Controller array lookahead and durable execution persistence -> explicit SimulatedMachine -> completion callbacks -> Controller progress/checkpoint -> real well-widget updates. Fixed the seven-file tool/fixture/test/documentation boundary, offscreen-by-default real-Qt construction, 96 deterministic A-D serpentine completions, informational-only metrics, failure artifact retention, focused/manual/full validation, and no Slice 6 thresholds. Risks are modal deadlock, callback instrumentation drift, queue-starvation false positives, Qt teardown leaks, and escaped writes; mitigations are allowlisted dialog automation, instance-local wrappers restored in `finally`, signal/file invariant checks, bounded timeout/cleanup, and resolved-root containment. Rollback removes only the Slice 5 runner, fixture, system test, and documentation additions while retaining Slices 0-4. |
| 2026-07-23 | 5 | `in_progress` -> `verified` | Added the versioned 96-well fixture, real-UI scenario/CLI, real persistence/UI/queue instrumentation, screenshots, injected-stall proof, failure diagnostics, system tests, and documentation without changing production or firmware code. Focused tests: 245 passed. Normal 1x report passed in 16.959 s; the final injected report passed in 10.838 s with a 412.042 ms detected gap and attributed stack. Two retained default-root failures document Windows atomic-replace contention without weakening durability. Full suite: 3,375 passed and 24 skipped in 456.93 s. All reports, summaries, screenshots, ignore rules, cleanup, and diff checks were inspected. |

For every update, include:

- date;
- slice;
- old and new status;
- files changed;
- validation commands and results;
- report/artifact paths;
- decisions made;
- remaining risks or blockers;
- next permitted slice.

## Current Next Action

Slice 5 is verified. The next permitted work is the separately reviewed Slice
6 regression comparison and performance-gate implementation. Use compatible
same-host reports and do not reinterpret Slice 5 informational measurements as
acceptance thresholds.
