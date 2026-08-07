# Milestone 8 Slice 5 — Parameterized Scenario Matrices

Status: implemented and qualified (2026-08-07)

## Summary

Add one operator-invoked eight-case calibration matrix that reuses the composed
multi-stock journey and normal Qt controls. Cases cover mixed, droplet-pair,
and stream-pair modes, both stock orders, baseline and alternate calibration
profiles, successful refuel checks, and failed-rise, failed-fall, and unclear
checks that select the default-safe Cancel response and prove no print began.

The matrix uses typed case records and one in-memory builder derived from the
tracked mixed-mode fixture. It does not create a fixture or journey body per
case. Every case runs in a fresh Windows Python child and retains report-v1
evidence beneath `verification_reports/matrices`.

## Contracts

- Matrix ID: `mixed_mode_calibration_v1`.
- Plan schema: `labcraft.virtual_workflow_matrix_plan` v1.
- Aggregate schema: `labcraft.virtual_workflow_matrix_aggregate` v1.
- CLI: `--matrix`, optional `--case`, `--dry-run`, and `--list matrices`.
- Matrix runs reject Pi, repetition, fault injection, baseline, comparison,
  and scheduling controls.
- Negative cases must prove the matching persisted non-pass, preflight code,
  Start-confirmation/Cancel order, no bypass, no new execution intent or
  completion, idle state, drained queue, closed modal, returned head, and clean
  teardown.
- Matrix evidence remains separate from registered capability coverage.

## Implementation and validation

1. Add the typed catalog, profiles, pairwise audit, case hash, and in-memory
   fixture builder.
2. Generalize stock-pass ordering, zero/one/two stream checks, and expected
   safeguard cancellation while preserving registered journey defaults.
3. Add matrix case assertions, report evidence, and exact case replay.
4. Add fresh-process matrix aggregation using the Slice 3 child contract.
5. Add focused unit/system coverage.
6. Run the full matrix offscreen and its replay, then visibly run and replay
   `stream_pair_ab_baseline_pass` and `mixed_ba_baseline_unclear`.
7. Update README, roadmap, and the completion record only after qualification.

The complete pytest suite remains deferred to Milestone 8 Slice 8. Production
MVC, simulator, tracked fixtures, capability manifest, coverage evaluator,
protocol, firmware, Pi, scheduler, and hardware behavior are excluded.

## Risk and rollback

Same-mode cases may expose a production assumption; such a finding stops this
slice for a separate correction plan. Aggregate and child evidence fail closed
on identity, hash, report-count, return-code, timeout, or path disagreement.
Rollback removes the matrix selector, catalog, aggregation, case composition,
tests, and docs while retaining all registered scenario and suite evidence.
