# Calibration Prior Application

## Modes

Configured in:

- `FreeRTOS-interface/CalibrationMemory/config.json`

Modes:

- `off`: skip lookup and skip application
- `advisory`: lookup only, no runtime effect
- `seed_start`: use a qualified prior to seed the initial pressure guess

Default:

- `advisory`

## What Active Application Can Steer

Phase 4 can currently steer only the initial pressure guess for:

- `PressureBandCalibrationProcess`
- `PressureCalibrationProcess`

It does not:

- skip verification
- lock in a final pressure
- bypass replicate classification
- replace pressure-band discovery

## Allowed Prior Types For Active Use

Allowed:

- `exact_pair`
- `exact_reagent_head_type`

Not currently allowed for active use:

- `reagent_family_head_type`
- `reagent_only`
- `head_type_only`

Those lower levels remain advisory.

## Qualification Rules

A prior qualifies for `seed_start` only if all checks pass:

- allowed aggregation level
- confidence above configured threshold
- pulse width close enough to the requested pulse width
- not stale by policy
- no weak/inferred identity in the contributing bucket
- compatible target volume if a target volume is supplied
- usable recommended pressure or pressure band available

Current default thresholds:

- exact pair: `0.80`
- exact reagent + head type: `0.78`
- max pulse distance: `100 us`
- max age: `365 days`
- max target-volume relative error: `25%`

## Seed Derivation

Order of preference:

1. `recommended_pressure_psi`
2. midpoint of `stable_single_droplet_band_psi`
3. midpoint of `trajectory_pressure_band_psi`

The seed is clamped to hardware pressure bounds before application.

## Fallback

Fallback is triggered when early live observations strongly disagree with the seeded prior.

Current mismatch rules:

- seeded pressure lies inside the predicted single-droplet band but the observed verdict is not `single`
- or the seeded pressure is very close to the predicted pressure but the observed verdict is clearly inconsistent

Fallback behavior:

- mark the prior as no longer trusted for runtime use in the current session
- append a `prior_application_fallback` observation
- continue with the existing calibration logic

## What Is Recorded

Run summary:

- mode
- candidate prior
- qualification result
- whether the seed was applied
- seeded values
- fallback status
- usefulness summary

Raw sidecar observations:

- lookup event
- application decision
- seeded probe records
- fallback trigger

## Current Safety Boundaries

- active seeding is opt-in
- grouped priors do not steer runtime
- weak identity does not drive strong runtime decisions
- the first live observation can invalidate the seed
- measured behavior always outranks prior expectations

## Next-Phase Candidates

Possible future work after Phase 4:

- optional UI toggle for the mode
- seeding of search ordering around a trusted prior band
- stricter usefulness analytics against larger datasets
- broader but still conservative grouped-prior application policies
