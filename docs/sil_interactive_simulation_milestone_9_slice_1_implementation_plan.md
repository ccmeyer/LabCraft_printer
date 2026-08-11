# Milestone 9 Slice 1 Implementation Plan

## Objective

Refactor the existing mixed-mode matrix implementation behind a generic,
fail-closed registry and journey-dispatch boundary. Preserve all current CLI
behavior, hashes, schemas, reports, fixtures, and eight mixed-mode cases
exactly. Do not register `calibration_requantization_v1` until Slice 3 has
executable cases.

## Call path

`CLI matrix selection -> matrix registry and plan validation -> fresh-process
matrix runner -> journey-family dispatch -> existing mixed-mode
Qt/Controller/Model/simulator journey -> report and aggregate validation`.

The application-facing journey remains simulation-only. This slice does not
change production MVC, simulator, fixture, capability-manifest, protocol,
firmware, or physical-hardware behavior.

## Implementation

1. Add frozen `MatrixDefinition` and fail-closed `MatrixRegistry` contracts,
   with the existing mixed-mode catalog as the only production definition.
2. Preserve the module-level matrix helpers as compatibility wrappers and
   freeze the existing catalog and representative plan hashes in tests.
3. Resolve matrix-runner plan validation and optional child expectations from
   the selected definition instead of mixed-mode constants.
4. Dispatch single cases by the definition's base scenario and journey family,
   rejecting unknown families before application construction.
5. Prove multiple-definition behavior with test-local synthetic definitions;
   do not expose a placeholder operator catalog.
6. Run focused contracts, the existing real-process matrix system test, the
   complete eight-case matrix and replay, and the complete Python suite.
7. Inspect retained evidence, record exact results, and close the slice in one
   independent commit.

## Compatibility gates

- `MATRIX_SCHEMA_VERSION` and `MATRIX_AGGREGATE_SCHEMA_VERSION` remain `1`.
- report-v1 remains unchanged.
- mixed-mode catalog SHA-256 remains
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`.
- the frozen representative dry-run plan SHA-256 remains
  `543bec9aa811508fcba2bb84e0549054ddbffc6d10bc85ec2ed88353f971ab9f`.
- `--list matrices` still exposes only `mixed_mode_calibration_v1` with the
  same eight ordered cases.
- existing aggregate `expected_terminal` and `expected_completion_count`
  fields remain present for every mixed-mode child.

## Safety, failure handling, and rollback

Malformed definitions, duplicate matrix/case IDs, reserved metadata keys,
unknown matrices/cases/families, catalog drift, and case drift fail closed.
No test may publish an empty or synthetic production matrix. Rollback reverts
the registry/dispatch commit and restores the direct mixed-mode path; retained
evidence remains historical and no application-data migration is required.
