# Milestone 7 Slice 2.5 Completion Record

Status: `complete`

Date: `2026-08-06`

Baseline: `04594f37966bc3e41b025004733f17a70094672b`, plus the intentionally
uncommitted Milestone 7 Slice 2 worktree.

## Outcome

The smoke, editor create/finalize, and two-stock 24x2 composed workflows now
share one typed composition and finalization path. No workflow was migrated in
this slice; all three existing scenario, fixture, UI-surface, assertion,
report-v1, failure, evidence, and teardown contracts were preserved.

The registry now sends every `runner_family="composed_journey"` scenario to
`run_composed_journey()`. The registered `JourneyDefinition` selects the
fixture, typed body, required actions/assertions/screenshots, artifact policy,
scenario metric payload, and summary without another scenario-ID branch.

No fixture, capability-manifest JSON, page driver, production MVC, simulator
response model, legacy runner, Pi tool, firmware, protocol, or hardware file
was changed for Slice 2.5. The existing `AutomationHarness` API was sufficient
and did not require modification.

## Implemented Composition Boundary

- `SemanticStep` validates one stable action ID, truthful interaction surface,
  bounded operation, optional precondition, and dialog policy.
- `JourneyDefinition` freezes scenario identity and the action, assertion,
  screenshot, fixture, artifact, payload, and summary contracts.
- `JourneyRuntime` owns fresh per-run observations and restores registered
  observers in reverse order exactly once while retaining their snapshots.
- `JourneyExecutor` owns launch, body execution, success-contract validation,
  failure capture, restoration, teardown, incomplete assertions, artifacts,
  report construction, ledgers, summary, evidence manifest, and return.
- `MachineStartupSpec`, `EditorPreparationSpec`, and `StockPassSpec` feed
  reusable machine/editor/stock phases. A normalized plan can be inspected
  without constructing Qt or application objects.
- `ExecutionLifecycleExpectation` provides a typed input for reusable terminal
  lifecycle assertions while the Slice 2 public helper remains as a
  compatibility wrapper.
- `ComposedReportPayload` and `ComposedReportAdapter.build()` replace the three
  separate report-envelope functions. A stable projection helper supports
  before/after and replay comparison.

## Concision Measurements

Before Slice 2.5, `journeys.py` contained about 1,806 lines. Its three journey
functions plus their report builders occupied about 1,342 lines:

| Scenario | Previous journey | Previous report | New body | Compatibility runner |
|---|---:|---:|---:|---:|
| 24-well smoke | 207 | 197 | 35 | 2 |
| editor create/finalize | 124 | 185 | 50 | 2 |
| two-stock 24x2 | 458 | 171 | 56 | 2 |

`journeys.py` is now about 798 lines including fixtures-to-spec adapters,
scenario metric payloads, definitions, and compatibility exports. The detailed
bounded Qt lifecycle implementation lives once in the approximately 589-line
`journey_phases.py`, while the generic executor/contracts occupy approximately
302 lines in `composition.py`.

The implementation meets the approved gates: every public runner is below 80
lines, every journey body is below 120 lines, the three scenario-specific
report functions are removed, machine startup and stock-pass orchestration
each have one implementation, and registry dispatch has no composed
scenario-ID conditional.

## Matrix Readiness

Pure unit tests construct different ordered `StockPassSpec` sequences and
verify the normalized action plan without adding a runner or registered
scenario. The two-stock plan retains exactly two settings, volume, stage,
calibration, start, boundary-validation, and return groups, one pressure-enable
group, and one explicitly `model`-surface head-identity binding.

This slice does not activate a scenario matrix or seeded sequence generator.
Those remain separately planned later work.

## Focused Validation

The approved targeted-only policy was used. The complete Python suite was not
run and remains deferred to the final Milestone 7 validation.

- Pre-refactor composed baseline: `9 passed`, including success, legacy parity,
  and controlled failure paths.
- Shared session/harness/composition/phase/driver/action/assertion/observer/
  report/manifest/contract tests: `161 passed`.
- Calibration, normal-UI convergence, execution plan, progress, and resume
  adjacency tests: `84 passed`.
- Smoke lifecycle file: `2 passed`.
- Editor composed lifecycle file: `4 passed`.
- Multi-stock composed lifecycle file: `3 passed` together in 19.92 seconds;
  its success, parity, and fail-closed nodes also passed independently.
- CLI help, Python compilation, and `git diff --check` passed.

One combined lifecycle invocation became quiet for more than three minutes and
was terminated at the user's direction. Its two orphaned Python processes were
stopped. Isolation showed no failing node: smoke and editor files passed, each
multi-stock node passed independently, and the complete multi-stock file then
passed within a 60-second cap. This was treated as transient in-process Windows
Qt/pytest behavior, not as an accepted test failure.

Pytest's reused default OS temporary root also produced one Windows access
error. A first workaround under the repository was correctly rejected by the
SIL root-overlap safety guard. The successful reruns used fresh explicit roots
under `%TEMP%\LabCraft`.

## Pre/Post And Replay Parity

One direct report for each composed journey was retained before and after the
refactor. All three stable projections were exactly equal, including:

- schema, scenario, workload, version, seed, and fixture fields/hash;
- ordered action IDs, interaction surfaces, and statuses;
- ordered assertion IDs and decisions;
- milestone and screenshot names;
- expected dialogs, no unexpected dialogs, no errors, and pass classification;
- assertion-decision maps.

The direct smoke, editor, and multi-stock post-refactor runs all passed.

The visible two-stock run passed with 48 completions, 42 actions, 11 passing
assertions, and no retained session lock. Its exact emitted replay command also
passed. Their stable projections were equal, and both retained roots were
lock-free after close.

Primary visible report:

```text
verification_reports\milestone7-slice2-5-visible\print_array_multi_stock_24x2_v1\20260807T004420043732Z_composed
```

Exact replay report:

```text
verification_reports\milestone7-slice2-5-visible\print_array_multi_stock_24x2_v1\20260807T004436331653Z_composed
```

The pre-refactor, post-refactor, unit-test, and visible evidence roots are
ignored local validation artifacts and are not added to Git.

## Risks And Limitations

- The new phase module is intentionally detailed because it owns Qt timing,
  expected dialogs, evidence, pass boundaries, and cleanup once. Future named
  journeys should add short specifications/compositions, not copy that module.
- The pure normalized plan is matrix-ready, but an active matrix runner and
  state-aware seeded legal/illegal sequence exploration are not implemented.
- Compatibility wrappers remain for direct imports while registry dispatch is
  generic.
- This remains application-facing SIL. It makes no firmware, protocol,
  physical head handling, motion, collision safety, pressure-response, camera,
  balance, volume-accuracy, or droplet-quality claim.
- The full pytest suite remains required at the final Milestone 7 gate.

## Rollback

Restore only the pre-Slice-2.5 versions of `assertions.py`, `journeys.py`,
`registry.py`, and `report.py`; remove `composition.py`, `journey_phases.py`,
and their focused tests; and restore the README/roadmap wording. The smoke,
editor, and multi-stock scenarios then return to their independently wired
composed functions.

Do not revert Slice 2 fixtures, page drivers, actions, observer, capability
claims, production state, or retained evidence. No firmware/protocol, Pi, or
hardware rollback is required.

## Next Step

Stop before Slice 3. Review this completion record and create a concrete plan
for the prepared edit/refinalize migration using the typed composition layer.
