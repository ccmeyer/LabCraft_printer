# SIL Pulse-Aware Calibration Schema Version 3

Milestone 4D adds pulse-aware request/result contracts for new application
generation. It does not replace or reinterpret schema v1 or v2 artifacts.

## Identity and request

Requests use `labcraft.sil_calibration_request`, schema version `3`, provider
`milestone-4d-v1`, profile version `3`, and response model
`labcraft.sil_pulse_ejection_response` version `1`. Supported application
profiles are `nominal_droplet`, `droplet_to_stream`, `nominal_stream`, and
`stream_to_droplet`.

Each request retains seed, virtual run, printer-head, stock, factor,
option/fill, requested-mode, and source-volume identity. It also records exact
`print_pressure_psi`, `print_pulse_width_us`, `response_model_id`, and
`response_model_version`. Missing or unknown fields, unsupported identities,
non-finite values, mode/profile mismatches, and out-of-band pulse widths fail
closed.

## Response

The applied profile mode selects one inclusive linear segment:

```text
droplet: 1300 us = 9 nL; 1800 us = 18 nL
stream:  2500 us = 60 nL; 10000 us = 250 nL
```

Interpolation is linear and rounded to nine decimals. There is no clamping or
extrapolation; 1801–2499 us is unsupported. Pressure and seed are retained as
provenance but do not affect volume in model version 1.

Results use `labcraft.sil_calibration_result`, schema version `3`, and repeat
the complete request. They retain the established fingerprints,
measured/effective volume, original/applied modes, settings, virtual timestamp,
run/phase, six-field source-row fingerprint, validation state, and existing-
compatible droplet or stream application shapes.

Canonical JSON remains UTF-8 with sorted keys, compact separators,
`ensure_ascii=False`, and `allow_nan=False`. The result fingerprint excludes
only its own field. Timestamp derivation remains fingerprint-based within the
fixed year-2000 virtual epoch. Generation uses no random state.

## Compatibility and limitations

V1 and v2 serialization, generation, and golden fingerprints are unchanged.
They remain readable historical evidence. Historical pre-v3 synthetic
candidates are read-only because they do not prove a pulse-to-volume
relationship; existing authoritative experiment state is not migrated.

V3 evidence explicitly states that the response is synthetic, linear, and not
empirical, and that pressure is not modeled as a volume input. It provides no
physical ejection, volume-accuracy, camera, refuel, firmware, protocol,
collision, or hardware evidence.
