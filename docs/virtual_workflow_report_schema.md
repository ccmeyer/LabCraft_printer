# Virtual Workflow Report Schema v1

## Purpose

`labcraft.virtual_workflow_report` is the canonical machine-readable result for
host characterization, software-in-the-loop, protocol simulation, and later
hardware verification workflows. JSON is authoritative; text and CSV files are
derived views.

Version 1 freezes the report envelope while allowing each scenario to add
values inside the five metric groups. A new top-level field or an incompatible
meaning requires a schema-version increment.

## Required Envelope

Every report contains exactly these top-level fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_name` | string | Must be `labcraft.virtual_workflow_report` |
| `schema_version` | integer | Must be `1` |
| `run` | object | Scenario identity, timing policy, repetitions, and timestamps |
| `source` | object | Git commit, short commit, dirty state, and collection error |
| `environment` | object | OS, CPU, architecture, Python, and Qt identity |
| `safety` | object | Simulation identity and explicit hardware prohibitions |
| `workload` | object | Versioned scenario inputs and operation counts |
| `metrics` | object | The five required metric groups |
| `artifacts` | object | Paths relative to the report directory where practical |
| `classification` | object | Result, threshold maturity, and reasons |
| `limitations` | array[string] | Evidence that the run did not collect |

Unknown top-level fields are rejected. Scenario-specific values belong inside
`workload`, `metrics.<group>.values`, or `artifacts`.

## Run And Classification

`run` requires:

- non-empty `run_id`, `scenario_name`, `scenario_version`, `run_mode`, and
  `timing_policy` strings;
- non-negative integer `warmup_runs` and `measured_runs`;
- UTC ISO-8601 `started_at_utc` and `ended_at_utc` values ending in `Z`;
- non-negative `duration_ms`.

`classification.status` is `pass`, `warning`, or `fail`.
`classification.threshold_maturity` is `informational`, `candidate`, or
`acceptance`. Slice 0 always writes `informational`; its `pass` means the
workload and durability invariants completed, not that performance is
acceptable. `classification.reasons` is always a list of strings.

## Safety Contract

`safety.simulation` must be `true`, and `safety.hardware_access_allowed` must be
`false`. `safety.hardware_interfaces` is a non-empty object whose values must
all be `false`. Slice 0 records at least:

- serial;
- GPIO;
- camera;
- balance;
- MCU;
- firmware update.

The Slice 0 runner constructs a deliberately incomplete model using
`Model.__new__`, `ExperimentModel`, and `WellPlate`. It must not instantiate
`App`, `Controller`, `Machine_FreeRTOS`, a transport, or any physical-device
object.

## Metric Groups

`metrics` contains exactly:

- `responsiveness`;
- `workflow`;
- `queue`;
- `persistence`;
- `resources`.

Every group is an object with:

- `status`: `measured`, `partial`, `not_available`, or `not_applicable`;
- `values`: an object, empty when no values were collected.

Durations use milliseconds and byte counts use bytes. Metric names include
their unit suffix where ambiguity is possible.

The Slice 0 persistence report includes raw per-operation samples and
distributions for intent creation, command attachment, runtime update, progress
write, intent completion, and total completion cost. It also includes
first/last-quartile comparison, linear growth slope, run-to-run variation,
process CPU time, final durable-file sizes, intent count, and final invariant
results.

Slice 0 reports responsiveness as `not_available`, queue behavior as
`not_applicable`, and resources as `partial`. Slice 1 populates responsiveness
and resources without changing the envelope.

### Slice 2 persistence values

Slice 2 retains the Slice 0 field names and adds compatible values beneath
`metrics.persistence.values`:

- `well_total_growth_by_run`: first/last quartile distributions, means,
  absolute delta, and ratio computed independently for each measured run;
- `well_total_growth_ratio` and `well_total_growth_delta_ms`: distributions
  across the per-run growth results;
- `growth_assessment`: the informational ratio and absolute-delta thresholds,
  observed medians, candidate-regression decision, and classification effect;
- `file_growth`: initial/final size, byte growth, and bytes-per-completion slope
  distributions for `progress.json` and `execution_resume.json`;
- `durable_io_statistics_ms`: real `fsync` and atomic `os.replace` duration
  distributions overall and by named persistence phase;
- `runs[*].file_size_samples_bytes`: initial and post-completion file-size
  samples;
- `runs[*].durable_io_samples_ms`: raw real durable-I/O timings grouped by
  operation and phase; and
- `runs[*].quartile_growth`: that run's independently calculated growth
  evidence.

File-size observation occurs outside `well_total` timing. The synchronous I/O
observer always calls the original `fsync` and `os.replace`, records their
duration, and restores them after success or failure.

Slice 2 uses three workload IDs:

- `execution_persistence_96_single_v1` for 96 wells and one stock;
- `execution_persistence_v1` for the original 96 wells and four stocks; and
- `execution_persistence_384_single_v1` for 384 wells and one stock.

A correct run is an informational `warning` only when the median per-run
last/first quartile ratio is greater than 1.25 and the median absolute increase
is greater than 10 ms. That warning retains exit code 0 and is not an
acceptance gate. Correctness or durability failure is `fail`; performance
acceptance and baseline comparison remain Slice 6 work.

### Slice 1 responsiveness values

The Qt event-loop probe writes these keys beneath
`metrics.responsiveness.values`:

- `heartbeat_interval_ms`, `observer_interval_ms`, and
  `stack_capture_threshold_ms`: configured intervals;
- `threshold_bands_ms`: descriptive latency bands, currently 25, 50, 100, 250,
  and 1000 ms;
- `event_loop_gap_ms`: callback-to-callback service-gap distribution;
- `scheduling_lateness_ms`: `max(0, service gap - heartbeat interval)`;
- `probe_callback_cost_ms`: time spent in the heartbeat callback itself;
- `stall_events`: service gaps strictly greater than the first threshold band,
  including the greatest-overlap named phase;
- `stack_captures`: main-thread Python stacks captured by the observer while a
  gap is above the stack threshold;
- `injected_stall_checks`: per-run detection and attribution results for the
  known probe workload;
- `runs`: bounded raw samples, phase records, retention counts, shutdown state,
  and resource results for each measured run.

Each distribution contains `count`, `mean`, `p50`, `p95`, `p99`, `maximum`,
`linear_slope_per_sample`, and `counts_strictly_above_ms`. Percentiles use
deterministic linear interpolation. A value exactly equal to a threshold is not
counted above that threshold.

A service gap measures how long the Qt main thread went without servicing the
probe timer. Lateness subtracts the requested timer interval and therefore
estimates scheduling delay. Neither metric is rendering-frame time.

Named phase records contain `name`, monotonic start/end nanoseconds,
`duration_ms`, thread identity, nesting depth, `outcome` (`ok` or `exception`),
and scenario metadata. A delayed gap is attributed to the completed phase with
the greatest time overlap; nesting depth breaks equal-overlap ties.

Stack captures contain the capture monotonic timestamp, observed gap,
active-phase record, main-thread identity, run index, and a formatted Python
stack string. The daemon observer polls without calling Qt APIs and captures at
most once per blocked episode. Raw histories report dropped-sample counts when
their bounded storage is exceeded.

### Slice 1 resource values

The optional process sampler records:

- process CPU-time delta in milliseconds;
- peak resident-set size in bytes;
- process read/write byte deltas;
- maximum thread count;
- sample and dropped-sample counts;
- machine-readable availability reasons; and
- per-run snapshots in the aggregate report.

The group is `measured` when all counters are available, `partial` when only
some platform counters are available, and `not_available` when `psutil` or a
process handle cannot be obtained. Resource limitations never abort the Qt
probe.

### Slice 5 real-UI scenario values

The `virtual_print_array_96_v1` workload retains the v1 envelope and adds its
evidence only beneath the existing workload, metric, and artifact objects. It
uses the real 16-by-24 `shallow-384_well_plate` widget tree while completing
the first 96 wells (rows A-D) once in deterministic serpentine order.

`metrics.responsiveness.values` contains the Slice 1 Qt probe snapshot plus:

- `well_plate_paint_event_count`;
- `phase_timings` for real persistence, Controller completion, and well-widget
  update callbacks; and
- `injected_stall_assessment`, including the requested delay, completion
  position, detection result, stack-capture result, and decision.

`metrics.workflow.values` contains expected/completed wells, the ordered well
updates, array-state transitions, completion-signal count, observed dialogs,
errors, and final invariant results. `metrics.queue.values` contains simulator
lifecycle counts, depth observations, unexpected drain/starvation evidence,
and teardown state. `metrics.persistence.values` contains the validated clean
intent count and command sequences, terminal plan state/revision, authoritative
bundle checks, durable file sizes, and named phase distributions.

The scenario writes `report.json`, `summary.txt`, `events.jsonl`,
`stall_stacks.txt`, retained scenario data, and ready/printing/mid/completed
screenshots. A failing run additionally writes `failure_traceback.txt` and a
failure screenshot when the real window can be captured.

Slice 5 classification remains `informational`. Functional, persistence,
safety, timeout, teardown, missing injected-stall evidence, or required
artifact failures use `fail`; raw latency never warns or fails until Slice 6
defines compatible comparisons and acceptance gates.

## Qt Identity

`environment.qt.binding` is:

- `real` when an installed PySide6 module exposes a module path, version, and
  Qt version function;
- `stub` when a module is present without those real-binding attributes;
- `missing` when PySide6 cannot be imported.

The repository test bootstrap uses real PySide6 when installed and otherwise
installs a limited stub. Importing Qt successfully does not by itself prove a
real event loop or real widgets were exercised.

## Generated Artifact Policy

Local reports are written under:

```text
verification_reports/virtual_workflows/<workload-id>/<UTC>_<short-commit>/
```

The directory is ignored by Git and has no automatic retention. Successful
Slice 0 runs contain `report.json` and `summary.txt`. Slice 1 Qt probe runs
additionally contain `stall_stacks.txt`. Failed runs also contain a traceback;
Slice 0 retains the failing temporary experiment by default.

Raw machine-specific baselines are not committed. The verification plan records
the command, environment, aggregate results, limitations, and local artifact
path. Later regression comparison generates the reference and candidate on the
same host.

## Validation Interface

`tools.virtual_workflows.report` exposes:

- `collect_environment_identity(repo_root)`;
- `validate_report_v1(payload)`;
- `write_report_atomic(path, payload)`.

The writer validates first, flushes and synchronizes a temporary file, and then
atomically replaces the destination.
