# Calibration Memory Aggregation Schema

## Source Vs Derived

Source files:

- `CalibrationMemory/runs/<run_id>/run_summary.json`
- `CalibrationMemory/runs/<run_id>/observations.jsonl`
- `CalibrationMemory/indices/run_catalog.jsonl`

Derived files:

- `CalibrationMemory/indices/pair_memory.json`
- `CalibrationMemory/indices/pair_type_memory.json`
- `CalibrationMemory/indices/reagent_memory.json`
- `CalibrationMemory/indices/head_type_memory.json`
- `CalibrationMemory/indices/recommendation_index.json`

## Common Snapshot Envelope

Each derived snapshot file has:

```json
{
  "schema_name": "labcraft.calibration_memory.pair_memory",
  "schema_version": 1,
  "feature_extraction_version": 1,
  "entry_count": 1,
  "updated_at_utc": "2026-03-06T18:12:00Z",
  "entries": []
}
```

## Aggregate Entry Shape

Top-level aggregate entries are keyed by identity scope and contain per-pulse buckets.

Example:

```json
{
  "schema_version": 1,
  "aggregation_level": "exact_pair",
  "entry_key": "water::nozzle_100um_h01",
  "identity_keys": {
    "reagent_id": "water",
    "printer_head_id": "nozzle_100um_h01",
    "head_type_id": "nozzle_100um"
  },
  "available_pulse_widths_us": [1500, 1700],
  "contributing_run_count": 3,
  "source_run_ids": ["run_a", "run_b", "run_c"],
  "source_run_refs": [],
  "identity_quality_summary": {},
  "per_pulse_width": {
    "1500": {}
  },
  "default_recommendation": {},
  "updated_at_utc": "2026-03-06T18:12:00Z"
}
```

## Per-Pulse Bucket Shape

Example:

```json
{
  "schema_version": 1,
  "aggregation_level": "exact_pair",
  "pulse_width_us": 1500,
  "recommended_pressure_psi": 1.62,
  "recommended_pressure_band_psi": [1.6, 1.64],
  "emergence_time_us": 4305,
  "stable_single_droplet_band_psi": [1.455, 1.755],
  "trajectory_pressure_band_psi": [1.505, 1.695],
  "expected_mean_volume_nL": 9.95,
  "expected_cv_pct": 4.1,
  "run_to_run_volume_cv_pct": 0.5,
  "contributing_runs": 2,
  "sample_count": 2,
  "source_run_ids": ["run_a", "run_b"],
  "source_run_refs": [],
  "identity_quality_summary": {},
  "identity_keys": {
    "reagent_id": "water",
    "printer_head_id": "nozzle_100um_h01",
    "head_type_id": "nozzle_100um"
  },
  "recommendation_sources": {
    "recommended_pressure": {
      "droplet_search": 2
    },
    "volume": {
      "droplet_search": 2
    }
  },
  "updated_at_utc": "2026-03-06T18:11:00Z",
  "recommendation_confidence": 0.99,
  "confidence_components": {
    "base": 0.82,
    "run_support_adjustment": 0.04,
    "identity_adjustment": 0.0,
    "consistency_adjustment": 0.06,
    "recency_adjustment": 0.03,
    "weak_identity_fraction": 0.0,
    "latest_gap_days_from_dataset": 0.0
  }
}
```

## Recommendation Index Shape

`recommendation_index.json` is a flattened lookup table derived from the aggregate snapshots.

Example:

```json
{
  "schema_name": "labcraft.calibration_memory.recommendation_index",
  "schema_version": 1,
  "feature_extraction_version": 1,
  "entry_count": 5,
  "updated_at_utc": "2026-03-06T18:12:00Z",
  "entries": [
    {
      "schema_version": 1,
      "aggregation_level": "exact_pair",
      "lookup_rank": 1,
      "entry_key": "water::nozzle_100um_h01",
      "identity_keys": {
        "reagent_id": "water",
        "printer_head_id": "nozzle_100um_h01",
        "head_type_id": "nozzle_100um"
      },
      "available_pulse_widths_us": [1500, 1700],
      "pulse_width_us": 1500,
      "recommended_pressure_psi": 1.62,
      "stable_single_droplet_band_psi": [1.455, 1.755],
      "trajectory_pressure_band_psi": [1.505, 1.695],
      "expected_mean_volume_nL": 9.95,
      "expected_cv_pct": 4.1,
      "contributing_runs": 2,
      "source_run_ids": ["run_a", "run_b"],
      "recommendation_confidence": 0.99,
      "confidence_components": {},
      "updated_at_utc": "2026-03-06T18:11:00Z"
    }
  ]
}
```

## Run Summary Additions Used By Phase 3

New or now-preserved run-summary fields:

- `run_status`
- `source_refs`
- `authoritative_refs`
- `manager_meta`
- `advisory_prior`
- `derived_metrics`

`derived_metrics` is a compact extracted view of a run used for aggregation qualification and fallback analysis.
