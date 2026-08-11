# Milestone 8 Slice 6 — Bounded Seeded Editor Sequence Exploration

Status: complete after approved invalid-volume amendment (2026-08-07)

## Approved amendment and implementation finding

The legal generated path passes through the real editor. Qualification of the
illegal path is blocked by an existing, explicitly tested editor contract:
`ExperimentDesignDialog._on_finish()` automatically runs Optimize and Generate
when `_design_optimization_dirty` is true and then finalizes. The Refinalize
button remains enabled. This is covered by
`test_design_edit_marks_dirty_and_finish_reoptimizes` and is therefore not a
test-driver timing failure.

The retained `seed_101_illegal` diagnostic report is
`verification_reports/m8-s6-dev4/editor_prepared_guard_v1/20260808T000729685162Z_composed/report.json`
(SHA-256 `ca5b06a3a35a9566027a7cf94d4a9c05383a91a5b2be7cf77d34cb80ba9b7454`).
It fails closed before clicking because a dirty prepared design unexpectedly
exposes an enabled Refinalize action.

The operator approved the recommended amendment. Illegal sequences now create
a temporary invalid volume relationship through Qt, with printed volume above
final reaction volume. Finalize opens the production `Invalid volumes` warning;
the driver dismisses it through QTest and proves authoritative state unchanged
before restoring valid values and continuing. No production file was changed,
and the existing one-click reoptimization behavior remains intact.

## Contract

Add the manually invoked `editor_prepared_guard_v1` campaign. It generates one
legal and one intentionally illegal prepared-editor sequence for each frozen
seed `1, 7, 19, 42, 101`, using generator version
`editor-prepared-guard-v1`. Every sequence reuses the tracked prepared-editor
fixture and normal QTest controls, remains at or below 25 ledger actions, ends
prepared and runtime-inactive, and retains a hash-identified exact replay.

Illegal sequences attempt Refinalize exactly once while the editor contains
invalid printed/final volumes. That attempt passes only when the real warning
rejects finalization and authoritative files,
audit history, plan revision, modal state, and runtime activation remain
unchanged. The sequence then restores valid values, regenerates, refinalizes,
reloads, and proves normal recovery.

The campaign uses fresh Windows child processes and writes a hashed plan,
aggregate, summary, logs, and report-v1 references beneath
`verification_reports/exploration`. It is separate from registered capability
coverage. Pi, scheduling, physical hardware, protocol, firmware, production
MVC, simulator changes, tracked-fixture changes, fault injection, repetition,
baselines, and comparisons are excluded.

## Implementation and gates

1. Add typed deterministic sequence generation, state transitions, hashes, and
   catalog/dry-run validation.
2. Generalize prepared-editor automation without changing its fixed default.
3. Add the dynamic journey, safeguard/recovery assertions, and report evidence.
4. Share bounded child execution between matrix and exploration aggregation.
5. Add CLI selection, exact replay, and fail-closed aggregate validation.
6. Run focused unit/system tests, the ten-child offscreen campaign and replay,
   and visible `seed_7_legal` and `seed_101_illegal` runs and replays.
7. Update README, roadmap, and the completion record only after qualification.

The complete pytest suite remains deferred to Milestone 8 Slice 8. Rollback
removes the exploration selector/catalog/runner/dynamic journey and restores
the fixed editor and matrix child-runner organization; no persisted-data or
hardware migration is required.
