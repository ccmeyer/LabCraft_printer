# Milestone 8 Slice 4 — Capability Coverage and Source Freshness

Status: implemented and qualified (2026-08-07)

## Summary

Add an offline, operator-invoked coverage evaluator that joins one or more
explicitly selected Slice 3 aggregate reports to the tracked capability
manifest. It will validate the aggregate and its transitive report hashes,
then assess scenario presence, required assertions, required semantic actions,
declared interaction surfaces, verification layers, and source identity.

The evaluator will distinguish `pass`, `fail`, `incomplete`, `missing`, and
`stale`; it will not treat the existence of a report as coverage. It will
write a versioned machine-readable evaluation and a deterministic text summary
under the existing `verification_reports/suites` root. Generated evidence will
never edit the tracked manifest.

This slice is read-only with respect to the application. It does not run a
workflow, schedule tests, scan for a convenient “latest” result, or import Qt
or application modules. No production MVC, simulator, protocol, firmware, Pi,
matrix, sequence-exploration, performance-baseline, or hardware behavior will
change. The complete pytest suite remains deferred to Milestone 8 Slice 8.

## Call Path and Interfaces

The only new call path is:

`--coverage-from aggregate.json` → transitive aggregate/report validation →
tracked manifest join → source/action/assertion assessment → coverage JSON/text

Add a repeatable, mutually exclusive CLI selector:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --coverage-from <aggregate.json> `
  [--coverage-from <second-aggregate.json>] `
  --output-root verification_reports\suites
```

The operator must name every aggregate. Coverage mode accepts only
`--coverage-from` and `--output-root`; scenario execution, planning, Pi,
visibility, timing, repetition, fault-injection, baseline, and comparison
controls fail closed. Its emitted replay command contains every input path in
the same order and an explicit output root.

When no output root is supplied, results are retained at
`verification_reports/suites/coverage/<timestamp>_<run-id>/` with:

- `coverage.json` — `labcraft.sil_capability_evaluation` schema v1;
- `summary.txt` — stable human-readable status, reasons, and evidence links.

Both files are written atomically without overwrite. The CLI prints the
evaluation path, SHA-256, replay command, and classification. Exit code `0`
means every in-scope capability passed, `2` means a complete evaluation found
any non-pass capability, and `3` means validation/orchestration/writing failed.

## Evaluation Contract

### Scope and joins

- A capability-selected aggregate evaluates only its named capability. A
  suite-selected aggregate evaluates the union of capabilities declared by its
  selected manifest scenarios. Other manifest capabilities are listed as
  out-of-scope and are not silently labelled covered.
- A capability is complete only when every manifest `active_scenario_id`
  applicable to the aggregate platform has authoritative evidence. A narrower
  suite therefore reports `incomplete` rather than making a portfolio-wide
  claim from one passing journey.
- Every candidate report must match the aggregate child registry/scenario ID,
  workload, seed, report hash, and classification. The report must contain the
  scenario’s manifest action and assertion IDs. Each action’s observed
  `interaction_surface` must match the manifest action catalog, so a Model or
  harness action cannot be presented as UI coverage.
- Capability `required_assertion_ids` must appear in the applicable scenario
  evidence and pass. Required verification layers, selected platform, report
  observable sources, action surfaces, limitations, and exact evidence paths
  are retained in both per-scenario and per-capability results.
- Byte-identical duplicate evidence is deduplicated. Conflicting candidates
  for one scenario are ambiguous and yield `incomplete` until the operator
  supplies an unambiguous input set; the evaluator never chooses a convenient
  latest result.

### Status precedence

For each in-scope capability, classify in this order:

1. `fail` — relevant authoritative evidence explicitly failed, a required
   assertion/action failed, or an observed interaction surface contradicts the
   manifest;
2. `missing` — no authoritative scenario evidence exists for the capability;
3. `incomplete` — some evidence exists but a required scenario, assertion,
   action, layer, identity field, or unambiguous candidate is absent;
4. `stale` — the evidence is otherwise complete and passing but its source
   fingerprint differs from the evaluation target;
5. `pass` — all obligations are present, passing, surface-correct, and
   source-current.

The aggregate’s failure is retained, but only a failing child relevant to a
capability makes that capability fail. This prevents an unrelated failed
journey from contaminating otherwise independent evidence while preserving the
failure in the input summary.

### Source freshness and age

Extend report-v1’s existing `source` object additively with a deterministic
`source_tree` identity. The fingerprint hashes canonical repository-relative
paths and file contents for Git-tracked and non-ignored execution/verification
inputs while excluding documentation, retained evidence, caches, and generated
runtime artifacts. It records the fingerprint algorithm/version, SHA-256, file
count, Git commit provenance, and any collection error; it never records file
contents. The same Qt-free collector supplies the evaluator’s target identity.

This permits matching evidence from the repository’s intentionally
uncommitted milestone worktree while still detecting a later source change.
Older reports without the fingerprint remain readable but cannot establish
current-source coverage and are `incomplete`; a complete report with a
different fingerprint is `stale`. Documentation-only closeout edits do not
invalidate execution evidence. Report-v1 and aggregate-v1 schema versions stay
unchanged because the new source fields are additive.

Evidence age is calculated from each report’s UTC completion time and the
capability’s `max_evidence_age_days`. Age and threshold-exceeded warnings are
reported, but never change the five-state decision under the approved manual,
operator-invoked policy.

## Implementation Steps

1. Add this approved plan and freeze the evaluation schema, explicit-input
   CLI, source fingerprint, status precedence, artifact layout, exit codes,
   gates, exclusions, risks, and rollback.
2. Extend the Qt-free source identity collector with the versioned,
   deterministic source-tree fingerprint; add compatibility and mutation tests
   proving code/fixture/manifest changes invalidate it while docs, reports, and
   caches do not.
3. Add `tools/virtual_workflows/coverage.py` with typed inputs/results,
   transitive aggregate loading, manifest indexing, root-contained evidence
   references, scenario/action/assertion/layer joins, duplicate handling,
   five-state classification, informational age, deterministic rendering,
   validation/loading, hashing, and atomic non-overwriting writers.
4. Integrate repeatable `--coverage-from` in the Qt-free CLI branch, reject all
   incompatible controls before writing, preserve every existing direct,
   planning, suite, capability, recommendation, baseline, and comparison path,
   and emit the exact coverage replay and defined exit codes.
5. Update the static manifest policy marker to record that the coverage join
   is implemented in Slice 4; do not add generated statuses, timestamps, paths,
   or hashes to the manifest and preserve
   `generated_evidence_updates_manifest: false`.
6. Add focused unit/contract coverage for all five statuses, status precedence,
   selected scope, missing portfolio members, required assertions/actions,
   every interaction surface, source match/mismatch/error/legacy reports,
   age-only warnings, failed unrelated children, ambiguous duplicates, hashes,
   path escape, no-overwrite behavior, summaries, replay, exit codes, and the
   absence of Qt/application imports.
7. Add a fast system regression that executes the real standard suite at high
   simulator speed, evaluates its aggregate, validates transitive hashes and
   expected incomplete portfolio claims, and proves direct scenario and Slice
   3 aggregate behavior remain compatible.
8. Qualify a fresh mixed-mode capability aggregate and its coverage replay,
   evaluate one retained pre-fingerprint aggregate as non-current evidence,
   then update README, roadmap, and the completion record with commands, paths,
   hashes, status counts, risks, and deferred full-suite validation.

## Exact Files

Implementation:

- `tools/virtual_workflows/coverage.py` — new
- `tools/virtual_workflows/report.py`
- `tools/run_virtual_workflow.py`
- `tools/virtual_workflows/manifests/capability_coverage_v1.json`

Tests:

- `tests/test_virtual_workflow_coverage.py` — new
- `tests/test_virtual_workflow_report.py`
- `tests/test_virtual_workflow_selection.py`
- `tests/test_virtual_workflow_manifest.py`
- `tests/test_virtual_workflow_contract_freeze.py`
- `tests/system/test_virtual_workflow_coverage_execution.py` — new
- `tests/system/test_virtual_workflow_suite_execution.py`

Documentation:

- `docs/sil_interactive_simulation_milestone_8_slice_4_implementation_plan.md`
- `docs/sil_interactive_simulation_milestone_8_slice_4_completion_record.md` —
  new after qualification
- `docs/sil_interactive_simulation_and_composable_workflows_plan.md`
- `README.md`

No `View.py`, `Controller.py`, `Model.py`, simulator, protocol, firmware, Pi,
fixture, journey, action, assertion, or page-driver file will be edited. If
implementation reveals that report-v1 lacks evidence already promised by the
manifest beyond the additive source identity, stop and record a separate
focused correction rather than weakening the join.

## Focused Validation

Run only targeted tests during this slice:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests/test_virtual_workflow_coverage.py `
  tests/test_virtual_workflow_report.py `
  tests/test_virtual_workflow_selection.py `
  tests/test_virtual_workflow_manifest.py `
  tests/test_virtual_workflow_contract_freeze.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests/system/test_virtual_workflow_coverage_execution.py `
  tests/system/test_virtual_workflow_suite_execution.py
```

Qualification uses a fresh one-child capability aggregate rather than rerunning
the full lifecycle portfolio:

```powershell
.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --capability execution.mixed_droplet_stream_lifecycle `
  --output-root verification_reports\suites `
  --seed 1 --speed-multiplier 1000

.\env\Scripts\python.exe tools\run_virtual_workflow.py `
  --coverage-from <fresh-mixed-mode-aggregate.json> `
  --output-root verification_reports\suites
```

Run the exact coverage replay emitted by the second command. Also evaluate one
retained Slice 3 aggregate that predates the source-tree fingerprint and verify
that it is retained and reported as non-current rather than accepted as fresh.
No visible Qt qualification is required for this offline evaluator, and the
full pytest suite remains deferred to Milestone 8 Slice 8.

## Risks and Rollback

- A coarse source identity could accept changed code or reject harmless
  documentation edits. Mitigation: version and test the canonical path scope,
  include all tracked/non-ignored execution and verification inputs, and fail
  closed on collection errors.
- Multiple retained retries could hide a failure. Mitigation: never choose a
  latest candidate implicitly; conflicting candidates are incomplete and all
  input references remain visible.
- A passing report could overstate UI coverage. Mitigation: join each required
  semantic action to the manifest-declared interaction surface and fail on a
  mismatch.
- Evidence age could accidentally become an automated schedule or gate.
  Mitigation: age is labelled informational and cannot affect classification;
  the operator invokes every run and evaluation explicitly.
- Generated results could pollute the tracked manifest. Mitigation: the
  evaluator has no manifest write path and tests hash the manifest before and
  after generation.

Rollback removes the coverage module and CLI selector, restores the previous
source identity fields and manifest policy marker, and removes the new tests
and docs. Existing reports remain valid report-v1 documents, aggregate-v1
evidence is unchanged, and no persisted experiment, MVC, simulator, protocol,
firmware, Pi, or hardware state requires migration.
