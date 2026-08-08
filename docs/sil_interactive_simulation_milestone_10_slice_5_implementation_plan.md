# Milestone 10 Slice 10.5 Implementation Plan

Status: complete (2026-08-08); see
`docs/sil_interactive_simulation_milestone_10_slice_5_completion_record.md`

## Objective and non-goals

Append `exact_custom_capacity`, `capacity_plus_one_rejected`, and
`fixed_stock_exceeds_max_rejected` to complete the nine-case executable
experiment-design matrix. Prove exact-capacity finalization and authoritative
reload, plus two real Finalize Design rejections with exact warning evidence,
byte-identical draft directories, absent finalization-owned execution
artifacts, an unchanged draft progress file, inactive runtime, and zero
intent/simulator/completion activity.

Do not change production MVC behavior or warning text, bypass a safeguard,
add printing/calibration/execution cases, change schemas, or touch firmware,
protocol, hardware, motion, pressure, timing, or physical calibration.

## Exact call paths

Positive boundary:

```text
matrix selector -> fresh child -> typed exact-capacity case
-> Qt New/configuration/custom wells -> Optimize and Generate
-> Qt Finalize Design -> MainWindow -> application Model authoritative files
-> Qt reload -> exact reconstructed B1-B4 assignment
```

Capacity rejection:

```text
typed 5-reaction/4-well case -> Qt configuration
-> successful Optimize and Generate -> immediate directory/runtime baseline
-> Qt Finalize Design -> Insufficient Well Capacity warning
-> retained warning screenshot -> dismiss -> exact post-attempt snapshot
-> rejected-finalization no-mutation assertion
```

Formulation rejection:

```text
typed fixed-stock-above-max case -> Qt configuration remains dirty
-> immediate directory/runtime baseline
-> Qt Finalize Design -> production optimization flow
-> Optimization failed warning -> retained warning screenshot -> dismiss
-> exact post-attempt snapshot -> rejected-finalization no-mutation assertion
```

Controller remains idle and is observed only as negative evidence. No comms or
firmware handler is reached.

## Initial files expected to change

- `tools/virtual_workflows/experiment_design_cases.py`
- `tools/virtual_workflows/actions.py`
- `tools/virtual_workflows/assertions.py`
- `tools/virtual_workflows/journeys.py`
- `tools/virtual_workflows/editor_reporting.py`
- inspect `tools/virtual_workflows/manifests/capability_coverage_v1.json`, but
  leave it unchanged because matrix-only evidence must not enter registered
  scenario capability aggregation
- focused catalog, selector, action/assertion, reporting, contract, capacity,
  and stock-input tests
- `tests/system/test_virtual_workflow_experiment_design_matrix.py`
- this slice completion record and Milestone 10 status/current-action text

The existing page driver and journey phase already pass an unrestricted typed
specification to the bounded editor implementation. Existing
`snapshot_directory()`, simulator command history, instrumentation lifecycle,
and cleanup evidence are sufficient; no page-driver, journey-phase,
authoritative-evidence, fixture, matrix-runner, or production change is
expected.

## Implementation steps

1. Correct the exact-capacity case's independent 9 nL Water ceiling counts,
   append cases 7-9, and re-freeze only affected case/catalog/plan identities.
2. Add expected terminal metadata to the additive editor specification while
   preserving the legacy prepared default.
3. Generalize the bounded Qt driver so prepared cases retain their current
   path, capacity rejection generates before Finalize, and formulation
   rejection reaches optimization only through Finalize.
4. Capture the immediate pre/post directory, artifact, dialog, runtime,
   Controller, intent, completion, and simulator-command evidence and retain a
   warning-visible milestone before dismissal.
5. Add exact rejected-action and shared
   `experiment.finalization_rejected_no_mutation` assertions, dynamic report
   evidence, and screenshot requirements. Keep the IDs matrix-local because
   the static capability schema requires every assertion to be emitted by a
   registered scenario.
6. Add focused and fresh-process contracts for cases 7-9, including mutation,
   dialog, capacity, action-leakage, and zero-dispatch failure checks.
7. Run/replay all three selectors offscreen and visibly, inspect retained
   warnings/mappings/inventories, update records, run `git diff --check`, and
   commit as `test: add experiment design rejection boundaries`.

## Contracts, validation, and evidence

The exact-capacity case must prepare four reactions in exactly `B1`-`B4` and
reload without directory mutation. The capacity case must display
`Insufficient Well Capacity`, `Required reactions: 5`, and available-well
quantity `4`. The formulation case must display `Optimization failed` and
`exceeds max stock` after the real Finalize click.

Both negative baselines occur immediately before Finalize. The full draft
directory inventory and hashes must be byte-identical afterward. Execution
plan, revision directory, key, concentration key, resume, and runtime
assignment artifacts must remain absent. The normal New Experiment path may
have already created draft `progress.json`; if present in the immediate
pre-Finalize baseline, it must remain byte-identical. Runtime must remain
inactive; Controller/array state must remain idle; and intents, command
attachments, completions, simulator command events, and observed well
completions must remain zero.

Run the approved Slice 10.5 focused command, selected cases 7-9 in fresh
processes, exact offscreen replays, and visible run/replay for all three. The
complete matrix aggregate/replay, lifecycle/host regression suites, and full
Python suite remain deferred to Slice 10.6.

## Compatibility, risks, rollback, entrance, and exit

Keep cases 1-6, Milestone 7-9 identities, report-v1, matrix plan/aggregate v1,
replay formatting, the reference fixture, positive editor action order,
manual-assignment precedence, RNG behavior, and production safeguards
unchanged. The new assertion/report fields are additive within report-v1.

Risks are baselining before draft generation, accidentally accepting the
dialog after rejection, or proving only named files while another file
changes. Baseline immediately before Finalize, compare the complete directory,
and separately require finalization-owned execution artifacts absent plus any
preexisting draft progress file unchanged. Any production mutation or
incorrect warning is a blocker for a separate correction plan.
Rollback reverts this slice commit and restores the six-case prefix.

Entrance is clean Slice 10.4 commit `6e3900e`. Exit requires all three cases
and their offscreen/visible replays, exact warning and no-mutation evidence,
unchanged cases 1-6, focused tests, manual evidence inspection, completion
record, `git diff --check`, and one clean focused commit.
