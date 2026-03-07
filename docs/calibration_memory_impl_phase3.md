# Calibration Memory Phase 3

## Scope

Phase 3 turns the existing calibration-memory sidecar into a reusable prior system without changing calibration execution semantics.

Implemented behavior:

- completed sidecar run summaries are aggregated into derived memory snapshots
- prior lookup selects the best available prior for a requested calibration context
- calibration startup performs advisory lookup only
- current machine settings and calibration flow remain authoritative
- priors are recorded in sidecar state, not auto-applied

## Files Changed

- `FreeRTOS-interface/CalibrationMemoryAggregator.py`
- `FreeRTOS-interface/CalibrationMemoryStore.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `tests/test_calibration_memory_aggregator.py`
- `tests/test_calibration_memory_store.py`
- `tests/test_calibration_memory_integration.py`

## Derived Files

Created under `FreeRTOS-interface/CalibrationMemory/indices/` when completed runs exist:

- `pair_memory.json`
- `pair_type_memory.json`
- `reagent_memory.json`
- `head_type_memory.json`
- `recommendation_index.json`

Raw per-run summaries under `FreeRTOS-interface/CalibrationMemory/runs/<run_id>/run_summary.json` remain the source material for aggregation.

## Call Path

Advisory read path:

1. `CalibrationManager.begin_session()`
2. `CalibrationManager._start_calibration_memory_run()`
3. `CalibrationManager._lookup_calibration_memory_prior()`
4. `CalibrationMemoryStore.get_best_prior()`
5. `CalibrationMemoryAggregator.get_best_prior()`

Derived snapshot rebuild path:

1. `CalibrationManager.onCalibrationDataUpdated()` or `CalibrationManager.end_session()`
2. `CalibrationMemoryStore.build_run_summary()`
3. `CalibrationMemoryStore.write_run_summary()`
4. `CalibrationMemoryStore.refresh_derived_memory()`
5. `CalibrationMemoryAggregator.rebuild()`

## Aggregation Levels

Implemented levels:

- `exact_pair`
- `exact_reagent_head_type`
- `reagent_family_head_type`
- `reagent_only`
- `head_type_only`

Pulse width handling:

- snapshots are stored per exact observed pulse width
- lookup prefers exact pulse width, then nearest pulse width within the same aggregation level

Qualification rules:

- `exact_pair` requires explicit `reagent_id` and explicit `printer_head_id`
- `exact_reagent_head_type` requires explicit `reagent_id` and explicit `head_type_id`
- grouped levels can accept inferred identity, but confidence is reduced
- only completed runs with usable extracted metrics are aggregated

## Advisory Integration

At calibration start:

- the store builds the current memory context
- the best available prior is looked up
- the selected prior is stored on `CalibrationManager._calibration_memory_prior_candidate`
- the run summary records `advisory_prior`
- an `advisory_prior_lookup` observation is appended to the sidecar observation log

What does not happen:

- no UI fields are changed
- no pressure or pulse width is auto-applied
- no calibration algorithm branch changes based on the prior

## Confidence Model

The score is intentionally simple and explainable.

Components:

- base score by aggregation level
- support bonus from contributing run count
- penalty for inferred identity in grouped buckets
- consistency adjustment from observed CV / run-to-run spread
- recency adjustment relative to the newest run in the dataset

Lookup adds:

- pulse-distance penalty when nearest-pulse fallback is used
- optional target-volume tie-break penalty when a target volume is supplied

## Source Of Truth

Authoritative data:

- `calibration.json`
- per-run sidecar `run_summary.json`
- per-run sidecar `observations.jsonl`

Derived and regenerable:

- all files in `CalibrationMemory/indices/` except `run_catalog.jsonl`

## Known Limitations

- priors are advisory only; there is still no opt-in application hook
- grouped levels use rule-based aggregation, not statistical modeling
- exact-pair memory still depends on explicit runtime identity being present
- recommendation ranking does not yet model target volume beyond a small tie-break penalty
- raw observation logs are not yet re-aggregated into richer analytics tables; Phase 3 operates from run summaries plus authoritative fallback where needed
