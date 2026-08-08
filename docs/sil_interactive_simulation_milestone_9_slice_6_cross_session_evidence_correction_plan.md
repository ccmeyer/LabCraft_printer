# Milestone 9 Slice 9.6 Cross-Session Evidence Correction Plan

Status: implementation authorized (2026-08-08)

## Problem

The Slice 9.6 lifecycle qualification and its exact replay both completed the
`authoritative_reload_resume_24_v1` workload at 24/24 wells, then failed while
assembling terminal evidence with `'int' object is not iterable`.

`merge_session_lifecycles()` predates the bounded simulator-dispense evidence
added in Slice 9.2. It assumes every lifecycle value is an iterable event
collection, but current observer snapshots also contain the integer metadata
fields `simulator_dispense_limit` and
`simulator_dispense_overflow_count`.

Retained failing aggregates:

- initial lifecycle aggregate SHA-256:
  `17f9d65006999187e3835f5ff613409464624e46a6427ce758bb302952140ca4`;
- exact replay aggregate SHA-256:
  `cecb988450e0142d39ae93c69d0e7c84012ff513a5a7527c24d8679e3e092127`.

## Call path

```text
session 1 ExecutionObserver lifecycle snapshot
+ session 2 ExecutionObserver lifecycle snapshot
→ merge_session_lifecycles
→ authoritative reload/resume terminal assertions
→ report-v1
```

The completed production execution and authoritative persistence are not
changed. This correction is limited to SIL evidence composition.

## Correction

1. Continue concatenating list/tuple lifecycle event collections in session
   order and add `application_session_id` only to mapping rows.
2. Validate each per-session simulator retention limit as a positive non-bool
   integer and expose the combined capacity as their sum.
3. Validate each overflow count as a nonnegative non-bool integer and expose
   the combined overflow count as their sum.
4. Require bounded metadata to be present in every session when it is present
   in any session. Reject unknown scalar lifecycle fields and malformed event
   collections rather than silently dropping them.
5. Preserve compatibility for older snapshots that contain only event
   collections and no bounded metadata.
6. Add focused unit tests for deterministic event attribution, combined
   limits, accumulated overflow, missing/malformed metadata, unknown scalars,
   and legacy snapshots.
7. Run the focused authoritative-evidence tests and the direct composed
   authoritative reload/resume success test.
8. Retain a passing direct report, write a correction completion record, and
   commit independently as `fix: merge bounded cross-session SIL evidence`.

## Files

Modify:

- `tools/virtual_workflows/authoritative_evidence.py`
- `tests/test_virtual_workflow_authoritative_evidence.py`

Add:

- this correction plan;
- `docs/sil_interactive_simulation_milestone_9_slice_6_cross_session_evidence_correction_record.md`.

The existing uncommitted Slice 9.6 implementation plan remains outside the
correction commit.

## Validation and rollback

Run:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_authoritative_evidence.py

.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_authoritative_reload_composed.py::test_authoritative_reload_composed_report_passes

git diff --check
```

After the correction commit, restart Slice 9.6 qualification from its first
matrix so all closeout evidence has the corrected source identity. Rollback
reverts only this merger/test/documentation commit; retained failed evidence
remains historical.
