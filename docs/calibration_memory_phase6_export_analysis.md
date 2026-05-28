# Calibration Memory Phase 6: Export and Offline Analysis

## Scope

Phase 6 adds offline-only tooling for exporting and analyzing the calibration-memory sidecar. These scripts do not run in the live calibration path and do not change calibration execution behavior.

Source of truth remains:

- `local/CalibrationMemory/runs/<run_id>/run_summary.json`
- `local/CalibrationMemory/runs/<run_id>/observations.jsonl`
- `local/CalibrationMemory/indices/run_catalog.jsonl`

Derived indices remain secondary and rebuildable:

- `local/CalibrationMemory/indices/pair_memory.json`
- `local/CalibrationMemory/indices/pair_type_memory.json`
- `local/CalibrationMemory/indices/reagent_memory.json`
- `local/CalibrationMemory/indices/head_type_memory.json`
- `local/CalibrationMemory/indices/recommendation_index.json`

## Files Added

- `tools/calibration_memory_analysis.py`
- `tools/export_calibration_run_summaries.py`
- `tools/export_calibration_observations.py`
- `tools/plot_calibration_memory_trends.py`
- `tools/audit_calibration_memory_dataset.py`
- `tests/test_calibration_memory_export_tools.py`

## Outputs

Default outputs are written under:

- `local/CalibrationMemory/analysis/exports/`
- `local/CalibrationMemory/analysis/plots/`
- `local/CalibrationMemory/analysis/reports/`

Generated files:

- `analysis/exports/calibration_run_summaries.csv`
- `analysis/exports/calibration_observations.csv`
- `analysis/plots/volume_vs_pressure_points.csv`
- `analysis/plots/cv_vs_pressure_points.csv`
- `analysis/plots/emergence_vs_pulse_width_points.csv`
- `analysis/plots/volume_vs_pressure.png` when `matplotlib` is available
- `analysis/plots/cv_vs_pressure.png` when `matplotlib` is available
- `analysis/plots/emergence_vs_pulse_width.png` when `matplotlib` is available
- `analysis/plots/trend_manifest.json`
- `analysis/reports/calibration_memory_audit.json`
- `analysis/reports/calibration_memory_audit.md`

## Scripts

### Export run summaries

```powershell
.\env\Scripts\python.exe tools/export_calibration_run_summaries.py
```

Optional:

```powershell
.\env\Scripts\python.exe tools/export_calibration_run_summaries.py --root local/CalibrationMemory --out artifacts\calibration_run_summaries.csv
```

The summary export flattens each `run_summary.json` into stable CSV columns covering:

- run identity and timing
- reagent and stock identity
- printer-head and head-type identity
- identity quality
- derived metrics
- prior selection / application
- UI recommendation telemetry

Missing fields from older runs become empty cells.

### Export raw observations

```powershell
.\env\Scripts\python.exe tools/export_calibration_observations.py
```

Optional filters:

```powershell
.\env\Scripts\python.exe tools/export_calibration_observations.py --observation-type process_analysis --phase droplet_search --completed-only
```

The observation export keeps:

- `run_id`
- `ts_utc`
- `phase`
- `observation_type`
- reagent/head identity
- common settings
- common payload metrics
- artifact references
- full JSON spillover columns for mixed payload shapes

This export is separate from the run-summary export because raw observations can be much larger.

### Build trend tables and plots

```powershell
.\env\Scripts\python.exe tools/plot_calibration_memory_trends.py
```

Optional filters:

```powershell
.\env\Scripts\python.exe tools/plot_calibration_memory_trends.py --reagent water --reagent glycerol_25pct --reagent glycerol_50pct --head-type nozzle_80um --head-type nozzle_100um --head-type nozzle_120um
```

Supported trend outputs:

- droplet volume vs pressure by reagent and head type
- CV vs pressure by reagent and head type
- emergence time vs pulse width

If `matplotlib` is not available, the script still writes the trend-point CSV tables and a manifest explaining that PNG generation was skipped.

### Audit dataset availability and sparsity

```powershell
.\env\Scripts\python.exe tools/audit_calibration_memory_dataset.py
```

This audit reports:

- which summary export fields are populated
- which observation types exist
- which key metrics are sparse
- derived snapshot entry counts
- whether the current dataset is strong enough for:
  - exact-pair analysis
  - reagent + head-type analysis
  - emergence-time analysis
  - CV trend analysis

## Export Field Notes

### Summary CSV

The canonical summary CSV includes stable columns such as:

- `run_id`
- `reagent_id`
- `stock_id`
- `printer_head_id`
- `head_type_id`
- `nominal_nozzle_diameter_um`
- `pulse_width_us`
- `recommended_pressure_psi`
- `single_droplet_band_low_psi`
- `single_droplet_band_high_psi`
- `emergence_time_us`
- `expected_mean_volume_nL`
- `expected_cv_pct`
- `prior_application_mode`
- `prior_candidate_aggregation_level`
- `prior_candidate_confidence`
- `prior_applied`
- `ui_recommendation_applied`

Wide or multi-valued fields are serialized into deterministic JSON cells, for example:

- `phase_counts_json`
- `eligible_aggregation_levels_json`
- `prior_candidate_source_run_ids_json`
- `context_json`
- `derived_metrics_json`

### Observation CSV

The raw observation CSV uses one stable canonical envelope across observation types, including:

- `run_id`
- `observation_id`
- `ts_utc`
- `phase`
- `observation_type`
- `settings_print_width_us`
- `settings_print_pressure_psi`
- `payload_kind`
- `payload_reason`
- `payload_pressure_psi`
- `payload_mean_volume_nL`
- `payload_cv_pct`
- `payload_aggregation_level`
- `artifact_refs_json`
- `payload_json`

This keeps the source observation type visible while still allowing mixed observation payloads in one CSV.

## Example Workflow

For the initial water / glycerol baseline study:

1. Collect calibration runs normally.
2. Export summary rows:

```powershell
.\env\Scripts\python.exe tools/export_calibration_run_summaries.py
```

3. Export raw observations only if deeper event-level analysis is needed:

```powershell
.\env\Scripts\python.exe tools/export_calibration_observations.py --completed-only
```

4. Build trend tables and plots for the baseline reagents and nozzle types:

```powershell
.\env\Scripts\python.exe tools/plot_calibration_memory_trends.py --reagent water --reagent glycerol_25pct --reagent glycerol_50pct --head-type nozzle_80um --head-type nozzle_100um --head-type nozzle_120um
```

5. Run the dataset audit to see which fields are still sparse:

```powershell
.\env\Scripts\python.exe tools/audit_calibration_memory_dataset.py
```

## Known Limitations

- Older Phase 1 runs may have weak or missing explicit identities.
- Some runs may not have populated `derived_metrics`; those rows still export, but many analysis columns will be empty.
- Raw observation payloads are heterogeneous by design, so the CSV keeps both extracted scalar columns and a `payload_json` spillover column.
- The trend plots currently focus on summary-level metrics, not full event-sequence reconstruction.
- No pandas dependency is required; CSV output is designed to be analysis-friendly for later pandas use.
