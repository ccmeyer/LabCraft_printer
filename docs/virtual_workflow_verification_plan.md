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
| 6. Regression comparison and performance gates | `verified` | Baselines, budgets, comparison, exit policy | Stable candidate/baseline classification |
| 7. Target-Pi software-in-the-loop lane | `in_progress` | Run the same scenario on Pi CPU/storage | Pi report produced without MCU/hardware setup |
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

Status: `verified`

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
- `tests/performance/baselines/virtual_print_array_96_v1_windows_sil_primary_v1.json`
- `docs/virtual_workflow_report_schema.md`
- `README.md`
- this plan

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

- Started from clean commit
  `d9381a2f190f2325a41068c54da23feff8cc1e4c`.
- Collection call path: CLI -> warm-up scenario runs -> measured Slice 5
  scenario reports -> report-set aggregation -> candidate baseline/comparison
  input.
- Comparison call path: tracked summarized baseline plus candidate report set
  -> compatibility/noise checks -> absolute and relative rules -> JSON,
  Markdown, console classification, and stable exit code.
- Fixed the seven-file tool/test/baseline/documentation boundary. Production
  MVC, simulator, firmware, protocol, motion, pressure, and physical timing
  remain unchanged.
- Candidate-first policy: at least one warm-up and five measured runs; exact
  same-host/software/workload identity; 25% relative primary regression plus a
  robust absolute noise floor; 250 ms absolute warning; conservative
  acceptance-only severe gates; 30% primary CV noise rejection.
- Planned focused tests, clean-host baseline and normal/injected candidate
  evidence, full pytest, artifact inspection, ignore checks, and diff checks.
  Rollback reverts comparison/baseline changes to Slice 5 informational
  behavior while retaining ignored raw reports.
- Comparison tooling focused validation: 82 passed with 100 existing Qt chart
  deprecation warnings in 27.56 s. The 21 comparator cases cover aggregation,
  clean baseline requirements, exact compatibility, hashes, overwrite
  protection, candidate/acceptance decisions, noise, functional precedence,
  missing evidence, Markdown, and repeated CLI orchestration.
- A live two-run accelerated CLI smoke produced one passing report and then
  correctly stopped on the documented Windows `[WinError 5]` atomic replace
  contention. The one permitted retry under an ignored `tmp` root hit the same
  failure. Both failure reports were retained; durable writes were not
  weakened, and clean-host baseline collection remains pending after the
  tooling checkpoint.
- Tooling checkpoint:
  `ba70d6c544cf02c9cd83178f7ac225727a3c5d88`
  (`feat: add virtual workflow regression comparison`).
- Candidate baseline:
  `tests/performance/baselines/virtual_print_array_96_v1_windows_sil_primary_v1.json`;
  raw report set:
  `verification_reports/virtual_workflows/virtual_print_array_96_v1/20260724T010429447759Z_ba70d6c544cf_report_set/report_set.json`.
  One warm-up plus five measured real-timescale runs completed 96 wells and 96
  intents each with no starvation. Primary p95/p99 CV was 1.42%/1.67%;
  service-gap maxima ranged from 121.667 to 189.132 ms; baseline maturity is
  candidate and its source is the clean tooling checkpoint.
- Independent normal candidate report set:
  `verification_reports/virtual_workflows/virtual_print_array_96_v1/20260724T010642351824Z_ba70d6c544cf_report_set/`.
  It passed compatibility, functional, noise, and every performance rule:
  scheduling-lateness p95/p99 changed by only +0.624/+0.483 ms, both below the
  10 ms floor, and duration improved by 112.133 ms.
- Injected candidate report set:
  `verification_reports/virtual_workflows/virtual_print_array_96_v1/20260724T010840054476Z_ba70d6c544cf_report_set/`.
  All five measured runs detected and attributed the requested 300 ms stall,
  captured nonempty stacks, completed 96 wells, and remained functionally
  valid. The maximum service gap was 484.114 ms, producing the expected
  candidate warning and exit 0 while primary p95/p99 remained stable.
- All 18 baseline/candidate raw reports, report hashes, canonical JSON,
  summaries, event traces, stacks, and screenshots were inspected. Each run
  retained four nonempty screenshots and the injected stack artifacts were
  1,329 bytes. Interpreter and raw-report locations are repository-relative in
  tracked evidence; raw artifacts remain ignored and machine-specific.
- Final focused validation: 82 passed with 100 existing Qt chart deprecation
  warnings in 27.96 s. Full suite:
  `.\env\Scripts\python.exe -m pytest -q --basetemp=tests\.slice6_full_tmp`;
  3,396 passed, 24 skipped, and 138 existing deprecation warnings in 448.61 s
  (7:28). Validated pytest temporary roots were removed; report ignore and
  diff checks passed.
- Environment: Windows 11 AMD64, CPython 3.13.14, PySide6 6.11.1, Qt 6.11.1.
  Candidate thresholds detect regressions but remain warning-only. Promotion
  to acceptance still requires explicit reviewed baseline replacement.
- Remaining limitation: accelerated repeated live CLI writes can reproduce the
  existing Windows atomic-replace contention, while real-timescale baseline,
  normal candidate, injected candidate, focused tests, and the full suite all
  completed without weakening durable persistence.

## Slice 7: Target-Pi Software-In-The-Loop Lane

Status: `in_progress`

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
- `tools/virtual_workflows/scenarios.py`
- `tools/virtual_workflows/compare.py`
- `tools/virtual_workflows/pi_sil.py`
- `scripts/pi/run_virtual_workflow_sil.sh`
- `tools/run_pi_virtual_workflow.ps1`
- `requirements.in` and `requirements-pi.lock`
- focused Pi lane and comparison tests
- `README.md` troubleshooting/prerequisites
- this plan and the report-schema documentation

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

- Implementation opened from clean commit
  `e17b3524fb8fdeb3a2928c1ae8be0368d75b3e81`.
- Selected a fail-closed Bubblewrap boundary: read-only repository, writable
  ignored output root, private `/dev`, private process/network namespaces, and
  no unsandboxed Pi option. A separate accelerated `strace` run supplies
  device-access evidence without contaminating measured timing.
- The designated Pi baseline remains candidate-only. It was created only after
  the tooling commit and an actual compatible Pi completed clean preflight,
  proof, baseline, and independent-candidate collection.
- Windows focused validation passed 92 tests in 28.88 s. A separate final
  Pi/comparison unit pass completed 30 tests in 0.94 s. The accelerated
  backwards-compatibility CLI smoke report passed all 96 wells in 10.140 s at
  `verification_reports/virtual_workflows/slice7-local-smoke/`; its report,
  186,909-byte event trace, four screenshots, safety flags, and summary were
  inspected.
- Full pytest passed 3,406 tests with 24 skips and 138 existing deprecation
  warnings in 450.90 s (7:30). The repository-local pytest roots were removed;
  report ignore and diff checks passed.
- Target validation used Raspberry Pi 5 Model B Rev 1.0, aarch64 Debian kernel
  `6.12.20+rpt-rpi-2712`, NVMe/ext4, CPython 3.11.2, PySide6 6.7.1, Qt 6.7.1,
  and offscreen Qt. `bash -n` passed. Preflight recorded a private `/dev`,
  read-only root, unshared network, no visible serial device, and 49.05 C.
- The accelerated traced audit passed 96/96 wells in 34.187 s with zero matches
  for serial/UART, GPIO, camera, I2C, or USB/DFU paths. Its timings were
  excluded from performance evidence.
- The reviewed 600-second-timeout baseline and independent candidate each
  completed one warm-up plus five measured runs from clean commit
  `1f09d022b749`. Both passed functionally with acceptable noise. Baseline
  p95/p99 scheduling CV was 0.80%/2.34%, and median duration was 28.518 s.
  The independent comparison was compatible; every relative rule passed.
  Candidate-only absolute warnings recorded a 380.430 ms maximum service gap
  and 278.930 ms p99-lateness maximum.
- Two corrected 5.4 MB evidence bundles were retained locally and remotely.
  Archive SHA-256 values are
  `d46159cdefb7fc6baf9b38e7dda89140e918c4d42d02604cbd990036b47004e1`
  (baseline) and
  `ac3b6cd29fe4115da56f5367fc83d7b68ab0a4823f3d2c65e6b566abff3e97e4`
  (candidate). Sidecars, manifests, every member hash/size/path, report sets,
  proof/trace linkage, 56 nonempty screenshots, and 16,170 JSONL events were
  validated after retrieval. Remote evidence was intentionally retained.
- A first 180-second characterization was retained as historical ignored
  evidence but not tracked because timeout is part of compatibility identity.
  One report-only SSH orchestration call was delayed before remote execution;
  rerunning it in a pollable terminal completed immediately. No scenario or
  full-suite result depended on that delayed call.
- Final review found that compact tracked baselines incorrectly required their
  historical raw reports to exist at load/compare time. Baseline creation,
  report sets, and Pi bundle extraction still verify raw hashes strictly;
  compact baseline load/write/compare now validate standalone path/hash
  metadata. Two regression cases were added, and the final focused Pi/comparison
  run passed 32 tests in 0.97 s. The previously completed full suite predates
  this small portability fix and was not rerun per operator instruction, so
  Slice 7 remains `in_progress` with only that completion gate pending.

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
| D-006 | decided | Write generated reports under ignored `verification_reports/virtual_workflows/`; retain local evidence until manually removed. Slice 7 may remove only remote Pi run roots named in a validated bundle manifest, and only after complete local retrieval/hash/report validation; failures retain remote evidence. |
| D-007 | decided | Keep `simulation_dependencies` fail-closed and require the explicit official `make_simulated_machine_factory(config)`; use Qt timers with a positive speed multiplier so acceleration retains real event-loop scheduling |
| D-008 | decided | Use candidate-first policy v1: warn above a 250 ms maximum service gap; acceptance fails above a 1000 ms service gap, above 250 ms scheduling-lateness p99, or on a same-host p95/p99 regression exceeding both 25% and the robust absolute noise floor. The initial tracked baseline remains candidate until separately reviewed promotion. |
| D-009 | decided | Keep raw machine-specific reports local and ignored; commit summarized evidence, and later generate reference reports from a designated commit on the comparison host |
| D-010 | open | Shared skill location: developer-local skill versus versioned plugin/package |
| D-011 | open | Which CI environment can provide stable enough performance measurements |
| D-012 | decided | The designated Pi SIL command is fail-closed behind Bubblewrap with a read-only host filesystem, private `/dev`, no network, and only the ignored report root writable. A separate in-sandbox `strace` audit proves prohibited device paths were not opened; traced timings never enter performance sets. |

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
| 2026-07-23 | 6 | `not_started` -> `in_progress` | Starting commit `d9381a2f190f2325a41068c54da23feff8cc1e4c` with a clean worktree. Call paths cover repeated Slice 5 collection into validated report sets and same-host baseline/candidate comparison into JSON, Markdown, console classification, and stable exit codes. Fixed the seven-file boundary, candidate-first maturity, one-warm-up/five-measured minimum, exact compatibility identity, robust relative/absolute policy, explicit baseline overwrite protection, focused/manual/full validation, and no production/simulator/firmware/protocol changes. Risks are noisy or cross-environment decisions, hidden per-run outliers, and unreviewed baseline replacement; mitigations are CV/MAD/outlier evidence, exact fingerprints, raw-report hashes, run-boundary aggregation, and explicit reviewed acceptance. |
| 2026-07-23 | 6 | `in_progress` -> `verified` | Added versioned report sets, compact tracked baselines, exact same-host compatibility, hash validation, candidate/acceptance policy, repeat-run CLI, JSON/Markdown comparison, stable exit codes, tests, and documentation. Tooling checkpoint `ba70d6c544cf`; focused validation 82 passed. The clean candidate baseline had 1.42%/1.67% primary CV. An independent candidate passed with +0.624/+0.483 ms p95/p99 deltas; five injected 300 ms measured runs warned at a 484.114 ms maximum gap with complete stacks and no functional failure. Full suite: 3,396 passed and 24 skipped in 448.61 s. All raw reports/artifacts/hashes and ignore/diff/cleanup checks were inspected; no production, simulator, firmware, or protocol file changed. |
| 2026-07-23 | 7 | `not_started` -> `in_progress` | Starting commit `e17b3524fb8fdeb3a2928c1ae8be0368d75b3e81` with a clean worktree. Call paths cover a fail-closed Pi preflight and private-device sandbox, the unchanged real-UI/MVC/simulator workflow on Pi CPU/storage, traced hardware-access proof, and manifest-controlled SSH retrieval into same-Pi comparison. The boundary is limited to virtual-workflow tools, Pi wrappers/dependencies, focused tests, a later generated Pi baseline, and documentation; production MVC, simulator, firmware, protocol, motion, pressure, and physical timing remain unchanged. Risks are unavailable user namespaces/offscreen Qt, misleading traced timings, noisy thermal/storage state, unsafe remote paths, and accidental Windows/Pi equivalence. Mitigations are no unsandboxed Pi-run bypass, separate trace evidence, exact environment/filesystem compatibility, hash/path validation, candidate-only Pi maturity, and same-platform comparison. Rollback removes the Slice 7 tooling/evidence commits and retains Windows SIL. |
| 2026-07-23 | 7 | `in_progress` implementation checkpoint | Added Pi-aware CLI/report identity, exact Pi comparison compatibility, fail-closed preflight/proof/bundle helpers, the Bubblewrap Bash runner, SSH/SCP PowerShell orchestration, hashed `psutil` Pi dependency, traversal/hash/cleanup/hardware-isolation tests, and operator/schema documentation. Focused validation passed 92 tests; final Pi/comparison unit validation passed 30. The accelerated Windows CLI compatibility run passed 96/96 wells in 10.140 s, and full pytest passed 3,406 with 24 skips in 450.90 s. JSON, summary, events, screenshots, ignore rules, diff checks, and temporary-root cleanup were inspected. Bash/WSL and a Pi are unavailable on this workstation, so Pi `bash -n`, private-device trace proof, repeated target runs, remote retrieval, same-Pi comparison, and the candidate baseline remain required. Slice 7 stays `in_progress`; Slice 8 remains out of scope. |
| 2026-07-23 | 7 | `in_progress` Pi evidence checkpoint | Designated Pi `192.168.0.33` at clean commit `1f09d022b749` passed Bash syntax, fail-closed preflight, and a traced accelerated 96-well audit with no prohibited device access. A corrected 600-second-identity baseline and independent candidate each passed 1+5 runs with acceptable noise; their same-Pi comparison was compatible and every relative rule passed, with candidate-only absolute responsiveness warnings. Both 5.4 MB bundles and compact baseline were retrieved; archive/manifest/member hashes, reports, summaries, 56 screenshots, and 16,170 events validated. The candidate baseline is tracked at `tests/performance/baselines/virtual_print_array_96_v1_pi5_sil_primary_v1.json`. A compact-baseline portability fix then passed 32 focused tests in 0.97 s. Remote and local ignored evidence were retained. The final full suite was not rerun per operator instruction, so Slice 7 remains `in_progress`; Slice 8 remains deferred. |
| 2026-07-23 | Performance remediation | diagnostic instrumentation added | Added exception-safe timing around the already-connected real pressure-render slot. Reports now retain bounded `ui.pressure_render` invocation/duration evidence and summaries show count, p95, and maximum without changing pressure behavior or comparison policy v1. The original Qt signal connection is restored during scenario teardown. Focused metrics/scenario validation passed 37 tests in 25.06 s. An accelerated 96-well evidence run recorded 1,682 pressure renders at 1.276 ms p95 and 2.903 ms maximum, revealing high update frequency even though each individual render was short on this Windows host. The outstanding Slice 7 full-suite gate remains unchanged and will not run without a fresh operator-approved ETA. |
| 2026-07-23 | Performance remediation | UI repaint optimization implemented and Pi-verified | Starting from clean diagnostic commit `454ec3368689`, changed only `View.py`, virtual-workflow scenario evidence, focused UI/system tests, README, and report/plan documentation; implementation commit `3ee0a1906eb7` was pushed to the feature branch. Pressure signals now request a latest-state bulk-series render through a widget-owned 100 ms single-shot timer; concrete well notifications update only the named label while all non-concrete paths retain batched full refreshes. Focused validation passed 95 tests in 17.34 s. The standalone accelerated Windows report at `verification_reports/virtual_workflows/virtual_print_array_96_v1/20260724T065204790755Z_454ec3368689/` passed 96/96 wells, 96 clean intents, completed plan, valid persistence, and zero starvation in 6.337 s; it coalesced 1,655/1,690 pressure signals into 35 renders (0.298 ms p95), reduced well-update p95 to 0.191 ms, scheduling-lateness p95 to 36.381 ms, and maximum event-loop gap to 106.775 ms. Pi 5 fail-closed preflight and traced audit passed at the exact clean implementation commit with zero serial/UART/GPIO/camera/I2C/USB-DFU matches. The clean speed-1 Pi 1+5 report set `verification_reports/virtual_workflows/pi-sil/virtual_print_array_96_v1/20260724T071630960040Z_3ee0a1906eb7_report_set/report_set.json` passed functionally with acceptable noise. Compared with the tracked Pi baseline, scheduling-lateness p95 improved 176.665 -> 68.824 ms, p99 251.777 -> 118.722 ms, Controller completion p95 130.190 -> 70.677 ms, well update p95 50.903 -> 0.522 ms, and median duration 28.518 -> 18.925 s. Every relative rule passed; candidate classification remains warning only because the 287.254 ms maximum service gap exceeds the informational 250 ms budget, while absolute p99 lateness now passes. All five measured runs retained 96 completions, 1,690 pressure signals, 103 renders, clean teardown, 20 screenshots, and 5,775 event records. Bundle SHA-256 `979eebaec2d49fc9661ae5ae6a5221328c06b16a2895c9294a68882bf6c57b09` and all 225 extracted files validated beneath ignored `verification_reports/pi_sil_ui_repaint_*_20260724/`; remote evidence remains retained. Comparison policy v1, persistence ordering, machine behavior, pressure regulation, firmware, and protocol remain unchanged. Only the separately operator-approved full suite remains pending. |
| 2026-07-23 | 7 | `in_progress` -> `verified` | The announced full-suite command first completed 3,412 passes and 24 skips in 415.02 s with one new test-only timing failure: a fixed 125 ms wait did not reliably observe a 100 ms Qt timer under full-suite load. Replacing that sleep with bounded `QSignalSpy.wait(1000)` passed the timer and real-UI scenario checks (3 passed in 7.19 s). The announced clean retry then passed 3,413 tests with 24 skips and 138 existing warnings in 413.98 s (6:53). Both repository-local pytest roots were validated and removed; `git diff --check` passed. The repaint implementation, compact-baseline portability fix, Pi lane, and complete Python regression suite are now verified. Slice 8 remains deferred pending its own reviewed plan. |
| 2026-07-24 | Performance remediation | execution read elimination `not_started` -> `in_progress` | Starting commit `115503fdd9644c27abc3271b198a4a03fc5b935f` with a clean worktree. Call path: Controller array lookahead -> begin durable intent -> attach command sequence -> completion callback -> progress write -> complete intent. The boundary is limited to authoritative runtime persistence, compatible benchmark/scenario instrumentation, focused tests, and documentation; Controller command behavior, simulator, firmware, protocol, motion, pressure, and UI repaint behavior remain unchanged. The implementation retains three resume saves and one progress save with real fsync/atomic replace per well, replaces per-well bundle/resume reloads with a guarded in-memory session, and fails closed on external file identity changes. Risks are stale cached state, missed external edits, and cache advancement after failed writes; mitigations are pre-write file/revision guards, immutable documents, post-success advancement, failure injection, restart validation, and unchanged durable-operation counts. Rollback is the focused production/tooling/test/documentation commits; no schema or firmware migration is required. Slice 8 remains deferred. |
| 2026-07-24 | Performance remediation | execution read elimination implementation checkpoint | Commit `3c59d6c7280` changed `Model.py`, `AuthoritativeExecutionLoad.py`, the new `persistence_io.py`, the Slice 2 characterization, Slice 5 scenario instrumentation, cache/benchmark/system tests, README, report schema, and this plan. It added the guarded immutable runtime session, pure in-memory authoritative reconciliation, scoped read/fsync/replace observer, cache/conflict/failure tests, and compatible report evidence. The first clean Pi 1+5 set passed functionally with acceptable noise and zero hot-path reads, but comparison exposed a secondary progress-write p95 regression (12.185 -> 18.372 ms). Inspection showed seven identity guards per well because each resume transition guarded both before transformation and immediately before its write. Commit `ea509c7f704a` changed only `Model.py` and the cache/system tests, removed the redundant transformation-time checks, and added an exact four-guards/four-writes assertion; every write remains preceded by a complete identity/revision check. Focused cache, authoritative-load, resume, benchmark, and real-UI validation then passed 37 tests. The retained first Pi bundle SHA-256 is `8921aa670e13c4fc9c1de181668a07fe9e39611d00fdf46cfb83ad843830194e`; it is diagnostic evidence rather than the closing set. |
| 2026-07-24 | Performance remediation | execution read elimination `in_progress` -> `verified` | Final focused validation passed 176 tests in 20.48 s. The three Windows reports at `execution_persistence_96_single_v1/20260724T174747878542Z_ea509c7f704a`, `execution_persistence_v1/20260724T174757270146Z_ea509c7f704a`, and `execution_persistence_384_single_v1/20260724T174833225126Z_ea509c7f704a` all validated with zero measured authoritative read opens and unchanged 1,152/4,608 fsync and replace totals; the 96x4 workload retained its informational JSON-growth warning. The accelerated real-UI report `virtual_print_array_96_v1/20260724T174910862100Z_ea509c7f704a` passed 96/96 in 6.185 s with zero hot-path reads/resume loads, exactly 384 guards, 288 resume plus 96 progress durable operations, 99.812 ms maximum gap, and no starvation. Final full pytest passed 3,423 tests with 24 skips and 138 existing warnings in 415.84 s. Pi `192.168.0.33` at clean commit `ea509c7f704a` passed fail-closed preflight and traced audit with no prohibited device access, then completed a clean speed-1 1+5 set at `pi-sil/virtual_print_array_96_v1/20260724T173242241293Z_ea509c7f704a_report_set/report_set.json`: functional pass, compatible identity, acceptable noise, all relative gates pass, median duration 17.286 s, scheduling p95/p99 51.057/61.914 ms, Controller completion p95 49.627 ms, progress-write p95 14.303 ms, and 287.122 ms maximum gap (candidate warning only). All five raw hashes, 20 screenshots, 5,775 events, terminal plans, zero-read counts, 384 guards/run, and 288/96 durability counts validated. Retrieved bundle SHA-256 is `7d2d8507783767665353575572561b2040e49afbe355d4b0c73473a5f74d3978`. One Windows scenario required the documented single retry after transient atomic-replace contention; inaccessible old pytest temp directories owned by the sandbox remain untracked host artifacts and caused local characterization to report a dirty worktree, but tracked source and the closing Pi commit were clean. Remaining cost is growing JSON serialization plus four durable writes per well; no durability, protocol, firmware, motion, pressure, simulator, Controller command, or UI behavior was weakened. Slice 8 remains deferred pending a separate reviewed plan. |
| 2026-07-24 | Performance remediation | bounded resume checkpoint `not_started` -> `in_progress` | Starting commit `ceec059b0de2a67bd15c2fe4b12958b4555cf682` with a clean tracked worktree. Call path: Controller completion callback -> durable full progress snapshot -> progress-proven pending-intent retirement -> durable bounded resume checkpoint -> in-memory authoritative reconciliation. The boundary is limited to `ExecutionResumeStore.py`, explicit activation in `Model.py`, compatible persistence/scenario tooling, focused tests, and documentation; Controller, View, simulator, production machine, firmware, protocol, motion, pressure, and command timing remain unchanged. Decision: use the discarded-completion design, retain only unresolved pending intents, add no history file/digest/journal, keep schema v1 readable, and compact legacy completed records only during explicit activation after progress proof. All three resume writes, the progress write, identity guards, `fsync`, atomic replacement, and ordering remain mandatory. Risks are losing recovery evidence too early, changing legacy activation, and masking lifecycle metrics; mitigations are progress proof before retirement, passive-inspection/explicit-activation compatibility tests, in-memory lifecycle instrumentation, bounded-size evidence, restart validation, and unchanged durability counts. Rollback reverts the focused source/tooling/test/documentation commit; empty schema-v1 checkpoints remain valid to older readers and no on-disk migration is required. Slice 8 remains deferred. |
| 2026-07-24 | Performance remediation | bounded resume checkpoint implementation complete; verification warning retained | Implementation commit `48f1e0cd981a` makes schema-v1 runtime writes retain only unresolved pending intents, validates/compacts legacy completed records during explicit activation, and keeps lifecycle evidence in tooling memory. Focused validation passed 196 tests in 20.71 s. Windows 1+3 reports `execution_persistence_96_single_v1/20260724T183045870775Z_ceec059b0de2`, `execution_persistence_v1/20260724T183101687865Z_ceec059b0de2`, and `execution_persistence_384_single_v1/20260724T183132027189Z_ceec059b0de2` all passed with peak/final retained intents 1/0, clean resume size 499 bytes, zero net resume growth, zero hot-path reads, unchanged 1,152/4,608 `fsync` and replace totals, and no growth warning. The accelerated real-UI report `virtual_print_array_96_v1/20260724T183201990391Z_ceec059b0de2` passed 96/96 in 6.002 s with peak/final 2/0 intents, 499-byte clean checkpoint, zero reads/loads, 384 guards, 288/96 resume/progress durability calls, four nonempty screenshots, and 1,155 events. Full pytest passed 3,426 tests with 24 skips and 138 existing warnings in 418.33 s. Pi `192.168.0.33` at the clean implementation commit passed fail-closed preflight and traced proof, then two independent clean 1+5 sets (`20260724T183806598496Z_48f1e0cd981a_report_set` and `20260724T184206208517Z_48f1e0cd981a_report_set`) passed functionally with acceptable noise. All 12 raw report hashes and invariant sets validated: 96 completions/run, peak/final 2/0 intents, clean 485-byte checkpoints, zero reads/loads, 384 guards, 288/96 durability counts, and restored observers. The first bundle SHA-256 is `e8041015f15838a145752a0d2d86a9caf75f1128838697e95e7fb8546602837d`; repeat bundle SHA-256 is `1db0b21ffa9fa3b96bb3603a52f1bfa2bd3617a671d7309d351e4b7b83fbead6`. Both compatible comparisons improved primary scheduling and total duration but reproduced one secondary progress-write p95 warning (19.853 and 20.993 ms). Nested evidence attributes the first warning to unchanged progress-phase `fsync` p95 rising from 9.012 to 15.212 ms while replace remained about 0.070 ms; the bounded-resume path does not alter that write. Because the approved close gate required every relative rule to pass, the record is not labeled fully `verified`; the implementation, functional suite, boundedness, safety, and durability invariants are complete, and the remaining warning is retained for a separate progress-snapshot/storage remediation or an explicit reviewed closure exception. Slice 8 remains deferred. |
| 2026-07-24 | Performance remediation | progress snapshot construction `not_started` -> `in_progress` | Starting commit `e98206b3786f3779cf8823f38737b1b402d77820` with a clean tracked worktree. Call path: Controller completion -> live count update -> authoritative progress construction -> unchanged schema-v1 serialization -> atomic flush/fsync/replace -> identity acceptance -> intent retirement. The instrumentation milestone factors full construction, serialization, and atomic text writing into observable private boundaries and adds exception-safe benchmark/real-UI timing for full rebuilds, future cached updates, serialized bytes, and non-durable cost without changing the active durability phase or comparison policy v1. The optimization milestone will pass the pending intent identity and copy only the affected well/stock from the coherent cached payload; no compact JSON, append-only format, batching, deferred durability, background I/O, firmware, protocol, motion, pressure, or simulation changes are permitted. Risks are premature cache advancement, copy aliasing, mismatched live counts, and fallback that hides a conflict; mitigations are post-write advancement, copy-on-write isolation, exact intent/count checks, fail-closed behavior, byte-parity/failure-injection tests, and unchanged four guards/four durable writes per completion. Rollback reverts the two focused commits; schema-v1 files require no migration and Slice 8 remains deferred. |
| 2026-07-24 | Performance remediation | progress snapshot instrumentation baseline complete | Instrumentation commit `a300ded31dd2` passed 50 focused persistence tests and 48 real-UI/benchmark tests. Windows 1+3 reports `execution_persistence_96_single_v1/20260724T191744021734Z_a300ded31dd2`, `execution_persistence_v1/20260724T191750114764Z_a300ded31dd2`, and `execution_persistence_384_single_v1/20260724T191810172871Z_a300ded31dd2` plus accelerated UI report `virtual_print_array_96_v1/20260724T191831462030Z_a300ded31dd2` all passed and showed one full rebuild per measured completion, zero cached updates, aligned serialization/atomic/non-durable samples, restored observers, and unchanged durable calls. The pinned Pi at the same clean commit passed fail-closed preflight and traced hardware proof, then a clean speed-1 1+5 set at `pi-sil/virtual_print_array_96_v1/20260724T192844925928Z_a300ded31dd2_report_set/report_set.json`; all measured runs passed with acceptable collection completion, 96 full rebuilds, zero cached updates, 384 guards, 288 resume plus 96 progress durable calls, and non-durable progress p95 between 4.568 and 5.086 ms. All raw hashes and bundle members validated locally; bundle SHA-256 is `28a5e3a3765e5b954d67a594860b272534d6a88baa127983102da51b9b38d4b8`. A post-collection shell-path extraction error occurred only after the six reports were complete; the exact emitted report set was bundled directly without rerunning or altering evidence. |
| 2026-07-24 | Performance remediation | cached progress construction implemented | The second milestone changes only the Controller-to-Model durable completion call and progress construction/tooling/tests/docs. Durable authoritative completions pass their pending intent ID, validate cached/live reaction, stock, baseline, commanded count, frozen target, and exact post-command count, then copy only the top payload, affected well, reagent map, and affected reagent. Cache/public state advances only after serialization, real flush/fsync/replace, and post-write identity acceptance; conflicts invalidate the session and require explicit reload. Argument-free and non-authoritative calls retain full reconstruction. Final focused validation passed 174 tests in 19.53 s after correcting one test-only revision filename. Deterministic reports now fail if any authoritative completion enumerates all wells, uses a full rebuild, loses samples, reduces durability, or leaves its observer installed. Firmware, protocol, motion, pressure, simulator, schema v1, JSON indentation, and comparison policy remain unchanged. |
| 2026-07-24 | Performance remediation | progress snapshot construction `in_progress` -> `verified` | Optimized Windows 1+3 reports `execution_persistence_96_single_v1/20260724T194130640425Z_69f7f857230f`, `execution_persistence_v1/20260724T194136598265Z_69f7f857230f`, and `execution_persistence_384_single_v1/20260724T194155994374Z_69f7f857230f` all passed with zero full rebuilds, one cached update/serialization/atomic-write sample per completion, valid terminal bundles, zero hot-path reads, and unchanged durability. Cached-construction p50 was 0.0099-0.0107 ms versus 0.1568-0.4174 ms before; non-durable p95 improved for all three workloads. The accelerated UI report `virtual_print_array_96_v1/20260724T194216204406Z_69f7f857230f` passed 96/96 in 5.884 s with 0/96 full/cached construction, 3.467 ms non-durable p95, 384 guards, 288/96 durability counts, zero starvation, and a 101.125 ms maximum gap. Pi `192.168.0.33` at the exact clean commit passed fail-closed preflight and traced proof, then the clean speed-1 1+5 set `pi-sil/virtual_print_array_96_v1/20260724T194644733405Z_69f7f857230f_report_set/report_set.json`; all five measured reports retained 0/96 full/cached counts, 96 serialization/atomic samples, 384 guards, 288/96 durable operations, max/final intents 2/0, valid terminal bundles, restored observers, and acceptable primary noise. Against the instrumentation-only same-Pi set, median construction p50 improved 0.7319 -> 0.0405 ms and median per-run non-durable p95 improved 4.9003 -> 4.7272 ms (-0.1731 ms). Every relative rule passed; the only candidate warning was the existing informational 293.390 ms maximum service gap. Preserving allowed cached reagent metadata increased this fixture's median serialized bytes from 34,368.5 to 54,624.5; schema v1 and four-space formatting remain valid, and serialization-volume changes remain separate. Candidate bundle SHA-256 `38d3cd5312183c1e0218024702beceb9b31756c3d1c8d4956978a46ef7d93e49` and all members validated locally. Final full pytest passed 3,441 tests with 24 skips and 138 existing warnings in 418.76 s. No application durability, firmware, protocol, motion, pressure, simulator, or comparison-policy behavior was weakened; Slice 8 remains deferred. |
| 2026-07-24 | 384x10 stress characterization | `not_started` -> `in_progress` | Starting commit `ccf15b3274019d42ad825ed8c7b1a50262a6353a` had a clean tracked worktree; inaccessible pre-existing pytest temporary directories remain untracked and untouched. Call path: real QTest start click -> MainWindow/WellPlateWidget -> Controller print-array lookahead -> guarded intent/progress/resume persistence -> SimulatedMachine -> completion callback -> real well and pressure-render updates, repeated for ten virtual head exchanges and stock passes. Scope is limited to a versioned fixture, generalized scenario/report tooling, opt-in CLI/Pi wrapper selection, system/performance tests, README, report schema, and this record; production Model, Controller, View, Machine, firmware, protocol, motion, pressure, and persistence ordering remain unchanged. The workload is A-P x 24 wells x 10 stocks = 3,840 stock/well completions. Required evidence is 3,840 cached updates, zero full rebuilds/reads/resume loads, 11,520 resume plus 3,840 progress durable operations, 15,369 guards (`4 x 3,840 + 9` pass-start guards), max/final retained intents 2/0, ten clean pass transitions, bounded event retention, responsive pressure rendering, and a valid terminal bundle. Validation consists of focused reduced multi-stock and 96-well compatibility tests, one accelerated Windows full stress run, one accelerated fail-closed Pi measured run emitted as a one-report report set, JSON/summary/screenshot/event inspection, full pytest, ignore/diff/status checks. Risks are long-run UI/modal deadlock, event/log memory growth, virtual head-exchange drift, and storage variation; mitigations are an 1,800-second hard timeout, pass progress on stderr, redirected bounded application output, event sampling/counters, per-pass invariants, real durability counts, fail-closed Pi sandboxing, and retained failure artifacts. Rollback removes only the stress fixture/tooling/tests/docs additions; no application data migration or hardware rollback is required. Slice 8 remains deferred. |
| 2026-07-24 | 384x10 stress characterization | implementation and Windows validation checkpoint | The versioned 384x10 fixture, generalized real-UI scenario, bounded event/output evidence, one-report report-set option, selectable Pi lane, focused system/comparison/resource tests, README, and schema documentation are implemented without production application changes. Focused validation passed 100 tests in 24.48 s, including a real reduced 24-well x 2-stock workflow and unchanged 96-well compatibility. Full pytest passed 3,452 tests with 24 skips and 148 existing warnings in 422.89 s. Two full Windows attempts were retained at `verification_reports/virtual_workflows/virtual_print_array_384x10_v1/20260724T220131292808Z_ccf15b327401/` and `tmp/virtual_workflows/virtual_print_array_384x10_v1/20260724T220338388086Z_ccf15b327401/`; both failed closed on transient Windows `os.replace` access denial rather than overwriting a checkpoint, at completions 1,121 and 1,414 respectively. The second run completed three passes with zero hot-path reads/full rebuilds/starvation, 1,414 cached updates, exact durability counts, 1.505 GB cumulative progress serialization, 74.864 ms scheduling-lateness p99, 916.750 ms maximum service gap, and 1,009.991 ms maximum active pressure-render interval. The latter crosses the opt-in 1,000 ms stress limit and demonstrates a real one-second UI-update gap on this Windows host. The documented single fresh-root retry was exhausted; no durability operation was suppressed or retried invisibly. The implementation remains `in_progress` pending one clean target-Pi run, report/artifact/hash inspection, and final diff/status checks. Slice 8 remains deferred. |
| 2026-07-24 | 384x10 stress characterization | target-Pi run incomplete at announced boundary | Commit `831da86166f3731571a9f1e33e17d59273bb0e8d` was pushed to the feature branch and cleanly fast-forwarded on Pi `192.168.0.33`. Fail-closed preflight and the fixed traced 96-well proof passed first at that exact commit with 96/96 completions, zero prohibited hardware access, zero hot-path reads/full rebuilds/starvation, and exact 288/96 resume/progress durability counts. The one measured 384x10 run remained inside Bubblewrap with private `/dev` and no network, sustained approximately 96% CPU, and grew from roughly 403 to 449 MiB RSS during live observation. It exceeded the announced 15-minute abnormal threshold and was terminated at the announced 20-minute hard boundary by its exact verified process group; no process remained afterward. Retrieved ignored evidence at `verification_reports/pi_sil_384x10_partial_20260724/20260724T222100105889Z_831da86166f3/` proves 3,791/3,840 durable target entries: stocks 1-9 completed 384/384 and stock 10 completed 335/384, leaving 49. The progress snapshot was 1,064,148 bytes (SHA-256 `5B63406CF7CCF65D7529850A3C413E5A167DBF516E281F61DF40FFC4BA05371A`), the bounded resume checkpoint was 1,274 bytes, and the partial retained directory was 6.7 MiB. Ready, printing, and midpoint screenshots were nonempty; the midpoint image visibly showed the real 16x24 UI, simulation banner, pressure plot, queue, and stock-5 guidance. Because termination preceded teardown, no canonical report, events file, terminal bundle validation, or final responsiveness classification exists and the run is not a pass. This result demonstrates that complete-snapshot serialization plus mandatory synchronous durability dominate even at 100x simulated speed and that a comparable Pi needs approximately 20-25 minutes. Implementation and regression validation are complete, but the characterization remains `in_progress`; a future explicitly announced run may use the existing 1,800-second scenario timeout to obtain terminal evidence. Slice 8 remains deferred. |

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

The progress-snapshot construction remediation is verified. The opt-in
`virtual_print_array_384x10_v1` stress implementation, focused tests, and full
pytest are complete. Windows exposed repeatable fail-closed atomic-replace
contention and a 1,009.991 ms pressure-render interval before either full run
could finish. The target Pi durably reached 3,791/3,840 completions at the
announced 20-minute stop boundary, proving that full snapshot serialization and
synchronous durability remain material at this scale. The current next action,
if terminal Pi evidence is required, is one separately announced run using the
existing 1,800-second timeout and an expected 20-25 minute duration. Preserve the
intent-bound copy-on-write path, one identity guard per write, three resume
writes plus one progress write per completion, schema-v1 four-space JSON, real
flush/fsync/atomic replace, fail-closed external-change behavior, and terminal
full validation. Remaining progress cost is complete-file serialization plus
variable synchronous `fsync`; any compact format, metadata-volume change, or
ordered persistence worker requires a separate plan and recovery review.
Slice 8 remains `deferred`.
