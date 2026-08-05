# SIL Synthetic Calibration Schema Version 2

Schema version 2 is an additive, simulation-only directional transition
contract. It allows a normal droplet design such as 9 nL to produce a stream
calibration result without pretending that 40 nL belongs to a symmetric
variation interval around the source volume.

## Identity and compatibility

| Contract | `schema_id` | Version |
| --- | --- | ---: |
| Request | `labcraft.sil_calibration_request` | 2 |
| Result | `labcraft.sil_calibration_result` | 2 |

Provider version 2 is `milestone-4c-v2`. The supported profile is
`droplet_to_stream` at profile version 2. Schema v1, provider
`milestone-3-v1`, profile version 1, and every existing v1 fingerprint remain
unchanged. Readers dispatch by schema version and reject unknown versions.

## Request

The request retains the v1 seed, virtual run, printer-head, stock,
factor/option/fill, pressure-bound, and pulse-width-bound identities. It uses:

| Field | Requirement |
| --- | --- |
| `requested_mode` | Exactly `droplet` |
| `source_volume_nL` | Finite, inclusive 1 nL and strictly below 40 nL |
| `target_volume_nL` | Finite and within the inclusive 40-250 nL stream envelope |

The application adapter derives `source_volume_nL` from the authoritative
current design/effective volume and requests an exact 40 nL target. Missing or
unknown fields, unsupported identities, non-finite values, and invalid bounds
fail closed.

## Result

The result repeats every request input and adds the same self-contained
identity, measurement, mode, settings, timestamp, source-row fingerprint,
application-validation, and limitation fields as schema v1. For the supported
transition:

- measured and effective volume exactly equal `target_volume_nL`;
- original mode is `droplet` and applied mode is `stream`;
- phase is `stream`;
- the summary row retains `source_volume_nL` and `target_volume_nL` for visible
  directional provenance;
- the stream evidence warning and fixed synthetic limitations remain present.

Canonical JSON, SHA-256 request/result fingerprints, request-local seeded
randomness for bounded pressure/pulse selection, and the fingerprint-derived
year-2000 timestamp use the v1 algorithms. The exact target volume is not
randomized.

## Evidence and application

Canonical request/result artifacts use the existing layout:

```text
artifacts/synthetic-calibration/<application_session_id>/<result_fingerprint>/
  request.json
  result.json
```

V1 and v2 artifacts may coexist. Historical rows are exposed only when an
artifact validates canonically and matches an authoritative execution-
calibration record. The provider still supplies no camera, segmentation,
physical ejection, pressure-response, refuel, motion, collision, firmware, or
protocol evidence. Application continues through the existing preview,
mode-switch confirmation, ExperimentModel, Controller settings, authoritative
writers, and manual-refuel preflight.
