# Calibration Memory Phase 4

## Scope

Phase 4 adds opt-in prior-driven initialization.

What changed:

- priors can now seed the initial pressure guess when the runtime mode is `seed_start`
- the application path is conservative and explicit
- the old behavior remains available via mode selection and automatic fallback
- live calibration measurements still remain authoritative

What did not change:

- no Bayesian or ML logic
- no automatic acceptance of priors as truth
- no removal of existing verification logic

## Files Changed

- `FreeRTOS-interface/CalibrationMemoryStore.py`
- `FreeRTOS-interface/CalibrationClasses/Model.py`
- `tests/test_calibration_prior_application.py`
- `docs/calibration_memory_impl_phase4.md`
- `docs/calibration_prior_application.md`

Phase 4 builds on the existing Phase 3 files:

- `FreeRTOS-interface/CalibrationMemoryAggregator.py`

## New Configuration

New runtime config file:

- `local/CalibrationMemory/config.json`

Default mode:

- `advisory`

Current supported modes:

- `off`
- `advisory`
- `seed_start`

`aggressive` is accepted as a forward-compatible alias but currently behaves like `seed_start`.

## Prior Application Hook

Primary hook:

1. `CalibrationManager.begin_session()`
2. `CalibrationManager._start_calibration_memory_run()`
3. prior lookup populates `prior_candidate`
4. `CalibrationManager._try_start_process()`
5. `CalibrationManager._prepare_calibration_memory_prior_application()`
6. seed kwargs are injected only for eligible pressure-finding processes

Current runtime targets:

- `PressureBandCalibrationProcess`
- `PressureCalibrationProcess`

Applied seed behavior:

- `PressureBandCalibrationProcess(start_pressure=...)`
- `PressureCalibrationProcess(seed_pressure=...)`

## Qualification Policy

Active seeding is currently allowed only for:

- `exact_pair`
- `exact_reagent_head_type`

Current default checks:

- aggregation level must be allowed
- confidence must meet the configured minimum
- pulse distance must be within `100 us`
- prior age must be within `365 days` if timestamped
- target-volume mismatch must be within policy when a target is provided
- inferred or unknown identity is rejected for active seeding
- prior must contain a usable recommended pressure or pressure band

Grouped fallback priors are still available for advisory lookup, but not for active application.

## Seeded Initialization Behavior

Phase 4 only changes the initial guess.

Current seed derivation:

- use `recommended_pressure_psi` when available
- else use the midpoint of `stable_single_droplet_band_psi`
- else use the midpoint of `trajectory_pressure_band_psi`
- clamp to machine pressure bounds when necessary

What remains authoritative:

- the pressure scan state machine
- replicate classification
- pressure-band verification
- downstream trajectory and characterization results

## Fallback Behavior

Fallback is automatic and conservative.

Current trigger:

- if the first seeded pressure probe lands inside the predicted single-droplet band but the observed verdict is not `single`
- or if the first seeded probe is very close to the predicted pressure but clearly mismatched

Fallback action:

- mark the prior as rejected for further runtime use in the current session
- append a `prior_application_fallback` sidecar observation
- keep running the normal calibration logic

Because Phase 4 only seeds the initial guess, the algorithm naturally returns to the original measurement-driven path after the first live observation.

## Telemetry Added

Run summary fields:

- `prior_application_mode`
- `prior_lookup_performed`
- `prior_candidate_found`
- `prior_qualified`
- `prior_candidate`
- `prior_applied`
- `prior_application_reason`
- `prior_rejected_reason`
- `prior_seed_values`
- `prior_fallback_triggered`
- `prior_fallback_reason`
- `prior_qualification`
- `prior_usefulness_summary`

New raw observation types:

- `prior_application_decision`
- `prior_seed_probe`
- `prior_application_fallback`

Current usefulness metrics include:

- whether lookup happened
- whether a candidate was found
- whether the prior qualified
- whether it was applied
- which process used the seed
- pressure probe count
- first probe details
- steps until first `single` verdict
- first single pressure
- fallback status
- actual-vs-prior pressure and volume deltas when available
- a coarse usefulness signal (`likely_helpful`, `possibly_helpful`, `mismatch`, `inconclusive`)

## Known Limitations

- only pressure-seeding is implemented
- grouped priors do not actively steer runtime yet
- fallback currently disables further prior use in-session but does not restart the current process from a baseline seed
- usefulness tracking is heuristic and intended for evaluation, not automatic optimization
- no UI control was added; the feature is configured via `local/CalibrationMemory/config.json`
