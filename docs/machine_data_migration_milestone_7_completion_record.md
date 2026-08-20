# Machine Data Migration Milestone 7 Completion Record

> Current correction: rc.2 first-start qualification passed, but its enrolled
> protected update failed safely before Git. The
> [rc.3 correction plan](machine_data_migration_milestone_7_rc3_correction_plan.md)
> now owns correction qualification, attended recovery, publication, and
> rollout.

Status: `in_progress` — Windows and unattended Pi gates passed; attended,
tag-dependent, publication, and rollout gates remain.

Started: 2026-08-20

Current target release: `v1.3.0-rc.3`

Parent documents:

- [Machine Data Migration and Location Safety Plan](machine_data_migration_and_location_safety_plan.md)
- [Milestone 7 Implementation Plan](machine_data_migration_milestone_7_implementation_plan.md)
- [Machine Data Update and Rollback Runbook](machine_data_update_and_rollback_runbook.md)
- [Release Process](release_process.md)

## Current boundary

The verified M1-M6 branch has been merged into local `main`, and the untagged
rc.2 release commit is being constructed there. This record does not claim
that exact-commit Windows, target-Pi, attended hardware, local-tag,
publication, or rollout gates have passed. No `v1.3.0-rc.2` tag exists.

Physical Camera-route approval, firmware flashing, HIL, release publication,
and fleet rollout remain separate attended or operator-authorized gates.

## Slice 0 traceability audit

Every required parent-plan scenario has direct existing automated coverage.
No new runtime or test-code change is justified at candidate construction.
The exact collected node IDs and results will replace `pending execution` after
the focused gate runs.

| Requirement | Direct evidence | Status |
| --- | --- | --- |
| Exact rc.6 and rc.1 layouts | `test_machine_data_migration.py::test_historical_catalog_recognizes_both_reviewed_source_cohorts`; `test_machine_data_bootstrap.py::test_first_start_migrates_activates_and_reuses_from_second_checkout`; compatibility catalog tests | Mapped; pending execution |
| Machine-specific non-preset Camera | `test_machine_data_migration.py::test_custom_camera_is_not_mistaken_for_historical_camera`; Camera confirmation and authorizer tests | Mapped; pending execution |
| Camera-only/full-preset similarity | `test_machine_data_verification.py::test_camera_confirmation_and_preset_service_rules_fail_closed`; `test_machine_data_bootstrap_dialog.py::test_preset_like_candidate_surfaces_independent_service_requirement` | Mapped; pending execution |
| Folder layouts and ZIP | parametrized explicit shallow-layout test; missing/ambiguous layout test; selected-ZIP semantic-equality test | Mapped; pending execution |
| Duplicate/conflicting candidates | candidate comparison and bootstrap-dialog duplicate/conflict tests | Mapped; pending execution |
| Missing/malformed/partial data | invalid required/safety and incomplete calibration tests; archive and persisted-evidence parser tests | Mapped; pending execution |
| Existing canonical and new checkout | existing-canonical inspection, second-checkout bootstrap, and deployment-anchor reopen tests | Mapped; pending execution |
| Permission/disk/lock/interruption | insufficient-space, lock-contention, migration-recovery, transaction-fault, and update-recovery tests | Mapped; pending execution |
| Verification cancellation/revocation | bootstrap worker cancellation, cancelled transaction, target authorizer, and revoked legacy-export tests | Mapped; pending execution |
| Named/rack/plate history | named-location transaction and rack-pair/plate-quartet aggregate transaction tests | Mapped; pending execution |
| Guarded edits | safety-policy, preview, guarded-workflow, capture-precondition, and adapter tests | Mapped; pending execution |
| Update preservation | preservation, recovery, deployment-anchor, updater, window, and app-launch tests | Mapped; pending execution |
| Legacy rollback/re-upgrade | compatibility export, exact return, Camera conflict, and keep-canonical tests | Mapped; pending execution |
| Simulation/no hardware | App bootstrap ordering, safe construction, send-path guards, Pi hardware proof, and contained SIL | Mapped; pending execution |
| Release metadata/tag/bundle | release validator, candidate-series update check, bundle, and tag-validation tests | Mapped; pending execution |

## Read-only target-Pi Slice 0 preflight

On 2026-08-20, authorized read-only SSH inspection of
`labcraft@192.168.0.33` recorded:

- clean `update_bug_fix` checkout at `0ee3e50a`;
- `VERSION` `v1.3.0-rc.1`;
- no running `FreeRTOS-interface/App.py` process;
- no `LABCRAFT_MACHINE_DATA_ROOT` environment override;
- Desktop backup wrapper present for the rc.1 cohort;
- 148 backed-up `local/` files totaling 746,658 bytes;
- backup and live `Locations.json` hashes matched at truncated SHA-256
  `3e5b4de9...c5f3c7d02`;
- backup and expected Settings evidence matched at truncated SHA-256
  `69a5f4b9...a7646a`;
- hardware profile `current`; and
- resolved default external root below Qt application-local data, outside the
  Git checkout.

The exact Camera value, paths, and checklist state are retained only in ignored
private evidence. The prior external-drive backup is operator-attested but was
not mounted during this read-only inspection; it must be refreshed and opened
again before attended qualification.

## Candidate implementation

Working-tree changes prepared on local `main` on 2026-08-20:

- `VERSION` advanced to `v1.3.0-rc.2`;
- release index points to rc.2 while stable remains `v1.2.0`;
- rc.2 manifest declares the exact M6 machine-data preservation contract with
  `transition: none`;
- lineage is rc.1 to rc.2 with reviewed rollback target `v1.2.0`;
- the explicit v1.3 firmware requirement is retained for direct rc.6/v1.2.0
  upgrades while documenting byte identity with rc.1; and
- changelog/release notes cover external data, migration, verification,
  history, guarded changes, update preservation, support-guided rollback, and
  firmware pairing.

No application runtime, firmware, protocol, motion, pressure, or updater source
changed in this candidate-construction slice. Qualification found and corrected
one Pi SIL shell mount-order gap, with one focused regression assertion and
operator documentation.

## Windows validation

Status: `passed` for exact candidate
`5f54a4a174cd50f145e1bfa98aa61535b7aa59e9` (tree
`4dc25df5a7b0b206dc40f0bce8c75d085c2d2bc0`).

Pre-candidate checks on the same application/release tree passed 570 focused
tests with one skip, release-metadata and release-JSON validation, firmware
identity checks, and one contained 96/96 SIL journey. The discarded first
pytest attempt executed no test bodies because the sandbox denied its default
temporary directory; the successful rerun used a unique OS-temporary base
outside the repository. Final full-suite and clean-commit evidence must be
collected again against the exact release commit.

The initial target-Pi sandbox attempt found that the private `/tmp` mount hid a
candidate checkout located below `/tmp`. Candidate execution stopped before
Python, the application, or hardware access. The Pi SIL shell now re-binds only
the candidate repository read-only after mounting the private `/tmp`, then
overlays only its evidence output writable. A regression assertion fixes that
mount order. The candidate was re-frozen and every exact-commit gate was rerun.

Final exact-candidate evidence:

- focused M1-M7 group: 592 passed, 1 skipped, 130 warnings in 93.37 seconds;
- complete suite: 5,402 passed, 156 skipped, 605 warnings in 343.14 seconds;
- changed Python regression module compiled and executed successfully;
- release metadata validation and parsing of every release JSON passed;
- contained Windows SIL completed 96/96 with exit code 0;
- `git diff --check`, clean-worktree, no-rc.2-tag, and no-firmware-diff checks
  passed;
- firmware artifact remained 343,064 bytes, Git blob
  `526bc6ffbe980bbbebc67a8cf4b1db04ec8f263a`, SHA-256
  `EDA070CE...B0D5884`; and
- qualification bundle verified as complete at 52,075,353 bytes and SHA-256
  `B135BE8D...7EB408ED`.

## Target-Pi unattended qualification

Status: `passed` for the unattended/no-hardware boundary.

Final workspace: `/tmp/labcraft-m7-qualification.nqzNos`.

- The transferred bundle hash, candidate commit, and peeled rc.6, v1.2.0, and
  rc.1 commits matched the Windows record.
- The candidate was detached and clean; the verified production venv was
  exposed only through an ignored disposable shim.
- Focused groups passed 199 migration/bootstrap, 101 transaction/guard/routing,
  and 275 update/rollback/release tests.
- A verbose 33-case matrix independently showed both exact source cohorts,
  non-preset Camera preservation, supported folder/ZIP layouts, malformed and
  preset-like failure modes, cancellation, target revocation, transactional
  recovery, backup failure, exact return, and synthetic Camera-conflict paths.
- Bubblewrap/strace SIL completed 96/96. Its report bound commit `5f54a4a1`,
  showed a clean worktree, private `/dev`, unshared network, read-only root,
  simulation-only interfaces, and zero forbidden hardware-device matches.
- Production Pi HEAD `0ee3e50a`, tree `5db5adb4`, VERSION, interpreter/prefix,
  clean status, and no-App-process state matched before and after. The default
  production machine-data root was not read or written.
- The Pi-side evidence manifest verified 48 files. The archive contained 63
  safe relative members, excluded the venv, and matched locally at SHA-256
  `09D68B3C...0E98A0B7` after SCP.

The superseded diagnostic workspace
`/tmp/labcraft-m7-qualification.3Z7R15` remains retained. Its failed SIL
attempt exposed the private-`/tmp` visibility gap and reached neither Python
nor hardware; none of its results are counted as final qualification evidence.

## Attended designated-machine qualification

Status: `in_progress` — attended preflight, candidate installation,
cancellation, source review, migration, activation, and genesis enrollment
passed on `5f54a4a1`; a release-blocking bootstrap UI correction was then found.

On LC-001, operator `Conary-Codex` confirmed motor inhibition, clear motion
envelope, immediate emergency-stop access, and recovery understanding. The
Desktop and disconnected external-drive copies each matched the deployed rc.1
`local/` and `VERSION` exactly. The clean production checkout fast-forwarded
from `0ee3e50a` to `5f54a4a1` without relaunch; all 148 legacy files and
746,658 bytes remained unchanged. A first-start cancellation produced only the
bootstrap startup line, created no canonical root, and constructed no normal
MVC/hardware components.

The operator selected the verified Desktop rc.1 wrapper and reviewed all nine
saved locations and three plates without an unexplained discrepancy. The
candidate was assigned to LC-001, had complete CalibrationMemory, had no full
preset or Camera-preset match, and classified all 136 legacy `update_logs/**`
entries through the reviewed archive-only ownership rule. Activation then:

- reopened a verified 149-member source ZIP;
- proved all 11 canonical configuration/calibration files byte-identical and
  semantically equal to the selected source;
- retained the expected Locations and Settings hashes;
- authorized 12 targets with Camera recorded as custom/non-preset;
- began configuration history at sequence zero; and
- created a genesis deployment anchor for rc.2 commit `5f54a4a174cd`.

The main app opened under motor inhibition, its captured startup log contained
no textual motion-command or error marker, and the operator closed it normally.
Private evidence retains exact coordinates, UUIDs, full hashes, receipts, and
operator attestations.

Attended use also exposed two connected human-interface defects before any
motion qualification:

1. `App.py` supplied the direct checkout `local/`, while the dialog classified
   that path using repository-root semantics and attempted to inspect
   `local/local`. The failure was safe and occurred before migration/hardware,
   but the offered source was unusable without browsing to another wrapper.
2. Requiring operators to retype displayed Camera coordinates added
   transcription risk without independent physical knowledge. Operators would
   normally copy the displayed value rather than validate it independently.

The correction treats the prefilled path as a direct local candidate, displays
Camera coordinates read-only from immutable candidate evidence, requires a
dedicated preserve-exactly approval, and clears approvals when the candidate
changes. Candidate `5f54a4a1` and all exact-candidate release evidence are now
historical/superseded for tagging. Its on-machine migration evidence remains
valid and must not be removed or rewritten. A corrected candidate must pass
affected Windows/Pi/release gates and reach this enrolled machine through the
authorized M6 update path; direct Git mutation is no longer permitted.

The correction is frozen as exact candidate
`d59f73be498b695db47872a4b7a01bb95ded2d8e`. Exact-commit Windows
qualification passed 571 tests with one skip in the M1-M7 focused group and
5,403 tests with 156 skips in the complete suite. Python compilation,
release-metadata validation, release-JSON parsing, `git diff --check`, clean
worktree, no-rc.2-tag, no-firmware-diff, and a contained 96/96 SIL run also
passed. The verified 52,083,845-byte transport bundle has SHA-256
`B0D151E5...185BB6C1`.

The affected target-Pi group passed 196 migration/bootstrap/UI tests in the
detached candidate checkout. Contained Pi SIL completed 96/96 and independently
proved private `/dev`, unshared network, read-only root and repository, and
zero forbidden hardware matches. Its 3,393,454-byte evidence archive has
SHA-256 `B38B738A...7DA87CC` and binds source commit `d59f73be`. Production
postflight remained clean at `5f54a4a1`, with no app process and the original
genesis deployment anchor still intact. Two preliminary disposable clones
stopped before Python when qualification commands confused annotated tag
objects with peeled commits; both were retained, the assertion was corrected,
and neither production nor hardware was reached.

No firmware, protocol, Controller, Model, communication, motion, pressure,
timing, production checkout, or canonical machine-data file changed during
the correction or its isolated qualification. The corrected enrolled-machine
update cannot start while the candidate is untagged: M6 deliberately resolves
and verifies a release tag and has no commit-only bypass. Direct Git mutation
remains prohibited. Creating the final local `v1.3.0-rc.2` tag therefore
remains the explicit next authorization/pre-tag decision.

That rc.2 tag was subsequently created locally and verified without being
pushed. The attended enrolled-machine update then stopped before Git with
`source_binding_mismatch`: rc.2's app-generated command recorded source commit
`5f54a4a174cd`, while the updater resolved the same `HEAD` as full commit
`5f54a4a174cd50f145e1bfa98aa61535b7aa59e9` and compared them literally.
No update transaction directory was created. Read-only postflight proved the
production checkout remained clean at the same commit and that the active
pointer, genesis deployment anchor, and all protected machine-data bytes were
unchanged. The updater and launcher logs are retained in the external update
history; the operator left the error window open for evidence preservation.

Because the immutable rc.2 tag contains both the short app binding and the
literal full updater comparison, it cannot safely complete the next protected
update or validate a full target anchor after relaunch. It will not be moved or
retargeted. `v1.3.0-rc.3` supersedes it with full new bindings, exact
compatibility for only rc.2's 12-lowercase-hex historical prefix, full new
transaction/anchor evidence, and a narrowly gated attended recovery launcher.
The implementation and qualification sequence is recorded in the linked rc.3
correction plan.

The rc.3 correction code and release metadata then passed the final Windows
pre-commit gates: 602 focused tests with one skip, 5,430 complete-suite tests
with 156 skips, contained SIL at 96/96, changed-file compilation, release
metadata/JSON validation, static diff checks, and unchanged firmware SHA-256
`EDA070CE...B0D5884`. The candidate remains untagged and has not changed
LC-001. Its exact commit and disposable Pi results are pending.

No-command probe, audit/restore, firmware provenance or flash, SAFE/HIL, and
the machine-specific Camera route remain pending.

## Local tag, updater, and rollback qualification

Status: rc.2 tag/same-version discovery passed; rc.2-to-corrected-target apply
exposed the fail-safe source-binding defect. rc.3 tag-dependent qualification
is pending.

Record peeled tag commit, metadata tag validation, release-aware bundle hash,
exact rc.6/rc.1 old-updater lanes, offline equivalence, unchanged return, and
synthetic Camera-conflict recovery here.

## Publication and rollout

Status: not authorized.

Record tag/branch publication order, remote refs, controlled public-tag result,
rc.6 pilot, rc.1 pilot, evidence reviews, fleet batches, and final decision
here.

## Evidence

Private evidence root:
`verification_reports/machine_data_m7/`

No private evidence is tracked by Git. Final archives require a Pi-side and
post-transfer checksum match before their truncated hash is recorded here.

Final ignored evidence roots:

- `verification_reports/machine_data_m7/5f54a4a174cd50f145e1bfa98aa61535b7aa59e9/`;
- retrieved Pi SIL archive SHA-256 `4E4B6C16...9804C8C8`; and
- retrieved unattended archive SHA-256 `09D68B3C...0E98A0B7`.

## Open gates

- Complete exact-candidate Windows and disposable-Pi qualification for rc.3.
- Authorize and create the immutable local `v1.3.0-rc.3` tag; do not push it
  before the required tag-dependent and attended recovery gates pass.
- Apply rc.3 to enrolled LC-001 through the narrow attended rc.2 recovery mode
  and verify preservation, full target anchor, and manual reopen evidence.
- Private operator, rc.6 pilot, rc.1 pilot, fixtures, and Camera-route approval.
- Attended designated-machine migration, firmware, HIL, and Camera route.
- Local tag and exact legacy updater/rollback qualification.
- Release publication and staged rollout.

## Document change log

| Date | Change |
| --- | --- |
| 2026-08-20 | Implemented the rc.3 full-commit binding, exact rc.2 prefix compatibility, candidate-side recovery updater, exact-evidence rc.3 genesis enrollment, release metadata, and runbook; final Windows gates passed 602 focused/1 skipped, 5,430 full/156 skipped, and 96/96 contained SIL. |
| 2026-08-20 | Recorded the immutable rc.2 tag and fail-safe attended `source_binding_mismatch`, proved no Git/protected-data mutation, and began the rc.3 full-commit compatibility and attended recovery correction plan. |
| 2026-08-20 | Froze correction candidate `d59f73be`; passed exact-commit Windows focused/full/static/release/SIL and affected target-Pi focused/private-device SIL gates; proved production remained unchanged; stopped the enrolled update at the intentional release-tag boundary. |
| 2026-08-20 | Recorded passing attended backup/install/cancel/review/migration/activation/genesis gates on LC-001, then superseded `5f54a4a1` for release after its prefilled source failed closed and manual Camera transcription was judged unsafe; began the direct-source/read-only-Camera correction and required affected requalification. |
| 2026-08-20 | Created the in-progress completion record, closed the software traceability audit without a code change, recorded sanitized read-only Pi preflight evidence, and documented the untagged rc.2 candidate changes and remaining gates. |
| 2026-08-20 | Recorded the local `main` integration boundary and the passing pre-candidate focused, metadata, firmware-identity, and contained-SIL checks without claiming the exact-commit gate. |
| 2026-08-20 | Recorded and corrected the Pi SIL private-`/tmp` visibility gap; the failed attempt reached neither Python nor hardware, and exact-candidate qualification restarted. |
| 2026-08-20 | Recorded final candidate `5f54a4a1`, passing Windows focused/full/static/SIL gates, passing fresh target-Pi focused/cohort/private-device SIL gates, unchanged production state, and the independently rechecked evidence archives; retained attended/tag/publication/rollout gates. |
