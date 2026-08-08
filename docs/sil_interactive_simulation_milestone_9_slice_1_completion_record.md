# Milestone 9 Slice 1 Completion Record

Status: complete (2026-08-08)

## Scope and implementation

Slice 9.1 placed the existing mixed-mode parameter matrix behind a generic,
fail-closed `MatrixDefinition` and `MatrixRegistry`. The production registry
still contains only `mixed_mode_calibration_v1`; no empty, placeholder, or
requantization catalog was published.

The matrix runner now validates the selected registered definition rather than
mixed-mode constants. Single-case execution resolves its base scenario from
that definition and dispatches through a bounded journey-family map. Existing
module-level helpers remain compatibility wrappers. Test-local definitions
prove multiple catalogs, independent hashes, fixture routing, child command
construction, aggregation, and stub journey dispatch without entering the
operator catalog.

This slice changed no production MVC, simulator, fixture, capability manifest,
report schema, protocol, firmware, or physical-hardware behavior.

## Compatibility evidence

- matrix plan schema remains version 1;
- matrix aggregate schema remains version 1;
- report-v1 remains unchanged;
- the production operator catalog still contains the same eight ordered
  mixed-mode cases and no other matrix;
- mixed-mode catalog SHA-256 remains
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`;
- the frozen representative unauthorized dry-run plan SHA-256 remains
  `543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f`;
- existing child `expected_terminal` and `expected_completion_count` fields
  remain present, while test-local cases prove other `expected_*` fields can be
  retained without requiring the mixed-mode pair.

## Automated validation

- focused registry, runner, composition, and contract validation: 34 passed;
- real-process matrix lifecycle validation with `--run-sil-lifecycle`: 1
  passed in 51.42 seconds;
- complete default Python suite: 4,084 passed, 72 intentionally skipped, 389
  warnings, zero failures in 228.95 seconds;
- `git diff --check`: passed.

The lifecycle test is intentionally skipped without `--run-sil-lifecycle` and
was rerun with that explicit qualification flag.

## Matrix and replay evidence

| Run | Result | Aggregate | SHA-256 |
|---|---|---|---|
| primary | 8/8 pass | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T074849502164Z_101de944-a89/aggregate.json` | `28b8bba0d581df6d159ff52d2d7cd945375e896ee9216894be8e6074947e3b4b` |
| retained-command replay | 8/8 pass | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T074957990336Z_a3e2839e-2b1/aggregate.json` | `d684013c3750729c0cdf819a0f7b78277d0416510669f9fe8e85d2a471fba358` |

The two aggregates have identical catalog identity, case order, case hashes,
normalized parameters, expected outcomes, and child classifications. All 16
child reports passed report-v1 validation. Every child process returned zero
without timeout or launch failure, retained empty unexpected-dialog evidence,
identified the `SIMULATED` port, prohibited hardware access, and reported all
hardware interfaces disabled.

No visible or Raspberry Pi qualification was required because this slice did
not change UI behavior or platform scope.

## Risks, next step, and rollback

Only the mixed-mode journey family is registered in production. Slice 9.2 will
add exact preview/intent/simulator count evidence without registering new
matrix cases. The real `calibration_requantization_v1` definition remains
deferred to Slice 9.3 when its first three cases are executable.

Rollback reverts the Slice 9.1 registry, runner, dispatch, CLI, tests, and
documentation together, restoring the direct mixed-mode path. Retained
evidence remains historical; no application-data migration or cleanup is
required.
