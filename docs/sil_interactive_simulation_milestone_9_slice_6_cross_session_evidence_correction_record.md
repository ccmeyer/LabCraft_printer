# Milestone 9 Slice 9.6 Cross-Session Evidence Correction Record

Status: complete (2026-08-08)

## Outcome

The deterministic Slice 9.6 lifecycle blocker is corrected. Cross-session
execution evidence now distinguishes ordered lifecycle event collections from
the bounded integer metadata introduced in Slice 9.2.

The correction is confined to SIL evidence composition. No production MVC,
simulator behavior, firmware, protocol, fixture, report schema, matrix schema,
catalog, or operator workflow changed.

## Root cause and correction

The authoritative reload/resume journey completed 24/24 wells in both the
initial lifecycle qualification and its exact replay, then
`merge_session_lifecycles()` attempted to iterate the integer
`simulator_dispense_limit`. Both runs failed report assembly with
`'int' object is not iterable`.

The merger now:

- concatenates list/tuple event collections in session order;
- retains application-session attribution on mapping rows without mutating
  source snapshots;
- validates positive non-bool per-session retention limits and sums their
  combined capacity;
- validates nonnegative non-bool overflow counts and sums them;
- rejects incomplete bounded metadata, malformed event collections, and
  unknown scalar fields;
- remains compatible with legacy event-only lifecycle snapshots.

## Validation

Focused evidence tests:

```powershell
.\env\Scripts\python.exe -m pytest -q `
  tests\test_virtual_workflow_authoritative_evidence.py
```

Result: `11 passed in 0.10s`.

Composed reload/resume success:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_authoritative_reload_composed.py::test_authoritative_reload_composed_report_passes
```

Result: `1 passed in 7.37s`; 25 existing Qt deprecation warnings.

Direct/composed stable-oracle parity:

```powershell
.\env\Scripts\python.exe -m pytest -q --run-sil-lifecycle `
  tests\system\test_virtual_workflow_authoritative_reload_composed.py::test_authoritative_reload_composed_matches_direct_stable_oracle
```

Result: `1 passed in 14.19s`; 45 existing Qt deprecation warnings.

Retained fresh CLI evidence:

- report:
  `verification_reports/corrections/authoritative_reload_resume_24_v1/20260808T191926376295Z_composed/report.json`;
- report SHA-256:
  `aa3e7e95250a89c033a83c0c8e8d017dc9181cb38851ee2f6b9df7a65bfac2f7`;
- classification: `pass`;
- completions: `24 / 24`;
- application sessions: `2`;
- required assertions: `12 / 12 pass`;
- terminal plan: `completed` with completion count `24`;
- session-1 completed pairs were not replayed;
- unexpected dialogs and workflow errors: `0`.

The two historical failing lifecycle aggregates remain retained with SHA-256
values:

- `17f9d65006999187e3835f5ff613409464624e46a6427ce758bb302952140ca4`;
- `cecb988450e0142d39ae93c69d0e7c84012ff513a5a7527c24d8679e3e092127`.

## Risk and rollback

The merger now fails earlier and more clearly if a future observer publishes
an unregistered scalar lifecycle field or only part of its bounded metadata.
Combined retention capacity is the sum of validated instance-local limits;
combined overflow is the sum of per-session overflows, so downstream evidence
continues to fail closed when any observer overflowed.

Rollback reverts this correction commit. Historical reports require no
migration or deletion. Slice 9.6 qualification must restart from its first
matrix after this correction is committed so every closeout artifact shares
the corrected source identity.
