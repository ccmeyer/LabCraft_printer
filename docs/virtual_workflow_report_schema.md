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

Slice 7 Pi reports add compatible nested `safety.pi_sil` evidence:

- `sandbox_method` is `bubblewrap_private_dev_v1`;
- `private_dev`, `root_read_only`, and `network_unshared` are `true`;
- `forbidden_access_attempt_count` is zero;
- `proof_sha256` identifies the validated hardware proof; and
- `trace_sha256` identifies the traced safety-audit system-call log.

The proof is produced by a separate accelerated run and is not performance
evidence. Measured Pi runs execute without tracing but inside the same required
private-device sandbox. A report missing or mismatching its preflight/proof is
rejected before Qt construction.

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
  update callbacks;
- `phase_timings.duration_by_name_ms.ui.pressure_render`, containing the
  invocation count and duration distribution for the real
  `PressurePlotBox.update_pressure` render;
- `pressure_render_assessment`, containing the incoming update-signal count,
  actual render count, coalesced count, render-to-signal ratio, 100 ms render
  interval, timer teardown state, and the same render-duration distribution;
  and
- `injected_stall_assessment`, including the requested delay, completion
  position, detection result, stack-capture result, and decision.

`MachineModel.pressure_updated` requests a trailing render through a
widget-owned 100 ms single-shot timer. Repeated signals while the timer is
active are coalesced, and the eventual render reads the latest model arrays.
The phase wraps that real render method and is restored during scenario
teardown. It measures Python and Qt-series replacement work, but not deferred
native paint or compositor time. The metric is diagnostic and is not part of
policy v1 comparison gates, preserving compatibility with existing tracked
baselines.

Concrete well-ID notifications update only that well's existing label. Full
plate refreshes remain batched for non-concrete notifications and UI context
changes. `ui.well_plate_update` continues to time the same public callback, so
existing same-host baseline comparisons remain valid across the optimization.

`metrics.workflow.values` contains expected/completed wells, the ordered well
updates, array-state transitions, completion-signal count, observed dialogs,
errors, and final invariant results. `metrics.queue.values` contains simulator
lifecycle counts, depth observations, unexpected drain/starvation evidence,
and teardown state. `metrics.persistence.values` contains the validated clean
intent count and command sequences, terminal plan state/revision, authoritative
bundle checks, durable file sizes, and named phase distributions.

`metrics.persistence.values.authoritative_io` adds compatible diagnostic
evidence for the guarded active-runtime checkpoint:

- `hot_path_read_count` and
  `execution_resume_hot_path_disk_load_count`;
- `full_bundle_refresh_count`, `guard_count`, and
  `cache_reconciliation_count`;
- resume and progress `fsync`/atomic-replace counts;
- real durable-operation timing samples by named phase;
- root-filtered read-open counts by phase and authoritative relative path; and
- `observer_restored`, which must be true after success or failure.

For a successful 96-well run, hot-path reads and resume loads are zero, resume
fsync/replace counts are 288, and progress fsync/replace counts are 96. Full
bundle inspection remains permitted at activation, explicit repair/reload, and
terminal lifecycle validation; it is not performed inside per-well intent
completion. The observer calls the real file, `fsync`, and replace operations
and is restored in `finally`.

Slice 2 persistence reports similarly expose aggregated
`authoritative_read_opens`. Read counts cover only the measured lifecycle;
final invariant inspection remains outside that observer. Existing report
envelopes and comparison policy paths are unchanged.

The scenario writes `report.json`, `summary.txt`, `events.jsonl`,
`stall_stacks.txt`, retained scenario data, and ready/printing/mid/completed
screenshots. A failing run additionally writes `failure_traceback.txt` and a
failure screenshot when the real window can be captured.

Slice 5 classification remains `informational`. Functional, persistence,
safety, timeout, teardown, missing injected-stall evidence, or required
artifact failures use `fail`; raw latency never warns or fails until Slice 6
defines compatible comparisons and acceptance gates.

### Slice 6 report sets, baselines, and comparisons

Slice 6 does not change the canonical
`labcraft.virtual_workflow_report` version 1 envelope. It introduces three
separate versioned JSON artifacts:

- `labcraft.virtual_workflow_report_set` version 1 retains references and
  SHA-256 hashes for every warm-up and measured canonical report. Warm-up
  reports are retained but excluded from metric statistics. Every measured
  report contributes one run-level value to each comparison metric; raw
  heartbeat samples are never concatenated across run boundaries.
- `labcraft.virtual_workflow_baseline` version 1 is compact tracked evidence
  created from at least one warm-up plus five compatible, clean, passing,
  non-injected measured reports from one commit. It stores environment and
  workload identity, policy version, distributions, CV/MAD/outlier evidence,
  and raw-report locations/hashes, but no raw timing arrays, screenshots, or
  scenario data.
- `labcraft.virtual_workflow_comparison` version 1 records compatibility,
  functional, noise, and performance results separately. Each rule includes
  the metric path, baseline and candidate values, ratio, absolute delta,
  effective noise floor or absolute budget, maturity, and decision.

Compatibility requires exact scenario/report/workload/timing identity and the
same explicit host label, OS/release, architecture, CPU identity, Python
implementation/version/executable, PySide/Qt versions, and Qt platform.
Different Git commits are permitted because they are the comparison target.
Dirty candidate reports remain usable review evidence and are labeled
prominently; dirty reports cannot create an accepted baseline. Raw hashes are
verified before baseline creation or comparison. An interpreter beneath the
repository is recorded relative to the repository root so tracked summaries do
not expose a workstation user directory; an external interpreter retains its
resolved path.

Policy `virtual_workflow_policy_v1` compares the median of run-level values:

- scheduling-lateness p95 and p99 are primary metrics;
- a primary relative regression requires both a ratio greater than 1.25 and an
  absolute delta greater than `max(10 ms, 3 x baseline MAD, 3 x candidate
  MAD)`;
- Controller well completion, well-widget update, progress write, and intent
  completion p95 use the same relative rule with a 5 ms floor; scenario
  duration uses a 1000 ms floor, and these secondary results remain warnings;
- a maximum event-loop service gap above 250 ms warns;
- acceptance maturity fails above a 1000 ms service gap, above 250 ms
  scheduling-lateness p99, or on a primary relative regression; and
- primary CV above 30% is `noisy`/`incomplete`, not a performance failure.

The first Windows workstation baseline is intentionally `candidate`: warnings
return success while functional failures still fail. Acceptance behavior is
implemented and tested but requires an explicit reviewed baseline replacement.

### Slice 7 Pi identity and artifact bundles

A validated Pi report uses `offscreen_pi_sil` or `minimal_pi_sil` as
`run.run_mode`. `environment.target_pi` records:

- lane identifier `raspberry_pi_sil`;
- exact Raspberry Pi model; and
- output filesystem type, storage class, and mount source.

Pi comparison compatibility additionally requires exact target-Pi identity and
the same sandbox method/protection booleans. Proof and trace hashes are retained
for audit but deliberately excluded from compatibility, since an independent
candidate is expected to have a different proof file. Windows reports omit
these fields, so Windows/Pi comparison is explicitly incompatible and never
reaches performance rules.

Slice 7 adds `labcraft.pi_sil_preflight`,
`labcraft.pi_sil_hardware_proof`, and
`labcraft.pi_sil_artifact_bundle`, each at version 1. The bundle manifest
contains repository-relative file paths, byte counts, SHA-256 hashes, the
report-set/proof/trace entry points, and exact cleanup roots. Extraction rejects
absolute or parent-traversal paths, symlinks, unexpected entries, overwrites,
and hash/size mismatches before validating the report set and raw-report
references.

The initial Pi baseline is separately generated at candidate maturity on a
clean designated Pi. Its relative budgets are derived only from that compatible
Pi. The absolute responsiveness rules remain policy-v1 values; they are not
relaxed merely because the target is slower.

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

Slice 6 continues to ignore raw canonical reports and report-set artifacts, but
commits a compact baseline summary beneath `tests/performance/baselines/`.
Referenced raw reports must remain available locally for hash validation.
Replacing that summary is never implicit: the CLI requires both
`--accept-baseline` and `--replace-accepted-baseline`.

Slice 7 retrieves Pi artifacts into the same ignored root. Remote scenario and
report-set directories may be deleted only after local bundle/hash/report
validation and only through manifest-listed cleanup roots. Safety or retrieval
failures retain remote evidence.

## Validation Interface

`tools.virtual_workflows.report` exposes:

- `collect_environment_identity(repo_root)`;
- `validate_report_v1(payload)`;
- `write_report_atomic(path, payload)`.

The writer validates first, flushes and synchronizes a temporary file, and then
atomically replaces the destination.

`tools.virtual_workflows.compare` exposes:

- immutable `ComparisonPolicy`;
- `build_report_set(...)`;
- `create_baseline_summary(...)`;
- `compare_report_sets(...)`;
- validators/loaders for all three Slice 6 artifact types; and
- atomic JSON writers plus the derived Markdown comparison writer.

`tools.virtual_workflows.pi_sil` exposes Pi preflight/proof validation,
artifact bundling and path-safe extraction, candidate-baseline installation,
and manifest-bound cleanup. None of these interfaces imports or constructs the
production machine.
