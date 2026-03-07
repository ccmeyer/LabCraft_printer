# Calibration Prior Selection

## API

Primary API:

- `CalibrationMemoryStore.get_best_prior(context, target_pulse_width_us=None, target_volume_nl=None)`
- `CalibrationMemoryAggregator.get_best_prior(context, target_pulse_width_us=None, target_volume_nl=None)`

Returned prior fields include:

- `aggregation_level`
- `match_type`
- `pulse_match_type`
- `pulse_distance_us`
- `recommended_pressure_psi`
- `stable_single_droplet_band_psi`
- `trajectory_pressure_band_psi`
- `expected_mean_volume_nL`
- `expected_cv_pct`
- `source_run_ids`
- `source_run_refs`
- `recommendation_confidence`
- `recommendation_confidence_adjusted`
- `selection_reason`
- `requested_context`
- `advisory_only`
- `applied`

## Lookup Order

Lookup proceeds in this order:

1. `exact_pair`
2. `exact_reagent_head_type`
3. `reagent_family_head_type`
4. `reagent_only`
5. `head_type_only`

Within each level:

- exact pulse width is preferred
- nearest pulse width is used if no exact pulse bucket exists
- higher adjusted confidence wins
- more supporting runs win ties
- newer source runs win later ties
- lower pulse width wins final ties to keep selection deterministic

## Match Types

- `exact`: exact pair and exact pulse width
- `near_exact`: exact pair with nearest available pulse width
- `grouped`: grouped by reagent+head type or reagent family+head type
- `weak_fallback`: reagent-only or head-type-only fallback

## Qualification Rules

Runs are only eligible if:

- `run_status == completed` or `ended_at_utc` is present
- a pulse width can be extracted
- usable calibration metrics exist

Level-specific requirements:

- `exact_pair`: explicit `reagent_id` and explicit `printer_head_id`
- `exact_reagent_head_type`: explicit `reagent_id` and explicit `head_type_id`
- `reagent_family_head_type`: known `reagent_family` and known `head_type_id`
- `reagent_only`: known `reagent_id`
- `head_type_only`: known `head_type_id`

Weak or inferred identity never qualifies an `exact_pair` prior.

## Confidence Adjustments

Stored bucket confidence:

- starts from a base score per aggregation level
- increases with supporting run count
- decreases when contributing runs use inferred identity for that level
- increases or decreases based on observed repeatability
- decreases when the bucket is stale relative to the newest run in the dataset

Selection-time adjustments:

- nearest-pulse fallback reduces confidence
- target-volume mismatch can slightly reduce confidence

## Advisory Integration

At session start the selected prior is:

- stored on `CalibrationManager._calibration_memory_prior_candidate`
- written into the new run summary as `advisory_prior`
- appended as an `advisory_prior_lookup` observation

The prior is not auto-applied.

## No-Prior Cases

`get_best_prior()` returns `None` when:

- no derived recommendation index exists and rebuild finds no usable runs
- the requested context does not match any eligible bucket
- only incomplete or non-usable runs exist for the relevant identities
