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
`not_applicable`, and resources as `partial`. Later slices populate those
groups without changing the envelope.

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
Slice 0 runs contain `report.json` and `summary.txt`. Failed runs also contain a
traceback and retain the failing temporary experiment by default.

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
