# Milestone 9 Slice 2 Completion Record

Status: complete (2026-08-08)

## Scope and implementation

Slice 9.2 added exact, bounded dispense-count evidence without publishing a
requantization matrix. The calibration page driver now retains all seven
visible preview headers and every displayed cell. Durable intent evidence now
includes `commanded_droplets`, while instance-local instrumentation retains
the corresponding simulator `DISPENSE` command, count, manual flag, sequence,
and terminal status with a fail-closed 10,000-command bound.

The new deterministic count module normalizes exact stock/well identities and
captures authoritative plan targets, decoded persisted progress targets and
added counts, reconstructed runtime targets, preview projections, durable
intent counts, and simulator counts. The required
`execution.dispense_counts_reconciled` assertion is active for the existing
mixed-mode journey and completed mixed-mode matrix cases. Its evidence is
retained additively at
`metrics.persistence.values.dispense_count_evidence`.

The assertion is explicitly scoped to Slice 9.2 internal self-consistency.
Independent expected requantized counts remain deferred to the typed catalog
introduced in Slice 9.3. No production MVC, simulator behavior, fixture,
matrix catalog, report schema, protocol, firmware, or physical-hardware code
changed.

## Exact evidence result

The representative case and retained-command replay both proved:

- all nine required layers reconciled exactly: prepared plan, calibration
  preview, calibrated plan, zero-progress targets, runtime, intent, simulator,
  terminal targets, and terminal added counts;
- 48 durable intents joined one-to-one with 48 completed non-manual simulator
  `DISPENSE` commands;
- two manual-refuel dispense commands remained retained and explicitly
  unattached to execution intents;
- prepared revision 1 advanced through calibrated revision 4 and terminal
  revision 5 with one plan identity and two contiguous calibration
  transitions;
- each calibrated stock had zero added progress at its own Apply boundary;
- all exact rendered preview headers and cells were retained;
- report-v1 validation and classification passed with no count mismatch,
  overflow, hardware access, unexpected dialog, timeout, or process/report
  disagreement.

## Compatibility evidence

- no production matrix or case was added;
- mixed-mode catalog SHA-256 remains
  `d2439c2e47cb9825ad5a5024e014fd4429ff6b28dcafa54809c92fa674cff884`;
- representative case SHA-256 remains
  `739dcba583d1d09a8db55eab58c1def80d70304ec98a2768b5e63b98f203a951`;
- the frozen seed-7 dry-run plan hash test remains green;
- report-v1 and matrix schema versions remain unchanged;
- CLI selection and retained replay behavior remain unchanged.

## Targeted validation

- page-driver, observer, dispense-count, assertion, journey-phase,
  composition, and contract tests: 83 passed;
- frozen matrix catalog and deterministic plan hash tests: 2 passed;
- opted-in composed mixed-mode lifecycle: 1 passed with 18 existing Qt
  deprecation warnings;
- one fresh-process `mixed_ab_baseline_pass` case: passed, 48/48 completions;
- exact retained-command replay of that case: passed, 48/48 completions;
- `git diff --check`: passed with line-ending notices only.

Per the approved Milestone 9 validation policy, the complete eight-case matrix
and unfiltered Python suite were not run. They remain required once in Slice
9.6 after all Milestone 9 slices are complete.

## Retained representative reports

| Run | Report | SHA-256 |
|---|---|---|
| primary | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T081741222930Z_composed/report.json` | `1d349cb844faeb5e224cf14d03cd1b83bea4a7c32620f838958f197652fc09e4` |
| retained replay | `verification_reports/matrices/mixed_mode_calibration_v1/20260808T081759877464Z_composed/report.json` | `1e226630ab82a7f869e5b5c6c580ce57f8565e8d244f63238ef28110563b6017` |

## Risk, next step, and rollback

The current required assertion intentionally accepts only the existing
single-row, single-stock preview projection and idempotent prepared/final
counts. Slice 9.3 will replace the self-derived expectation with independently
frozen idempotent, count-increase, and count-decrease case expectations.

Rollback reverts the page-driver, observer, count module, journey/assertion,
tests, and documentation together. Retained reports remain historical and no
application data migration or cleanup is required.
