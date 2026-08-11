# Milestone 8 Slice 4 — Completion Record

Status: complete (2026-08-07)

## Delivered behavior

The operator can now pass one or more explicit Slice 3 `aggregate.json` files
to `--coverage-from`. The Qt/application-import-free evaluator validates every
aggregate, selection plan, child report, and transitive hash before joining the
evidence to the tracked capability manifest.

The `labcraft.sil_capability_evaluation` v1 JSON and deterministic text summary
record in-scope and out-of-scope capabilities, exact inputs and hashes,
required scenarios/assertions/actions/layers, expected and observed interaction
surfaces, observable sources, evidence paths, informational age, target source
identity, five-state decisions, reasons, counts, and exact replay. Generated
evidence writes only new contained directories below
`verification_reports/suites/coverage`; it cannot update the manifest.

Report-v1 source metadata now additively includes a versioned source-tree
fingerprint. Its canonical scope covers Git-tracked and non-ignored execution
and verification inputs, excludes documentation/evidence/cache/runtime paths,
and records only the aggregate digest and metadata—not file contents. This
allows the intentionally uncommitted milestone worktree to match its evidence
while still detecting later executable-source changes. Report-v1 and
aggregate-v1 schema versions remain unchanged.

The manifest action catalog now declares an interaction surface for all 55
semantic actions. Coverage fails on an observed surface mismatch, so direct
Model, Controller, simulator, or harness work cannot be reported as normal-UI
coverage. The static policy marker records Slice 4 implementation while
`generated_evidence_updates_manifest` remains false.

No production View, Controller, Model, simulator, protocol, firmware, Pi, or
hardware behavior changed. No scheduler, matrix, seeded exploration, cleanup,
or automatic test trigger was introduced.

## Retained qualification evidence

- Fresh mixed-mode capability aggregate:
  `verification_reports/suites/capability__execution.mixed_droplet_stream_lifecycle/20260807T231220344362Z_37e8cdc1-3ce/aggregate.json`
  — SHA-256 `68c88b8e0a686483db22b95f5dd6c6b5cb562a105c58a9e0c2da3631e4ce4f66`.
- Source-current coverage evaluation:
  `verification_reports/suites/coverage/20260807T231232424208Z_f1c614ab6a5f/coverage.json`
  — SHA-256 `a27ca22916dcdde54c767ce11abe35b0a2475be61acea3df71f32c4610a46a9c`.
- Exact coverage replay:
  `verification_reports/suites/coverage/20260807T231237625548Z_72dc80d38b50/coverage.json`
  — SHA-256 `ac65dc1965bfee81d07f1bf73cecc827182239b0334a82ef73457a67aca365c1`.
- Retained pre-fingerprint evidence evaluation:
  `verification_reports/suites/coverage/20260807T231241713616Z_4a20296161cd/coverage.json`
  — SHA-256 `76fdeabc1b431c6eb732b7643cc6f7fee70ba9a2531686f742ff9af71b38221a`.

The fresh evaluation and replay each classified the explicitly selected
`execution.mixed_droplet_stream_lifecycle` capability `pass` with source
fingerprint
`56409ac0a5c3ed436d7a52de190e75c66b582821a575704f2e354ba48754b13b`.
The older aggregate remained valid aggregate-v1 evidence but had no source-tree
fingerprint; its evaluation classified the capability `incomplete` and returned
the expected completed-non-pass exit code 2 rather than treating report
presence as fresh coverage.

## Focused validation

The final unit/contract gate passed 138 tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests/test_virtual_workflow_coverage.py `
  tests/test_virtual_workflow_report.py `
  tests/test_virtual_workflow_selection.py `
  tests/test_virtual_workflow_manifest.py `
  tests/test_virtual_workflow_contract_freeze.py
```

The real-process gate passed two tests covering a high-speed standard suite,
hashed coverage evaluation, deliberately incomplete broader portfolio claims,
current source identity, and unchanged direct/suite behavior:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests/system/test_virtual_workflow_coverage_execution.py `
  tests/system/test_virtual_workflow_suite_execution.py
```

The standard system regression was run with pytest temporary data in a
dedicated OS-temp directory. An initial workspace-local `%TEMP%` attempt was
correctly rejected by the existing SIL safety guard because simulation session
data may not overlap the repository; no safety bypass or production change was
made.

The complete pytest suite was intentionally not run and remains deferred to
Milestone 8 Slice 8.

## Risks and rollback

The main residual risk is incorrect source-scope classification. Focused tests
prove that code, fixture, manifest, and untracked executable inputs change the
fingerprint while documentation, reports, and caches do not; collection errors
fail closed as incomplete evidence. Ambiguous conflicting reports are never
resolved by silently choosing the latest run.

Rollback removes `coverage.py` and the CLI selector, restores the prior source
metadata and manifest policy/action fields, and removes the new tests/docs.
Existing report-v1 and aggregate-v1 files remain readable, generated coverage
artifacts need not be deleted, and no persisted experiment or hardware state
requires migration.
