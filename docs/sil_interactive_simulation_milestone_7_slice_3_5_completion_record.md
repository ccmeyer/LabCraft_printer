# Milestone 7 Slice 3.5 — Completion Record

Status: `complete — focused correction validated on 2026-08-06`

Baseline: `f8bba35b83593c5b4dfd7a70844c5463d1404f45`, plus the
intentionally uncommitted and validated Slice 3 worktree.

## Outcome

Slice 3.5 completed the bounded authoritative-evidence consolidation without
adding or migrating a workflow. No production MVC, action, page-driver,
fixture, registry, capability-manifest, report-schema, simulator protocol, Pi,
firmware, or hardware behavior changed.

Before Slice 4 planning, an approved focused correction made the existing
editable-copy name dialog's 640 px minimum persistent across Qt's modal layout
cycle. This is a View-only UI constraint: duplication still occurs only after
dialog acceptance and does not add a Controller, communications, simulator,
firmware, or hardware path.

`AuthoritativeBundleSnapshot` captures canonical design/plan/history,
eligibility, progress, resume, calibration, assignments, keys, audit rows, and
deterministic file inventory through read-only operations. It retains no live
Qt, Model, ExperimentModel, ExecutionPlan, or callback object. Composed editor
create/revision/reload assertions, legacy prepared/refinalized validation,
legacy authoritative reload boundaries, and legacy post-start locked-source /
editable-copy validation now consume the shared readers or snapshot facts.

`ActionSequenceExpectation` validates the complete explicit ledger window,
including harness milestones interleaved with UI actions. Its stable evidence
still reports only the required UI action sequence. The two editor payload
adapters delegate to one typed editor report builder and remain 12 lines each.

## Code Shape

Relative to the completed Slice 3 worktree:

- existing runtime consumer files lost 482 physical lines:
  `assertions.py` 106, `journeys.py` 60, `editor_scenarios.py` 284, and
  `scenarios.py` 32;
- the typed shared foundation added 633 physical lines:
  `authoritative_evidence.py` 465 and `editor_reporting.py` 168;
- the net runtime change is therefore +151 physical lines;
- `editor_prepared_revision_assertions()` is 169 lines when its reusable
  `checks` and assertion-group declarations are excluded, below the 180-line
  gate;
- `_editor_payload()` and `_editor_revision_payload()` are 12 lines each;
- all duplicate private CSV/hash/audit/runtime/directory reader definitions
  named in the plan are removed.

The proposed no-net-growth gate was amended to the measured consumer/shared
split. Reaching zero net growth would have required compressing the immutable
typed snapshot, deterministic inventory, comparison result, and report
contracts or deleting their fail-closed validation. The important per-workflow
result is a 482-line reduction in existing consumers and a single foundation
for later migrations rather than another scenario-family copy.

## Validation

Focused unit and authoritative-persistence set:

```text
89 passed in 5.94s
```

This included the new authoritative-evidence and editor-reporting tests,
assertion/composition/report/contract-freeze tests, and initial-plan,
authoritative-load, artifact-policy, progress, resume, and calibration-store
contracts.

Composed editor success, parity, and controlled-failure set:

```text
7 passed in 11.88s
```

Legacy editor, post-start lock/copy, authoritative reload, and controlled
failure set:

```text
11 passed in 19.57s
```

The composed create/finalize, prepared-revision, and authoritative-reload
post-refactor direct paths passed. One post-start direct run passed and a later
rerun reproduced the dialog-width failure described below; the focused
post-start success/failure tests remained stable. The composed create/finalize
and prepared-revision reports have exactly equal
`composed_report_contract_projection()` values to their fresh pre-refactor
references. The existing lifecycle tests validated the detailed legacy
reload/lock persistence contracts and failure retention.

`py_compile`, CLI help, and `git diff --check` passed. The complete pytest suite
was intentionally not run and remains deferred to final Milestone 7
validation.

The focused correction added a real `exec()` lifecycle regression. Its
validation passed as follows:

```text
30 passed in 1.65s
33 passed in 4.61s
```

The first set is the complete experiment-designer interlock module. The second
combines the virtual-workflow action tests with the post-start lifecycle success
and controlled-failure tests. A direct offscreen modal probe also reproduced
the pre-correction transition from a 640 px rendered dialog to a 502 px minimum
and then confirmed the corrected minimum remains 640 px through and after the
real modal event loop.

## Retained Evidence

Fresh baseline and post-refactor roots:

```text
verification_reports\milestone7-slice3-5-baseline
verification_reports\milestone7-slice3-5-post
```

The visible composed prepared-revision run and its exact emitted replay both
passed with ten assertions and the frozen action/screenshot contract:

```text
verification_reports\milestone7-slice3-5-visible\experiment_editor_prestart_rename_refinalize_v1\20260807T013912098258Z_composed
verification_reports\milestone7-slice3-5-visible\experiment_editor_prestart_rename_refinalize_v1\20260807T013924712868Z_composed
```

The pre-correction visible legacy post-start run failed because Qt reduced the
640 px dialog's `minimumWidth()` property to 502 px during modal layout. The
rendered dialog and name field were already 640 px and 618 px respectively;
the separate 480 px name-field minimum was also satisfied. Retained failure
evidence:

```text
verification_reports\milestone7-slice3-5-visible\experiment_editor_post_start_lock_v1\20260807T013849293715Z_f8bba35b8359
```

The focused correction's fresh visible run passed all nine assertions with no
errors or unexpected dialogs. Its copy evidence records dialog
actual/minimum widths of 640/640 px and name-field actual/minimum widths of
618/480 px:

```text
verification_reports\milestone7-slice3-5-dialog-correction-visible\experiment_editor_post_start_lock_v1\20260807T015234437382Z_f8bba35b8359
```

Two additional direct offscreen scenario attempts failed closed at the
existing Qt font-family precondition before application construction and are
not correction gates. The real offscreen modal probe and the offscreen pytest
lifecycle cases reached the corrected dialog and passed. The legacy report
still has no emitted replay command, and the legacy CLI seed mismatch remains
outside this correction.

## Risks And Rollback

Risk remains concentrated in SIL evidence capture, validation, and report
payload assembly, with one bounded production-View risk: future Qt layout
requests reapply existing minimum-width constraints to this dialog. No model
state, persistence, command, protocol, motion, pressure, timing, firmware, or
hardware behavior is affected. The main residual evidence risk is that future
lifecycle requirements need a new snapshot fact; add it only when a migrated
journey exercises it rather than turning the snapshot into a universal state
model.

Rollback only the Slice 3.5 hunks in `assertions.py`, `journeys.py`,
`editor_scenarios.py`, and `scenarios.py`; remove the two new runtime modules
and their tests; remove the focused `EditableCopyNameDialog.event()` constraint
hook and real-modal regression; and restore the Slice 3 README/roadmap wording.
Preserve all Slice 3 implementation, plans, tests, fixtures, manifests, and
retained evidence. No model, protocol, firmware, Pi, or hardware rollback is
required.

## Next Step

Review this record and create a separately approved Slice 4 plan for only the
soft stop/resume migration. Keep targeted tests per slice and run the complete
Python suite only at final Milestone 7 validation.
