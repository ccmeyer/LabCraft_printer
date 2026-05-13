# Self-Test Qualification Report Schema v1

Milestone 3 introduces `qualification_report_v1`, a Python-side report layer that keeps the raw firmware self-test output intact while adding derived analysis for qualification and fleet comparison.

## Artifact Layout

Each qualification run still writes:

- `raw_selftest.json`: exact output from `tools/run_selftest.py`; this remains the source of truth.
- `report.json`: normalized qualification report with machine identity, manifest metadata, raw rows, analysis, warnings, operator notes, and verdict.
- `summary.csv`: flat fleet-comparison export with raw and analyzer fields.

Existing raw reports can be converted without touching hardware:

```powershell
.\env\Scripts\python.exe tools\run_qualification.py --manifest factory_acceptance_v0 --machine-id LC-0001 --raw-report hil_reports\selftest_20260513_163220.json
```

## Report Fields

Top-level compatibility fields remain present: `results`, `host_checks`, `raw_summary`, `run_id`, `profile`, `started_at`, `finished_at`, `aborted`, and `overall_status`.

New v1 fields:

- `analysis`: analyzer output, including per-item statuses and metric evaluations.
- `verdict`: final pass/fail result derived from blocking analyzer issues.
- `warnings`: non-blocking candidate-threshold and manifest warnings.
- `operator_notes`: fixture notes copied from the manifest for operator-facing reports.

The manifest can include optional `analysis_rules` keyed by test ID. Metric rules support `informational`, `candidate`, and `acceptance` maturity. Candidate rules warn without failing; acceptance rules fail qualification when violated.

## CSV Summary

`summary.csv` keeps one row per firmware result and host check, and adds rows for analyzer issues and metric evaluations. Stable comparison columns include:

- machine/run identity: `machine_id`, `machine_uuid`, `manifest_id`, `run_id`, `profile`
- raw status: `item_kind`, `item_id`, `name`, `pass`
- analyzer status: `analysis_status`, `failure_domain`, `category`, `message`
- metric thresholds: `metric_name`, `metric_value`, `threshold_maturity`, `threshold_min`, `threshold_max`, `threshold_expected`

## Migration Note

`qualification_report_v0` consumers that only read raw rows can continue using `results`, `host_checks`, and `raw_summary`. Consumers that need machine acceptance should migrate to `verdict.status` and use `warnings` for non-blocking candidate-threshold issues.
